#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from tqdm import tqdm


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--chunk-size", default="9")
    parser.add_argument("--timeout", default=None)
    parser.add_argument("--sleep", default=None)
    parser.add_argument("--script", default=str(Path(__file__).with_name("translate_srt_omlx.py")))
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_srts = sorted(input_dir.glob("*.ja.asr.srt"))

    with tqdm(
        total=len(input_srts),
        desc="batch translate",
        unit="file",
        dynamic_ncols=True,
        bar_format="{l_bar}{bar:32}| {n_fmt}/{total_fmt} {unit} [{elapsed}<{remaining}, {rate_fmt}] {postfix}",
        position=0,
    ) as progress:
        for input_srt in input_srts:
            output_srt = output_dir / input_srt.name.replace(".ja.asr.srt", ".zh.srt")
            partial_srt = output_srt.with_suffix(output_srt.suffix + ".partial.json")
            if output_srt.exists() and not partial_srt.exists():
                progress.set_postfix_str(f"skip {output_srt.name}")
                progress.write(f"SKIP_EXISTING {output_srt.name}")
                progress.update(1)
                continue
            progress.set_postfix_str(input_srt.name)
            progress.write(f"BATCH_TRANSLATE {input_srt.name}")
            command = [
                sys.executable,
                args.script,
                str(input_srt),
                str(output_srt),
                "--api-key",
                args.api_key,
                "--chunk-size",
                args.chunk_size,
                "--progress-position",
                "1",
            ]
            if args.model:
                command.extend(["--model", args.model])
            if args.base_url:
                command.extend(["--base-url", args.base_url])
            if args.timeout:
                command.extend(["--timeout", args.timeout])
            if args.sleep:
                command.extend(["--sleep", args.sleep])
            subprocess.run(command, check=True)
            progress.update(1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
