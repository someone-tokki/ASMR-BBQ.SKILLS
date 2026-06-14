#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


OPENAI_COMPATIBLE_KEYS = {
    "model",
    "messages",
    "temperature",
    "max_tokens",
    "top_p",
    "stop",
    "stream",
    "presence_penalty",
    "frequency_penalty",
    "chat_template_kwargs",
    "thinking_budget",
}
ANTHROPIC_KEYS = {"model", "messages", "temperature", "max_tokens", "top_p", "stop_sequences", "system"}


def endpoint(base_url: str, suffix: str) -> str:
    return base_url.rstrip("/") + "/" + suffix.lstrip("/")


def error_body(exc: urllib.error.HTTPError) -> str:
    try:
        detail = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        detail = ""
    if len(detail) > 1000:
        detail = detail[:1000] + "...[truncated]"
    return detail


def request_json(
    url: str,
    *,
    method: str = "POST",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw) if raw.strip() else {}


def compact_payload(payload: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key in allowed and value is not None}


def anthropic_payload(payload: dict[str, Any], model: str) -> dict[str, Any]:
    system_parts: list[str] = []
    messages: list[dict[str, str]] = []
    for message in payload.get("messages", []):
        role = str(message.get("role", "user"))
        content = str(message.get("content", ""))
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        messages.append({"role": role, "content": content})
    result: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": int(payload.get("max_tokens") or 1024),
    }
    if system_parts:
        result["system"] = "\n\n".join(system_parts)
    for source, target in [("temperature", "temperature"), ("top_p", "top_p"), ("stop", "stop_sequences")]:
        if source in payload and payload[source] is not None:
            result[target] = payload[source]
    return compact_payload(result, ANTHROPIC_KEYS)


def normalize_anthropic_response(data: dict[str, Any]) -> dict[str, Any]:
    parts: list[str] = []
    for item in data.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return {
        "id": data.get("id", ""),
        "model": data.get("model", ""),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "".join(parts)},
                "finish_reason": data.get("stop_reason", ""),
            }
        ],
        "usage": data.get("usage", {}),
        "provider_raw": {"type": "anthropic_messages"},
    }


def chat_completion(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    provider = provider or "openai-compatible"
    if not api_key:
        raise RuntimeError("API key is missing. Set the configured environment variable or pass --api-key for this run.")
    if provider == "openai-compatible":
        body = compact_payload({**payload, "model": model}, OPENAI_COMPATIBLE_KEYS)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        return request_json(endpoint(base_url, "/chat/completions"), payload=body, headers=headers, timeout=timeout)
    if provider == "anthropic":
        body = anthropic_payload(payload, model)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        data = request_json(endpoint(base_url, "/v1/messages"), payload=body, headers=headers, timeout=timeout)
        return normalize_anthropic_response(data)
    raise RuntimeError(f"Unsupported provider: {provider}")


def list_models(*, base_url: str, api_key: str, timeout: float) -> list[str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = request_json(endpoint(base_url, "/models"), method="GET", headers=headers, timeout=timeout)
    values = data.get("data")
    if isinstance(values, list):
        ids: list[str] = []
        for item in values:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
            elif isinstance(item, str):
                ids.append(item)
        return ids
    models = data.get("models")
    if isinstance(models, list):
        ids = []
        for item in models:
            if isinstance(item, dict) and item.get("name"):
                ids.append(str(item["name"]))
            elif isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
            elif isinstance(item, str):
                ids.append(item)
        return ids
    return []


def build_chat_probe(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "Reply with OK only."},
            {"role": "user", "content": "ping"},
        ],
        "temperature": 0,
        "max_tokens": 8,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def resolve_provider_runtime(args: Any, *, stage: str = "") -> dict[str, str]:
    from manage_provider_registry import registry_path, resolve_profile

    local_default_base_url = "http://127.0.0.1:8000/v1"
    profile_name = str(getattr(args, "provider_profile", "") or "")
    provider = str(getattr(args, "provider", "") or "openai-compatible")
    base_url = str(getattr(args, "base_url", "") or "")
    model = str(getattr(args, "model", "") or "")
    api_key = str(getattr(args, "api_key", "") or "")
    api_key_env = ""
    if profile_name:
        registry = registry_path(str(getattr(args, "provider_registry", "") or ""))
        profile = resolve_profile(profile_name, path=registry, stage=stage)
        provider = str(getattr(args, "provider", "") or profile.get("provider") or provider)
        if not base_url or base_url.rstrip("/") == local_default_base_url:
            base_url = str(profile.get("base_url") or "")
        model = model or str(profile.get("default_model") or "")
        api_key = api_key or str(profile.get("api_key") or "")
        api_key_env = str(profile.get("api_key_env") or "")
    return {
        "provider_profile": profile_name,
        "provider": provider,
        "base_url": base_url.rstrip("/"),
        "model": model,
        "api_key": api_key,
        "api_key_env": api_key_env,
    }
