#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tqdm import tqdm

from subtitle_io import format_srt_timestamp, parse_srt_text
from subtitle_chunking import (
    Chunk,
    build_chunks_from_indexes,
    build_semantic_chunks,
    chunk_summary,
    item_chars,
    item_risk_score,
)
from translate_srt_omlx import extract_json_array, post_json


SYSTEM_PROMPT = """你是日译中 ASMR 字幕质检员。
只标出明显问题：错译、ASR 误识别导致中文荒唐、残留日文/英文音译、不符合上下文、中文不自然或逻辑不通。
不要挑细小风格问题，不要改写可接受的句子。
你的输出只是候选建议，不会直接自动修改字幕；请只报告有明确证据的问题。
只返回 JSON 数组，不要解释，不要 Markdown。
"""

PROMPT_VERSION = "qc-v2-halo-tiered"
DEEP_FLAGS = {
    "asr_uncertain",
    "adult_term",
    "speaker_ambiguous",
    "pronoun_ambiguous",
    "long_line",
    "possible_noise",
    "needs_context",
}


def load_pairs(ja_path: Path, zh_path: Path) -> list[dict]:
    ja_subs = parse_srt_text(ja_path.read_text(encoding="utf-8"))
    zh_subs = parse_srt_text(zh_path.read_text(encoding="utf-8"))
    if len(ja_subs) != len(zh_subs):
        raise ValueError(f"count mismatch: {ja_path.name} {len(ja_subs)} != {zh_path.name} {len(zh_subs)}")
    pairs: list[dict] = []
    for ja, zh in zip(ja_subs, zh_subs):
        if ja.index != zh.index or ja.start != zh.start or ja.end != zh.end:
            raise ValueError(f"timeline mismatch at {ja.index}: {ja_path.name}")
        pairs.append(
            {
                "i": ja.index,
                "start": format_srt_timestamp(ja.start),
                "end": format_srt_timestamp(ja.end),
                "ja": ja.content,
                "zh": zh.content,
            }
        )
    return pairs


def qc_chunk(
    items: list[dict],
    context_before: list[dict],
    context_after: list[dict],
    *,
    url: str,
    api_key: str,
    model: str,
    timeout: int,
    context: str,
    qc_pass: str,
) -> list[dict]:
    context_line = f"本作上下文：{context}\n" if context else ""
    pass_line = (
        "本轮是全量轻 QC：只标出明显错译、编号/结构异常、术语错误、严重 ASR 荒唐句。\n"
        if qc_pass == "light"
        else "本轮是风险深 QC：重点检查高风险、上下文依赖、成人术语、ASR 可疑和长句。\n"
        if qc_pass == "deep"
        else ""
    )
    user_payload = json.dumps(
        {
            "context_before": context_before,
            "target_items": items,
            "context_after": context_after,
        },
        ensure_ascii=False,
        indent=2,
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    context_line +
                    pass_line +
                    "检查下面同编号日文 ASR 与中文字幕。"
                    "context_before 和 context_after 只用于理解语义、角色、指代和动作连续性。"
                    "只检查并输出 target_items 的编号，不要输出上下文编号。"
                    "只输出明显需要修改的问题；建议只是候选，不代表会直接自动改字幕。"
                    "返回 JSON 数组，每项格式为 "
                    "{\"i\":编号,\"problem\":\"简短说明\",\"suggest\":\"建议中文字幕\"}。\n"
                    f"{user_payload}"
                ),
            },
        ],
        "temperature": 0.1,
        "max_tokens": max(1200, sum(len(x["ja"]) + len(x["zh"]) for x in items) * 2 + 800),
        "chat_template_kwargs": {"enable_thinking": False},
    }
    data = post_json(url, api_key, payload, timeout)
    content = data["choices"][0]["message"].get("content", "")
    result = extract_json_array(content)
    clean: list[dict] = []
    valid_indexes = {item["i"] for item in items}
    for item in result:
        try:
            index = int(item["i"])
        except Exception:
            continue
        if index not in valid_indexes:
            continue
        problem = str(item.get("problem", "")).strip()
        suggest = str(item.get("suggest", "")).strip()
        if problem and suggest:
            clean.append({"i": index, "problem": problem, "suggest": suggest, "qc_pass": qc_pass})
    return clean


