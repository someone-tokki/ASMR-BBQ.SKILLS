#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from subtitle_io import parse_srt_text


@dataclass(frozen=True)
class RiskPattern:
    name: str
    pattern: str
    problem: str
    suggestion: str


@dataclass
class Finding:
    path: str
    pattern: str
    matched: str
    problem: str
    suggestion: str
    subtitle_index: int | None = None
    line: int | None = None


DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "subtitle_risk_patterns.json"


FALLBACK_RISK_PATTERNS: tuple[RiskPattern, ...] = (
    RiskPattern("asr_thanks", r"感谢(?:您的)?观看|谢谢观看", "May be ASR hallucination over long sounds or ending noise.", "Check audio/source; if it is only sound, replace with a short sound cue."),
    RiskPattern("asr_subscribe", r"订阅|频道|点赞|字幕组", "Often ASR/video-platform hallucination in ASMR audio.", "Check source context before keeping as dialogue."),
    RiskPattern("model_artifact", r"语言模型|JSON|undefined|null|Markdown", "Likely model or formatting artifact.", "Remove or retranslate from the original subtitle."),
    RiskPattern("vagus", r"冥想神经", "Likely mistranslation of 迷走神経.", "Check whether it should be 迷走神经."),
    RiskPattern("seieki_justice", r"正义", "Adult ASMR context may have confused 精液 with 正義.", "Check source; often should be 精液."),
    RiskPattern("shasei_writing", r"写生|写真|书生|照片|姿势", "May be ASR/translation drift from 射精 in adult ASMR.", "Check neighboring subtitles and climax/countdown context."),
    RiskPattern("m_otoko", r"魔女", "May be misread from M男 depending on context.", "Check character/roleplay context."),
    RiskPattern("tekoki", r"手呼吸", "Likely mistranslation of 手コキ or hand stimulation.", "Check source; often should be 手冲 or 用手帮你弄."),
    RiskPattern("shiko_urine", r"尿尿|嘘嘘", "May be mistaken from シコ/しっこ in adult ASMR.", "Check source; often should be 撸/撸撸 in hand-stimulation context."),
    RiskPattern("sourou", r"僧侣|僧侶|骚动|騒動|Souro|灵魂|步态|神父", "May be 早漏（そうろう） in early-ejaculation themed works.", "Check title and recurring theme; normalize if the work is about 早漏."),
    RiskPattern("onanie_owner", r"主人|服侍主人|オーナー", "May be オナニー misrecognized as owner/master wording.", "Check whether the source is 自慰/手淫 rather than master-servant dialogue."),
    RiskPattern("fellatio_overuse", r"口交", "Can be wrong when source is オナニー/ホナニー/オナサポ rather than フェラ.", "Confirm sex act from source before keeping 口交."),
    RiskPattern("onasuport", r"自慰辅助", "Term is acceptable but can sound stiff in dialogue.", "Check whether 陪你自慰 or 帮你弄 is more natural in context."),
    RiskPattern("doutei", r"道谢室|草子", "May be corrupted from 童貞喪失.", "Check source; often should be 童贞丧失 or 破处."),
    RiskPattern("police", r"警察", "May be unrelated near-sound ASR error.", "Check source before keeping."),
    RiskPattern("shi_houdai", r"大开杀戒", "May be mistranslation of し放題.", "Check whether 想怎么做都可以 is intended."),
    RiskPattern("nama_ecchi", r"生涩", "May be 生エッチ in adult ASMR.", "Check whether 无套做爱 is intended."),
    RiskPattern("miminame_raw", r"耳舐め", "Japanese term left in Chinese output.", "Use 舔耳, 舔耳朵, or [舔耳声]."),
    RiskPattern("love_hotel", r"Love Hotel|爱情旅馆", "Less natural localization for ラブホテル.", "Use 情人旅馆 if context fits."),
    RiskPattern("cos_layer", r"图层|官方解说员", "Likely mistranslation of レイヤー.", "Use coser/官方 coser as appropriate."),
    RiskPattern("asmr_script_artifact", r"我的Cosplay", "May be model literalization or odd phrasing.", "Check source and make the cosplay reference natural."),
)

SUPPORTED_SUFFIXES = {".srt", ".vtt", ".txt", ".md"}


def rel(path: Path) -> str:
    return path.as_posix()


def risk_pattern_from_item(item: object, index: int) -> RiskPattern:
    if not isinstance(item, dict):
        raise ValueError(f"patterns[{index}] must be an object")
    missing = [key for key in ("name", "pattern", "problem", "suggestion") if not str(item.get(key, "")).strip()]
    if missing:
        raise ValueError(f"patterns[{index}] missing required field(s): {', '.join(missing)}")
    return RiskPattern(
        name=str(item["name"]).strip(),
        pattern=str(item["pattern"]).strip(),
        problem=str(item["problem"]).strip(),
        suggestion=str(item["suggestion"]).strip(),
    )


def load_patterns_from_file(path: Path) -> tuple[RiskPattern, ...]:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Risk rules file must be a JSON object")
    if data.get("version") != 1:
        raise ValueError("Risk rules file must have version=1")
    raw_patterns = data.get("patterns")
    if not isinstance(raw_patterns, list) or not raw_patterns:
        raise ValueError("Risk rules file must contain a non-empty patterns array")
    patterns = tuple(risk_pattern_from_item(item, index) for index, item in enumerate(raw_patterns))
    names = [pattern.name for pattern in patterns]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"Duplicate risk pattern name(s): {', '.join(duplicates)}")
    return patterns


