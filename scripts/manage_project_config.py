#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFIG_NAME = "project_config.json"
CONFIG_VERSION = 1
OUTPUT_FORMATS = {"vtt", "srt", "both"}
PROJECT_TYPES = {"with-script", "no-script", "subtitle-only", "format-only", "unknown"}
PLATFORM_PROFILES = {"auto", "macos-mlx", "windows-ollama", "wsl-ollama", "generic-openai"}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_path(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).as_posix()


def config_path(project_root: Path) -> Path:
    return project_root / CONFIG_NAME


def read_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split_notes(values: list[str]) -> list[str]:
    notes: list[str] = []
    for value in values:
        for part in value.splitlines():
            part = part.strip()
            if part:
                notes.append(part)
    return notes


def build_config(args: argparse.Namespace, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    created_at = existing.get("created_at") if existing else now_utc()
    project_root = Path(args.project_root)
    work_id = args.work_id or project_root.name

    return {
        "config_version": CONFIG_VERSION,
        "created_at": created_at,
        "updated_at": now_utc(),
        "work_id": work_id,
        "project_type": args.project_type,
        "platform": {
            "system": platform.system(),
            "python": platform.python_version(),
            "profile": args.platform_profile,
        },
        "paths": {
            "project_root": project_root.as_posix(),
            "source_audio_dir": normalize_path(args.source_audio_dir),
            "script_path": normalize_path(args.script_path),
            "asr_dir": normalize_path(args.asr_dir),
            "zh_srt_dir": normalize_path(args.zh_srt_dir),
            "final_dir": normalize_path(args.final_dir),
            "promo_asr_dir": normalize_path(args.promo_asr_dir),
            "promo_zh_srt_dir": normalize_path(args.promo_zh_srt_dir),
            "promo_final_dir": normalize_path(args.promo_final_dir),
        },
        "models": {
            "asr_backend": args.asr_backend,
            "asr_base_url": args.asr_base_url,
            "asr_model": args.asr_model,
            "translate_backend": args.translate_backend,
            "translate_base_url": args.translate_base_url,
            "translate_model": args.translate_model,
            "translate_model_class": getattr(args, "translate_model_class", ""),
            "translate_behavior_probe_required": getattr(args, "translate_behavior_probe_required", None),
            "translate_require_non_thinking": getattr(args, "translate_require_non_thinking", None),
            "qc_backend": args.qc_backend,
            "qc_base_url": args.qc_base_url,
            "qc_model": args.qc_model,
            "qc_model_class": getattr(args, "qc_model_class", ""),
            "qc_behavior_probe_required": getattr(args, "qc_behavior_probe_required", None),
            "qc_require_non_thinking": getattr(args, "qc_require_non_thinking", None),
        },
        "settings": {
            "output_format": args.output_format,
            "translate_chunk_size": args.translate_chunk_size,
            "qc_chunk_size": args.qc_chunk_size,
            "readability_max_cps": args.readability_max_cps,
        },
        "artifacts": {
            "script_compare_report": normalize_path(args.script_compare_report),
            "validate_report": normalize_path(args.validate_report),
            "risk_report": normalize_path(args.risk_report),
            "readability_report": normalize_path(args.readability_report),
            "qc_report": normalize_path(args.qc_report),
            "qc_review": normalize_path(args.qc_review),
            "qc_review_items": normalize_path(args.qc_review_items),
        },
        "notes": split_notes(args.note),
    }


def print_config_summary(data: dict[str, Any]) -> None:
    paths = data.get("paths", {})
    models = data.get("models", {})
    settings = data.get("settings", {})
    print(f"work_id: {data.get('work_id', '')}")
    print(f"project_type: {data.get('project_type', '')}")
    print(f"output_format: {settings.get('output_format', '')}")
    print(f"asr_dir: {paths.get('asr_dir', '')}")
    print(f"zh_srt_dir: {paths.get('zh_srt_dir', '')}")
    print(f"final_dir: {paths.get('final_dir', '')}")
    if paths.get("promo_asr_dir") or paths.get("promo_zh_srt_dir"):
        print(f"promo_asr_dir: {paths.get('promo_asr_dir', '')}")
        print(f"promo_zh_srt_dir: {paths.get('promo_zh_srt_dir', '')}")
        print(f"promo_final_dir: {paths.get('promo_final_dir', '')}")
    print(f"asr_backend: {models.get('asr_backend', '')}")
    print(f"asr_base_url: {models.get('asr_base_url', '')}")
    print(f"translate_backend: {models.get('translate_backend', '')}")
    print(f"translate_base_url: {models.get('translate_base_url', '')}")
    print(f"translate_model: {models.get('translate_model', '')}")
    print(f"qc_backend: {models.get('qc_backend', '')}")
    print(f"qc_base_url: {models.get('qc_base_url', '')}")
    print(f"qc_model: {models.get('qc_model', '')}")
    print(f"qc_report: {data.get('artifacts', {}).get('qc_report', '')}")


def add_common_init_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_root", help="Project artifact root, normally /path/to/RJxxxx/subtitle_project.")
    parser.add_argument("--work-id", help="Work ID. Defaults to project_root directory name.")
    parser.add_argument("--project-type", default="unknown", choices=sorted(PROJECT_TYPES))
    parser.add_argument("--platform-profile", default="auto", choices=sorted(PLATFORM_PROFILES))
    parser.add_argument("--source-audio-dir", default="")
    parser.add_argument("--script-path", default="")
    parser.add_argument("--asr-dir", default="")
    parser.add_argument("--zh-srt-dir", default="")
    parser.add_argument("--final-dir", default="")
    parser.add_argument("--promo-asr-dir", default="")
    parser.add_argument("--promo-zh-srt-dir", default="")
    parser.add_argument("--promo-final-dir", default="")
    parser.add_argument("--asr-backend", default="auto")
    parser.add_argument("--asr-base-url", default="", help="Local ASR API base URL, for example http://127.0.0.1:8000/v1.")
    parser.add_argument("--asr-model", default="")
    parser.add_argument("--translate-backend", default="auto", help="Backend record: auto, ollama, omlx, openai-compatible, or another project-specific value.")
    parser.add_argument("--translate-base-url", default="")
    parser.add_argument("--translate-model", default="")
    parser.add_argument("--translate-model-class", default="")
    parser.add_argument("--translate-behavior-probe-required", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--translate-require-non-thinking", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--qc-backend", default="auto", help="QC backend record. Defaults to auto and may differ from translation.")
    parser.add_argument("--qc-base-url", default="", help="QC chat API base URL. Defaults to translate_base_url when omitted in workflow usage.")
    parser.add_argument("--qc-model", default="")
    parser.add_argument("--qc-model-class", default="")
    parser.add_argument("--qc-behavior-probe-required", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--qc-require-non-thinking", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--output-format", default="vtt", choices=sorted(OUTPUT_FORMATS))
    parser.add_argument("--translate-chunk-size", type=int, default=9)
    parser.add_argument("--qc-chunk-size", type=int, default=18)
    parser.add_argument("--readability-max-cps", type=float, default=10.0)
    parser.add_argument("--script-compare-report", default="")
    parser.add_argument("--validate-report", default="")
    parser.add_argument("--risk-report", default="")
    parser.add_argument("--readability-report", default="")
    parser.add_argument("--qc-report", default="")
    parser.add_argument("--qc-review", default="")
    parser.add_argument("--qc-review-items", default="")
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing project_config.json.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and inspect ASMR subtitle project configuration records.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create project_config.json.")
    add_common_init_args(init_parser)

    show_parser = subparsers.add_parser("show", help="Show an existing project_config.json summary.")
    show_parser.add_argument("project_root", help="Project output root or a project_config.json path.")
    show_parser.add_argument("--json", action="store_true", help="Print full JSON instead of a summary.")

    args = parser.parse_args()

    if args.command == "init":
        root = Path(args.project_root)
        path = config_path(root)
        existing = read_config(path) if path.exists() else None
        if existing and not args.overwrite:
            raise SystemExit(f"Config exists: {path}; pass --overwrite to replace it.")
        data = build_config(args, existing)
        write_config(path, data)
        print(path.as_posix())
        return 0

    show_target = Path(args.project_root)
    path = show_target if show_target.name == CONFIG_NAME else config_path(show_target)
    data = read_config(path)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_config_summary(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
