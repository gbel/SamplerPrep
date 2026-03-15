"""Elektron Octatrack driver.

Output: <target_folder>/AUDIO/ flat pool.
Format: 16-bit mono WAV at 44100 Hz (also accepts 24-bit; 48 kHz plays at wrong speed).
Storage: Compact Flash card (FAT32).
"""

from pathlib import Path

from samplerprep.core import EXT_OTHER, EXT_RAW, convert_file, find_files, print_step


def process(source_folder, target_folder: Path, device, config, overwrite, normalize):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    audio_pool = target_folder / "AUDIO"
    audio_pool.mkdir(parents=True, exist_ok=True)
    ext = device["extension"]

    for src in files:
        stem = Path(src).stem
        target_file = str(audio_pool / f"{stem}{ext}")
        print_step(src)
        if not Path(target_file).exists():
            convert_file(src, target_file, device, overwrite, normalize)

    print_step(f"Done — {len(files)} file(s) written to {audio_pool}")
    print_step("Copy the output folder to your Octatrack CF card as a Set folder.")


def describe_output(device):
    return "Set folder with AUDIO/ subfolder — 16-bit mono WAV at 44100 Hz"
