"""Make Noise Morphagene driver.

Output: files in root of target_folder, named mg1.wav–mgw.wav (32 reels max).
Format: 32-bit float stereo WAV at 48000 Hz.
"""

from pathlib import Path

from samplerprep.core import EXT_OTHER, EXT_RAW, convert_file, find_files, print_step

# Morphagene naming: mg1–mg9, then mga–mgw (32 total)
_REEL_NAMES = [f"mg{i}" for i in range(1, 10)] + [f"mg{c}" for c in "abcdefghijklmnopqrstuvw"]
MAX_REELS = 32


def process(source_folder, target_folder: Path, device, config, overwrite, normalize):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    if len(files) > MAX_REELS:
        print_step(
            f"⚠  {len(files)} files found — Morphagene supports max {MAX_REELS} reels. "
            f"Extra files will be skipped."
        )
        files = files[:MAX_REELS]

    target_folder.mkdir(parents=True, exist_ok=True)
    ext = device["extension"]

    for i, src in enumerate(files):
        name = _REEL_NAMES[i]
        target_file = str(target_folder / f"{name}{ext}")
        print_step(src)
        if not Path(target_file).exists():
            convert_file(src, target_file, device, overwrite, normalize)

    print_step(f"Done — {len(files)} reel(s) written to {target_folder}")


def describe_output(device):
    return "Files in root: mg1.wav–mgw.wav (32 reels max), 32-bit float stereo 48 kHz"
