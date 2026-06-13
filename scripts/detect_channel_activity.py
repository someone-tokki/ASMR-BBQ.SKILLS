#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import struct
import sys
import tempfile
import wave
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from subtitle_io import format_srt_timestamp, parse_srt_text


@dataclass
class Frame:
    start: float
    end: float
    left_rms: int
    right_rms: int
    left_db: float
    right_db: float
    max_db: float
    diff_db: float
    asr_covered: bool
    asr_state: str
    asr_text: str
    active: bool
    side: str
    score: float
    reasons: list[str]


def dbfs(rms: int) -> float:
    if rms <= 0:
        return -120.0
    return 20.0 * math.log10(min(rms, 32767) / 32767.0)


def format_time(seconds: float) -> str:
    return format_srt_timestamp(timedelta(seconds=max(0.0, seconds))).replace(",", ".")


def run_ffmpeg_pcm(audio_path: Path, output: Path) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required for channel activity detection")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        audio_path.as_posix(),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "16000",
        "-sample_fmt",
        "s16",
        "-y",
        output.as_posix(),
    ]
    subprocess.run(command, check=True)


def read_pcm_frames(path: Path, *, frame_seconds: float) -> tuple[list[tuple[float, float, int, int]], float]:
    frames: list[tuple[float, float, int, int]] = []
    with wave.open(path.as_posix(), "rb") as wav:
        if wav.getnchannels() != 2 or wav.getsampwidth() != 2:
            raise RuntimeError("internal PCM must be 16-bit stereo")
        rate = wav.getframerate()
        total_frames = wav.getnframes()
        step = max(1, int(rate * frame_seconds))
        cursor = 0
        while cursor < total_frames:
            raw = wav.readframes(step)
            if not raw:
                break
            start = cursor / rate
            end = min(total_frames, cursor + step) / rate
            left_rms, right_rms = stereo_rms(raw)
            frames.append((start, end, left_rms, right_rms))
            cursor += step
        duration = total_frames / rate
    return frames, duration


def stereo_rms(raw: bytes) -> tuple[int, int]:
    left_sum = 0
    right_sum = 0
    count = 0
    for left, right in struct.iter_unpack("<hh", raw[: len(raw) - (len(raw) % 4)]):
        left_sum += left * left
        right_sum += right * right
        count += 1
    if count == 0:
        return 0, 0
    return int(math.sqrt(left_sum / count)), int(math.sqrt(right_sum / count))


def normalize_asr_text(text: str) -> str:
    return "".join(text.split()).strip()


WEAK_ASR_TEXTS = {
    "…",
    "……",
    "...",
    "。。",
    "。。。",
    "ん",
    "んっ",
    "うん",
    "ううん",
    "あ",
    "あっ",
    "ああ",
    "はぁ",
    "はあ",
    "ハァ",
    "ふぅ",
    "ふう",
    "ちゅ",
    "ちゅっ",
    "チュ",
    "チュッ",
    "嗯",
    "嗯嗯",
    "啊",
    "啊啊",
    "哈",
    "哈啊",
}


def is_punctuation_only(text: str) -> bool:
    return bool(text) and all(not char.isalnum() and not ("\u3040" <= char <= "\u30ff") and not ("\u4e00" <= char <= "\u9fff") for char in text)


def is_weak_asr_text(text: str, *, duration: float) -> bool:
    normalized = normalize_asr_text(text)
    if not normalized:
        return True
    lowered = normalized.lower()
    if normalized in WEAK_ASR_TEXTS or lowered in WEAK_ASR_TEXTS:
        return True
    if is_punctuation_only(normalized):
        return True
    unique_chars = set(normalized)
    if len(normalized) >= 3 and len(unique_chars) <= 2 and any(char in normalized for char in "…。.、,・~ー-"):
        return True
    if len(normalized) <= 4 and any(token in normalized for token in ("ん", "あ", "は", "ふ", "ちゅ", "嗯", "啊", "哈")):
        return True
    text_density = len(normalized) / max(duration, 0.1)
    if duration >= 2.5 and len(normalized) <= 4:
        return True
    if duration >= 4.0 and text_density <= 1.0:
        return True
    return False


