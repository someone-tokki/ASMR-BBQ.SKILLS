#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Iterable

from subtitle_io import Subtitle, compose_srt_text, parse_srt_text


@dataclass
class RepairIssue:
    level: str
    code: str
    path: str
    message: str
    index: int | None = None
    previous_index: int | None = None
    overlap_ms: int | None = None
    action: str = ""


def rel(path: Path) -> str:
    return path.as_posix()


def ms(value: timedelta) -> int:
    return int(round(value.total_seconds() * 1000))


def timedelta_ms(value: int) -> timedelta:
    return timedelta(milliseconds=value)


def parse_srt_file(path: Path) -> list[Subtitle]:
    return parse_srt_text(path.read_text(encoding="utf-8"))


def iter_asr_srt_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.ja.asr.srt")))
        elif path.name.endswith(".ja.asr.srt"):
            files.append(path)
    return sorted(dict.fromkeys(files))


def matching_zh_path(ja_path: Path, zh_dir: Path | None) -> Path | None:
    if zh_dir is None:
        return None
    return zh_dir / ja_path.name.replace(".ja.asr.srt", ".zh.srt")


def backup_file(path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / path.name
    if backup_path.exists():
        suffix = 1
        while True:
            candidate = backup_dir / f"{path.stem}.bak{suffix}{path.suffix}"
            if not candidate.exists():
                backup_path = candidate
                break
            suffix += 1
    shutil.copy2(path, backup_path)
    return backup_path


def analyze_subtitles(
    path: Path,
    subtitles: list[Subtitle],
    *,
    max_auto_overlap_ms: int,
    warn_overlap_ms: int,
    min_duration_ms: int,
) -> tuple[list[RepairIssue], list[Subtitle], bool]:
    issues: list[RepairIssue] = []
    repaired = [Subtitle(index=sub.index, start=sub.start, end=sub.end, content=sub.content) for sub in subtitles]
    changed = False
    for position in range(1, len(repaired)):
        previous = repaired[position - 1]
        current = repaired[position]
        if current.start >= current.end:
            issues.append(
                RepairIssue(
                    "error",
                    "invalid_time_range",
                    rel(path),
                    "Subtitle start must be before end",
                    index=current.index,
                    action="review_required",
                )
            )
            continue
        if previous.start >= previous.end:
            issues.append(
                RepairIssue(
                    "error",
                    "invalid_time_range",
                    rel(path),
                    "Previous subtitle start must be before end",
                    index=previous.index,
                    action="review_required",
                )
            )
            continue
        if current.start >= previous.end:
            continue

        overlap = previous.end - current.start
        overlap_ms = ms(overlap)
        previous_new_duration_ms = ms(current.start - previous.start)

        if overlap_ms <= max_auto_overlap_ms and previous_new_duration_ms >= min_duration_ms:
            issues.append(
                RepairIssue(
                    "warning",
                    "minor_overlap",
                    rel(path),
                    "Small Whisper-style overlap can be auto-fixed by clipping the previous subtitle end to the current start",
                    index=current.index,
                    previous_index=previous.index,
                    overlap_ms=overlap_ms,
                    action="auto_fixable",
                )
            )
            continue

        if overlap_ms <= max_auto_overlap_ms and previous_new_duration_ms < min_duration_ms:
            issues.append(
                RepairIssue(
                    "warning",
                    "minor_overlap_too_short_after_clip",
                    rel(path),
                    "Small overlap exists, but clipping would make the previous subtitle too short",
                    index=current.index,
                    previous_index=previous.index,
                    overlap_ms=overlap_ms,
                    action="review_required",
                )
            )
            continue

        if overlap_ms <= warn_overlap_ms:
            issues.append(
                RepairIssue(
                    "warning",
                    "moderate_overlap",
                    rel(path),
                    "Overlap is too large for safe auto-fix and needs review",
                    index=current.index,
                    previous_index=previous.index,
                    overlap_ms=overlap_ms,
                    action="review_required",
                )
            )
            continue

        issues.append(
            RepairIssue(
                "error",
                "severe_overlap",
                rel(path),
                "Large overlap strongly suggests non-trivial timeline problems and must not be auto-fixed",
                index=current.index,
                previous_index=previous.index,
                overlap_ms=overlap_ms,
                action="review_required",
            )
        )
    return issues, repaired, changed


def apply_fixes(
    subtitles: list[Subtitle],
    issues: list[RepairIssue],
    *,
    max_auto_overlap_ms: int,
    min_duration_ms: int,
) -> tuple[list[Subtitle], list[RepairIssue], bool]:
    repaired = [Subtitle(index=sub.index, start=sub.start, end=sub.end, content=sub.content) for sub in subtitles]
    changed = False
    updated_issues: list[RepairIssue] = []
    auto_fixable = {
        (issue.previous_index, issue.index): issue
        for issue in issues
        if issue.code == "minor_overlap" and issue.action == "auto_fixable"
    }
    for position in range(1, len(repaired)):
        previous = repaired[position - 1]
        current = repaired[position]
        key = (previous.index, current.index)
        issue = auto_fixable.get(key)
        if issue is None:
            continue
        overlap_ms = ms(previous.end - current.start)
        previous_new_duration_ms = ms(current.start - previous.start)
        if overlap_ms <= max_auto_overlap_ms and previous_new_duration_ms >= min_duration_ms:
            previous.end = current.start
            issue.action = "fixed"
            issue.message = "Clipped previous subtitle end to current subtitle start"
            changed = True
        else:
            issue.action = "review_required"
        updated_issues.append(issue)
    updated_lookup = {(issue.previous_index, issue.index): issue for issue in updated_issues}
    final_issues = [updated_lookup.get((issue.previous_index, issue.index), issue) for issue in issues]
    return repaired, final_issues, changed


def summarize(issues: list[RepairIssue], *, changed_files: int, blocked_files: int) -> dict[str, int]:
    summary = {
        "files": 0,
        "issues": len(issues),
        "auto_fixable": sum(1 for issue in issues if issue.action == "auto_fixable"),
        "fixed": sum(1 for issue in issues if issue.action == "fixed"),
        "needs_review": sum(1 for issue in issues if issue.action == "review_required"),
        "blocked_by_existing_zh": blocked_files,
        "changed_files": changed_files,
    }
    return summary


def print_report(report: dict) -> None:
    summary = report["summary"]
    print(
        "ASR TIMESTAMP REPAIR REPORT "
        f"files={summary['files']} issues={summary['issues']} "
        f"auto_fixable={summary['auto_fixable']} fixed={summary['fixed']} "
        f"needs_review={summary['needs_review']} blocked_by_existing_zh={summary['blocked_by_existing_zh']}"
    )
    for file_record in report["files"]:
        print(f"{file_record['path']}: {file_record['status']}")
        for issue in file_record["issues"]:
            parts = [issue["level"].upper(), issue["code"]]
            if issue.get("previous_index") is not None and issue.get("index") is not None:
                parts.append(f"{issue['previous_index']}->{issue['index']}")
            if issue.get("overlap_ms") is not None:
                parts.append(f"{issue['overlap_ms']}ms")
            if issue.get("action"):
                parts.append(issue["action"])
            print("  " + " | ".join(parts) + f" | {issue['message']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report or repair minor Whisper-style ASR timestamp overlaps.")
    parser.add_argument("paths", nargs="+", help="ASR .ja.asr.srt files or directories containing them.")
    parser.add_argument("--mode", choices=["report", "fix"], default="report")
    parser.add_argument("--zh-dir", help="If provided, block fixes when matching .zh.srt files already exist.")
    parser.add_argument(
        "--allow-asr-only-with-existing-zh",
        action="store_true",
        help="Allow fixing JA ASR files even if matching .zh.srt files exist. Use with caution.",
    )
    parser.add_argument("--max-auto-overlap-ms", type=int, default=120)
    parser.add_argument("--warn-overlap-ms", type=int, default=500)
    parser.add_argument("--min-duration-ms", type=int, default=120)
    parser.add_argument("--backup-dir", help="Required when --mode fix. Backups are written here before changes.")
    parser.add_argument("--json-out", help="Write a JSON report to this path.")
    parser.add_argument("--warnings-as-errors", action="store_true")
    args = parser.parse_args()

    if args.mode == "fix" and not args.backup_dir:
        raise SystemExit("--backup-dir is required when --mode fix")

    zh_dir = Path(args.zh_dir) if args.zh_dir else None
    backup_dir = Path(args.backup_dir) if args.backup_dir else None
    files = iter_asr_srt_files(Path(path) for path in args.paths)
    if not files:
        raise SystemExit("No *.ja.asr.srt files found")

    file_reports: list[dict] = []
    all_issues: list[RepairIssue] = []
    changed_files = 0
    blocked_files = 0

    for path in files:
        subtitles = parse_srt_file(path)
        issues, _, _ = analyze_subtitles(
            path,
            subtitles,
            max_auto_overlap_ms=args.max_auto_overlap_ms,
            warn_overlap_ms=args.warn_overlap_ms,
            min_duration_ms=args.min_duration_ms,
        )
        status = "ok"
        blocked_by_zh = False
        backup_path = ""

        if args.mode == "fix" and issues:
            zh_path = matching_zh_path(path, zh_dir)
            if zh_path and zh_path.exists() and not args.allow_asr_only_with_existing_zh:
                blocked_by_zh = True
                blocked_files += 1
                issues.append(
                    RepairIssue(
                        "warning",
                        "existing_translation_blocks_fix",
                        rel(path),
                        f"Matching translation exists at {zh_path}; fixing JA only would break pair timeline alignment",
                        action="blocked",
                    )
                )
                status = "blocked_by_existing_zh"
            else:
                repaired, issues, changed = apply_fixes(
                    subtitles,
                    issues,
                    max_auto_overlap_ms=args.max_auto_overlap_ms,
                    min_duration_ms=args.min_duration_ms,
                )
                if changed:
                    assert backup_dir is not None
                    backup_path = rel(backup_file(path, backup_dir))
                    path.write_text(compose_srt_text(repaired), encoding="utf-8")
                    changed_files += 1
                    status = "fixed"
                elif issues:
                    status = "needs_review"

        elif issues:
            status = "needs_review"

        all_issues.extend(issues)
        file_reports.append(
            {
                "path": rel(path),
                "status": status,
                "backup_path": backup_path,
                "blocked_by_existing_zh": blocked_by_zh,
                "issues": [asdict(issue) for issue in issues],
            }
        )

    summary = summarize(all_issues, changed_files=changed_files, blocked_files=blocked_files)
    summary["files"] = len(file_reports)
    report = {
        "version": 1,
        "mode": args.mode,
        "summary": summary,
        "files": file_reports,
    }

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print_report(report)
    has_errors = any(issue.level == "error" for issue in all_issues)
    has_warnings = any(issue.level == "warning" for issue in all_issues)
    if has_errors:
        return 1
    if args.warnings_as_errors and has_warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
