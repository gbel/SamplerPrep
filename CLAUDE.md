# FormatRadio — Claude Guidelines

## What this project is

A Python CLI tool that prepares audio sample packs for the
[Music Thing Modular Radio Music](https://github.com/TomWhitwell/RadioMusic) hardware module.
It converts audio files to RAW format via ffmpeg and organises them into a folder structure
the module's firmware can read from an SD card.

## Running the tool

```bash
uv run format-radio   # interactive wizard
uv run python format_radio.py  # direct
```

Requires `ffmpeg` on the system PATH.

## Project layout

```
format_radio.py   — entire application (single module)
config.json       — runtime configuration
data.json         — catalogue of downloadable sample packs
card_folders/     — output (gitignored): processed volumes ready to copy to SD cards
source_material/  — default input folder for local audio files
empty_folder/     — placeholder .raw files seeded into unused bank slots
```

## Hardware constraints — do not change these without good reason

| Constant | Value | Why |
|----------|-------|-----|
| `MAX_FILES_PER_FOLDER` | 48 | Radio Music firmware limit per bank |
| `MAX_FOLDERS` | 16 | Radio Music firmware limit per volume |
| `MAX_FILES_PER_VOLUME` | 768 (48 × 16) | Derived |

Output format: **16-bit signed little-endian PCM, mono, 44100 Hz** (`.raw` extension).
This is hardcoded in the `convert_file()` ffmpeg call and must not be changed.

## Output folder structure

```
card_folders/
  my-pack/           ← volume 0 (named by user)
    settings.txt
    0/   1/  ... 15/ ← up to 16 bank folders
      0.raw  1.raw … ← up to 48 files each
  my-pack-1/         ← volume 1 (overflow, sibling of volume 0)
    settings.txt
    0/  1/  ...
```

Volume 0 lives directly in the user-named folder. Overflow volumes become numbered siblings
(`my-pack-1`, `my-pack-2`, …). This is implemented in `vol_root_for()`.

## CLI flow

```
Step 1  Output folder    Create new | Use existing
Step 2  Source           Default source_material/ | Specify path | Download pack
Step 3  Profile          default | oneshots | immediate
Step 4  Processing
```

Interactive prompts use **questionary** (arrow-key selection). Do not replace with
numbered input or argparse — the UX is intentionally wizard-style.

## Profiles

Profiles write `settings.txt` into each volume root. All profiles inherit from `default`.

| Profile | Looping | StartCVDivider | Immediate start |
|---------|---------|---------------|-----------------|
| `default` | yes | 2 (slowed) | no |
| `oneshots` | no | 1 (full) | no |
| `immediate` | yes | 1 (full) | yes |

The `_name` key is internal only — it is never written to `settings.txt`.

## config.json keys

| Key | Purpose |
|-----|---------|
| `rootFolder` | Where card volumes are written (`./card_folders/`) |
| `localSource` | Default local source folder (`./source_material/`) |
| `emptyFolder` | Placeholder `.raw` files seeded into unused bank slots |
| `overwriteConvertedFiles` | Pass `-y` to ffmpeg |
| `profiles` | List of settings profile objects |

## Code style

- **Formatter / linter:** `ruff` (line length 100). Run `uv run ruff check` and
  `uv run ruff format` before committing. Both must pass clean.
- **Python:** 3.11+. Use `pathlib.Path` for all filesystem paths, `subprocess.run`
  for external processes (never `os.system`).
- **No shell interpolation:** ffmpeg and all subprocesses are called with argument lists,
  never shell strings.
- **Single-file architecture:** keep everything in `format_radio.py`. Do not split into
  packages unless the file exceeds ~500 lines.
- **No new dependencies** without discussion. Current runtime deps: `questionary` only.

## data.json — adding sample packs

Each entry needs at minimum `key`, `name`, and `url` (direct ZIP download link).

```json
{
    "key":  "short-unique-slug",
    "name": "Display name shown in the picker",
    "url":  "https://example.com/samples.zip"
}
```

Only add packs with **verified, direct-download ZIP URLs** — do not guess or fabricate URLs.
The existing MusicRadar CDN entries (`cdn.mos.musicradar.com`) may be stale; verify before
adding more from the same source.
