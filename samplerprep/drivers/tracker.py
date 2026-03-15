"""Polyend Tracker driver.

Output: <target_folder>/Samples/ flat folder.
Format: 16-bit mono WAV at 44100 Hz (Tracker auto-converts on load, but pre-converting
        avoids on-device overhead).
Storage: microSD FAT32.
"""

from pathlib import Path

from samplerprep.core import EXT_OTHER, EXT_RAW, convert_file, find_files, print_step


def process(source_folder, target_folder: Path, device, config, overwrite, normalize):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    samples_dir = target_folder / device["structure"].get("subfolder", "Samples")
    samples_dir.mkdir(parents=True, exist_ok=True)
    ext = device["extension"]

    for src in files:
        stem = Path(src).stem
        target_file = str(samples_dir / f"{stem}{ext}")
        print_step(src)
        if not Path(target_file).exists():
            convert_file(src, target_file, device, overwrite, normalize)

    print_step(f"Done — {len(files)} file(s) written to {samples_dir}")


def describe_output(device):
    subfolder = device["structure"].get("subfolder", "Samples")
    return f"{subfolder}/ flat folder — 16-bit mono WAV at 44100 Hz"
