#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

EXT_RAW = ".RAW"
EXT_OTHER = [".WAV", ".AIF", ".MP3", ".MP4", ".OGG", ".M4A"]
SETTINGS_FILE = "settings.txt"


# @see http://stackoverflow.com/a/12886818
def unzip(source_filename, dest_dir):
    # @note path traversal vulnerability in extractall has been fixed as of Python 2.7.4
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
            print(filename)
            name, ext = os.path.splitext(filename)
            if ext.upper() in extensions:
                p = os.path.join(root, filename)
                if "__MACOSX/" not in p:
                    matches.append(p)
    return matches


def hr():
    print("#" * 80)


def print_status(s):
    hr()
    print(s)
    hr()


def print_step(s):
    print(f">>> {s}")


def print_set_local_online(options):
    hr()
    for i, item in enumerate(options):
        print(f"[{i}] {item}")
    print_status(f"Select if content is local or to be downloaded [0..{len(options) - 1}]")


def print_set_local_dir():
    hr()
    print_status("Enter the name of the folder to be created")


def print_dup_local_dir():
    hr()
    print_status(
        "This folder already exists. Proceed anyway? \n"
        "!!! Doing so WILL overwrite previous data and mix things up !!!\n"
        "Type Y or N"
    )


def print_set_menu(sets):
    hr()
    for i, s in enumerate(sets):
        print(f"[{i}] {s['name']}")
    print_status(f"Select sample set [0..{len(sets) - 1}]")


def print_profile_menu(profiles):
    hr()
    for i, p in enumerate(profiles):
        print(f"[{i}] {p['_name']}")
    print_status(f"Select settings profile [0..{len(profiles) - 1}]")


def load_config(path):
    return json.loads(Path(path).read_text())


def get_path(target_folder, key, current_volume, current_folder):
    path = Path(target_folder) / f"{key}-{current_volume}" / str(current_folder)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_input():
    n = input()
    try:
        n = int(n)
    except ValueError:
        sys.exit(f'Invalid selection "{n}"')
    return n


def get_input_string():
    return input()


def select_profile(profiles):
    print_profile_menu(profiles)
    n = get_input()
    if n not in range(0, len(profiles)):
        sys.exit(f'Invalid profile "{n}"')
    return n


def get_profile(profiles, which_profile=None):
    if which_profile is None:
        which_profile = select_profile(profiles)

    default_profile = profiles[0]
    for p in profiles:
        if p["_name"] == "default":
            default_profile = p
            break

    # @see http://stackoverflow.com/a/26853961
    profile = default_profile.copy()
    profile.update(profiles[which_profile])
    del profile["_name"]
    return profile


def select_local_online(local_online):
    print_set_local_online(local_online)
    n = get_input()
    if n not in range(0, len(local_online)):
        sys.exit(f'Invalid selection "{n}"')
    return n


def get_local_online(local_online, which_local_online):
    if which_local_online is None:
        which_local_online = select_local_online(local_online)
    return local_online[which_local_online]


def select_local_dir():
    print_set_local_dir()
    return get_input_string()


def get_local_dir(which_local_dir):
    if which_local_dir is None:
        which_local_dir = select_local_dir()
    return which_local_dir


def select_dup_local_dir():
    print_dup_local_dir()
    n = get_input_string()
    if n not in ["Y", "N", "y", "n"]:
        sys.exit(f'Invalid input "{n}"')
    return n


def get_dup_local_dir():
    return select_dup_local_dir()


def select_set(sets):
    print_set_menu(sets)
    n = get_input()
    if n not in range(0, len(sets)):
        sys.exit(f'Invalid set "{n}"')
    return n


def get_set(sets, which_set):
    if which_set is None:
        which_set = select_set(sets)
    return sets[which_set]


def write_settings(path, settings):
    with open(path, "w") as f:
        for k, v in settings.items():
            f.write(f"{k}={v}\n")


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
    name, ext = os.path.splitext(filename)
    return name + extension


