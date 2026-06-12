#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

import srt
from tqdm import tqdm


SYSTEM_PROMPT = """你是专业的日译中 ASMR 字幕翻译器。
要求：
- 输出自然、有人情味、符合情境的简体中文。
- 保留亲密、撒娇、停顿、耳语的感觉，但不要生硬直译。
- 拟声词、喘息、亲吻/耳语/摩擦等重复声音可以简化为短中文或方括号提示，例如「[耳语]」「[亲吻声]」「……」。
- 修正常见 ASR 错字，但不要改写剧情。
- 只返回 JSON 数组，不要解释，不要 Markdown。
"""


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
    *,
    url: str,
    api_key: str,
    model: str,
    timeout: int,
) -> dict[int, str]:
    user_payload = json.dumps(items, ensure_ascii=False, indent=2)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "把下面 JSON 数组中每个 text 从日文翻译成简体中文。"
                    "必须返回同样长度的 JSON 数组，每项格式为 {\"i\": 原编号, \"zh\": \"中文字幕\"}。\n"
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
    for item in translated:
        if "i" in item and "zh" in item:
            result[int(item["i"])] = str(item["zh"]).strip()
    missing = [item["i"] for item in items if int(item["i"]) not in result]
    if missing:
        raise ValueError(f"Missing translations for indexes: {missing}; raw={content[:500]}")
    return result


def completed_chunk_count(subs: list[srt.Subtitle], chunk_size: int, translations: dict[int, str]) -> int:
    return sum(
        1
        for start in range(0, len(subs), chunk_size)
        if all(sub.index in translations for sub in subs[start : start + chunk_size])
    )


def progress_postfix(start: int, chunk_len: int, total_subs: int, translated: int) -> str:
    return f"subs {start + 1}-{start + chunk_len}/{total_subs} done {translated}/{total_subs}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_srt")
    parser.add_argument("output_srt")
    parser.add_argument("--model", default="Qwen3.6-27B-MLX-VL-oQ6")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--chunk-size", type=int, default=18)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--progress-position", type=int, default=0)
    args = parser.parse_args()

    input_path = Path(args.input_srt)
    output_path = Path(args.output_srt)
    partial_path = output_path.with_suffix(output_path.suffix + ".partial.json")
    subs = list(srt.parse(input_path.read_text(encoding="utf-8")))
    translations: dict[int, str] = {}
    if partial_path.exists():
        saved = json.loads(partial_path.read_text(encoding="utf-8"))
        translations = {int(key): str(value) for key, value in saved.items()}
        print(f"RESUMED {len(translations)} translations from {partial_path}", flush=True)
    url = args.base_url.rstrip("/") + "/chat/completions"
    total_chunks = (len(subs) + args.chunk_size - 1) // args.chunk_size
    initial_chunks = completed_chunk_count(subs, args.chunk_size, translations)

    with tqdm(
        total=total_chunks,
        desc=input_path.name,
        unit="chunk",
        dynamic_ncols=True,
        initial=initial_chunks,
        position=args.progress_position,
        bar_format="{l_bar}{bar:32}| {n_fmt}/{total_fmt} {unit} [{elapsed}<{remaining}, {rate_fmt}] {postfix}",
    ) as progress:
        for start in range(0, len(subs), args.chunk_size):
            chunk = subs[start : start + args.chunk_size]
            if all(sub.index in translations for sub in chunk):
                continue
            items = [{"i": sub.index, "text": simplify_source_text(sub.content)} for sub in chunk]
            progress.set_postfix_str(progress_postfix(start, len(chunk), len(subs), len(translations)))
            last_error: Exception | None = None
            for attempt in range(1, 4):
                try:
                    translations.update(
                        translate_chunk(items, url=url, api_key=args.api_key, model=args.model, timeout=args.timeout)
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    progress.write(f"RETRY {attempt} failed for {start + 1}-{start + len(chunk)}: {exc}")
                    time.sleep(1.5 * attempt)
            else:
                raise RuntimeError(f"Failed chunk {start + 1}-{start + len(chunk)}") from last_error
            partial_path.write_text(json.dumps(translations, ensure_ascii=False, indent=2), encoding="utf-8")
            progress.update(1)
            progress.set_postfix_str(progress_postfix(start, len(chunk), len(subs), len(translations)))
            if args.sleep:
                time.sleep(args.sleep)

    out_subs = []
    for sub in subs:
        zh = translations[sub.index]
        out_subs.append(srt.Subtitle(index=sub.index, start=sub.start, end=sub.end, content=zh))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(srt.compose(out_subs), encoding="utf-8")
    if partial_path.exists():
        partial_path.unlink()
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
