"""Shared utilities for SamplerPrep."""

import json
import os
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


def run_rsync(src, dst, extra_flags):
    """Run rsync from src/ to dst/ with extra_flags."""
    cmd = ["rsync", "-av", "--progress"] + extra_flags + [f"{src}/", f"{dst}/"]
    subprocess.run(cmd, check=True)


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


def download_freesound_sounds(sounds, dest_folder, api_key):
    """Download HQ-MP3 previews for each selected sound into dest_folder."""
    dest_folder.mkdir(parents=True, exist_ok=True)
    for s in sounds:
        url = s["previews"]["preview-hq-mp3"]
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in s["name"])[:40]
        filename = dest_folder / f"{s['id']}_{safe_name}.mp3"
        req = Request(url, headers={"Authorization": f"Token {api_key}"})
        print_step(f"Downloading: {s['name']}")
        with urlopen(req) as r, open(filename, "wb") as f:
            f.write(r.read())
