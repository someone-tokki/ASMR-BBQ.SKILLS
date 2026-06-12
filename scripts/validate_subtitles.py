#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from subtitle_io import Subtitle, parse_srt_text


@dataclass
class Issue:
    level: str
    code: str
    path: str
    message: str
    index: int | None = None


WORK_ARTIFACT_SUFFIXES = (
    ".ja.asr.srt",
    ".ja.asr.json",
    ".partial.json",
)
WORK_ARTIFACT_NAMES = {
    "qc_report.json",
    "validate_report.json",
    "risk_report.json",
    "readability_report.json",
    "review_notes.md",
    "asr_vs_script_report.md",
}


def rel(path: Path) -> str:
    return path.as_posix()


def parse_srt_file(path: Path) -> tuple[list[Subtitle], list[Issue]]:
    try:
        return parse_srt_text(path.read_text(encoding="utf-8")), []
    except Exception as exc:
        return [], [Issue("error", "parse_error", rel(path), f"Could not parse SRT: {exc}")]


def check_subtitles(path: Path, subtitles: list[Subtitle]) -> list[Issue]:
    issues: list[Issue] = []
    previous_end = None
    previous_index = 0
    for position, subtitle in enumerate(subtitles, start=1):
        if subtitle.index != previous_index + 1:
            issues.append(
                Issue(
                    "error",
                    "index_not_continuous",
                    rel(path),
                    f"Expected subtitle index {previous_index + 1}, found {subtitle.index}",
                    subtitle.index,
                )
            )
        previous_index = subtitle.index

        if subtitle.start >= subtitle.end:
            issues.append(
                Issue(
                    "error",
                    "invalid_time_range",
                    rel(path),
                    "Subtitle start must be before end",
                    subtitle.index,
                )
            )
        if previous_end is not None and subtitle.start < previous_end:
            issues.append(
                Issue(
                    "error",
                    "time_overlap",
                    rel(path),
                    "Subtitle starts before the previous subtitle ends",
                    subtitle.index,
                )
            )
        if not subtitle.content.strip():
            issues.append(Issue("error", "empty_subtitle", rel(path), "Subtitle content is empty", subtitle.index))
        previous_end = subtitle.end

        if subtitle.index != position:
            # This duplicates the continuity check but gives a clearer position hint for manually edited files.
            issues.append(
                Issue(
                    "warning",
                    "index_position_mismatch",
                    rel(path),
                    f"Subtitle appears at position {position} but has index {subtitle.index}",
                    subtitle.index,
                )
            )
    return issues


def iter_srt_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.srt")))
        elif path.suffix.lower() == ".srt":
            files.append(path)
    return sorted(dict.fromkeys(files))


def check_srt_paths(paths: Iterable[Path]) -> list[Issue]:
    issues: list[Issue] = []
    for path in iter_srt_files(paths):
        subtitles, parse_issues = parse_srt_file(path)
        issues.extend(parse_issues)
        if not parse_issues:
            issues.extend(check_subtitles(path, subtitles))
    return issues


def compare_subtitle_pair(ja_path: Path, zh_path: Path) -> list[Issue]:
    issues: list[Issue] = []
    if not zh_path.exists():
        return [Issue("error", "missing_translation", rel(zh_path), f"Missing translation for {ja_path.name}")]

    ja_subs, ja_issues = parse_srt_file(ja_path)
    zh_subs, zh_issues = parse_srt_file(zh_path)
    issues.extend(ja_issues)
    issues.extend(zh_issues)
    if ja_issues or zh_issues:
        return issues

    issues.extend(check_subtitles(ja_path, ja_subs))
    issues.extend(check_subtitles(zh_path, zh_subs))

    if len(ja_subs) != len(zh_subs):
        issues.append(
            Issue(
                "error",
                "count_mismatch",
                rel(zh_path),
                f"ASR has {len(ja_subs)} subtitles but translation has {len(zh_subs)}",
            )
        )

    for ja, zh in zip(ja_subs, zh_subs):
        if ja.index != zh.index:
            issues.append(
                Issue(
                    "error",
                    "pair_index_mismatch",
                    rel(zh_path),
                    f"Expected index {ja.index} from {ja_path.name}, found {zh.index}",
                    zh.index,
                )
            )
        if ja.start != zh.start or ja.end != zh.end:
            issues.append(
                Issue(
                    "error",
                    "pair_timeline_mismatch",
                    rel(zh_path),
                    f"Timeline differs from {ja_path.name} at index {ja.index}",
                    zh.index,
                )
            )
    return issues


