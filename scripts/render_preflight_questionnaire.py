#!/usr/bin/env python3
"""Render the fixed, seven-item ASMR subtitle preflight questionnaire.

The agent must present this file verbatim after read-only discovery and before
any ASR, translation, or QC model call. Keeping the questions in a generated
artifact prevents an execution frontend from silently shrinking the checklist.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_ITEMS = (
    "scope",
    "quality_mode",
    "asr",
    "translate",
    "qc",
    "output_format",
    "wav_only_asr_strategy",
)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def path_for(project_root: Path, requested: str, name: str) -> Path:
    return Path(requested) if requested else project_root / name


def folder_lines(scope: dict[str, Any]) -> list[str]:
    folders = scope.get("folders", [])
    if not isinstance(folders, list) or not folders:
        return ["- 未发现可选文件夹；请先修复或重跑 audio_scope_report.json。"]
    lines: list[str] = []
    for index, folder in enumerate(folders, start=1):
        if not isinstance(folder, dict):
            continue
        duration = float(folder.get("known_duration_sec") or 0)
        duration_text = f"{duration / 60:.1f} 分钟（已知）" if duration else "时长待探测"
        tags = ", ".join(str(tag) for tag in folder.get("tags", []) if tag) or "audio"
        lines.append(
            f"- [{index}] {folder.get('folder', '.') } | {folder.get('audio_count', 0)} 个文件 | {duration_text} | {tags}"
        )
    return lines or ["- 未发现可选文件夹；请先修复或重跑 audio_scope_report.json。"]


def existing_asr_lines(source_root: Path) -> list[str]:
    matches = sorted(path for path in source_root.rglob("*.ja.asr.srt") if not path.name.startswith("._"))
    if not matches:
        return ["- 未发现可复用的 `.ja.asr.srt`。"]
    return [f"- 已发现可复用 ASR：{path.relative_to(source_root).as_posix()}" for path in matches]


def render(project_root: Path, source_root: Path, scope: dict[str, Any], source: dict[str, Any], env: dict[str, Any]) -> str:
    source_notes = source.get("notes", []) if isinstance(source.get("notes"), list) else []
    source_decision = str(source.get("decision") or "未生成音源选择报告")
    env_summary = str(env.get("overall_status") or env.get("status") or "未生成环境报告")
    recommended = source.get("recommended_asr_files", []) if isinstance(source.get("recommended_asr_files"), list) else []
    recommendation_lines = [
        f"- 音源扫描结论：{source_decision}",
        f"- 环境检测结论：{env_summary}",
    ]
    for item in recommended:
        if isinstance(item, dict):
            recommendation_lines.append(f"- 推荐 ASR 候选：{item.get('path', '')}（requires_review={item.get('requires_review', False)}）")
    recommendation_lines.extend(f"- {note}" for note in source_notes[:3])

    return "\n".join(
        [
            "<!-- ASMR-PREFLIGHT v1 required-items: " + ",".join(REQUIRED_ITEMS) + " -->",
            "# ASMR 字幕开工确认单（必须一次性逐项确认）",
            "",
            "扫描已完成。请一次性回复以下七项；未确认前不得开始 ASR、翻译或 QC 模型调用。",
            "",
            "## 扫描结果",
            *folder_lines(scope),
            *existing_asr_lines(source_root),
            *recommendation_lines,
            "",
            "## 1. 翻译范围（scope）",
            "请选择：全部 / 指定文件夹编号或名称 / 指定具体音频文件。试听、DLC、EX、bonus 不会被自动跳过。",
            "",
            "## 2. 精度模式（quality_mode）",
            "请选择：draft（最快粗稿）/ standard（推荐，two-pass QC）/ premium（更严格）/ polish（复用成果精修）。",
            "",
            "## 3. ASR（asr）",
            "请分别确认：复用已有 ASR 或新建 ASR；backend、base URL（如适用）与模型。默认只是一项建议，不构成确认。",
            "",
            "## 4. 翻译（translate）",
            "请分别确认：backend、base URL（如适用）与 chat 模型；不得从 ASR 自动沿用。",
            "",
            "## 5. QC（qc）",
            "请分别确认：backend、base URL（如适用）与 QC chat 模型；QC 必须是独立确认项。",
            "",
            "## 6. 输出格式（output_format）",
            "请选择：vtt / srt / both。",
            "",
            "## 7. 条件性 WAV-only 策略（wav_only_asr_strategy）",
            "若选中轨道最终没有安全的原生 MP3：请选择 `转临时 MP3`（mp3_cache）或 `直接使用 WAV`（original_wav）。若本次不适用，会记录为 not_applicable，不会另行追问。",
            "",
            "可直接回复：`范围：全部；质量：standard；ASR：…；翻译：…；QC：…；输出：vtt；WAV-only：original_wav`。",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the mandatory seven-item preflight questionnaire from discovery reports.")
    parser.add_argument("project_root")
    parser.add_argument("--source-project-dir", required=True)
    parser.add_argument("--audio-scope-report", default="")
    parser.add_argument("--audio-source-report", default="")
    parser.add_argument("--env-report", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    project_root = Path(args.project_root)
    source_root = Path(args.source_project_dir)
    if not source_root.exists():
        raise SystemExit(f"Source project directory not found: {source_root}")
    scope = read_json(path_for(project_root, args.audio_scope_report, "audio_scope_report.json"))
    source = read_json(path_for(project_root, args.audio_source_report, "audio_source_report.json"))
    env = read_json(path_for(project_root, args.env_report, "env_report.json"))
    out = path_for(project_root, args.out, "preflight_questionnaire.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(project_root, source_root, scope, source, env), encoding="utf-8")
    print(out.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
