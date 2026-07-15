from __future__ import annotations

import argparse
from pathlib import Path

from check_preflight import load_profile, validate


def add_preflight_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project-root",
        required=True,
        help="Project root containing the confirmed run_profile.json. Required for every ASR, translation, and QC model call.",
    )


def enforce_preflight(args: argparse.Namespace, stage: str) -> None:
    profile = load_profile(Path(args.project_root))
    errors = validate(profile, stage)
    if errors:
        message = [
            f"Preflight gate blocked {stage}. Ask the user the mandatory Preflight questions, "
            "write a confirmed run_profile.json, then retry.",
        ]
        message.extend(f"- {error}" for error in errors)
        raise SystemExit("\n".join(message))
