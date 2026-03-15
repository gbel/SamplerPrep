#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import termios
import tty
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import questionary
from questionary import Choice

EXT_RAW = ".RAW"
EXT_OTHER = [".WAV", ".AIF", ".MP3", ".MP4", ".OGG", ".M4A"]
SETTINGS_FILE = "settings.txt"

MAX_FILES_PER_FOLDER = 48
MAX_FOLDERS = 16
MAX_FILES_PER_VOLUME = MAX_FILES_PER_FOLDER * MAX_FOLDERS  # 768


# @see http://stackoverflow.com/a/12886818
def unzip(source_filename, dest_dir):
    zipfile.ZipFile(source_filename).extractall(dest_dir)


# @see http://stackoverflow.com/q/4028697
def dlfile(url, filename=""):
    try:
        f = urlopen(url)
        if filename == "":
            filename = os.path.basename(url)
        with open(filename, "wb") as local_file:
            local_file.write(f.read())
    except HTTPError as e:
        print_step(f"HTTP Error: {e.code} {url}")
    except URLError as e:
        print_step(f"URL Error: {e.reason} {url}")


# @see http://stackoverflow.com/a/2186565
def find_files(path, extensions):
    matches = []
    for root, dirnames, filenames in os.walk(path, topdown=False):
        for filename in filenames:
            _, ext = os.path.splitext(filename)
            if ext.upper() in extensions:
                p = os.path.join(root, filename)
                if "__MACOSX/" not in p:
                    matches.append(p)
    return matches


def pick_subfolder(base_path: Path) -> Path:
    """If base_path has immediate subdirectories, offer a picker; otherwise return it as-is."""
    subdirs = sorted(d for d in base_path.iterdir() if d.is_dir())
    if not subdirs:
        return base_path
    choices = [Choice(title=d.name, value=d) for d in subdirs]
    choices.append(Choice(title=f"All files in {base_path.name}/", value=base_path))
    return questionary.select("Select source folder:", choices=choices).ask()


def print_step(s):
    sys.stdout.write(f">>> {s}\r\n")
    sys.stdout.flush()


def load_config(path):
    return json.loads(Path(path).read_text())


def load_dotenv(path=".env"):
    """Parse a .env file and return a dict of key=value pairs."""
    env = {}
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env


