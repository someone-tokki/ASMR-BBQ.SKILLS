#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

from subtitle_io import Subtitle, compose_srt_text, parse_srt_text


OUTPUT_FORMATS = {"vtt", "srt", "both"}


def vtt_time(value: timedelta) -> str:
    total_ms = int(round(value.total_seconds() * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


def compose_vtt(subtitles: list[Subtitle]) -> str:
    lines = ["WEBVTT", ""]
    for subtitle in subtitles:
        lines.append(f"{vtt_time(subtitle.start)} --> {vtt_time(subtitle.end)}")
        lines.extend(subtitle.content.splitlines())
        lines.append("")
    return "\n".join(lines)


def rel(path: Path, base: Path) -> Path:
    try:
        return path.relative_to(base)
    except ValueError:
        return Path(path.name)


def output_paths(input_path: Path, input_root: Path, output_dir: Path, output_format: str) -> list[Path]:
    relative = rel(input_path, input_root)
    paths: list[Path] = []
    if output_format in {"srt", "both"}:
        paths.append(output_dir / relative)
    if output_format in {"vtt", "both"}:
        paths.append(output_dir / relative.with_suffix(".vtt"))
    return paths


def collect_inputs(input_path: Path, pattern: str, recursive: bool) -> tuple[list[Path], Path]:
    if input_path.is_dir():
        glob_pattern = f"**/{pattern}" if recursive else pattern
        files = sorted(path for path in input_path.glob(glob_pattern) if path.is_file())
        if not files:
            raise SystemExit(f"No SRT files matched {glob_pattern!r} in {input_path}")
        return files, input_path
    if not input_path.exists():
        raise SystemExit(f"Input does not exist: {input_path}")
    if input_path.suffix.lower() != ".srt":
        raise SystemExit(f"Input must be an .srt file or directory: {input_path}")
    return [input_path], input_path.parent


def export_file(input_path: Path, input_root: Path, output_dir: Path, output_format: str, overwrite: bool) -> list[dict]:
    subtitles = parse_srt_text(input_path.read_text(encoding="utf-8"))
    written: list[dict] = []
    for output_path in output_paths(input_path, input_root, output_dir, output_format):
        if output_path.exists() and not overwrite:
            written.append({"input": input_path.as_posix(), "output": output_path.as_posix(), "status": "skipped_exists"})
            continue
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".vtt":
            output_path.write_text(compose_vtt(subtitles), encoding="utf-8")
        else:
            output_path.write_text(compose_srt_text(subtitles), encoding="utf-8")
        written.append({"input": input_path.as_posix(), "output": output_path.as_posix(), "status": "wrote"})
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Export final ASMR subtitles from reviewed .zh.srt work files.")
    parser.add_argument("input", help="Input .srt file or directory, normally $ZH_SRT_DIR.")
    parser.add_argument("output_dir", help="Final subtitle directory, normally $FINAL_SUBTITLE_DIR.")
    parser.add_argument("--format", default="vtt", choices=sorted(OUTPUT_FORMATS), help="Final output format.")
    parser.add_argument("--glob", default="*.zh.srt", help="Glob used when input is a directory.")
    parser.add_argument("--recursive", action="store_true", help="Search input directory recursively.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing final subtitle files.")
    parser.add_argument("--json-out", help="Write a JSON export report.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    input_files, input_root = collect_inputs(input_path, args.glob, args.recursive)

    results: list[dict] = []
    for srt_path in input_files:
        results.extend(export_file(srt_path, input_root, output_dir, args.format, args.overwrite))

    for item in results:
        print(f"{item['status'].upper()} {item['output']}")

    report = {
        "input": input_path.as_posix(),
        "output_dir": output_dir.as_posix(),
        "format": args.format,
        "count": len(results),
        "results": results,
    }
    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"WROTE {json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
