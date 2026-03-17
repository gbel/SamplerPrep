"""Make Noise Morphagene driver.

Output: files in root of target_folder, named mg1.wav–mgw.wav (32 reels max).
Format: 32-bit float stereo WAV at 48000 Hz.
"""

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import questionary
from questionary import Choice

from samplerprep.core import (
    EXT_OTHER,
    EXT_RAW,
    ask_int,
    convert_file,
    find_files,
    getch_timeout,
    pick_files,
    print_step,
    read_wav_cues,
    read_wav_info,
    write_wav_cues,
)

# Morphagene naming: mg1–mg9, then mga–mgw (32 total)
_REEL_NAMES = [f"mg{i}" for i in range(1, 10)] + [f"mg{c}" for c in "abcdefghijklmnopqrstuvw"]
MAX_REELS = 32
_TARGET_SR = 48000  # Morphagene hardware sample rate
MAX_REEL_DURATION_SECS = 174  # ~2.9 min firmware limit; files longer than this won't load
MAX_SPLICE_MARKERS = 300  # firmware limit on cue points per reel

OPTIONS_FILE = "options.txt"

_OPTIONS_DEFS = [
    (
        "vsop",
        0,
        "Varispeed option: 0 bidirectional classic, 1 bidirectional 1 v/oct, 2 positive only - 1 v/oct",  # noqa: E501
    ),
    ("inop", 0, "Input option: 0 record SOS mix, 1 record input only"),
    (
        "pmin",
        0,
        "Phase/position modulation: 0 no phase modulation, 1 phase playback modulation on right signal input when no signal on left input",  # noqa: E501
    ),
    ("omod", 0, "Organize option: 0 organize at end of gene, 1 organize immediately"),
    ("gnsm", 0, "Gene smooth: 0 classic, 1 smooth gene window"),
    (
        "rsop",
        0,
        "Record option: 0 record + splice = record new splice, record = record current splice; 1 record + splice = record current splice, record = record new splice",  # noqa: E501
    ),
    ("pmod", 0, "Play option: 0 classic, 1 momentary, 2 trigger loop"),
    (
        "ckop",
        0,
        "Clock control option: 0 hybrid gene shift time stretch, 1 gene shift only, 2 time stretch only",  # noqa: E501
    ),
    ("cvop", 0, "CV out: 0 envelope follow, 1 ramp gene"),
    ("mcr1", 2.0, "Morph Chord Ratio: 0.06250 to 16.00000, negative is reverse"),
    ("mcr2", 1.5, "Morph Chord Ratio: 0.06250 to 16.00000, negative is reverse"),
    ("mcr3", 1.33333, "Morph Chord Ratio: 0.06250 to 16.00000, negative is reverse"),
]


