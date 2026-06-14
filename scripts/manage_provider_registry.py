#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REGISTRY_NAME = "providers.json"
REGISTRY_VERSION = 1
PROVIDERS = {"openai-compatible", "anthropic"}
CHAT_STAGES = {"translate", "qc"}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def registry_home() -> Path:
    value = os.environ.get("ASMR_BBQ_HOME")
    if value:
        return Path(value).expanduser()
    return Path.home() / "ASMR-BBQ"


def registry_path(path: str = "") -> Path:
    return Path(path).expanduser() if path else registry_home() / REGISTRY_NAME


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def empty_registry() -> dict[str, Any]:
    return {
        "schema_version": REGISTRY_VERSION,
        "description": "User-level provider registry for ASMR-BBQ. No API keys or secrets.",
        "updated_at": now_utc(),
        "profiles": {},
    }


def load_registry(path: Path | None = None) -> dict[str, Any]:
    target = path or registry_path()
    if target.exists():
        data = read_json(target)
        data.setdefault("profiles", {})
        return data
    return empty_registry()


def save_registry(path: Path, data: dict[str, Any]) -> None:
    data["schema_version"] = REGISTRY_VERSION
    data["updated_at"] = now_utc()
    write_json(path, data)


def normalize_base_url(value: str, provider: str = "openai-compatible") -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid base URL: {value}")
    normalized = raw.rstrip("/")
    parsed = urlparse(normalized)
    if provider == "openai-compatible" and parsed.path in {"", "/"}:
        normalized += "/v1"
    return normalized


def public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(profile)
    cleaned.pop("api_key", None)
    return cleaned


def validate_profile(profile: dict[str, Any]) -> None:
    if "api_key" in profile:
        raise ValueError("Provider profiles must not contain plaintext api_key.")
    provider = str(profile.get("provider") or "")
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    if not profile.get("api_key_env"):
        raise ValueError("Provider profile requires api_key_env; store the key in an environment variable.")
    if not profile.get("base_url"):
        raise ValueError("Provider profile requires base_url.")
    if not profile.get("default_model"):
        raise ValueError("Provider profile requires default_model.")
    stages = profile.get("stages", [])
    if not isinstance(stages, list) or not stages:
        raise ValueError("Provider profile requires at least one stage.")
    invalid = sorted(set(str(stage) for stage in stages) - CHAT_STAGES)
    if invalid:
        raise ValueError(f"Unsupported stage(s): {', '.join(invalid)}")


def resolve_profile(
    name: str,
    *,
    registry: dict[str, Any] | None = None,
    path: Path | None = None,
    stage: str = "",
) -> dict[str, Any]:
    data = registry or load_registry(path)
    profiles = data.get("profiles", {}) if isinstance(data.get("profiles"), dict) else {}
    profile = profiles.get(name)
    if not isinstance(profile, dict):
        raise KeyError(f"Provider profile not found: {name}")
    validate_profile(profile)
    if stage and stage not in profile.get("stages", []):
        raise ValueError(f"Provider profile '{name}' is not enabled for stage '{stage}'.")
    result = public_profile(profile)
    result["name"] = name
    result["api_key"] = os.environ.get(str(profile.get("api_key_env") or ""), "")
    return result


def build_profile(args: argparse.Namespace, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    stages = sorted(set(args.stage or (existing or {}).get("stages", []) or ["translate", "qc"]))
    provider = args.provider or (existing or {}).get("provider", "")
    base_url = args.base_url or (existing or {}).get("base_url", "")
    profile = {
        "provider": provider,
        "base_url": normalize_base_url(base_url, provider) if base_url else "",
        "default_model": args.model or (existing or {}).get("default_model", ""),
        "api_key_env": args.api_key_env or (existing or {}).get("api_key_env", ""),
        "stages": stages,
        "updated_at": now_utc(),
    }
    if existing and existing.get("created_at"):
        profile["created_at"] = existing["created_at"]
    else:
        profile["created_at"] = now_utc()
    if args.note:
        profile["notes"] = [str(note) for note in args.note if str(note).strip()]
    elif existing and existing.get("notes"):
        profile["notes"] = existing["notes"]
    validate_profile(profile)
    return profile


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="Manage user-level cloud/local chat provider profiles. No API keys are stored.")
    parser.add_argument("--registry", default="", help="Override registry path. Defaults to ${ASMR_BBQ_HOME:-~/ASMR-BBQ}/providers.json.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_registry_arg(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--registry", default=argparse.SUPPRESS, help="Override registry path.")

    for command in ("add", "update"):
        sub = subparsers.add_parser(command, help=f"{command} a provider profile.")
        add_registry_arg(sub)
        sub.add_argument("--name", required=True)
        sub.add_argument("--provider", choices=sorted(PROVIDERS), required=(command == "add"))
        sub.add_argument("--base-url", required=(command == "add"))
        sub.add_argument("--model", required=(command == "add"), help="Default model id for this provider profile.")
        sub.add_argument("--api-key-env", required=(command == "add"), help="Environment variable name containing the API key.")
        sub.add_argument("--stage", action="append", choices=sorted(CHAT_STAGES), default=[])
        sub.add_argument("--note", action="append", default=[])

    show = subparsers.add_parser("show", help="Show one provider profile without secrets.")
    add_registry_arg(show)
    show.add_argument("name")
    show.add_argument("--json", action="store_true")

    list_parser = subparsers.add_parser("list", help="List provider profiles.")
    add_registry_arg(list_parser)
    list_parser.add_argument("--json", action="store_true")

    remove = subparsers.add_parser("remove", help="Remove one provider profile.")
    add_registry_arg(remove)
    remove.add_argument("name")

    test = subparsers.add_parser("test", help="Resolve a profile and optionally make a tiny chat probe.")
    add_registry_arg(test)
    test.add_argument("name")
    test.add_argument("--stage", choices=sorted(CHAT_STAGES), default="")
    test.add_argument("--model", default="", help="Override model for the probe.")
    test.add_argument("--timeout", type=float, default=20.0)
    test.add_argument("--skip-api", action="store_true")
    test.add_argument("--json", action="store_true")

    return parser.parse_known_args()


