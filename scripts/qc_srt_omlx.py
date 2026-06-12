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

from subtitle_io import parse_srt_text
from translate_srt_omlx import extract_json_array, post_json


SYSTEM_PROMPT = """你是日译中 ASMR 字幕质检员。
只标出明显问题：错译、ASR 误识别导致中文荒唐、残留日文/英文音译、不符合上下文、中文不自然或逻辑不通。
不要挑细小风格问题，不要改写可接受的句子。
只返回 JSON 数组，不要解释，不要 Markdown。
"""

RISK_TERMS = [
    "耳舐め",
    "耳舐",
    "耳なめ",
    "おちんちん",
    "ちんちん",
    "射精",
    "中出し",
    "フェラ",
    "手コキ",
    "乳首",
    "挿入",
    "騎乗位",
    "キス",
    "喘",
    "耳舔",
    "舔耳",
    "射精",
    "口交",
    "手冲",
    "乳头",
    "插入",
    "骑乘",
]


def load_pairs(ja_path: Path, zh_path: Path) -> list[dict]:
    ja_subs = parse_srt_text(ja_path.read_text(encoding="utf-8"))
    zh_subs = parse_srt_text(zh_path.read_text(encoding="utf-8"))
    if len(ja_subs) != len(zh_subs):
        raise ValueError(f"count mismatch: {ja_path.name} {len(ja_subs)} != {zh_path.name} {len(zh_subs)}")
    pairs: list[dict] = []
    for ja, zh in zip(ja_subs, zh_subs):
        if ja.index != zh.index or ja.start != zh.start or ja.end != zh.end:
            raise ValueError(f"timeline mismatch at {ja.index}: {ja_path.name}")
        pairs.append({"i": ja.index, "ja": ja.content, "zh": zh.content})
    return pairs


def qc_chunk(items: list[dict], *, url: str, api_key: str, model: str, timeout: int, context: str) -> list[dict]:
    context_line = f"本作上下文：{context}\n" if context else ""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    context_line +
                    "检查下面同编号日文 ASR 与中文字幕。"
                    "只输出明显需要修改的问题。"
                    "返回 JSON 数组，每项格式为 "
                    "{\"i\":编号,\"problem\":\"简短说明\",\"suggest\":\"建议中文字幕\"}。\n"
                    f"{json.dumps(items, ensure_ascii=False, indent=2)}"
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
            clean.append({"i": index, "problem": problem, "suggest": suggest})
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
    text = f"{pair.get('ja', '')}\n{pair.get('zh', '')}"
    score = sum(1 for term in RISK_TERMS if term in text)
    if len(str(pair.get("ja", ""))) + len(str(pair.get("zh", ""))) > 140:
        score += 1
    if "\n" in str(pair.get("zh", "")):
        score += 1
    return score


def pair_chars(pair: dict[str, Any]) -> int:
    return len(str(pair.get("ja", ""))) + len(str(pair.get("zh", "")))


def build_chunks(
    pairs: list[dict[str, Any]],
    *,
    mode: str,
    chunk_size: int,
    min_chunk_size: int,
    max_chunk_size: int,
    target_chars: int,
    hard_chars: int,
) -> list[dict[str, Any]]:
    if mode == "fixed":
        return [
            {"chunk_no": number, "items": pairs[start : start + chunk_size]}
            for number, start in enumerate(range(0, len(pairs), chunk_size), start=1)
        ]

    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    chars = 0
    risk = 0
    for pair in pairs:
        current.append(pair)
        chars += pair_chars(pair)
        risk += pair_risk_score(pair)
        current_len = len(current)
        should_cut = False
        if current_len >= max_chunk_size:
            should_cut = True
        elif current_len >= min_chunk_size and risk >= 4:
            should_cut = True
        elif current_len >= min_chunk_size and chars >= hard_chars:
            should_cut = True
        elif current_len >= chunk_size and (chars >= target_chars or risk >= 2):
            should_cut = True
        if should_cut:
            chunks.append({"chunk_no": len(chunks) + 1, "items": current})
            current = []
            chars = 0
            risk = 0
    if current:
        chunks.append({"chunk_no": len(chunks) + 1, "items": current})
    return chunks


def chunk_range(items: list[dict[str, Any]]) -> tuple[int, int]:
    return int(items[0]["i"]), int(items[-1]["i"])


