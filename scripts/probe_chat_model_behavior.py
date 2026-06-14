#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chat_client import chat_completion, resolve_provider_runtime

THINKING_MARKERS = ("<think>", "</think>", "thinking", "reasoning")


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_prompt(style: str) -> str:
    if style == "json":
        return "请只输出一个合法 JSON 对象，不要解释。内容为 {\"ok\": true}。"
    return "请只输出一句极短中文，不要解释，不要思考过程。"


def build_payload(model: str, *, style: str, no_thinking: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "只输出最终答案，不要思考过程。"},
            {"role": "user", "content": build_prompt(style)},
        ],
        "temperature": 0,
        "max_tokens": 96,
    }
    if no_thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        payload["thinking_budget"] = 0
    return payload


def summarize_content(content: str) -> dict[str, Any]:
    stripped = content.strip()
    has_think = any(marker in stripped.lower() for marker in THINKING_MARKERS)
    return {
        "empty": not bool(stripped),
        "len": len(stripped),
        "has_think_markers": has_think,
        "preview": stripped[:240],
    }


def run_probe(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    style: str,
    no_thinking: bool,
    timeout: float,
) -> dict[str, Any]:
    payload = build_payload(model, style=style, no_thinking=no_thinking)
    started = time.monotonic()
    response = chat_completion(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        payload=payload,
        timeout=timeout,
    )
    elapsed = time.monotonic() - started
    content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
    summary = summarize_content(str(content))
    return {
        "style": style,
        "no_thinking": no_thinking,
        "elapsed_sec": round(elapsed, 3),
        "response": summary,
        "raw_preview": str(content).strip()[:400],
    }


def classify_http_error(probe: dict[str, Any]) -> tuple[str, str]:
    code = int(probe.get("http_code") or 0)
    error = str(probe.get("error") or "").strip()
    if code == 401:
        return "auth_failed", "本地服务拒绝 API key；尚未进入模型加载或推理阶段。"
    if code == 404:
        return "model_not_found", "模型 id 不在本地服务的 /models 列表中；请使用后端暴露的精确模型名。"
    if code >= 500:
        return "model_load_failed", "本地服务返回 5xx；通常是模型加载、权重/架构兼容、显存/内存或后端热切换问题，不是输出 thinking 的问题。"
    return "backend_http_error", f"本地服务返回 HTTP {code}；请求被后端拒绝。{error[:160]}"


def classify(probes: list[dict[str, Any]], *, max_reasonable_sec: float) -> tuple[str, list[str]]:
    notes: list[str] = []
    no_thinking_clean = True
    any_empty = False
    slow_count = 0
    json_ok = True
    http_errors = [probe for probe in probes if probe.get("status") == "http_error"]
    if http_errors:
        first_verdict, first_note = classify_http_error(http_errors[0])
        notes.append(first_note)
        plain_ok = any(probe.get("status") == "ok" and not probe.get("no_thinking") for probe in probes)
        no_thinking_failed = any(probe.get("status") == "http_error" and probe.get("no_thinking") for probe in probes)
        plain_failed = any(probe.get("status") == "http_error" and not probe.get("no_thinking") for probe in probes)
        if plain_ok and no_thinking_failed:
            notes.append("普通请求可用，但 no-thinking 请求失败；该后端/模型可能不接受 chat_template_kwargs 或 thinking_budget。")
            return "no_thinking_payload_rejected", notes
        if plain_failed:
            notes.append("普通请求也失败；问题发生在模型可用性/加载阶段，不能归因于 no-thinking 参数。")
        return first_verdict, notes
    for probe in probes:
        elapsed = float(probe["elapsed_sec"])
        resp = probe["response"]
        if elapsed > max_reasonable_sec:
            slow_count += 1
        if resp.get("empty"):
            any_empty = True
        if probe.get("no_thinking") and resp.get("has_think_markers"):
            no_thinking_clean = False
        if probe["style"] == "json":
            preview = str(probe.get("raw_preview", "")).strip()
            if not (preview.startswith("{") and preview.endswith("}")):
                json_ok = False
    if any_empty:
        notes.append("至少一个探测返回空响应，说明该模型/后端在当前参数下有空回包风险。")
    if slow_count >= 2:
        notes.append("多次探测都超过阈值，说明该模型可能不适合作为批量字幕翻译主模型。")
    if no_thinking_clean is False:
        notes.append("探测中仍可见思考痕迹或思考标签，no-thinking 可能没有真正生效。")
    if not json_ok:
        notes.append("JSON 探测未稳定返回可解析对象，翻译/QC JSON 输出风险较高。")
    if any_empty or slow_count >= 2 or not json_ok:
        return "too_slow_reasoning_model", notes
    if no_thinking_clean is False:
        return "no_thinking_not_effective", notes
    return "ok_for_translation", notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe whether a local chat model behaves like a fast non-reasoning model.")
    parser.add_argument("base_url")
    parser.add_argument("model")
    parser.add_argument("--provider", default="openai-compatible", choices=["openai-compatible", "anthropic"])
    parser.add_argument("--provider-profile", default="")
    parser.add_argument("--provider-registry", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-reasonable-sec", type=float, default=12.0)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--allow-fail", action="store_true")
    args = parser.parse_args()
    runtime = resolve_provider_runtime(args, stage="translate")
    provider = runtime["provider"]
    base_url = runtime["base_url"] or args.base_url.rstrip("/")
    model = runtime["model"] or args.model
    api_key = runtime["api_key"]

    probes: list[dict[str, Any]] = []
    for style, no_thinking in [("plain", False), ("plain", True), ("json", True)]:
        started = time.monotonic()
        try:
            result = run_probe(
                provider=provider,
                base_url=base_url,
                api_key=api_key,
                model=model,
                style=style,
                no_thinking=no_thinking,
                timeout=args.timeout,
            )
            result["status"] = "ok"
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                body = ""
            result = {
                "style": style,
                "no_thinking": no_thinking,
                "elapsed_sec": round(time.monotonic() - started, 3),
                "status": "http_error",
                "http_code": exc.code,
                "error": body[:400],
                "response": {"empty": True, "len": 0, "has_think_markers": False, "preview": ""},
                "raw_preview": "",
            }
        except Exception as exc:  # pragma: no cover
            result = {
                "style": style,
                "no_thinking": no_thinking,
                "elapsed_sec": round(time.monotonic() - started, 3),
                "status": "error",
                "error": str(exc),
                "response": {"empty": True, "len": 0, "has_think_markers": False, "preview": ""},
                "raw_preview": "",
            }
        probes.append(result)

    verdict, notes = classify(probes, max_reasonable_sec=args.max_reasonable_sec)
    report = {
        "schema_version": 1,
        "created_at": now_utc(),
        "provider": provider,
        "provider_profile": args.provider_profile,
        "base_url": base_url,
        "model": model,
        "verdict": verdict,
        "notes": notes,
        "probes": probes,
    }
    if args.json_out:
        write_json(Path(args.json_out), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if verdict == "ok_for_translation" or args.allow_fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
