#!/usr/bin/env python3
"""SamplerPrep — prepare audio sample packs for hardware samplers."""

import json
import os
import sys
import termios
from pathlib import Path

import questionary
from questionary import Choice

from samplerprep.core import (
    dlfile,
    download_freesound_sounds,
    find_files,
    find_mounted_volumes,
    freesound_search,
    load_config,
    load_dotenv,
    pick_subfolder,
    print_step,
    run_rsync,
    unzip,
)
from samplerprep.drivers import load_driver


def _load_devices() -> list[dict]:
    devices_path = Path(__file__).parent / "devices.json"
    return json.loads(devices_path.read_text())


def main():
    config = load_config("config.json")
    devices = _load_devices()

    # ── Device selection ──────────────────────────────────────────────────────
    device = questionary.select(
        "Target device:",
        choices=[Choice(title=f"{d['name']}  ({d['storage']})", value=d) for d in devices],
    ).ask()

    driver = load_driver(device["key"])

    # ── Top-level action ──────────────────────────────────────────────────────
    action_choices = ["Prepare output folder"]

    if hasattr(driver, "preview"):
        action_choices.append("Preview card folder")

    if hasattr(driver, "create_settings_profile"):
        action_choices.append("Create Settings Profile")

    if hasattr(driver, "create_options_preset"):
        action_choices.append("Create Options Preset")

    if hasattr(driver, "save_recordings"):
        action_choices.append("Save recordings from card")

    if hasattr(driver, "clean_card"):
        action_choices.append("Clean card before ejecting")

    action_choices.append("Copy folder to card")

    top_action = questionary.select(
        "What would you like to do?",
        choices=action_choices,
    ).ask()

    root_folder = Path(config["rootFolder"]) / device["key"]
    root_folder.mkdir(parents=True, exist_ok=True)

    # ── Preview ───────────────────────────────────────────────────────────────
    if top_action == "Preview card folder":
        folders = sorted(d.name for d in root_folder.iterdir() if d.is_dir())
        if not folders:
            sys.exit(f"No card folders found in {root_folder}")
        folder_name = questionary.select("Card folder to preview:", choices=folders).ask()
        driver.preview(root_folder / folder_name)
        return

    # ── Create Settings Profile ───────────────────────────────────────────────
    if top_action == "Create Settings Profile":
        driver.create_settings_profile(config)
        return

    # ── Create Options Preset ─────────────────────────────────────────────────
    if top_action == "Create Options Preset":
        driver.create_options_preset(config)
        return

    # ── Save recordings from card ─────────────────────────────────────────────
    if top_action == "Save recordings from card":
        print_step(
            "⚠  Run this IMMEDIATELY after inserting the card — macOS Spotlight\n"
            "   creates ._* shadow files within seconds of mount that corrupt recordings."
        )
        volumes = find_mounted_volumes()
        if not volumes:
            sys.exit("No volumes found at /Volumes.")
        vol_choice = questionary.select(
            "Select Morphagene card volume:",
            choices=[Choice(title=f"{p.name}  ({p})", value=p) for p in volumes],
        ).ask()
        dest = driver.save_recordings(vol_choice, root_folder)
        if dest and questionary.confirm("Clean macOS metadata from card now?", default=True).ask():
            driver.clean_card(vol_choice)
        return

    # ── Clean card before ejecting ────────────────────────────────────────────
    if top_action == "Clean card before ejecting":
        volumes = find_mounted_volumes()
        if not volumes:
            sys.exit("No volumes found at /Volumes.")
        vol_choice = questionary.select(
            "Select Morphagene card volume:",
            choices=[Choice(title=f"{p.name}  ({p})", value=p) for p in volumes],
        ).ask()
        driver.clean_card(vol_choice)
        return

    # ── Copy folder to card ───────────────────────────────────────────────────
    if top_action == "Copy folder to card":
        # Digitakt uses USB, not a card volume
        if device["storage"].startswith("USB"):
            print_step(f"⚠  {device['name']} uses USB transfer — no SD/CF card slot.")
            print_step("Open Elektron Transfer and drag your output folder into the application.")
            print_step("Download: elektron.se/en/downloads/transfer")
            return

        card_folders = sorted(d.name for d in root_folder.iterdir() if d.is_dir())
        if not card_folders:
            sys.exit(f"No card folders found in {root_folder}")
        folder_name = questionary.select("Card folder to copy:", choices=card_folders).ask()
        card_folder = root_folder / folder_name

        volumes = find_mounted_volumes()
        if not volumes:
            sys.exit("No volumes found at /Volumes.")
        vol_choice = questionary.select(
            "Destination volume:",
            choices=[Choice(title=f"{p.name}  ({p})", value=p) for p in volumes],
        ).ask()

        # Folder scope
        bank_dirs = sorted(
            [p for p in card_folder.iterdir() if p.is_dir() and p.name.isdigit()],
            key=lambda p: int(p.name),
        )
        scope_choices = [Choice("All folders", value="all")]
        if bank_dirs:
            scope_choices.append(Choice("Specific folders...", value="pick"))
        scope = questionary.select("Folders to sync:", choices=scope_choices).ask()

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

        backup_path = None
        if sync_mode == "replace":
            if questionary.confirm("Back up the card before syncing?", default=True).ask():
                from datetime import datetime

                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_vol = "".join(c if c.isalnum() or c in "-_" else "_" for c in vol_choice.name)
                backup_path = root_folder / "backups" / f"{safe_vol}_{ts}"

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
            raw_files = find_files(str(card_folder), [".raw", ".RAW", ".wav", ".WAV"])
            num_files = len(raw_files)
            num_dirs = sum(1 for p in card_folder.iterdir() if p.is_dir())
            print_step(f"Files       {num_files} file(s) in {num_dirs} folder(s)")
        if sync_mode == "replace":
            print_step("⚠  Files on the card not present in the source folder will be deleted")

        if not questionary.confirm("Proceed?", default=(sync_mode == "add")).ask():
            sys.exit("Aborted.")

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

    # ── Prepare output folder ─────────────────────────────────────────────────

    # Save terminal settings before any questionary prompt so we can restore
    # them before process() runs (questionary disables ISIG, preventing Ctrl-C).
    _term_fd = sys.stdin.fileno()
    _saved_term = termios.tcgetattr(_term_fd)

    # Step 1: Output folder
    folder_action = questionary.select(
        "Output folder:",
        choices=["Create new folder", "Use existing folder"],
    ).ask()

    is_existing = False

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
    else:
        existing = sorted(d.name for d in root_folder.iterdir() if d.is_dir())
        if not existing:
            sys.exit(f"No existing folders found in {root_folder}")
        folder_name = questionary.select("Select folder:", choices=existing).ask()
        target_folder = root_folder / folder_name
        key = folder_name
        is_existing = True

        if hasattr(driver, "analyse"):
            used, available = driver.analyse(target_folder)
            available_folders = available // driver.MAX_FILES_PER_FOLDER
            print_step(f"Existing folder: {used}/{driver.MAX_FILES_PER_VOLUME} slots used")
            if available == 0:
                sys.exit("Folder is full — no slots available. Aborting.")
            extra_slots = available % driver.MAX_FILES_PER_FOLDER
            print_step(
                f"Remaining capacity: {available} samples"
                f" (~{available_folders} full folder(s) + {extra_slots} extra slots)"
            )
            if available < driver.MAX_FILES_PER_FOLDER:
                print_step(
                    f"⚠  Only {available} slots left — files beyond that will not be processed"
                )

    # Step 2: Settings profile (Radio Music only)
    settings = {}
    if hasattr(driver, "get_profile"):
        profiles = config.get("profiles", [])
        existing_settings = {}
        if is_existing:
            existing_settings = driver.read_settings(target_folder / driver.SETTINGS_FILE)
            matched_name = driver.detect_profile(existing_settings, profiles)
            keep_label = (
                f"Keep current  ({matched_name})" if matched_name else "Keep current  (custom)"
            )
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
            driver.create_settings_profile(config)
            if len(profiles) > before_count:
                settings = driver.get_profile(profiles, len(profiles) - 1)
            else:
                settings = driver.get_profile(profiles, 0)
        else:
            which_profile = next(i for i, p in enumerate(profiles) if p["_name"] == profile_name)
            settings = driver.get_profile(profiles, which_profile)

    # Step 2b: Options preset (Morphagene only)
    options_preset = None
    if hasattr(driver, "get_options_preset"):
        mg_presets = config.get("morphagene_presets", [])
        existing_options = {}
        if is_existing:
            _, existing_options = driver.read_options(target_folder / driver.OPTIONS_FILE)
            matched = driver.detect_options_preset(existing_options, mg_presets)
            keep_label = f"Keep current  ({matched})" if matched else "Keep current  (custom)"
            preset_choices = [Choice(title=keep_label, value="__keep__")]
        else:
            preset_choices = []

        preset_choices += [
            Choice(
                title=p["_name"] + (f"  — {p['description']}" if "description" in p else ""),
                value=p["_name"],
            )
            for p in mg_presets
        ]
        preset_choices.append(Choice(title="Create new preset...", value="__new__"))

        preset_name = questionary.select("Options preset:", choices=preset_choices).ask()

        if preset_name == "__keep__":
            options_preset = existing_options
        elif preset_name == "__new__":
            before = len(mg_presets)
            driver.create_options_preset(config)
            if len(mg_presets) > before:
                options_preset = driver.get_options_preset(mg_presets, len(mg_presets) - 1)
            else:
                options_preset = driver.get_options_preset(mg_presets, 0)
        else:
            idx = next(i for i, p in enumerate(mg_presets) if p["_name"] == preset_name)
            options_preset = driver.get_options_preset(mg_presets, idx)

    # Step 3: Source
    freesound_files: list[str] | None = None
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
        # Freesound.org
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
        freesound_files = download_freesound_sounds(selected_sounds, source_folder, api_key)

    # Step 4: Process
    overwrite = config["overwriteConvertedFiles"]
    normalize = config.get("normalizeVolume", False)
    empty_folder = config.get("emptyFolder", "./empty_folder/")

    termios.tcsetattr(_term_fd, termios.TCSADRAIN, _saved_term)
    try:
        if hasattr(driver, "analyse"):
            # Radio Music — extra parameters
            driver.process(
                source_folder,
                target_folder,
                device,
                config,
                overwrite,
                normalize,
                key=key,
                settings=settings,
                empty_folder=empty_folder,
                overwrite_placeholders=is_existing,
            )
        elif hasattr(driver, "get_options_preset"):
            driver.process(
                source_folder,
                target_folder,
                device,
                config,
                overwrite,
                normalize,
                options=options_preset,
                files=freesound_files,
            )
        else:
            driver.process(source_folder, target_folder, device, config, overwrite, normalize)
    except KeyboardInterrupt:
        sys.stdout.write("\r\n⚠  Interrupted.\r\n")
        sys.stdout.flush()
        sys.exit(1)

    if hasattr(driver, "preview"):
        if questionary.confirm("Preview processed files?", default=True).ask():
            driver.preview(target_folder)


if __name__ == "__main__":
    main()
