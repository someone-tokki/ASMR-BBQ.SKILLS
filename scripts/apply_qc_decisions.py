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
    issue_id: str
    file: str
    index: int
    decision: str
    status: str
    evidence_level: str = ""
    decision_reason: str = ""
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


def text(value: object) -> str:
    return str(value or "").strip()


def replacement_text(item: dict[str, Any]) -> str:
    return text(item.get("replacement")) or text(item.get("corrected_zh")) or text(item.get("suggest"))


def zh_path_for(item: dict[str, Any], zh_dir: Path) -> Path:
    explicit = item.get("zh_path")
    if explicit:
        return Path(str(explicit))
    file_name = text(item.get("file"))
    if file_name.endswith(".ja.asr.srt"):
        file_name = file_name.replace(".ja.asr.srt", ".zh.srt")
    return zh_dir / file_name


def load_subtitles(path: Path) -> list[Subtitle]:
    return parse_srt_text(path.read_text(encoding="utf-8"))


def subtitle_map(subtitles: list[Subtitle]) -> dict[int, Subtitle]:
    return {subtitle.index: subtitle for subtitle in subtitles}


def load_closure_allowances(path: Path) -> dict[str, dict[str, Any]]:
    report = read_json(path)
    if not isinstance(report, dict) or report.get("status") != "pass":
        raise ValueError("Closure report must have status=pass before QC decisions can be applied.")
    raw_items = report.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("Closure report has no items array.")
    allowances: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        issue_id = text(item.get("issue_id"))
        if issue_id:
            allowances[issue_id] = item
    return allowances


def result_for(item: dict[str, Any], *, status: str, message: str = "", before: str = "", after: str = "") -> ApplyResult:
    return ApplyResult(
        issue_id=text(item.get("issue_id")),
        file=text(item.get("file")),
        index=int(item.get("index", item.get("i", 0)) or 0),
        decision=normalize_decision(item.get("decision")),
        status=status,
        evidence_level=text(item.get("evidence_level")),
        decision_reason=text(item.get("decision_reason")),
        before=before,
        after=after,
        message=message,
    )


def closure_allows(item: dict[str, Any], allowance: dict[str, Any] | None) -> str:
    if allowance is None:
        return "Accepted item is missing from the closure report."
    if not allowance.get("apply_allowed") or allowance.get("effective_decision") != "accept":
        return "Closure report did not authorize this accepted item."
    if text(allowance.get("file")) != text(item.get("file")):
        return "Closure report file does not match review item."
    if int(allowance.get("index", 0) or 0) != int(item.get("index", item.get("i", 0)) or 0):
        return "Closure report subtitle index does not match review item."
    if text(allowance.get("replacement")) != replacement_text(item):
        return "Closure report replacement does not match review item. Rerun closure validation."
    if text(allowance.get("evidence_level")) != text(item.get("evidence_level")):
        return "Closure report evidence level does not match review item. Rerun closure validation."
    return ""


