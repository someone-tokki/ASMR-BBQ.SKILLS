#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path
from typing import Any


AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".webm"}
NO_SE_MARKERS = ("no se", "nose", "no_se", "no-se", "無se", "无se", "seなし", "se抜き")
MAIN_MARKERS = ("本編", "本篇", "main", "track", "トラック")
BONUS_MARKERS = ("ex", "extra", "bonus", "特典", "おまけ", "番外")
TRIAL_MARKERS = ("trial", "sample", "体験", "試聴", "试听", "promo", "プロモ")
SE_BGM_MARKERS = ("bgm", "se", "効果音", "環境音")


def is_audio(path: Path) -> bool:
    return path.is_file() and not path.name.startswith("._") and path.suffix.lower() in AUDIO_EXTENSIONS


def classify_folder(path: Path) -> list[str]:
    text = path.as_posix().lower()
    tags: list[str] = []
    if any(marker in text for marker in NO_SE_MARKERS):
        tags.append("no_se")
    if any(marker.lower() in text for marker in MAIN_MARKERS):
        tags.append("main_candidate")
    if any(marker.lower() in text for marker in BONUS_MARKERS):
        tags.append("bonus_or_extra")
    if any(marker.lower() in text for marker in TRIAL_MARKERS):
        tags.append("trial_or_promo")
    if any(marker.lower() in text for marker in SE_BGM_MARKERS) and "no_se" not in tags:
        tags.append("se_or_bgm_candidate")
    return tags or ["audio"]


def wav_duration(path: Path) -> float | None:
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(path.as_posix(), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            if rate:
                return frames / float(rate)
    except Exception:
        return None
    return None


def folder_key(root: Path, audio: Path) -> str:
    try:
        rel_parent = audio.parent.relative_to(root)
    except ValueError:
        rel_parent = audio.parent
    return "." if str(rel_parent) == "." else rel_parent.as_posix()


def scan(root: Path) -> dict[str, Any]:
    audio_files = sorted(path for path in root.rglob("*") if is_audio(path))
    folders: dict[str, dict[str, Any]] = {}
    for audio in audio_files:
        key = folder_key(root, audio)
        record = folders.setdefault(
            key,
            {
                "folder": key,
                "path": (root / key).as_posix() if key != "." else root.as_posix(),
                "tags": classify_folder(root / key if key != "." else root),
                "audio_count": 0,
                "known_duration_sec": 0.0,
                "unknown_duration_count": 0,
                "files": [],
            },
        )
        duration = wav_duration(audio)
        record["audio_count"] += 1
        if duration is None:
            record["unknown_duration_count"] += 1
        else:
            record["known_duration_sec"] += duration
        try:
            rel = audio.relative_to(root).as_posix()
        except ValueError:
            rel = audio.as_posix()
        record["files"].append(
            {
                "path": rel,
                "name": audio.name,
                "extension": audio.suffix.lower(),
                "duration_sec": duration,
                "size_bytes": audio.stat().st_size,
            }
        )
    folder_list = sorted(folders.values(), key=lambda item: item["folder"])
    return {
        "version": 1,
        "source_root": root.as_posix(),
        "audio_folder_count": len(folder_list),
        "audio_file_count": len(audio_files),
        "folders": folder_list,
        "scope_policy": (
            "Ask the user which listed audio folders should be translated. "
            "No-SE folders are ASR-source candidates, not automatic translation scope."
        ),
    }


def print_text(report: dict[str, Any]) -> None:
    print(f"source_root: {report['source_root']}")
    print(f"audio_folders: {report['audio_folder_count']}")
    print(f"audio_files: {report['audio_file_count']}")
    for index, folder in enumerate(report["folders"], start=1):
        duration = folder["known_duration_sec"]
        duration_text = f"{duration / 60:.1f} min known" if duration else "duration unknown"
        tags = ", ".join(folder["tags"])
        print(f"[{index}] {folder['folder']} | {folder['audio_count']} files | {duration_text} | {tags}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan ASMR source folders for preflight translation scope selection.")
    parser.add_argument("source_root")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.source_root)
    if not root.exists():
        raise SystemExit(f"Source root not found: {root}")
    report = scan(root)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
