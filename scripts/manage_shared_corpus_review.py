#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from resolve_learning_paths import build_report as build_learning_paths_report, default_user_learning_dir
from update_learning_library import read_config


CHOICES = {"agent-assisted", "user-review", "skip"}
MARKDOWN_TARGETS = {
    "style": "references/style.md",
    "terms": "references/terms.md",
    "risk-notes": "references/risk-notes.md",
    "risk_notes": "references/risk-notes.md",
    "pending": "references/pending.md",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_learning_paths(project_root: Path, path: str, *, create: bool) -> dict[str, Any]:
    if path:
        target = Path(path).expanduser()
        if target.exists():
            return json.loads(target.read_text(encoding="utf-8"))
    return build_learning_paths_report(project_root, create=create)


def ensure_file(path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"# {title}\n\n", encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json_if_exists(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def project_summary(config: dict[str, Any]) -> dict[str, str]:
    paths = config.get("paths", {}) if isinstance(config.get("paths"), dict) else {}
    settings = config.get("settings", {}) if isinstance(config.get("settings"), dict) else {}
    models = config.get("models", {}) if isinstance(config.get("models"), dict) else {}
    return {
        "work_id": str(config.get("work_id") or "UNKNOWN"),
        "project_type": str(config.get("project_type") or "unknown"),
        "project_root": str(paths.get("project_root") or ""),
        "output_format": str(settings.get("output_format") or "unknown"),
        "asr_backend": str(models.get("asr_backend") or "unknown"),
        "translate_backend": str(models.get("translate_backend") or "unknown"),
        "qc_model": str(models.get("qc_model") or "unknown"),
    }


def build_packet(summary: dict[str, str], *, choice: str, evidence_paths: list[str]) -> str:
    lines = [
        f"# Shared Corpus Review - {summary['work_id']}",
        "",
        f"- created_at: {now_utc()}",
        f"- review_choice: {choice}",
        f"- work_id: {summary['work_id']}",
        f"- project_type: {summary['project_type']}",
        f"- project_root: `{summary['project_root']}`",
        f"- output_format: {summary['output_format']}",
        f"- tools: ASR `{summary['asr_backend']}` / translate `{summary['translate_backend']}` / QC `{summary['qc_model']}`",
        "",
        "## Evidence Paths",
        "",
    ]
    if evidence_paths:
        lines.extend(f"- `{item}`" for item in evidence_paths)
    else:
        lines.append("- TODO: add final subtitles, QC report, risk report, readability report, review notes, or user corrections.")
    lines.extend(
        [
            "",
            "## Candidate Items",
            "",
            "Use one block per candidate. Do not move any candidate to the shared user corpus until the user approves it.",
            "",
            "```markdown",
            "### Candidate: <short name>",
            "",
            "- target: style / terms / risk-notes / risk-patterns / pending",
            "- evidence_level: confirmed / project-only / pending / false-positive",
            "- source: RJxxxx / track / subtitle indexes / report path",
            "- ja_or_asr: ...",
            "- current_zh: ...",
            "- proposed_shared_rule: ...",
            "- boundaries: when this applies and when it must not apply",
            "- pollution_risk: low / medium / high",
            "- decision: pending / approve / reject",
            "- reviewer: user / agent-assisted",
            "```",
            "",
            "## Review Result",
            "",
            "- approved_items: TODO / none",
            "- rejected_items: TODO / none",
            "- pending_items: TODO / none",
            "- shared_files_updated: TODO / none",
            "",
        ]
    )
    return "\n".join(lines)


def build_packet_json(summary: dict[str, str], *, choice: str, evidence_paths: list[str], packet_md: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": now_utc(),
        "status": "pending_review" if choice != "skip" else "skipped",
        "review_choice": choice,
        "work": summary,
        "packet_md": packet_md.as_posix(),
        "evidence_paths": evidence_paths,
        "candidates": [
            {
                "id": "TODO-001",
                "target": "style|terms|risk-notes|risk-patterns|pending",
                "title": "TODO short candidate title",
                "evidence_level": "confirmed|project-only|pending|false-positive",
                "source": "RJxxxx / track / subtitle indexes / report path",
                "ja_or_asr": "",
                "current_zh": "",
                "proposed_entry": "Markdown entry to append after approval, or empty until reviewed.",
                "proposed_json": None,
                "boundaries": "When this applies and when it must not apply.",
                "pollution_risk": "low|medium|high",
                "decision": "pending",
                "reviewer": "",
                "review_notes": "",
            }
        ],
        "applied": [],
    }


def append_queue(index_path: Path, summary: dict[str, str], packet_path: Path, choice: str) -> None:
    ensure_file(index_path, "Shared Corpus Review Queue")
    existing = index_path.read_text(encoding="utf-8")
    marker = f"- {summary['work_id']}:"
    if marker in existing and packet_path.as_posix() in existing:
        return
    entry = (
        f"- {summary['work_id']}: {choice}; "
        f"packet `{packet_path.as_posix()}`; "
        f"created_at {now_utc()}; status pending\n"
    )
    index_path.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8")


def append_queue_json(index_json_path: Path, summary: dict[str, str], packet_md: Path, packet_json: Path, choice: str) -> None:
    entries = read_json_if_exists(index_json_path, [])
    if not isinstance(entries, list):
        entries = []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("packet_json") == packet_json.as_posix():
            return
    entries.append(
        {
            "work_id": summary["work_id"],
            "choice": choice,
            "status": "pending_review",
            "created_at": now_utc(),
            "project_root": summary["project_root"],
            "packet_md": packet_md.as_posix(),
            "packet_json": packet_json.as_posix(),
            "next_action": "Fill candidates, set candidate decision=approve/reject/pending, then run manage_shared_corpus_review.py --apply-approved --packet <packet_json>.",
        }
    )
    write_json(index_json_path, entries)


def default_queue_paths() -> tuple[Path, Path]:
    user_dir = default_user_learning_dir()
    return user_dir / "review_queue" / "index.md", user_dir / "review_queue" / "index.json"


def queue_report(index_json_path: Path) -> dict[str, Any]:
    entries = read_json_if_exists(index_json_path, [])
    if not isinstance(entries, list):
        entries = []
    normalized = [entry for entry in entries if isinstance(entry, dict)]
    pending_entries = [
        entry
        for entry in normalized
        if str(entry.get("status") or "") in {"pending", "pending_review"}
    ]
    return {
        "created_at": now_utc(),
        "queue_json_path": index_json_path.as_posix(),
        "total_count": len(normalized),
        "pending_count": len(pending_entries),
        "entries": normalized,
        "pending_entries": pending_entries,
    }


def print_queue(index_json_path: Path) -> dict[str, Any]:
    report = queue_report(index_json_path)
    entries = report["entries"]
    if not entries:
        print("No shared corpus review queue entries.")
        return report
    for idx, entry in enumerate(entries, start=1):
        print(
            f"{idx}. {entry.get('work_id', 'UNKNOWN')} "
            f"status={entry.get('status', 'unknown')} "
            f"choice={entry.get('choice', 'unknown')} "
            f"packet={entry.get('packet_json') or entry.get('packet_md') or ''}"
        )
    print(f"Pending review entries: {report['pending_count']}")
    return report


def append_markdown_once(path: Path, title: str, entry: str, marker: str) -> bool:
    if not entry.strip():
        return False
    ensure_file(path, title)
    existing = path.read_text(encoding="utf-8")
    if marker in existing:
        return False
    block = f"\n<!-- shared-corpus:{marker} -->\n{entry.rstrip()}\n"
    path.write_text(existing.rstrip() + "\n" + block, encoding="utf-8")
    return True


def append_risk_pattern_once(path: Path, candidate: dict[str, Any]) -> bool:
    item = candidate.get("proposed_json")
    if not isinstance(item, dict):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    data = read_json_if_exists(path, [])
    if not isinstance(data, list):
        data = []
    item_id = str(item.get("name") or candidate.get("id") or "")
    if any(isinstance(existing, dict) and str(existing.get("name") or "") == item_id for existing in data):
        return False
    data.append(item)
    write_json(path, data)
    return True


def update_queue_status(index_json_path: Path, packet_json: Path, status: str) -> None:
    entries = read_json_if_exists(index_json_path, [])
    if not isinstance(entries, list):
        return
    changed = False
    for entry in entries:
        if isinstance(entry, dict) and entry.get("packet_json") == packet_json.as_posix():
            entry["status"] = status
            entry["updated_at"] = now_utc()
            changed = True
    if changed:
        write_json(index_json_path, entries)


def apply_approved(packet_json: Path, *, user_learning_dir: Path | None = None) -> dict[str, Any]:
    packet = read_json_if_exists(packet_json, {})
    if not isinstance(packet, dict):
        raise SystemExit(f"Invalid packet JSON: {packet_json}")
    user_dir = user_learning_dir or default_user_learning_dir()
    target_paths = {
        "style": user_dir / "references/style.md",
        "terms": user_dir / "references/terms.md",
        "risk-notes": user_dir / "references/risk-notes.md",
        "risk_notes": user_dir / "references/risk-notes.md",
        "pending": user_dir / "references/pending.md",
        "risk-patterns": user_dir / "data/subtitle_risk_patterns.local.json",
        "risk_patterns": user_dir / "data/subtitle_risk_patterns.local.json",
    }
    titles = {
        "style": "User ASMR Style Rules",
        "terms": "User ASMR Terms",
        "risk-notes": "User ASMR Risk Notes",
        "risk_notes": "User ASMR Risk Notes",
        "pending": "User ASMR Pending Notes",
    }
    applied: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for candidate in packet.get("candidates", []):
        if not isinstance(candidate, dict) or candidate.get("decision") != "approve":
            continue
        candidate_id = str(candidate.get("id") or "unnamed")
        target = str(candidate.get("target") or "").strip()
        path = target_paths.get(target)
        if not path:
            skipped.append({"id": candidate_id, "reason": f"unknown target {target}"})
            continue
        if target in {"risk-patterns", "risk_patterns"}:
            changed = append_risk_pattern_once(path, candidate)
        else:
            changed = append_markdown_once(path, titles.get(target, target), str(candidate.get("proposed_entry") or ""), candidate_id)
        if changed:
            applied.append({"id": candidate_id, "target": target, "path": path.as_posix()})
        else:
            skipped.append({"id": candidate_id, "reason": "empty, duplicate, or unsupported payload"})
    packet["applied"] = applied
    packet["status"] = "applied" if applied else "reviewed_no_changes"
    packet["updated_at"] = now_utc()
    write_json(packet_json, packet)
    _, queue_json = default_queue_paths()
    update_queue_status(queue_json, packet_json, packet["status"])
    return {"packet_json": packet_json.as_posix(), "applied": applied, "skipped": skipped, "status": packet["status"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or queue shared corpus review packets without promoting items automatically.")
    parser.add_argument("project_root", nargs="?")
    parser.add_argument("--choice", choices=sorted(CHOICES), help="User choice after task finalization.")
    parser.add_argument("--list-queue", action="store_true", help="List pending shared corpus review queue entries.")
    parser.add_argument("--apply-approved", action="store_true", help="Apply approved candidates from a review packet JSON to the shared corpus.")
    parser.add_argument("--packet", default="", help="Review packet JSON path for --apply-approved.")
    parser.add_argument("--user-learning-dir", default="", help="Override shared user learning directory for applying approved items.")
    parser.add_argument("--learning-paths", default="")
    parser.add_argument("--evidence", action="append", default=[], help="Evidence path to include in the review packet. Can be repeated.")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    if args.list_queue:
        _, queue_json = default_queue_paths()
        report = print_queue(queue_json)
        if args.json_out:
            out = Path(args.json_out).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0

    if args.apply_approved:
        if not args.packet:
            raise SystemExit("--packet is required with --apply-approved")
        user_dir = Path(args.user_learning_dir).expanduser() if args.user_learning_dir else None
        report = apply_approved(Path(args.packet).expanduser(), user_learning_dir=user_dir)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if not args.project_root or not args.choice:
        raise SystemExit("project_root and --choice are required unless using --list-queue or --apply-approved")

    project_root = Path(args.project_root).expanduser()
    learning_paths = load_learning_paths(project_root, args.learning_paths, create=args.choice != "skip")
    work_paths = learning_paths.get("work_paths", {}) if isinstance(learning_paths.get("work_paths"), dict) else {}
    user_paths = learning_paths.get("user_paths", {}) if isinstance(learning_paths.get("user_paths"), dict) else {}

    packet_path = Path(work_paths.get("shared_corpus_review") or project_root / "learning" / "shared_corpus_review.md")
    packet_json_path = Path(work_paths.get("shared_corpus_review_json") or project_root / "learning" / "shared_corpus_review.json")
    queue_path = Path(user_paths.get("review_queue") or Path.home() / "ASMR-Subtitle-Translator" / "learning" / "review_queue" / "index.md")
    queue_json_path = Path(user_paths.get("review_queue_json") or Path.home() / "ASMR-Subtitle-Translator" / "learning" / "review_queue" / "index.json")

    config = read_config(project_root)
    summary = project_summary(config)
    if not summary["project_root"]:
        summary["project_root"] = project_root.as_posix()

    if args.choice != "skip":
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        if not packet_path.exists():
            packet_path.write_text(build_packet(summary, choice=args.choice, evidence_paths=args.evidence), encoding="utf-8")
        if not packet_json_path.exists():
            write_json(packet_json_path, build_packet_json(summary, choice=args.choice, evidence_paths=args.evidence, packet_md=packet_path))
        append_queue(queue_path, summary, packet_path, args.choice)
        append_queue_json(queue_json_path, summary, packet_path, packet_json_path, args.choice)

    report = {
        "created_at": now_utc(),
        "choice": args.choice,
        "work_id": summary["work_id"],
        "packet_path": packet_path.as_posix() if args.choice != "skip" else "",
        "packet_json_path": packet_json_path.as_posix() if args.choice != "skip" else "",
        "queue_path": queue_path.as_posix() if args.choice != "skip" else "",
        "queue_json_path": queue_json_path.as_posix() if args.choice != "skip" else "",
        "promoted_to_shared_corpus": False,
        "next_action": "Review candidates and explicitly approve items before promotion." if args.choice != "skip" else "Keep learning project-local only.",
    }
    if args.json_out:
        out = Path(args.json_out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
