"""WMD Clutch driver.

Output: {bank}/{pair:02d}CH.wav and {bank}/{pair:02d}OH.wav
Format: 16-bit signed PCM mono WAV at 48 kHz.
Banks are colour-coded folders: BLUE, CYAN, GREEN, ORANGE, RED, VIOLET, WHITE, YELLOW.
Each bank holds up to 16 closed/open hi-hat pairs (01CH/01OH … 16CH/16OH).

SD card structure and file-naming conventions inferred from the ClutchEdit open-source
project (https://github.com/cpr2323/ClutchEdit) by cpr2323.  Credit for the format
analysis belongs to that project's author.

NOTE: this driver was developed without access to physical WMD Clutch hardware.
Use ClutchEdit to edit the HIHAT.INI settings file and validate your SD card setup.
"""

from pathlib import Path

import questionary
from questionary import Choice

from samplerprep.core import EXT_OTHER, EXT_RAW, convert_file, find_files, pick_files, print_step

BANKS = ["BLUE", "CYAN", "GREEN", "ORANGE", "RED", "VIOLET", "WHITE", "YELLOW"]
MAX_PAIRS = 16


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

    bank = questionary.select(
        "Select target bank (colour):",
        choices=[Choice(b, value=b) for b in BANKS],
    ).ask()
    if not bank:
        return

    assign_mode = questionary.select(
        "Sample assignment:",
        choices=[
            Choice(
                "Alternate CH/OH pairs  (1st=01CH, 2nd=01OH, 3rd=02CH …)",
                value="alternate",
            ),
            Choice("All as closed hi-hat (CH)", value="all_ch"),
            Choice("All as open hi-hat   (OH)", value="all_oh"),
        ],
    ).ask()
    if not assign_mode:
        return

    max_files = MAX_PAIRS * 2 if assign_mode == "alternate" else MAX_PAIRS
    if len(files) > max_files:
        print_step(f"⚠  {len(files)} files — max {max_files} for this mode. Extra files skipped.")
        files = files[:max_files]

    bank_dir = target_folder / bank
    bank_dir.mkdir(parents=True, exist_ok=True)
    ext = device["extension"]

    for idx, src in enumerate(files):
        if assign_mode == "alternate":
            pair = idx // 2 + 1
            kind = "CH" if idx % 2 == 0 else "OH"
        elif assign_mode == "all_ch":
            pair = idx + 1
            kind = "CH"
        else:
            pair = idx + 1
            kind = "OH"

        dst = bank_dir / f"{pair:02d}{kind}{ext}"
        print_step(f"{Path(src).name} → {dst.name}")
        convert_file(src, str(dst), device, overwrite, normalize)

    if assign_mode == "alternate" and len(files) % 2 != 0:
        print_step("⚠  Odd number of files — last pair is missing its partner.")

    print_step(f"Done — {len(files)} file(s) written to {bank_dir}")
    print_step("Tip: use ClutchEdit (https://github.com/cpr2323/ClutchEdit) to edit HIHAT.INI.")


def describe_output(device):
    return "{BANK}/{pair:02d}CH.wav + OH.wav — 16-bit mono 48 kHz, 16 pairs/bank, 8 banks"
