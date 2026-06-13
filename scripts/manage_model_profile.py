#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROFILE_NAME = "model_profile.json"
PROFILE_VERSION = 1
STAGES = ("asr", "translate", "qc")
DEFAULT_PROFILE = {
    "profile_version": PROFILE_VERSION,
    "description": "User-editable stage model preferences for ASMR subtitle work. No API keys or secrets.",
    "defaults": {
        "local_chat_base_url": "http://127.0.0.1:8000/v1",
        "asr_base_url": "",
        "asr_model": "large-v3",
        "translate_model": "qwen3.6-27b",
        "qc_model": "qwen3.6-27b",
    },
    "stages": {
        "asr": {
            "backend": "auto",
            "base_url": "",
            "model": "large-v3",
            "interface": "/audio/transcriptions",
            "notes": "Use a Whisper-class model. Auto probes local platform ASR first, then fallbacks.",
        },
        "translate": {
            "backend": "auto",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "qwen3.6-27b",
            "interface": "/chat/completions",
            "notes": "Use a chat model suitable for Japanese-to-Chinese ASMR translation.",
        },
        "qc": {
            "backend": "auto",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "qwen3.6-27b",
            "interface": "/chat/completions",
            "notes": "Can be a faster chat model for light QC or a stronger model for deep QC.",
        },
    },
    "stage_overrides": [],
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def profile_path(project_root: Path) -> Path:
    if project_root.name == PROFILE_NAME:
        return project_root
    return project_root / PROFILE_NAME


def config_path(project_root: Path) -> Path:
    if project_root.name == "project_config.json":
        return project_root
    return project_root / "project_config.json"


def run_profile_path(project_root: Path) -> Path:
    if project_root.name == "run_profile.json":
        return project_root
    return project_root / "run_profile.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def deep_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def load_profile(project_root: Path) -> dict[str, Any]:
    path = profile_path(project_root)
    if path.exists():
        return read_json(path)
    return deep_copy(DEFAULT_PROFILE)


def merge_project_config(profile: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    models = config.get("models", {}) if isinstance(config.get("models"), dict) else {}
    stages = profile.setdefault("stages", {})
    if models.get("asr_backend"):
        stages.setdefault("asr", {})["backend"] = models.get("asr_backend")
    if models.get("asr_base_url"):
        stages.setdefault("asr", {})["base_url"] = models.get("asr_base_url")
    if models.get("asr_model"):
        stages.setdefault("asr", {})["model"] = models.get("asr_model")
    if models.get("translate_backend"):
        stages.setdefault("translate", {})["backend"] = models.get("translate_backend")
    if models.get("translate_base_url"):
        stages.setdefault("translate", {})["base_url"] = models.get("translate_base_url")
        stages.setdefault("qc", {})["base_url"] = models.get("translate_base_url")
    if models.get("translate_model"):
        stages.setdefault("translate", {})["model"] = models.get("translate_model")
    if models.get("qc_base_url"):
        stages.setdefault("qc", {})["base_url"] = models.get("qc_base_url")
    if models.get("qc_backend"):
        stages.setdefault("qc", {})["backend"] = models.get("qc_backend")
    if models.get("qc_model"):
        stages.setdefault("qc", {})["model"] = models.get("qc_model")
    return profile


def merge_run_profile(profile: dict[str, Any], run_profile: dict[str, Any]) -> dict[str, Any]:
    stages = run_profile.get("stages", {}) if isinstance(run_profile.get("stages"), dict) else {}
    target = profile.setdefault("stages", {})
    for stage_name in STAGES:
        source = stages.get(stage_name, {}) if isinstance(stages.get(stage_name), dict) else {}
        if not source:
            continue
        stage_data = target.setdefault(stage_name, {})
        for key in ("backend", "base_url", "model"):
            value = source.get(key)
            if value:
                stage_data[key] = value
        if stage_name == "asr":
            stage_data.setdefault("interface", "/audio/transcriptions")
        else:
            stage_data.setdefault("interface", "/chat/completions")
    profile["updated_at"] = now_utc()
    profile.setdefault("stage_overrides", []).append(
        {
            "source": "run_profile.json",
            "quality_mode": run_profile.get("quality_mode", ""),
            "scope": run_profile.get("scope", ""),
            "output_format": run_profile.get("output_format", ""),
            "updated_at": now_utc(),
        }
    )
    return profile


def resolve_stage(profile: dict[str, Any], stage: str) -> dict[str, Any]:
    if stage not in STAGES:
        raise SystemExit(f"Unknown stage: {stage}")
    defaults = profile.get("defaults", {}) if isinstance(profile.get("defaults"), dict) else {}
    stages = profile.get("stages", {}) if isinstance(profile.get("stages"), dict) else {}
    data = stages.get(stage, {}) if isinstance(stages.get(stage), dict) else {}
    result = {
        "stage": stage,
        "backend": str(data.get("backend") or "auto"),
        "base_url": str(data.get("base_url") or ""),
        "model": str(data.get("model") or ""),
        "interface": str(data.get("interface") or ""),
        "notes": str(data.get("notes") or ""),
    }
    if stage == "asr":
        result["model"] = result["model"] or str(defaults.get("asr_model") or "large-v3")
        result["base_url"] = result["base_url"] or str(defaults.get("asr_base_url") or "")
        result["interface"] = result["interface"] or "/audio/transcriptions"
    elif stage == "translate":
        result["model"] = result["model"] or str(defaults.get("translate_model") or "")
        result["base_url"] = result["base_url"] or str(defaults.get("local_chat_base_url") or "")
        result["interface"] = result["interface"] or "/chat/completions"
    else:
        result["model"] = result["model"] or str(defaults.get("qc_model") or defaults.get("translate_model") or "")
        result["base_url"] = result["base_url"] or str(defaults.get("local_chat_base_url") or "")
        result["interface"] = result["interface"] or "/chat/completions"
    return result


def print_shell(stage: dict[str, Any]) -> None:
    prefix = stage["stage"].upper()
    print(f"{prefix}_BACKEND={stage['backend']}")
    if stage.get("base_url"):
        print(f"{prefix}_BASE_URL={stage['base_url']}")
    print(f"{prefix}_MODEL={stage['model']}")
    print(f"{prefix}_INTERFACE={stage['interface']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage user-editable stage model preferences for ASMR subtitle projects.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create model_profile.json.")
    init.add_argument("project_root")
    init.add_argument("--from-config", action="store_true", help="Seed profile from project_config.json when present.")
    init.add_argument("--overwrite", action="store_true")

    show = subparsers.add_parser("show", help="Show model_profile.json.")
    show.add_argument("project_root")

    set_stage = subparsers.add_parser("set-stage", help="Update one stage in model_profile.json.")
    set_stage.add_argument("project_root")
    set_stage.add_argument("stage", choices=STAGES)
    set_stage.add_argument("--backend")
    set_stage.add_argument("--base-url")
    set_stage.add_argument("--model")
    set_stage.add_argument("--interface")
    set_stage.add_argument("--notes")

    resolve = subparsers.add_parser("resolve", help="Resolve effective backend/base_url/model for a stage.")
    resolve.add_argument("project_root")
    resolve.add_argument("stage", choices=STAGES)
    resolve.add_argument("--json", action="store_true")
    resolve.add_argument("--from-config", action="store_true", help="Let project_config.json override missing/profile values.")

    sync_run = subparsers.add_parser("sync-run-profile", help="Sync stage backend/base_url/model from run_profile.json.")
    sync_run.add_argument("project_root")
    sync_run.add_argument("--run-profile", default="", help="Defaults to <project_root>/run_profile.json.")

    args = parser.parse_args()
    root = Path(args.project_root)

    if args.command == "init":
        path = profile_path(root)
        if path.exists() and not args.overwrite:
            raise SystemExit(f"Profile exists: {path}; pass --overwrite to replace it.")
        profile = deep_copy(DEFAULT_PROFILE)
        if args.from_config and config_path(root).exists():
            profile = merge_project_config(profile, read_json(config_path(root)))
        profile["created_at"] = now_utc()
        profile["updated_at"] = now_utc()
        write_json(path, profile)
        print(path.as_posix())
        return 0

    if args.command == "show":
        print(json.dumps(load_profile(root), ensure_ascii=False, indent=2))
        return 0

    if args.command == "sync-run-profile":
        path = profile_path(root)
        profile = load_profile(root)
        run_path = Path(args.run_profile) if args.run_profile else run_profile_path(root)
        run_profile = read_json(run_path)
        if run_profile.get("confirmed") is not True:
            raise SystemExit(f"Run profile is not confirmed: {run_path}")
        profile = merge_run_profile(profile, run_profile)
        write_json(path, profile)
        print(path.as_posix())
        return 0

    if args.command == "set-stage":
        path = profile_path(root)
        profile = load_profile(root)
        stage_data = profile.setdefault("stages", {}).setdefault(args.stage, {})
        for arg_name, key in [
            ("backend", "backend"),
            ("base_url", "base_url"),
            ("model", "model"),
            ("interface", "interface"),
            ("notes", "notes"),
        ]:
            value = getattr(args, arg_name)
            if value is not None:
                stage_data[key] = value
        profile["updated_at"] = now_utc()
        write_json(path, profile)
        print(path.as_posix())
        return 0

    profile = load_profile(root)
    if args.from_config and config_path(root).exists():
        profile = merge_project_config(profile, read_json(config_path(root)))
    stage = resolve_stage(profile, args.stage)
    if args.json:
        print(json.dumps(stage, ensure_ascii=False, indent=2))
    else:
        print_shell(stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
