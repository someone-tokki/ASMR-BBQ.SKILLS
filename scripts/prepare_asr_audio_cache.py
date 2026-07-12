#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".webm"}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def collect_audio(input_path: Path, pattern: str, recursive: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in AUDIO_EXTENSIONS else []
    glob_pattern = f"**/{pattern}" if recursive else pattern
    return sorted(path for path in input_path.glob(glob_pattern) if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS)


def wav_duration(path: Path) -> float | None:
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(path.as_posix(), "rb") as handle:
            rate = handle.getframerate()
            if rate:
                return handle.getnframes() / float(rate)
    except Exception:
        return None
    return None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def safe_stem(path: Path) -> str:
    stem = path.stem.strip() or "audio"
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in stem)


def build_segments(duration: float | None, *, segment_sec: float, overlap_sec: float) -> list[dict[str, Any]]:
    if not duration or duration <= 0:
        return [
            {
                "segment_index": 1,
                "start_sec": 0.0,
                "end_sec": None,
                "overlap_before_sec": 0.0,
                "overlap_after_sec": overlap_sec,
                "status": "planned_unknown_duration",
            }
        ]
    segments: list[dict[str, Any]] = []
    start = 0.0
    index = 1
    while start < duration:
        end = min(duration, start + segment_sec)
        segments.append(
            {
                "segment_index": index,
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "overlap_before_sec": overlap_sec if index > 1 else 0.0,
                "overlap_after_sec": overlap_sec if end < duration else 0.0,
                "status": "planned",
            }
        )
        if end >= duration:
            break
        start = max(0.0, end - overlap_sec)
        index += 1
    return segments


def normalize_audio(source: Path, target: Path, *, force: bool, output_format: str) -> str:
    if target.exists() and not force:
        return "cached"
    if not ffmpeg_available():
        return "ffmpeg_unavailable"
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        source.as_posix(),
        "-ac",
        "1",
        "-ar",
        "16000",
    ]
    if output_format == "mp3":
        command.extend(["-codec:a", "libmp3lame", "-b:a", "64k"])
    command.append(target.as_posix())
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "created"


def prepare_file(audio: Path, cache_root: Path, *, segment_sec: float, overlap_sec: float, normalize: bool, output_format: str, force: bool) -> dict[str, Any]:
    track_dir = cache_root / safe_stem(audio)
    track_dir.mkdir(parents=True, exist_ok=True)
    normalized = track_dir / f"normalized_16k_mono.{output_format}"
    duration = wav_duration(audio)
    normalize_status = "not_requested"
    if normalize:
        normalize_status = normalize_audio(audio, normalized, force=force, output_format=output_format)
    segments = build_segments(duration, segment_sec=segment_sec, overlap_sec=overlap_sec)
    record = {
        "version": 1,
        "source_audio": audio.as_posix(),
        "track_dir": track_dir.as_posix(),
        "normalized_audio": normalized.as_posix() if normalize_status in {"created", "cached"} else "",
        "normalize_status": normalize_status,
        "duration_sec": duration,
        "segment_sec": segment_sec,
        "overlap_sec": overlap_sec,
        "segments": segments,
        "resume_policy": "ASR may transcribe missing segments only; do not delete successful segment transcripts on rerun.",
        "vad_policy": "VAD is intentionally not applied here. If later enabled, it must preserve quiet whispers, breaths, and important pauses.",
        "updated_at": now_utc(),
    }
    (track_dir / "segments.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a conservative ASR audio cache and segment resume plan.")
    parser.add_argument("input", help="Audio file or directory.")
    parser.add_argument("--cache-dir", required=True, help="Usually $PROJECT_ROOT/asr_prepared.")
    parser.add_argument("--glob", default="*.wav")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--segment-sec", type=float, default=900.0)
    parser.add_argument("--overlap-sec", type=float, default=8.0)
    parser.add_argument("--normalize", action="store_true", help="Use ffmpeg to create normalized 16k mono audio when available.")
    parser.add_argument("--normalize-format", choices=["wav", "mp3"], default="wav", help="Use MP3 for faster WAV-only ASR I/O; defaults to WAV for lossless preparation.")
    parser.add_argument("--cleanup-mp3", action="store_true", help="Delete only generated normalized_16k_mono.mp3 cache files, then exit.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    input_path = Path(args.input)
    cache_root = Path(args.cache_dir)
    if args.cleanup_mp3:
        removed = 0
        if cache_root.exists():
            for prepared in cache_root.rglob("normalized_16k_mono.mp3"):
                prepared.unlink()
                removed += 1
        print(json.dumps({"cache_dir": cache_root.as_posix(), "removed_mp3_files": removed}, ensure_ascii=False))
        return 0
    audio_files = collect_audio(input_path, args.glob, args.recursive)
    if not audio_files:
        raise SystemExit(f"No supported audio files found: {input_path}")
    records = [
        prepare_file(
            audio,
            cache_root,
            segment_sec=args.segment_sec,
            overlap_sec=args.overlap_sec,
            normalize=args.normalize,
            output_format=args.normalize_format,
            force=args.force,
        )
        for audio in audio_files
    ]
    report = {
        "version": 1,
        "cache_dir": cache_root.as_posix(),
        "audio_count": len(records),
        "normalize_requested": args.normalize,
        "normalize_format": args.normalize_format,
        "ffmpeg_available": ffmpeg_available(),
        "records": records,
        "updated_at": now_utc(),
    }
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
