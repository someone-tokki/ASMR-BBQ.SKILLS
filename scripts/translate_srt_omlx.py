#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

from tqdm import tqdm

from subtitle_io import Subtitle, compose_srt_text, format_srt_timestamp, parse_srt_text
from subtitle_chunking import Chunk, build_semantic_chunks, chunk_summary


SYSTEM_PROMPT = """你是专业的日译中 ASMR 字幕翻译器。
要求：
- 输出自然、有人情味、符合情境的简体中文。
- 保留亲密、撒娇、停顿、耳语的感觉，但不要生硬直译。
- 拟声词、喘息、亲吻/耳语/摩擦等重复声音可以简化为短中文或方括号提示，例如「[耳语]」「[亲吻声]」「……」。
- 修正常见 ASR 错字，但不要改写剧情。
- 只返回 JSON 数组，不要解释，不要 Markdown。
"""

ALLOWED_FLAGS = {
    "asr_uncertain",
    "adult_term",
    "speaker_ambiguous",
    "pronoun_ambiguous",
    "onomatopoeia",
    "long_line",
    "possible_noise",
    "needs_context",
}


def simplify_source_text(text: str) -> str:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 100:
        return text
    counts: dict[str, int] = {}
    for char in compact:
        counts[char] = counts.get(char, 0) + 1
    dominant = max(counts.values()) / max(1, len(compact))
    unique = len(counts)
    repeated_noise = dominant > 0.45 or unique <= 12
    soundish = bool(re.search(r"[んあぁはハアぅうっッ♡아青]+", compact))
    if repeated_noise and soundish:
        return "（長い喘ぎ声・キス音・耳舐め音。字幕では简短处理。）"
    return text


def post_json(url: str, api_key: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def extract_json_array(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = repair_json_array(text)
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            raise
        return json.loads(repair_json_array(match.group(0)), strict=False)


def repair_json_array(text: str) -> str:
    """Handle common local-model JSON slips without accepting arbitrary prose."""
    text = text.strip()
    text = re.sub(r"}\s*{", "}, {", text)
    text = re.sub(r"}\s*\n\s*{", "},\n{", text)
    text = re.sub(r"}\s*\n\s*]", "}\n]", text)
    text = re.sub(r",\s*]", "]", text)
    return text


def translate_chunk(
    items: list[dict],
    context_before: list[dict],
    context_after: list[dict],
    *,
    url: str,
    api_key: str,
    model: str,
    timeout: int,
) -> tuple[dict[int, str], dict[int, list[str]]]:
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
                    "把 target_items 中每个 text 从日文翻译成简体中文。"
                    "context_before 和 context_after 只用于理解语义、角色关系、指代和动作连续性。"
                    "不要输出上下文编号，也不要把上下文字幕内容写入 target_items 的译文。"
                    "必须返回与 target_items 同样长度的 JSON 数组，每项格式为 "
                    "{\"i\": 原编号, \"zh\": \"中文字幕\", \"flags\": [\"可选风险标签\"]}。"
                    "flags 只能从 asr_uncertain、adult_term、speaker_ambiguous、pronoun_ambiguous、"
                    "onomatopoeia、long_line、possible_noise、needs_context 中选择；没有风险可为空数组。\n"
                    f"{user_payload}"
                ),
            },
        ],
        "temperature": 0.2,
        "max_tokens": max(1200, sum(len(item["text"]) for item in items) * 4 + 600),
        "chat_template_kwargs": {"enable_thinking": False},
    }
    data = post_json(url, api_key, payload, timeout)
    content = data["choices"][0]["message"].get("content", "")
    translated = extract_json_array(content)
    result: dict[int, str] = {}
    flags: dict[int, list[str]] = {}
    for item in translated:
        if "i" in item and "zh" in item:
            index = int(item["i"])
            result[index] = str(item["zh"]).strip()
            raw_flags = item.get("flags", [])
            if isinstance(raw_flags, list):
                flags[index] = [str(flag).strip() for flag in raw_flags if str(flag).strip() in ALLOWED_FLAGS]
            else:
                flags[index] = []
    missing = [item["i"] for item in items if int(item["i"]) not in result]
    if missing:
        raise ValueError(f"Missing translations for indexes: {missing}; raw={content[:500]}")
    return result, flags


def completed_chunk_count(chunks: list[Chunk], translations: dict[int, str]) -> int:
    return sum(1 for chunk in chunks if all(int(item["i"]) in translations for item in chunk.items))


def progress_postfix(chunk: Chunk, total_subs: int, translated: int) -> str:
    indexes = chunk.target_indexes
    return f"subs {indexes[0]}-{indexes[-1]}/{total_subs} done {translated}/{total_subs}"


