#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tqdm import tqdm

from subtitle_io import Subtitle, compose_srt_text, format_srt_timestamp, parse_srt_text
from subtitle_chunking import Chunk, build_semantic_chunks, chunk_summary
from preflight_gate import add_preflight_args, enforce_preflight
from chat_client import chat_completion, error_body, resolve_provider_runtime


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

PROMPT_VERSION = "translate-v2"

PRESETS = {
    "safe": {
        "chunk_mode": "dynamic",
        "chunk_size": 12,
        "min_chunk_size": 6,
        "max_chunk_size": 24,
        "target_chars": 900,
        "hard_chars": 1300,
        "context_before": 3,
        "context_after": 3,
    },
    "fast": {
        "chunk_mode": "dynamic",
        "chunk_size": 18,
        "min_chunk_size": 8,
        "max_chunk_size": 32,
        "target_chars": 1400,
        "hard_chars": 2200,
        "context_before": 2,
        "context_after": 2,
    },
    "turbo": {
        "chunk_mode": "dynamic",
        "chunk_size": 24,
        "min_chunk_size": 10,
        "max_chunk_size": 40,
        "target_chars": 1800,
        "hard_chars": 2600,
        "context_before": 1,
        "context_after": 1,
    },
}

DEFAULT_CHAT_MODEL = "Qwen2.5-32B-Instruct-GGUF-Q4_K_M"


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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        if len(detail) > 1000:
            detail = detail[:1000] + "...[truncated]"
        model = str(payload.get("model") or "")
        message = f"HTTP {exc.code} from {url} while calling model '{model}'."
        if exc.code == 500:
            message += (
                " For local stage switches, common causes are: the previous stage model still occupies memory; "
                "the target model failed to load or is too large; the backend cannot hot-switch models from the "
                "request model field; the model id is wrong; or the service needs a manual reload/restart. "
                "Run scripts/prepare_model_stage.py for the target stage before retrying."
            )
        if detail:
            message += f" Response body: {detail}"
        raise RuntimeError(message) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach {url}: {exc}") from exc


def call_chat(
    *,
    provider: str,
    base_url: str,
    url: str,
    api_key: str,
    model: str,
    payload: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    if provider == "openai-compatible" and url:
        return post_json(url, api_key, payload, timeout)
    try:
        return chat_completion(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            payload=payload,
            timeout=timeout,
        )
    except urllib.error.HTTPError as exc:
        detail = error_body(exc)
        message = f"HTTP {exc.code} from {provider} provider while calling model '{model}'."
        if detail:
            message += f" Response body: {detail}"
        raise RuntimeError(message) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach {provider} provider at {base_url}: {exc}") from exc


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
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    reasoning_token_budget: int,
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
        "max_tokens": max(1200, reasoning_token_budget, sum(len(item["text"]) for item in items) * 4 + 600),
        "chat_template_kwargs": {"enable_thinking": False},
    }
    data = call_chat(
        provider=provider,
        base_url=base_url,
        url=url,
        api_key=api_key,
        model=model,
        payload=payload,
        timeout=timeout,
    )
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


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def chunk_range(chunk: Chunk) -> tuple[int, int]:
    return chunk.target_indexes[0], chunk.target_indexes[-1]


def chunk_signature(
    *,
    chunk: Chunk,
    context_before: list[dict[str, Any]],
    context_after: list[dict[str, Any]],
    model: str,
    base_url: str,
    settings: dict[str, Any],
) -> str:
    payload = {
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "base_url": base_url.rstrip("/"),
        "settings": settings,
        "target_indexes": chunk.target_indexes,
        "items": chunk.items,
        "context_before": context_before,
        "context_after": context_after,
    }
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


def chunk_cache_path(cache_dir: Path, *, chunk_no: int, start_i: int, end_i: int) -> Path:
    return cache_dir / f"chunk_{chunk_no:04d}_{start_i}-{end_i}.json"


def load_cached_chunk(path: Path, signature: str) -> tuple[dict[int, str], dict[int, list[str]]] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("status") != "ok" or data.get("signature") != signature:
        return None
    translations = {int(key): str(value) for key, value in data.get("translations", {}).items()}
    flags = {int(key): list(value) for key, value in data.get("flags", {}).items()}
    return translations, flags


