#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Iterable

from subtitle_io import Subtitle, parse_srt_text


@dataclass
class WarningItem:
    path: str
    code: str
    message: str
    subtitle_index: int | None = None
    value: float | int | str | None = None
    threshold: float | int | str | None = None


SUPPORTED_SUFFIXES = {".srt", ".vtt"}
PUNCTUATION_RE = re.compile(r"[\s，。！？、,.!?…~～\-—「」『』“”\"'（）()\[\]【】：:；;♡♪]+")
REPEATED_CHAR_RE = re.compile(r"(.)\1{5,}")


def rel(path: Path) -> str:
    return path.as_posix()


def readable_length(text: str) -> int:
    return len(PUNCTUATION_RE.sub("", text))


def duration_seconds(subtitle: Subtitle) -> float:
    return max(0.001, (subtitle.end - subtitle.start).total_seconds())


def parse_srt_file(path: Path) -> tuple[list[Subtitle], list[WarningItem]]:
    try:
        return parse_srt_text(path.read_text(encoding="utf-8")), []
    except Exception as exc:
        return [], [WarningItem(rel(path), "parse_error", f"Could not parse SRT: {exc}")]


def vtt_timestamp_seconds(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"Invalid VTT timestamp: {value}")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_vtt_file(path: Path) -> tuple[list[Subtitle], list[WarningItem]]:
    warnings: list[WarningItem] = []
    subtitles: list[Subtitle] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    block: list[str] = []
    cue_index = 0
    for line in lines + [""]:
        if line.strip():
            block.append(line)
            continue
        if not block:
            continue
        timing = next((item for item in block if "-->" in item), None)
        if timing:
            try:
                start_text, end_text = [part.strip().split()[0] for part in timing.split("-->", 1)]
                start = timedelta(seconds=vtt_timestamp_seconds(start_text))
                end = timedelta(seconds=vtt_timestamp_seconds(end_text))
                text = "\n".join(item for item in block if item != timing and item.strip() != "WEBVTT")
                cue_index += 1
                subtitles.append(Subtitle(index=cue_index, start=start, end=end, content=text))
            except Exception as exc:
                warnings.append(WarningItem(rel(path), "parse_error", f"Could not parse VTT cue: {exc}"))
        block = []
    return subtitles, warnings


def iter_subtitle_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(child for child in sorted(path.rglob("*")) if child.suffix.lower() in SUPPORTED_SUFFIXES)
        elif path.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(path)
    return sorted(dict.fromkeys(files))


def load_subtitles(path: Path) -> tuple[list[Subtitle], list[WarningItem]]:
    if path.suffix.lower() == ".vtt":
        return parse_vtt_file(path)
    return parse_srt_file(path)


def check_subtitle(
    path: Path,
    subtitle: Subtitle,
    *,
    max_cps: float,
    max_chars: int,
    max_line_chars: int,
    max_lines: int,
) -> list[WarningItem]:
    warnings: list[WarningItem] = []
    content = subtitle.content.strip()
    lines = content.splitlines() or [content]
    length = readable_length(content)
    cps = length / duration_seconds(subtitle)

    if length > max_chars:
        warnings.append(
            WarningItem(rel(path), "too_many_chars", "Subtitle may be too dense for relaxed ASMR reading", subtitle.index, length, max_chars)
        )
    if cps > max_cps:
        warnings.append(
            WarningItem(rel(path), "high_cps", "Reading speed is high for ASMR listening", subtitle.index, round(cps, 2), max_cps)
        )
    if len(lines) > max_lines:
        warnings.append(
            WarningItem(rel(path), "too_many_lines", "Subtitle uses more lines than expected", subtitle.index, len(lines), max_lines)
        )
    for line in lines:
        line_length = readable_length(line)
        if line_length > max_line_chars:
            warnings.append(
                WarningItem(
                    rel(path),
                    "line_too_long",
                    "A subtitle line may be too long for comfortable reading",
                    subtitle.index,
                    line_length,
                    max_line_chars,
                )
            )
            break
    if REPEATED_CHAR_RE.search(PUNCTUATION_RE.sub("", content)):
        warnings.append(
            WarningItem(
                rel(path),
                "dense_repeated_sound",
                "Repeated sound text may be better as a short sound cue if it spans a long moment",
                subtitle.index,
            )
        )
    return warnings


