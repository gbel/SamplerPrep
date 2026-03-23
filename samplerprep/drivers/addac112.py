"""ADDAC112 VC Looper & Granular Processor driver.

Output: BANK0/ folder containing WAV/, DELETED/, SETTINGS.CFG, SCALES.CFG, and 0.CFG.
Format: user-configurable (channels, sample rate, bit depth chosen at wizard time).
Storage: microSD.
Max files per bank: 99.
Recommended max bank size: ~60 MB total WAV content.

File naming: 1_<originalname>.wav, 2_<originalname>.wav, … (1-indexed, module sorts by prefix).
BANK folder name matches BANK\\d+.* — firmware ignores the suffix, so BANK0 is valid.

SETTINGS.CFG bit_depth encoding is non-obvious: 0=24-bit, 1=8-bit, 2=16-bit.
This inversion is documented inline wherever the value is set.

NOTE: CFG file formats and scale data are derived from the ADDAC112 user manual (pp. 40–43).
Verify against firmware updates before use on hardware.
"""

import subprocess
from pathlib import Path

import questionary
from questionary import Choice

from samplerprep.core import EXT_OTHER, EXT_RAW, find_files, pick_files, print_step

MAX_FILES_PER_BANK = 99
MAX_BANK_SIZE_BYTES = 60 * 1024 * 1024  # ~60 MB

# ffmpeg codec for each user-visible bit depth choice
_CODEC_MAP = {8: "pcm_u8", 16: "pcm_s16le", 24: "pcm_s24le"}

# SETTINGS.CFG bit_depth field uses an inverted encoding: 0=24-bit, 1=8-bit, 2=16-bit
_BIT_DEPTH_FIELD = {8: 1, 16: 2, 24: 0}

# ── Scale data (manual p. 43) ──────────────────────────────────────────────────

_DEFAULT_SCALES: list[tuple[str, list[float], bool]] = [
    (
        "CHROMATIC",
        [
            1,
            1.05946,
            1.12246,
            1.18921,
            1.25992,
            1.33483,
            1.41421,
            1.49831,
            1.58740,
            1.68179,
            1.78180,
            1.88775,
        ],
        True,
    ),
    ("MAJOR", [1, 1.12246, 1.25992, 1.33483, 1.49831, 1.68179, 1.88775], True),
    ("MINOR", [1, 1.12246, 1.18921, 1.33483, 1.49831, 1.58740, 1.88775], True),
    ("PENTA MAJOR", [1, 1.12246, 1.25992, 1.49831, 1.68179], True),
    ("PENTA MINOR", [1, 1.12246, 1.33483, 1.49831, 1.78180], True),
    ("TIZITA MINOR", [1, 1.12246, 1.18921, 1.33483, 1.41421], True),
    ("OCTAVES", [1], True),
]

# Named custom presets the wizard offers (manual p. 43 extras)
_EXTRA_SCALES: dict[str, tuple[list[float], bool]] = {
    "HARMONIC": ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16], False),
    "WELL TUNED": (
        [
            1,
            1.10742,
            1.12500,
            1.14844,
            1.31250,
            1.29199,
            1.47656,
            1.50000,
            1.53125,
            1.75000,
            1.72266,
            1.96875,
        ],
        True,
    ),
}

# ── SETTINGS.CFG schema (manual p. 40) ────────────────────────────────────────

_SETTINGS_DEFAULTS: dict[str, float | int] = {
    "dry_vol_pre_post": 0,
    "quant_mode": 0,
    "pause_mode": 0,
    "overdub_origin": 0,
    "scales_set": 0,
    "keep_grain_pitch": 1,
    "samplerate": 44100,
    "resampling_pitch": 1,
    "pitch_range_octaves": 2.5,
    "clocked_mode": 0,
    "trigger_size_ms": 10,
    "stereo": 1,
    # IMPORTANT: bit_depth encoding is inverted — 0=24-bit, 1=8-bit, 2=16-bit
    "bit_depth": 2,
    "rec_dir_en": 0,
    "anti_alias": 1,
    "grain_dev_mode": 1,
    "grain_pan_mode": 0,
    "vols_in_presets": 255,
}

# ── Preset .CFG defaults (manual pp. 41–42) ───────────────────────────────────

_PRESET_DEFAULTS: dict[str, float | int | str] = {
    "pos": 0.0,
    "pos_quant": 0,
    "pos_dev": 0.0,
    "length": 8969,
    "length_quant": 0,
    "length_dev": 0.0,
    "delay": 0.0,
    "delay_quant": 8,
    "delay_dev": 0.0,
    "direction": 1.0,
    "repeat_mode": 1,
    "repeats": 0.0,
    "vol_min": 1.0,
    "vol_dev": 0.0,
    "n_grains": 4,
    "attack": 0.2,
    "decay": 0.8,
    "grain_pitch": 1.0,
    "grain_pan": 0.5,
    "feedback": 0.0,
    "selected_loop": 0,
    "quantizer": 7,
    "loop_pitch": 1.0,
    "overdub_decay": 1.0,
    "vol_in": 1.0,
    "vol_loop": 1.0,
    "vol_grains": 1.0,
    "rec_prob": 1.0,
    "rec_delay": 0.0,
    "rec_delay_dev": 0.0,
    "rec_mode": 1,
    "rec_sync": 1,
    "pause_retrigger": 0,
    "on_loop_change_mode": 0,
    "loop_play_mode": 0,
    "loop_direction": 1,
    "loop_list": "{0,}",
}


