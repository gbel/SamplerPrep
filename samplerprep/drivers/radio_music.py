"""Music Thing Modular Radio Music driver."""

import os
import shutil
import sys
from pathlib import Path

import questionary
from questionary import Choice

from samplerprep.core import (
    EXT_OTHER,
    EXT_RAW,
    ask_int,
    convert_file,
    find_files,
    getch,
    print_step,
)

MAX_FILES_PER_FOLDER = 48
MAX_FOLDERS = 16
MAX_FILES_PER_VOLUME = MAX_FILES_PER_FOLDER * MAX_FOLDERS  # 768
SETTINGS_FILE = "settings.txt"


# ── Settings helpers ──────────────────────────────────────────────────────────


def read_settings(path) -> dict:
    """Parse a settings.txt file into a dict of string values. Returns {} if missing."""
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return {}
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def write_settings(path, settings):
    with open(path, "w") as f:
        for k, v in settings.items():
            f.write(f"{k}={v}\n")


def get_profile(profiles, which_profile):
    default_profile = next((p for p in profiles if p["_name"] == "default"), profiles[0])
    profile = default_profile.copy()
    profile.update(profiles[which_profile])
    del profile["_name"]
    return profile


def detect_profile(settings_dict: dict, profiles: list) -> str | None:
    """Return the _name of the first profile whose merged settings match settings_dict."""
    for i, p in enumerate(profiles):
        merged = get_profile(profiles, i)
        merged.pop("description", None)
        comparable = {k: str(v) for k, v in merged.items()}
        candidate = {k: v for k, v in settings_dict.items() if k != "description"}
        if comparable == candidate:
            return p["_name"]
    return None


def create_settings_profile(config):
    """Interactive wizard to build and save a new settings profile to config.json."""
    import json

    profiles = config["profiles"]
    builtin_names = {"default", "oneshots", "immediate"}

    print_step("── Settings Profile: Name ──")
    while True:
        name = (questionary.text("Profile name:").ask() or "").strip()
        if not name:
            print_step("⚠  Name cannot be empty")
            continue
        existing = next((p for p in profiles if p["_name"] == name), None)
        if existing:
            if name in builtin_names:
                print_step(f'⚠  "{name}" is a built-in profile and cannot be overwritten')
                continue
            if not questionary.confirm(f'"{name}" already exists. Overwrite?', default=False).ask():
                continue
        break

    p = {"_name": name}

    print_step("── Settings Profile: Playback ──")
    p["Looping"] = questionary.select(
        "Playback:",
        choices=[
            Choice("Loop continuously", value=1),
            Choice("Play once and stop", value=0),
        ],
    ).ask()

    print_step("── Settings Profile: Channel control ──")
    p["ChanPotImmediate"] = int(
        questionary.confirm("Station knob takes effect immediately?", default=True).ask()
    )
    p["ChanCVImmediate"] = int(
        questionary.confirm("Station CV takes effect immediately?", default=True).ask()
    )

    print_step("── Settings Profile: Start / Pitch mode ──")
    pitch = questionary.select(
        "START input mode:",
        choices=[
            Choice("Position mode  — START controls playback position", value=0),
            Choice(
                "Pitch mode     — START controls speed/pitch, reset replays from start",
                value=1,
            ),
        ],
    ).ask()
    p["pitchMode"] = pitch

    if pitch:
        p["rootNote"] = questionary.select(
            "Root note (pitch at original speed):",
            choices=[
                Choice("C2  (MIDI 36)", value=36),
                Choice("C3  (MIDI 48)", value=48),
                Choice("C4 / middle C  (MIDI 60)", value=60),
                Choice("C5  (MIDI 72)", value=72),
                Choice("C6  (MIDI 84)", value=84),
            ],
        ).ask()
        p["noteRange"] = questionary.select(
            "Pitch range:",
            choices=[
                Choice("1 octave   (12 semitones)", value=12),
                Choice("2 octaves  (24 semitones)", value=24),
                Choice("3 octaves  (36 semitones)", value=36),
                Choice("~3¼ octaves  (39 semitones, default)", value=39),
                Choice("4 octaves  (48 semitones)", value=48),
            ],
        ).ask()
        p["quantiseNoteCV"] = int(
            questionary.confirm("Quantise pitch CV to semitones?", default=True).ask()
        )
        p["quantiseNotePot"] = int(
            questionary.confirm("Quantise pitch knob to semitones?", default=True).ask()
        )
    else:
        p["StartPotImmediate"] = int(
            questionary.confirm("Start position knob immediate?", default=False).ask()
        )
        p["StartCVImmediate"] = int(
            questionary.confirm("Start position CV immediate?", default=False).ask()
        )
        p["StartCVDivider"] = ask_int(
            "Start CV resolution divider (1=finest, 255=coarsest)", 2, 1, 255
        )

    print_step("── Settings Profile: Click reduction ──")
    mute = questionary.confirm(
        "Fade audio on channel change to reduce clicks?", default=False
    ).ask()
    p["MUTE"] = int(mute)
    if mute:
        p["DECLICK"] = ask_int("Fade duration in ms", 15, 1, 9999)

    print_step("── Settings Profile: Display ──")
    p["ShowMeter"] = questionary.select(
        "LED display:",
        choices=[
            Choice("VU meter", value=1),
            Choice("Binary bank number", value=0),
        ],
    ).ask()
    p["meterHIDE"] = ask_int("Hide meter after (ms)", 2000, 0, 99999)

    print_step("── Summary ──")
    for k, v in p.items():
        if k != "_name":
            sys.stdout.write(f"    {k}={v}\r\n")
    sys.stdout.flush()

    if not questionary.confirm("Save this profile?", default=True).ask():
        print_step("Discarded.")
        return

    profiles[:] = [x for x in profiles if x["_name"] != name]
    profiles.append(p)
    config["profiles"] = profiles
    Path("config.json").write_text(json.dumps(config, indent=4))
    print_step(f'Settings profile "{name}" saved.')