def load_risk_patterns(path: Path, *, explicit: bool) -> tuple[RiskPattern, ...]:
    if path.exists():
        return load_patterns_from_file(path)
    if explicit:
        raise FileNotFoundError(f"Risk rules file not found: {path}")
    print(f"WARN risk rules file not found; using built-in fallback: {path}", file=sys.stderr)
    return FALLBACK_RISK_PATTERNS


def compile_patterns(patterns: Iterable[RiskPattern]) -> list[tuple[RiskPattern, re.Pattern[str]]]:
    compiled: list[tuple[RiskPattern, re.Pattern[str]]] = []
    for risk in patterns:
        try:
            compiled.append((risk, re.compile(risk.pattern, re.IGNORECASE)))
        except re.error as exc:
            raise ValueError(f"Invalid regex for risk pattern {risk.name}: {exc}") from exc
    return compiled


def include_path(path: Path, include: list[str], exclude: list[str]) -> bool:
    text = path.as_posix()
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return False
    if include and not any(fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(path.name, pattern) for pattern in include):
        return False
    if exclude and any(fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(path.name, pattern) for pattern in exclude):
        return False
    return True


def iter_files(paths: Iterable[Path], include: list[str], exclude: list[str]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and include_path(child, include, exclude):
                    files.append(child)
        elif path.is_file() and include_path(path, include, exclude):
            files.append(path)
    return sorted(dict.fromkeys(files))


def scan_text(path: Path, text: str, patterns: list[tuple[RiskPattern, re.Pattern[str]]], *, line: int | None = None, subtitle_index: int | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for risk, regex in patterns:
        for match in regex.finditer(text):
            findings.append(
                Finding(
                    path=rel(path),
                    pattern=risk.name,
                    matched=match.group(0),
                    problem=risk.problem,
                    suggestion=risk.suggestion,
                    subtitle_index=subtitle_index,
                    line=line,
                )
            )
    return findings


def scan_srt(path: Path, patterns: list[tuple[RiskPattern, re.Pattern[str]]]) -> list[Finding]:
    try:
        subtitles = parse_srt_text(path.read_text(encoding="utf-8"))
    except Exception:
        return scan_lines(path, patterns)
    findings: list[Finding] = []
    for subtitle in subtitles:
        findings.extend(scan_text(path, subtitle.content, patterns, subtitle_index=subtitle.index))
    return findings


def scan_vtt(path: Path, patterns: list[tuple[RiskPattern, re.Pattern[str]]]) -> list[Finding]:
    findings: list[Finding] = []
    block_lines: list[str] = []
    block_start_line = 1
    cue_index = 0
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines + [""], start=1):
        if line.strip():
            if not block_lines:
                block_start_line = line_number
            block_lines.append(line)
            continue
        if block_lines:
            cue_text = "\n".join(block_lines)
            if "-->" in cue_text:
                cue_index += 1
                text_lines = [item for item in block_lines if "-->" not in item and item.strip() != "WEBVTT"]
                findings.extend(scan_text(path, "\n".join(text_lines), patterns, line=block_start_line, subtitle_index=cue_index))
            else:
                findings.extend(scan_text(path, cue_text, patterns, line=block_start_line))
            block_lines = []
    return findings


def scan_lines(path: Path, patterns: list[tuple[RiskPattern, re.Pattern[str]]]) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        findings.extend(scan_text(path, line, patterns, line=line_number))
    return findings


def scan_file(path: Path, patterns: list[tuple[RiskPattern, re.Pattern[str]]]) -> list[Finding]:
    suffix = path.suffix.lower()
    if suffix == ".srt":
        return scan_srt(path, patterns)
    if suffix == ".vtt":
        return scan_vtt(path, patterns)
    return scan_lines(path, patterns)


def print_report(findings: list[Finding]) -> None:
    if not findings:
        print("RISK SCAN OK")
        return
    print(f"RISK SCAN FOUND {len(findings)} candidate issue(s)")
    for finding in findings:
        location = f"#{finding.subtitle_index}" if finding.subtitle_index is not None else f"line {finding.line}"
        print(
            f"{finding.path} {location}: {finding.pattern} matched {finding.matched!r} - "
            f"{finding.problem} Suggestion: {finding.suggestion}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan ASMR subtitles and docs for high-risk ASR/translation terms.")
    parser.add_argument("paths", nargs="+", help="Files or directories to scan.")
    parser.add_argument("--rules", default=str(DEFAULT_RULES_PATH), help="Structured JSON risk rule file.")
    parser.add_argument("--include", action="append", default=[], help="Glob to include; may be repeated.")
    parser.add_argument("--exclude", action="append", default=[], help="Glob to exclude; may be repeated.")
    parser.add_argument("--json-out", help="Write a JSON report to this path.")
    parser.add_argument("--fail-on-findings", action="store_true", help="Return exit code 1 when findings are present.")
    args = parser.parse_args()

    rules_path = Path(args.rules)
    explicit_rules = args.rules != str(DEFAULT_RULES_PATH)
    try:
        patterns = compile_patterns(load_risk_patterns(rules_path, explicit=explicit_rules))
    except Exception as exc:
        print(f"ERROR loading risk rules: {exc}", file=sys.stderr)
        return 2

    files = iter_files((Path(path) for path in args.paths), args.include, args.exclude)
    findings: list[Finding] = []
    for path in files:
        findings.extend(scan_file(path, patterns))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([asdict(finding) for finding in findings], ensure_ascii=False, indent=2), encoding="utf-8")

    print_report(findings)
    return 1 if findings and args.fail_on_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
