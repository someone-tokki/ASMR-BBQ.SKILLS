#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from review_qc_report import (
    EVIDENCE_LEVELS,
    FORMAL_DECISIONS,
    HIGH_RISK_CATEGORIES,
    normalize_report,
    read_json,
)


def normalize_decision(value: object) -> str:
    decision = str(value or "").strip().lower()
    if decision in {"accept", "accepted", "apply", "yes", "y"}:
        return "accept"
    if decision in {"reject", "rejected", "no", "n"}:
        return "reject"
    if decision in {"defer", "deferred"}:
        return "defer"
    return decision or "pending"


def text(value: object) -> str:
    return str(value or "").strip()


def is_semantic_expansion(item: dict[str, Any]) -> bool:
    """Require explicit evidence before high-risk replacement text can add meaning."""
    category = text(item.get("category"))
    if category not in HIGH_RISK_CATEGORIES:
        return False
    replacement = text(item.get("replacement")) or text(item.get("corrected_zh")) or text(item.get("suggest"))
    current = text(item.get("current_zh"))
    if not replacement or replacement == current:
        return False
    evidence = text(item.get("evidence_summary"))
    # The check is deliberately conservative: an explicit source anchor is required
    # for a high-risk semantic rewrite, while the actual linguistic judgment remains human/agent evidence review.
    source_markers = ("台本", "音频", "音轨", "日文", "JA", "原文", "上下文", "ASR")
    return not any(marker.lower() in evidence.lower() for marker in source_markers)


def review_payload(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "issue_id": text(item.get("issue_id")),
        "file": text(item.get("file")),
        "index": item.get("index", item.get("i", 0)),
        "start": text(item.get("start")),
        "end": text(item.get("end")),
        "category": text(item.get("category")),
        "severity": text(item.get("severity")),
        "problem": text(item.get("problem")),
        "suggest": text(item.get("suggest")),
        "current_ja": text(item.get("current_ja")),
        "current_zh": text(item.get("current_zh")),
        "context_before": item.get("context_before", []),
        "context_after": item.get("context_after", []),
        "decision_reason": text(item.get("decision_reason")) or reason,
        "evidence_level": text(item.get("evidence_level")) or "insufficient",
        "evidence_summary": text(item.get("evidence_summary")),
        "review_method": text(item.get("review_method")) or "audio_or_human_review",
    }


