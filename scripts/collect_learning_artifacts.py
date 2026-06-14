#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NAMES = {"reference", "references", "learning", "lesson", "lessons"}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_candidate(path: Path) -> bool:
    lower = path.name.lower()
    if lower in NAMES:
        return True
    return any(token in lower for token in ("reference", "learning", "lesson")) and path.suffix.lower() in {".md", ".txt", ".json"}


def collect(source_root: Path, imported_dir: Path, *, copy: bool) -> dict[str, Any]:
    candidates: list[Path] = []
    for path in source_root.rglob("*"):
        if ".git" in path.parts or "subtitle_project" in path.parts:
            continue
        if is_candidate(path):
            candidates.append(path)
    records: list[dict[str, Any]] = []
    if copy:
        imported_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(candidates):
        rel = path.relative_to(source_root)
        target = imported_dir / rel
        record = {"source": path.as_posix(), "target": target.as_posix(), "type": "dir" if path.is_dir() else "file", "copied": False}
        if copy:
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(path, target)
            else:
                shutil.copy2(path, target)
            record["copied"] = True
        records.append(record)
    return {"created_at": now_utc(), "source_root": source_root.as_posix(), "imported_dir": imported_dir.as_posix(), "candidates": records}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect stray learning/reference artifacts into the work record imported directory.")
    parser.add_argument("source_root")
    parser.add_argument("--work-record-dir", required=True)
    parser.add_argument("--copy", action="store_true", help="Copy candidates into <work-record-dir>/imported. Default only reports.")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    report = collect(Path(args.source_root), Path(args.work_record_dir) / "imported", copy=args.copy)
    if args.json_out:
        write_json(Path(args.json_out), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