def check_fragmentation(
    path: Path,
    subtitles: list[Subtitle],
    *,
    short_chars: int,
    short_gap: float,
    window: int,
) -> list[WarningItem]:
    warnings: list[WarningItem] = []
    if window < 2:
        return warnings
    for start in range(0, max(0, len(subtitles) - window + 1)):
        chunk = subtitles[start : start + window]
        if all(readable_length(sub.content) <= short_chars for sub in chunk):
            close = True
            for left, right in zip(chunk, chunk[1:]):
                gap = (right.start - left.end).total_seconds()
                if gap > short_gap:
                    close = False
                    break
            if close:
                warnings.append(
                    WarningItem(
                        rel(path),
                        "fragmented_short_run",
                        "Several very short subtitles appear in quick succession; avoid over-fragmenting ASMR captions",
                        chunk[0].index,
                        f"{chunk[0].index}-{chunk[-1].index}",
                        f"{window} subtitles",
                    )
                )
    return warnings


def check_file(path: Path, args: argparse.Namespace) -> list[WarningItem]:
    subtitles, warnings = load_subtitles(path)
    if warnings:
        return warnings
    for subtitle in subtitles:
        warnings.extend(
            check_subtitle(
                path,
                subtitle,
                max_cps=args.max_cps,
                max_chars=args.max_chars,
                max_line_chars=args.max_line_chars,
                max_lines=args.max_lines,
            )
        )
    warnings.extend(
        check_fragmentation(
            path,
            subtitles,
            short_chars=args.short_chars,
            short_gap=args.short_gap,
            window=args.short_run,
        )
    )
    return warnings


def print_report(warnings: list[WarningItem]) -> None:
    if not warnings:
        print("READABILITY OK")
        return
    print(f"READABILITY FOUND {len(warnings)} warning(s)")
    for warning in warnings:
        location = f"#{warning.subtitle_index}" if warning.subtitle_index is not None else ""
        details = ""
        if warning.value is not None:
            details = f" value={warning.value}"
        if warning.threshold is not None:
            details += f" threshold={warning.threshold}"
        print(f"WARNING {warning.code} {warning.path} {location}: {warning.message}{details}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ASMR subtitle readability without modifying subtitle files.")
    parser.add_argument("paths", nargs="+", help="SRT/VTT files or directories to check.")
    parser.add_argument("--max-cps", type=float, default=10.0, help="Warning threshold for Chinese characters per second.")
    parser.add_argument("--max-chars", type=int, default=42, help="Warning threshold for readable characters per subtitle.")
    parser.add_argument("--max-line-chars", type=int, default=24, help="Warning threshold for readable characters per line.")
    parser.add_argument("--max-lines", type=int, default=2, help="Warning threshold for lines per subtitle.")
    parser.add_argument("--short-chars", type=int, default=4, help="Subtitle length considered very short for fragmentation checks.")
    parser.add_argument("--short-gap", type=float, default=0.35, help="Maximum gap between very short subtitles for fragmentation checks.")
    parser.add_argument("--short-run", type=int, default=4, help="Number of close very short subtitles that triggers fragmentation warning.")
    parser.add_argument("--json-out", help="Write a JSON report to this path.")
    parser.add_argument("--fail-on-warnings", action="store_true", help="Return exit code 1 when warnings are present.")
    args = parser.parse_args()

    warnings: list[WarningItem] = []
    files = iter_subtitle_files(Path(path) for path in args.paths)
    if not files:
        warnings.append(WarningItem(".", "no_input_files", "No SRT or VTT files found"))
    for path in files:
        warnings.extend(check_file(path, args))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([asdict(warning) for warning in warnings], ensure_ascii=False, indent=2), encoding="utf-8")

    print_report(warnings)
    return 1 if warnings and args.fail_on_warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