# ── Volume helpers ─────────────────────────────────────────────────────────────


def analyse(vol_root: Path) -> tuple[int, int]:
    """Return (used_slots, available_slots) for an existing volume root."""
    used = 0
    for i in range(MAX_FOLDERS):
        folder = vol_root / str(i)
        if folder.is_dir():
            used += sum(1 for f in folder.glob("*.raw") if f.stem.isdigit())
    available = MAX_FILES_PER_VOLUME - used
    return used, available


def create_skeleton(vol_root, empty_folder, overwrite_placeholders=False):
    """Create all 16 numbered folders and seed each with empty_folder placeholder files."""
    src = Path(empty_folder)
    placeholder_files = list(src.glob("*.raw")) + list(src.glob("*.RAW"))
    for i in range(MAX_FOLDERS):
        folder = vol_root / str(i)
        folder.mkdir(parents=True, exist_ok=True)
        for src_file in placeholder_files:
            dst = folder / src_file.name
            if overwrite_placeholders or not dst.exists():
                shutil.copy2(str(src_file), str(dst))


# ── Process ───────────────────────────────────────────────────────────────────


def process(
    source_folder,
    target_folder,
    device,
    config,
    overwrite,
    normalize,
    *,
    key,
    settings,
    empty_folder,
    overwrite_placeholders=False,
):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    files_in_set = len(files)
    print_step(f"Found {files_in_set} files")

    current_folder = 0
    current_file = 0

    vol_root = target_folder
    vol_root.mkdir(parents=True, exist_ok=True)
    write_settings(str(vol_root / SETTINGS_FILE), settings)
    create_skeleton(vol_root, empty_folder, overwrite_placeholders)

    if overwrite_placeholders:
        for folder_idx in range(MAX_FOLDERS):
            folder_path = vol_root / str(folder_idx)
            n_real = sum(1 for f in folder_path.glob("*.raw") if f.stem.isdigit())
            if n_real < MAX_FILES_PER_FOLDER:
                current_folder = folder_idx
                current_file = n_real
                break

    path = vol_root / str(current_folder)
    folders_started: set[int] = set()

    for f in files:
        print_step(f)
        if current_folder not in folders_started:
            for placeholder in path.glob("*.raw"):
                if not placeholder.stem.isdigit():
                    placeholder.unlink()
            folders_started.add(current_folder)
        target_file = str(path / f"{current_file}.raw")
        _, ext = os.path.splitext(f)

        if not Path(target_file).exists():
            if ext.upper() in EXT_OTHER:
                convert_file(f, target_file, device, overwrite, normalize)
            else:
                shutil.copy2(f, target_file)

        current_file += 1

        if current_file == MAX_FILES_PER_FOLDER:
            current_file = 0
            current_folder += 1
            if current_folder == MAX_FOLDERS:
                print_step("⚠  Folder is full — remaining files will not be processed")
                break
            path = vol_root / str(current_folder)

    print_step(f"Done — written to {target_folder}")


