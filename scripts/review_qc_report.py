#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from subtitle_io import Subtitle, format_srt_timestamp, parse_srt_text


HIGH_RISK_CATEGORIES = {"semantic", "omission", "hallucination", "terminology", "role_tone"}
FORMAL_DECISIONS = {"accept", "reject", "defer"}
EVIDENCE_LEVELS = {"script_confirmed", "audio_confirmed", "ja_context_confirmed", "insufficient"}


@dataclass
class ReviewItem:
    issue_id: str
    file: str
    index: int
    problem: str
    suggest: str
    category: str
    severity: str
    current_zh: str = ""
    current_ja: str = ""
    start: str = ""
    end: str = ""
    context_before: list[dict[str, object]] = field(default_factory=list)
    context_after: list[dict[str, object]] = field(default_factory=list)
    decision: str = "pending"
    decision_reason: str = ""
    evidence_level: str = "insufficient"
    evidence_summary: str = ""
    replacement: str = ""
    review_required: bool = False
    review_method: str = ""
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


def subtitle_context(subtitles: dict[int, Subtitle], index: int) -> dict[str, object] | None:
    subtitle = subtitles.get(index)
    if subtitle is None:
        return None
    return {
        "i": subtitle.index,
        "start": format_srt_timestamp(subtitle.start),
        "end": format_srt_timestamp(subtitle.end),
        "text": subtitle.content,
    }


def paired_context(ja_subs: dict[int, Subtitle], zh_subs: dict[int, Subtitle], index: int) -> dict[str, object] | None:
    ja = subtitle_context(ja_subs, index)
    zh = subtitle_context(zh_subs, index)
    if ja is None and zh is None:
        return None
    return {
        "i": index,
        "start": (ja or zh or {}).get("start", ""),
        "end": (ja or zh or {}).get("end", ""),
        "ja": (ja or {}).get("text", ""),
        "zh": (zh or {}).get("text", ""),
    }


def classify_issue(problem: str, suggest: str) -> tuple[str, str]:
    text = f"{problem} {suggest}".lower()
    if re.search(r"漏译|遗漏|缺失|没翻", text):
        return "omission", "high"
    if re.search(r"幻觉|荒唐|误识别|asr", text):
        return "hallucination", "high"
    if re.search(r"术语|专有|译名|名词", text):
        return "terminology", "high"
    if re.search(r"人称|称呼|角色|语气|敬语|口吻", text):
        return "role_tone", "high"
    if re.search(r"标点|断句|换行|编号|时间轴|格式|残留日文|残留英文", text):
        return "formatting", "low"
    if re.search(r"可读|阅读|过长|字数|字符|cps", text):
        return "readability", "medium"
    if re.search(r"错译|语义|上下文|逻辑|不通", text):
        return "semantic", "high"
    return "semantic", "high"


def stable_issue_id(file_name: str, index: int, problem: str, suggest: str) -> str:
    payload = "\x1f".join((file_name, str(index), problem.strip(), suggest.strip()))
    return "qc-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def normalize_report(qc_report: object, *, asr_dir: Path | None, zh_dir: Path | None) -> list[ReviewItem]:
    if not isinstance(qc_report, dict):
        raise ValueError("QC report must be a JSON object mapping file names to issue arrays")

    items: list[ReviewItem] = []
    seen_ids: set[str] = set()
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

            issue_id = stable_issue_id(file_name, index, problem, suggest)
            if issue_id in seen_ids:
                continue
            seen_ids.add(issue_id)
            category, severity = classify_issue(problem, suggest)
            current_ja = ja_subs.get(index)
            current_zh = zh_subs.get(index)
            before = [paired_context(ja_subs, zh_subs, i) for i in (index - 2, index - 1)]
            after = [paired_context(ja_subs, zh_subs, i) for i in (index + 1, index + 2)]
            items.append(
                ReviewItem(
                    issue_id=issue_id,
                    file=file_name,
                    index=index,
                    problem=problem,
                    suggest=suggest,
                    category=category,
                    severity=severity,
                    current_ja=current_ja.content if current_ja else "",
                    current_zh=current_zh.content if current_zh else "",
                    start=format_srt_timestamp((current_ja or current_zh).start) if current_ja or current_zh else "",
                    end=format_srt_timestamp((current_ja or current_zh).end) if current_ja or current_zh else "",
                    context_before=[item for item in before if item is not None],
                    context_after=[item for item in after if item is not None],
                )
            )
    return items


def markdown_escape(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def render_context(items: list[dict[str, object]]) -> str:
    if not items:
        return "(none)"
    return "\n".join(
        f"- #{item['i']} JA: {item.get('ja', '')}\n  ZH: {item.get('zh', '')}" for item in items
    )


def render_markdown(items: list[ReviewItem], qc_path: Path) -> str:
    by_file: dict[str, list[ReviewItem]] = {}
    for item in items:
        by_file.setdefault(item.file, []).append(item)

    lines: list[str] = [
        "# QC Review",
        "",
        f"- Source report: `{qc_path.as_posix()}`",
        f"- Total suggestions: {len(items)}",
        "- Before closure, every item must have exactly one decision: accept, reject, or defer.",
        "- accept requires source evidence and a minimal replacement; reject requires a reason; defer requires a review method.",
        "- Do not apply changes until validate_qc_closure.py has produced a passing closure report.",
        "",
    ]
    for file_name, file_items in by_file.items():
        lines.extend([f"## {file_name}", ""])
        for item in file_items:
            lines.extend(
                [
                    f"### #{item.index} ({item.issue_id})",
                    "",
                    f"- Category/severity: `{item.category}` / `{item.severity}`",
                    "- [ ] accept",
                    "- [ ] reject",
                    "- [ ] defer",
                    "",
                    "**Problem**",
                    "",
                    markdown_escape(item.problem) or "(none)",
                    "",
                    "**Current JA ASR**",
                    "",
                    markdown_escape(item.current_ja) or "(none)",
                    "",
                    "**Current ZH**",
                    "",
                    markdown_escape(item.current_zh) or "(none)",
                    "",
                    "**Suggested ZH**",
                    "",
                    markdown_escape(item.suggest) or "(none)",
                    "",
                    "**Neighbor Context**",
                    "",
                    render_context(item.context_before + item.context_after),
                    "",
                    "**Evidence**",
                    "",
                    "- level: script_confirmed / audio_confirmed / ja_context_confirmed / insufficient",
                    "- summary:",
                    "",
                    "**Decision Reason / Final Replacement**",
                    "",
                    "- reason:",
                    "- replacement:",
                    "- review required: yes/no",
                    "- review method:",
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
    parser = argparse.ArgumentParser(description="Convert qc_report.json into an evidence-backed QC decision template.")
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
        json_out.write_text(json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_summary(items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