def write_cached_chunk(
    path: Path,
    *,
    signature: str,
    chunk: Chunk,
    translations: dict[int, str],
    flags: dict[int, list[str]],
    model: str,
    base_url: str,
    settings: dict[str, Any],
    duration_sec: float,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "status": "ok",
                "signature": signature,
                "prompt_version": PROMPT_VERSION,
                "model": model,
                "base_url": base_url.rstrip("/"),
                "settings": settings,
                "summary": chunk_summary(chunk),
                "target_indexes": chunk.target_indexes,
                "translations": {str(key): value for key, value in translations.items()},
                "flags": {str(key): value for key, value in flags.items()},
                "duration_sec": duration_sec,
                "updated_at": now_utc(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_profile(path: Path, data: dict[str, Any]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_preset(args: argparse.Namespace) -> None:
    if not args.preset:
        return
    preset = PRESETS[args.preset]
    for key, value in preset.items():
        if getattr(args, key) is None:
            setattr(args, key, value)


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
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--provider", default="openai-compatible", choices=["openai-compatible", "anthropic"])
    parser.add_argument("--provider-profile", default="", help="User-level provider registry profile.")
    parser.add_argument("--provider-registry", default="", help="Override provider registry path.")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="fast")
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--chunk-mode", choices=["dynamic", "fixed"], default=None)
    parser.add_argument("--min-chunk-size", type=int, default=None)
    parser.add_argument("--max-chunk-size", type=int, default=None)
    parser.add_argument("--target-chars", type=int, default=None)
    parser.add_argument("--hard-chars", type=int, default=None)
    parser.add_argument("--context-before", type=int, default=None)
    parser.add_argument("--context-after", type=int, default=None)
    parser.add_argument("--flags-out", default="", help="Write translation risk flags JSON. Defaults to <output>.flags.json.")
    parser.add_argument("--manifest-out", default="", help="Write translation chunk manifest. Defaults to <output>.translate_manifest.json.")
    parser.add_argument("--chunk-cache-dir", default="", help="Directory for resumable translation chunk cache. Defaults to <output_stem>.translate_chunks.")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Ignore cached successful translation chunks.")
    parser.add_argument("--force", action="store_true", help="Rerun all translation chunks even if cached chunks exist.")
    parser.add_argument("--profile", default="", help="Write per-file translation timing profile JSON.")
    parser.add_argument("--plan-only", action="store_true", help="Build translation chunk manifest without calling the model.")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--model-class", default="", help="Optional model class hint, e.g. non_reasoning_instruct or reasoning.")
    parser.add_argument("--reasoning-token-budget", type=int, default=0, help="Minimum max_tokens budget for reasoning/hidden-thinking models. Prefer switching models instead of raising this for bulk translation.")
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--progress-position", type=int, default=0)
    add_preflight_args(parser)
    parser.set_defaults(resume=True)
    args = parser.parse_args()
    enforce_preflight(args, "translate")
    apply_preset(args)
    runtime = resolve_provider_runtime(args, stage="translate")
    args.provider = runtime["provider"]
    args.base_url = runtime["base_url"] or "http://127.0.0.1:8000/v1"
    args.model = runtime["model"] or DEFAULT_CHAT_MODEL
    args.api_key = runtime["api_key"]
    if not args.api_key and not args.plan_only:
        source = f" environment variable {runtime['api_key_env']}" if runtime.get("api_key_env") else " --api-key"
        raise SystemExit(f"API key is missing for translation; set{source}.")

    input_path = Path(args.input_srt)
    output_path = Path(args.output_srt)
    partial_path = output_path.with_suffix(output_path.suffix + ".partial.json")
    flags_path = Path(args.flags_out) if args.flags_out else output_path.with_suffix(output_path.suffix + ".flags.json")
    manifest_path = (
        Path(args.manifest_out)
        if args.manifest_out
        else output_path.with_suffix(output_path.suffix + ".translate_manifest.json")
    )
    chunk_cache_dir = (
        Path(args.chunk_cache_dir)
        if args.chunk_cache_dir
        else output_path.parent / f"{output_path.stem}.translate_chunks"
    )
    profile_path = Path(args.profile) if args.profile else None
    started = time.monotonic()
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
    url = args.base_url.rstrip("/") + "/chat/completions" if args.provider == "openai-compatible" else ""
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
        "prompt_version": PROMPT_VERSION,
        "input_srt": input_path.as_posix(),
        "output_srt": output_path.as_posix(),
        "chunk_cache_dir": chunk_cache_dir.as_posix(),
        "settings": {
            "preset": args.preset,
            "chunk_mode": args.chunk_mode,
            "chunk_size": args.chunk_size,
            "min_chunk_size": args.min_chunk_size,
            "max_chunk_size": args.max_chunk_size,
            "target_chars": args.target_chars,
            "hard_chars": args.hard_chars,
            "context_before": args.context_before,
            "context_after": args.context_after,
            "model": args.model,
            "provider": args.provider,
            "provider_profile": args.provider_profile,
            "base_url": args.base_url.rstrip("/"),
        },
        "chunks": [],
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
        chunk_durations: list[float] = []
        cached_chunks = 0
        retried_chunks = 0
        for chunk in chunks:
            if all(int(item["i"]) in translations for item in chunk.items):
                summary = chunk_summary(chunk)
                summary["status"] = "partial_json"
                manifest["chunks"].append(summary)
                continue
            progress.set_postfix_str(progress_postfix(chunk, len(subs), len(translations)))
            context_before = chunk.context_before[-args.context_before :] if args.context_before else []
            context_after = chunk.context_after[: args.context_after] if args.context_after else []
            signature = chunk_signature(
                chunk=chunk,
                context_before=context_before,
                context_after=context_after,
                model=args.model,
                base_url=args.base_url,
                settings=manifest["settings"],
            )
            start_i, end_i = chunk_range(chunk)
            cache_path = chunk_cache_path(chunk_cache_dir, chunk_no=chunk.chunk_no, start_i=start_i, end_i=end_i)
            cached = None if args.force or not args.resume else load_cached_chunk(cache_path, signature)
            if cached:
                cached_translations, cached_flags = cached
                translations.update(cached_translations)
                flags.update(cached_flags)
                cached_chunks += 1
                summary = chunk_summary(chunk)
                summary["status"] = "cached"
                summary["signature"] = signature
                summary["cache_path"] = cache_path.as_posix()
                manifest["chunks"].append(summary)
                progress.update(1)
                continue
            last_error: Exception | None = None
            chunk_started = time.monotonic()
            attempt_count = 0
            for attempt in range(1, 4):
                attempt_count = attempt
                try:
                    translated, chunk_flags = translate_chunk(
                        chunk.items,
                        context_before,
                        context_after,
                        url=url,
                        provider=args.provider,
                        base_url=args.base_url,
                        api_key=args.api_key,
                        model=args.model,
                        timeout=args.timeout,
                        reasoning_token_budget=args.reasoning_token_budget,
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
            duration_sec = time.monotonic() - chunk_started
            chunk_durations.append(duration_sec)
            if attempt_count > 1:
                retried_chunks += 1
            write_cached_chunk(
                cache_path,
                signature=signature,
                chunk=chunk,
                translations=translated,
                flags=chunk_flags,
                model=args.model,
                base_url=args.base_url,
                settings=manifest["settings"],
                duration_sec=duration_sec,
            )
            summary = chunk_summary(chunk)
            summary["status"] = "ok"
            summary["signature"] = signature
            summary["cache_path"] = cache_path.as_posix()
            summary["duration_sec"] = duration_sec
            summary["attempts"] = attempt_count
            manifest["chunks"].append(summary)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    finished = time.monotonic()
    profile = {
        "version": 1,
        "stage": "translate",
        "input_srt": input_path.as_posix(),
        "output_srt": output_path.as_posix(),
        "duration_sec": finished - started,
        "chunks": total_chunks,
        "cached_chunks": cached_chunks if "cached_chunks" in locals() else 0,
        "retried_chunks": retried_chunks if "retried_chunks" in locals() else 0,
        "avg_uncached_sec_per_chunk": (
            sum(chunk_durations) / len(chunk_durations) if "chunk_durations" in locals() and chunk_durations else 0.0
        ),
        "settings": manifest["settings"],
        "updated_at": now_utc(),
    }
    if profile_path:
        write_profile(profile_path, profile)
    manifest["profile"] = profile
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
