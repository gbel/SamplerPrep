"""Squarp Rample driver.

Output: kit folders at root (A0/, A1/, …, Z99/), each with up to 4 voice files.
File naming: <voice>_<original_stem>.wav  (voice is 1–4).
Format: 16-bit mono WAV at 44100 Hz.
Storage: microSD.

Files are assigned to voices round-robin (1→2→3→4→1→2→…). When all 4 voices
in a kit are filled, a new kit folder is started.
"""

from pathlib import Path

from samplerprep.core import EXT_OTHER, EXT_RAW, convert_file, find_files, print_step

_VOICES_PER_KIT = 4
_MAX_KITS = 2600  # 26 letters × 100 numbers


def _kit_name(idx: int) -> str:
    """Return the Rample kit folder name for a zero-based index (A0, A1, …, Z99)."""
    letter = chr(ord("A") + idx // 100)
    number = idx % 100
    return f"{letter}{number}"


def process(source_folder, target_folder: Path, device, config, overwrite, normalize):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    voices_per_kit = device["structure"].get("voices_per_kit", _VOICES_PER_KIT)
    max_files = _MAX_KITS * voices_per_kit
    if len(files) > max_files:
        print_step(f"⚠  More than {max_files} files — extra files will be skipped.")
        files = files[:max_files]

    ext = device["extension"]
    kit_idx = 0
    voice = 1

    for src in files:
        kit_name = _kit_name(kit_idx)
        kit_dir = target_folder / kit_name
        kit_dir.mkdir(parents=True, exist_ok=True)

        stem = Path(src).stem
        target_file = str(kit_dir / f"{voice}_{stem}{ext}")
        print_step(src)
        if not Path(target_file).exists():
            convert_file(src, target_file, device, overwrite, normalize)

        voice += 1
        if voice > voices_per_kit:
            voice = 1
            kit_idx += 1

    kits_used = kit_idx + (1 if voice > 1 else 0)
    print_step(f"Done — {len(files)} file(s) in {kits_used} kit(s) written to {target_folder}")


def describe_output(device):
    vpk = device["structure"].get("voices_per_kit", _VOICES_PER_KIT)
    return f"Kit folders A0/… at root, {vpk} voice files each (1_name.wav–{vpk}_name.wav)"
