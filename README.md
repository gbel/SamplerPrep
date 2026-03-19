# SamplerPrep

A wizard-style CLI tool for preparing audio sample packs for hardware samplers. Point it at a folder of audio files, pick your device, and it handles conversion, organisation, and copying to your SD card.

---

## Background

This project started as a fork of [apolakipso/FormatRadio](https://github.com/apolakipso/FormatRadio), itself inspired by the original scripts that circulated in the Music Thing Modular community around the Radio Music module's release in 2015. The Radio Music — designed by Tom Whitwell — was a radical idea: a Eurorack module that behaved like a radio, scanning a bank of audio files as if tuning across stations. It had no sample editor, no screen, no fine-grained control. You fed it a micro-SD card full of correctly-formatted files, patched it in, and turned the knob.

The friction was the point. Files had to be 16-bit signed little-endian raw PCM, named `0.raw` through `47.raw`, sorted into folders `0/` through `15/`. No headers, no metadata, no mercy. The original community scripts were rough — shell one-liners, Python 2 glue code, manual ffmpeg invocations. This tool grew from that tradition: automate the tedious parts, keep the spirit.

Over the course of development, what started as a simple converter accumulated a settings profile wizard, a Freesound search integration, an interactive audio preview browser, SD card sync with rsync, and eventually support for eight more devices. At some point it became something else — a general-purpose sampler preparation tool — and was renamed accordingly.

---

## Supported devices

| Device | Format | Sample rate | Depth | Channels | Storage |
|--------|--------|-------------|-------|----------|---------|
| Music Thing Modular Radio Music | RAW (headerless PCM) | 44100 Hz | 16-bit s-LE | Mono | microSD |
| Make Noise Morphagene | WAV | 48000 Hz | 32-bit float | Stereo | microSD |
| Elektron Digitakt | WAV | 48000 Hz | 16-bit | Mono | USB (Elektron Transfer) |
| Elektron Octatrack | WAV | 44100 Hz | 16-bit | Mono | CF card |
| Polyend Tracker | WAV | 44100 Hz | 16-bit | Mono | microSD |
| Squarp Rample | WAV | 44100 Hz | 16-bit | Mono | microSD |
| Endorphines Queen of Pentacles | WAV (no metadata) | 44100 Hz | 16-bit | Mono | microSD |
| 1010music Bitbox mk2 / Micro | WAV | 48000 Hz | 24-bit | Stereo | microSD |
| ALM/Busy Circuits Squid Salmple | WAV | 44100 Hz | 16-bit | Mono | USB stick |

---

## Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org) on your PATH
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

```bash
brew install ffmpeg uv
```

Optional (for Morphagene features):

| Tool | Feature | Install |
|------|---------|---------|
| sox | Preview browser playback (all devices) | `brew install sox` |
| rubberband | Pitch/tempo shift | `brew install rubberband` |
| aubio | Transient auto-detection for splice markers | `brew install aubio` |

---

## Installation

```bash
git clone https://github.com/gbel/FormatRadio.git
cd FormatRadio
uv sync
```

---

## Usage

```bash
uv run sampler-prep
```

The wizard opens with a device picker, then walks you through output folder, source, and processing.

---

## Wizard walkthrough

### Step 0 — Device

Pick your hardware. The rest of the wizard adapts to its format requirements, folder structure, and file naming conventions.

### Step 1 — Output folder

Create a new output folder or add to an existing one. For the Radio Music, existing folders report used and remaining slot counts (max 768 per volume: 16 folders × 48 files).

### Step 2 — Settings profile *(Radio Music only)*

Choose a `settings.txt` profile to write to the volume root. Profiles inherit from `default` and can be created interactively with the built-in wizard. See [Settings profiles](#settings-profiles--radio-music) below.

### Step 3 — Source

- **Default source_material folder** — reads from `./source_material/`; if subdirectories exist, a picker lets you drill into a specific pack
- **Specify a folder path** — with tab completion; same subfolder picker if subdirectories are found
- **Download a sample pack** — selects from the built-in catalogue in `data.json`; skips the download if the archive already exists
- **Search Freesound.org** — live search with pagination and multi-select; downloads HQ MP3 previews; requires a free API key from [freesound.org/apiv2](https://freesound.org/apiv2)

### Step 4 — Processing

Files are converted with ffmpeg to the device's native format and organised into the correct folder and file naming structure. Pressing Ctrl-C cleanly interrupts both the Python process and any running ffmpeg child.

After processing completes, the tool offers to open the interactive preview browser (Radio Music and Morphagene).

---

## Device output structures

### Radio Music

```
card_folders/radio-music/my-pack/
  settings.txt
  0/   1/  …  15/          ← 16 bank folders
    0.raw  1.raw  …         ← up to 48 files per bank
```

Every folder is always created and seeded with placeholder RAW files from `empty_folder/` so the module has valid audio in every slot from the start. Placeholder files have non-numeric names (`BIRDS.raw`, `VINYL.raw`) and are cleaned out as real files fill each bank.

### Morphagene

```
card_folders/morphagene/my-reels/
  mg1.wav  mg2.wav  …  mgw.wav   ← up to 32 reels in root
```

Files follow the Morphagene naming scheme: `mg1`–`mg9`, then `mga`–`mgw` (32 total). Format is 32-bit float stereo WAV at 48 kHz, as required by the firmware.

Morphagene-specific processing options:

- **Splice markers** — in concat mode, file-boundary markers are added automatically; additional options: even grid every N seconds, or auto-detect transients (requires `brew install aubio`); markers are stored as standard WAV cue chunks
- **Cue point passthrough** — existing cue points in source WAVs are preserved and rescaled to 48 kHz
- **Pitch/tempo shift** — shift pitch by semitones or stretch tempo by a factor via rubberband (requires `brew install rubberband`)

#### macOS metadata

See [macOS and AppleDouble files](#macos-and-appledouble-files) for how SamplerPrep
handles `._*` files and Spotlight indexing automatically.

### Digitakt

```
card_folders/digitakt/my-samples/
  kick.wav  snare.wav  …
```

The Digitakt has no SD card slot. Output is a flat folder of 16-bit mono WAV files at 48 kHz, ready to be imported via [Elektron Transfer](https://www.elektron.se/en/downloads/transfer) over USB.

### Octatrack

```
card_folders/octatrack/my-set/
  AUDIO/
    kick.wav  snare.wav  …
```

Files land in the `AUDIO/` pool subfolder. Copy the output folder to your CF card as an Octatrack Set. The Octatrack requires 44100 Hz — files at 48 kHz will play at the wrong speed.

### Polyend Tracker

```
card_folders/tracker/my-samples/
  Samples/
    kick.wav  snare.wav  …
```

Files go into `Samples/` at the root of the output folder. The Tracker auto-converts on load, but SamplerPrep pre-converts to 44100 Hz 16-bit mono to avoid on-device overhead.

### Squarp Rample

```
card_folders/rample/my-kit/
  A0/
    1_kick.wav  2_snare.wav  3_hat.wav  4_clap.wav
  A1/
    1_bass.wav  …
```

Files are distributed across kit folders (`A0/`, `A1/`, … up to `Z99/`), four voices per kit. Voice assignment is sequential (1→2→3→4→1→…); a new kit folder is started when all four voices are filled.

### Queen of Pentacles

```
card_folders/queen-of-pentacles/my-banks/
  1/   2/  …  8/            ← 8 bank folders
    1.wav  2.wav  3.wav  4.wav
```

Maximum 32 files (8 banks × 4). All metadata is stripped from output files — the Queen of Pentacles is sensitive to embedded BWF or ID3 chunks.

> **Note:** The bank folder naming (`1/`–`8/`) is inferred from community reports; the official manual PDF was inaccessible during research. Verify against your hardware before copying to the card.

### 1010music Bitbox mk2 / Micro

```
card_folders/bitbox/my-preset/
  Presets/
    my-preset/
      preset.xml
      kick.wav  snare.wav  …   ← up to 16 samples per preset
    my-preset-2/               ← overflow preset if > 16 files
      preset.xml
      …
```

Samples are mapped onto the 4×4 pad grid (16 slots). Each preset folder contains a `preset.xml` that tells the hardware which file goes on which pad — without it the preset won't appear in the device's browser. SamplerPrep generates this XML automatically. Files beyond 16 overflow into additional numbered presets (`{name}-2`, `{name}-3`, …).

Format is 24-bit stereo WAV at 48 kHz, the recommended output format per the [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss) reference implementation.

> **Note:** The `preset.xml` format was inferred from ConvertWithMoss's Java source and the open-source Bitbox-Editor project — not verified against the official manual (login-gated). The structure should work on both Bitbox mk2 and Micro. Raise an issue if the hardware rejects the XML.

### ALM/Busy Circuits Squid Salmple

```
card_folders/squid/my-banks/
  ALM022/
    01/
      kick.wav  snare.wav  …   ← up to 8 files per bank
    02/
      …
```

Files are distributed across numbered bank folders inside `ALM022/` on a USB stick. Each bank holds up to 8 samples, one per channel. Up to 99 banks per USB key.

---

## macOS and AppleDouble files

When macOS mounts a FAT32 volume (SD card, USB stick), it silently creates hidden
`._*` "AppleDouble" sidecar files alongside every file you copy — for example
`._mg1.wav` next to `mg1.wav`. These store macOS-specific metadata (resource forks,
Finder tags) that no hardware sampler understands.

**Why this matters for the Morphagene:** the firmware scans the card root for anything
that looks like an audio file. When it finds `._mg1.wav` it tries to parse it, fails,
and overwrites it with a 44-byte stub WAV — destroying what it thinks is a corrupt reel.
If that sidecar happened to sit next to a recording you hadn't backed up, the recording
is gone.

**SamplerPrep mitigates this automatically:**

- **Sync (`Copy folder to card`)** — rsync is called with `--exclude=._*` so AppleDouble
  files are never written to the card during a sync.
- **Clean card** — the Morphagene menu includes a *Clean card before ejecting* action
  that removes all macOS metadata files (`._*`, `.DS_Store`, `.Spotlight-V100`, etc.)
  from a mounted volume before you eject.
- **Spotlight indexing** — see [below](#spotlight-indexing) for the permanent fix that
  stops Spotlight from creating these files in the first place.

Other devices (Squid Salmple, Bitbox, Radio Music) are similarly affected if you copy
files to their card manually via Finder. Always use *Copy folder to card* rather than
drag-and-drop to avoid leaving metadata files behind.

### Spotlight indexing

When a FAT32 card is mounted on macOS, Spotlight begins indexing it within seconds —
even without opening Finder. Beyond `._*` files it also creates `.Spotlight-V100`,
`.Trashes`, and `.DocumentRevisions-V100` directories. The Morphagene firmware treats
every file in the card root as a reel; encountering these directories corrupts them.

**Permanent fix:**

1. Open **System Settings → Siri & Spotlight → Spotlight Privacy** (macOS Ventura+),
   or **System Preferences → Spotlight → Privacy** (Monterey and earlier).
2. Click **+** and add the mounted card volume (usually **NO NAME** for a default
   FAT32 card).
3. Click **Done**.

The exclusion persists across remounts as long as the volume label doesn't change.

---

## Copy to card

From the top-level menu, choose **Copy folder to card** to rsync an output folder to a mounted SD or CF card volume.

- **Folder scope** — sync all folders or select specific bank folders (useful when you've only updated one or two banks)
- **Sync mode** — *Add* preserves everything already on the card; *Replace* does a full sync and removes files not in the source
- **Backup** — in Replace mode, the tool optionally backs up the full card to `card_folders/<device>/backups/` before syncing

The Digitakt shows a reminder about Elektron Transfer instead.

---

## Preview browser

After processing, the tool offers an interactive preview browser. Playback requires `sox` (`brew install sox`). The browser is also available from the top-level menu as **Preview card folder**.

### Radio Music

```
  Preview: my-pack   Folder 1 / 16
  ──────────────────────────────────────────────────────
  ▶ 0.raw       3.2s  ♪
    1.raw       1.8s
    2.raw       5.0s
  ──────────────────────────────────────────────────────
  [↑/↓] navigate   [SPACE] play/stop   [←/→] folder   [,/.] seek 5s   [D] delete   [Q] quit
```

### Morphagene

```
  Morphagene Preview
  [q] quit  [space] play/stop  [,/.] seek 5s  [[ / ]] prev/next splice

  > ▶  mg1.wav  (4 splices)
       mg2.wav
       mg3.wav  (12 splices)

  [████████████|░░░░░░░░░░|░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░]  0:42 / 2:15
```

`[` and `]` jump between splice markers within the playing reel. Splice positions are shown as `|` ticks on the progress bar.

---

## Settings profiles *(Radio Music only)*

Each Radio Music volume gets a `settings.txt` written to its root. SamplerPrep ships with three built-in profiles:

| Profile | Looping | Start CV | Immediate start |
|---------|---------|----------|-----------------|
| `default` | Yes | Slowed (÷2) | No |
| `oneshots` | No (plays once) | Full | No |
| `immediate` | Yes | Full | Yes |

Custom profiles can be created with the **Create Settings Profile** wizard (available from the top-level menu or during the prepare flow). Profiles cover looping, channel/CV immediacy, pitch mode, click reduction, and LED display behaviour.

Key `settings.txt` parameters:

| Setting | Description |
|---------|-------------|
| `Looping` | `1` = loop, `0` = play once |
| `ChanPotImmediate` | Station knob takes effect immediately |
| `ChanCVImmediate` | Station CV takes effect immediately |
| `StartCVDivider` | Divides CV resolution for start position (1 = full, 2 = half, …) |
| `pitchMode` | `1` = START input controls pitch/speed; `0` = controls position |
| `MUTE` / `DECLICK` | Fade audio on channel change to reduce clicks |
| `ShowMeter` / `meterHIDE` | VU meter vs. binary bank display |

Full reference: [Radio Music wiki — settings.txt](https://github.com/TomWhitwell/RadioMusic/wiki/Customise-your-module%3A-Editing-settings.txt)

---

## Configuration

`config.json` — runtime settings:

| Key | Description | Default |
|-----|-------------|---------|
| `rootFolder` | Root directory for all device output folders | `./card_folders/` |
| `emptyFolder` | Placeholder RAW files seeded into empty Radio Music banks | `./empty_folder/` |
| `localSource` | Default source folder | `./source_material/` |
| `overwriteConvertedFiles` | Pass `-y` to ffmpeg | `true` |
| `normalizeVolume` | Apply loudnorm filter during conversion | `false` |
| `profiles` | Radio Music settings profiles | — |

---

## Adding sample packs to the catalogue

`data.json` lists packs available for download. Each entry:

```json
{
    "key":  "short-unique-slug",
    "name": "Display name shown in picker",
    "url":  "https://example.com/samples.zip"
}
```

Only add packs with verified direct-download ZIP URLs. Do not guess or fabricate URLs.

---

## Development

```bash
uv run sampler-prep          # run the wizard
uv run ruff check samplerprep/ && uv run ruff format --check samplerprep/
```

Requires `ffmpeg` on the system PATH. Optionally `sox` for the preview browser.

Project layout:

```
samplerprep/
  __main__.py     ← wizard entry point
  core.py         ← shared utilities (ffmpeg, rsync, Freesound, …)
  devices.json    ← device specs
  drivers/
    radio_music.py
    morphagene.py
    digitakt.py
    octatrack.py
    tracker.py
    rample.py
    queen.py
    bitbox.py
    squid.py
config.json       ← runtime config and Radio Music profiles
data.json         ← downloadable sample pack catalogue
empty_folder/     ← placeholder RAW files for Radio Music skeleton
source_material/  ← default input folder (gitignored)
card_folders/     ← output (gitignored)
```