def asr_intervals(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    subtitles = parse_srt_text(path.read_text(encoding="utf-8"))
    intervals: list[dict[str, Any]] = []
    for item in subtitles:
        start = item.start.total_seconds()
        end = item.end.total_seconds()
        text = normalize_asr_text(item.content)
        intervals.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "weak": is_weak_asr_text(text, duration=end - start),
            }
        )
    return intervals


def asr_coverage(intervals: list[dict[str, Any]], start: float, end: float) -> tuple[str, str]:
    overlapping = [item for item in intervals if float(item["start"]) < end and float(item["end"]) > start]
    if not overlapping:
        return "none", ""
    if any(not bool(item["weak"]) for item in overlapping):
        text = " / ".join(str(item["text"]) for item in overlapping if not bool(item["weak"]))[:120]
        return "strong", text
    text = " / ".join(str(item["text"]) for item in overlapping)[:120]
    return "weak", text


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return -60.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


def classify_frames(
    raw_frames: list[tuple[float, float, int, int]],
    *,
    intervals: list[dict[str, Any]],
    threshold_db: float | None,
    diff_db: float,
    noise_margin_db: float,
) -> tuple[list[Frame], dict[str, Any]]:
    max_values = [max(dbfs(left), dbfs(right)) for _, _, left, right in raw_frames]
    noise_floor = percentile(max_values, 0.2)
    dynamic_threshold = max(noise_floor + noise_margin_db, -48.0)
    active_threshold = threshold_db if threshold_db is not None else dynamic_threshold
    frames: list[Frame] = []
    for start, end, left_rms, right_rms in raw_frames:
        left_db = dbfs(left_rms)
        right_db = dbfs(right_rms)
        max_db = max(left_db, right_db)
        channel_diff = abs(left_db - right_db)
        asr_state, asr_text = asr_coverage(intervals, start, end)
        asr_covered = asr_state != "none"
        active = max_db >= active_threshold
        reasons: list[str] = []
        score = 0.0
        side = "balanced"
        if active:
            reasons.append("channel_energy_active")
            score += 1.0
        if asr_state == "none":
            reasons.append("main_asr_gap")
            score += 1.25
        elif asr_state == "weak":
            reasons.append("weak_main_asr_coverage")
            score += 0.9
        else:
            reasons.append("strong_main_asr_coverage")
            score -= 0.5
        if channel_diff >= diff_db:
            side = "left" if left_db > right_db else "right"
            reasons.append(f"{side}_dominant")
            score += 0.75
        elif active:
            reasons.append("both_channels_active_or_balanced")
            score += 0.3
        if max_db >= active_threshold + 8:
            reasons.append("strong_energy")
            score += 0.4
        frames.append(
            Frame(
                start=start,
                end=end,
                left_rms=left_rms,
                right_rms=right_rms,
                left_db=left_db,
                right_db=right_db,
                max_db=max_db,
                diff_db=channel_diff,
                asr_covered=asr_covered,
                asr_state=asr_state,
                asr_text=asr_text,
                active=active,
                side=side,
                score=score,
                reasons=reasons,
            )
        )
    stats = {
        "noise_floor_db": round(noise_floor, 2),
        "active_threshold_db": round(active_threshold, 2),
        "threshold_source": "explicit" if threshold_db is not None else "dynamic",
    }
    return frames, stats


