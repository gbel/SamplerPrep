"""Make Noise Morphagene driver.

Output: files in root of target_folder, named mg1.wav–mgw.wav (32 reels max).
Format: 32-bit float stereo WAV at 48000 Hz.
"""

import subprocess
import tempfile
from pathlib import Path

import questionary
from questionary import Choice

from samplerprep.core import (
    EXT_OTHER,
    EXT_RAW,
    ask_int,
    convert_file,
    find_files,
    print_step,
    read_wav_cues,
    read_wav_info,
    write_wav_cues,
)

# Morphagene naming: mg1–mg9, then mga–mgw (32 total)
_REEL_NAMES = [f"mg{i}" for i in range(1, 10)] + [f"mg{c}" for c in "abcdefghijklmnopqrstuvw"]
MAX_REELS = 32
_TARGET_SR = 48000  # Morphagene hardware sample rate


def _concat_wavs(wav_files: list[Path], output_path: Path) -> None:
    """Concatenate wav_files into output_path using ffmpeg concat demuxer."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        list_file = Path(f.name)
        f.write("\n".join(f"file '{p}'" for p in wav_files))
    try:
        cmd = [
            "ffmpeg",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            "-y",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        list_file.unlink(missing_ok=True)


def process(source_folder, target_folder: Path, device, config, overwrite, normalize):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    if not files:
        print_step("No files found.")
        return

    # ── Reel creation mode ────────────────────────────────────────────────────
    reel_mode = questionary.select(
        "Reel creation:",
        choices=[
            Choice("One file per reel", value="per_file"),
            Choice("Concat all files → one reel", value="concat"),
        ],
    ).ask()

    if reel_mode == "per_file" and len(files) > MAX_REELS:
        print_step(
            f"⚠  {len(files)} files found — Morphagene supports max {MAX_REELS} reels. "
            f"Extra files will be skipped."
        )
        files = files[:MAX_REELS]

    # ── Splice markers ────────────────────────────────────────────────────────
    splice_choices = [Choice("None — plain conversion", value="none")]
    if reel_mode == "per_file":
        splice_choices.append(Choice("Preserve cue points from source WAVs", value="passthrough"))
    if reel_mode == "concat":
        splice_choices.append(
            Choice("File boundaries — one splice per source file", value="boundaries")
        )
    splice_choices.append(Choice("Even grid — splice every N seconds", value="grid"))

    splice_mode = questionary.select("Splice markers:", choices=splice_choices).ask()

    grid_step_secs = 2
    if splice_mode == "grid":
        grid_step_secs = ask_int("Splice every N seconds:", 2, 1, 60)

    target_folder.mkdir(parents=True, exist_ok=True)
    ext = device["extension"]

    if reel_mode == "concat":
        with tempfile.TemporaryDirectory() as _tmp:
            tmp = Path(_tmp)
            converted = []
            for i, src in enumerate(files):
                dst = tmp / f"{i:04d}.wav"
                convert_file(src, str(dst), device, overwrite, normalize)
                converted.append(dst)
                print_step(f"Converted {Path(src).name}")

            output_path = target_folder / f"{_REEL_NAMES[0]}{ext}"
            print_step(f"Concatenating {len(converted)} files → {output_path.name}")
            _concat_wavs(converted, output_path)

            if splice_mode == "boundaries":
                offsets = []
                cumulative = 0
                for wav in converted[:-1]:  # boundary after each file except the last
                    cumulative += read_wav_info(wav)["num_samples"]
                    offsets.append(cumulative)
                if offsets:
                    write_wav_cues(output_path, offsets)
                    print_step(f"Wrote {len(offsets)} splice marker(s)")
            elif splice_mode == "grid":
                info = read_wav_info(output_path)
                step = grid_step_secs * info["sample_rate"]
                offsets = list(range(step, info["num_samples"], step))
                if offsets:
                    write_wav_cues(output_path, offsets)
                    print_step(f"Wrote {len(offsets)} splice marker(s)")

        print_step(f"Done — 1 reel written to {target_folder}")

    else:  # per_file
        for i, src in enumerate(files):
            name = _REEL_NAMES[i]
            target_file = target_folder / f"{name}{ext}"
            print_step(src)
            if not target_file.exists() or overwrite:
                convert_file(src, str(target_file), device, overwrite, normalize)

            if splice_mode == "passthrough" and Path(src).suffix.lower() == ".wav":
                src_info = read_wav_info(Path(src))
                cues = read_wav_cues(Path(src))
                if cues and src_info["sample_rate"] and src_info["sample_rate"] != _TARGET_SR:
                    scale = _TARGET_SR / src_info["sample_rate"]
                    cues = [int(c * scale) for c in cues]
                if cues:
                    write_wav_cues(target_file, cues)
                    print_step(f"  → copied {len(cues)} splice marker(s)")
            elif splice_mode == "grid":
                info = read_wav_info(target_file)
                step = grid_step_secs * info["sample_rate"]
                offsets = list(range(step, info["num_samples"], step))
                if offsets:
                    write_wav_cues(target_file, offsets)
                    print_step(f"  → wrote {len(offsets)} splice marker(s)")

        print_step(f"Done — {len(files)} reel(s) written to {target_folder}")


def describe_output(device):
    return "Files in root: mg1.wav–mgw.wav (32 reels max), 32-bit float stereo 48 kHz"
