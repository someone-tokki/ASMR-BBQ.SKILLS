#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tqdm import tqdm

from subtitle_io import parse_srt_text
from translate_srt_omlx import extract_json_array, post_json


SYSTEM_PROMPT = """你是日译中 ASMR 字幕质检员。
只标出明显问题：错译、ASR 误识别导致中文荒唐、残留日文/英文音译、不符合上下文、中文不自然或逻辑不通。
不要挑细小风格问题，不要改写可接受的句子。
只返回 JSON 数组，不要解释，不要 Markdown。
"""


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asr-dir", required=True)
    parser.add_argument("--zh-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--model", default="Qwen3.6-27B-MLX-VL-oQ6")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--chunk-size", type=int, default=18)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--context", default="", help="Brief work-specific context and known ASR risks for QC.")
    parser.add_argument("--context-file", default="", help="Optional Markdown/text context profile to include in QC prompts.")
    args = parser.parse_args()

    asr_dir = Path(args.asr_dir)
    zh_dir = Path(args.zh_dir)
    out = Path(args.out)
    url = args.base_url.rstrip("/") + "/chat/completions"
    context = read_context(args.context, args.context_file)
    report: dict[str, list[dict]] = {}

    ja_files = sorted(asr_dir.glob("*.ja.asr.srt"))
    with tqdm(total=len(ja_files), desc="qc files", unit="file", dynamic_ncols=True, position=0) as file_bar:
        for ja_path in ja_files:
            zh_path = zh_dir / ja_path.name.replace(".ja.asr.srt", ".zh.srt")
            pairs = load_pairs(ja_path, zh_path)
            issues: list[dict] = []
            total_chunks = (len(pairs) + args.chunk_size - 1) // args.chunk_size
            with tqdm(
                total=total_chunks,
                desc=ja_path.name,
                unit="chunk",
                dynamic_ncols=True,
                position=1,
                leave=False,
            ) as chunk_bar:
                for start in range(0, len(pairs), args.chunk_size):
                    chunk = pairs[start : start + args.chunk_size]
                    last_error: Exception | None = None
                    for attempt in range(1, 4):
                        try:
                            issues.extend(
                                qc_chunk(
                                    chunk,
                                    url=url,
                                    api_key=args.api_key,
                                    model=args.model,
                                    timeout=args.timeout,
                                    context=context,
                                )
                            )
                            break
                        except Exception as exc:
                            last_error = exc
                            chunk_bar.write(f"RETRY {attempt} failed for {ja_path.name} {start + 1}-{start + len(chunk)}: {exc}")
                            time.sleep(1.5 * attempt)
                    else:
                        raise RuntimeError(f"failed {ja_path.name} {start + 1}-{start + len(chunk)}") from last_error
                    chunk_bar.update(1)
            report[ja_path.name] = issues
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            file_bar.update(1)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
