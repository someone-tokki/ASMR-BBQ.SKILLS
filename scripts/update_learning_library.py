#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from resolve_learning_paths import build_report as build_learning_paths_report


def read_json_if_exists(path: Path | None) -> Any:
    if not path or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def project_config_path(project_root: Path) -> Path:
    return project_root if project_root.name == "project_config.json" else project_root / "project_config.json"


def read_config(project_root: Path) -> dict[str, Any]:
    path = project_config_path(project_root)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    root = project_root if project_root.name != "project_config.json" else project_root.parent
    return {
        "work_id": root.name,
        "project_type": "unknown",
        "paths": {"project_root": root.as_posix()},
        "models": {},
        "settings": {},
        "artifacts": {},
        "notes": [],
    }


def count_json_issues(data: Any) -> int | None:
    if data is None:
        return None
    if isinstance(data, dict):
        return sum(len(value) for value in data.values() if isinstance(value, list))
    if isinstance(data, list):
        return len(data)
    return None


def path_from_config(config: dict[str, Any], section: str, key: str) -> Path | None:
    value = config.get(section, {}).get(key, "")
    return Path(value) if value else None


def count_files(path: Path | None, pattern: str) -> int | None:
    if not path or not path.exists():
        return None
    return len(list(path.glob(pattern)))


def report_line(label: str, path: Path | None, count: int | None = None) -> str:
    if not path:
        return f"  - {label}: 未记录"
    if count is None:
        status = "存在" if path.exists() else "未找到"
    else:
        status = f"{count} 项"
    return f"  - {label}: `{path.as_posix()}` ({status})"


def work_heading_exists(work_record: Path, work_id: str) -> bool:
    if not work_record.exists():
        return False
    text = work_record.read_text(encoding="utf-8")
    return f"## {work_id}" in text


def build_work_record_entry(config: dict[str, Any], *, today: str) -> str:
    work_id = str(config.get("work_id") or "UNKNOWN")
    project_type = str(config.get("project_type") or "unknown")
    paths = config.get("paths", {})
    models = config.get("models", {})
    settings = config.get("settings", {})
    artifacts = config.get("artifacts", {})

    project_root = Path(paths.get("project_root") or f"generated_subtitles/{work_id}")
    zh_srt_dir = path_from_config(config, "paths", "zh_srt_dir")
    final_dir = path_from_config(config, "paths", "final_dir")
    promo_zh_srt_dir = path_from_config(config, "paths", "promo_zh_srt_dir")
    promo_final_dir = path_from_config(config, "paths", "promo_final_dir")

    qc_report = Path(artifacts["qc_report"]) if artifacts.get("qc_report") else project_root / "qc_report.json"
    risk_report = Path(artifacts["risk_report"]) if artifacts.get("risk_report") else project_root / "risk_report.json"
    readability_report = (
        Path(artifacts["readability_report"]) if artifacts.get("readability_report") else project_root / "readability_report.json"
    )
    validate_report = Path(artifacts["validate_report"]) if artifacts.get("validate_report") else project_root / "validate_report.json"

    qc_count = count_json_issues(read_json_if_exists(qc_report))
    risk_count = count_json_issues(read_json_if_exists(risk_report))
    readability_count = count_json_issues(read_json_if_exists(readability_report))

    lines = [
        f"## {work_id}",
        "",
        f"- 日期：{today}",
        f"- 类型：{project_type}",
        f"- 输出格式：{settings.get('output_format', '未记录')}",
        f"- 输出范围：",
        report_line("中文字幕工作目录", zh_srt_dir, count_files(zh_srt_dir, "*.zh.srt")),
        report_line("最终字幕目录", final_dir, count_files(final_dir, "*.zh.*")),
        report_line("促销中文字幕工作目录", promo_zh_srt_dir, count_files(promo_zh_srt_dir, "*.zh.srt")),
        report_line("促销最终字幕目录", promo_final_dir, count_files(promo_final_dir, "*.zh.*")),
        f"- 工具/后端：ASR `{models.get('asr_backend', '未记录')}` / 翻译 `{models.get('translate_backend', '未记录')}` / QC `{models.get('qc_model', '未记录')}`",
        "- 检查记录：",
        report_line("结构校验", validate_report),
        report_line("风险扫描", risk_report, risk_count),
        report_line("可读性检查", readability_report, readability_count),
        report_line("模型 QC", qc_report, qc_count),
        "- 主要 QC 发现：TODO / 无新增可泛化规则",
        "- 可复用经验：TODO / 无新增可泛化规则",
        "- 已同步：",
        "  - `references/style.md`：TODO / 无",
        "  - `references/terms.md`：TODO / 无",
        "  - `references/risk-notes.md`：TODO / 无",
        "  - `data/subtitle_risk_patterns.local.json`：TODO / 无",
        "  - `references/pending.md`：TODO / 无",
        "",
    ]
    return "\n".join(lines)


