#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import srt


@dataclass
class MatchResult:
    start_page: int
    end_page: int
    ratio: float
    script_text: str


def normalize(text: str) -> str:
    text = text.replace("︙", "…")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[0-9０-９]", "", text)
    text = re.sub(r"[-‐‑–—―ー−]+", "ー", text)
    text = re.sub(r"[、。,.!?！？♡❤♪『』「」()\[\]（）…・:：;；\"'“”]", "", text)
    return text


def clean_pdf_page(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"-\s*\d+\s*-", line):
            continue
        if re.fullmatch(r"[\d\s]+", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def extract_pdf_pages(pdf: Path) -> list[str]:
    out = subprocess.check_output(["pdftotext", "-layout", str(pdf), "-"], text=True)
    return [clean_pdf_page(page) for page in out.split("\f") if clean_pdf_page(page)]


def read_srt_text(path: Path) -> tuple[str, list[srt.Subtitle]]:
    subs = list(srt.parse(path.read_text(encoding="utf-8")))
    return "\n".join(sub.content for sub in subs), subs


def best_page_window(asr_norm: str, pages: list[str], *, max_window: int = 12) -> MatchResult:
    best = MatchResult(1, 1, 0.0, pages[0] if pages else "")
    page_norms = [normalize(page) for page in pages]
    for start in range(len(pages)):
        for end in range(start, min(len(pages), start + max_window)):
            script_norm = "".join(page_norms[start : end + 1])
            if not script_norm:
                continue
            # SequenceMatcher is expensive on very long text; compare to a length-near slice first.
            ratio = SequenceMatcher(None, asr_norm, script_norm, autojunk=False).ratio()
            if ratio > best.ratio:
                best = MatchResult(start + 1, end + 1, ratio, "\n".join(pages[start : end + 1]))
    return best


def suspicious_segments(subs: list[srt.Subtitle], script_norm: str, limit: int = 12) -> list[tuple[int, str, float]]:
    suspicious: list[tuple[int, str, float]] = []
    for sub in subs:
        text_norm = normalize(sub.content)
        if len(text_norm) < 4:
            continue
        if text_norm in script_norm:
            continue
        # Compare against short windows around likely substrings by brute force stride.
        best = 0.0
        window = max(12, min(len(text_norm) * 3, 120))
        for i in range(0, max(1, len(script_norm) - window), max(1, window // 3)):
            ratio = SequenceMatcher(None, text_norm, script_norm[i : i + window], autojunk=False).ratio()
            if ratio > best:
                best = ratio
        if best < 0.45:
            suspicious.append((sub.index, sub.content.replace("\n", " "), best))
    return suspicious[:limit]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--asr-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    pdf = Path(args.pdf)
    asr_dir = Path(args.asr_dir)
    out = Path(args.out)

    pages = extract_pdf_pages(pdf)
    rows: list[str] = [
        "# RJ01201653 ASR vs 初稿台本比对",
        "",
        f"- PDF pages parsed: {len(pages)}",
        "- Similarity is fuzzy text similarity after removing punctuation/spaces/numbers.",
        "- EX フリートーク is expected to have no PDF script match.",
        "",
        "| Track | Best PDF pages | Similarity | ASR segments | Notes |",
        "|---|---:|---:|---:|---|",
    ]

    detail_sections: list[str] = []
    for srt_path in sorted(asr_dir.glob("*.ja.asr.srt")):
        text, subs = read_srt_text(srt_path)
        asr_norm = normalize(text)
        if srt_path.name.startswith("EX."):
            rows.append(f"| `{srt_path.stem}` | n/a | n/a | {len(subs)} | フリートーク; no script expected |")
            continue
        match = best_page_window(asr_norm, pages)
        script_norm = normalize(match.script_text)
        suspicious = suspicious_segments(subs, script_norm)
        note = "good" if match.ratio >= 0.58 else "needs review"
        rows.append(
            f"| `{srt_path.stem}` | {match.start_page}-{match.end_page} | {match.ratio:.3f} | {len(subs)} | {note}; suspicious={len(suspicious)} |"
        )
        detail_sections.append(f"## {srt_path.stem}\n")
        detail_sections.append(f"- Best pages: {match.start_page}-{match.end_page}\n")
        detail_sections.append(f"- Similarity: {match.ratio:.3f}\n")
        if suspicious:
            detail_sections.append("- Low-confidence ASR segments:\n")
            for index, content, score in suspicious:
                clipped = content[:90] + ("..." if len(content) > 90 else "")
                detail_sections.append(f"  - #{index} score={score:.2f}: `{clipped}`\n")
        else:
            detail_sections.append("- Low-confidence ASR segments: none in sampled threshold.\n")
        detail_sections.append("\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(rows) + "\n\n" + "".join(detail_sections), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
