"""1010music Bitbox mk2 / Micro driver.

Output: Presets/{name}/preset.xml + WAV files alongside it.
Format: 24-bit signed PCM stereo WAV at 48 kHz.
Each preset maps up to 16 samples onto a 4×4 pad grid (rows 0–3, columns 0–3).
Files beyond 16 overflow into additional numbered presets.

preset.xml format inferred from ConvertWithMoss (Music1010Creator.java) and
the Bitbox-Editor open-source project.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import questionary

from samplerprep.core import EXT_OTHER, EXT_RAW, convert_file, find_files, pick_files, print_step

MAX_SLOTS = 16


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _write_preset_xml(preset_folder: Path, preset_name: str, wav_files: list[Path]) -> None:
    """Write a minimal preset.xml for the given WAV files."""
    doc = ET.Element("document", version="2")
    session = ET.SubElement(doc, "session", version="2")
    for i, wav in enumerate(wav_files):
        row, col = divmod(i, 4)
        path_str = f"\\Presets\\{preset_name}\\{wav.name}"
        cell = ET.SubElement(
            session,
            "cell",
            row=str(row),
            column=str(col),
            layer="0",
            filename=path_str,
            type="1",
        )
        ET.SubElement(cell, "params")
    tree = ET.ElementTree(doc)
    ET.indent(tree, space="  ")
    tree.write(preset_folder / "preset.xml", xml_declaration=True, encoding="UTF-8")


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

    ext = device["extension"]
    total_presets = 0

    for chunk_idx, chunk in enumerate(_chunks(files, MAX_SLOTS)):
        name = preset_name if chunk_idx == 0 else f"{preset_name}-{chunk_idx + 1}"
        preset_folder = target_folder / "Presets" / name
        preset_folder.mkdir(parents=True, exist_ok=True)

        converted: list[Path] = []
        for src in chunk:
            stem = Path(src).stem
            dst = preset_folder / f"{stem}{ext}"
            print_step(Path(src).name)
            convert_file(src, str(dst), device, overwrite, normalize)
            converted.append(dst)

        _write_preset_xml(preset_folder, name, converted)
        print_step(f"Wrote {len(converted)} sample(s) + preset.xml → Presets/{name}/")
        total_presets += 1

    print_step(f"Done — {total_presets} preset(s) written to {target_folder}")


def describe_output(device):
    return "Presets/{name}/preset.xml + WAVs — 24-bit stereo 48 kHz, max 16 slots/preset"
