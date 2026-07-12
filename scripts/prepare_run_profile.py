#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROFILE_NAME = "run_profile.json"
QUALITY_MODES = {"draft", "standard", "premium", "polish"}
OUTPUT_FORMATS = {"vtt", "srt", "both"}
CHUNK_PRESETS = {"safe", "fast", "turbo"}
QC_TIERS = {"off", "light", "standard", "deep", "two-pass"}
CONFIRMATION_SOURCES = {"explicit_user", "user_default_authorized", "imported_existing"}
WAV_ONLY_ASR_STRATEGIES = {"not_applicable", "mp3_cache", "original_wav"}


MODE_DEFAULTS = {
    "draft": {"chunk_preset": "turbo", "qc_tier": "off", "learning_loop": False},
    "standard": {"chunk_preset": "fast", "qc_tier": "two-pass", "learning_loop": True},
    "premium": {"chunk_preset": "safe", "qc_tier": "two-pass", "learning_loop": True},
    "polish": {"chunk_preset": "safe", "qc_tier": "two-pass", "learning_loop": True},
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def profile_path(project_root: Path) -> Path:
    return project_root / PROFILE_NAME


def split_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                result.append(part)
    return result


def stage(backend: str, base_url: str, model: str, *, reuse_existing: bool | None = None, tier: str = "") -> dict[str, Any]:
    data: dict[str, Any] = {"backend": backend, "base_url": base_url, "model": model}
    if reuse_existing is not None:
        data["reuse_existing"] = reuse_existing
    if tier:
        data["tier"] = tier
    return data


def missing_fields(profile: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in ("quality_mode", "output_format", "scope"):
        if not profile.get(key):
            missing.append(key)
    if profile.get("scope") == "ask":
        missing.append("scope_confirmation")
    if profile.get("scope") in {"selected_dirs", "selected_files"}:
        if profile.get("scope") == "selected_dirs" and not profile.get("selected_audio_dirs"):
            missing.append("selected_audio_dirs")
        if profile.get("scope") == "selected_files" and not profile.get("selected_audio_files"):
            missing.append("selected_audio_files")
    if profile.get("scope") == "all" and not (
        profile.get("audio_scope_summary")
        or profile.get("audio_scope_report")
        or profile.get("preflight_questions_presented") is True
    ):
        missing.append("audio_scope_summary_or_report")
    if profile.get("confirmed"):
        if profile.get("confirmation_source") not in CONFIRMATION_SOURCES:
            missing.append("confirmation_source")
        if profile.get("confirmation_source") == "user_default_authorized" and not profile.get("confirmation_text"):
            missing.append("confirmation_text")
        if profile.get("preflight_questions_presented") is not True:
            missing.append("preflight_questions_presented")
    preparation = profile.get("asr_audio_preparation", {})
    if preparation.get("wav_only_choice_required") is True:
        if preparation.get("wav_only_strategy") not in {"mp3_cache", "original_wav"}:
            missing.append("asr_audio_preparation.wav_only_strategy")
        if not preparation.get("wav_only_report"):
            missing.append("asr_audio_preparation.wav_only_report")
    stages = profile.get("stages", {})
    for name in ("asr", "translate", "qc"):
        current = stages.get(name, {})
        if not current.get("backend"):
            missing.append(f"{name}.backend")
        if not current.get("model"):
            missing.append(f"{name}.model")
        if name in {"translate", "qc"} and current.get("backend") not in {"none", "off"} and not current.get("base_url"):
            missing.append(f"{name}.base_url")
    return missing


def build_profile(args: argparse.Namespace, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    created_at = existing.get("created_at") if existing else now_utc()
    mode_defaults = MODE_DEFAULTS[args.quality_mode]
    qc_tier = args.qc_tier or mode_defaults["qc_tier"]
    chunk_preset = args.chunk_preset or mode_defaults["chunk_preset"]
    profile: dict[str, Any] = {
        "version": 1,
        "created_at": created_at,
        "updated_at": now_utc(),
        "confirmed": bool(args.confirmed),
        "needs_user_confirmation": not bool(args.confirmed),
        "confirmation_source": args.confirmation_source,
        "confirmation_text": args.confirmation_text,
        "confirmed_at": now_utc() if args.confirmed else "",
        "confirmed_by": (
            "agent_with_user_default_authorization"
            if args.confirmation_source == "user_default_authorized"
            else ("user" if args.confirmed else "")
        ),
        "preflight_questions_presented": bool(args.preflight_questions_presented),
        "audio_scope_summary": args.audio_scope_summary,
        "audio_scope_report": args.audio_scope_report,
        "quality_mode": args.quality_mode,
        "scope": args.scope,
        "selected_audio_dirs": split_values(args.selected_audio_dir),
        "selected_audio_files": split_values(args.selected_audio_file),
        "asr_audio_preparation": {
            "wav_only_choice_required": bool(args.wav_only_asr_required),
            "wav_only_strategy": args.wav_only_asr_strategy,
            "wav_only_report": args.wav_only_asr_report,
            "wav_only_tracks": split_values(args.wav_only_asr_track),
        },
        "output_format": args.output_format,
        "chunk_preset": chunk_preset,
        "learning_loop": bool(mode_defaults["learning_loop"]),
        "profile_paths": {
            "project_config": (Path(args.project_root) / "project_config.json").as_posix(),
            "model_profile": (Path(args.project_root) / "model_profile.json").as_posix(),
        },
        "stages": {
            "asr": stage(
                args.asr_backend,
                args.asr_base_url,
                args.asr_model,
                reuse_existing=args.reuse_existing_asr,
            ),
            "translate": stage(args.translate_backend, args.translate_base_url, args.translate_model),
            "qc": stage(args.qc_backend, args.qc_base_url, args.qc_model, tier=qc_tier),
        },
        "notes": split_values(args.note),
    }
    profile["missing"] = missing_fields(profile)
    if profile["missing"]:
        profile["confirmed"] = False
        profile["needs_user_confirmation"] = True
    return profile


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a confirmed or proposed ASMR subtitle run_profile.json.")
    parser.add_argument("project_root")
    parser.add_argument("--quality-mode", default="standard", choices=sorted(QUALITY_MODES))
    parser.add_argument("--scope", default="ask", choices=["ask", "all", "selected_dirs", "selected_files"])
    parser.add_argument("--selected-audio-dir", action="append", default=[])
    parser.add_argument("--selected-audio-file", action="append", default=[])
    parser.add_argument("--output-format", default="vtt", choices=sorted(OUTPUT_FORMATS))
    parser.add_argument("--chunk-preset", default="", choices=["", *sorted(CHUNK_PRESETS)])
    parser.add_argument("--qc-tier", default="", choices=["", *sorted(QC_TIERS)])
    parser.add_argument("--asr-backend", default="auto")
    parser.add_argument("--asr-base-url", default="")
    parser.add_argument("--asr-model", default="large-v3")
    parser.add_argument("--reuse-existing-asr", action="store_true")
    parser.add_argument("--translate-backend", default="auto")
    parser.add_argument("--translate-base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--translate-model", default="Qwen2.5-32B-Instruct-GGUF-Q4_K_M")
    parser.add_argument("--qc-backend", default="auto")
    parser.add_argument("--qc-base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--qc-model", default="Qwen2.5-32B-Instruct-GGUF-Q4_K_M")
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--confirmation-source", default="", choices=["", *sorted(CONFIRMATION_SOURCES)])
    parser.add_argument("--confirmation-text", default="", help="User confirmation text or concise summary.")
    parser.add_argument("--preflight-questions-presented", action="store_true")
    parser.add_argument("--audio-scope-summary", default="")
    parser.add_argument("--audio-scope-report", default="")
    parser.add_argument("--wav-only-asr-required", action="store_true", help="Set only when the selected ASR-input report found WAV-only tracks.")
    parser.add_argument("--wav-only-asr-strategy", choices=sorted(WAV_ONLY_ASR_STRATEGIES), default="not_applicable")
    parser.add_argument("--wav-only-asr-report", default="")
    parser.add_argument("--wav-only-asr-track", action="append", default=[])
    parser.add_argument(
        "--assume-defaults-authorized",
        action="store_true",
        help="Use only when the user explicitly authorized defaults; sets confirmation_source=user_default_authorized.",
    )
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.assume_defaults_authorized and not args.confirmation_source:
        args.confirmation_source = "user_default_authorized"
    if args.confirmed and not args.confirmation_source:
        raise SystemExit(
            "--confirmed now requires --confirmation-source. Use explicit_user, user_default_authorized, or imported_existing."
        )
    if args.wav_only_asr_required and args.wav_only_asr_strategy == "not_applicable":
        raise SystemExit("--wav-only-asr-required requires --wav-only-asr-strategy mp3_cache or original_wav.")

    root = Path(args.project_root)
    path = profile_path(root)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if existing and not args.overwrite:
        raise SystemExit(f"Run profile exists: {path}; pass --overwrite to replace it.")
    profile = build_profile(args, existing)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path.as_posix())
    if profile["needs_user_confirmation"]:
        print("NEEDS_USER_CONFIRMATION")
        if profile["missing"]:
            print("missing: " + ", ".join(profile["missing"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