def describe_output(device):
    s = device["structure"]
    return (
        f"Folders 0–{s['max_folders'] - 1}, "
        f"up to {s['max_files_per_folder']} files each "
        f"(max {s['max_files_per_folder'] * s['max_folders']} total)"
    )


# ── Preview browser ───────────────────────────────────────────────────────────


def raw_duration(path):
    """Return duration in seconds for a 16-bit mono 44100 Hz RAW file."""
    return Path(path).stat().st_size / (44100 * 2)


def play_raw(path):
    """Start playing a RAW file via sox/play in the background. Returns Popen handle."""
    import subprocess

    cmd = [
        "play",
        "-t",
        "raw",
        "-r",
        "44100",
        "-e",
        "signed-integer",
        "-b",
        "16",
        "-c",
        "1",
        str(path),
    ]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def render_preview(card_folder, folder_idx, cursor, all_files, playing_idx):
    NL = "\r\n"
    out = ["\033[2J\033[H"]
    divider = "─" * 54
    out.append(f"  Preview: {card_folder.name}   Folder {folder_idx + 1} / {MAX_FOLDERS}{NL}")
    out.append(f"  {divider}{NL}")
    if not all_files:
        out.append(f"  (empty folder){NL}")
    for i, f in enumerate(all_files):
        is_real = f.stem.isdigit()
        marker = "▶" if i == cursor else " "
        if is_real:
            secs = raw_duration(f)
            dur = f"{secs:.1f}s"
            playing_tag = "  ♪" if (i == playing_idx) else ""
            out.append(f"  {marker} {f.name:<12}  {dur}{playing_tag}{NL}")
        else:
            secs = raw_duration(f)
            out.append(f"  {marker} {f.name:<12}  {secs:.1f}s{NL}")
    out.append(f"  {divider}{NL}")
    out.append(f"  [↑/↓] navigate   [SPACE] play/stop   [←/→] folder   [D] delete   [Q] quit{NL}")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def preview(card_folder: Path):
    """Interactive audio preview browser for a Radio Music card folder."""
    folder_idx = 0
    cursor = 0
    proc = None
    playing_idx = None

    try:
        while True:
            folder = card_folder / str(folder_idx)
            real_files = sorted(
                (f for f in folder.glob("*.raw") if f.stem.isdigit()),
                key=lambda f: int(f.stem),
            )
            placeholders = sorted(f for f in folder.glob("*.raw") if not f.stem.isdigit())
            all_files = list(real_files) + list(placeholders)

            cursor = max(0, min(cursor, len(all_files) - 1))

            if proc is not None and proc.poll() is not None:
                proc = None
                playing_idx = None

            render_preview(card_folder, folder_idx, cursor, all_files, playing_idx)

            key = getch()

            if key in (b"q", b"Q", b"\x1b"):
                break
            elif key in (b"\x1b[A", b"k"):
                cursor = max(0, cursor - 1)
            elif key in (b"\x1b[B", b"j"):
                cursor = min(len(all_files) - 1, cursor + 1)
            elif key == b"\x1b[D":
                if proc:
                    proc.terminate()
                    proc = None
                    playing_idx = None
                folder_idx = (folder_idx - 1) % MAX_FOLDERS
                cursor = 0
            elif key == b"\x1b[C":
                if proc:
                    proc.terminate()
                    proc = None
                    playing_idx = None
                folder_idx = (folder_idx + 1) % MAX_FOLDERS
                cursor = 0
            elif key == b" ":
                if proc and proc.poll() is None:
                    proc.terminate()
                    proc.wait()
                    proc = None
                    playing_idx = None
                elif all_files:
                    proc = play_raw(all_files[cursor])
                    playing_idx = cursor
            elif key in (b"d", b"D"):
                if all_files:
                    target = all_files[cursor]
                    if proc and playing_idx == cursor:
                        proc.terminate()
                        proc = None
                        playing_idx = None
                    target.unlink()
    finally:
        if proc:
            proc.terminate()
            proc.wait()
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
