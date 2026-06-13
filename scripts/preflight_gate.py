from __future__ import annotations

import argparse
from pathlib import Path

from check_preflight import load_profile, validate


def add_preflight_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", default="", help="Project root containing confirmed run_profile.json.")
    parser.add_argument(
        "--require-preflight",
        action="store_true",
        help="Require confirmed run_profile.json even when --project-root is omitted.",
    )
    parser.add_argument("--no-preflight-check", action="store_true", help="Skip preflight gate for ad-hoc debugging.")


def enforce_preflight(args: argparse.Namespace, stage: str) -> None:
    if args.no_preflight_check:
        return
    if not args.project_root:
        if args.require_preflight:
            raise SystemExit(
                f"Preflight gate requires --project-root for {stage}. "
                "Ask the user the mandatory Preflight questions and write run_profile.json first."
            )
        return
    profile = load_profile(Path(args.project_root))
    errors = validate(profile, stage)
    if errors:
        message = [
            f"Preflight gate blocked {stage}. Ask the user the mandatory Preflight questions, "
            "write a confirmed run_profile.json, then retry.",
        ]
        message.extend(f"- {error}" for error in errors)
        raise SystemExit("\n".join(message))