def render_manual_review(items: list[dict[str, Any]]) -> str:
    lines = ["# QC Manual Review Queue", "", f"- Pending review items: {len(items)}", ""]
    for item in items:
        lines.extend(
            [
                f"## {item['issue_id']} / {item['file']} #{item['index']}",
                "",
                f"- Time: {item.get('start', '')} --> {item.get('end', '')}",
                f"- Category/severity: {item.get('category', '')} / {item.get('severity', '')}",
                f"- Required review: {item.get('review_method', '')}",
                f"- Reason: {item.get('decision_reason', '')}",
                "",
                "**JA**",
                "",
                str(item.get("current_ja", "")) or "(missing)",
                "",
                "**Current ZH**",
                "",
                str(item.get("current_zh", "")) or "(missing)",
                "",
                "**QC Candidate**",
                "",
                str(item.get("suggest", "")) or "(missing)",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def validate_items(expected: list[dict[str, Any]], reviewed: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    expected_by_id = {text(item["issue_id"]): item for item in expected}
    reviewed_by_id: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    unknown_ids: set[str] = set()
    for item in reviewed:
        issue_id = text(item.get("issue_id"))
        if issue_id in reviewed_by_id:
            duplicate_ids.add(issue_id)
        reviewed_by_id[issue_id] = item
        if issue_id not in expected_by_id:
            unknown_ids.add(issue_id)

    result_items: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    errors: list[str] = []
    for issue_id, expected_item in expected_by_id.items():
        reviewed_item = reviewed_by_id.get(issue_id)
        if reviewed_item is None:
            errors.append(f"Missing decision for {issue_id}.")
            result_items.append({"issue_id": issue_id, "status": "unresolved", "apply_allowed": False})
            continue

        decision = normalize_decision(reviewed_item.get("decision"))
        # Classification is derived from the original QC candidate, not trusted from an edited review file.
        category = text(expected_item.get("category"))
        severity = text(expected_item.get("severity"))
        decision_reason = text(reviewed_item.get("decision_reason"))
        evidence_level = text(reviewed_item.get("evidence_level")) or "insufficient"
        evidence_summary = text(reviewed_item.get("evidence_summary"))
        replacement = text(reviewed_item.get("replacement")) or text(reviewed_item.get("corrected_zh"))
        review_method = text(reviewed_item.get("review_method"))
        errors_for_item: list[str] = []
        effective_decision = decision
        if decision not in FORMAL_DECISIONS:
            errors_for_item.append("Decision must be accept, reject, or defer.")
        if evidence_level not in EVIDENCE_LEVELS:
            errors_for_item.append("Invalid evidence_level.")
        if decision == "accept":
            if not replacement:
                errors_for_item.append("Accepted item has no replacement.")
            if not decision_reason:
                errors_for_item.append("Accepted item has no decision_reason.")
            if not evidence_summary or evidence_level == "insufficient":
                errors_for_item.append("Accepted item lacks sufficient source evidence.")
            if category in HIGH_RISK_CATEGORIES and evidence_level not in {
                "script_confirmed",
                "audio_confirmed",
                "ja_context_confirmed",
            }:
                errors_for_item.append("High-risk semantic item cannot be accepted without source evidence.")
            if is_semantic_expansion({**reviewed_item, "category": category}):
                effective_decision = "defer"
                review_method = review_method or "audio_or_human_review"
        elif decision == "reject" and not decision_reason:
            errors_for_item.append("Rejected item has no decision_reason.")
        elif decision == "defer":
            if not decision_reason:
                errors_for_item.append("Deferred item has no decision_reason.")
            if not review_method:
                errors_for_item.append("Deferred item has no review_method.")
            if reviewed_item.get("review_required") is not True:
                errors_for_item.append("Deferred item must set review_required=true.")

        if effective_decision == "defer":
            manual_review.append(review_payload({**expected_item, **reviewed_item, "category": category, "severity": severity, "review_method": review_method}, "Evidence requires review."))
        apply_allowed = effective_decision == "accept" and not errors_for_item
        status = "ready_to_apply" if apply_allowed else ("deferred" if effective_decision == "defer" else "rejected" if decision == "reject" and not errors_for_item else "invalid")
        if errors_for_item:
            errors.extend(f"{issue_id}: {message}" for message in errors_for_item)
        result_items.append(
            {
                "issue_id": issue_id,
                "file": text(reviewed_item.get("file")) or text(expected_item.get("file")),
                "index": reviewed_item.get("index", expected_item.get("index")),
                "decision": decision,
                "effective_decision": effective_decision,
                "status": status,
                "apply_allowed": apply_allowed,
                "category": category,
                "severity": severity,
                "evidence_level": evidence_level,
                "evidence_summary": evidence_summary,
                "decision_reason": decision_reason,
                "replacement": replacement,
                "errors": errors_for_item,
            }
        )

    if duplicate_ids:
        errors.extend(f"Duplicate decision item: {issue_id}." for issue_id in sorted(duplicate_ids))
    if unknown_ids:
        errors.extend(f"Unknown decision item: {issue_id}." for issue_id in sorted(unknown_ids))
    ready_targets = Counter((text(item["file"]), int(item["index"] or 0)) for item in result_items if item["apply_allowed"])
    for file_name, index in sorted(target for target, count in ready_targets.items() if count > 1):
        errors.append(f"Multiple accepted decisions target {file_name} subtitle {index}.")
        for item in result_items:
            if (text(item["file"]), int(item["index"] or 0)) == (file_name, index) and item["apply_allowed"]:
                item["apply_allowed"] = False
                item["status"] = "invalid"
                item["errors"].append("Multiple accepted decisions target the same subtitle.")
    counts = Counter(item["status"] for item in result_items)
    report = {
        "status": "pass" if not errors else "fail",
        "summary": {
            "total": len(expected),
            "ready_to_apply": counts["ready_to_apply"],
            "rejected": counts["rejected"],
            "deferred": counts["deferred"],
            "invalid": counts["invalid"],
            "unresolved": counts["unresolved"],
            "manual_review_count": len(manual_review),
        },
        "errors": errors,
        "items": result_items,
        "manual_review_items": manual_review,
    }
    return report, not errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate that every QC candidate has an evidence-backed closure decision.")
    parser.add_argument("qc_report", help="Original qc_report.json path.")
    parser.add_argument("review_items", help="Reviewed JSON items from review_qc_report.py.")
    parser.add_argument("--asr-dir", help="Optional directory with matching *.ja.asr.srt files.")
    parser.add_argument("--zh-dir", help="Optional directory with matching *.zh.srt files.")
    parser.add_argument("--json-out", required=True, help="Write qc_closure_report.json to this path.")
    parser.add_argument("--manual-review-json", help="Write deferred items to this JSON path.")
    parser.add_argument("--manual-review-md", help="Write deferred items to this Markdown path.")
    args = parser.parse_args()

    expected = [item.__dict__ for item in normalize_report(read_json(Path(args.qc_report)), asr_dir=Path(args.asr_dir) if args.asr_dir else None, zh_dir=Path(args.zh_dir) if args.zh_dir else None)]
    raw_reviewed = read_json(Path(args.review_items))
    if not isinstance(raw_reviewed, list) or not all(isinstance(item, dict) for item in raw_reviewed):
        raise SystemExit("review_items must be a JSON array of objects.")
    report, passed = validate_items(expected, raw_reviewed)
    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manual_json = Path(args.manual_review_json) if args.manual_review_json else out.with_name("qc_manual_review.json")
    manual_md = Path(args.manual_review_md) if args.manual_review_md else out.with_name("qc_manual_review.md")
    manual_json.write_text(json.dumps(report["manual_review_items"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manual_md.write_text(render_manual_review(report["manual_review_items"]), encoding="utf-8")
    print(out)
    print(f"QC CLOSURE {report['status'].upper()} {report['summary']}", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
