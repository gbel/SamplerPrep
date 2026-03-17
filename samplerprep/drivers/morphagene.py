"""Make Noise Morphagene driver.

Output: files in root of target_folder, named mg1.wav–mgw.wav (32 reels max).
Format: 32-bit float stereo WAV at 48000 Hz.
"""

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import questionary
from questionary import Choice

from samplerprep.core import (
    EXT_OTHER,
    EXT_RAW,
    ask_int,
    convert_file,
    find_files,
    getch_timeout,
    print_step,
    read_wav_cues,
    read_wav_info,
    write_wav_cues,
)

# Morphagene naming: mg1–mg9, then mga–mgw (32 total)
_REEL_NAMES = [f"mg{i}" for i in range(1, 10)] + [f"mg{c}" for c in "abcdefghijklmnopqrstuvw"]
MAX_REELS = 32
_TARGET_SR = 48000  # Morphagene hardware sample rate


def _concat_wavs(wav_files: list[Path], output_path: Path) -> None:
    """Concatenate wav_files into output_path using ffmpeg concat demuxer."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        list_file = Path(f.name)
        f.write("\n".join(f"file '{p}'" for p in wav_files))
    try:
        cmd = [
            "ffmpeg",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            "-y",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        list_file.unlink(missing_ok=True)


def _rubberband_available() -> bool:
    return shutil.which("rubberband") is not None


def _apply_rubberband(wav_path: Path, pitch_semitones: int = 0, tempo_factor: float = 1.0) -> None:
    """Apply rubberband pitch/tempo shift to wav_path in-place (via a temp file)."""
    tmp = wav_path.with_suffix(".rb_out.wav")
    cmd = ["rubberband", "-2"]
    if pitch_semitones:
        cmd += ["-p", str(pitch_semitones)]
    if tempo_factor != 1.0:
        cmd += ["-t", str(tempo_factor)]
    cmd += [str(wav_path), str(tmp)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tmp.replace(wav_path)


def _aubio_available() -> bool:
    try:
        import aubio  # noqa: F401

        return True
    except ImportError:
        return False


def _detect_transients(wav_path: Path, threshold: float = 0.3) -> list[int]:
    """Return sample offsets of detected onsets in wav_path using aubio.

    Exports a mono downmix via ffmpeg first, since aubio onset detection
    works on mono audio. Detected positions are reported in the stereo
    reel's sample space (same sample rate, just one channel reference).
    """
    import aubio

    info = read_wav_info(wav_path)
    sr = info["sample_rate"]
    hop_size = 512
    win_size = 1024

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        mono_path = Path(f.name)
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            "-ac",
            "1",
            "-ar",
            str(sr),
            str(mono_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        src = aubio.source(str(mono_path), sr, hop_size)
        onset = aubio.onset("default", win_size, hop_size, sr)
        onset.set_threshold(threshold)

        offsets = []
        while True:
            samples, read = src()
            if onset(samples):
                pos = onset.get_last()
                if pos > 0:
                    offsets.append(pos)
            if read < hop_size:
                break
    finally:
        mono_path.unlink(missing_ok=True)

    return offsets


def process(source_folder, target_folder: Path, device, config, overwrite, normalize):
    files = find_files(str(source_folder), [EXT_RAW] + EXT_OTHER)
    print_step(f"Found {len(files)} files")

    if not files:
        print_step("No files found.")
        return

    # ── Pitch/tempo shift ─────────────────────────────────────────────────────
    pitch_semitones = 0
    tempo_factor = 1.0
    if _rubberband_available():
        shift_mode = questionary.select(
            "Pitch/tempo adjustment:",
            choices=[
                Choice("None — no adjustment", value="none"),
                Choice("Shift pitch", value="pitch"),
                Choice("Stretch tempo", value="tempo"),
            ],
        ).ask()
        if shift_mode == "pitch":
            pitch_semitones = ask_int("Semitones (negative = lower pitch):", 0, -24, 24)
        elif shift_mode == "tempo":
            raw = questionary.text("Tempo factor (e.g. 0.5 = half speed, 2.0 = double):").ask()
            try:
                tempo_factor = float(raw or "1.0")
            except ValueError:
                tempo_factor = 1.0

    # ── Reel creation mode ────────────────────────────────────────────────────
    reel_mode = questionary.select(
        "Reel creation:",
        choices=[
            Choice("One file per reel", value="per_file"),
            Choice("Concat all files → one reel", value="concat"),
        ],
    ).ask()

    if reel_mode == "per_file" and len(files) > MAX_REELS:
        print_step(
            f"⚠  {len(files)} files found — Morphagene supports max {MAX_REELS} reels. "
            f"Extra files will be skipped."
        )
        files = files[:MAX_REELS]

    # ── Splice markers ────────────────────────────────────────────────────────
    splice_choices = [Choice("None — plain conversion", value="none")]
    if reel_mode == "per_file":
        splice_choices.append(Choice("Preserve cue points from source WAVs", value="passthrough"))
    if reel_mode == "concat":
        splice_choices.append(
            Choice("File boundaries — one splice per source file", value="boundaries")
        )
    splice_choices.append(Choice("Even grid — splice every N seconds", value="grid"))
    if _aubio_available():
        splice_choices.append(Choice("Auto-detect transients (aubio)", value="transients"))
    else:
        splice_choices.append(
            Choice(
                "Auto-detect transients (aubio)",
                value="transients",
                disabled="run: brew install aubio",
            )
        )

    splice_mode = questionary.select("Splice markers:", choices=splice_choices).ask()

    grid_step_secs = 2
    if splice_mode == "grid":
        grid_step_secs = ask_int("Splice every N seconds:", 2, 1, 60)

    transient_threshold = 0.3
    if splice_mode == "transients":
        raw = questionary.text("Detection sensitivity 0.0–1.0 (lower = more splices) [0.3]:").ask()
        try:
            transient_threshold = max(0.0, min(1.0, float(raw or "0.3")))
        except ValueError:
            transient_threshold = 0.3

    target_folder.mkdir(parents=True, exist_ok=True)
    ext = device["extension"]

    if reel_mode == "concat":
        with tempfile.TemporaryDirectory() as _tmp:
            tmp = Path(_tmp)
            converted = []
            for i, src in enumerate(files):
                dst = tmp / f"{i:04d}.wav"
                convert_file(src, str(dst), device, overwrite, normalize)
                if pitch_semitones or tempo_factor != 1.0:
                    _apply_rubberband(dst, pitch_semitones, tempo_factor)
                converted.append(dst)
                print_step(f"Converted {Path(src).name}")

            output_path = target_folder / f"{_REEL_NAMES[0]}{ext}"
            print_step(f"Concatenating {len(converted)} files → {output_path.name}")
            _concat_wavs(converted, output_path)

            if splice_mode == "boundaries":
                offsets = []
                cumulative = 0
                for wav in converted[:-1]:  # boundary after each file except the last
                    cumulative += read_wav_info(wav)["num_samples"]
                    offsets.append(cumulative)
                if offsets:
                    write_wav_cues(output_path, offsets)
                    print_step(f"Wrote {len(offsets)} splice marker(s)")
            elif splice_mode == "grid":
                info = read_wav_info(output_path)
                step = grid_step_secs * info["sample_rate"]
                offsets = list(range(step, info["num_samples"], step))
                if offsets:
                    write_wav_cues(output_path, offsets)
                    print_step(f"Wrote {len(offsets)} splice marker(s)")
            elif splice_mode == "transients":
                offsets = _detect_transients(output_path, transient_threshold)
                if offsets:
                    write_wav_cues(output_path, offsets)
                    print_step(f"Wrote {len(offsets)} splice marker(s)")

        print_step(f"Done — 1 reel written to {target_folder}")

    else:  # per_file
        for i, src in enumerate(files):
            name = _REEL_NAMES[i]
            target_file = target_folder / f"{name}{ext}"
            print_step(src)
            if not target_file.exists() or overwrite:
                convert_file(src, str(target_file), device, overwrite, normalize)
                if pitch_semitones or tempo_factor != 1.0:
                    _apply_rubberband(target_file, pitch_semitones, tempo_factor)

            if splice_mode == "passthrough" and Path(src).suffix.lower() == ".wav":
                src_info = read_wav_info(Path(src))
                cues = read_wav_cues(Path(src))
                if cues and src_info["sample_rate"] and src_info["sample_rate"] != _TARGET_SR:
                    scale = _TARGET_SR / src_info["sample_rate"]
                    cues = [int(c * scale) for c in cues]
                if cues:
                    write_wav_cues(target_file, cues)
                    print_step(f"  → copied {len(cues)} splice marker(s)")
            elif splice_mode == "grid":
                info = read_wav_info(target_file)
                step = grid_step_secs * info["sample_rate"]
                offsets = list(range(step, info["num_samples"], step))
                if offsets:
                    write_wav_cues(target_file, offsets)
                    print_step(f"  → wrote {len(offsets)} splice marker(s)")
            elif splice_mode == "transients":
                offsets = _detect_transients(target_file, transient_threshold)
                if offsets:
                    write_wav_cues(target_file, offsets)
                    print_step(f"  → wrote {len(offsets)} splice marker(s)")

        print_step(f"Done — {len(files)} reel(s) written to {target_folder}")


def describe_output(device):
    return "Files in root: mg1.wav–mgw.wav (32 reels max), 32-bit float stereo 48 kHz"


# ── Preview browser ────────────────────────────────────────────────────────────


def _play_wav(path: Path, seek_secs: float = 0.0) -> subprocess.Popen:
    """Start playing a WAV file via sox/play in the background. Returns Popen handle."""
    cmd = ["play", str(path)]
    if seek_secs > 0:
        cmd += ["trim", str(seek_secs)]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _wav_duration(path: Path) -> float:
    info = read_wav_info(path)
    return info["num_samples"] / info["sample_rate"]


def _cues_for(path: Path) -> list[float]:
    """Return splice marker positions in seconds for a reel WAV."""
    info = read_wav_info(path)
    sr = info["sample_rate"]
    if not sr:
        return []
    return [c / sr for c in read_wav_cues(path)]


def _fmt_time(secs: float) -> str:
    secs = max(0.0, secs)
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"


def _render_preview_mg(
    reels: list[Path],
    cursor: int,
    playing_idx: int | None,
    elapsed: float | None,
    play_total: float | None,
    cue_cache: dict,
) -> None:
    BAR_WIDTH = 40
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write("Morphagene Preview\n")
    sys.stdout.write("[q] quit  [space] play/stop  [,/.] seek 5s  [[ / ]] prev/next splice\n\n")
    for i, reel in enumerate(reels):
        cur = ">" if i == cursor else " "
        play = "▶" if i == playing_idx else " "
        cues = cue_cache.get(i, [])
        cue_tag = f"  ({len(cues)} splices)" if cues else ""
        sys.stdout.write(f" {cur} {play}  {reel.name}{cue_tag}\n")
    sys.stdout.write("\n")
    if playing_idx is not None and elapsed is not None and play_total and play_total > 0:
        frac = min(1.0, elapsed / play_total)
        filled = int(frac * BAR_WIDTH)
        cues = cue_cache.get(playing_idx, [])
        bar = list("░" * BAR_WIDTH)
        for c in cues:
            idx = int(c / play_total * BAR_WIDTH)
            if 0 <= idx < BAR_WIDTH:
                bar[idx] = "|"
        for i in range(filled):
            if bar[i] != "|":
                bar[i] = "█"
        sys.stdout.write(f"[{''.join(bar)}]  {_fmt_time(elapsed)} / {_fmt_time(play_total)}\n")
    sys.stdout.flush()


def preview(target_folder: Path) -> None:
    """Interactive reel browser for a Morphagene card folder."""
    if not shutil.which("play"):
        print("sox 'play' not found — install with: brew install sox")
        return
    reels = sorted(
        (f for f in target_folder.glob("mg*.wav")),
        key=lambda f: _REEL_NAMES.index(f.stem) if f.stem in _REEL_NAMES else 999,
    )
    if not reels:
        print(f"No mg*.wav reels found in {target_folder}")
        return

    cursor = 0
    proc = None
    playing_idx: int | None = None
    play_start_time: float | None = None
    seek_offset = 0.0
    cue_cache: dict[int, list[float]] = {}

    def _load_cues(idx: int) -> None:
        if idx not in cue_cache:
            cue_cache[idx] = _cues_for(reels[idx])

    def current_elapsed() -> float | None:
        if play_start_time is None:
            return None
        return seek_offset + (time.monotonic() - play_start_time)

    def start_playback(idx: int, offset: float = 0.0) -> None:
        nonlocal proc, playing_idx, play_start_time, seek_offset
        proc = _play_wav(reels[idx], offset)
        playing_idx = idx
        seek_offset = offset
        play_start_time = time.monotonic()
        _load_cues(idx)

    def stop_playback() -> None:
        nonlocal proc, playing_idx, play_start_time, seek_offset
        if proc:
            proc.terminate()
            proc.wait()
        proc = None
        playing_idx = None
        play_start_time = None
        seek_offset = 0.0

    try:
        _load_cues(0)
        while True:
            if proc is not None and proc.poll() is not None:
                proc = None
                playing_idx = None
                play_start_time = None
                seek_offset = 0.0

            elapsed = current_elapsed()
            play_total = _wav_duration(reels[playing_idx]) if playing_idx is not None else None
            _render_preview_mg(reels, cursor, playing_idx, elapsed, play_total, cue_cache)

            key = getch_timeout(0.1)
            if key is None:
                continue

            if key in (b"q", b"Q", b"\x1b"):
                break
            elif key in (b"\x1b[A", b"k"):
                new_cursor = max(0, cursor - 1)
                if new_cursor != cursor:
                    cursor = new_cursor
                    _load_cues(cursor)
                    if proc and proc.poll() is None:
                        proc.terminate()
                        proc.wait()
                        start_playback(cursor)
            elif key in (b"\x1b[B", b"j"):
                new_cursor = min(len(reels) - 1, cursor + 1)
                if new_cursor != cursor:
                    cursor = new_cursor
                    _load_cues(cursor)
                    if proc and proc.poll() is None:
                        proc.terminate()
                        proc.wait()
                        start_playback(cursor)
            elif key == b" ":
                if proc and proc.poll() is None:
                    stop_playback()
                else:
                    start_playback(cursor)
            elif key == b",":
                if proc and proc.poll() is None and playing_idx is not None:
                    new_offset = max(0.0, (current_elapsed() or 0.0) - 5.0)
                    proc.terminate()
                    proc.wait()
                    start_playback(playing_idx, new_offset)
            elif key == b".":
                if proc and proc.poll() is None and playing_idx is not None:
                    total = _wav_duration(reels[playing_idx])
                    new_offset = min(total - 0.5, (current_elapsed() or 0.0) + 5.0)
                    proc.terminate()
                    proc.wait()
                    start_playback(playing_idx, new_offset)
            elif key == b"[":
                if proc and proc.poll() is None and playing_idx is not None:
                    el = current_elapsed() or 0.0
                    prev_cues = [c for c in cue_cache.get(playing_idx, []) if c < el - 0.1]
                    new_offset = prev_cues[-1] if prev_cues else 0.0
                    proc.terminate()
                    proc.wait()
                    start_playback(playing_idx, new_offset)
            elif key == b"]":
                if proc and proc.poll() is None and playing_idx is not None:
                    el = current_elapsed() or 0.0
                    next_cues = [c for c in cue_cache.get(playing_idx, []) if c > el + 0.1]
                    if next_cues:
                        proc.terminate()
                        proc.wait()
                        start_playback(playing_idx, next_cues[0])
    finally:
        if proc:
            proc.terminate()
            proc.wait()
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
