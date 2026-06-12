#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUSES = ("OK", "WARN", "FAIL")
OUTPUT_FORMATS = {"vtt", "srt", "both"}
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
OPENAI_COMPATIBLE_BASE_URL = "http://127.0.0.1:8000/v1"
REQUIRED_SCRIPTS = [
    "transcribe_mlx.py",
    "batch_transcribe_mlx.py",
    "translate_srt_omlx.py",
    "batch_translate_srt_omlx.py",
    "qc_srt_omlx.py",
    "convert_srt_to_vtt.py",
    "validate_subtitles.py",
    "scan_subtitle_risks.py",
    "subtitle_readability.py",
    "review_qc_report.py",
    "manage_project_config.py",
    "check_environment.py",
]
CORE_IMPORTS = [
    ("tqdm", "Required by batch/long-running ASR, translation, and QC scripts."),
]


@dataclass
class Check:
    category: str
    name: str
    status: str
    message: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"Invalid status: {self.status}")


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return repo_root() / path


def find_config(target: str | None) -> Path | None:
    if not target:
        return None
    path = resolve_path(target)
    if path is None:
        return None
    if path.name == "project_config.json":
        return path
    return path / "project_config.json"


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object")
    return data


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def is_wsl() -> bool:
    if platform.system() != "Linux":
        return False
    version_path = Path("/proc/version")
    try:
        text = version_path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return "microsoft" in text or "wsl" in text


def platform_id() -> str:
    system = platform.system()
    if is_wsl():
        return "wsl"
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    return "unknown"


def target_platform_id(config: dict[str, Any] | None) -> str:
    profile = str((config or {}).get("platform", {}).get("profile", "")).strip().lower()
    if profile == "windows-ollama":
        return "windows"
    if profile == "wsl-ollama":
        return "wsl"
    if profile == "macos-mlx":
        return "macos"
    if profile == "generic-openai":
        return "linux"
    return platform_id()


def default_translate_backend_for_platform(config: dict[str, Any] | None) -> str:
    return "ollama" if target_platform_id(config) in {"windows", "wsl"} else "openai-compatible"


def default_asr_backend_for_platform(config: dict[str, Any] | None) -> str:
    return "mlx_whisper" if target_platform_id(config) == "macos" else "external"


def configured_asr_backend(config: dict[str, Any] | None) -> str:
    models = config.get("models", {}) if config else {}
    return str(models.get("asr_backend", "")).strip().lower()


def configured_translate_backend(config: dict[str, Any] | None) -> str:
    models = config.get("models", {}) if config else {}
    return str(models.get("translate_backend", "")).strip().lower()


def fallback_translate_backend(config: dict[str, Any] | None) -> str:
    preferred = default_translate_backend_for_platform(config)
    if preferred == "ollama" and shutil.which("ollama"):
        return "ollama"
    if shutil.which("omlx"):
        return "omlx"
    if shutil.which("ollama"):
        return "ollama"
    return "openai-compatible"


def effective_translate_backend(config: dict[str, Any] | None) -> str:
    configured = configured_translate_backend(config)
    if configured and configured != "auto":
        return configured
    return fallback_translate_backend(config)


def existing_asr_files(config: dict[str, Any] | None) -> list[Path]:
    if not config:
        return []
    paths = config.get("paths", {})
    if not isinstance(paths, dict):
        return []
    files: list[Path] = []
    for key in ("asr_dir", "promo_asr_dir"):
        path = resolve_path(str(paths.get(key, "")).strip())
        if path and path.exists() and path.is_dir():
            files.extend(sorted(path.glob("*.ja.asr.srt")))
    return files


def effective_asr_backend(config: dict[str, Any] | None) -> str:
    configured = configured_asr_backend(config)
    if configured and configured != "auto":
        return configured
    platform_default = default_asr_backend_for_platform(config)
    if platform_default == "mlx_whisper" and module_available("mlx_whisper"):
        return "mlx_whisper"
    return "external"


def default_base_url_for_backend(backend: str) -> str:
    if backend == "ollama":
        return OLLAMA_BASE_URL
    return OPENAI_COMPATIBLE_BASE_URL


