#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import unicodedata
import wave
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


AUDIO_EXTENSIONS = {
    ".wav",
    ".wave",
    ".flac",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wma",
}

NO_SE_PATTERNS = [
    r"無\s*se",
    r"无\s*se",
    r"se\s*なし",
    r"se\s*無し",
    r"se\s*抜き",
    r"no[-_\s]*se",
    r"without[-_\s]*se",
    r"効果音\s*なし",
    r"効果音\s*無し",
    r"効果音\s*抜き",
]

WITH_SE_PATTERNS = [
    r"有\s*se",
    r"se\s*あり",
    r"se\s*有り",
    r"se\s*入り",
    r"with[-_\s]*se",
    r"効果音\s*あり",
    r"効果音\s*有り",
    r"効果音\s*入り",
]

TRIAL_OR_LOW_CONFIDENCE_PATTERNS = [
    r"体験版",
    r"試聴",
    r"试听",
    r"sample",
    r"demo",
    r"preview",
]

EXTENSION_PRIORITY = {
    ".mp3": 0,
    ".wav": 1,
    ".wave": 1,
    ".flac": 2,
    ".m4a": 3,
    ".aac": 4,
    ".opus": 5,
    ".ogg": 6,
    ".wma": 7,
}


@dataclass
class AudioFile:
    path: str
    directory: str
    category: str
    reason: str
    extension: str
    track_key: str
    size_bytes: int
    duration_seconds: float | None


@dataclass
class SelectedAsrFile:
    track_key: str
    path: str
    directory: str
    extension: str
    matched_counterparts: list[str]
    selection_reason: str
    warnings: list[str]
    requires_review: bool


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).lower()


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


NO_SE_RE = compile_patterns(NO_SE_PATTERNS)
WITH_SE_RE = compile_patterns(WITH_SE_PATTERNS)
TRIAL_OR_LOW_CONFIDENCE_RE = compile_patterns(TRIAL_OR_LOW_CONFIDENCE_PATTERNS)


def classify(path: Path) -> tuple[str, str]:
    text = normalize_text(path.as_posix())
    for pattern in NO_SE_RE:
        if pattern.search(text):
            return "no_se", pattern.pattern
    for pattern in WITH_SE_RE:
        if pattern.search(text):
            return "with_se", pattern.pattern
    return "unknown", ""


def track_key(path: Path) -> str:
    text = normalize_text(path.stem)
    for pattern in [*NO_SE_RE, *WITH_SE_RE]:
        text = pattern.sub("", text)
    text = re.sub(r"\b(wav|wave|mp3|flac|m4a|aac|ogg|opus|wma)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\s\-_.,，。・、/\\()[\]{}【】「」『』]+", "", text)
    return text or normalize_text(path.stem)


def extension_priority(path_text: str) -> int:
    return EXTENSION_PRIORITY.get(Path(path_text).suffix.lower(), 99)


def path_warnings(path_text: str, size_bytes: int) -> list[str]:
    warnings: list[str] = []
    normalized = normalize_text(path_text)
    for pattern in TRIAL_OR_LOW_CONFIDENCE_RE:
        if pattern.search(normalized):
            warnings.append("name_suggests_trial_or_preview_verify_scope")
            break
    if size_bytes < 256 * 1024:
        warnings.append("very_small_audio_file_verify_not_placeholder")
    return warnings