def read_context(context: str, context_file: str) -> str:
    parts: list[str] = []
    if context:
        parts.append(context.strip())
    if context_file:
        path = Path(context_file)
        parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n".join(part for part in parts if part).strip()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": path.as_posix(), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def pair_risk_score(pair: dict[str, Any]) -> int:
    return item_risk_score(pair)


def pair_chars(pair: dict[str, Any]) -> int:
    return item_chars(pair)


def build_chunks(
    pairs: list[dict[str, Any]],
    *,
    mode: str,
    chunk_size: int,
    min_chunk_size: int,
    max_chunk_size: int,
    target_chars: int,
    hard_chars: int,
    halo: int,
) -> list[Chunk]:
    return build_semantic_chunks(
        pairs,
        mode=mode,
        chunk_size=chunk_size,
        min_chunk_size=min_chunk_size,
        max_chunk_size=max_chunk_size,
        target_chars=target_chars,
        hard_chars=hard_chars,
        halo=halo,
        risk_score_fn=pair_risk_score,
    )


def chunk_range(chunk: Chunk) -> tuple[int, int]:
    return chunk.target_indexes[0], chunk.target_indexes[-1]


def chunk_signature(
    *,
    chunk: Chunk,
    context: str,
    model: str,
    base_url: str,
    pass_name: str,
    settings: dict[str, Any],
    flags: dict[int, list[str]],
) -> str:
    return stable_hash(
        {
            "prompt_version": PROMPT_VERSION,
            "pass": pass_name,
            "target_indexes": chunk.target_indexes,
            "items": chunk.items,
            "context_before": chunk.context_before,
            "context_after": chunk.context_after,
            "flags": {str(index): flags.get(index, []) for index in chunk.target_indexes},
            "context": context,
            "model": model,
            "base_url": base_url.rstrip("/"),
            "settings": settings,
        }
    )


def chunk_cache_path(chunk_dir: Path, *, pass_name: str, file_no: int, chunk_no: int, start_i: int, end_i: int) -> Path:
    return chunk_dir / f"{pass_name}_file_{file_no:03d}_chunk_{chunk_no:04d}_{start_i}-{end_i}.json"


def load_cached_chunk(path: Path, signature: str) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("status") != "ok" or data.get("signature") != signature:
        return None
    issues = data.get("issues")
    return issues if isinstance(issues, list) else None


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def default_chunk_dir(out: Path) -> Path:
    return out.parent / f"{out.stem}_chunks"