def check_platform(config: dict[str, Any] | None) -> list[Check]:
    checks: list[Check] = []
    system = platform.system() or "unknown"
    release = platform.release()
    machine = platform.machine() or "unknown"
    platform_name = "WSL" if is_wsl() else system
    checks.append(Check("platform", "system", "OK", f"{platform_name} {release}", f"arch={machine}"))
    profile = str((config or {}).get("platform", {}).get("profile", "")).strip() or "auto"
    checks.append(Check("platform", "profile", "OK", profile, f"target_platform={target_platform_id(config)}"))

    version = sys.version_info
    status = "OK" if version >= (3, 10) else "FAIL"
    checks.append(
        Check(
            "platform",
            "python",
            status,
            f"Python {platform.python_version()}",
            "Python 3.10+ is recommended for the workflow scripts.",
        )
    )
    return checks


def check_backend_recommendation(config: dict[str, Any] | None) -> list[Check]:
    configured = configured_translate_backend(config)
    platform_default = default_translate_backend_for_platform(config)
    effective = effective_translate_backend(config)
    ollama_found = bool(shutil.which("ollama"))
    omlx_found = bool(shutil.which("omlx"))

    checks = [
        Check(
            "backend",
            "platform_default_translate_backend",
            "OK",
            platform_default,
            f"target_platform={target_platform_id(config)}. Windows/WSL default to Ollama; macOS/Linux keep OpenAI-compatible service usage by default.",
        )
    ]

    if configured and configured != "auto":
        status = "OK"
        detail = "Explicit project config overrides platform default."
        if platform_default == "ollama" and configured != "ollama":
            status = "WARN"
            detail = "This Windows/WSL profile normally prefers Ollama, but the project config explicitly chooses another backend."
        checks.append(Check("backend", "configured_translate_backend", status, configured, detail))
    else:
        checks.append(
            Check(
                "backend",
                "configured_translate_backend",
                "OK",
                configured or "auto",
                "Auto means environment detection recommends a backend; it does not start services.",
            )
        )

    if platform_default == "ollama" and not ollama_found and configured in {"", "auto"}:
        checks.append(
            Check(
                "backend",
                "ollama_fallback",
                "WARN",
                f"Ollama not found; recommend fallback backend: {effective}",
                "Install/start Ollama for the Windows/WSL default path, or use the fallback backend if it is available.",
            )
        )
    elif platform_default == "ollama" and not ollama_found and configured == "ollama":
        checks.append(
            Check(
                "backend",
                "ollama_required",
                "WARN",
                "Ollama is explicitly configured but not found",
                "The commands check reports this as FAIL because the project config requires Ollama.",
            )
        )
    else:
        checks.append(
            Check(
                "backend",
                "recommended_translate_backend",
                "OK" if effective != "openai-compatible" or configured not in {"", "auto"} else "WARN",
                effective,
                f"Detected commands: ollama={'yes' if ollama_found else 'no'}, omlx={'yes' if omlx_found else 'no'}.",
            )
        )
    return checks


def check_asr_recommendation(config: dict[str, Any] | None, *, require_asr: bool) -> list[Check]:
    configured = configured_asr_backend(config)
    platform_default = default_asr_backend_for_platform(config)
    effective = effective_asr_backend(config)
    asr_files = existing_asr_files(config)
    mlx_found = module_available("mlx_whisper")
    checks = [
        Check(
            "asr",
            "existing_asr_files",
            "OK" if asr_files else "WARN",
            f"{len(asr_files)} *.ja.asr.srt file(s) found",
            "Existing ASR files allow translation/QC/checks to continue even if the local ASR backend is unavailable.",
        ),
        Check(
            "asr",
            "platform_default_asr_backend",
            "OK",
            platform_default,
            f"target_platform={target_platform_id(config)}. macOS may use MLX; Windows/WSL should avoid MLX-only assumptions.",
        ),
    ]
    if configured and configured != "auto":
        checks.append(Check("asr", "configured_asr_backend", "OK", configured, "Explicit project config overrides platform default."))
    else:
        checks.append(Check("asr", "configured_asr_backend", "OK", configured or "auto", "Auto recommends an ASR route; it does not run ASR."))
    if effective == "mlx_whisper":
        recommended_status = "OK" if mlx_found else ("FAIL" if require_asr or not asr_files else "WARN")
    elif effective == "external":
        recommended_status = "OK" if configured not in {"", "auto"} else "WARN"
    else:
        recommended_status = "OK"
    checks.append(
        Check(
            "asr",
            "recommended_asr_backend",
            recommended_status,
            effective,
            f"mlx_whisper={'yes' if mlx_found else 'no'}. External means use existing ASR, another Whisper-compatible tool, or a user-approved ASR service.",
        )
    )
    return checks