def apply_items(
    items: list[dict[str, Any]],
    *,
    zh_dir: Path,
    closure_allowances: dict[str, dict[str, Any]],
    apply: bool,
    allow_stale: bool,
    backup_dir: Path | None,
) -> tuple[list[ApplyResult], int]:
    accepted = [item for item in items if normalize_decision(item.get("decision")) == "accept"]
    by_path: dict[Path, list[dict[str, Any]]] = {}
    results: list[ApplyResult] = []
    failure_count = 0
    for item in accepted:
        error = closure_allows(item, closure_allowances.get(text(item.get("issue_id"))))
        if error:
            results.append(result_for(item, status="error", message=error))
            failure_count += 1
            continue
        by_path.setdefault(zh_path_for(item, zh_dir), []).append(item)

    for path in sorted(by_path):
        file_items = by_path[path]
        if not path.exists():
            results.extend(result_for(item, status="error", message=f"ZH SRT not found: {path}") for item in file_items)
            failure_count += len(file_items)
            continue
        subtitles = load_subtitles(path)
        by_index = subtitle_map(subtitles)
        planned: list[tuple[dict[str, Any], Subtitle, str]] = []
        file_errors = 0
        for item in file_items:
            try:
                index = int(item.get("index", item.get("i")))
            except Exception:
                results.append(result_for(item, status="error", message="Missing or invalid subtitle index."))
                file_errors += 1
                continue
            subtitle = by_index.get(index)
            if subtitle is None:
                results.append(result_for(item, status="error", message=f"Subtitle index {index} not found in {path}."))
                file_errors += 1
                continue
            new_text = replacement_text(item)
            if not new_text:
                results.append(result_for(item, status="error", message="Accepted item has no replacement.", before=subtitle.content))
                file_errors += 1
                continue
            expected_current = text(item.get("current_zh"))
            if expected_current and expected_current != subtitle.content.strip() and not allow_stale:
                results.append(result_for(item, status="stale", message="Current subtitle differs from review item; rerun review or pass --allow-stale.", before=subtitle.content, after=new_text))
                file_errors += 1
                continue
            if subtitle.content == new_text:
                results.append(result_for(item, status="already_correct", message="Subtitle already matches the evidence-backed replacement.", before=subtitle.content, after=new_text))
                continue
            planned.append((item, subtitle, new_text))

        if file_errors:
            results.extend(result_for(item, status="not_applied", message="Another accepted item for this file failed validation; no changes were written.", before=subtitle.content, after=new_text) for item, subtitle, new_text in planned)
            failure_count += file_errors
            continue
        before_by_index = {subtitle.index: subtitle.content for subtitle in subtitles}
        for _, subtitle, new_text in planned:
            subtitle.content = new_text
        changed_indexes = {index for index, content in before_by_index.items() if by_index[index].content != content}
        allowed_indexes = {subtitle.index for _, subtitle, _ in planned}
        if not changed_indexes.issubset(allowed_indexes):
            results.extend(result_for(item, status="error", message="Change scope exceeded accepted QC targets.", before=before_by_index.get(subtitle.index, ""), after=subtitle.content) for item, subtitle, _ in planned)
            failure_count += len(planned)
            continue
        if apply and planned:
            if backup_dir:
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup_dir / path.name)
            path.write_text(compose_srt_text(subtitles), encoding="utf-8")
        for item, subtitle, new_text in planned:
            results.append(result_for(item, status="applied" if apply else "would_apply", before=before_by_index[subtitle.index], after=new_text))

    for item in items:
        decision = normalize_decision(item.get("decision"))
        if decision in {"reject", "defer"}:
            results.append(result_for(item, status="skipped"))
    return results, failure_count


def print_summary(results: list[ApplyResult], *, apply: bool) -> None:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    print(f"QC DECISION {'APPLY' if apply else 'DRY RUN'}", file=sys.stderr)
    for status in sorted(counts):
        print(f"{status}: {counts[status]}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply closure-approved QC decisions to matching Chinese SRT files.")
    parser.add_argument("review_items", help="JSON items from review_qc_report.py, with evidence-backed decision fields.")
    parser.add_argument("--zh-dir", required=True, help="Directory containing matching *.zh.srt files.")
    parser.add_argument("--closure-report", required=True, help="Passing qc_closure_report.json from validate_qc_closure.py.")
    parser.add_argument("--apply", action="store_true", help="Write approved changes. Without this, only reports would_apply.")
    parser.add_argument("--allow-stale", action="store_true", help="Apply even if current_zh differs from the live subtitle text.")
    parser.add_argument("--backup-dir", help="Optional directory to copy original SRT files before writing.")
    parser.add_argument("--json-out", help="Write apply report JSON.")
    args = parser.parse_args()

    raw = read_json(Path(args.review_items))
    if not isinstance(raw, list):
        raise SystemExit("review_items must be a JSON array.")
    items = [item for item in raw if isinstance(item, dict)]
    try:
        closure_allowances = load_closure_allowances(Path(args.closure_report))
    except ValueError as exc:
        raise SystemExit(str(exc))
    results, failure_count = apply_items(
        items,
        zh_dir=Path(args.zh_dir),
        closure_allowances=closure_allowances,
        apply=args.apply,
        allow_stale=args.allow_stale,
        backup_dir=Path(args.backup_dir) if args.backup_dir else None,
    )
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_summary(results, apply=args.apply)
    return 1 if failure_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
