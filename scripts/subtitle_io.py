from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta


@dataclass
class Subtitle:
    index: int
    start: timedelta
    end: timedelta
    content: str


TIMESTAMP_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})$")


def parse_timestamp(value: str) -> timedelta:
    match = TIMESTAMP_RE.match(value.strip())
    if not match:
        raise ValueError(f"Invalid timestamp: {value!r}")
    hours, minutes, seconds, milliseconds = match.groups()
    return timedelta(
        hours=int(hours),
        minutes=int(minutes),
        seconds=int(seconds),
        milliseconds=int(milliseconds.ljust(3, "0")),
    )


def parse_srt_text(text: str) -> list[Subtitle]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    subtitles: list[Subtitle] = []
    cursor = 0
    while cursor < len(lines):
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        if cursor >= len(lines):
            break

        index_line = lines[cursor].strip()
        cursor += 1
        if not index_line.isdigit():
            raise ValueError(f"Expected subtitle index, found {index_line!r}")
        index = int(index_line)

        if cursor >= len(lines):
            raise ValueError(f"Missing timing line after subtitle {index}")
        timing_line = lines[cursor].strip()
        cursor += 1
        if "-->" not in timing_line:
            raise ValueError(f"Missing timing separator at subtitle {index}")
        start_text, end_text = [part.strip().split()[0] for part in timing_line.split("-->", 1)]
        start = parse_timestamp(start_text)
        end = parse_timestamp(end_text)

        content_lines: list[str] = []
        while cursor < len(lines) and lines[cursor].strip():
            content_lines.append(lines[cursor])
            cursor += 1
        subtitles.append(Subtitle(index=index, start=start, end=end, content="\n".join(content_lines)))

    return subtitles


def format_srt_timestamp(value: timedelta) -> str:
    total_ms = int(round(value.total_seconds() * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def compose_srt_text(subtitles: list[Subtitle]) -> str:
    blocks: list[str] = []
    for subtitle in subtitles:
        blocks.append(
            "\n".join(
                [
                    str(subtitle.index),
                    f"{format_srt_timestamp(subtitle.start)} --> {format_srt_timestamp(subtitle.end)}",
                    subtitle.content,
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")