def getch():
    """Read one keypress in raw mode. Returns bytes; arrow keys return 3-byte sequences."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.buffer.read(1)
        if ch == b"\x1b":
            ch2 = sys.stdin.buffer.read(1)
            if ch2 == b"[":
                ch3 = sys.stdin.buffer.read(1)
                return b"\x1b[" + ch3
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def raw_duration(path):
    """Return duration in seconds for a 16-bit mono 44100 Hz RAW file."""
    return Path(path).stat().st_size / (44100 * 2)


def play_raw(path):
    """Start playing a RAW file via sox/play in the background. Returns Popen handle."""
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
        start_new_session=True,  # detach from our controlling tty
    )


def render_preview(card_folder, folder_idx, cursor, all_files, playing_idx):
    """Clear screen and render the preview browser state."""
    # Use \r\n throughout — OPOST may be disabled (e.g. left so by questionary/prompt_toolkit)
    # so we cannot rely on \n being translated to CR+LF automatically.
    NL = "\r\n"
    out = ["\033[2J\033[H"]  # clear screen + cursor home, sent atomically with the frame
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


def preview_card_folder(card_folder):
    """Interactive audio preview browser for a card folder."""
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
            elif key in (b"\x1b[A", b"k"):  # up
                cursor = max(0, cursor - 1)
            elif key in (b"\x1b[B", b"j"):  # down
                cursor = min(len(all_files) - 1, cursor + 1)
            elif key == b"\x1b[D":  # left → prev folder
                if proc:
                    proc.terminate()
                    proc = None
                    playing_idx = None
                folder_idx = (folder_idx - 1) % MAX_FOLDERS
                cursor = 0
            elif key == b"\x1b[C":  # right → next folder
                if proc:
                    proc.terminate()
                    proc = None
                    playing_idx = None
                folder_idx = (folder_idx + 1) % MAX_FOLDERS
                cursor = 0
            elif key == b" ":  # space → play / stop
                if proc and proc.poll() is None:
                    proc.terminate()
                    proc.wait()
                    proc = None
                    playing_idx = None
                elif all_files:
                    proc = play_raw(all_files[cursor])
                    playing_idx = cursor
            elif key in (b"d", b"D"):  # delete current file
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


def read_settings(path) -> dict:
    """Parse a settings.txt file into a dict of string values. Returns {} if file is missing."""
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
    # @see http://stackoverflow.com/a/26853961
    profile = default_profile.copy()
    profile.update(profiles[which_profile])
    del profile["_name"]
    return profile


def detect_profile(settings_dict: dict, profiles: list) -> str | None:
    """Return the _name of the first profile whose merged settings match settings_dict,
    or None. Excludes 'description' and converts merged int values to strings."""
    for i, p in enumerate(profiles):
        merged = get_profile(profiles, i)
        merged.pop("description", None)
        comparable = {k: str(v) for k, v in merged.items()}
        candidate = {k: v for k, v in settings_dict.items() if k != "description"}
        if comparable == candidate:
            return p["_name"]
    return None


def convert_file(source_file, target_file, overwrite, normalize=False):
    cmd = [
        "ffmpeg",
        "-i",
        source_file,
        *(["-y"] if overwrite else []),
        "-f",
        "s16le",
        "-ac",
        "1",
        "-loglevel",
        "error",
        "-stats",
        "-ar",
        "44100",
        "-acodec",
        "pcm_s16le",
        *(["-af", "loudnorm=I=-16:TP=-1:LRA=11"] if normalize else []),
        target_file,
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


def set_extension(filename, extension):
    name, _ = os.path.splitext(filename)
    return name + extension


def ask_int(prompt, default, min_val, max_val):
    """Prompt for an integer in [min_val, max_val], re-prompting on bad input."""
    while True:
        raw = questionary.text(f"{prompt} [{default}]:").ask()
        if raw is None:
            return default
        if raw.strip() == "":
            return default
        try:
            v = int(raw.strip())
            if min_val <= v <= max_val:
                return v
        except ValueError:
            pass
        print_step(f"⚠  Enter a whole number between {min_val} and {max_val}")


def create_settings_profile(config):
    """Interactive wizard to build and save a new settings profile to config.json."""
    profiles = config["profiles"]
    builtin_names = {"default", "oneshots", "immediate"}

    # ── Section 1: Name ───────────────────────────────────────────────────
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

    # ── Section 2: Playback ───────────────────────────────────────────────
    print_step("── Settings Profile: Playback ──")
    p["Looping"] = questionary.select(
        "Playback:",
        choices=[
            Choice("Loop continuously", value=1),
            Choice("Play once and stop", value=0),
        ],
    ).ask()

    # ── Section 3: Channel control ────────────────────────────────────────
    print_step("── Settings Profile: Channel control ──")
    p["ChanPotImmediate"] = int(
        questionary.confirm("Station knob takes effect immediately?", default=True).ask()
    )
    p["ChanCVImmediate"] = int(
        questionary.confirm("Station CV takes effect immediately?", default=True).ask()
    )

    # ── Section 4: Start / Pitch mode ─────────────────────────────────────
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

    # ── Section 5: Click reduction ────────────────────────────────────────
    print_step("── Settings Profile: Click reduction ──")
    mute = questionary.confirm(
        "Fade audio on channel change to reduce clicks?", default=False
    ).ask()
    p["MUTE"] = int(mute)
    if mute:
        p["DECLICK"] = ask_int("Fade duration in ms", 15, 1, 9999)

    # ── Section 6: Display ────────────────────────────────────────────────
    print_step("── Settings Profile: Display ──")
    p["ShowMeter"] = questionary.select(
        "LED display:",
        choices=[
            Choice("VU meter", value=1),
            Choice("Binary bank number", value=0),
        ],
    ).ask()
    p["meterHIDE"] = ask_int("Hide meter after (ms)", 2000, 0, 99999)

    # ── Summary + save ────────────────────────────────────────────────────
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


def find_mounted_volumes():
    """Return sorted list of directories under /Volumes."""
    volumes = Path("/Volumes")
    if not volumes.is_dir():
        return []
    return sorted(p for p in volumes.iterdir() if p.is_dir())


def run_rsync(src, dst, extra_flags):
    """Run rsync from src/ to dst/ with extra_flags."""
    cmd = ["rsync", "-av", "--progress"] + extra_flags + [f"{src}/", f"{dst}/"]
    subprocess.run(cmd, check=True)


def analyse_vol_root(vol_root):
    """Return (used_slots, available_slots) for an existing volume root."""
    used = 0
    for i in range(MAX_FOLDERS):
        folder = vol_root / str(i)
        if folder.is_dir():
            used += sum(1 for f in folder.glob("*.raw") if f.stem.isdigit())
    available = MAX_FILES_PER_VOLUME - used
    return used, available


def freesound_search(query, api_key, page=1, page_size=15):
    """Return parsed JSON from the Freesound text-search endpoint."""
    params = urlencode(
        {
            "query": query,
            "token": api_key,
            "fields": "id,name,duration,tags,license,previews",
            "page": page,
            "page_size": page_size,
        }
    )
    url = f"https://freesound.org/apiv2/search/text/?{params}"
    with urlopen(url) as r:
        return json.loads(r.read().decode())


def download_freesound_sounds(sounds, dest_folder, api_key):
    """Download HQ-MP3 previews for each selected sound into dest_folder."""
    dest_folder.mkdir(parents=True, exist_ok=True)
    for s in sounds:
        url = s["previews"]["preview-hq-mp3"]
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in s["name"])[:40]
        filename = dest_folder / f"{s['id']}_{safe_name}.mp3"
        req = Request(url, headers={"Authorization": f"Token {api_key}"})
        print_step(f"Downloading: {s['name']}")
        with urlopen(req) as r, open(filename, "wb") as f:
            f.write(r.read())


def create_skeleton(vol_root, empty_folder, overwrite_placeholders=False):
    """Create all 16 numbered folders and seed each with empty_folder placeholder files."""
    src = Path(empty_folder)
    placeholder_files = list(src.glob("*.raw")) + list(src.glob("*.RAW"))
    for i in range(MAX_FOLDERS):
        folder = vol_root / str(i)
        folder.mkdir(parents=True, exist_ok=True)
        for src in placeholder_files:
            dst = folder / src.name
            if overwrite_placeholders or not dst.exists():
                shutil.copy2(str(src), str(dst))


def process(
    source_folder,
    target_folder,
    key,
    settings,
    overwrite,
    empty_folder,
    overwrite_placeholders=False,
    normalize=False,
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
        # Existing folder — find the first empty slot so new files append after existing ones.
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
                convert_file(f, target_file, overwrite, normalize)
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


def main():
    config = load_config("config.json")
    profiles = config["profiles"]
    root_folder = Path(config["rootFolder"])
    root_folder.mkdir(parents=True, exist_ok=True)

    # ── Top-level action ──────────────────────────────────────────────────
    top_action = questionary.select(
        "What would you like to do?",
        choices=[
            "Prepare card folder",
            "Preview card folder",
            "Create Settings Profile",
            "Copy folder to SD card",
        ],
    ).ask()

    if top_action == "Preview card folder":
        folders = sorted(d.name for d in root_folder.iterdir() if d.is_dir())
        if not folders:
            sys.exit(f"No card folders found in {root_folder}")
        folder_name = questionary.select("Card folder to preview:", choices=folders).ask()
        preview_card_folder(root_folder / folder_name)
        return

    if top_action == "Create Settings Profile":
        create_settings_profile(config)
        return

    if top_action == "Copy folder to SD card":
        # ── A: Source card folder ─────────────────────────────────────────
        card_folders = sorted(d.name for d in root_folder.iterdir() if d.is_dir())
        if not card_folders:
            sys.exit(f"No card folders found in {root_folder}")
        folder_name = questionary.select("Card folder to copy:", choices=card_folders).ask()
        card_folder = root_folder / folder_name

        # ── B: Destination volume ─────────────────────────────────────────
        volumes = find_mounted_volumes()
        if not volumes:
            sys.exit("No volumes found at /Volumes.")
        vol_choice = questionary.select(
            "Destination volume:",
            choices=[Choice(title=f"{p.name}  ({p})", value=p) for p in volumes],
        ).ask()

        # ── C: Folder scope ───────────────────────────────────────────────
        bank_dirs = sorted(
            [p for p in card_folder.iterdir() if p.is_dir() and p.name.isdigit()],
            key=lambda p: int(p.name),
        )
        scope = questionary.select(
            "Folders to sync:",
            choices=[
                Choice("All folders", value="all"),
                Choice("Specific folders...", value="pick"),
            ],
        ).ask()

        if scope == "pick":
            folder_choices = [
                Choice(
                    title=f"Folder {p.name}  "
                    f"({sum(1 for f in p.glob('*.raw') if f.stem.isdigit())} files)",
                    value=p,
                )
                for p in bank_dirs
            ]
            selected_bank_dirs = questionary.checkbox(
                "Select folders to sync:", choices=folder_choices
            ).ask()
            if not selected_bank_dirs:
                sys.exit("No folders selected.")
        else:
            selected_bank_dirs = None  # None = all

        # ── D: Sync mode ──────────────────────────────────────────────────
        sync_mode = questionary.select(
            "Sync mode:",
            choices=[
                Choice(
                    "Add — copy new files, preserve everything already on card",
                    value="add",
                ),
                Choice(
                    "Replace — full sync, remove files not in source folder",
                    value="replace",
                ),
            ],
        ).ask()

        # ── E: Backup (replace only) ──────────────────────────────────────
        backup_path = None
        if sync_mode == "replace":
            if questionary.confirm("Back up the card before syncing?", default=True).ask():
                from datetime import datetime

                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_vol = "".join(c if c.isalnum() or c in "-_" else "_" for c in vol_choice.name)
                backup_path = root_folder / "backups" / f"{safe_vol}_{ts}"

        # ── F: Overview + confirmation ────────────────────────────────────
        print_step(f"Source      {card_folder}")
        print_step(f"Destination {vol_choice}")
        mode_label = "Add (--ignore-existing)" if sync_mode == "add" else "Replace (--delete)"
        print_step(f"Mode        {mode_label}")
        if backup_path:
            print_step(f"Backup      {backup_path}")
        if selected_bank_dirs:
            folder_nums = ", ".join(
                p.name for p in sorted(selected_bank_dirs, key=lambda p: int(p.name))
            )
            print_step(f"Folders     {folder_nums}")
        else:
            raw_files = find_files(str(card_folder), [".raw", ".RAW"])
            num_files = len(raw_files)
            num_folders = sum(1 for p in card_folder.iterdir() if p.is_dir() and p.name.isdigit())
            print_step(f"Files       {num_files} .raw files in {num_folders} folder(s)")
        if sync_mode == "replace":
            print_step("⚠  Files on the card not present in the source folder will be deleted")

        if not questionary.confirm("Proceed?", default=(sync_mode == "add")).ask():
            sys.exit("Aborted.")

        # ── G: Execute ────────────────────────────────────────────────────
        if backup_path:
            print_step(f"Backing up {vol_choice} → {backup_path} ...")
            run_rsync(vol_choice, backup_path, [])
            print_step(f"Backup complete: {backup_path}")

        extra = ["--ignore-existing"] if sync_mode == "add" else ["--delete"]
        if selected_bank_dirs:
            for bank_dir in sorted(selected_bank_dirs, key=lambda p: int(p.name)):
                dest_dir = vol_choice / bank_dir.name
                print_step(f"Syncing folder {bank_dir.name} → {dest_dir} ...")
                run_rsync(bank_dir, dest_dir, extra)
        else:
            print_step(f"Syncing {card_folder} → {vol_choice} ...")
            run_rsync(card_folder, vol_choice, extra)
        print_step("Done.")
        return

    # Save terminal settings before any questionary prompt so we can restore
    # them before process() runs (questionary disables ISIG, preventing Ctrl-C).
    _term_fd = sys.stdin.fileno()
    _saved_term = termios.tcgetattr(_term_fd)

    # ── Step 1: Output folder ─────────────────────────────────────────────
    folder_action = questionary.select(
        "Output folder:",
        choices=["Create new folder", "Use existing folder"],
    ).ask()

    if folder_action == "Create new folder":
        folder_name = questionary.text("Folder name:").ask()
        target_folder = root_folder / folder_name
        if target_folder.exists():
            proceed = questionary.confirm(
                f'"{folder_name}" already exists. Proceed anyway?', default=False
            ).ask()
            if not proceed:
                sys.exit("Aborted.")
        target_folder.mkdir(parents=True, exist_ok=True)
        key = folder_name
        is_existing = False
    else:
        existing = sorted(d.name for d in root_folder.iterdir() if d.is_dir())
        if not existing:
            sys.exit(f"No existing folders found in {root_folder}")
        folder_name = questionary.select("Select folder:", choices=existing).ask()
        target_folder = root_folder / folder_name
        key = folder_name
        is_existing = True
        used, available = analyse_vol_root(target_folder)
        available_folders = available // MAX_FILES_PER_FOLDER
        print_step(f"Existing folder: {used}/{MAX_FILES_PER_VOLUME} slots used")
        if available == 0:
            sys.exit("Folder is full — no slots available. Aborting.")
        extra = available % MAX_FILES_PER_FOLDER
        print_step(
            f"Remaining capacity: {available} samples"
            f" (~{available_folders} full folder(s) + {extra} extra slots)"
        )
        if available < MAX_FILES_PER_FOLDER:
            print_step(f"⚠  Only {available} slots left — files beyond that will not be processed")

    # ── Step 2: Settings Profile ──────────────────────────────────────────
    existing_settings = {}
    if is_existing:
        existing_settings = read_settings(target_folder / SETTINGS_FILE)
        matched_name = detect_profile(existing_settings, profiles)
        keep_label = f"Keep current  ({matched_name})" if matched_name else "Keep current  (custom)"
        profile_choices = [Choice(title=keep_label, value="__keep__")]
    else:
        profile_choices = []

    profile_choices += [
        Choice(
            title=p["_name"] + (f"  — {p['description']}" if "description" in p else ""),
            value=p["_name"],
        )
        for p in profiles
    ]
    profile_choices.append(Choice(title="Create new profile...", value="__new__"))

    profile_name = questionary.select("Settings Profile:", choices=profile_choices).ask()

    if profile_name == "__keep__":
        settings = existing_settings
    elif profile_name == "__new__":
        before_count = len(profiles)
        create_settings_profile(config)
        if len(profiles) > before_count:
            settings = get_profile(profiles, len(profiles) - 1)
        else:
            settings = get_profile(profiles, 0)  # cancelled — fall back to default
    else:
        which_profile = next(i for i, p in enumerate(profiles) if p["_name"] == profile_name)
        settings = get_profile(profiles, which_profile)

    # ── Step 3: Source ────────────────────────────────────────────────────
    source_type = questionary.select(
        "Source:",
        choices=[
            "Default source_material folder",
            "Specify a folder path",
            "Download a sample pack",
            "Search Freesound.org",
        ],
    ).ask()

    if source_type == "Default source_material folder":
        source_folder = pick_subfolder(Path(config["localSource"]))
    elif source_type == "Specify a folder path":
        folder_path = questionary.path("Folder path:").ask()
        source_folder = Path(folder_path)
        if not source_folder.is_dir():
            sys.exit(f"Not a valid directory: {source_folder}")
        source_folder = pick_subfolder(source_folder)
    elif source_type == "Download a sample pack":
        sets = json.loads(Path("data.json").read_text())["sets"]
        set_name = questionary.select(
            "Select sample pack:",
            choices=[s["name"] for s in sets],
        ).ask()
        s = next(s for s in sets if s["name"] == set_name)
        local_source = Path(config["localSource"])
        source_folder = local_source / s["key"] / "source"
        archive = local_source / s["key"] / f"{s['key']}.zip"
        source_folder.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            print_step(f"Downloading {s['name']}...")
            dlfile(s["url"], str(archive))
        else:
            print_step(f'Skipping download, "{archive.name}" already exists')
        print_step(f"Unzipping {archive.name}...")
        unzip(str(archive), str(source_folder))
    else:
        # ── Freesound.org ─────────────────────────────────────────────────
        dotenv = load_dotenv()
        api_key = os.environ.get("FREESOUND_API_KEY") or dotenv.get("FREESOUND_API_KEY") or ""
        if not api_key:
            api_key = (
                questionary.text("Freesound API key (get one at freesound.org/apiv2):")
                .ask()
                .strip()
            )
            if not api_key:
                sys.exit("No API key provided.")
            if questionary.confirm("Save key to .env for future use?").ask():
                with open(".env", "a") as f:
                    f.write(f"\nFREESOUND_API_KEY={api_key}\n")

        query = questionary.text("Search Freesound:").ask()
        page = 1
        selected_sounds = []

        while True:
            data = freesound_search(query, api_key, page=page)
            print_step(f"{data['count']} result(s) — page {page}")

            sound_choices = [
                Choice(
                    title=(
                        f"{s['name']}  ({s['duration']:.1f}s)"
                        f"  [{s['license'].rstrip('/').rsplit('/', 1)[-1]}]"
                    ),
                    value=s,
                )
                for s in data["results"]
            ]
            if not sound_choices:
                query = questionary.text("No results. Try a different search:").ask()
                page = 1
                continue

            picked = questionary.checkbox(
                "Select sounds (space to toggle, enter to confirm):",
                choices=sound_choices,
            ).ask()

            if picked is None:
                sys.exit("Aborted.")

            for s in picked:
                if s not in selected_sounds:
                    selected_sounds.append(s)

            nav_options = ["✓ Download selected"]
            if data["next"]:
                nav_options.insert(0, "→ Next page")
            nav_options.append("⟳ New search")

            action = questionary.select(
                f"{len(selected_sounds)} sound(s) selected — what next?",
                choices=nav_options,
            ).ask()

            if action == "→ Next page":
                page += 1
            elif action == "⟳ New search":
                query = questionary.text("Search Freesound:").ask()
                page = 1
                selected_sounds = []
            else:
                break

        if not selected_sounds:
            sys.exit("No sounds selected.")

        safe_query = "".join(c if c.isalnum() or c in "-_" else "_" for c in query)[:40]
        source_folder = Path(config["localSource"]) / f"freesound-{safe_query}"
        download_freesound_sounds(selected_sounds, source_folder, api_key)

    # ── Step 4: Process ───────────────────────────────────────────────────
    empty_folder = config.get("emptyFolder", "./empty_folder/")
    termios.tcsetattr(_term_fd, termios.TCSADRAIN, _saved_term)
    try:
        process(
            source_folder,
            target_folder,
            key,
            settings,
            config["overwriteConvertedFiles"],
            empty_folder,
            overwrite_placeholders=is_existing,
            normalize=config.get("normalizeVolume", False),
        )
    except KeyboardInterrupt:
        sys.stdout.write("\r\n⚠  Interrupted.\r\n")
        sys.stdout.flush()
        sys.exit(1)

    if questionary.confirm("Preview processed files?", default=True).ask():
        preview_card_folder(target_folder)


if __name__ == "__main__":
    main()
