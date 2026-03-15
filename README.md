# Format Radio

Prepares sound packs for use with [Music Thing Modular's Radio Music](https://github.com/TomWhitwell/RadioMusic).

## What it does

- Converts WAV, AIF, MP3, MP4, OGG, and M4A files to RAW (16-bit signed, mono, 44100 Hz — per [Radio Music specs](https://github.com/TomWhitwell/RadioMusic/wiki/SD-Card%3A-Format-%26-File-Structure#setting-up-files-on-the-micro-sd-card))
- Renames files sequentially (0.raw, 1.raw, …) to ensure 8.3-compatible names
- Always creates the full 16-folder skeleton (folders 0–15), seeding empty folders with placeholder files from `empty_folder/`
- Writes a `settings.txt` for the selected profile
- Downloads sample packs from the built-in repository ([data.json](data.json))
When expanding an **existing** card folder, placeholder files are refreshed and existing numbered audio files are never overwritten.

## Requirements

- Python 3.8+
- [ffmpeg](https://ffmpeg.org) — install via Homebrew:

```bash
brew install ffmpeg
```

## Installation

```bash
git clone https://github.com/apolakipso/FormatRadio.git
cd FormatRadio
pip install questionary
```

## Usage

Run from the project directory:

```bash
python format_radio.py
```

The tool walks you through four steps:

### 1. Output folder

Choose to **create a new card folder** or **use an existing one**.

When using an existing folder, the tool reports how many slots are used and how many remain (max 768 per volume: 16 folders × 48 files).

### 2. Source

- **Default source_material folder** — reads from the path set in `config.json` (`localSource`)
- **Specify a folder path** — tab-completion supported
- **Download a sample pack** — picks from the built-in list in [data.json](data.json); skips the download if the zip already exists

### 3. Profile

Selects the `settings.txt` written to each volume root:

| Profile | Behaviour |
|---|---|
| `default` | Loops, slowed CV on start position |
| `oneshots` | Plays once and stops, full CV resolution |
| `immediate` | Loops, start position jumps instantly with pot/CV |

### 4. Processing

Files are converted/copied into numbered folders. The full 16-folder skeleton is always created first (see [Folder skeleton](#folder-skeleton)), then audio files are written sequentially into slots.

## Folder skeleton

Every volume always gets the full 16-folder structure (folders `0`–`15`) created before any audio is written. Each folder is seeded with the placeholder RAW files found in `empty_folder/` (`BIRDS.raw` and `VINYL.raw` by default), so the module always has valid audio in every slot even if your source doesn't fill all 16 folders.

Placeholder seeding behaviour:

- **New card folder** — placeholders are written only if the file doesn't already exist
- **Existing card folder** — placeholders are refreshed (overwritten) so stale placeholders don't persist; your own numbered audio files (`0.raw`, `1.raw`, …) are never touched

You can replace the files in `empty_folder/` with any valid RAW audio to use your own placeholders. The path is configurable via `emptyFolder` in `config.json`.

## Settings customization

Each volume gets a `settings.txt` written to its root. You can customise the values by editing the `profiles` array in `config.json`. All profiles merge on top of `default` — only specify keys that differ. The `_name` key is internal and is not written to the file.

| Setting | Description |
|---|---|
| `MUTE` | Mute output on channel change (`0` = off, `1` = on) |
| `DECLICK` | De-click time in ms when switching channels |
| `ShowMeter` | Show level meter on display (`0` = off, `1` = on) |
| `meterHIDE` | Time in ms before meter auto-hides |
| `ChanPotImmediate` | Channel pot changes take effect immediately (`0` = on next loop) |
| `ChanCVImmediate` | Channel CV changes take effect immediately |
| `StartPotImmediate` | Start position pot changes take effect immediately |
| `StartCVImmediate` | Start position CV changes take effect immediately |
| `StartCVDivider` | Divides CV resolution for start position (`1` = full, `2` = half, …) |
| `Looping` | Loop playback (`0` = one-shot, `1` = loop) |

See the [Radio Music wiki](https://github.com/TomWhitwell/RadioMusic/wiki/Customise-your-module%3A-Editing-settings.txt) for the full reference.

## Configuration

[config.json](config.json) contains:

| Key | Description | Default |
|---|---|---|
| `rootFolder` | Where card folders are written | `./card_folders/` |
| `emptyFolder` | Source of placeholder RAW files for empty folders | `./empty_folder/` |
| `localSource` | Default source folder when not downloading | `./source_material/` |
| `overwriteConvertedFiles` | Pass `-y` to ffmpeg (overwrite converted files) | `true` |
| `profiles` | Array of settings profiles (see below) | — |

Profiles merge with `default` — you only need to specify keys that differ. The `_name` key identifies each profile and is not written to `settings.txt`.

## Sample Pack Repository

[data.json](data.json) lists downloadable packs. Each entry has:

| Key | Description |
|---|---|
| `key` | Used as the folder name — must be a valid directory name |
| `name` | Display name shown in the selection list |
| `url` | URL of the zip file to download |
| `source` | Optional link to the pack's website |

## Notes

- Tested on macOS
- Files already present in a target folder are never overwritten (new slots are filled in sequence)
- Sources with more than 768 files are truncated at the limit with a warning — no overflow volumes are created