def chunk_signature(
    *,
    ja_path: Path,
    zh_path: Path,
    items: list[dict[str, Any]],
    context: str,
    model: str,
    base_url: str,
    mode: str,
) -> str:
    return stable_hash(
        {
            "ja": file_fingerprint(ja_path),
            "zh": file_fingerprint(zh_path),
            "indexes": [item["i"] for item in items],
            "items": items,
            "context": context,
            "model": model,
            "base_url": base_url.rstrip("/"),
            "mode": mode,
        }
    )


def chunk_cache_path(chunk_dir: Path, *, file_no: int, chunk_no: int, start_i: int, end_i: int) -> Path:
    return chunk_dir / f"file_{file_no:03d}_chunk_{chunk_no:04d}_{start_i}-{end_i}.json"


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


def summarize_chunk(items: list[dict[str, Any]]) -> dict[str, Any]:
    start_i, end_i = chunk_range(items)
    return {
        "start_i": start_i,
        "end_i": end_i,
        "count": len(items),
        "chars": sum(pair_chars(item) for item in items),
        "risk_score": sum(pair_risk_score(item) for item in items),
    }


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
    parser.add_argument("--min-chunk-size", type=int, default=8)
    parser.add_argument("--max-chunk-size", type=int, default=24)
    parser.add_argument("--target-chars", type=int, default=900)
    parser.add_argument("--hard-chars", type=int, default=1300)
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
    manifest_path = chunk_dir / "manifest.json"
    url = args.base_url.rstrip("/") + "/chat/completions"
    context = read_context(args.context, args.context_file)
    report: dict[str, list[dict]] = {}
    manifest: dict[str, Any] = {
        "version": 1,
        "updated_at": now_utc(),
        "out": out.as_posix(),
        "chunk_dir": chunk_dir.as_posix(),
        "settings": {
            "chunk_mode": args.chunk_mode,
            "chunk_size": args.chunk_size,
            "min_chunk_size": args.min_chunk_size,
            "max_chunk_size": args.max_chunk_size,
            "target_chars": args.target_chars,
            "hard_chars": args.hard_chars,
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
            issues: list[dict] = []
            chunks = build_chunks(
                pairs,
                mode=args.chunk_mode,
                chunk_size=args.chunk_size,
                min_chunk_size=args.min_chunk_size,
                max_chunk_size=args.max_chunk_size,
                target_chars=args.target_chars,
                hard_chars=args.hard_chars,
            )
            manifest["files"][ja_path.name] = {
                "ja": file_fingerprint(ja_path),
                "zh": file_fingerprint(zh_path),
                "chunks": [],
            }
            with tqdm(
                total=len(chunks),
                desc=ja_path.name,
                unit="chunk",
                dynamic_ncols=True,
                position=1,
                leave=False,
            ) as chunk_bar:
                for chunk_info in chunks:
                    chunk = chunk_info["items"]
                    chunk_no = int(chunk_info["chunk_no"])
                    start_i, end_i = chunk_range(chunk)
                    signature = chunk_signature(
                        ja_path=ja_path,
                        zh_path=zh_path,
                        items=chunk,
                        context=context,
                        model=args.model,
                        base_url=args.base_url,
                        mode=args.chunk_mode,
                    )
                    cache_path = chunk_cache_path(chunk_dir, file_no=file_no, chunk_no=chunk_no, start_i=start_i, end_i=end_i)
                    chunk_record = {
                        "chunk_no": chunk_no,
                        "cache_path": cache_path.as_posix(),
                        "signature": signature,
                        **summarize_chunk(chunk),
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
                                chunk,
                                url=url,
                                api_key=args.api_key,
                                model=args.model,
                                timeout=args.timeout,
                                context=context,
                            )
                            issues.extend(chunk_issues)
                            write_json_atomic(
                                cache_path,
                                {
                                    "status": "ok",
                                    "file": ja_path.name,
                                    "chunk_no": chunk_no,
                                    "signature": signature,
                                    "summary": summarize_chunk(chunk),
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
                            chunk_bar.write(f"RETRY {attempt} failed for {ja_path.name} {start_i}-{end_i}: {exc}")
                            time.sleep(1.5 * attempt)
                    else:
                        chunk_record["status"] = "error"
                        chunk_record["error"] = str(last_error)
                        manifest["files"][ja_path.name]["chunks"].append(chunk_record)
                        write_json_atomic(manifest_path, manifest)
                        raise RuntimeError(f"failed {ja_path.name} {start_i}-{end_i}") from last_error
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
