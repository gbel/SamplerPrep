#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
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
        print("HTTP Error:", e.code, url)
    except URLError as e:
        print("URL Error:", e.reason, url)


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


def print_step(s):
    print(f">>> {s}")


def load_config(path):
    return json.loads(Path(path).read_text())


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


def convert_file(source_file, target_file, overwrite):
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
        target_file,
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


def set_extension(filename, extension):
    name, _ = os.path.splitext(filename)
    return name + extension


def analyse_vol_root(vol_root):
    """Return (used_slots, available_slots) for an existing volume root."""
    used = 0
    for i in range(MAX_FOLDERS):
        folder = vol_root / str(i)
        if folder.is_dir():
            used += sum(1 for f in folder.glob("*.raw") if f.stem.isdigit())
    available = MAX_FILES_PER_VOLUME - used
    return used, available


def vol_root_for(target_folder, key, volume):
    """Volume 0 lives directly in target_folder; overflow volumes are siblings."""
    if volume == 0:
        return target_folder
    return target_folder.parent / f"{key}-{volume}"


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
    is_existing=False,
):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    files_in_set = len(files)
    print_step(f"Found {files_in_set} files")

    current_volume = 0
    current_folder = 0
    current_file = 0

    vol_root = vol_root_for(target_folder, key, current_volume)
    vol_root.mkdir(parents=True, exist_ok=True)
    write_settings(str(vol_root / SETTINGS_FILE), settings)
    create_skeleton(vol_root, empty_folder, overwrite_placeholders)
    path = vol_root / str(current_folder)

    for f in files:
        print_step(f)
        target_file = str(path / f"{current_file}.raw")
        _, ext = os.path.splitext(f)

        if not Path(target_file).exists():
            if ext.upper() in EXT_OTHER:
                convert_file(f, target_file, overwrite)
            else:
                shutil.copy2(f, target_file)

        current_file += 1

        if current_file == MAX_FILES_PER_FOLDER:
            current_file = 0
            current_folder += 1
            if current_folder == MAX_FOLDERS:
                if is_existing:
                    print_step("⚠  Folder is full — remaining files will not be processed")
                    break
                current_volume += 1
                current_folder = 0
                vol_root = vol_root_for(target_folder, key, current_volume)
                vol_root.mkdir(parents=True, exist_ok=True)
                write_settings(str(vol_root / SETTINGS_FILE), settings)
                create_skeleton(vol_root, empty_folder, overwrite_placeholders)
            path = vol_root / str(current_folder)

    print_step(f"Done — {current_volume + 1} volume(s) written to {target_folder}")


def main():
    config = load_config("config.json")
    profiles = config["profiles"]
    root_folder = Path(config["rootFolder"])
    root_folder.mkdir(parents=True, exist_ok=True)

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

    # ── Step 2: Source ────────────────────────────────────────────────────
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
        source_folder = Path(config["localSource"])
    elif source_type == "Specify a folder path":
        folder_path = questionary.path("Folder path:").ask()
        source_folder = Path(folder_path)
        if not source_folder.is_dir():
            sys.exit(f"Not a valid directory: {source_folder}")
    elif source_type == "Download a sample pack":
        sets = json.loads(Path("data.json").read_text())["sets"]
        set_name = questionary.select(
            "Select sample pack:",
            choices=[s["name"] for s in sets],
        ).ask()
        s = next(s for s in sets if s["name"] == set_name)
        source_folder = root_folder / s["key"] / "source"
        archive = source_folder / f"{s['key']}.zip"
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
        api_key = config.get("freesoundApiKey", "")
        if not api_key:
            api_key = (
                questionary.text("Freesound API key (get one at freesound.org/apiv2):")
                .ask()
                .strip()
            )
            if not api_key:
                sys.exit("No API key provided.")
            if questionary.confirm("Save key to config.json for future use?").ask():
                config["freesoundApiKey"] = api_key
                Path("config.json").write_text(json.dumps(config, indent=4))

        query = questionary.text("Search Freesound:").ask()
        page = 1
        selected_sounds = []

        while True:
            data = freesound_search(query, api_key, page=page)
            total = data["count"]
            results = data["results"]
            print_step(f"{total} result(s) — page {page}")

            sound_choices = [
                Choice(
                    title=(
                        f"{s['name']}  ({s['duration']:.1f}s)"
                        f"  [{s['license'].rstrip('/').rsplit('/', 1)[-1]}]"
                    ),
                    value=s,
                )
                for s in results
            ]
            nav_choices = []
            if data["next"]:
                nav_choices.append(Choice("→ Next page", value="__next__"))
            nav_choices.append(Choice("✓ Done selecting", value="__done__"))

            picked = questionary.checkbox(
                "Select sounds (space to toggle, enter to confirm):",
                choices=sound_choices + nav_choices,
            ).ask()

            if picked is None:
                sys.exit("Aborted.")

            advance = False
            for item in picked:
                if item == "__next__":
                    page += 1
                    advance = True
                elif item == "__done__":
                    pass
                elif item not in selected_sounds:
                    selected_sounds.append(item)

            if not advance:
                break

        if not selected_sounds:
            sys.exit("No sounds selected.")

        safe_query = "".join(c if c.isalnum() or c in "-_" else "_" for c in query)[:40]
        source_folder = root_folder / f"freesound-{safe_query}" / "source"
        download_freesound_sounds(selected_sounds, source_folder, api_key)

    # ── Step 3: Profile ───────────────────────────────────────────────────
    profile_name = questionary.select(
        "Profile:",
        choices=[
            Choice("default    — loops, slowed CV on start position", value="default"),
            Choice("oneshots   — plays once and stops, full CV resolution", value="oneshots"),
            Choice("immediate  — loops, start jumps instantly with pot/CV", value="immediate"),
        ],
    ).ask()
    which_profile = next(i for i, p in enumerate(profiles) if p["_name"] == profile_name)
    settings = get_profile(profiles, which_profile)

    # ── Step 4: Process ───────────────────────────────────────────────────
    empty_folder = config.get("emptyFolder", "./empty_folder/")
    process(
        source_folder,
        target_folder,
        key,
        settings,
        config["overwriteConvertedFiles"],
        empty_folder,
        overwrite_placeholders=is_existing,
        is_existing=is_existing,
    )


if __name__ == "__main__":
    main()
