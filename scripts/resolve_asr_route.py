#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from shared_asr_env import shared_whisper_available, shared_whisper_python


PLATFORM_ASR_CANDIDATES = [
    "http://127.0.0.1:8000/v1",
    "http://127.0.0.1:1234/v1",
    "http://127.0.0.1:11434/v1",
]
ASR_ENDPOINT_EXISTS_CODES = {400, 401, 403, 405, 415, 422}


def read_config(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    target = path if path.name == "project_config.json" else path / "project_config.json"
    if not target.exists():
        return {}
    data = json.loads(target.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def path_from_config(config: dict[str, Any], key: str) -> Path | None:
    value = config.get("paths", {}).get(key, "") if isinstance(config.get("paths"), dict) else ""
    if not value:
        return None
    return Path(str(value)).expanduser()


def existing_asr_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.exists() and path.is_dir():
            files.extend(sorted(path.glob("*.ja.asr.srt")))
        elif path.exists() and path.is_file() and path.name.endswith(".ja.asr.srt"):
            files.append(path)
    return files


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def python_whisper_available() -> bool:
    return module_available("whisper") or shared_whisper_available()


def python_whisper_next_action() -> str:
    if shared_whisper_available() and not module_available("whisper"):
        return f"Run scripts/transcribe_whisper.py; it will delegate to the shared Whisper Python at {shared_whisper_python().as_posix()}."
    return "Run scripts/transcribe_whisper.py with the local Python openai-whisper package."


def model_value(config: dict[str, Any], key: str) -> str:
    models = config.get("models", {}) if isinstance(config.get("models"), dict) else {}
    return str(models.get(key, "") or "").strip()


def whisper_model(args: argparse.Namespace, config: dict[str, Any]) -> str:
    return args.asr_model.strip() or model_value(config, "asr_model") or "large-v3"


def normalize_base_url(value: str) -> str:
    return value.strip().rstrip("/")


def audio_transcriptions_url(base_url: str) -> str:
    return normalize_base_url(base_url) + "/audio/transcriptions"


def probe_audio_transcriptions(base_url: str, timeout: float) -> dict[str, Any]:
    url = audio_transcriptions_url(base_url)
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = getattr(response, "status", 200)
        return {"base_url": normalize_base_url(base_url), "ok": True, "status_code": status_code, "detail": f"GET {url} -> HTTP {status_code}"}
    except urllib.error.HTTPError as exc:
        ok = exc.code in ASR_ENDPOINT_EXISTS_CODES
        return {"base_url": normalize_base_url(base_url), "ok": ok, "status_code": exc.code, "detail": f"GET {url} -> HTTP {exc.code}"}
    except Exception as exc:
        return {"base_url": normalize_base_url(base_url), "ok": False, "status_code": None, "detail": f"Cannot reach {url}: {exc}"}


def dedupe_urls(values: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_base_url(value)
        if normalized and normalized not in seen:
            urls.append(normalized)
            seen.add(normalized)
    return urls


def platform_asr_candidates(args: argparse.Namespace, config: dict[str, Any]) -> list[str]:
    values: list[str] = []
    values.extend(args.platform_base_url or [])
    translate_base_url = model_value(config, "translate_base_url")
    if translate_base_url:
        values.append(translate_base_url)
    translate_backend = model_value(config, "translate_backend").lower()
    if translate_backend == "ollama":
        values.append("http://127.0.0.1:11434/v1")
    elif translate_backend == "lmstudio":
        values.append("http://127.0.0.1:1234/v1")
    elif translate_backend in {"omlx", "openai-compatible", "auto", ""}:
        values.append("http://127.0.0.1:8000/v1")
    values.extend(PLATFORM_ASR_CANDIDATES)
    return dedupe_urls(values)


def first_working_asr_api(candidates: list[str], timeout: float) -> tuple[str, list[dict[str, Any]]]:
    probes: list[dict[str, Any]] = []
    for base_url in candidates:
        result = probe_audio_transcriptions(base_url, timeout)
        probes.append(result)
        if result["ok"]:
            return result["base_url"], probes
    return "", probes


def build_route(args: argparse.Namespace) -> dict[str, Any]:
    config = read_config(Path(args.config).expanduser() if args.config else None)
    models = config.get("models", {}) if isinstance(config.get("models"), dict) else {}
    configured_backend = str(args.asr_backend or models.get("asr_backend", "") or "auto").strip().lower()

    asr_paths: list[Path] = []
    if args.asr_dir:
        asr_paths.append(Path(args.asr_dir).expanduser())
    for key in ("asr_dir", "promo_asr_dir"):
        path = path_from_config(config, key)
        if path:
            asr_paths.append(path)
    asr_files = existing_asr_files(asr_paths)

    if asr_files and not args.require_new_asr:
        return {
            "status": "ok",
            "decision": "reuse_existing_asr",
            "asr_backend": configured_backend,
            "existing_asr_count": len(asr_files),
            "existing_asr_files": [path.as_posix() for path in asr_files],
            "next_action": "Skip new ASR and continue with structure validation, translation, QC, or export.",
            "blocked_reason": "",
        }

    if configured_backend in {"", "auto"}:
        model = whisper_model(args, config)
        platform_base_url, platform_probes = first_working_asr_api(platform_asr_candidates(args, config), args.probe_timeout)
        if platform_base_url:
            return {
                "status": "ok",
                "decision": "run_local_platform_asr_api",
                "asr_backend": "local-platform-asr-api",
                "asr_base_url": platform_base_url,
                "asr_model": model,
                "existing_asr_count": len(asr_files),
                "existing_asr_files": [path.as_posix() for path in asr_files],
                "probes": platform_probes,
                "next_action": "Run scripts/transcribe_openai_audio.py against the detected local platform /audio/transcriptions endpoint.",
                "blocked_reason": "",
            }
        explicit_asr_base_urls = dedupe_urls([args.asr_base_url, model_value(config, "asr_base_url")])
        explicit_base_url, explicit_probes = first_working_asr_api(explicit_asr_base_urls, args.probe_timeout)
        if explicit_base_url:
            return {
                "status": "ok",
                "decision": "run_local_asr_api",
                "asr_backend": "local-asr-api",
                "asr_base_url": explicit_base_url,
                "asr_model": model,
                "existing_asr_count": len(asr_files),
                "existing_asr_files": [path.as_posix() for path in asr_files],
                "probes": platform_probes + explicit_probes,
                "next_action": "Run scripts/transcribe_openai_audio.py against the configured local ASR API endpoint.",
                "blocked_reason": "",
            }
        if python_whisper_available():
            return {
                "status": "ok",
                "decision": "run_python_whisper",
                "asr_backend": "python-whisper",
                "asr_model": model,
                "shared_whisper_python": shared_whisper_python().as_posix() if shared_whisper_available() else "",
                "existing_asr_count": len(asr_files),
                "existing_asr_files": [path.as_posix() for path in asr_files],
                "probes": platform_probes + explicit_probes,
                "next_action": python_whisper_next_action(),
                "blocked_reason": "",
            }
        return {
            "status": "blocked",
            "decision": "setup_python_whisper_required",
            "asr_backend": "python-whisper",
            "asr_model": model,
            "existing_asr_count": len(asr_files),
            "existing_asr_files": [path.as_posix() for path in asr_files],
            "probes": platform_probes + explicit_probes,
            "next_action": "After user approval, run scripts/setup_whisper_backend.py --install-package --download-model --model <model>, then run scripts/transcribe_whisper.py. The setup script uses the shared user ASR venv by default.",
            "blocked_reason": "No reachable local platform/local ASR API was detected and Python Whisper is not available in the current interpreter or shared user ASR venv. Use the packaged setup script; do not guess other ASR backends.",
        }

    if configured_backend in {"python-whisper", "whisper", "openai-whisper"}:
        model = whisper_model(args, config)
        ready = python_whisper_available()
        return {
            "status": "ok" if ready else "blocked",
            "decision": "run_python_whisper" if ready else "setup_python_whisper_required",
            "asr_backend": "python-whisper",
            "asr_model": model,
            "shared_whisper_python": shared_whisper_python().as_posix() if shared_whisper_available() else "",
            "existing_asr_count": len(asr_files),
            "existing_asr_files": [path.as_posix() for path in asr_files],
            "next_action": python_whisper_next_action() if ready else "After user approval, run scripts/setup_whisper_backend.py --install-package --download-model --model <model>. The setup script uses the shared user ASR venv by default.",
            "blocked_reason": "" if ready else "Python Whisper is not available in the current interpreter or shared user ASR venv.",
        }

    if configured_backend in {"local-asr-api", "openai-audio", "local-service"}:
        base_url = args.asr_base_url.strip() or model_value(config, "asr_base_url") or model_value(config, "translate_base_url") or "http://127.0.0.1:8000/v1"
        probe = probe_audio_transcriptions(base_url, args.probe_timeout)
        if not probe["ok"]:
            return {
                "status": "blocked",
                "decision": "local_asr_api_unreachable",
                "asr_backend": configured_backend,
                "asr_base_url": normalize_base_url(base_url),
                "asr_model": whisper_model(args, config),
                "existing_asr_count": len(asr_files),
                "existing_asr_files": [path.as_posix() for path in asr_files],
                "probes": [probe],
                "next_action": "Start or switch the selected local ASR API so /audio/transcriptions is available, or choose another ASR route.",
                "blocked_reason": "The explicitly selected local ASR API did not expose a reachable /audio/transcriptions endpoint.",
            }
        return {
            "status": "ok",
            "decision": "run_local_asr_api",
            "asr_backend": configured_backend,
            "asr_base_url": normalize_base_url(base_url),
            "asr_model": whisper_model(args, config),
            "existing_asr_count": len(asr_files),
            "existing_asr_files": [path.as_posix() for path in asr_files],
            "probes": [probe],
            "next_action": "Run scripts/transcribe_openai_audio.py against the configured local ASR API endpoint.",
            "blocked_reason": "",
        }

    if configured_backend == "external":
        import shutil

        command = args.external_command.strip()
        command_found = bool(command and shutil.which(command.split()[0]))
        return {
            "status": "ok" if command_found else "blocked",
            "decision": "run_external_asr" if command_found else "external_command_required",
            "asr_backend": "external",
            "existing_asr_count": len(asr_files),
            "existing_asr_files": [path.as_posix() for path in asr_files],
            "external_command": command,
            "next_action": "Run the user-selected external ASR command/service." if command_found else "Ask the user for the installed ASR command/service to use.",
            "blocked_reason": "" if command_found else "asr_backend=external requires an explicit installed command or service. Do not guess or download one.",
        }

    if configured_backend == "mlx_whisper":
        ready = module_available("mlx_whisper")
        return {
            "status": "ok" if ready else "blocked",
            "decision": "run_mlx_whisper" if ready else "explicit_mlx_missing",
            "asr_backend": "mlx_whisper",
            "existing_asr_count": len(asr_files),
            "existing_asr_files": [path.as_posix() for path in asr_files],
            "next_action": "Run mlx_whisper ASR with the user-approved model/path." if ready else "Ask whether to use another ASR route or explicitly approve installing/configuring mlx_whisper and its model.",
            "blocked_reason": "" if ready else "mlx_whisper was explicitly selected but is not importable. Do not auto-install it or download models.",
        }

    return {
        "status": "blocked",
        "decision": "unsupported_asr_backend",
        "asr_backend": configured_backend,
        "existing_asr_count": len(asr_files),
        "existing_asr_files": [path.as_posix() for path in asr_files],
        "next_action": "Ask the user how this ASR backend should be invoked.",
        "blocked_reason": f"Unknown ASR backend: {configured_backend}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve the ASR route without installing packages, downloading models, or running ASR.")
    parser.add_argument("--config", help="Project root or project_config.json.")
    parser.add_argument("--asr-dir", help="Existing ASR directory/file to inspect.")
    parser.add_argument("--asr-backend", help="Override configured ASR backend: auto, python-whisper, local-asr-api, external, mlx_whisper, etc.")
    parser.add_argument("--asr-base-url", default="", help="Optional local ASR API base URL when using local-asr-api.")
    parser.add_argument("--asr-model", default="", help="ASR model name. Defaults to config asr_model or large-v3.")
    parser.add_argument("--platform-base-url", action="append", default=[], help="Local platform OpenAI-compatible base URL to probe before explicit local-asr-api.")
    parser.add_argument("--probe-timeout", type=float, default=1.0, help="Timeout in seconds for non-invasive /audio/transcriptions probes.")
    parser.add_argument("--external-command", default="", help="Installed external ASR command selected by the user.")
    parser.add_argument("--require-new-asr", action="store_true", help="Force a new ASR route decision even if existing ASR files are present.")
    parser.add_argument("--json-out", help="Write route decision JSON.")
    args = parser.parse_args()

    route = build_route(args)
    print(f"STATUS={route['status']}")
    print(f"DECISION={route['decision']}")
    print(f"ASR_BACKEND={route['asr_backend']}")
    if route.get("asr_base_url"):
        print(f"ASR_BASE_URL={route['asr_base_url']}")
    if route.get("asr_model"):
        print(f"ASR_MODEL={route['asr_model']}")
    if route.get("shared_whisper_python"):
        print(f"SHARED_WHISPER_PYTHON={route['shared_whisper_python']}")
    print(f"EXISTING_ASR_COUNT={route['existing_asr_count']}")
    if route.get("probes"):
        for probe in route["probes"]:
            print(f"PROBE {probe['base_url']}: {'ok' if probe['ok'] else 'not-ok'} ({probe['detail']})")
    if route.get("blocked_reason"):
        print(f"BLOCKED_REASON={route['blocked_reason']}")
    print(f"NEXT_ACTION={route['next_action']}")

    if args.json_out:
        out_path = Path(args.json_out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(route, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"WROTE {out_path}")

    return 0 if route["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
