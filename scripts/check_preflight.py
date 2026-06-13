#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


MODEL_STAGES = {"asr", "translate", "qc"}


def load_profile(project_root: Path) -> dict[str, Any]:
    path = project_root / "run_profile.json"
    if not path.exists():
        raise SystemExit(
            "Preflight confirmation missing: run_profile.json not found. "
            "The agent must ask the user to confirm ASR/translation/QC models, quality mode, scope, and output format before running."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate(profile: dict[str, Any], stage: str) -> list[str]:
    errors: list[str] = []
    require(profile.get("confirmed") is True, "run_profile.json is not confirmed", errors)
    require(profile.get("quality_mode") in {"draft", "standard", "premium", "polish"}, "quality_mode is missing or invalid", errors)
    require(profile.get("output_format") in {"vtt", "srt", "both"}, "output_format is missing or invalid", errors)
    require(profile.get("scope") in {"all", "selected_dirs", "selected_files"}, "scope must be confirmed as all, selected_dirs, or selected_files", errors)
    if profile.get("scope") == "selected_dirs":
        require(bool(profile.get("selected_audio_dirs")), "selected_audio_dirs is required for selected_dirs scope", errors)
    if profile.get("scope") == "selected_files":
        require(bool(profile.get("selected_audio_files")), "selected_audio_files is required for selected_files scope", errors)
    stages = profile.get("stages", {}) if isinstance(profile.get("stages"), dict) else {}
    names = MODEL_STAGES if stage == "all" else {stage}
    for name in names:
        current = stages.get(name, {}) if isinstance(stages.get(name), dict) else {}
        require(bool(current.get("backend")), f"{name}.backend is missing", errors)
        require(bool(current.get("model")), f"{name}.model is missing", errors)
        if name in {"translate", "qc"} and current.get("backend") not in {"none", "off"}:
            require(bool(current.get("base_url")), f"{name}.base_url is missing", errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Hard gate before ASMR subtitle model calls.")
    parser.add_argument("project_root")
    parser.add_argument("--stage", default="all", choices=["all", "asr", "translate", "qc"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    profile = load_profile(Path(args.project_root))
    errors = validate(profile, args.stage)
    result = {"ok": not errors, "stage": args.stage, "errors": errors}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("Preflight confirmation invalid.")
        for error in errors:
            print(f"- {error}")
    else:
        print(f"Preflight OK for {args.stage}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
