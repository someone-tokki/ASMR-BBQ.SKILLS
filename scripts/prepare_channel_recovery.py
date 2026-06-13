#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from subtitle_io import format_srt_timestamp, parse_srt_text


@dataclass
class Window:
    start: float
    end: float
    reason: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def parse_time(value: str) -> float:
    text = value.strip().replace(",", ".")
    if not text:
        raise ValueError("empty timestamp")
    parts = text.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {value!r}") from exc
    raise ValueError(f"invalid timestamp: {value!r}")


def format_time(seconds: float) -> str:
    return format_srt_timestamp(timedelta(seconds=max(0.0, seconds))).replace(",", ".")


def parse_window(value: str) -> Window:
    if "-" not in value:
        raise ValueError(f"window must be START-END: {value!r}")
    start_text, end_text = value.split("-", 1)
    start = parse_time(start_text)
    end = parse_time(end_text)
    if end <= start:
        raise ValueError(f"window end must be after start: {value!r}")
    return Window(start=start, end=end, reason="user_window")


def audio_duration(path: Path) -> float:
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe is required to inspect audio duration")
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path.as_posix(),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


def clamp_window(window: Window, *, duration: float, pad: float, min_duration: float) -> Window | None:
    start = max(0.0, window.start - pad)
    end = min(duration, window.end + pad)
    if end - start < min_duration:
        return None
    return Window(start=start, end=end, reason=window.reason)


def windows_from_srt(path: Path, *, duration: float, min_gap: float, min_duration: float) -> list[Window]:
    subtitles = parse_srt_text(path.read_text(encoding="utf-8"))
    windows: list[Window] = []
    cursor = 0.0
    for subtitle in subtitles:
        start = subtitle.start.total_seconds()
        end = subtitle.end.total_seconds()
        if start - cursor >= min_gap and start - cursor >= min_duration:
            windows.append(Window(start=cursor, end=start, reason="main_asr_gap"))
        cursor = max(cursor, end)
    if duration - cursor >= min_gap and duration - cursor >= min_duration:
        windows.append(Window(start=cursor, end=duration, reason="main_asr_gap"))
    return windows


def merge_windows(windows: list[Window], *, merge_gap: float = 0.25) -> list[Window]:
    if not windows:
        return []
    ordered = sorted(windows, key=lambda item: (item.start, item.end))
    merged = [ordered[0]]
    for window in ordered[1:]:
        previous = merged[-1]
        if window.start <= previous.end + merge_gap:
            previous.end = max(previous.end, window.end)
            if window.reason not in previous.reason.split("+"):
                previous.reason += f"+{window.reason}"
        else:
            merged.append(window)
    return merged


