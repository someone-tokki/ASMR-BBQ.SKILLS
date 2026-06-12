#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from subtitle_io import Subtitle, compose_srt_text, parse_srt_text


@dataclass
class ApplyResult:
    file: str
    index: int
    decision: str
    status: str
    before: str = ""
    after: str = ""
    message: str = ""


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_decision(value: object) -> str:
    decision = str(value or "").strip().lower()
    if decision in {"accept", "accepted", "apply", "yes", "y"}:
        return "accept"
    if decision in {"reject", "rejected", "no", "n"}:
        return "reject"
    if decision in {"defer", "deferred", "pending", ""}:
        return "defer"
    return decision


def replacement_text(item: dict[str, Any]) -> str:
    return str(item.get("replacement") or item.get("corrected_zh") or item.get("suggest") or "").strip()


def zh_path_for(item: dict[str, Any], zh_dir: Path) -> Path:
    explicit = item.get("zh_path")
    if explicit:
        return Path(str(explicit))
    file_name = str(item.get("file", "")).strip()
    if file_name.endswith(".ja.asr.srt"):
        file_name = file_name.replace(".ja.asr.srt", ".zh.srt")
    return zh_dir / file_name


def load_subtitles(path: Path) -> list[Subtitle]:
    return parse_srt_text(path.read_text(encoding="utf-8"))


def subtitle_map(subtitles: list[Subtitle]) -> dict[int, Subtitle]:
    return {subtitle.index: subtitle for subtitle in subtitles}


def apply_items(
    items: list[dict[str, Any]],
    *,
    zh_dir: Path,
    apply: bool,
    allow_stale: bool,
    backup_dir: Path | None,
) -> tuple[list[ApplyResult], int]:
    accepted = [item for item in items if normalize_decision(item.get("decision")) == "accept"]
    by_path: dict[Path, list[dict[str, Any]]] = {}
    for item in accepted:
        by_path.setdefault(zh_path_for(item, zh_dir), []).append(item)

    results: list[ApplyResult] = []
    failure_count = 0

    for path in sorted(by_path):
        file_items = by_path[path]
        if not path.exists():
            for item in file_items:
                results.append(
                    ApplyResult(
                        file=str(item.get("file", path.name)),
                        index=int(item.get("index", item.get("i", 0)) or 0),
                        decision="accept",
                        status="error",
                        message=f"ZH SRT not found: {path}",
                    )
                )
                failure_count += 1
            continue

        subtitles = load_subtitles(path)
        by_index = subtitle_map(subtitles)
        changed = False

        for item in file_items:
            try:
                index = int(item.get("index", item.get("i")))
            except Exception:
                results.append(
                    ApplyResult(
                        file=str(item.get("file", path.name)),
                        index=0,
                        decision="accept",
                        status="error",
                        message="Missing or invalid subtitle index.",
                    )
                )
                failure_count += 1
                continue

            subtitle = by_index.get(index)
            if not subtitle:
                results.append(
                    ApplyResult(
                        file=str(item.get("file", path.name)),
                        index=index,
                        decision="accept",
                        status="error",
                        message=f"Subtitle index {index} not found in {path}.",
                    )
                )
                failure_count += 1
                continue

            new_text = replacement_text(item)
            if not new_text:
                results.append(
                    ApplyResult(
                        file=str(item.get("file", path.name)),
                        index=index,
                        decision="accept",
                        status="error",
                        before=subtitle.content,
                        message="Accepted item has no replacement/corrected_zh/suggest text.",
                    )
                )
                failure_count += 1
                continue

            expected_current = str(item.get("current_zh", "")).strip()
            if expected_current and expected_current != subtitle.content.strip() and not allow_stale:
                results.append(
                    ApplyResult(
                        file=str(item.get("file", path.name)),
                        index=index,
                        decision="accept",
                        status="stale",
                        before=subtitle.content,
                        after=new_text,
                        message="Current subtitle differs from review item; rerun review or pass --allow-stale.",
                    )
                )
                failure_count += 1
                continue

            if subtitle.content == new_text:
                results.append(
                    ApplyResult(
                        file=str(item.get("file", path.name)),
                        index=index,
                        decision="accept",
                        status="unchanged",
                        before=subtitle.content,
                        after=new_text,
                        message="Subtitle already matches replacement.",
                    )
                )
                continue

            results.append(
                ApplyResult(
                    file=str(item.get("file", path.name)),
                    index=index,
                    decision="accept",
                    status="applied" if apply else "would_apply",
                    before=subtitle.content,
                    after=new_text,
                )
            )
            subtitle.content = new_text
            changed = True

        if apply and changed and failure_count == 0:
            if backup_dir:
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup_dir / path.name)
            path.write_text(compose_srt_text(subtitles), encoding="utf-8")

    for item in items:
        decision = normalize_decision(item.get("decision"))
        if decision in {"reject", "defer"}:
            results.append(
                ApplyResult(
                    file=str(item.get("file", "")),
                    index=int(item.get("index", item.get("i", 0)) or 0),
                    decision=decision,
                    status="skipped",
                )
            )

    return results, failure_count


def print_summary(results: list[ApplyResult], *, apply: bool) -> None:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    mode = "APPLY" if apply else "DRY RUN"
    print(f"QC DECISION {mode}", file=sys.stderr)
    for status in sorted(counts):
        print(f"{status}: {counts[status]}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply accepted QC review decisions to matching Chinese SRT files. Defaults to dry-run."
    )
    parser.add_argument("review_items", help="JSON items from review_qc_report.py, with decision fields edited.")
    parser.add_argument("--zh-dir", required=True, help="Directory containing matching *.zh.srt files.")
    parser.add_argument("--apply", action="store_true", help="Write accepted changes. Without this, only reports would_apply.")
    parser.add_argument("--allow-stale", action="store_true", help="Apply even if current_zh differs from the live subtitle text.")
    parser.add_argument("--backup-dir", help="Optional directory to copy original SRT files before writing.")
    parser.add_argument("--json-out", help="Write apply report JSON.")
    args = parser.parse_args()

    raw = read_json(Path(args.review_items))
    if not isinstance(raw, list):
        raise SystemExit("review_items must be a JSON array.")
    items = [item for item in raw if isinstance(item, dict)]

    results, failure_count = apply_items(
        items,
        zh_dir=Path(args.zh_dir),
        apply=args.apply,
        allow_stale=args.allow_stale,
        backup_dir=Path(args.backup_dir) if args.backup_dir else None,
    )

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2), encoding="utf-8")

    print_summary(results, apply=args.apply)
    return 1 if failure_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
