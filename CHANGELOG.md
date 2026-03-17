# Changelog

## v0.2.0 — 2026-03-16

### Features

- **Morphagene splice markers** — four modes per reel: none, file boundaries (concat mode), even grid every N seconds, and auto-detect transients via aubio; splice markers stored as standard WAV cue chunks readable by Reaper and other DAWs
- **Morphagene cue point passthrough** — existing cue points from source WAVs are preserved and rescaled to 48 kHz when converting per-file reels
- **Morphagene pitch/tempo shift** — optional rubberband integration; shift pitch by semitones or stretch tempo by a factor, applied before or after conversion (`brew install rubberband`)
- **Morphagene interactive preview browser** — reel list with splice count display, live playback via sox, progress bar with `|` ticks at each splice position, `[`/`]` to jump between splices
- **aubio availability hint** — when aubio is not installed the "Auto-detect transients" option appears greyed-out with the install command (`brew install aubio`)
- **Radio Music preview improvements** — live elapsed time and progress bar, 5-second seek forward/back with `,`/`.`, auto-switch playback when navigating to a new file

### Internal

- Python 3.14 dev environment pin; venv configured with `--system-site-packages` for native brew aubio compatibility
- sdist excludes local data directories (`card_folders/`, `source_material/`, `AP Card/`) to prevent accidentally packaging large audio files

---

## v0.1.0 — 2026-03-15

First public release.

### Features

- **7-device support** — Radio Music, Morphagene, Digitakt, Octatrack, Tracker, Rample, Queen of Pentacles
- **Device-driven wizard** — device selected first, drives all subsequent steps (output format, folder structure, file limits)
- **Freesound.org search integration** — search and download samples directly from within the wizard
- **Interactive preview browser** — audition files before committing (Radio Music)
- **Settings profile wizard** — choose between default, oneshots, and immediate playback profiles (Radio Music)
- **Subfolder picker** — navigate nested source directories without leaving the wizard
- **SD card rsync** — copy prepared volumes to a mounted SD card with add or replace modes, optional backup, and selective folder sync
- **Ctrl-C safe interrupt** — clean exit during processing without leaving partial output
- **Loudnorm volume normalisation** — optional EBU R128 normalisation pass via ffmpeg
