"""Shared utilities for SamplerPrep."""

import json
import os
import select
import struct
import subprocess
import sys
import termios
import tty
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import questionary
from questionary import Choice

EXT_RAW = ".RAW"
EXT_OTHER = [".WAV", ".AIF", ".MP3", ".MP4", ".OGG", ".M4A"]


def unzip(source_filename, dest_dir):
    zipfile.ZipFile(source_filename).extractall(dest_dir)


def dlfile(url, filename=""):
    try:
        f = urlopen(url)
        if filename == "":
            filename = os.path.basename(url)
        with open(filename, "wb") as local_file:
            local_file.write(f.read())
    except HTTPError as e:
        print_step(f"HTTP Error: {e.code} {url}")
    except URLError as e:
        print_step(f"URL Error: {e.reason} {url}")


def find_files(path, extensions):
    matches = []
    for root, dirnames, filenames in os.walk(path, topdown=False):
        for filename in filenames:
            if filename.startswith("."):  # skip macOS hidden / AppleDouble files
                continue
            _, ext = os.path.splitext(filename)
            if ext.upper() in extensions:
                p = os.path.join(root, filename)
                if "__MACOSX/" not in p:
                    matches.append(p)
    return matches


def pick_subfolder(base_path: Path) -> Path:
    """If base_path has immediate subdirectories, offer a picker; otherwise return it as-is."""
    subdirs = sorted(d for d in base_path.iterdir() if d.is_dir())
    if not subdirs:
        return base_path
    choices = [Choice(title=d.name, value=d) for d in subdirs]
    choices.append(Choice(title=f"All files in {base_path.name}/", value=base_path))
    return questionary.select("Select source folder:", choices=choices).ask()


def pick_files(files: list[str]) -> list[str]:
    """Checkbox so the user can deselect files before processing.

    Skipped when there is only one file. Returns selected subset.
    """
    if len(files) <= 1:
        return files
    choices = [questionary.Choice(title=Path(f).name, value=f, checked=True) for f in files]
    selected = questionary.checkbox("Select files to process:", choices=choices).ask()
    return selected or []


def print_step(s):
    sys.stdout.write(f">>> {s}\r\n")
    sys.stdout.flush()


def load_config(path):
    return json.loads(Path(path).read_text())


def load_dotenv(path=".env"):
    env = {}
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env


def getch():
    """Read one keypress in raw mode. Returns bytes; arrow keys return 3-byte sequences."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.buffer.read(1)
        if ch == b"\x1b":
            ch2 = sys.stdin.buffer.read(1)
            if ch2 == b"[":
                ch3 = sys.stdin.buffer.read(1)
                return b"\x1b[" + ch3
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def getch_timeout(timeout=0.1):
    """Like getch() but returns None if no key is pressed within `timeout` seconds."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return None
        ch = sys.stdin.buffer.read(1)
        if ch == b"\x1b":
            ch2 = sys.stdin.buffer.read(1)
            if ch2 == b"[":
                ch3 = sys.stdin.buffer.read(1)
                return b"\x1b[" + ch3
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def convert_file(source_file, target_file, device, overwrite, normalize=False):
    """Convert source_file to target_file using device's ffmpeg spec."""
    spec = device["ffmpeg"]
    cmd = [
        "ffmpeg",
        "-i",
        source_file,
        *(["-y"] if overwrite else []),
        "-f",
        spec["format"],
        "-ac",
        str(spec["channels"]),
        "-loglevel",
        "error",
        "-stats",
        "-ar",
        str(spec["sample_rate"]),
        "-acodec",
        spec["codec"],
        *(["-map_metadata", "-1"] if spec.get("strip_metadata") else []),
        *(["-af", "loudnorm=I=-16:TP=-1:LRA=11"] if normalize else []),
        target_file,
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


def ask_int(prompt, default, min_val, max_val):
    """Prompt for an integer in [min_val, max_val], re-prompting on bad input."""
    while True:
        raw = questionary.text(f"{prompt} [{default}]:").ask()
        if raw is None:
            return default
        if raw.strip() == "":
            return default
        try:
            v = int(raw.strip())
            if min_val <= v <= max_val:
                return v
        except ValueError:
            pass
        print_step(f"⚠  Enter a whole number between {min_val} and {max_val}")


def find_mounted_volumes():
    """Return sorted list of directories under /Volumes."""
    volumes = Path("/Volumes")
    if not volumes.is_dir():
        return []
    return sorted(p for p in volumes.iterdir() if p.is_dir())


_RSYNC_EXCLUDE = [
    "--exclude=.DS_Store",
    "--exclude=._*",
    "--exclude=.Spotlight-V100",
    "--exclude=.Trashes",
    "--exclude=.DocumentRevisions-V100",
    "--exclude=.TemporaryItems",
    "--exclude=.fseventsd",
]


def run_rsync(src, dst, extra_flags):
    """Run rsync from src/ to dst/ with extra_flags."""
    cmd = ["rsync", "-av", "--progress"] + _RSYNC_EXCLUDE + extra_flags + [f"{src}/", f"{dst}/"]
    result = subprocess.run(cmd)
    # Exit code 23 = partial transfer due to unreadable source entries (e.g. macOS
    # system dirs on the destination volume). Files we care about were transferred.
    if result.returncode not in (0, 23):
        raise subprocess.CalledProcessError(result.returncode, cmd)


def freesound_search(query, api_key, page=1, page_size=15):
    """Return parsed JSON from the Freesound text-search endpoint."""
    params = urlencode(
        {
            "query": query,
            "token": api_key,
            "fields": "id,name,duration,tags,license,previews",
            "page": page,
            "page_size": page_size,
        }
    )
    url = f"https://freesound.org/apiv2/search/text/?{params}"
    with urlopen(url) as r:
        return json.loads(r.read().decode())


def download_freesound_sounds(sounds, dest_folder, api_key) -> list[str]:
    """Download HQ-MP3 previews for each selected sound into dest_folder.

    Returns the list of downloaded file paths as strings.
    """
    dest_folder.mkdir(parents=True, exist_ok=True)
    downloaded = []
    for s in sounds:
        url = s["previews"]["preview-hq-mp3"]
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in s["name"])[:40]
        filename = dest_folder / f"{s['id']}_{safe_name}.mp3"
        req = Request(url, headers={"Authorization": f"Token {api_key}"})
        print_step(f"Downloading: {s['name']}")
        with urlopen(req) as r, open(filename, "wb") as f:
            f.write(r.read())
        downloaded.append(str(filename))
    return downloaded


