#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


USER_FILES = {
    "style": "references/style.md",
    "terms": "references/terms.md",
    "risk_notes": "references/risk-notes.md",
    "pending": "references/pending.md",
    "work_index": "references/work-index.md",
    "risk_patterns": "data/subtitle_risk_patterns.local.json",
}
WORK_FILES = {
    "work_record": "work_record.md",
    "promote_candidates": "promote_candidates.md",
    "pending": "pending.md",
    "risk_candidates": "risk_candidates.json",
    "learning_summary": "learning_summary.json",
    "imported": "imported",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_user_learning_dir() -> Path:
    value = os.environ.get("ASMR_SUBTITLE_LEARNING_DIR")
    if value:
        return Path(value).expanduser()
    return Path.home() / "ASMR-Subtitle-Translator" / "learning"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def builtin_reference_dir() -> Path:
    return repo_root() / "references"


def work_record_dir(project_root: Path) -> Path:
    return project_root / "learning"


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_file(path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"# {title}\n\n", encoding="utf-8")


def build_report(project_root: Path, *, user_learning_dir: Path | None = None, codex_home: Path | None = None, create: bool) -> dict[str, Any]:
    user_dir = user_learning_dir or (codex_home / "asmr-subtitle-translator" / "learning" if codex_home else default_user_learning_dir())
    work_dir = work_record_dir(project_root)
    user_paths = {key: (user_dir / rel).as_posix() for key, rel in USER_FILES.items()}
    work_paths = {key: (work_dir / rel).as_posix() for key, rel in WORK_FILES.items()}
    if create:
        for key, rel in USER_FILES.items():
            title = {
                "style": "User ASMR Style Rules",
                "terms": "User ASMR Terms",
                "risk_notes": "User ASMR Risk Notes",
                "pending": "User ASMR Pending Notes",
                "work_index": "ASMR Work Learning Index",
                "risk_patterns": "[]",
            }.get(key, key)
            path = user_dir / rel
            if key == "risk_patterns":
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_text("[]\n", encoding="utf-8")
            else:
                ensure_file(path, title)
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "imported").mkdir(parents=True, exist_ok=True)
    return {
        "schema_version": 1,
        "created_at": now_utc(),
        "project_root": project_root.as_posix(),
        "builtin_reference_dir": builtin_reference_dir().as_posix(),
        "user_learning_dir": user_dir.as_posix(),
        "user_learning_env": "ASMR_SUBTITLE_LEARNING_DIR",
        "legacy_codex_learning_dir": (Path.home() / ".codex" / "asmr-subtitle-translator" / "learning").as_posix(),
        "work_record_dir": work_dir.as_posix(),
        "user_paths": user_paths,
        "work_paths": work_paths,
        "read_order": ["builtin", "user_learning", "work_record"],
        "write_policy": {
            "builtin": "read_only",
            "user_learning": "confirmed_only",
            "work_record": "auto",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve ASMR subtitle learning paths without writing to the skill package.")
    parser.add_argument("project_root")
    parser.add_argument("--user-learning-dir", default="", help="Override the shared user learning directory. Defaults to ~/ASMR-Subtitle-Translator/learning or ASMR_SUBTITLE_LEARNING_DIR.")
    parser.add_argument("--codex-home", default="", help="Deprecated compatibility option; maps to <codex-home>/asmr-subtitle-translator/learning.")
    parser.add_argument("--no-create", action="store_true", help="Only report paths; do not create user/work learning directories.")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser()
    user_learning = Path(args.user_learning_dir).expanduser() if args.user_learning_dir else None
    codex_home = Path(args.codex_home).expanduser() if args.codex_home else None
    report = build_report(project_root, user_learning_dir=user_learning, codex_home=codex_home, create=not args.no_create)
    if args.json_out:
        write_json(Path(args.json_out), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
