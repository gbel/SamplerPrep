"""Rossum Electro-Music Assimil8or driver.

Output: WAV files + prst001.yml–prst199.yml in a flat folder on the SD card.
Format: 16-bit signed PCM mono WAV at 48 kHz.
Each preset addresses up to 8 channels; each channel holds a Zone 1 pointing to one WAV.
Files beyond 8 per preset overflow into additional numbered preset files.

SD card structure and preset YAML format inferred from the A8Manager open-source project
(https://github.com/cpr2323/A8Manager) by cpr2323.  Credit for the format analysis
belongs to that project's author.

NOTE: this driver was developed without access to physical Assimil8or hardware.
Use A8Manager for full preset editing, validation, and any advanced zone/channel settings.
"""

from pathlib import Path

import questionary

from samplerprep.core import EXT_OTHER, EXT_RAW, convert_file, find_files, pick_files, print_step

CHANNELS_PER_PRESET = 8
MAX_PRESETS = 199


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _write_preset_yml(path: Path, preset_num: int, name: str, wav_filenames: list[str]) -> None:
    """Write a minimal Assimil8or preset YAML assigning one WAV per channel."""
    lines = [f"Preset {preset_num} :"]
    lines.append(f"  Name : {name}")
    for ch_idx, filename in enumerate(wav_filenames, start=1):
        lines.append(f"  Channel {ch_idx} :")
        lines.append("    Zone 1 :")
        lines.append(f"      Sample : {filename}")
    path.write_text("\n".join(lines) + "\n")


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

    default_name = Path(source_folder).name
    preset_name = (
        questionary.text("Preset name:", default=default_name).ask() or default_name
    ).strip()

    target_folder.mkdir(parents=True, exist_ok=True)
    ext = device["extension"]
    total_presets = 0

    for chunk_idx, chunk in enumerate(_chunks(files, CHANNELS_PER_PRESET)):
        if total_presets >= MAX_PRESETS:
            print_step(f"⚠  Reached {MAX_PRESETS}-preset limit — remaining files skipped.")
            break

        preset_num = chunk_idx + 1
        wav_filenames = []
        for src in chunk:
            stem = Path(src).stem
            dst = target_folder / f"{stem}{ext}"
            print_step(Path(src).name)
            convert_file(src, str(dst), device, overwrite, normalize)
            wav_filenames.append(dst.name)

        yml_name = f"prst{preset_num:03d}.yml"
        yml_path = target_folder / yml_name
        name = preset_name if chunk_idx == 0 else f"{preset_name} {preset_num}"
        _write_preset_yml(yml_path, preset_num, name, wav_filenames)
        print_step(f"Wrote {len(wav_filenames)} sample(s) + {yml_name}")
        total_presets += 1

    print_step(f"Done — {total_presets} preset(s) written to {target_folder}")


def describe_output(device):
    return (
        "Flat folder: prst001.yml + WAVs — 16-bit mono 48 kHz, 8 channels/preset, max 199 presets"  # noqa: E501
    )
