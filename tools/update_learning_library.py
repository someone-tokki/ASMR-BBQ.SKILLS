#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_PROJECT_LESSONS = Path("references/project-lessons.md")


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


def project_heading_exists(project_lessons: Path, work_id: str) -> bool:
    if not project_lessons.exists():
        return False
    text = project_lessons.read_text(encoding="utf-8")
    return f"## {work_id}" in text


def build_project_entry(config: dict[str, Any], *, today: str) -> str:
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
        "  - `data/subtitle_risk_patterns.json`：TODO / 无",
        "  - `references/pending.md`：TODO / 无",
        "",
    ]
    return "\n".join(lines)


def build_draft(config: dict[str, Any], *, today: str, project_lessons: Path) -> str:
    work_id = str(config.get("work_id") or "UNKNOWN")
    exists = project_heading_exists(project_lessons, work_id)
    entry = build_project_entry(config, today=today)
    return (
        f"# Learning Library Update Draft - {work_id}\n\n"
        f"- Project lesson already exists: {'yes' if exists else 'no'}\n"
        "- Use this draft after final QC/checks. Replace TODO items with evidence-backed lessons.\n"
        "- Add reusable style, terminology, and easy-mistake notes to their shared reference files; keep uncertain items in pending.\n\n"
        "## Project Lesson Entry\n\n"
        f"{entry}\n"
        "## Shared Reference Checklist\n\n"
        "- `references/style.md`: ASMR pacing, tone, readable subtitle style, reusable phrasing.\n"
        "- `references/terms.md`: stable terms with source, recommended translation, rejected translation, context.\n"
        "- `references/risk-notes.md`: confirmed easy mistakes, ASR misrecognitions, model mistranslations, false positives.\n"
        "- `data/subtitle_risk_patterns.json`: mechanically scannable confirmed risks only.\n"
        "- `references/pending.md`: no-script, not-listened, or evidence-insufficient items.\n"
    )


def append_project_lesson(project_lessons: Path, entry: str, work_id: str) -> bool:
    if project_heading_exists(project_lessons, work_id):
        return False
    project_lessons.parent.mkdir(parents=True, exist_ok=True)
    existing = project_lessons.read_text(encoding="utf-8") if project_lessons.exists() else "# 作品经验记录\n"
    separator = "\n" if existing.endswith("\n") else "\n\n"
    project_lessons.write_text(existing + separator + entry.rstrip() + "\n", encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a learning-library update draft for an ASMR subtitle project.")
    parser.add_argument("project_root", help="Project output root or project_config.json.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Entry date. Defaults to today.")
    parser.add_argument("--out", help="Write Markdown draft to this path. Defaults to stdout.")
    parser.add_argument("--append-project-lesson", action="store_true", help="Append the project lesson entry if it does not exist.")
    parser.add_argument("--project-lessons", default=DEFAULT_PROJECT_LESSONS.as_posix(), help="Path to project lessons reference.")
    args = parser.parse_args()

    config = read_config(Path(args.project_root))
    project_lessons = Path(args.project_lessons)
    draft = build_draft(config, today=args.date, project_lessons=project_lessons)
    entry = build_project_entry(config, today=args.date)
    work_id = str(config.get("work_id") or Path(args.project_root).name)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(draft, encoding="utf-8")
    else:
        print(draft, end="")

    if args.append_project_lesson:
        appended = append_project_lesson(project_lessons, entry, work_id)
        print(f"project_lesson_appended={str(appended).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