def append_block(path: Path, heading: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if heading in existing:
        return
    separator = "" if not existing else ("" if existing.endswith("\n\n") else "\n")
    path.write_text(existing + separator + body.rstrip() + "\n", encoding="utf-8")


def append_user_reference(path: Path, title: str, entry: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {title}\n\n"
    if entry.splitlines()[0] in existing:
        return
    separator = "" if existing.endswith("\n\n") else "\n"
    path.write_text(existing + separator + entry.rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a learning-library update draft for an ASMR subtitle work record.")
    parser.add_argument("project_root", help="Project output root or project_config.json.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Entry date. Defaults to today.")
    parser.add_argument("--out", help="Write Markdown draft to this path. Defaults to stdout.")
    parser.add_argument("--append-work-record", action="store_true", help="Append the work record entry if it does not exist.")
    parser.add_argument("--promote-confirmed", action="store_true", help="Append confirmed items to the user long-term learning library.")
    parser.add_argument("--learning-paths", default="", help="Optional JSON path from resolve_learning_paths.py.")
    parser.add_argument("--work-record", default="", help="Override work_record.md path.")
    parser.add_argument("--user-learning-dir", default="", help="Override user learning directory.")
    args = parser.parse_args()

    config = read_config(Path(args.project_root))
    work_id = str(config.get("work_id") or Path(args.project_root).name)
    learning_paths = None
    if args.learning_paths:
        path = Path(args.learning_paths)
        if path.exists():
            learning_paths = json.loads(path.read_text(encoding="utf-8"))
    else:
        learning_paths = build_learning_paths_report(Path(args.project_root), codex_home=Path.home() / ".codex", create=False)

    work_record = Path(args.work_record) if args.work_record else Path((learning_paths or {}).get("work_record_dir", Path(args.project_root) / "learning")) / "work_record.md"
    user_learning_dir = Path(args.user_learning_dir) if args.user_learning_dir else Path((learning_paths or {}).get("user_learning_dir", Path.home() / ".codex" / "asmr-subtitle-translator" / "learning"))
    user_style = user_learning_dir / "references/style.md"
    user_terms = user_learning_dir / "references/terms.md"
    user_risk = user_learning_dir / "references/risk-notes.md"
    user_pending = user_learning_dir / "references/pending.md"
    user_work_index = user_learning_dir / "references/work-index.md"
    user_risk_patterns = user_learning_dir / "data/subtitle_risk_patterns.local.json"

    entry = build_work_record_entry(config, today=args.date)
    draft = (
        f"# Learning Update Draft - {work_id}\n\n"
        "- Write the work record first; then promote only confirmed items to the user learning library.\n"
        "- This draft intentionally targets a short-lived work record, not the skill package itself.\n\n"
        "## Work Record Entry\n\n"
        f"{entry}\n"
        "## User Library Targets\n\n"
        f"- style: `{user_style.as_posix()}`\n"
        f"- terms: `{user_terms.as_posix()}`\n"
        f"- risk-notes: `{user_risk.as_posix()}`\n"
        f"- pending: `{user_pending.as_posix()}`\n"
        f"- work-index: `{user_work_index.as_posix()}`\n"
        f"- risk-patterns: `{user_risk_patterns.as_posix()}`\n"
    )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(draft, encoding="utf-8")
    else:
        print(draft, end="")

    if args.append_work_record:
        append_block(work_record, f"## {work_id}", entry)
        print(f"work_record_appended={str(True).lower()}")

    if args.promote_confirmed:
        append_user_reference(user_work_index, "ASMR Work Index", f"- {work_id}: {entry.splitlines()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