def frame_to_candidate(frames: list[Frame], *, min_duration: float) -> dict[str, Any] | None:
    start = frames[0].start
    end = frames[-1].end
    if end - start < min_duration:
        return None
    avg_left = sum(item.left_db for item in frames) / len(frames)
    avg_right = sum(item.right_db for item in frames) / len(frames)
    max_db = max(item.max_db for item in frames)
    avg_score = sum(item.score for item in frames) / len(frames)
    gap_ratio = sum(1 for item in frames if item.asr_state == "none") / len(frames)
    weak_ratio = sum(1 for item in frames if item.asr_state == "weak") / len(frames)
    gap_or_weak_ratio = sum(1 for item in frames if item.asr_state in {"none", "weak"}) / len(frames)
    active_ratio = sum(1 for item in frames if item.active) / len(frames)
    dominant_left = sum(1 for item in frames if item.side == "left")
    dominant_right = sum(1 for item in frames if item.side == "right")
    reasons = sorted({reason for frame in frames for reason in frame.reasons})
    confidence_score = avg_score + gap_or_weak_ratio * 0.6 + active_ratio * 0.4
    if confidence_score >= 2.7 and gap_or_weak_ratio >= 0.6:
        confidence = "high"
    elif confidence_score >= 1.8:
        confidence = "medium"
    else:
        confidence = "low"
    reasons.append("speech_not_confirmed_energy_only")
    reasons.append("needs_user_disambiguation")
    side = "balanced"
    if dominant_left > dominant_right and dominant_left >= len(frames) * 0.4:
        side = "left"
    elif dominant_right > dominant_left and dominant_right >= len(frames) * 0.4:
        side = "right"
    return {
        "start": format_time(start),
        "end": format_time(end),
        "start_seconds": round(start, 3),
        "end_seconds": round(end, 3),
        "duration_seconds": round(end - start, 3),
        "confidence": confidence,
        "confidence_score": round(confidence_score, 3),
        "side_hint": side,
        "avg_left_db": round(avg_left, 2),
        "avg_right_db": round(avg_right, 2),
        "max_db": round(max_db, 2),
        "asr_gap_ratio": round(gap_ratio, 3),
        "weak_asr_coverage_ratio": round(weak_ratio, 3),
        "gap_or_weak_coverage_ratio": round(gap_or_weak_ratio, 3),
        "active_ratio": round(active_ratio, 3),
        "reasons": reasons,
        "review_required": True,
        "user_disambiguation_required": True,
    }


def merge_active_frames(frames: list[Frame], *, merge_gap: float, min_duration: float) -> list[dict[str, Any]]:
    groups: list[list[Frame]] = []
    current: list[Frame] = []
    for frame in frames:
        candidate = frame.active and (
            "main_asr_gap" in frame.reasons
            or "weak_main_asr_coverage" in frame.reasons
            or frame.diff_db >= 5.0
        )
        if not candidate:
            if current:
                groups.append(current)
                current = []
            continue
        if current and frame.start > current[-1].end + merge_gap:
            groups.append(current)
            current = []
        current.append(frame)
    if current:
        groups.append(current)
    candidates: list[dict[str, Any]] = []
    for group in groups:
        item = frame_to_candidate(group, min_duration=min_duration)
        if item:
            candidates.append(item)
    return candidates


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def render_report(data: dict[str, Any]) -> str:
    lines = [
        "# Channel Activity Candidates",
        "",
        "This report detects possible stereo/multi-speaker ASR recovery windows from channel energy and the main ASR timeline.",
        "It is not proof of speech. ASMR breaths, kisses, licking, rubbing, BGM, and effects can look active. Review candidates before running recovery ASR or merging text.",
        "",
        f"- audio: `{data['audio']}`",
        f"- main_asr: `{data.get('main_asr') or 'not provided'}`",
        f"- active_threshold_db: `{data['analysis']['active_threshold_db']}` ({data['analysis']['threshold_source']})",
        f"- noise_floor_db: `{data['analysis']['noise_floor_db']}`",
        f"- candidates: `{len(data['candidates'])}`",
        "",
    ]
    if not data["candidates"]:
        lines.extend(["No channel activity candidates found.", ""])
    for number, item in enumerate(data["candidates"], start=1):
        flags = ", ".join(item["reasons"])
        reminder = " 用户需甄别：能量检测不能确认这是台词。"
        lines.extend(
            [
                f"## C{number:03d} {item['start']} - {item['end']}",
                "",
                f"- confidence: `{item['confidence']}`{reminder}",
                f"- side_hint: `{item['side_hint']}`",
                f"- avg_left_db / avg_right_db: `{item['avg_left_db']}` / `{item['avg_right_db']}`",
                f"- asr_gap_ratio: `{item['asr_gap_ratio']}`",
                f"- weak_asr_coverage_ratio: `{item['weak_asr_coverage_ratio']}`",
                f"- reasons: {flags}",
                "- review_decision: pending / prepare-recovery / ignore",
                "- note: ",
                "",
            ]
        )
    lines.extend(
        [
            "## Next Step",
            "",
            "High confidence means strong channel activity around a main-ASR gap, not confirmed speech. Ask the user or listen when the segment could be ASMR sound effects before spending ASR time or merging text.",
            "",
        ]
    )
    return "\n".join(lines)