def main() -> int:
    args, unknown = parse_args()
    if any(arg == "--api-key" or arg.startswith("--api-key=") for arg in unknown):
        raise SystemExit("Do not pass plaintext API keys to this tool. Store the key in the named environment variable.")
    if unknown:
        raise SystemExit("Unknown arguments: " + " ".join(unknown))

    path = registry_path(args.registry)
    registry = load_registry(path)
    profiles = registry.setdefault("profiles", {})

    if args.command in {"add", "update"}:
        existing = profiles.get(args.name)
        if args.command == "add" and existing:
            raise SystemExit(f"Provider profile exists: {args.name}; use update.")
        if args.command == "update" and not existing:
            raise SystemExit(f"Provider profile does not exist: {args.name}; use add.")
        profiles[args.name] = build_profile(args, existing if isinstance(existing, dict) else None)
        save_registry(path, registry)
        print(path.as_posix())
        return 0

    if args.command == "show":
        profile = resolve_profile(args.name, registry=registry)
        profile.pop("api_key", None)
        if args.json:
            print(json.dumps(profile, ensure_ascii=False, indent=2))
        else:
            print(f"name: {args.name}")
            print(f"provider: {profile.get('provider', '')}")
            print(f"base_url: {profile.get('base_url', '')}")
            print(f"default_model: {profile.get('default_model', '')}")
            print(f"api_key_env: {profile.get('api_key_env', '')}")
            print(f"stages: {', '.join(profile.get('stages', []))}")
        return 0

    if args.command == "list":
        names = sorted(profiles)
        if args.json:
            print(json.dumps({"registry": path.as_posix(), "profiles": names}, ensure_ascii=False, indent=2))
        else:
            print(path.as_posix())
            for name in names:
                profile = profiles.get(name, {})
                print(f"- {name}: {profile.get('provider', '')} {profile.get('base_url', '')} model={profile.get('default_model', '')}")
        return 0

    if args.command == "remove":
        if args.name not in profiles:
            raise SystemExit(f"Provider profile not found: {args.name}")
        profiles.pop(args.name)
        save_registry(path, registry)
        print(path.as_posix())
        return 0

    if args.command == "test":
        from chat_client import build_chat_probe, chat_completion, list_models

        profile = resolve_profile(args.name, registry=registry, stage=args.stage)
        model = args.model or str(profile.get("default_model") or "")
        report: dict[str, Any] = {
            "profile": args.name,
            "provider": profile.get("provider", ""),
            "base_url": profile.get("base_url", ""),
            "model": model,
            "api_key_env": profile.get("api_key_env", ""),
            "api_key_present": bool(profile.get("api_key")),
            "checks": [],
        }
        if not profile.get("api_key"):
            report["checks"].append({"name": "api_key_env", "status": "FAIL", "message": f"Environment variable is not set: {profile.get('api_key_env', '')}"})
        elif args.skip_api:
            report["checks"].append({"name": "api_probe", "status": "WARN", "message": "Skipped live API checks by request."})
        else:
            if profile.get("provider") == "openai-compatible":
                try:
                    ids = list_models(base_url=str(profile["base_url"]), api_key=str(profile["api_key"]), timeout=args.timeout)
                    report["checks"].append({"name": "models_endpoint", "status": "OK" if model in ids else "WARN", "message": "Model listed by /models." if model in ids else "Model was not found in /models.", "models": ids[:20]})
                except Exception as exc:
                    report["checks"].append({"name": "models_endpoint", "status": "WARN", "message": str(exc)})
            try:
                chat_completion(
                    provider=str(profile["provider"]),
                    base_url=str(profile["base_url"]),
                    api_key=str(profile["api_key"]),
                    model=model,
                    payload=build_chat_probe(model),
                    timeout=args.timeout,
                )
                report["checks"].append({"name": "chat_probe", "status": "OK", "message": "Tiny chat probe succeeded."})
            except Exception as exc:
                report["checks"].append({"name": "chat_probe", "status": "FAIL", "message": str(exc)})
        report["status"] = "FAIL" if any(check["status"] == "FAIL" for check in report["checks"]) else ("WARN" if any(check["status"] == "WARN" for check in report["checks"]) else "OK")
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"PROVIDER {args.name} {report['status']}")
            for check in report["checks"]:
                print(f"{check['status']}: {check['name']}: {check['message']}")
        return 0 if report["status"] != "FAIL" else 1

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