def _concat_wavs(wav_files: list[Path], output_path: Path) -> None:
    """Concatenate wav_files into output_path using ffmpeg concat demuxer."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        list_file = Path(f.name)
        f.write("\n".join(f"file '{p}'" for p in wav_files))
    try:
        cmd = [
            "ffmpeg",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            "-y",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        list_file.unlink(missing_ok=True)


def _enforce_min_gap(offsets: list[int], sample_rate: int, min_secs: float = 1.0) -> list[int]:
    """Remove markers closer than min_secs apart, keeping the earlier one."""
    min_samples = int(min_secs * sample_rate)
    result: list[int] = []
    last = -min_samples
    for offset in sorted(offsets):
        if offset - last >= min_samples:
            result.append(offset)
            last = offset
    return result


def _trim_reel(path: Path) -> bool:
    """Trim a reel to MAX_REEL_DURATION_SECS in-place if it exceeds the firmware limit.

    Returns True if the reel was trimmed.
    """
    info = read_wav_info(path)
    if not info["sample_rate"]:
        return False
    dur = info["num_samples"] / info["sample_rate"]
    if dur <= MAX_REEL_DURATION_SECS:
        return False
    tmp = path.with_suffix(".trim.wav")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(path),
            "-t",
            str(MAX_REEL_DURATION_SECS),
            "-c",
            "copy",
            str(tmp),
        ],  # noqa: E501
        check=True,
        capture_output=True,
    )
    tmp.replace(path)
    return True


def _rubberband_available() -> bool:
    return shutil.which("rubberband") is not None


def _apply_rubberband(wav_path: Path, pitch_semitones: int = 0, tempo_factor: float = 1.0) -> None:
    """Apply rubberband pitch/tempo shift to wav_path in-place (via a temp file)."""
    tmp = wav_path.with_suffix(".rb_out.wav")
    cmd = ["rubberband", "-2"]
    if pitch_semitones:
        cmd += ["-p", str(pitch_semitones)]
    if tempo_factor != 1.0:
        cmd += ["-t", str(tempo_factor)]
    cmd += [str(wav_path), str(tmp)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tmp.replace(wav_path)


def _aubio_available() -> bool:
    try:
        import aubio  # noqa: F401

        return True
    except ImportError:
        return False


def _detect_transients(wav_path: Path, threshold: float = 0.3) -> list[int]:
    """Return sample offsets of detected onsets in wav_path using aubio.

    Exports a mono downmix via ffmpeg first, since aubio onset detection
    works on mono audio. Detected positions are reported in the stereo
    reel's sample space (same sample rate, just one channel reference).
    """
    import aubio

    info = read_wav_info(wav_path)
    sr = info["sample_rate"]
    hop_size = 512
    win_size = 1024

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        mono_path = Path(f.name)
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            "-ac",
            "1",
            "-ar",
            str(sr),
            str(mono_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        src = aubio.source(str(mono_path), sr, hop_size)
        onset = aubio.onset("default", win_size, hop_size, sr)
        onset.set_threshold(threshold)

        offsets = []
        while True:
            samples, read = src()
            if onset(samples):
                pos = onset.get_last()
                if pos > 0:
                    offsets.append(pos)
            if read < hop_size:
                break
    finally:
        mono_path.unlink(missing_ok=True)

    return offsets


def read_options(path: Path) -> tuple[str, dict]:
    """Return (state_line, {key: int_value}). Returns ("0 0 0", {}) if file absent."""
    if not path.exists():
        return ("0 0 0", {})
    state_line = "0 0 0"
    options = {}
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if i == 0:
            state_line = line.strip()
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            key = parts[0]
            val_str = parts[1]
            try:
                options[key] = float(val_str) if "." in val_str else int(val_str)
            except ValueError:
                pass
    return (state_line, options)


def write_options(path: Path, options: dict, state_line: str = "0 0 0") -> None:
    """Write options.txt in correct format."""
    lines = [state_line, "//", "// firmware version 204", "//", "// 0 option is default"]
    for key, default, comment in _OPTIONS_DEFS:
        value = options.get(key, default)
        formatted = f"{value:.5f}" if isinstance(value, float) else str(value)
        lines.append(f"{key} {formatted} //{comment}")
    lines += ["//", "//Default Chord: 2.0, 1.5, 1.33333"]
    path.write_text("\n".join(lines) + "\n")


def get_options_preset(presets: list, which: int) -> dict:
    """Merge presets[which] over the default preset. Returns complete 9-key dict."""
    default = next((p for p in presets if p.get("_name") == "default"), {})
    base = {key: default.get(key, dflt) for key, dflt, _ in _OPTIONS_DEFS}
    overlay = presets[which]
    for key, _, _ in _OPTIONS_DEFS:
        if key in overlay:
            base[key] = overlay[key]
    return base


def detect_options_preset(current: dict, presets: list) -> str | None:
    """Return _name of first matching preset, or None."""
    for i, p in enumerate(presets):
        merged = get_options_preset(presets, i)
        if all(current.get(k) == merged[k] for k, _, _ in _OPTIONS_DEFS):
            return p["_name"]
    return None


def create_options_preset(config: dict) -> None:
    """Interactive wizard to create a new options preset."""
    import json

    presets = config.setdefault("morphagene_presets", [])
    built_in_names = {p["_name"] for p in presets}

    name = questionary.text("Preset name:").ask()
    if not name:
        return
    if name in built_in_names:
        print_step(f'A preset named "{name}" already exists. Choose a different name.')
        return

    new_preset: dict = {"_name": name}
    for key, default, comment in _OPTIONS_DEFS:
        comment_parts = comment.split(": ", 1)
        label = comment_parts[0] if comment_parts else key

        if isinstance(default, float):
            # Continuous float param (mcr1/2/3) — use text input
            range_hint = comment_parts[1] if len(comment_parts) > 1 else ""
            raw = questionary.text(f"{label} [{default:.5f}]  (range: {range_hint}):").ask()
            try:
                chosen = float(raw) if raw else default
            except ValueError:
                chosen = default
        else:
            # Integer param — build choices from comment
            value_descs = comment_parts[1].split(", ") if len(comment_parts) > 1 else []
            choices = []
            for desc in value_descs:
                parts = desc.strip().split(" ", 1)
                if parts[0].isdigit():
                    val = int(parts[0])
                    desc_text = parts[1] if len(parts) > 1 else str(val)
                    choices.append(Choice(title=f"{val} — {desc_text}", value=val))
            if not choices:
                choices = [Choice(title=str(default), value=default)]
            chosen = questionary.select(f"{label}:", choices=choices).ask()

        new_preset[key] = chosen

    presets.append(new_preset)
    config_path = Path("config.json")
    config_path.write_text(json.dumps(config, indent=4) + "\n")
    print_step(f'Saved preset "{name}" to config.json')


def process(
    source_folder,
    target_folder: Path,
    device,
    config,
    overwrite,
    normalize,
    options: dict | None = None,
    files: list[str] | None = None,
):
    if files is None:
        files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    if not files:
        print_step("No files found.")
        return

    files = pick_files(files)
    if not files:
        print_step("No files selected.")
        return

    # ── Pitch/tempo shift ─────────────────────────────────────────────────────
    pitch_semitones = 0
    tempo_factor = 1.0
    if _rubberband_available():
        shift_mode = questionary.select(
            "Pitch/tempo adjustment:",
            choices=[
                Choice("None — no adjustment", value="none"),
                Choice("Shift pitch", value="pitch"),
                Choice("Stretch tempo", value="tempo"),
            ],
        ).ask()
        if shift_mode == "pitch":
            pitch_semitones = ask_int("Semitones (negative = lower pitch):", 0, -24, 24)
        elif shift_mode == "tempo":
            raw = questionary.text("Tempo factor (e.g. 0.5 = half speed, 2.0 = double):").ask()
            try:
                tempo_factor = float(raw or "1.0")
            except ValueError:
                tempo_factor = 1.0

    # ── Reel creation mode ────────────────────────────────────────────────────
    reel_mode = questionary.select(
        "Reel creation:",
        choices=[
            Choice("One file per reel", value="per_file"),
            Choice("Concat all files → one reel", value="concat"),
        ],
    ).ask()

    if reel_mode == "per_file" and len(files) > MAX_REELS:
        print_step(
            f"⚠  {len(files)} files found — Morphagene supports max {MAX_REELS} reels. "
            f"Extra files will be skipped."
        )
        files = files[:MAX_REELS]

    # ── Splice markers ────────────────────────────────────────────────────────
    splice_choices = [Choice("None — plain conversion", value="none")]
    if reel_mode == "per_file":
        splice_choices.append(Choice("Preserve cue points from source WAVs", value="passthrough"))
    if reel_mode == "concat":
        pass  # boundary markers are added automatically when concatenating multiple files
    splice_choices.append(Choice("Even grid — splice every N seconds", value="grid"))
    if _aubio_available():
        splice_choices.append(Choice("Auto-detect transients (aubio)", value="transients"))
    else:
        splice_choices.append(
            Choice(
                "Auto-detect transients (aubio)",
                value="transients",
                disabled="run: brew install aubio",
            )
        )

    splice_mode = questionary.select("Splice markers:", choices=splice_choices).ask()

    grid_step_secs = 2
    if splice_mode == "grid":
        grid_step_secs = ask_int("Splice every N seconds:", 2, 1, 60)

    transient_threshold = 0.3
    if splice_mode == "transients":
        raw = questionary.text("Detection sensitivity 0.0–1.0 (lower = more splices) [0.3]:").ask()
        try:
            transient_threshold = max(0.0, min(1.0, float(raw or "0.3")))
        except ValueError:
            transient_threshold = 0.3

    target_folder.mkdir(parents=True, exist_ok=True)
    (target_folder / ".metadata_never_index").touch()
    ext = device["extension"]

    if reel_mode == "concat":
        with tempfile.TemporaryDirectory() as _tmp:
            tmp = Path(_tmp)
            converted = []
            for i, src in enumerate(files):
                dst = tmp / f"{i:04d}.wav"
                convert_file(src, str(dst), device, overwrite, normalize)
                if pitch_semitones or tempo_factor != 1.0:
                    _apply_rubberband(dst, pitch_semitones, tempo_factor)
                converted.append(dst)
                print_step(f"Converted {Path(src).name}")

            output_path = target_folder / f"{_REEL_NAMES[0]}{ext}"
            print_step(f"Concatenating {len(converted)} files → {output_path.name}")
            _concat_wavs(converted, output_path)

            if _trim_reel(output_path):
                print_step(
                    f"Reel clipped to {MAX_REEL_DURATION_SECS}s"
                    f" ({MAX_REEL_DURATION_SECS / 60:.1f} min) — Morphagene firmware limit."
                )

            # Always add file-boundary markers when concatenating multiple files
            boundary_offsets: list[int] = []
            if len(converted) > 1:
                cumulative = 0
                for wav in converted[:-1]:
                    cumulative += read_wav_info(wav)["num_samples"]
                    boundary_offsets.append(cumulative)

            # Additional markers from user-selected mode
            extra_offsets: list[int] = []
            if splice_mode == "grid":
                info = read_wav_info(output_path)
                step = grid_step_secs * info["sample_rate"]
                extra_offsets = list(range(step, info["num_samples"], step))
            elif splice_mode == "transients":
                extra_offsets = _detect_transients(output_path, transient_threshold)

            all_offsets = boundary_offsets + extra_offsets
            if all_offsets:
                info = read_wav_info(output_path)
                all_offsets = _enforce_min_gap(all_offsets, info["sample_rate"])
                if len(all_offsets) > MAX_SPLICE_MARKERS:
                    print_step(
                        f"Capped splice markers at {MAX_SPLICE_MARKERS}"
                        f" ({len(all_offsets)} detected) — Morphagene firmware limit."
                    )
                    all_offsets = all_offsets[:MAX_SPLICE_MARKERS]
                write_wav_cues(output_path, all_offsets)
                if boundary_offsets:
                    print_step(f"Auto-added {len(boundary_offsets)} file-boundary marker(s)")
                if extra_offsets:
                    print_step(f"Added {len(extra_offsets)} {splice_mode} marker(s)")
                print_step(f"Wrote {len(all_offsets)} splice marker(s) total")

        print_step(f"Done — 1 reel written to {target_folder}")

    else:  # per_file
        for i, src in enumerate(files):
            name = _REEL_NAMES[i]
            target_file = target_folder / f"{name}{ext}"
            print_step(src)
            if not target_file.exists() or overwrite:
                convert_file(src, str(target_file), device, overwrite, normalize)
                if pitch_semitones or tempo_factor != 1.0:
                    _apply_rubberband(target_file, pitch_semitones, tempo_factor)

            if _trim_reel(target_file):
                print_step(
                    f"  Reel clipped to {MAX_REEL_DURATION_SECS}s"
                    f" ({MAX_REEL_DURATION_SECS / 60:.1f} min) — Morphagene firmware limit."
                )

            if splice_mode == "passthrough" and Path(src).suffix.lower() == ".wav":
                src_info = read_wav_info(Path(src))
                cues = read_wav_cues(Path(src))
                if cues and src_info["sample_rate"] and src_info["sample_rate"] != _TARGET_SR:
                    scale = _TARGET_SR / src_info["sample_rate"]
                    cues = [int(c * scale) for c in cues]
                if cues:
                    write_wav_cues(target_file, cues)
                    print_step(f"  → copied {len(cues)} splice marker(s)")
            elif splice_mode == "grid":
                info = read_wav_info(target_file)
                step = grid_step_secs * info["sample_rate"]
                offsets = list(range(step, info["num_samples"], step))
                offsets = _enforce_min_gap(offsets, info["sample_rate"])
                if len(offsets) > MAX_SPLICE_MARKERS:
                    print_step(
                        f"  Capped splice markers at {MAX_SPLICE_MARKERS}"
                        f" ({len(offsets)} detected) — Morphagene firmware limit."
                    )
                    offsets = offsets[:MAX_SPLICE_MARKERS]
                if offsets:
                    write_wav_cues(target_file, offsets)
                    print_step(f"  → wrote {len(offsets)} splice marker(s)")
            elif splice_mode == "transients":
                offsets = _detect_transients(target_file, transient_threshold)
                info = read_wav_info(target_file)
                offsets = _enforce_min_gap(offsets, info["sample_rate"])
                if len(offsets) > MAX_SPLICE_MARKERS:
                    print_step(
                        f"  Capped splice markers at {MAX_SPLICE_MARKERS}"
                        f" ({len(offsets)} detected) — Morphagene firmware limit."
                    )
                    offsets = offsets[:MAX_SPLICE_MARKERS]
                if offsets:
                    write_wav_cues(target_file, offsets)
                    print_step(f"  → wrote {len(offsets)} splice marker(s)")

        print_step(f"Done — {len(files)} reel(s) written to {target_folder}")

    state_line, _ = read_options(target_folder / OPTIONS_FILE)
    write_options(target_folder / OPTIONS_FILE, options or {}, state_line)
    print_step("Wrote options.txt")


def describe_output(device):
    return "Files in root: mg1.wav–mgw.wav (32 reels max), 32-bit float stereo 48 kHz"


_MACOS_JUNK = [
    ".DS_Store",
    ".Spotlight-V100",
    ".Trashes",
    ".DocumentRevisions-V100",
    ".TemporaryItems",
    ".fseventsd",
]


def clean_card(volume: Path) -> None:
    """Remove macOS metadata files from a mounted FAT32 Morphagene card.

    macOS creates AppleDouble (._filename) resource-fork shadow files and system
    directories on FAT32 volumes. The Morphagene firmware tries to load any file in
    the card root as a reel; when it can't parse these, it overwrites them with a
    44-byte WAV stub — corrupting recordings. Run this before returning the card to
    the module.
    """
    import shutil

    removed = 0
    for f in volume.rglob("._*"):
        f.unlink()
        removed += 1
    for name in _MACOS_JUNK:
        target = volume / name
        if target.is_file():
            target.unlink()
            removed += 1
        elif target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            removed += 1
    print_step(f"Removed {removed} macOS metadata file(s) from {volume}")
    print_step(
        "Card is ready to return to the Morphagene.\n"
        "   Tip: to prevent Spotlight from re-creating metadata on remount, add\n"
        "   the card volume (usually 'NO NAME') to System Settings → Siri & Spotlight\n"
        "   → Spotlight Privacy. Otherwise, reinsert immediately after cleaning."
    )


def save_recordings(volume: Path, root_folder: Path) -> "Path | None":
    """Copy mg*.wav reels from a mounted card to a timestamped local folder.

    Returns the destination path, or None if no recordings were found.
    Run immediately after inserting the card — macOS Spotlight begins creating
    AppleDouble (._*) shadow files within seconds of mount, which will corrupt
    recordings if the card is returned to the Morphagene without cleaning first.
    """
    from datetime import datetime

    reels = sorted(
        (f for f in volume.glob("mg*.wav") if f.stem in _REEL_NAMES),
        key=lambda f: _REEL_NAMES.index(f.stem),
    )
    if not reels:
        print_step("No mg*.wav recordings found on the card.")
        return None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_vol = "".join(c if c.isalnum() or c in "-_" else "_" for c in volume.name)
    dest = root_folder / f"recordings_{safe_vol}_{ts}"
    dest.mkdir(parents=True, exist_ok=True)

    for reel in reels:
        shutil.copy2(reel, dest / reel.name)
        print_step(f"Saved {reel.name}  ({reel.stat().st_size // 1024} KB)")

    print_step(f"Saved {len(reels)} reel(s) to {dest}")
    return dest


# ── Preview browser ────────────────────────────────────────────────────────────


def _play_wav(path: Path, seek_secs: float = 0.0) -> subprocess.Popen:
    """Start playing a WAV file via sox/play in the background. Returns Popen handle."""
    cmd = ["play", str(path)]
    if seek_secs > 0:
        cmd += ["trim", str(seek_secs)]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _wav_duration(path: Path) -> float:
    info = read_wav_info(path)
    return info["num_samples"] / info["sample_rate"]


def _cues_for(path: Path) -> list[float]:
    """Return splice marker positions in seconds for a reel WAV."""
    info = read_wav_info(path)
    sr = info["sample_rate"]
    if not sr:
        return []
    return [c / sr for c in read_wav_cues(path)]


def _fmt_time(secs: float) -> str:
    secs = max(0.0, secs)
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"


def _render_preview_mg(
    reels: list[Path],
    cursor: int,
    playing_idx: int | None,
    elapsed: float | None,
    play_total: float | None,
    cue_cache: dict,
) -> None:
    BAR_WIDTH = 40
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write("Morphagene Preview\n")
    sys.stdout.write("[q] quit  [space] play/stop  [,/.] seek 5s  [[ / ]] prev/next splice\n\n")
    for i, reel in enumerate(reels):
        cur = ">" if i == cursor else " "
        play = "▶" if i == playing_idx else " "
        cues = cue_cache.get(i, [])
        cue_tag = f"  ({len(cues)} splices)" if cues else ""
        sys.stdout.write(f" {cur} {play}  {reel.name}{cue_tag}\n")
    sys.stdout.write("\n")
    if playing_idx is not None and elapsed is not None and play_total and play_total > 0:
        frac = min(1.0, elapsed / play_total)
        filled = int(frac * BAR_WIDTH)
        cues = cue_cache.get(playing_idx, [])
        bar = list("░" * BAR_WIDTH)
        for c in cues:
            idx = int(c / play_total * BAR_WIDTH)
            if 0 <= idx < BAR_WIDTH:
                bar[idx] = "|"
        for i in range(filled):
            if bar[i] != "|":
                bar[i] = "█"
        sys.stdout.write(f"[{''.join(bar)}]  {_fmt_time(elapsed)} / {_fmt_time(play_total)}\n")
    sys.stdout.flush()


def preview(target_folder: Path) -> None:
    """Interactive reel browser for a Morphagene card folder."""
    if not shutil.which("play"):
        print("sox 'play' not found — install with: brew install sox")
        return
    reels = sorted(
        (f for f in target_folder.glob("mg*.wav")),
        key=lambda f: _REEL_NAMES.index(f.stem) if f.stem in _REEL_NAMES else 999,
    )
    if not reels:
        print(f"No mg*.wav reels found in {target_folder}")
        return

    cursor = 0
    proc = None
    playing_idx: int | None = None
    play_start_time: float | None = None
    seek_offset = 0.0
    cue_cache: dict[int, list[float]] = {}

    def _load_cues(idx: int) -> None:
        if idx not in cue_cache:
            cue_cache[idx] = _cues_for(reels[idx])

    def current_elapsed() -> float | None:
        if play_start_time is None:
            return None
        return seek_offset + (time.monotonic() - play_start_time)

    def start_playback(idx: int, offset: float = 0.0) -> None:
        nonlocal proc, playing_idx, play_start_time, seek_offset
        proc = _play_wav(reels[idx], offset)
        playing_idx = idx
        seek_offset = offset
        play_start_time = time.monotonic()
        _load_cues(idx)

    def stop_playback() -> None:
        nonlocal proc, playing_idx, play_start_time, seek_offset
        if proc:
            proc.terminate()
            proc.wait()
        proc = None
        playing_idx = None
        play_start_time = None
        seek_offset = 0.0

    try:
        _load_cues(0)
        while True:
            if proc is not None and proc.poll() is not None:
                proc = None
                playing_idx = None
                play_start_time = None
                seek_offset = 0.0

            elapsed = current_elapsed()
            play_total = _wav_duration(reels[playing_idx]) if playing_idx is not None else None
            _render_preview_mg(reels, cursor, playing_idx, elapsed, play_total, cue_cache)

            key = getch_timeout(0.1)
            if key is None:
                continue

            if key in (b"q", b"Q", b"\x1b"):
                break
            elif key in (b"\x1b[A", b"k"):
                new_cursor = max(0, cursor - 1)
                if new_cursor != cursor:
                    cursor = new_cursor
                    _load_cues(cursor)
                    if proc and proc.poll() is None:
                        proc.terminate()
                        proc.wait()
                        start_playback(cursor)
            elif key in (b"\x1b[B", b"j"):
                new_cursor = min(len(reels) - 1, cursor + 1)
                if new_cursor != cursor:
                    cursor = new_cursor
                    _load_cues(cursor)
                    if proc and proc.poll() is None:
                        proc.terminate()
                        proc.wait()
                        start_playback(cursor)
            elif key == b" ":
                if proc and proc.poll() is None:
                    stop_playback()
                else:
                    start_playback(cursor)
            elif key == b",":
                if proc and proc.poll() is None and playing_idx is not None:
                    new_offset = max(0.0, (current_elapsed() or 0.0) - 5.0)
                    proc.terminate()
                    proc.wait()
                    start_playback(playing_idx, new_offset)
            elif key == b".":
                if proc and proc.poll() is None and playing_idx is not None:
                    total = _wav_duration(reels[playing_idx])
                    new_offset = min(total - 0.5, (current_elapsed() or 0.0) + 5.0)
                    proc.terminate()
                    proc.wait()
                    start_playback(playing_idx, new_offset)
            elif key == b"[":
                if proc and proc.poll() is None and playing_idx is not None:
                    el = current_elapsed() or 0.0
                    prev_cues = [c for c in cue_cache.get(playing_idx, []) if c < el - 0.1]
                    new_offset = prev_cues[-1] if prev_cues else 0.0
                    proc.terminate()
                    proc.wait()
                    start_playback(playing_idx, new_offset)
            elif key == b"]":
                if proc and proc.poll() is None and playing_idx is not None:
                    el = current_elapsed() or 0.0
                    next_cues = [c for c in cue_cache.get(playing_idx, []) if c > el + 0.1]
                    if next_cues:
                        proc.terminate()
                        proc.wait()
                        start_playback(playing_idx, next_cues[0])
    finally:
        if proc:
            proc.terminate()
            proc.wait()
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