def load_translation_flags(flags_dir: Path, zh_path: Path) -> dict[int, list[str]]:
    candidates = [
        flags_dir / f"{zh_path.name}.flags.json",
        zh_path.with_suffix(zh_path.suffix + ".flags.json"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {int(key): [str(flag) for flag in value] for key, value in data.items() if isinstance(value, list)}
    return {}


def select_deep_index_groups(
    pairs: list[dict[str, Any]],
    *,
    flags: dict[int, list[str]],
    neighbor_window: int,
    max_group_size: int,
) -> list[list[int]]:
    selected_positions: set[int] = set()
    for pos, pair in enumerate(pairs):
        index = int(pair["i"])
        pair_flags = set(flags.get(index, []))
        zh = str(pair.get("zh", ""))
        suspicious = bool(pair_flags & DEEP_FLAGS)
        suspicious = suspicious or pair_risk_score(pair) >= 1
        suspicious = suspicious or pair_chars(pair) >= 180
        suspicious = suspicious or any("\u3040" <= ch <= "\u30ff" for ch in zh)
        suspicious = suspicious or any(marker in zh for marker in ["???", "？？？", "�", "□"])
        if not suspicious:
            continue
        for offset in range(-neighbor_window, neighbor_window + 1):
            selected = pos + offset
            if 0 <= selected < len(pairs):
                selected_positions.add(selected)
    groups: list[list[int]] = []
    current: list[int] = []
    previous_pos: int | None = None
    for pos in sorted(selected_positions):
        if previous_pos is None or pos == previous_pos + 1:
            current.append(int(pairs[pos]["i"]))
        else:
            if current:
                groups.extend(current[start : start + max_group_size] for start in range(0, len(current), max_group_size))
            current = [int(pairs[pos]["i"])]
        previous_pos = pos
    if current:
        groups.extend(current[start : start + max_group_size] for start in range(0, len(current), max_group_size))
    return groups


def previous_groups(manifest: dict[str, Any], *, file_name: str, pass_name: str) -> list[list[int]]:
    file_record = manifest.get("files", {}).get(file_name, {})
    groups: list[list[int]] = []
    for chunk in file_record.get("chunks", []):
        if chunk.get("pass") != pass_name:
            continue
        indexes = chunk.get("target_indexes")
        if isinstance(indexes, list) and indexes:
            groups.append([int(index) for index in indexes])
    return groups


def build_qc_plan(
    pairs: list[dict[str, Any]],
    *,
    qc_tier: str,
    flags: dict[int, list[str]],
    previous_manifest: dict[str, Any],
    file_name: str,
    args: argparse.Namespace,
) -> list[tuple[str, list[Chunk]]]:
    def chunks_for(pass_name: str, source_pairs: list[dict[str, Any]], *, small: bool = False) -> list[Chunk]:
        old_groups = previous_groups(previous_manifest, file_name=file_name, pass_name=pass_name) if args.reuse_chunk_boundaries else []
        if old_groups:
            reused = build_chunks_from_indexes(pairs, old_groups, halo=args.context_halo, reason="manifest_reuse")
            if reused and sum(len(chunk.items) for chunk in reused) == sum(len(group) for group in old_groups):
                return reused
        return build_chunks(
            source_pairs,
            mode=args.chunk_mode,
            chunk_size=max(2, min(args.chunk_size, 8)) if small else args.chunk_size,
            min_chunk_size=max(1, min(args.min_chunk_size, 2)) if small else args.min_chunk_size,
            max_chunk_size=max(3, min(args.max_chunk_size, 10)) if small else args.max_chunk_size,
            target_chars=min(args.target_chars, 420) if small else args.target_chars,
            hard_chars=min(args.hard_chars, 650) if small else args.hard_chars,
            halo=args.context_halo,
        )

    deep_groups = select_deep_index_groups(
        pairs,
        flags=flags,
        neighbor_window=args.deep_neighbor_window,
        max_group_size=max(3, min(args.max_chunk_size, 10)),
    )
    deep_chunks = build_chunks_from_indexes(pairs, deep_groups, halo=args.context_halo, reason="risk_window") if deep_groups else []
    if qc_tier == "light":
        return [("light", chunks_for("light", pairs))]
    if qc_tier == "deep":
        return [("deep", deep_chunks)] if deep_chunks else []
    if qc_tier == "two-pass":
        plan = [("light", chunks_for("light", pairs))]
        if deep_chunks:
            plan.append(("deep", deep_chunks))
        return plan
    return [("standard", chunks_for("standard", pairs))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asr-dir", required=True)
    parser.add_argument("--zh-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--model", default="Qwen3.6-27B-MLX-VL-oQ6")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--chunk-size", type=int, default=18, help="Fixed chunk size, or target chunk size when --chunk-mode dynamic.")
    parser.add_argument("--chunk-mode", choices=["dynamic", "fixed"], default="dynamic")
    parser.add_argument("--qc-tier", choices=["standard", "light", "deep", "two-pass"], default="two-pass")
    parser.add_argument("--min-chunk-size", type=int, default=8)
    parser.add_argument("--max-chunk-size", type=int, default=32)
    parser.add_argument("--target-chars", type=int, default=1400)
    parser.add_argument("--hard-chars", type=int, default=2200)
    parser.add_argument("--context-halo", type=int, default=3)
    parser.add_argument("--flags-dir", default="", help="Directory containing <zh_file>.flags.json from translation. Defaults to --zh-dir.")
    parser.add_argument("--deep-neighbor-window", type=int, default=1)
    parser.add_argument("--reuse-chunk-boundaries", action="store_true", default=True)
    parser.add_argument("--no-reuse-chunk-boundaries", dest="reuse_chunk_boundaries", action="store_false")
    parser.add_argument("--chunk-dir", default="", help="Directory for resumable QC chunk cache. Defaults to <out_stem>_chunks next to --out.")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Ignore cached successful QC chunks.")
    parser.add_argument("--force", action="store_true", help="Rerun all QC chunks even if cached chunks exist.")
    parser.add_argument("--plan-only", action="store_true", help="Build chunk manifest without calling the model.")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--context", default="", help="Brief work-specific context and known ASR risks for QC.")
    parser.add_argument("--context-file", default="", help="Optional Markdown/text context profile to include in QC prompts.")
    parser.set_defaults(resume=True)
    args = parser.parse_args()

    asr_dir = Path(args.asr_dir)
    zh_dir = Path(args.zh_dir)
    out = Path(args.out)
    chunk_dir = Path(args.chunk_dir) if args.chunk_dir else default_chunk_dir(out)
    flags_dir = Path(args.flags_dir) if args.flags_dir else zh_dir
    manifest_path = chunk_dir / "manifest.json"
    previous_manifest = {}
    if manifest_path.exists():
        try:
            previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            previous_manifest = {}
    url = args.base_url.rstrip("/") + "/chat/completions"
    context = read_context(args.context, args.context_file)
    signature_settings = {
        "chunk_mode": args.chunk_mode,
        "qc_tier": args.qc_tier,
        "chunk_size": args.chunk_size,
        "min_chunk_size": args.min_chunk_size,
        "max_chunk_size": args.max_chunk_size,
        "target_chars": args.target_chars,
        "hard_chars": args.hard_chars,
        "context_halo": args.context_halo,
        "deep_neighbor_window": args.deep_neighbor_window,
    }
    report: dict[str, list[dict]] = {}
    manifest: dict[str, Any] = {
        "version": 2,
        "updated_at": now_utc(),
        "out": out.as_posix(),
        "chunk_dir": chunk_dir.as_posix(),
        "settings": {
            "prompt_version": PROMPT_VERSION,
            "qc_tier": args.qc_tier,
            "chunk_mode": args.chunk_mode,
            "chunk_size": args.chunk_size,
            "min_chunk_size": args.min_chunk_size,
            "max_chunk_size": args.max_chunk_size,
            "target_chars": args.target_chars,
            "hard_chars": args.hard_chars,
            "context_halo": args.context_halo,
            "deep_neighbor_window": args.deep_neighbor_window,
            "reuse_chunk_boundaries": args.reuse_chunk_boundaries,
            "model": args.model,
            "base_url": args.base_url.rstrip("/"),
            "resume": args.resume,
            "force": args.force,
            "plan_only": args.plan_only,
        },
        "files": {},
    }

    ja_files = sorted(asr_dir.glob("*.ja.asr.srt"))
    with tqdm(total=len(ja_files), desc="qc files", unit="file", dynamic_ncols=True, position=0) as file_bar:
        for file_no, ja_path in enumerate(ja_files, start=1):
            zh_path = zh_dir / ja_path.name.replace(".ja.asr.srt", ".zh.srt")
            pairs = load_pairs(ja_path, zh_path)
            flags = load_translation_flags(flags_dir, zh_path)
            issues: list[dict] = []
            plan = build_qc_plan(
                pairs,
                qc_tier=args.qc_tier,
                flags=flags,
                previous_manifest=previous_manifest,
                file_name=ja_path.name,
                args=args,
            )
            total_chunks = sum(len(chunks) for _, chunks in plan)
            manifest["files"][ja_path.name] = {
                "ja": file_fingerprint(ja_path),
                "zh": file_fingerprint(zh_path),
                "translation_flags": {str(key): value for key, value in sorted(flags.items()) if value},
                "chunks": [],
            }
            with tqdm(
                total=total_chunks,
                desc=ja_path.name,
                unit="chunk",
                dynamic_ncols=True,
                position=1,
                leave=False,
            ) as chunk_bar:
                for pass_name, chunks in plan:
                    for chunk in chunks:
                        chunk_no = int(chunk.chunk_no)
                        start_i, end_i = chunk_range(chunk)
                        signature = chunk_signature(
                            chunk=chunk,
                            context=context,
                            model=args.model,
                            base_url=args.base_url,
                            pass_name=pass_name,
                            settings=signature_settings,
                            flags=flags,
                        )
                        cache_path = chunk_cache_path(
                            chunk_dir,
                            pass_name=pass_name,
                            file_no=file_no,
                            chunk_no=chunk_no,
                            start_i=start_i,
                            end_i=end_i,
                        )
                        chunk_record = {
                            "pass": pass_name,
                            "chunk_no": chunk_no,
                            "cache_path": cache_path.as_posix(),
                            "signature": signature,
                            **chunk_summary(chunk),
                        }
                        if args.plan_only:
                            chunk_record["status"] = "planned"
                            manifest["files"][ja_path.name]["chunks"].append(chunk_record)
                            chunk_bar.update(1)
                            continue
                        cached = None if args.force or not args.resume else load_cached_chunk(cache_path, signature)
                        if cached is not None:
                            issues.extend(cached)
                            chunk_record["status"] = "cached"
                            chunk_record["issue_count"] = len(cached)
                            manifest["files"][ja_path.name]["chunks"].append(chunk_record)
                            write_json_atomic(manifest_path, manifest)
                            chunk_bar.update(1)
                            continue
                        last_error: Exception | None = None
                        for attempt in range(1, 4):
                            try:
                                chunk_issues = qc_chunk(
                                    chunk.items,
                                    chunk.context_before,
                                    chunk.context_after,
                                    url=url,
                                    api_key=args.api_key,
                                    model=args.model,
                                    timeout=args.timeout,
                                    context=context,
                                    qc_pass=pass_name,
                                )
                                issues.extend(chunk_issues)
                                write_json_atomic(
                                    cache_path,
                                    {
                                        "status": "ok",
                                        "file": ja_path.name,
                                        "pass": pass_name,
                                        "chunk_no": chunk_no,
                                        "signature": signature,
                                        "summary": chunk_summary(chunk),
                                        "issues": chunk_issues,
                                        "updated_at": now_utc(),
                                    },
                                )
                                chunk_record["status"] = "ok"
                                chunk_record["issue_count"] = len(chunk_issues)
                                manifest["files"][ja_path.name]["chunks"].append(chunk_record)
                                write_json_atomic(manifest_path, manifest)
                                break
                            except Exception as exc:
                                last_error = exc
                                chunk_bar.write(f"RETRY {attempt} failed for {ja_path.name} {pass_name} {start_i}-{end_i}: {exc}")
                                time.sleep(1.5 * attempt)
                        else:
                            chunk_record["status"] = "error"
                            chunk_record["error"] = str(last_error)
                            manifest["files"][ja_path.name]["chunks"].append(chunk_record)
                            write_json_atomic(manifest_path, manifest)
                            raise RuntimeError(f"failed {ja_path.name} {pass_name} {start_i}-{end_i}") from last_error
                        chunk_bar.update(1)
            report[ja_path.name] = issues
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            write_json_atomic(manifest_path, manifest)
            file_bar.update(1)
    if args.plan_only:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_json_atomic(manifest_path, manifest)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