# ── Wizard ─────────────────────────────────────────────────────────────────────


def wizard_settings() -> dict:
    """Interactive prompts for ADDAC112 bank configuration.

    Returns a settings dict with all keys needed by process() and the CFG writers.
    """
    channels = questionary.select(
        "Channels:",
        choices=[Choice("Mono", value=1), Choice("Stereo", value=2)],
    ).ask()

    samplerate = questionary.select(
        "Sample rate:",
        choices=[
            Choice("8000 Hz", value=8000),
            Choice("11025 Hz", value=11025),
            Choice("16000 Hz", value=16000),
            Choice("22050 Hz", value=22050),
            Choice("36000 Hz", value=36000),
            Choice("44100 Hz  (default)", value=44100),
            Choice("48000 Hz", value=48000),
            Choice("96000 Hz", value=96000),
        ],
        default=Choice("44100 Hz  (default)", value=44100),
    ).ask()

    bit_depth = questionary.select(
        "Bit depth:",
        choices=[
            Choice("8-bit", value=8),
            Choice("16-bit  (default)", value=16),
            Choice("24-bit  (halves available recording time)", value=24),
        ],
        default=Choice("16-bit  (default)", value=16),
    ).ask()

    dry_vol_pre_post = questionary.select(
        "Dry volume position:",
        choices=[Choice("Pre-FX", value=0), Choice("Post-FX", value=1)],
    ).ask()

    pause_mode = questionary.select(
        "Pause button mode:",
        choices=[Choice("Toggle", value=0), Choice("Momentary", value=1)],
    ).ask()

    keep_grain_pitch = questionary.select(
        "Grain pitch on loop change:",
        choices=[Choice("Keep pitch", value=1), Choice("Retune to loop pitch", value=0)],
    ).ask()

    grain_pan_mode = questionary.select(
        "Grain pan mode:",
        choices=[Choice("Fixed", value=0), Choice("Travel", value=1)],
    ).ask()

    grain_dev_mode = questionary.select(
        "Grain deviation mode:",
        choices=[Choice("Random", value=0), Choice("Spread", value=1)],
    ).ask()

    custom_scales: list[tuple[str, list[float], bool]] = []
    scale_choice = questionary.select(
        "Scales:",
        choices=[
            Choice("Use factory defaults only", value="defaults"),
            Choice("Add custom scale presets", value="custom"),
        ],
    ).ask()

    if scale_choice == "custom":
        scale_names = list(_EXTRA_SCALES.keys())
        selected = questionary.checkbox(
            "Select custom scale presets (fills custom slots 1–7):",
            choices=[Choice(name, value=name) for name in scale_names],
        ).ask()
        for name in selected or []:
            ratios, per_octave = _EXTRA_SCALES[name]
            custom_scales.append((name, ratios, per_octave))

    return {
        "channels": channels,
        "samplerate": samplerate,
        "bit_depth_user": bit_depth,  # raw user choice: 8 / 16 / 24
        # SETTINGS.CFG uses inverted encoding: 0=24-bit, 1=8-bit, 2=16-bit
        "bit_depth": _BIT_DEPTH_FIELD[bit_depth],
        "stereo": 1 if channels == 2 else 0,
        "dry_vol_pre_post": dry_vol_pre_post,
        "pause_mode": pause_mode,
        "keep_grain_pitch": keep_grain_pitch,
        "grain_pan_mode": grain_pan_mode,
        "grain_dev_mode": grain_dev_mode,
        "custom_scales": custom_scales,
    }


# ── Core processing ────────────────────────────────────────────────────────────


def process(  # noqa: PLR0913
    source_folder, target_folder: Path, device, config, overwrite, normalize, settings=None
):
    """Convert audio and build the BANK0/ folder structure for the ADDAC112."""
    if settings is None:
        settings = {}

    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    if not files:
        print_step("No files found.")
        return

    files = pick_files(files)
    if not files:
        print_step("No files selected.")
        return

    if len(files) > MAX_FILES_PER_BANK:
        print_step(
            f"⚠  {len(files)} files — ADDAC112 supports max {MAX_FILES_PER_BANK} per bank. "
            "Reduce the selection and try again."
        )
        return

    bank_path = target_folder / "BANK0"
    wav_dir = bank_path / "WAV"
    deleted_dir = bank_path / "DELETED"
    wav_dir.mkdir(parents=True, exist_ok=True)
    deleted_dir.mkdir(parents=True, exist_ok=True)

    # Resolve conversion parameters from wizard settings (fall back to device spec defaults)
    samplerate = settings.get("samplerate", device["ffmpeg"]["sample_rate"])
    channels = settings.get("channels", device["ffmpeg"]["channels"])
    bit_depth_user = settings.get("bit_depth_user", 16)
    codec = _CODEC_MAP.get(bit_depth_user, "pcm_s16le")

    for idx, src in enumerate(files, start=1):
        stem = Path(src).stem
        dst = wav_dir / f"{idx}_{stem}.wav"
        print_step(Path(src).name)
        if not dst.exists() or overwrite:
            _convert(src, str(dst), samplerate, channels, codec, overwrite)

    # Size guard
    total_bytes = sum(f.stat().st_size for f in wav_dir.glob("*.wav"))
    if total_bytes > MAX_BANK_SIZE_BYTES:
        mb = total_bytes / (1024 * 1024)
        limit_mb = MAX_BANK_SIZE_BYTES // (1024 * 1024)
        print_step(
            f"⚠  WAV folder is {mb:.1f} MB — exceeds the recommended {limit_mb} MB limit. "
            "Consider a lower sample rate or bit depth."
        )

    write_settings_cfg(bank_path, settings)
    write_scales_cfg(bank_path, settings)
    write_preset_cfg(bank_path, 0, settings)

    print_step(f"Done — {len(files)} file(s) written to {bank_path}")