def audio_duration(path: Path) -> float | None:
    """Return container duration without loading the entire audio stream."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", path.as_posix()],
            capture_output=True,
            check=True,
            text=True,
        )
        return float(result.stdout.strip())
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError):
        if path.suffix.lower() != ".wav":
            return None
        try:
            with wave.open(path.as_posix(), "rb") as handle:
                return handle.getnframes() / float(handle.getframerate())
        except (OSError, EOFError, wave.Error):
            return None


def duration_error(left: float | None, right: float | None) -> float | None:
    if left is None or right is None or max(left, right) <= 0:
        return None
    return abs(left - right) / max(left, right)


def choose_preferred_no_se(candidates: list[AudioFile]) -> AudioFile:
    return sorted(
        candidates,
        key=lambda item: (
            len(path_warnings(item.path, item.size_bytes)),
            extension_priority(item.path),
            item.path,
        ),
    )[0]


def iter_audio_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if not root.name.startswith("._") and root.suffix.lower() in AUDIO_EXTENSIONS else []
    if not root.exists():
        raise FileNotFoundError(root)
    return sorted(path for path in root.rglob("*") if path.is_file() and not path.name.startswith("._") and path.suffix.lower() in AUDIO_EXTENSIONS)


def rel(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def build_report(paths: list[Path], *, user_selected: Path | None = None, duration_tolerance: float = 0.02) -> dict:
    files: list[AudioFile] = []
    roots = [path.resolve() for path in paths]
    common_base = roots[0] if len(roots) == 1 and roots[0].is_dir() else Path.cwd()

    for root in roots:
        for audio_path in iter_audio_files(root):
            category, reason = classify(audio_path)
            files.append(
                AudioFile(
                    path=rel(audio_path, common_base),
                    directory=rel(audio_path.parent, common_base),
                    category=category,
                    reason=reason,
                    extension=audio_path.suffix.lower(),
                    track_key=track_key(audio_path),
                    size_bytes=audio_path.stat().st_size,
                    duration_seconds=audio_duration(audio_path),
                )
            )

    counts = Counter(item.category for item in files)
    no_se_dirs: defaultdict[str, int] = defaultdict(int)
    for item in files:
        if item.category == "no_se":
            no_se_dirs[item.directory] += 1

    recommended = [
        {"directory": directory, "audio_count": count}
        for directory, count in sorted(no_se_dirs.items(), key=lambda item: (-item[1], item[0]))
    ]
    by_key: defaultdict[str, list[AudioFile]] = defaultdict(list)
    for item in files:
        by_key[item.track_key].append(item)

    selected_files: list[SelectedAsrFile] = []
    unmatched_no_se: list[dict] = []
    unmatched_regular: list[dict] = []
    duplicate_no_se_groups: list[dict] = []

    for key, items in sorted(by_key.items()):
        no_se_items = [item for item in items if item.category == "no_se"]
        regular_items = [item for item in items if item.category != "no_se"]
        if no_se_items:
            preferred = choose_preferred_no_se(no_se_items)
            warnings = path_warnings(preferred.path, preferred.size_bytes)
            duration_matched_regular = [
                item for item in regular_items
                if (error := duration_error(preferred.duration_seconds, item.duration_seconds)) is not None and error <= duration_tolerance
            ]
            reason_parts = ["prefer_no_se"]
            if preferred.extension == ".mp3":
                reason_parts.append("mp3_preferred_for_faster_asr_when_track_matches")
            elif any(item.extension == ".mp3" for item in no_se_items):
                reason_parts.append("mp3_candidate_not_selected_due_warning_or_tie_break")
            if duration_matched_regular:
                reason_parts.append("matched_regular_audio_name_and_duration")
            else:
                reason_parts.append("no_regular_name_and_duration_match_verify_mapping")
                unmatched_no_se.extend(asdict(item) for item in no_se_items)
                warnings.append("no_regular_duration_match")
            if len(no_se_items) > 1:
                duplicate_no_se_groups.append(
                    {
                        "track_key": key,
                        "candidates": [asdict(item) for item in sorted(no_se_items, key=lambda item: item.path)],
                        "selected": preferred.path,
                    }
                )
            selected_files.append(
                SelectedAsrFile(
                    track_key=key,
                    path=preferred.path,
                    directory=preferred.directory,
                    extension=preferred.extension,
                    matched_counterparts=[item.path for item in sorted(duration_matched_regular, key=lambda item: item.path)],
                    selection_reason=", ".join(reason_parts),
                    warnings=warnings,
                    requires_review=not duration_matched_regular or bool(warnings),
                )
            )
        else:
            unmatched_regular.extend(asdict(item) for item in items)

    if user_selected:
        category, reason = classify(user_selected)
        decision = "user_override"
        recommended = [
            {
                "directory": rel(user_selected if user_selected.is_dir() else user_selected.parent, common_base),
                "audio_count": 0,
                "source": "user_selected",
                "category": category,
                "reason": reason,
            }
        ]
        selected_files = []
        unmatched_no_se = []
        unmatched_regular = []
        duplicate_no_se_groups = []
        notes = [
            "The user explicitly selected an ASR audio source. Use the user-selected version even if a no-SE variant is detected.",
            "No-SE audio remains only a default preference when the user has not specified another version.",
        ]
    elif selected_files and any(item.matched_counterparts for item in selected_files):
        decision = "prefer_aligned_no_se"
        notes = [
            "No-SE audio was detected and at least one track matches a regular audio counterpart. Use recommended_asr_files entries with matched_counterparts and requires_review=false for ASR by default when the user has not requested another version.",
            "When the same no-SE track has MP3 and WAV candidates, MP3 is selected first for speed unless the filename/size raises a warning; verify duration/track mapping when warnings are present.",
            "Use only matched no-SE audio for tracks that align with regular audio. If a no-SE track has no regular counterpart, verify it before treating it as the canonical ASR source.",
            "No-SE is an ASR source preference only. Deliver final subtitles to the configured final_subtitle_dir, normally the source ASMR work directory's subtitles folder.",
        ]
    elif selected_files:
        decision = "prefer_no_se_unpaired"
        notes = [
            "No-SE audio was detected, but no regular counterpart with the same normalized track name was found. Prefer it only after verifying it is the intended full track and not a cropped/preview/alternate file.",
            "No-SE is an ASR source preference only. Deliver final subtitles to the configured final_subtitle_dir, normally the source ASMR work directory's subtitles folder.",
        ]
    elif files:
        decision = "no_no_se_detected"
        notes = ["No no-SE audio variant was detected. Use the best available main audio source for ASR."]
    else:
        decision = "no_audio_detected"
        notes = ["No supported audio files were detected under the provided path(s)."]

    return {
        "decision": decision,
        "duration_tolerance": duration_tolerance,
        "audio_count": len(files),
        "counts": dict(counts),
        "recommended_asr_inputs": recommended,
        "recommended_asr_files": [asdict(item) for item in selected_files],
        "unmatched_no_se_files": unmatched_no_se,
        "unmatched_regular_files": unmatched_regular,
        "duplicate_no_se_groups": duplicate_no_se_groups,
        "files": [asdict(item) for item in files],
        "notes": notes,
    }


def print_report(report: dict) -> None:
    print(f"Audio files: {report['audio_count']}")
    print(f"Decision: {report['decision']}")
    counts = report.get("counts", {})
    if counts:
        print("Counts: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    recommendations = report.get("recommended_asr_inputs", [])
    if recommendations:
        print("\nRecommended ASR input(s):")
        for item in recommendations:
            print(f"- {item['directory']} ({item['audio_count']} audio file(s))")
    selected = report.get("recommended_asr_files", [])
    if selected:
        print("\nRecommended ASR file(s):")
        for item in selected:
            match_count = len(item.get("matched_counterparts", []))
            warning_suffix = f" warnings={','.join(item['warnings'])}" if item.get("warnings") else ""
            review_suffix = " requires_review=true" if item.get("requires_review") else ""
            print(f"- {item['path']} [{item['extension']}; matched_counterparts={match_count}]{warning_suffix}{review_suffix}")
    if report.get("unmatched_no_se_files"):
        print(f"\nUnmatched no-SE files: {len(report['unmatched_no_se_files'])} (verify before using as canonical ASR source)")
    print("\nNotes:")
    for note in report.get("notes", []):
        print(f"- {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan ASMR audio folders and prefer no-SE variants for ASR when available unless the user chooses another version.")
    parser.add_argument("paths", nargs="+", help="Audio file or directory path(s) to scan.")
    parser.add_argument("--user-selected", help="Explicit user-selected ASR source; overrides the default no-SE preference.")
    parser.add_argument("--duration-tolerance", type=float, default=0.02, help="Maximum relative duration difference for automatic no-SE matching (default: 2%%).")
    parser.add_argument("--json-out", help="Write a JSON report.")
    args = parser.parse_args()

    report = build_report(
        [Path(path).expanduser() for path in args.paths],
        user_selected=Path(args.user_selected).expanduser() if args.user_selected else None,
        duration_tolerance=args.duration_tolerance,
    )
    print_report(report)
    if args.json_out:
        out_path = Path(args.json_out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nWROTE {out_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
