# Changelog

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
