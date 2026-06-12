#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from subtitle_io import Subtitle, parse_srt_text


@dataclass
class ReviewItem:
    file: str
    index: int
    problem: str
    suggest: str
    current_zh: str = ""
    current_ja: str = ""
    decision: str = "pending"
    replacement: str = ""
    notes: str = ""


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_srt_map(path: Path) -> dict[int, Subtitle]:
    if not path.exists():
        return {}
    return {subtitle.index: subtitle for subtitle in parse_srt_text(path.read_text(encoding="utf-8"))}


def zh_path_for(ja_name: str, zh_dir: Path | None) -> Path | None:
    if zh_dir is None:
        return None
    return zh_dir / ja_name.replace(".ja.asr.srt", ".zh.srt")


def asr_path_for(ja_name: str, asr_dir: Path | None) -> Path | None:
    if asr_dir is None:
        return None
    return asr_dir / ja_name


def subtitle_content(subtitles: dict[int, Subtitle], index: int) -> str:
    subtitle = subtitles.get(index)
    return subtitle.content if subtitle else ""


def normalize_report(qc_report: object, *, asr_dir: Path | None, zh_dir: Path | None) -> list[ReviewItem]:
    if not isinstance(qc_report, dict):
        raise ValueError("QC report must be a JSON object mapping file names to issue arrays")

    items: list[ReviewItem] = []
    for file_name in sorted(qc_report):
        raw_issues = qc_report[file_name]
        if not isinstance(raw_issues, list):
            continue

        ja_subs = load_srt_map(asr_path_for(file_name, asr_dir)) if asr_dir else {}
        zh_subs = load_srt_map(zh_path_for(file_name, zh_dir)) if zh_dir else {}

        for raw_issue in raw_issues:
            if not isinstance(raw_issue, dict):
                continue
            try:
                index = int(raw_issue["i"])
            except Exception:
                continue
            problem = str(raw_issue.get("problem", "")).strip()
            suggest = str(raw_issue.get("suggest", "")).strip()
            if not problem and not suggest:
                continue

            items.append(
                ReviewItem(
                    file=file_name,
                    index=index,
                    problem=problem,
                    suggest=suggest,
                    current_ja=subtitle_content(ja_subs, index),
                    current_zh=subtitle_content(zh_subs, index),
                )
            )
    return items


def markdown_escape(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def render_markdown(items: list[ReviewItem], qc_path: Path) -> str:
    by_file: dict[str, list[ReviewItem]] = {}
    for item in items:
        by_file.setdefault(item.file, []).append(item)

    lines: list[str] = [
        "# QC Review",
        "",
        f"- Source report: `{qc_path.as_posix()}`",
        f"- Total suggestions: {len(items)}",
        "- Decisions: leave exactly one of accept/reject/defer checked when reviewing.",
        "- Apply no change until the accepted items have been checked against neighboring subtitles and source context.",
        "- JSON workflow: set decision to accept/reject/defer; optionally set replacement when the suggestion needs editing before applying.",
        "- Apply accepted JSON decisions with scripts/apply_qc_decisions.py, then rerun validation, risk scan, and readability checks.",
        "",
    ]

    for file_name, file_items in by_file.items():
        lines.extend([f"## {file_name}", ""])
        for item in file_items:
            lines.extend(
                [
                    f"### #{item.index}",
                    "",
                    "- [ ] accept",
                    "- [ ] reject",
                    "- [ ] defer",
                    "",
                    "**Problem**",
                    "",
                    markdown_escape(item.problem) or "(none)",
                    "",
                ]
            )
            if item.current_ja:
                lines.extend(["**Current JA ASR**", "", markdown_escape(item.current_ja), ""])
            if item.current_zh:
                lines.extend(["**Current ZH**", "", markdown_escape(item.current_zh), ""])
            lines.extend(
                [
                    "**Suggested ZH**",
                    "",
                    markdown_escape(item.suggest) or "(none)",
                    "",
                    "**Reviewer Notes**",
                    "",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def print_summary(items: list[ReviewItem]) -> None:
    by_file: dict[str, int] = {}
    for item in items:
        by_file[item.file] = by_file.get(item.file, 0) + 1
    print(f"QC REVIEW ITEMS {len(items)}", file=sys.stderr)
    for file_name in sorted(by_file):
        print(f"{file_name}: {by_file[file_name]}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert qc_report.json into a human QC decision template.")
    parser.add_argument("qc_report", help="Path to qc_report.json.")
    parser.add_argument("--asr-dir", help="Optional directory with matching *.ja.asr.srt files.")
    parser.add_argument("--zh-dir", help="Optional directory with matching *.zh.srt files.")
    parser.add_argument("--out", help="Write Markdown review template to this path. Defaults to stdout.")
    parser.add_argument("--json-out", help="Write normalized JSON review items to this path.")
    args = parser.parse_args()

    qc_path = Path(args.qc_report)
    items = normalize_report(
        read_json(qc_path),
        asr_dir=Path(args.asr_dir) if args.asr_dir else None,
        zh_dir=Path(args.zh_dir) if args.zh_dir else None,
    )

    markdown = render_markdown(items, qc_path)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")

    if args.json_out:
        json_out = Path(args.json_out)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2), encoding="utf-8")

    print_summary(items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