def check_scripts() -> list[Check]:
    checks: list[Check] = []
    tools_dir = repo_root() / "tools"
    for script in REQUIRED_SCRIPTS:
        path = tools_dir / script
        status = "OK" if path.exists() else "FAIL"
        message = f"Found {rel(path)}" if path.exists() else f"Missing {rel(path)}"
        checks.append(Check("scripts", script, status, message))
    return checks


def check_imports(config: dict[str, Any] | None, *, require_asr: bool) -> list[Check]:
    checks: list[Check] = []
    for name, detail in CORE_IMPORTS:
        checks.append(
            Check(
                "imports",
                name,
                "OK" if module_available(name) else "FAIL",
                "Import is available" if module_available(name) else "Import is not available",
                detail,
            )
        )

    models = config.get("models", {}) if config else {}
    asr_backend = str(models.get("asr_backend", "")).strip().lower()
    asr_files = existing_asr_files(config)
    mlx_needed = asr_backend == "mlx_whisper" and (require_asr or not asr_files)
    mlx_status = "OK" if module_available("mlx_whisper") else ("FAIL" if mlx_needed else "WARN")
    if module_available("mlx_whisper"):
        mlx_message = "Import is available"
    elif asr_backend == "mlx_whisper" and asr_files and not require_asr:
        mlx_message = "Import is not available, but existing ASR files are present"
    else:
        mlx_message = "Import is not available"
    checks.append(
        Check(
            "imports",
            "mlx_whisper",
            mlx_status,
            mlx_message,
            "Required only when the project must run new ASR through mlx_whisper. Existing *.ja.asr.srt files can skip this backend.",
        )
    )
    return checks


def check_external_tools(config: dict[str, Any] | None) -> list[Check]:
    checks: list[Check] = []
    paths = config.get("paths", {}) if config else {}
    project_type = str(config.get("project_type", "")) if config else ""
    script_path = str(paths.get("script_path", "")).strip()
    script_is_pdf = script_path.lower().endswith(".pdf")
    pdftotext_needed = project_type == "with-script" and script_is_pdf
    pdftotext_path = shutil.which("pdftotext")
    checks.append(
        Check(
            "commands",
            "pdftotext",
            "OK" if pdftotext_path else ("FAIL" if pdftotext_needed else "WARN"),
            f"Found {pdftotext_path}" if pdftotext_path else "Command not found",
            "Needed for PDF script comparison; plain text scripts do not need it.",
        )
    )

    models = config.get("models", {}) if config else {}
    translate_backend = str(models.get("translate_backend", "")).strip().lower()
    for command, backend_names in (("omlx", {"omlx"}), ("ollama", {"ollama"})):
        found = shutil.which(command)
        required = translate_backend in backend_names
        checks.append(
            Check(
                "commands",
                command,
                "OK" if found else ("FAIL" if required else "WARN"),
                f"Found {found}" if found else "Command not found",
                f"Only required when translate_backend is explicitly {command}. Auto mode may fall back.",
            )
        )
    return checks


