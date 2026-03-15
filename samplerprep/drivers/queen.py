"""Endorphines Queen of Pentacles driver.

Output: 8 numbered bank folders (1/–8/), each with up to 4 files (1.wav–4.wav).
Format: 16-bit mono WAV at 44100 Hz — metadata MUST be stripped (no BWF/ID3 chunks).
Storage: microSD.
Max files: 32 (8 banks × 4).

NOTE: The bank folder naming scheme (1/–8/) is inferred from community reports;
the official manual PDF was inaccessible during research. Verify with hardware before use.
"""

from pathlib import Path

from samplerprep.core import EXT_OTHER, EXT_RAW, convert_file, find_files, print_step

_MAX_FOLDERS = 8
_MAX_FILES_PER_FOLDER = 4
_MAX_FILES = _MAX_FOLDERS * _MAX_FILES_PER_FOLDER  # 32


def process(source_folder, target_folder: Path, device, config, overwrite, normalize):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    max_folders = device["structure"].get("max_folders", _MAX_FOLDERS)
    max_per = device["structure"].get("max_files_per_folder", _MAX_FILES_PER_FOLDER)
    max_total = max_folders * max_per

    if len(files) > max_total:
        print_step(
            f"⚠  {len(files)} files found — Queen of Pentacles supports max {max_total} "
            f"({max_folders} banks × {max_per}). Extra files will be skipped."
        )
        files = files[:max_total]

    ext = device["extension"]
    bank = 1
    slot = 1

    for src in files:
        bank_dir = target_folder / str(bank)
        bank_dir.mkdir(parents=True, exist_ok=True)

        target_file = str(bank_dir / f"{slot}{ext}")
        print_step(src)
        if not Path(target_file).exists():
            convert_file(src, target_file, device, overwrite, normalize)

        slot += 1
        if slot > max_per:
            slot = 1
            bank += 1

    print_step(f"Done — {len(files)} file(s) written to {target_folder}")
    print_step("⚠  Verify bank folder numbering (1/–8/) matches your hardware before copying.")


def describe_output(device):
    max_f = device["structure"].get("max_folders", _MAX_FOLDERS)
    max_p = device["structure"].get("max_files_per_folder", _MAX_FILES_PER_FOLDER)
    return f"Bank folders 1/–{max_f}/, files 1.wav–{max_p}.wav — no metadata, 16-bit mono 44100 Hz"