def prepare_recovery(audio: Path, out_dir: Path, candidates: list[dict[str, Any]], *, min_confidence: str) -> None:
    order = {"low": 0, "medium": 1, "high": 2}
    threshold = order[min_confidence]
    windows = [
        f"{item['start']}-{item['end']}"
        for item in candidates
        if order.get(str(item.get("confidence")), 0) >= threshold
    ]
    if not windows:
        return
    command = [
        sys.executable,
        str(Path(__file__).with_name("prepare_channel_recovery.py")),
        audio.as_posix(),
        "--out-dir",
        out_dir.as_posix(),
    ]
    for window in windows:
        command.extend(["--window", window])
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect possible stereo channel ASR recovery windows from audio activity.")
    parser.add_argument("audio")
    parser.add_argument("--main-asr", help="Main ASR SRT used to suppress already-covered spans and find gaps.")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--report-out", help="Markdown report path. Defaults to <json-out>.md.")
    parser.add_argument("--frame-seconds", type=float, default=0.5)
    parser.add_argument("--threshold-db", type=float, help="Explicit active threshold in dBFS. Defaults to dynamic noise floor + margin.")
    parser.add_argument("--noise-margin-db", type=float, default=10.0)
    parser.add_argument("--diff-db", type=float, default=6.0)
    parser.add_argument("--merge-gap", type=float, default=0.75)
    parser.add_argument("--min-duration", type=float, default=1.0)
    parser.add_argument("--prepare-out", help="Optional channel recovery output dir. Candidate clips are prepared after detection.")
    parser.add_argument("--prepare-min-confidence", choices=["low", "medium", "high"], default="high")
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        raise SystemExit(f"Audio file not found: {audio_path}")
    main_asr = Path(args.main_asr) if args.main_asr else None
    if main_asr and not main_asr.exists():
        raise SystemExit(f"Main ASR SRT not found: {main_asr}")

    with tempfile.TemporaryDirectory(prefix="channel-activity-") as temp_dir:
        pcm_path = Path(temp_dir) / "audio.wav"
        run_ffmpeg_pcm(audio_path, pcm_path)
        raw_frames, duration = read_pcm_frames(pcm_path, frame_seconds=args.frame_seconds)

    intervals = asr_intervals(main_asr)
    frames, stats = classify_frames(
        raw_frames,
        intervals=intervals,
        threshold_db=args.threshold_db,
        diff_db=args.diff_db,
        noise_margin_db=args.noise_margin_db,
    )
    candidates = merge_active_frames(frames, merge_gap=args.merge_gap, min_duration=args.min_duration)
    data = {
        "version": 1,
        "audio": audio_path.as_posix(),
        "main_asr": main_asr.as_posix() if main_asr else "",
        "duration_seconds": round(duration, 3),
        "policy": {
            "candidate_only": True,
            "auto_merge": False,
            "review_required": True,
            "uncertain_candidates_require_user_disambiguation": True,
        },
        "analysis": stats
        | {
            "frame_seconds": args.frame_seconds,
            "diff_db": args.diff_db,
            "vad": "not_used",
            "vad_note": "Energy-based scan only. ASMR effects can trigger candidates; uncertain findings require user review.",
        },
        "candidates": candidates,
    }
    json_out = Path(args.json_out)
    report_out = Path(args.report_out) if args.report_out else json_out.with_suffix(".md")
    write_json(json_out, data)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(render_report(data), encoding="utf-8")
    if args.prepare_out:
        prepare_recovery(audio_path, Path(args.prepare_out), candidates, min_confidence=args.prepare_min_confidence)
    print(f"WROTE {json_out}")
    print(f"WROTE {report_out}")
    if any(item["user_disambiguation_required"] for item in candidates):
        print("REVIEW_REQUIRED uncertain channel activity candidates need user/audio disambiguation before merging.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
