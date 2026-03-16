"""Make Noise Morphagene driver.

Output: files in root of target_folder, named mg1.wav–mgw.wav (32 reels max).
Format: 32-bit float stereo WAV at 48000 Hz.
"""

from pathlib import Path

import questionary
from questionary import Choice

from samplerprep.core import (
    EXT_OTHER,
    EXT_RAW,
    convert_file,
    find_files,
    print_step,
    read_wav_cues,
    read_wav_info,
    write_wav_cues,
)

# Morphagene naming: mg1–mg9, then mga–mgw (32 total)
_REEL_NAMES = [f"mg{i}" for i in range(1, 10)] + [f"mg{c}" for c in "abcdefghijklmnopqrstuvw"]
MAX_REELS = 32
_TARGET_SR = 48000  # Morphagene hardware sample rate


def process(source_folder, target_folder: Path, device, config, overwrite, normalize):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    if not files:
        print_step("No files found.")
        return

    if len(files) > MAX_REELS:
        print_step(
            f"⚠  {len(files)} files found — Morphagene supports max {MAX_REELS} reels. "
            f"Extra files will be skipped."
        )
        files = files[:MAX_REELS]

    # ── Splice markers ────────────────────────────────────────────────────────
    splice_mode = questionary.select(
        "Splice markers:",
        choices=[
            Choice("None — plain conversion", value="none"),
            Choice("Preserve cue points from source WAVs", value="passthrough"),
        ],
    ).ask()

    target_folder.mkdir(parents=True, exist_ok=True)
    ext = device["extension"]

    for i, src in enumerate(files):
        name = _REEL_NAMES[i]
        target_file = target_folder / f"{name}{ext}"
        print_step(src)
        if not target_file.exists() or overwrite:
            convert_file(src, str(target_file), device, overwrite, normalize)

        # Feature E: copy cue points from source WAV, scaling for sample-rate change
        if splice_mode == "passthrough" and Path(src).suffix.lower() == ".wav":
            src_info = read_wav_info(Path(src))
            cues = read_wav_cues(Path(src))
            if cues and src_info["sample_rate"] and src_info["sample_rate"] != _TARGET_SR:
                scale = _TARGET_SR / src_info["sample_rate"]
                cues = [int(c * scale) for c in cues]
            if cues:
                write_wav_cues(target_file, cues)
                print_step(f"  → copied {len(cues)} splice marker(s)")

    print_step(f"Done — {len(files)} reel(s) written to {target_folder}")


def describe_output(device):
    return "Files in root: mg1.wav–mgw.wav (32 reels max), 32-bit float stereo 48 kHz"
