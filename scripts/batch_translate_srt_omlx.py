#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tqdm import tqdm


PRESET_DEFAULTS = {
    "safe": {
        "chunk_size": "12",
        "chunk_mode": "dynamic",
        "min_chunk_size": "6",
        "max_chunk_size": "24",
        "target_chars": "900",
        "hard_chars": "1300",
        "context_before": "3",
        "context_after": "3",
    },
    "fast": {
        "chunk_size": "18",
        "chunk_mode": "dynamic",
        "min_chunk_size": "8",
        "max_chunk_size": "32",
        "target_chars": "1400",
        "hard_chars": "2200",
        "context_before": "2",
        "context_after": "2",
    },
    "turbo": {
        "chunk_size": "24",
        "chunk_mode": "dynamic",
        "min_chunk_size": "10",
        "max_chunk_size": "40",
        "target_chars": "1800",
        "hard_chars": "2600",
        "context_before": "1",
        "context_after": "1",
    },
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def apply_preset(args: argparse.Namespace) -> None:
    preset = PRESET_DEFAULTS[args.preset]
    for key, value in preset.items():
        if getattr(args, key) is None:
            setattr(args, key, value)


def build_command(args: argparse.Namespace, input_srt: Path, output_srt: Path, position: int) -> list[str]:
    command = [
        sys.executable,
        args.script,
        str(input_srt),
        str(output_srt),
        "--api-key",
        args.api_key,
        "--preset",
        args.preset,
        "--chunk-size",
        args.chunk_size,
        "--progress-position",
        str(position),
    ]
    optional_pairs = [
        ("model", "--model"),
        ("base_url", "--base-url"),
        ("chunk_mode", "--chunk-mode"),
        ("min_chunk_size", "--min-chunk-size"),
        ("max_chunk_size", "--max-chunk-size"),
        ("target_chars", "--target-chars"),
        ("hard_chars", "--hard-chars"),
        ("context_before", "--context-before"),
        ("context_after", "--context-after"),
        ("timeout", "--timeout"),
        ("sleep", "--sleep"),
    ]
    for attr, flag in optional_pairs:
        value = getattr(args, attr)
        if value:
            command.extend([flag, str(value)])
    if args.no_resume:
        command.append("--no-resume")
    if args.force:
        command.append("--force")
    if args.plan_only:
        command.append("--plan-only")
    return command


def translate_one(args: argparse.Namespace, input_srt: Path, output_dir: Path, position: int) -> dict[str, Any]:
    started = time.monotonic()
    output_srt = output_dir / input_srt.name.replace(".ja.asr.srt", ".zh.srt")
    partial_srt = output_srt.with_suffix(output_srt.suffix + ".partial.json")
    if output_srt.exists() and not partial_srt.exists() and not args.force:
        return {
            "input": input_srt.as_posix(),
            "output": output_srt.as_posix(),
            "status": "skipped",
            "duration_sec": 0.0,
        }
    command = build_command(args, input_srt, output_srt, position)
    subprocess.run(command, check=True)
    return {
        "input": input_srt.as_posix(),
        "output": output_srt.as_posix(),
        "status": "success",
        "duration_sec": time.monotonic() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--preset", default="fast", choices=sorted(PRESET_DEFAULTS))
    parser.add_argument("--chunk-size", default=None)
    parser.add_argument("--chunk-mode", default=None)
    parser.add_argument("--min-chunk-size", default=None)
    parser.add_argument("--max-chunk-size", default=None)
    parser.add_argument("--target-chars", default=None)
    parser.add_argument("--hard-chars", default=None)
    parser.add_argument("--context-before", default=None)
    parser.add_argument("--context-after", default=None)
    parser.add_argument("--timeout", default=None)
    parser.add_argument("--sleep", default=None)
    parser.add_argument("--workers", type=int, default=1, help="Translate multiple files concurrently. Keep 1 for most local 27B runs.")
    parser.add_argument("--profile", default="", help="Write batch translation timing profile JSON.")
    parser.add_argument("--no-resume", action="store_true", help="Pass --no-resume to translate_srt_omlx.py.")
    parser.add_argument("--force", action="store_true", help="Rerun files/chunks even if outputs or caches exist.")
    parser.add_argument("--plan-only", action="store_true", help="Build per-file translation manifests without calling the model.")
    parser.add_argument("--script", default=str(Path(__file__).with_name("translate_srt_omlx.py")))
    args = parser.parse_args()
    apply_preset(args)

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_srts = sorted(input_dir.glob("*.ja.asr.srt"))
    started = time.monotonic()
    records: list[dict[str, Any]] = []

    with tqdm(
        total=len(input_srts),
        desc="batch translate",
        unit="file",
        dynamic_ncols=True,
        bar_format="{l_bar}{bar:32}| {n_fmt}/{total_fmt} {unit} [{elapsed}<{remaining}, {rate_fmt}] {postfix}",
        position=0,
    ) as progress:
        if args.workers <= 1:
            for input_srt in input_srts:
                progress.set_postfix_str(input_srt.name)
                progress.write(f"BATCH_TRANSLATE {input_srt.name}")
                record = translate_one(args, input_srt, output_dir, 1)
                if record["status"] == "skipped":
                    progress.write(f"SKIP_EXISTING {Path(record['output']).name}")
                records.append(record)
                progress.update(1)
        else:
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(translate_one, args, input_srt, output_dir, 1 + (index % args.workers)): input_srt
                    for index, input_srt in enumerate(input_srts)
                }
                for future in as_completed(futures):
                    input_srt = futures[future]
                    progress.set_postfix_str(input_srt.name)
                    record = future.result()
                    records.append(record)
                    progress.write(f"{record['status'].upper()} {input_srt.name}")
                    progress.update(1)

    if args.profile:
        profile = {
            "version": 1,
            "stage": "batch_translate",
            "input_dir": input_dir.as_posix(),
            "output_dir": output_dir.as_posix(),
            "duration_sec": time.monotonic() - started,
            "files": len(input_srts),
            "workers": args.workers,
            "preset": args.preset,
            "settings": {
                "chunk_mode": args.chunk_mode,
                "chunk_size": args.chunk_size,
                "min_chunk_size": args.min_chunk_size,
                "max_chunk_size": args.max_chunk_size,
                "target_chars": args.target_chars,
                "hard_chars": args.hard_chars,
                "context_before": args.context_before,
                "context_after": args.context_after,
                "model": args.model,
                "base_url": args.base_url,
            },
            "records": records,
            "updated_at": now_utc(),
        }
        profile_path = Path(args.profile)
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