def check_config(config_path: Path | None) -> tuple[dict[str, Any] | None, list[Check]]:
    checks: list[Check] = []
    if not config_path:
        checks.append(Check("config", "project_config", "WARN", "No project_config.json provided"))
        return None, checks
    if not config_path.exists():
        checks.append(Check("config", "project_config", "FAIL", f"Missing {rel(config_path)}"))
        return None, checks
    try:
        config = read_json(config_path)
    except Exception as exc:
        checks.append(Check("config", "project_config", "FAIL", f"Invalid JSON: {rel(config_path)}", str(exc)))
        return None, checks

    checks.append(Check("config", "project_config", "OK", f"Loaded {rel(config_path)}"))
    version = config.get("config_version")
    checks.append(
        Check(
            "config",
            "config_version",
            "OK" if version == 1 else "WARN",
            f"config_version={version}",
            "Current tools expect version 1.",
        )
    )
    output_format = config.get("settings", {}).get("output_format")
    checks.append(
        Check(
            "config",
            "output_format",
            "OK" if output_format in OUTPUT_FORMATS else "FAIL",
            f"output_format={output_format}",
            "Allowed values: vtt, srt, both.",
        )
    )
    return config, checks


def check_config_paths(config: dict[str, Any] | None, *, strict_paths: bool) -> list[Check]:
    if not config:
        return []
    checks: list[Check] = []
    paths = config.get("paths", {})
    if not isinstance(paths, dict):
        return [Check("paths", "paths", "FAIL", "Config paths must be an object")]

    required_inputs = {"project_root", "source_audio_dir", "script_path"}
    generated_dirs = {
        "asr_dir",
        "zh_srt_dir",
        "final_dir",
        "promo_asr_dir",
        "promo_zh_srt_dir",
        "promo_final_dir",
    }
    for key, value in sorted(paths.items()):
        if not value:
            if key == "script_path" and config.get("project_type") == "with-script":
                checks.append(Check("paths", key, "WARN", "Not set", "With-script projects should record the script path when available."))
            continue
        path = resolve_path(str(value))
        if path is None:
            continue
        exists = path.exists()
        if exists:
            checks.append(Check("paths", key, "OK", f"Exists: {rel(path)}"))
            continue
        if key in required_inputs or strict_paths:
            status = "FAIL"
        elif key in generated_dirs:
            status = "WARN"
        else:
            status = "WARN"
        detail = "Generated/work directories may be created later." if key in generated_dirs else ""
        checks.append(Check("paths", key, status, f"Missing: {rel(path)}", detail))

    artifacts = config.get("artifacts", {})
    if isinstance(artifacts, dict):
        for key, value in sorted(artifacts.items()):
            if not value:
                continue
            path = resolve_path(str(value))
            if path is None:
                continue
            if path.exists():
                checks.append(Check("artifacts", key, "OK", f"Exists: {rel(path)}"))
            elif path.parent.exists():
                checks.append(Check("artifacts", key, "WARN", f"Not written yet: {rel(path)}"))
            else:
                checks.append(Check("artifacts", key, "WARN", f"Parent missing: {rel(path.parent)}"))
    return checks