def run_ffmpeg_split(audio_path: Path, window: Window, left_path: Path, right_path: Path, *, overwrite: bool) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to split stereo channel recovery clips")
    left_path.parent.mkdir(parents=True, exist_ok=True)
    right_path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and left_path.exists() and right_path.exists():
        return
    base = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{window.start:.3f}",
        "-t",
        f"{window.duration:.3f}",
        "-i",
        audio_path.as_posix(),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
    ]
    left_command = base + ["-af", "pan=mono|c0=c0", "-y" if overwrite else "-n", left_path.as_posix()]
    right_command = base + ["-af", "pan=mono|c0=c1", "-y" if overwrite else "-n", right_path.as_posix()]
    subprocess.run(left_command, check=True)
    subprocess.run(right_command, check=True)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def render_review(manifest: dict[str, Any]) -> str:
    lines = [
        "# Channel Recovery Review",
        "",
        "Purpose: these clips are candidates for ASMR stereo/multi-speaker recovery. Do not merge them into the main ASR automatically.",
        "",
        "Workflow:",
        "",
        "1. Transcribe the left/right clips with the selected ASR backend.",
        "2. Compare recovered left/right text with the main ASR, neighboring subtitles, and audio context.",
        "3. Accept only clear missing speech. Reject noise, breath-only hallucinations, duplicated main-ASR text, and uncertain guesses.",
        "4. If both channels contain simultaneous valid speech, keep channel labels through translation, such as `【左】...` and `【右】...`.",
        "",
        "Suggested local ASR commands:",
        "",
        "```bash",
        "python scripts/transcribe_openai_audio.py \\",
        f"  {manifest['artifacts']['clips_dir']!r} \\",
        f"  --out-dir {manifest['artifacts']['asr_out_dir']!r} \\",
        "  --base-url \"$ASR_BASE_URL\" \\",
        "  --model \"$ASR_MODEL\" \\",
        "  --glob \"*.wav\"",
        "",
        "python scripts/transcribe_whisper.py \\",
        f"  {manifest['artifacts']['clips_dir']!r} \\",
        f"  --out-dir {manifest['artifacts']['asr_out_dir']!r} \\",
        "  --model \"$ASR_MODEL\" \\",
        "  --glob \"*.wav\"",
        "```",
        "",
        "Windows:",
        "",
    ]
    for item in manifest["windows"]:
        lines.extend(
            [
                f"## W{item['id']:03d} {item['start']} - {item['end']}",
                "",
                f"- reason: {item['reason']}",
                f"- left_clip: `{item['left_clip']}`",
                f"- right_clip: `{item['right_clip']}`",
                "- decision: pending / accept-left / accept-right / accept-both / reject",
                "- note: ",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_manifest(audio_path: Path, out_dir: Path, windows: list[Window], *, dry_run: bool) -> dict[str, Any]:
    clips_dir = out_dir / "clips"
    asr_out_dir = out_dir / "asr"
    items: list[dict[str, Any]] = []
    for number, window in enumerate(windows, start=1):
        stem = f"{audio_path.stem}__w{number:03d}__{format_time(window.start).replace(':', '').replace('.', '')}_{format_time(window.end).replace(':', '').replace('.', '')}"
        left_clip = clips_dir / f"{stem}__left.wav"
        right_clip = clips_dir / f"{stem}__right.wav"
        items.append(
            {
                "id": number,
                "start": format_time(window.start),
                "end": format_time(window.end),
                "start_seconds": round(window.start, 3),
                "end_seconds": round(window.end, 3),
                "duration_seconds": round(window.duration, 3),
                "reason": window.reason,
                "left_clip": left_clip.as_posix(),
                "right_clip": right_clip.as_posix(),
                "status": "planned" if dry_run else "clips_ready",
            }
        )
    return {
        "version": 1,
        "audio": audio_path.as_posix(),
        "mode": "channel_recovery",
        "policy": {
            "default": "candidate_only",
            "merge_behavior": "do_not_auto_merge",
            "translation_hint": "keep channel labels for simultaneous valid speech",
        },
        "artifacts": {
            "out_dir": out_dir.as_posix(),
            "clips_dir": clips_dir.as_posix(),
            "asr_out_dir": asr_out_dir.as_posix(),
            "review": (out_dir / "channel_recovery_review.md").as_posix(),
        },
        "windows": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare stereo channel recovery clips for ASMR multi-speaker ASR gaps.")
    parser.add_argument("audio", help="Stereo audio file to inspect/split.")
    parser.add_argument("--out-dir", required=True, help="Recovery output directory, usually $PROJECT_ROOT/channel_recovery/<track>.")
    parser.add_argument("--window", action="append", default=[], help="Candidate START-END window. Repeatable. Example: 03:12-03:28")
    parser.add_argument("--from-srt", help="Main ASR SRT. Gaps in this timeline become candidate recovery windows.")
    parser.add_argument("--min-gap", type=float, default=2.0, help="Minimum main-ASR gap seconds when using --from-srt.")
    parser.add_argument("--min-duration", type=float, default=0.8, help="Drop candidate windows shorter than this many seconds after padding.")
    parser.add_argument("--pad", type=float, default=0.25, help="Seconds to pad before/after each candidate window.")
    parser.add_argument("--max-windows", type=int, default=80, help="Maximum windows to prepare.")
    parser.add_argument("--dry-run", action="store_true", help="Write manifest/review without creating audio clips.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing recovery clips.")
    args = parser.parse_args()

    audio_path = Path(args.audio)
    out_dir = Path(args.out_dir)
    if not audio_path.exists():
        raise SystemExit(f"Audio file not found: {audio_path}")
    duration = audio_duration(audio_path)

    raw_windows = [parse_window(value) for value in args.window]
    if args.from_srt:
        raw_windows.extend(
            windows_from_srt(
                Path(args.from_srt),
                duration=duration,
                min_gap=args.min_gap,
                min_duration=args.min_duration,
            )
        )
    if not raw_windows:
        raise SystemExit("No recovery windows. Use --window START-END or --from-srt.")

    windows = [
        window
        for window in (clamp_window(item, duration=duration, pad=args.pad, min_duration=args.min_duration) for item in raw_windows)
        if window is not None
    ]
    windows = merge_windows(windows)[: args.max_windows]
    if not windows:
        raise SystemExit("No recovery windows remain after filtering.")

    manifest = build_manifest(audio_path, out_dir, windows, dry_run=args.dry_run)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.dry_run:
        for item, window in zip(manifest["windows"], windows, strict=True):
            run_ffmpeg_split(
                audio_path,
                window,
                Path(item["left_clip"]),
                Path(item["right_clip"]),
                overwrite=args.overwrite,
            )

    manifest_path = out_dir / "channel_recovery_manifest.json"
    review_path = out_dir / "channel_recovery_review.md"
    write_json(manifest_path, manifest)
    review_path.write_text(render_review(manifest), encoding="utf-8")
    print(f"WROTE {manifest_path}")
    print(f"WROTE {review_path}")
    if not args.dry_run:
        print(f"WROTE {len(windows) * 2} channel clip(s) under {out_dir / 'clips'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
