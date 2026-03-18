"""ALM/Busy Circuits Squid Salmple driver.

Output: ALM022/{bank:02d}/{stem}.wav
Format: 16-bit signed PCM mono WAV at 44.1 kHz.
Banks are numbered 01–99; each holds up to 8 samples (one per channel).
Files are placed on a USB stick; the device reads from an ALM022/ root folder.
"""

from pathlib import Path

from samplerprep.core import EXT_OTHER, EXT_RAW, convert_file, find_files, pick_files, print_step


def process(source_folder, target_folder: Path, device, config, overwrite, normalize):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    if not files:
        print_step("No files found.")
        return

    files = pick_files(files)
    if not files:
        print_step("No files selected.")
        return

    structure = device["structure"]
    root = target_folder / structure["root_folder"]  # ALM022/
    files_per_bank = structure["files_per_bank"]
    max_banks = structure["max_banks"]
    ext = device["extension"]

    bank = 1
    slot = 1
    for src in files:
        if bank > max_banks:
            print_step(f"⚠  Reached {max_banks}-bank limit — remaining files skipped.")
            break
        bank_dir = root / f"{bank:02d}"
        bank_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(src).stem
        dst = str(bank_dir / f"{stem}{ext}")
        print_step(Path(src).name)
        convert_file(src, dst, device, overwrite, normalize)
        slot += 1
        if slot > files_per_bank:
            slot = 1
            bank += 1

    banks_written = bank - 1 if slot == 1 else bank
    print_step(f"Done — {banks_written} bank(s) written to {target_folder}")


def describe_output(device):
    return "ALM022/{bank:02d}/files.wav — 16-bit mono 44.1 kHz, 8 files/bank, max 99 banks"