def api_url_for_models(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/models"):
        return trimmed
    return trimmed + "/models"


def parse_model_ids(data: object) -> list[str]:
    if not isinstance(data, dict):
        return []
    raw_items = data.get("data")
    if not isinstance(raw_items, list):
        return []
    ids: list[str] = []
    for item in raw_items:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
    return ids


def check_api(
    config: dict[str, Any] | None,
    *,
    base_url_arg: str,
    api_key: str,
    timeout: float,
    skip_api: bool,
) -> list[Check]:
    if skip_api:
        return [Check("api", "translate_api", "WARN", "Skipped API reachability check")]

    models = config.get("models", {}) if config else {}
    translate_backend = effective_translate_backend(config)
    config_base_url = str(models.get("translate_base_url", "")).strip()
    base_url = base_url_arg.strip() or config_base_url
    if not base_url:
        base_url = default_base_url_for_backend(translate_backend)
    if not base_url:
        return [Check("api", "translate_api", "WARN", "No translate_base_url configured")]

    url = api_url_for_models(base_url)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer <redacted>"
    request_headers = headers.copy()
    if api_key:
        request_headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=request_headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            status_code = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        return [
            Check(
                "api",
                "translate_api",
                "WARN",
                f"HTTP {exc.code} from {url}",
                "Server is reachable but rejected the request; check API key or endpoint.",
            )
        ]
    except Exception as exc:
        return [
            Check(
                "api",
                "translate_api",
                "WARN",
                f"Cannot reach {url}",
                str(exc),
            )
        ]

    checks = [Check("api", "translate_api", "OK", f"GET {url} -> HTTP {status_code}")]
    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception:
        return checks + [Check("api", "models_payload", "WARN", "Response is not JSON")]

    model_ids = parse_model_ids(data)
    expected_models = [
        str(models.get("translate_model", "")).strip(),
        str(models.get("qc_model", "")).strip(),
    ]
    for expected in sorted({item for item in expected_models if item}):
        if not model_ids:
            checks.append(Check("api", f"model:{expected}", "WARN", "Models endpoint did not expose model IDs"))
        elif expected in model_ids:
            checks.append(Check("api", f"model:{expected}", "OK", "Model appears in /models"))
        else:
            checks.append(Check("api", f"model:{expected}", "WARN", "Model not listed by /models"))
    return checks


def summarize(checks: list[Check]) -> dict[str, Any]:
    counts = {status: 0 for status in STATUSES}
    for check in checks:
        counts[check.status] += 1
    overall = "FAIL" if counts["FAIL"] else ("WARN" if counts["WARN"] else "OK")
    return {"overall_status": overall, "counts": counts}


def print_report(checks: list[Check]) -> None:
    summary = summarize(checks)
    print(f"Environment status: {summary['overall_status']}  OK={summary['counts']['OK']} WARN={summary['counts']['WARN']} FAIL={summary['counts']['FAIL']}")
    last_category = ""
    for check in checks:
        if check.category != last_category:
            print(f"\n[{check.category}]")
            last_category = check.category
        print(f"{check.status:4} {check.name}: {check.message}")
        if check.detail:
            print(f"     {check.detail}")


def write_json_report(path: Path, checks: list[Check]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": now_utc(),
        **summarize(checks),
        "checks": [asdict(check) for check in checks],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the local ASMR subtitle workflow environment without modifying subtitle files.")
    parser.add_argument("--config", help="Path to project_config.json or a project output root.")
    parser.add_argument("--translate-base-url", default="", help="Override the configured OpenAI-compatible base URL.")
    parser.add_argument("--api-key", default="", help="Optional API key for the /models reachability check. The value is never printed.")
    parser.add_argument("--timeout", type=float, default=2.0, help="API reachability timeout in seconds.")
    parser.add_argument("--skip-api", action="store_true", help="Skip local translation API reachability check.")
    parser.add_argument("--require-asr", action="store_true", help="Treat missing ASR backend/files as blocking because new ASR will be run.")
    parser.add_argument("--strict-paths", action="store_true", help="Treat missing generated/work directories as FAIL instead of WARN.")
    parser.add_argument("--json-out", help="Write a JSON environment report.")
    args = parser.parse_args()

    config, checks = check_config(find_config(args.config))
    checks.extend(check_platform(config))
    checks.extend(check_backend_recommendation(config))
    checks.extend(check_asr_recommendation(config, require_asr=args.require_asr))
    checks.extend(check_scripts())
    checks.extend(check_imports(config, require_asr=args.require_asr))
    checks.extend(check_external_tools(config))
    checks.extend(check_config_paths(config, strict_paths=args.strict_paths))
    checks.extend(
        check_api(
            config,
            base_url_arg=args.translate_base_url,
            api_key=args.api_key,
            timeout=args.timeout,
            skip_api=args.skip_api,
        )
    )

    print_report(checks)
    if args.json_out:
        out_path = resolve_path(args.json_out)
        if out_path is None:
            raise SystemExit("--json-out must not be empty")
        write_json_report(out_path, checks)
        print(f"\nWROTE {rel(out_path)}")

    return 1 if summarize(checks)["overall_status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