def main():
    config = load_config("config.json")
    profiles = config["profiles"]

    settings = get_profile(profiles, int(sys.argv[1]) if len(sys.argv) > 1 else None)

    root_folder = config["rootFolder"]
    max_files_per_volume = config["maxFilesPerVolume"]
    max_folders = config["maxFolders"]
    max_files_per_folder = config["maxFilesPerFolder"]
    overwrite_converted_files = config["overwriteConvertedFiles"]
    mode = config["mode"]

    # select if local or online content
    local_online_options = ["Local", "Online"]
    local_online = get_local_online(
        local_online_options, int(sys.argv[3]) if len(sys.argv) > 3 else None
    )

    if local_online == "Local":
        local_dir = get_local_dir(int(sys.argv[4]) if len(sys.argv) > 4 else None)
        source_folder = config["localSource"]
        target_folder = os.path.join(root_folder, local_dir)
        key = local_dir

        if not os.path.isdir(target_folder):
            print_step(f"Creating target dir {target_folder}")
            Path(target_folder).mkdir(parents=True, exist_ok=True)
        else:
            print_step(f'Skipping creating target dir, "{target_folder}" already exists')
            dup_local_dir = get_dup_local_dir()
            if dup_local_dir in ["Y", "y", "yes", "Yes"]:
                print_step("Proceeding with existing folder, watch out for merged data!")
            else:
                sys.exit("Process stopped, no new files created.")

    elif local_online == "Online":
        # load set data
        sets = json.loads(Path("data.json").read_text())["sets"]
        # select a set
        s = get_set(sets, int(sys.argv[2]) if len(sys.argv) > 2 else None)

        url = s["url"]
        name = s["name"]
        key = s["key"]
        source_folder = root_folder + key + "/source"
        target_folder = root_folder + key
        archive = f"{source_folder}/{key}.zip"

        if not os.path.isdir(source_folder):
            print_step(f"Creating source dir {source_folder}")
            Path(source_folder).mkdir(parents=True, exist_ok=True)

        if not os.path.isfile(archive):
            print_step(f'Downloading "{name}" from {url} into "{archive}"')
            dlfile(url, archive)
        else:
            print_step(f'Skipping download, "{archive}" already exists')

        if not os.path.isdir(target_folder):
            print_step(f"Creating target dir {target_folder}")
            Path(target_folder).mkdir(parents=True, exist_ok=True)
        else:
            print_step(f'Skipping creating target dir, "{target_folder}" already exists')

        print_step(f'Unzipping "{archive}"')
        unzip(archive, source_folder)

        if "mode" in s:
            mode = s["mode"]

    print_step(f"Mode: {mode}")

    # Hacky interlude if we just need to copy and convert the files
    # while keeping the folder structure as is
    if mode == "convertOnly":
        # check source
        source_path = source_folder + (s["path"] if "path" in s else "")
        if not os.path.isdir(source_path):
            sys.exit(f"Source path is invalid: {source_path}")

        # create target
        target_folder = f"{target_folder}/{key}/"
        Path(target_folder).mkdir(parents=True, exist_ok=True)

        # copy source files
        shutil.copytree(source_path, target_folder, dirs_exist_ok=True)

        if not os.path.isfile(target_folder + SETTINGS_FILE):
            print_step(f"Writing settings: {target_folder}" + SETTINGS_FILE)
            write_settings(target_folder + SETTINGS_FILE, settings)
        else:
            print_step("Keeping settings contained in archive")

        files = find_files(target_folder, EXT_OTHER)

        if len(files) > 0:
            print_step("Converting audio files")
            for source_file in files:
                target_file = set_extension(source_file, EXT_RAW)
                convert_file(source_file, target_file, True)
                Path(source_file).unlink()

        print()
        print_step("Done.")
        return

    files = find_files(source_folder, [EXT_RAW] + EXT_OTHER)
    files_in_set = len(files)
    current_volume = 0
    current_folder = 0
    current_file = 0
    num_files = 0

    print_step(f"Set contains {files_in_set} files")

    Path(f"{target_folder}/{key}-{current_volume}").mkdir(parents=True, exist_ok=True)

    write_settings(f"{target_folder}/{key}-{current_volume}/{SETTINGS_FILE}", settings)
    path = get_path(target_folder, key, current_volume, current_folder)

    if mode == "spreadAcrossVolumes":
        num_volumes = (files_in_set // max_files_per_volume) + 1
        max_files_per_folder = (files_in_set // (num_volumes * max_folders)) + 1
        max_files_per_volume = max_files_per_folder * max_folders
    elif mode == "spreadAcrossBanks":
        max_files_per_folder = min(
            max_files_per_folder, min(max_files_per_volume, files_in_set) // max_folders
        )
    elif mode == "voltOctish":
        max_files_per_folder = 60
    else:
        max_files_per_folder = 75

    num_volumes = (files_in_set // max_files_per_volume) + 1
    print_step(
        f"Spreading {files_in_set} files across {max_folders} folders, "
        f"{max_files_per_folder} files each (using {num_volumes} volumes)"
    )

    for f in files:
        print(f)
        if current_file < max_files_per_folder:
            target_file = f"{path}/{current_file}.raw"
            name, ext = os.path.splitext(f)

            if ext.upper() in EXT_OTHER:
                convert_file(f, target_file, overwrite_converted_files)
            else:
                # RAW file, just copy
                shutil.copy2(f, target_file)

            current_file += 1
            num_files += 1

            if num_files == max_files_per_volume:
                # next volume
                current_volume += 1
                current_folder = 0
                current_file = 0
                path = get_path(target_folder, key, current_volume, current_folder)
                write_settings(f"{target_folder}/{key}-{current_volume}/{SETTINGS_FILE}", settings)

        else:
            current_file = 0
            current_folder += 1

            if current_folder == max_folders:
                # next volume
                current_volume += 1
                current_folder = 0
                current_file = 0

            path = get_path(target_folder, key, current_volume, current_folder)
            write_settings(f"{target_folder}/{key}-{current_volume}/{SETTINGS_FILE}", settings)

    print_status(f"Created {current_volume + 1} volumes here: {target_folder}")

    if os.name == "mac":
        subprocess.run(["open", target_folder])


if __name__ == "__main__":
    main()
