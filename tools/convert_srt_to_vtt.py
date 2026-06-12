#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

import srt


def vtt_time(value: timedelta) -> str:
    total_ms = int(round(value.total_seconds() * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


def compose_vtt(subtitles: list[srt.Subtitle]) -> str:
    lines = ["WEBVTT", ""]
    for subtitle in subtitles:
        lines.append(f"{vtt_time(subtitle.start)} --> {vtt_time(subtitle.end)}")
        lines.extend(subtitle.content.splitlines())
        lines.append("")
    return "\n".join(lines)


def convert_file(input_path: Path, output_path: Path) -> None:
    subtitles = list(srt.parse(input_path.read_text(encoding="utf-8")))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(compose_vtt(subtitles), encoding="utf-8")


def output_for(input_path: Path, input_dir: Path, output_dir: Path) -> Path:
    relative = input_path.relative_to(input_dir)
    return output_dir / relative.with_suffix(".vtt")


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert SRT subtitles to WebVTT.")
    parser.add_argument("input", help="Input .srt file or directory.")
    parser.add_argument("output", help="Output .vtt file or directory.")
    parser.add_argument("--glob", default="*.srt", help="Glob used when input is a directory.")
    parser.add_argument("--recursive", action="store_true", help="Search input directory recursively.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing .vtt files.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if input_path.is_dir():
        pattern = f"**/{args.glob}" if args.recursive else args.glob
        input_files = sorted(input_path.glob(pattern))
        if not input_files:
            raise SystemExit(f"No SRT files matched {pattern!r} in {input_path}")
        for srt_path in input_files:
            vtt_path = output_for(srt_path, input_path, output_path)
            if vtt_path.exists() and not args.overwrite:
                print(f"SKIP_EXISTING {vtt_path}")
                continue
            convert_file(srt_path, vtt_path)
            print(f"WROTE {vtt_path}")
        return 0

    if not args.overwrite and output_path.exists():
        raise SystemExit(f"Output exists: {output_path}; pass --overwrite to replace it.")
    convert_file(input_path, output_path)
    print(f"WROTE {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
