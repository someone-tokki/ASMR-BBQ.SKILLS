#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PROFILES = {
    "fast_small_non_reasoning": {
        "translate": {
            "preset": "safe",
            "chunk_mode": "dynamic",
            "target_chars": 900,
            "hard_chars": 1300,
            "min_chunk_size": 6,
            "max_chunk_size": 20,
            "context_before": 3,
            "context_after": 3,
            "workers": 1,
        },
        "qc": {
            "qc_tier": "two-pass",
            "light_target_chars": 1800,
            "light_hard_chars": 2600,
            "deep_target_chars": 700,
            "deep_hard_chars": 1100,
            "context_halo": 3,
        },
    },
    "balanced_non_reasoning": {
        "translate": {
            "preset": "fast",
            "chunk_mode": "dynamic",
            "target_chars": 1400,
            "hard_chars": 2200,
            "min_chunk_size": 8,
            "max_chunk_size": 32,
            "context_before": 2,
            "context_after": 2,
            "workers": 1,
        },
        "qc": {
            "qc_tier": "two-pass",
            "light_target_chars": 2200,
            "light_hard_chars": 3200,
            "deep_target_chars": 900,
            "deep_hard_chars": 1400,
            "context_halo": 3,
        },
    },
    "large_non_reasoning": {
        "translate": {
            "preset": "fast",
            "chunk_mode": "dynamic",
            "target_chars": 1200,
            "hard_chars": 1800,
            "min_chunk_size": 6,
            "max_chunk_size": 26,
            "context_before": 2,
            "context_after": 2,
            "workers": 1,
        },
        "qc": {
            "qc_tier": "two-pass",
            "light_target_chars": 1800,
            "light_hard_chars": 2600,
            "deep_target_chars": 800,
            "deep_hard_chars": 1300,
            "context_halo": 3,
        },
    },
    "reasoning_verified": {
        "translate": {
            "preset": "safe",
            "chunk_mode": "dynamic",
            "target_chars": 700,
            "hard_chars": 1100,
            "min_chunk_size": 4,
            "max_chunk_size": 16,
            "context_before": 2,
            "context_after": 2,
            "reasoning_token_budget": 6000,
            "workers": 1,
        },
        "qc": {
            "qc_tier": "deep",
            "target_chars": 600,
            "hard_chars": 1000,
            "context_halo": 2,
            "reasoning_token_budget": 6000,
        },
    },
    "reasoning_slow": {
        "translate": {
            "bulk_translation": False,
        },
        "qc": {
            "qc_tier": "deep",
            "target_chars": 350,
            "hard_chars": 650,
            "context_halo": 2,
            "reasoning_token_budget": 8000,
        },
    },
    "remote_api": {
        "translate": {
            "preset": "fast",
            "chunk_mode": "dynamic",
            "target_chars": 1800,
            "hard_chars": 2800,
            "min_chunk_size": 10,
            "max_chunk_size": 40,
            "context_before": 2,
            "context_after": 2,
            "workers": 2,
        },
        "qc": {
            "qc_tier": "two-pass",
            "light_target_chars": 2400,
            "light_hard_chars": 3400,
            "deep_target_chars": 1000,
            "deep_hard_chars": 1500,
            "context_halo": 3,
        },
    },
    "unknown": {
        "translate": {
            "preset": "safe",
            "require_behavior_probe": True,
            "target_chars": 800,
            "hard_chars": 1200,
            "min_chunk_size": 4,
            "max_chunk_size": 18,
            "context_before": 3,
            "context_after": 3,
        },
        "qc": {
            "qc_tier": "two-pass",
            "require_behavior_probe": True,
            "light_target_chars": 1600,
            "light_hard_chars": 2400,
            "deep_target_chars": 650,
            "deep_hard_chars": 1000,
            "context_halo": 3,
        },
    },
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def model_class_from_profile(profile: dict[str, Any], stage: str) -> str:
    stages = profile.get("stages", {}) if isinstance(profile.get("stages"), dict) else {}
    stage_data = stages.get(stage, {}) if isinstance(stages.get(stage), dict) else {}
    value = str(stage_data.get("model_class") or "").strip()
    return value or "unknown"


def load_profiles(path: Path | None) -> dict[str, Any]:
    if path and path.exists():
        data = read_json(path)
        profiles = data.get("profiles")
        if isinstance(profiles, dict):
            return profiles
    return DEFAULT_PROFILES


def resolve_profile(model_class: str, profiles: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
    notes: list[str] = []
    if model_class in profiles:
        return model_class, profiles[model_class], notes
    if model_class.startswith("reasoning"):
        notes.append("Model class looks reasoning-like; using reasoning_verified profile defaults.")
        return "reasoning_verified", profiles["reasoning_verified"], notes
    if model_class in {"non_reasoning_instruct", "balanced", "fast", "translation", "qc"}:
        notes.append("Model class is non-reasoning-like; using balanced_non_reasoning profile defaults.")
        return "balanced_non_reasoning", profiles["balanced_non_reasoning"], notes
    notes.append("Unknown model class; using conservative safe defaults and require model probe before bulk work.")
    return "unknown", profiles["unknown"], notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve model-aware chunk profiles for translation and QC.")
    parser.add_argument("project_root")
    parser.add_argument("stage", choices=["translate", "qc"])
    parser.add_argument("--model-stage-report", default="", help="Optional JSON report from prepare_model_stage.py.")
    parser.add_argument("--model-profile", default="", help="Optional explicit model_profile.json path. Defaults to <project_root>/model_profile.json.")
    parser.add_argument("--profile-file", default="", help="Defaults to data/model_chunk_profiles.json next to this script when present.")
    parser.add_argument("--config", default="", help="Optional project_config.json path.")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    root = Path(args.project_root)
    model_profile_path = Path(args.model_profile) if args.model_profile else root / "model_profile.json"
    profile: dict[str, Any] = read_json(model_profile_path) if model_profile_path.exists() else {}
    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            cfg = read_json(config_path)
            models = cfg.get("models", {}) if isinstance(cfg.get("models"), dict) else {}
            profile.setdefault("stages", {}).setdefault(args.stage, {})
            stage_data = profile["stages"][args.stage]
            if models.get(f"{args.stage}_model_class"):
                stage_data["model_class"] = models.get(f"{args.stage}_model_class")
    stage_data = profile.get("stages", {}).get(args.stage, {}) if isinstance(profile.get("stages"), dict) else {}
    model_class = str(stage_data.get("model_class") or "unknown")
    report: dict[str, Any] = {}
    if args.model_stage_report:
        report_path = Path(args.model_stage_report)
        if report_path.exists():
            report = read_json(report_path)
            model_class = str(report.get("target", {}).get("model_class") or model_class or "unknown")
            verdict = str(report.get("status") or "")
            if verdict == "FAIL":
                raise SystemExit(f"Model stage report is FAIL: {report_path}")
    profile_file = Path(args.profile_file) if args.profile_file else Path(__file__).resolve().parents[1] / "data" / "model_chunk_profiles.json"
    profiles = load_profiles(profile_file)
    resolved_class, defaults, notes = resolve_profile(model_class, profiles)
    result = {
        "schema_version": 1,
        "created_at": now_utc(),
        "stage": args.stage,
        "model_class": resolved_class,
        "source_model_class": model_class,
        "defaults": defaults,
        "profile_file": profile_file.as_posix() if profile_file.exists() else "builtin",
        "notes": notes,
        "model_stage_report": args.model_stage_report,
    }
    if args.json_out:
        write_json(Path(args.json_out), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
