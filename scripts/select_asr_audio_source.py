#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
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


@dataclass
class AudioFile:
    path: str
    directory: str
    category: str
    reason: str


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).lower()


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


NO_SE_RE = compile_patterns(NO_SE_PATTERNS)
WITH_SE_RE = compile_patterns(WITH_SE_PATTERNS)


def classify(path: Path) -> tuple[str, str]:
    text = normalize_text(path.as_posix())
    for pattern in NO_SE_RE:
        if pattern.search(text):
            return "no_se", pattern.pattern
    for pattern in WITH_SE_RE:
        if pattern.search(text):
            return "with_se", pattern.pattern
    return "unknown", ""


def iter_audio_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in AUDIO_EXTENSIONS else []
    if not root.exists():
        raise FileNotFoundError(root)
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS)


def rel(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def build_report(paths: list[Path], *, user_selected: Path | None = None) -> dict:
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
        notes = [
            "The user explicitly selected an ASR audio source. Use the user-selected version even if a no-SE variant is detected.",
            "No-SE audio remains only a default preference when the user has not specified another version.",
        ]
    elif recommended:
        decision = "prefer_no_se"
        notes = [
            "No-SE audio was detected. Prefer the recommended no-SE directory/files for ASR when timing appears compatible with the delivery audio and the user has not requested another version.",
            "Keep final subtitle directories aligned with the original target audio folders; no-SE is an ASR source preference, not necessarily the delivery folder name.",
        ]
    elif files:
        decision = "no_no_se_detected"
        notes = ["No no-SE audio variant was detected. Use the best available main audio source for ASR."]
    else:
        decision = "no_audio_detected"
        notes = ["No supported audio files were detected under the provided path(s)."]

    return {
        "decision": decision,
        "audio_count": len(files),
        "counts": dict(counts),
        "recommended_asr_inputs": recommended,
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
    print("\nNotes:")
    for note in report.get("notes", []):
        print(f"- {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan ASMR audio folders and prefer no-SE variants for ASR when available unless the user chooses another version.")
    parser.add_argument("paths", nargs="+", help="Audio file or directory path(s) to scan.")
    parser.add_argument("--user-selected", help="Explicit user-selected ASR source; overrides the default no-SE preference.")
    parser.add_argument("--json-out", help="Write a JSON report.")
    args = parser.parse_args()

    report = build_report(
        [Path(path).expanduser() for path in args.paths],
        user_selected=Path(args.user_selected).expanduser() if args.user_selected else None,
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