def _convert(src: str, dst: str, samplerate: int, channels: int, codec: str, overwrite: bool):
    """Run ffmpeg with full metadata stripping (-map_metadata -1 -fflags +bitexact)."""
    cmd = [
        "ffmpeg",
        "-i",
        src,
        *(["-y"] if overwrite else []),
        "-ar",
        str(samplerate),
        "-ac",
        str(channels),
        "-acodec",
        codec,
        "-map_metadata",
        "-1",
        "-fflags",
        "+bitexact",
        "-loglevel",
        "error",
        "-stats",
        dst,
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


# ── CFG writers ────────────────────────────────────────────────────────────────


def write_settings_cfg(bank_path: Path, settings: dict) -> None:
    """Write SETTINGS.CFG — flat key=value, one key per line."""
    cfg = dict(_SETTINGS_DEFAULTS)
    # Apply user choices (keys that overlap SETTINGS_DEFAULTS)
    for key in (
        "stereo",
        "samplerate",
        "bit_depth",
        "dry_vol_pre_post",
        "pause_mode",
        "keep_grain_pitch",
        "grain_pan_mode",
        "grain_dev_mode",
    ):
        if key in settings:
            cfg[key] = settings[key]

    lines = [f"{k}={v}" for k, v in cfg.items()]
    (bank_path / "SETTINGS.CFG").write_text("\n".join(lines) + "\n")


def write_scales_cfg(bank_path: Path, settings: dict) -> None:
    """Write SCALES.CFG with Default and Custom sections, each containing exactly 7 entries."""
    custom_input: list[tuple[str, list[float], bool]] = settings.get("custom_scales", [])

    # Pad or trim custom section to exactly 7 entries using defaults as filler
    custom_section: list[tuple[str, list[float], bool]] = list(custom_input[:7])
    while len(custom_section) < 7:
        filler = _DEFAULT_SCALES[len(custom_section)]
        custom_section.append(filler)

    lines: list[str] = ["Default"]
    for name, ratios, per_octave in _DEFAULT_SCALES:
        lines.append(_scale_line(name, ratios, per_octave))

    lines.append("")
    lines.append("Custom")
    for name, ratios, per_octave in custom_section:
        lines.append(_scale_line(name, ratios, per_octave))

    (bank_path / "SCALES.CFG").write_text("\n".join(lines) + "\n")


def _scale_line(name: str, ratios: list[float], per_octave: bool) -> str:
    ratio_str = ",".join(str(r) for r in ratios)
    octave_val = 1 if per_octave else 0
    return f"{name}={{ratios={{{ratio_str}}},per_octave={octave_val}}}"


def write_preset_cfg(bank_path: Path, preset_index: int, settings: dict) -> None:
    """Write <preset_index>.CFG with safe defaults, mirroring format settings from SETTINGS.CFG."""
    cfg = dict(_PRESET_DEFAULTS)
    # Mirror global format settings into the preset so the module loads correctly
    if "samplerate" in settings:
        cfg["samplerate"] = settings["samplerate"]
    if "stereo" in settings:
        cfg["stereo"] = settings["stereo"]
    if "bit_depth" in settings:
        # Preserve the SETTINGS.CFG encoding (0=24-bit, 1=8-bit, 2=16-bit)
        cfg["bit_depth"] = settings["bit_depth"]

    lines = [f"{k}={v}" for k, v in cfg.items()]
    (bank_path / f"{preset_index}.CFG").write_text("\n".join(lines) + "\n")


# ── Describe output ────────────────────────────────────────────────────────────


def describe_output(device) -> str:
    max_files = device["structure"].get("max_files_per_bank", MAX_FILES_PER_BANK)
    max_mb = device["structure"].get("max_bank_size_mb", 60)
    return (
        f"BANK0/WAV/ with up to {max_files} numbered WAV files — "
        f"format chosen at wizard time — max ~{max_mb} MB total. "
        "SETTINGS.CFG, SCALES.CFG, and seed preset 0.CFG written per bank."
    )