def subtitle_to_item(sub: Subtitle) -> dict:
    return {
        "i": sub.index,
        "start": format_srt_timestamp(sub.start),
        "end": format_srt_timestamp(sub.end),
        "text": simplify_source_text(sub.content),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_srt")
    parser.add_argument("output_srt")
    parser.add_argument("--model", default="Qwen3.6-27B-MLX-VL-oQ6")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--chunk-size", type=int, default=18)
    parser.add_argument("--chunk-mode", choices=["dynamic", "fixed"], default="fixed")
    parser.add_argument("--min-chunk-size", type=int, default=6)
    parser.add_argument("--max-chunk-size", type=int, default=24)
    parser.add_argument("--target-chars", type=int, default=900)
    parser.add_argument("--hard-chars", type=int, default=1300)
    parser.add_argument("--context-before", type=int, default=3)
    parser.add_argument("--context-after", type=int, default=3)
    parser.add_argument("--flags-out", default="", help="Write translation risk flags JSON. Defaults to <output>.flags.json.")
    parser.add_argument("--manifest-out", default="", help="Write translation chunk manifest. Defaults to <output>.translate_manifest.json.")
    parser.add_argument("--plan-only", action="store_true", help="Build translation chunk manifest without calling the model.")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--progress-position", type=int, default=0)
    args = parser.parse_args()

    input_path = Path(args.input_srt)
    output_path = Path(args.output_srt)
    partial_path = output_path.with_suffix(output_path.suffix + ".partial.json")
    flags_path = Path(args.flags_out) if args.flags_out else output_path.with_suffix(output_path.suffix + ".flags.json")
    manifest_path = (
        Path(args.manifest_out)
        if args.manifest_out
        else output_path.with_suffix(output_path.suffix + ".translate_manifest.json")
    )
    subs = parse_srt_text(input_path.read_text(encoding="utf-8"))
    translations: dict[int, str] = {}
    flags: dict[int, list[str]] = {}
    if partial_path.exists():
        saved = json.loads(partial_path.read_text(encoding="utf-8"))
        if isinstance(saved, dict) and "translations" in saved:
            translations = {int(key): str(value) for key, value in saved.get("translations", {}).items()}
            flags = {int(key): list(value) for key, value in saved.get("flags", {}).items()}
        else:
            translations = {int(key): str(value) for key, value in saved.items()}
        print(f"RESUMED {len(translations)} translations from {partial_path}", flush=True)
    url = args.base_url.rstrip("/") + "/chat/completions"
    items = [subtitle_to_item(sub) for sub in subs]
    chunks = build_semantic_chunks(
        items,
        mode=args.chunk_mode,
        chunk_size=args.chunk_size,
        min_chunk_size=args.min_chunk_size,
        max_chunk_size=args.max_chunk_size,
        target_chars=args.target_chars,
        hard_chars=args.hard_chars,
        halo=max(args.context_before, args.context_after),
    )
    total_chunks = len(chunks)
    initial_chunks = completed_chunk_count(chunks, translations)
    manifest = {
        "version": 1,
        "input_srt": input_path.as_posix(),
        "output_srt": output_path.as_posix(),
        "settings": {
            "chunk_mode": args.chunk_mode,
            "chunk_size": args.chunk_size,
            "min_chunk_size": args.min_chunk_size,
            "max_chunk_size": args.max_chunk_size,
            "target_chars": args.target_chars,
            "hard_chars": args.hard_chars,
            "context_before": args.context_before,
            "context_after": args.context_after,
            "model": args.model,
            "base_url": args.base_url.rstrip("/"),
        },
        "chunks": [chunk_summary(chunk) for chunk in chunks],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.plan_only:
        print(manifest_path)
        return 0

    with tqdm(
        total=total_chunks,
        desc=input_path.name,
        unit="chunk",
        dynamic_ncols=True,
        initial=initial_chunks,
        position=args.progress_position,
        bar_format="{l_bar}{bar:32}| {n_fmt}/{total_fmt} {unit} [{elapsed}<{remaining}, {rate_fmt}] {postfix}",
    ) as progress:
        for chunk in chunks:
            if all(int(item["i"]) in translations for item in chunk.items):
                continue
            progress.set_postfix_str(progress_postfix(chunk, len(subs), len(translations)))
            last_error: Exception | None = None
            for attempt in range(1, 4):
                try:
                    translated, chunk_flags = translate_chunk(
                        chunk.items,
                        chunk.context_before[-args.context_before :] if args.context_before else [],
                        chunk.context_after[: args.context_after] if args.context_after else [],
                        url=url,
                        api_key=args.api_key,
                        model=args.model,
                        timeout=args.timeout,
                    )
                    translations.update(translated)
                    flags.update(chunk_flags)
                    break
                except Exception as exc:
                    last_error = exc
                    indexes = chunk.target_indexes
                    progress.write(f"RETRY {attempt} failed for {indexes[0]}-{indexes[-1]}: {exc}")
                    time.sleep(1.5 * attempt)
            else:
                indexes = chunk.target_indexes
                raise RuntimeError(f"Failed chunk {indexes[0]}-{indexes[-1]}") from last_error
            partial_path.write_text(
                json.dumps({"translations": translations, "flags": flags}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            progress.update(1)
            progress.set_postfix_str(progress_postfix(chunk, len(subs), len(translations)))
            if args.sleep:
                time.sleep(args.sleep)

    out_subs = []
    missing_output = [sub.index for sub in subs if sub.index not in translations]
    if missing_output:
        raise RuntimeError(f"Missing final translations for indexes: {missing_output}")
    for sub in subs:
        zh = translations[sub.index]
        out_subs.append(Subtitle(index=sub.index, start=sub.start, end=sub.end, content=zh))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(compose_srt_text(out_subs), encoding="utf-8")
    flags_path.parent.mkdir(parents=True, exist_ok=True)
    flags_path.write_text(json.dumps(flags, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if partial_path.exists():
        partial_path.unlink()
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