# ── WAV cue-chunk utilities ───────────────────────────────────────────────────


def read_wav_info(wav_path: Path) -> dict:
    """Parse key fields from a WAV file's RIFF headers.

    Returns dict with keys: sample_rate, channels, bits_per_sample, num_samples.
    Values are 0 if the file is not a valid WAV.
    """
    result = {"sample_rate": 0, "channels": 0, "bits_per_sample": 0, "num_samples": 0}
    data = Path(wav_path).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return result
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        chunk_size = struct.unpack_from("<I", data, pos + 4)[0]
        if chunk_id == b"fmt ":
            result["channels"] = struct.unpack_from("<H", data, pos + 10)[0]
            result["sample_rate"] = struct.unpack_from("<I", data, pos + 12)[0]
            result["bits_per_sample"] = struct.unpack_from("<H", data, pos + 22)[0]
        elif chunk_id == b"data":
            bpf = result["channels"] * (result["bits_per_sample"] // 8) if result["channels"] else 0
            result["num_samples"] = chunk_size // bpf if bpf else 0
            break
        pos += 8 + chunk_size + (chunk_size % 2)
    return result


def read_wav_cues(wav_path: Path) -> list[int]:
    """Return list of sample offsets from a WAV cue  chunk, or [] if absent."""
    data = Path(wav_path).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return []
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        chunk_size = struct.unpack_from("<I", data, pos + 4)[0]
        if chunk_id == b"cue ":
            num_cues = struct.unpack_from("<I", data, pos + 8)[0]
            offsets = []
            for i in range(num_cues):
                base = pos + 12 + i * 24
                offsets.append(struct.unpack_from("<I", data, base + 20)[0])
            return offsets
        pos += 8 + chunk_size + (chunk_size % 2)
    return []


def write_wav_cues(wav_path: Path, sample_offsets: list[int]) -> None:
    """Write (or replace) a cue  chunk in an existing WAV file in-place."""
    if not sample_offsets:
        return
    data = bytearray(Path(wav_path).read_bytes())
    # Drop any existing cue  chunk
    data = _strip_wav_chunk(data, b"cue ")
    # Build new cue  chunk: 4-byte count + 24 bytes per cue point
    num = len(sample_offsets)
    cue_data = bytearray(struct.pack("<I", num))
    for i, offset in enumerate(sample_offsets):
        # id, position, data_chunk_id ("data"), chunk_start, block_start, sample_offset
        cue_data += struct.pack("<IIIIII", i + 1, offset, 0x61746164, 0, 0, offset)
    data += b"cue " + struct.pack("<I", len(cue_data)) + bytes(cue_data)
    struct.pack_into("<I", data, 4, len(data) - 8)
    Path(wav_path).write_bytes(bytes(data))


def _strip_wav_chunk(data: bytearray, chunk_id: bytes) -> bytearray:
    """Return WAV data with every occurrence of chunk_id removed."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data
    result = bytearray(data[:12])
    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos : pos + 4]
        csz = struct.unpack_from("<I", data, pos + 4)[0]
        end = pos + 8 + csz + (csz % 2)
        if cid != chunk_id:
            result += data[pos:end]
        pos = end
    struct.pack_into("<I", result, 4, len(result) - 8)
    return result