def check_pairs(asr_dir: Path, zh_dir: Path) -> list[Issue]:
    issues: list[Issue] = []
    if not asr_dir.exists():
        return [Issue("error", "missing_asr_dir", rel(asr_dir), "ASR directory does not exist")]
    if not zh_dir.exists():
        return [Issue("error", "missing_zh_dir", rel(zh_dir), "Translation directory does not exist")]

    ja_files = sorted(asr_dir.glob("*.ja.asr.srt"))
    if not ja_files:
        issues.append(Issue("warning", "no_asr_files", rel(asr_dir), "No *.ja.asr.srt files found"))
    for ja_path in ja_files:
        zh_path = zh_dir / ja_path.name.replace(".ja.asr.srt", ".zh.srt")
        issues.extend(compare_subtitle_pair(ja_path, zh_path))
    return issues


def check_final_dir(final_dir: Path, *, allow_work_artifacts: bool = False) -> list[Issue]:
    issues: list[Issue] = []
    if not final_dir.exists():
        return [Issue("error", "missing_final_dir", rel(final_dir), "Final subtitle directory does not exist")]

    zh_vtts = list(final_dir.glob("*.zh.vtt"))
    zh_srts = list(final_dir.glob("*.zh.srt"))
    if not zh_vtts and not zh_srts:
        issues.append(Issue("warning", "no_final_subtitles", rel(final_dir), "No *.zh.vtt or *.zh.srt files found"))

    for path in sorted(final_dir.iterdir()):
        if path.is_dir():
            continue
        name = path.name
        if name in WORK_ARTIFACT_NAMES or any(name.endswith(suffix) for suffix in WORK_ARTIFACT_SUFFIXES):
            if allow_work_artifacts:
                continue
            issues.append(
                Issue(
                    "warning",
                    "work_artifact_in_final_dir",
                    rel(path),
                    "Final directory appears to contain an intermediate work artifact",
                )
            )
    return issues


def print_report(issues: list[Issue]) -> None:
    if not issues:
        print("VALIDATION OK")
        return

    errors = [issue for issue in issues if issue.level == "error"]
    warnings = [issue for issue in issues if issue.level == "warning"]
    print(f"VALIDATION FOUND {len(errors)} error(s), {len(warnings)} warning(s)")
    for issue in issues:
        index = f" #{issue.index}" if issue.index is not None else ""
        print(f"{issue.level.upper()} {issue.code} {issue.path}{index}: {issue.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ASMR SRT subtitle structure and ASR/translation alignment.")
    parser.add_argument("paths", nargs="*", help="SRT files or directories to validate individually.")
    parser.add_argument("--asr-dir", help="Directory containing *.ja.asr.srt files.")
    parser.add_argument("--zh-dir", help="Directory containing matching *.zh.srt files.")
    parser.add_argument("--final-dir", help="Final delivery directory to check for subtitle presence and mixed work artifacts.")
    parser.add_argument("--allow-work-artifacts", action="store_true", help="Allow reports/configs in --final-dir. Use when final VTT files are intentionally exported to PROJECT_ROOT.")
    parser.add_argument("--json-out", help="Write a JSON report to this path.")
    parser.add_argument("--warnings-as-errors", action="store_true", help="Return exit code 1 when warnings are present.")
    args = parser.parse_args()

    issues: list[Issue] = []
    if args.paths:
        issues.extend(check_srt_paths(Path(path) for path in args.paths))
    if args.asr_dir or args.zh_dir:
        if not args.asr_dir or not args.zh_dir:
            issues.append(Issue("error", "missing_pair_argument", ".", "--asr-dir and --zh-dir must be provided together"))
        else:
            issues.extend(check_pairs(Path(args.asr_dir), Path(args.zh_dir)))
    if args.final_dir:
        issues.extend(check_final_dir(Path(args.final_dir), allow_work_artifacts=args.allow_work_artifacts))
    if not args.paths and not (args.asr_dir or args.zh_dir) and not args.final_dir:
        issues.append(Issue("error", "no_input", ".", "Provide paths, --asr-dir/--zh-dir, or --final-dir"))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([asdict(issue) for issue in issues], ensure_ascii=False, indent=2), encoding="utf-8")

    print_report(issues)
    has_errors = any(issue.level == "error" for issue in issues)
    has_warnings = any(issue.level == "warning" for issue in issues)
    return 1 if has_errors or (args.warnings_as_errors and has_warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
