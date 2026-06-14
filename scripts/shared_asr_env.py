#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def shared_asr_root() -> Path:
    value = os.environ.get("ASMR_SUBTITLE_ASR_DIR")
    if value:
        return Path(value).expanduser()
    return Path.home() / "ASMR-Subtitle-Translator" / "asr"


def shared_whisper_venv() -> Path:
    return shared_asr_root() / "openai-whisper-venv"


def shared_whisper_python() -> Path:
    venv = shared_whisper_venv()
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def python_can_import(python: Path, module: str) -> bool:
    if not python.exists():
        return False
    result = subprocess.run(
        [str(python), "-c", f"import {module}"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def shared_whisper_available() -> bool:
    return python_can_import(shared_whisper_python(), "whisper")


def running_in_shared_whisper_python() -> bool:
    try:
        return Path(sys.executable).resolve() == shared_whisper_python().resolve()
    except OSError:
        return False


def create_shared_whisper_venv() -> None:
    venv = shared_whisper_venv()
    if shared_whisper_python().exists():
        return
    venv.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
