"""Elektron Digitakt driver.

The Digitakt has no SD card slot. Samples are transferred via USB using
Elektron Transfer. This driver converts files to the native format (16-bit
mono WAV at 48000 Hz) and writes them into a flat output folder ready to
be dragged into Elektron Transfer.
"""

from pathlib import Path

from samplerprep.core import EXT_OTHER, EXT_RAW, convert_file, find_files, print_step


def process(source_folder, target_folder: Path, device, config, overwrite, normalize):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    target_folder.mkdir(parents=True, exist_ok=True)
    ext = device["extension"]

    for src in files:
        stem = Path(src).stem
        target_file = str(target_folder / f"{stem}{ext}")
        print_step(src)
        if not Path(target_file).exists():
            convert_file(src, target_file, device, overwrite, normalize)

    print_step(f"Done — {len(files)} file(s) written to {target_folder}")
    print_step(
        "Transfer files to your Digitakt using Elektron Transfer via USB: "
        "elektron.se/en/downloads/transfer"
    )


def describe_output(device):
    return "Flat folder of 16-bit mono WAV at 48 kHz — import via Elektron Transfer over USB"
