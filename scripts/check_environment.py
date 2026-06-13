#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
import subprocess
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
LMSTUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
PLATFORM_ASR_CANDIDATES = [OPENAI_COMPATIBLE_BASE_URL, LMSTUDIO_BASE_URL, OLLAMA_BASE_URL]
ASR_ENDPOINT_EXISTS_CODES = {400, 401, 403, 405, 415, 422}
REQUIRED_SCRIPTS = [
    "transcribe_mlx.py",
    "batch_transcribe_mlx.py",
    "asr_resume.py",
    "transcribe_whisper.py",
    "setup_whisper_backend.py",
    "transcribe_openai_audio.py",
    "subtitle_io.py",
    "subtitle_chunking.py",
    "translate_srt_omlx.py",
    "batch_translate_srt_omlx.py",
    "qc_srt_omlx.py",
    "convert_srt_to_vtt.py",
    "export_final_subtitles.py",
    "validate_subtitles.py",
    "resolve_project_context.py",
    "resolve_asr_route.py",
    "scan_subtitle_risks.py",
    "select_asr_audio_source.py",
    "subtitle_readability.py",
    "review_qc_report.py",
    "manage_project_config.py",
    "manage_model_profile.py",
    "check_environment.py",
]
CORE_IMPORTS = [
    {
        "module": "tqdm",
        "package": "tqdm",
        "status_if_missing": "FAIL",
        "detail": "Required by batch/long-running ASR, translation, and QC scripts.",
    },
    {
        "module": "yaml",
        "package": "PyYAML",
        "status_if_missing": "WARN",
        "detail": "Needed by skill-creator validation helpers and YAML metadata checks; not required for subtitle runtime.",
    },
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


def work_root() -> Path:
    return Path.cwd()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(work_root()).as_posix()
    except ValueError:
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
    return work_root() / path


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


def missing_installable_python_packages() -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    seen: set[str] = set()
    for dep in CORE_IMPORTS:
        module = dep["module"]
        package = dep["package"]
        if not module_available(module) and package not in seen:
            missing.append(dep)
            seen.add(package)
    return missing


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
    profile = str((config or {}).get("platform", {}).get("profile", "")).strip().lower()
    return "mlx_whisper" if profile == "macos-mlx" else "local-platform-asr-api"


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
    return default_asr_backend_for_platform(config)


def default_base_url_for_backend(backend: str) -> str:
    if backend == "ollama":
        return OLLAMA_BASE_URL
    return OPENAI_COMPATIBLE_BASE_URL


def normalize_base_url(value: str) -> str:
    return value.strip().rstrip("/")


def dedupe_urls(values: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_base_url(value)
        if normalized and normalized not in seen:
            urls.append(normalized)
            seen.add(normalized)
    return urls


def audio_transcriptions_url(base_url: str) -> str:
    return normalize_base_url(base_url) + "/audio/transcriptions"


def probe_audio_transcriptions(base_url: str, timeout: float = 1.0) -> dict[str, Any]:
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


def platform_asr_candidates(config: dict[str, Any] | None) -> list[str]:
    models = config.get("models", {}) if config else {}
    values: list[str] = []
    translate_base_url = str(models.get("translate_base_url", "")).strip()
    if translate_base_url:
        values.append(translate_base_url)
    translate_backend = str(models.get("translate_backend", "")).strip().lower()
    if translate_backend == "ollama":
        values.append(OLLAMA_BASE_URL)
    elif translate_backend == "lmstudio":
        values.append(LMSTUDIO_BASE_URL)
    elif translate_backend in {"omlx", "openai-compatible", "auto", ""}:
        values.append(OPENAI_COMPATIBLE_BASE_URL)
    values.extend(PLATFORM_ASR_CANDIDATES)
    return dedupe_urls(values)


def explicit_asr_candidates(config: dict[str, Any] | None) -> list[str]:
    models = config.get("models", {}) if config else {}
    return dedupe_urls([str(models.get("asr_base_url", "")).strip()])


def first_working_asr_api(candidates: list[str], timeout: float = 1.0) -> tuple[str, list[dict[str, Any]]]:
    probes: list[dict[str, Any]] = []
    for base_url in candidates:
        result = probe_audio_transcriptions(base_url, timeout=timeout)
        probes.append(result)
        if result["ok"]:
            return result["base_url"], probes
    return "", probes


def auto_asr_api_available(config: dict[str, Any] | None) -> tuple[str, str, list[dict[str, Any]]]:
    platform_base_url, platform_probes = first_working_asr_api(platform_asr_candidates(config))
    if platform_base_url:
        return "local-platform-asr-api", platform_base_url, platform_probes
    explicit_base_url, explicit_probes = first_working_asr_api(explicit_asr_candidates(config))
    if explicit_base_url:
        return "local-asr-api", explicit_base_url, platform_probes + explicit_probes
    return "", "", platform_probes + explicit_probes


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
    detected_auto_backend, detected_auto_base_url, auto_probes = auto_asr_api_available(config)
    checks = [
        Check(
            "asr",
            "existing_asr_files",
            "OK" if asr_files else "WARN",
            f"{len(asr_files)} *.ja.asr.srt file(s) found",
            "Existing ASR files allow translation/QC/checks to continue. Do not install ASR packages just because a reusable ASR file already exists.",
        ),
        Check(
            "asr",
            "platform_default_asr_backend",
            "OK",
            platform_default,
            f"target_platform={target_platform_id(config)}. Auto probes local platform /audio/transcriptions first, then configured local-asr-api, then Python openai-whisper.",
        ),
    ]
    if configured and configured != "auto":
        checks.append(Check("asr", "configured_asr_backend", "OK", configured, "Explicit project config overrides platform default."))
    else:
        checks.append(Check("asr", "configured_asr_backend", "OK", configured or "auto", "Auto recommends an ASR route; it does not run ASR."))
    if effective == "mlx_whisper":
        recommended_status = "OK" if mlx_found else ("FAIL" if require_asr or not asr_files else "WARN")
        recommended_message = effective
        recommended_detail = f"mlx_whisper={'yes' if mlx_found else 'no'}. This route is only selected by explicit backend/profile."
    elif effective in {"local-platform-asr-api", "auto"} and configured in {"", "auto"}:
        if detected_auto_backend:
            recommended_status = "OK"
            recommended_message = f"{detected_auto_backend} at {detected_auto_base_url}"
        elif module_available("whisper"):
            recommended_status = "OK"
            recommended_message = "python-whisper fallback"
        else:
            recommended_status = "FAIL" if require_asr or (config and not asr_files) else "WARN"
            recommended_message = "setup_python_whisper_required"
        probe_summary = "; ".join(f"{item['base_url']}={'ok' if item['ok'] else 'not-ok'}" for item in auto_probes) or "no API candidates"
        recommended_detail = (
            f"Probe summary: {probe_summary}. "
            f"whisper={'yes' if module_available('whisper') else 'no'}, mlx_whisper={'yes' if mlx_found else 'no'}. "
            "ASR auto never treats a chat-only endpoint as transcription-capable unless /audio/transcriptions is detected."
        )
    elif effective in {"python-whisper", "whisper", "openai-whisper"}:
        recommended_status = "OK" if module_available("whisper") else ("FAIL" if require_asr or (config and not asr_files) else "WARN")
        recommended_message = effective
        recommended_detail = "Explicit Python Whisper route. Use setup_whisper_backend.py after user approval if import is missing."
    elif effective in {"local-asr-api", "openai-audio", "local-service"}:
        explicit_base_url = explicit_asr_candidates(config)[0] if explicit_asr_candidates(config) else ""
        if not explicit_base_url:
            recommended_status = "FAIL" if require_asr else "WARN"
            recommended_message = "local-asr-api missing asr_base_url"
            recommended_detail = "Explicit local ASR API route requires asr_base_url or --asr-base-url."
        else:
            probe = probe_audio_transcriptions(explicit_base_url)
            recommended_status = "OK" if probe["ok"] else ("FAIL" if require_asr else "WARN")
            recommended_message = f"{effective} at {explicit_base_url}"
            recommended_detail = probe["detail"]
    elif effective == "external":
        recommended_status = "FAIL" if require_asr and configured in {"", "auto"} and not asr_files else ("OK" if configured == "external" else "WARN")
        recommended_message = effective
        recommended_detail = "External ASR requires a user-selected installed command/service."
    else:
        recommended_status = "OK"
        recommended_message = effective
        recommended_detail = "Project-specific ASR backend; agent must know how to invoke it."
    checks.append(
        Check(
            "asr",
            "recommended_asr_backend",
            recommended_status,
            recommended_message,
            recommended_detail,
        )
    )
    return checks


def check_scripts() -> list[Check]:
    checks: list[Check] = []
    scripts_dir = repo_root() / "scripts"
    for script in REQUIRED_SCRIPTS:
        path = scripts_dir / script
        status = "OK" if path.exists() else "FAIL"
        message = f"Found {rel(path)}" if path.exists() else f"Missing {rel(path)}"
        checks.append(Check("scripts", script, status, message))
    return checks


def check_imports(config: dict[str, Any] | None, *, require_asr: bool) -> list[Check]:
    checks: list[Check] = []
    for dep in CORE_IMPORTS:
        name = dep["module"]
        available = module_available(name)
        checks.append(
            Check(
                "imports",
                name,
                "OK" if available else dep["status_if_missing"],
                "Import is available" if available else f"Import is not available; install package `{dep['package']}`",
                dep["detail"],
            )
        )

    asr_files = existing_asr_files(config)
    effective = effective_asr_backend(config)
    detected_auto_backend, _, _ = auto_asr_api_available(config)
    auto_will_need_python = effective in {"local-platform-asr-api", "auto"} and not detected_auto_backend
    whisper_needed = (
        effective in {"python-whisper", "whisper", "openai-whisper"} or auto_will_need_python
    ) and (require_asr or (bool(config) and not asr_files))
    whisper_status = "OK" if module_available("whisper") else ("FAIL" if whisper_needed else "WARN")
    checks.append(
        Check(
            "imports",
            "whisper",
            whisper_status,
            "Import is available" if module_available("whisper") else "Import is not available",
            "Required only when local platform/local ASR API is unavailable and the workflow falls back to Python Whisper. Use setup_whisper_backend.py after user approval.",
        )
    )
    explicit_mlx = configured_asr_backend(config) == "mlx_whisper" or str((config or {}).get("platform", {}).get("profile", "")).strip().lower() == "macos-mlx"
    mlx_needed = explicit_mlx and (require_asr or not asr_files)
    mlx_status = "OK" if module_available("mlx_whisper") else ("FAIL" if mlx_needed else "OK")
    if module_available("mlx_whisper"):
        mlx_message = "Import is available"
    elif explicit_mlx and asr_files and not require_asr:
        mlx_message = "Import is not available, but existing ASR files are present"
    elif explicit_mlx:
        mlx_message = "Import is not available for explicitly selected mlx_whisper route"
    else:
        mlx_message = "Not required for the current ASR route"
    checks.append(
        Check(
            "imports",
            "mlx_whisper",
            mlx_status,
            mlx_message,
            "Required only when the user explicitly chose mlx_whisper for new ASR. Missing mlx_whisper is not a reason to auto-install packages or download models.",
        )
    )
    return checks


def check_dependency_install_plan() -> list[Check]:
    missing = missing_installable_python_packages()
    if not missing:
        return [Check("install", "python_packages", "OK", "No missing installable Python packages")]
    package_list = " ".join(dep["package"] for dep in missing)
    return [
        Check(
            "install",
            "python_packages",
            "WARN",
            f"Missing installable package(s): {package_list}",
            f"To install into the active interpreter: {sys.executable} -m pip install {package_list}",
        )
    ]


def install_missing_python_packages(*, dry_run: bool) -> list[Check]:
    missing = missing_installable_python_packages()
    if not missing:
        return [Check("install", "python_packages", "OK", "No Python packages to install")]

    checks: list[Check] = []
    for dep in missing:
        package = dep["package"]
        command = [sys.executable, "-m", "pip", "install", package]
        if dry_run:
            checks.append(
                Check(
                    "install",
                    package,
                    "WARN",
                    "Dry run; package not installed",
                    " ".join(command),
                )
            )
            continue
        try:
            result = subprocess.run(command, text=True, capture_output=True, check=False)
        except OSError as exc:
            checks.append(Check("install", package, "FAIL", "Could not start pip", str(exc)))
            continue
        if result.returncode == 0:
            checks.append(Check("install", package, "OK", "Installed package", "Output suppressed; rerun environment check to verify imports."))
        else:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            checks.append(Check("install", package, "FAIL", f"pip exited with {result.returncode}", detail[-1] if detail else "No pip output"))
    importlib.invalidate_caches()
    return checks


def check_external_tools(config: dict[str, Any] | None, *, require_asr: bool) -> list[Check]:
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

    ffmpeg_path = shutil.which("ffmpeg")
    asr_backend = effective_asr_backend(config)
    asr_files = existing_asr_files(config)
    detected_auto_backend, _, _ = auto_asr_api_available(config)
    auto_will_need_python = asr_backend in {"local-platform-asr-api", "auto"} and not detected_auto_backend
    ffmpeg_required = (
        asr_backend in {"python-whisper", "whisper", "openai-whisper"} or auto_will_need_python
    ) and (require_asr or (bool(config) and not asr_files))
    checks.append(
        Check(
            "commands",
            "ffmpeg",
            "OK" if ffmpeg_path else ("FAIL" if ffmpeg_required else "WARN"),
            f"Found {ffmpeg_path}" if ffmpeg_path else "Command not found",
            "Required by openai-whisper when this run creates new ASR; existing ASR files can continue without it.",
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
    parser = argparse.ArgumentParser(description="Check the local ASMR subtitle workflow environment and optionally install small Python dependencies.")
    parser.add_argument("--config", help="Path to project_config.json or a project output root.")
    parser.add_argument("--translate-base-url", default="", help="Override the configured OpenAI-compatible base URL.")
    parser.add_argument("--api-key", default="", help="Optional API key for the /models reachability check. The value is never printed.")
    parser.add_argument("--timeout", type=float, default=2.0, help="API reachability timeout in seconds.")
    parser.add_argument("--skip-api", action="store_true", help="Skip local translation API reachability check.")
    parser.add_argument("--require-asr", action="store_true", help="Treat missing ASR backend/files as blocking because new ASR will be run.")
    parser.add_argument("--strict-paths", action="store_true", help="Treat missing generated/work directories as FAIL instead of WARN.")
    parser.add_argument("--install-missing-python", action="store_true", help="Install missing installable Python packages into the active interpreter with pip.")
    parser.add_argument("--dry-run-install", action="store_true", help="Show pip install commands without installing packages.")
    parser.add_argument("--json-out", help="Write a JSON environment report.")
    args = parser.parse_args()

    config, checks = check_config(find_config(args.config))
    checks.extend(check_platform(config))
    checks.extend(check_backend_recommendation(config))
    checks.extend(check_asr_recommendation(config, require_asr=args.require_asr))
    checks.extend(check_scripts())
    if args.install_missing_python or args.dry_run_install:
        checks.extend(install_missing_python_packages(dry_run=args.dry_run_install))
        checks.extend(check_imports(config, require_asr=args.require_asr))
    else:
        checks.extend(check_imports(config, require_asr=args.require_asr))
        checks.extend(check_dependency_install_plan())
    checks.extend(check_external_tools(config, require_asr=args.require_asr))
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
