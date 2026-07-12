#!/usr/bin/env python3
"""Report selected ASR tracks that have no safe MP3 input option.

This is a preflight decision helper. It never converts audio or changes scope.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


MP3_EXTENSIONS = {".mp3"}
WAV_EXTENSIONS = {".wav", ".wave"}
NO_SE_PATTERNS = [r"無\s*se", r"无\s*se", r"se\s*なし", r"se\s*無し", r"se\s*抜き", r"no[-_\s]*se", r"without[-_\s]*se", r"効果音\s*なし", r"効果音\s*無し", r"効果音\s*抜き"]
NO_SE_RE = [re.compile(pattern, re.IGNORECASE) for pattern in NO_SE_PATTERNS]


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected an object in {path}")
    return data


def normalized_path(value: str, source_root: Path) -> str:
    path = Path(value)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(source_root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix().lstrip("./") or "."


def track_key(path: str) -> str:
    text = unicodedata.normalize("NFKC", Path(path).stem).lower()
    for pattern in NO_SE_RE:
        text = pattern.sub("", text)
    text = re.sub(r"[\s\-_.,，。・、/\\()[\]{}【】「」『』]+", "", text)
    return text or unicodedata.normalize("NFKC", Path(path).stem).lower()


def selected_scope_files(report: dict[str, Any], *, scope: str, selected_dirs: list[str], selected_files: list[str]) -> list[dict[str, Any]]:
    root = Path(str(report.get("source_root", ".")))
    folders = report.get("folders", [])
    if not isinstance(folders, list):
        raise ValueError("audio scope report has no folders list")
    wanted_dirs = {normalized_path(value, root) for value in selected_dirs}
    wanted_files = {normalized_path(value, root) for value in selected_files}
    selected: list[dict[str, Any]] = []
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        folder_name = normalized_path(str(folder.get("folder", "")), root)
        folder_selected = scope == "all" or folder_name in wanted_dirs or "." in wanted_dirs
        for item in folder.get("files", []):
            if not isinstance(item, dict):
                continue
            path = normalized_path(str(item.get("path", "")), root)
            if scope == "selected_files":
                include = path in wanted_files
            else:
                include = folder_selected
            if include:
                selected.append({**item, "path": path})
    return selected


def preferred_no_se_by_counterpart(source_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    preferred: dict[str, dict[str, Any]] = {}
    for item in source_report.get("recommended_asr_files", []):
        if not isinstance(item, dict) or item.get("requires_review"):
            continue
        for counterpart in item.get("matched_counterparts", []):
            preferred[str(counterpart)] = item
    return preferred


def build_report(scope_report: dict[str, Any], source_report: dict[str, Any] | None, *, scope: str, selected_dirs: list[str], selected_files: list[str]) -> dict[str, Any]:
    selected = selected_scope_files(scope_report, scope=scope, selected_dirs=selected_dirs, selected_files=selected_files)
    by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        by_track[track_key(str(item["path"]))].append(item)
    preferred = preferred_no_se_by_counterpart(source_report or {})
    native_mp3_tracks: list[dict[str, Any]] = []
    wav_only_tracks: list[dict[str, Any]] = []
    other_tracks: list[dict[str, Any]] = []
    for key, items in sorted(by_track.items()):
        preferred_items = [preferred[str(item["path"])] for item in items if str(item["path"]) in preferred]
        if preferred_items:
            candidate = sorted(preferred_items, key=lambda item: (str(item.get("extension", "")) not in MP3_EXTENSIONS, str(item.get("path", ""))))[0]
            reason = "aligned_no_se_source"
        else:
            candidate = sorted(items, key=lambda item: (str(item.get("extension", "")).lower() not in MP3_EXTENSIONS, str(item["path"])))[0]
            reason = "native_selected_scope_source"
        extension = str(candidate.get("extension", Path(str(candidate.get("path", ""))).suffix)).lower()
        record = {
            "track_key": key,
            "asr_input": str(candidate.get("path", "")),
            "extension": extension,
            "source_reason": reason,
            "scope_files": sorted(str(item["path"]) for item in items),
        }
        if extension in MP3_EXTENSIONS:
            native_mp3_tracks.append(record)
        elif extension in WAV_EXTENSIONS:
            wav_only_tracks.append(record)
        else:
            other_tracks.append(record)
    return {
        "version": 1,
        "scope": scope,
        "selected_audio_dirs": selected_dirs,
        "selected_audio_files": selected_files,
        "selected_file_count": len(selected),
        "native_mp3_tracks": native_mp3_tracks,
        "wav_only_tracks": wav_only_tracks,
        "other_input_tracks": other_tracks,
        "wav_only_choice_required": bool(wav_only_tracks),
        "policy": "Ask about temporary MP3 caching only when selected ASR inputs include WAV-only tracks. Native or safely aligned MP3 tracks stay MP3 and are never reconverted.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Identify selected ASR tracks that need a WAV-only preparation choice.")
    parser.add_argument("--audio-scope-report", required=True)
    parser.add_argument("--audio-source-report", default="")
    parser.add_argument("--scope", required=True, choices=["all", "selected_dirs", "selected_files"])
    parser.add_argument("--selected-audio-dir", action="append", default=[])
    parser.add_argument("--selected-audio-file", action="append", default=[])
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()
    scope_report = load_json(Path(args.audio_scope_report))
    source_report = load_json(Path(args.audio_source_report)) if args.audio_source_report else None
    report = build_report(scope_report, source_report, scope=args.scope, selected_dirs=args.selected_audio_dir, selected_files=args.selected_audio_file)
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
