#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def run(command: list[str]) -> tuple[int, str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode, output


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the Python openai-whisper ASR backend for this Skill.")
    parser.add_argument("--install-package", action="store_true", help="Install/upgrade openai-whisper with pip.")
    parser.add_argument("--download-model", action="store_true", help="Download/cache the selected Whisper model by loading it once.")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--device", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print intended actions without changing the environment.")
    parser.add_argument("--json-out", help="Write setup report JSON.")
    args = parser.parse_args()

    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "python": sys.executable,
        "ffmpeg": shutil.which("ffmpeg") or "",
        "before": {"whisper_import": module_available("whisper")},
        "actions": [],
        "after": {},
    }

    if not report["ffmpeg"]:
        report["actions"].append(
            {
                "name": "ffmpeg",
                "status": "missing",
                "message": "ffmpeg is required by openai-whisper. Install it with the platform package manager before production ASR.",
            }
        )

    if args.install_package:
        command = [sys.executable, "-m", "pip", "install", "-U", "openai-whisper"]
        if args.dry_run:
            report["actions"].append({"name": "install_package", "status": "dry_run", "command": command})
        else:
            code, output = run(command)
            report["actions"].append({"name": "install_package", "status": "ok" if code == 0 else "fail", "command": command, "output_tail": output[-1000:]})
            importlib.invalidate_caches()

    if args.download_model:
        if args.dry_run:
            report["actions"].append({"name": "download_model", "status": "dry_run", "model": args.model})
        else:
            try:
                import whisper

                whisper.load_model(args.model, device=args.device)
                report["actions"].append({"name": "download_model", "status": "ok", "model": args.model})
            except Exception as exc:
                report["actions"].append({"name": "download_model", "status": "fail", "model": args.model, "error": str(exc)})

    report["after"] = {"whisper_import": module_available("whisper")}
    status = "ok"
    if any(item.get("status") == "fail" for item in report["actions"]):
        status = "fail"
    elif not report["after"]["whisper_import"]:
        status = "missing"
    report["status"] = status

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_out:
        out_path = Path(args.json_out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
