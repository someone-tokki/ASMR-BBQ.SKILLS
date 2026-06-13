#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from manage_model_profile import config_path, load_profile, merge_project_config, merge_run_profile, resolve_stage, run_profile_path


CHAT_STAGES = {"translate", "qc"}
STATUSES = ("OK", "WARN", "FAIL")


@dataclass
class Check:
    name: str
    status: str
    message: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"Invalid status: {self.status}")


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def endpoint(base_url: str, suffix: str) -> str:
    return base_url.rstrip("/") + "/" + suffix.lstrip("/")


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    api_key: str = "",
    timeout: float = 20.0,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    if not raw.strip():
        return {}
    return json.loads(raw)


def http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        body = ""
    if len(body) > 1000:
        body = body[:1000] + "...[truncated]"
    return body


def load_effective_profile(project_root: Path, from_config: bool, from_run_profile: bool) -> dict[str, Any]:
    profile = load_profile(project_root)
    cfg_path = config_path(project_root)
    if from_config and cfg_path.exists():
        profile = merge_project_config(profile, read_json(cfg_path))
    rp_path = run_profile_path(project_root)
    if from_run_profile and rp_path.exists():
        run_profile = read_json(rp_path)
        if run_profile.get("confirmed") is True:
            profile = merge_run_profile(profile, run_profile)
    return profile


def model_ids(data: dict[str, Any]) -> list[str]:
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


def stage_switch_check(target: dict[str, Any], previous: dict[str, Any] | None) -> Check:
    if not previous:
        return Check("stage_switch", "OK", "No previous chat stage was supplied.")
    previous_model = previous.get("model", "")
    target_model = target.get("model", "")
    previous_base_url = previous.get("base_url", "")
    target_base_url = target.get("base_url", "")
    if previous_model == target_model and previous_base_url == target_base_url:
        return Check("stage_switch", "OK", "Target stage uses the same chat model and base URL as the previous stage.")
    return Check(
        "stage_switch",
        "WARN",
        f"Switching from {previous.get('stage')} model '{previous_model}' to {target.get('stage')} model '{target_model}'.",
        (
            "If the local backend cannot keep both models loaded, release/unload the previous stage model "
            "or manually load the target stage model before continuing. HTTP 500 commonly means the previous "
            "model still occupies memory, the target model cannot fit, or the backend cannot hot-switch models."
        ),
    )


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


def print_report(report: dict[str, Any]) -> None:
    print(f"MODEL STAGE {report['stage']} {report['status']}")
    target = report["target"]
    print(f"target: backend={target.get('backend')} base_url={target.get('base_url')} model={target.get('model')} interface={target.get('interface')}")
    previous = report.get("previous")
    if previous:
        print(
            f"previous: stage={previous.get('stage')} base_url={previous.get('base_url')} "
            f"model={previous.get('model')} interface={previous.get('interface')}"
        )
    for check in report["checks"]:
        print(f"{check['status']}: {check['name']}: {check['message']}")
        if check.get("detail"):
            print(f"  {check['detail']}")
    if report.get("next_actions"):
        print("next actions:")
        for action in report["next_actions"]:
            print(f"- {action}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that the next translation/QC chat model stage is ready before model calls.")
    parser.add_argument("project_root")
    parser.add_argument("stage", choices=sorted(CHAT_STAGES))
    parser.add_argument("--previous-stage", choices=["asr", "translate", "qc"], default="")
    parser.add_argument("--from-config", action="store_true", help="Let project_config.json override missing/profile values.")
    parser.add_argument("--from-run-profile", action="store_true", default=True, help="Let confirmed run_profile.json override stage values when present.")
    parser.add_argument("--ignore-run-profile", action="store_false", dest="from_run_profile", help="Do not read run_profile.json.")
    parser.add_argument("--api-key", default="", help="Optional API key for OpenAI-compatible local services.")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--skip-api", action="store_true", help="Only resolve config; do not call /models or /chat/completions.")
    parser.add_argument("--probe-chat", action="store_true", help="Compatibility no-op; chat probe runs by default unless --skip-chat-probe is set.")
    parser.add_argument("--skip-chat-probe", action="store_true", help="Call /models only; skip the tiny chat completion probe.")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--allow-fail", action="store_true", help="Write/print report but return zero even when checks fail.")
    args = parser.parse_args()

    root = Path(args.project_root)
    profile = load_effective_profile(root, args.from_config, args.from_run_profile)
    target = resolve_stage(profile, args.stage)
    previous_stage = args.previous_stage or ("translate" if args.stage == "qc" else "")
    previous = resolve_stage(profile, previous_stage) if previous_stage else None
    checks: list[Check] = []
    next_actions: list[str] = []

    if target.get("interface") != "/chat/completions":
        checks.append(
            Check(
                "interface",
                "FAIL",
                f"{args.stage} must use /chat/completions, got '{target.get('interface')}'.",
                "Translation and QC require a chat model endpoint, not an ASR transcription endpoint.",
            )
        )
    else:
        checks.append(Check("interface", "OK", f"{args.stage} uses /chat/completions."))

    if not target.get("base_url"):
        checks.append(Check("base_url", "FAIL", f"{args.stage} base_url is missing."))
    else:
        checks.append(Check("base_url", "OK", f"{args.stage} base_url resolved."))

    if not target.get("model"):
        checks.append(Check("model", "FAIL", f"{args.stage} model is missing."))
    else:
        checks.append(Check("model", "OK", f"{args.stage} model resolved: {target.get('model')}"))

    checks.append(stage_switch_check(target, previous))

    can_probe = bool(target.get("base_url") and target.get("model") and target.get("interface") == "/chat/completions")
    if args.skip_api:
        checks.append(Check("api_probe", "WARN", "Skipped live API checks by request."))
    elif can_probe:
        models_url = endpoint(str(target["base_url"]), "/models")
        try:
            data = request_json(models_url, api_key=args.api_key, timeout=args.timeout)
            ids = model_ids(data)
            if not ids:
                checks.append(
                    Check(
                        "models_endpoint",
                        "WARN",
                        "/models responded but no model ids were parsed.",
                        "Some local services do not expose a useful model list; the chat probe will be the binding check.",
                    )
                )
            elif str(target["model"]) in ids:
                checks.append(Check("models_endpoint", "OK", f"Target model is listed by /models: {target['model']}"))
            else:
                checks.append(
                    Check(
                        "models_endpoint",
                        "FAIL",
                        f"Target model is not listed by /models: {target['model']}",
                        "Check the exact model id in the local backend or update model_profile.json/run_profile.json.",
                    )
                )
                next_actions.append("Confirm the exact model id exposed by the local backend and update the QC/translation model setting.")
        except urllib.error.HTTPError as exc:
            detail = http_error_detail(exc)
            checks.append(
                Check(
                    "models_endpoint",
                    "FAIL" if exc.code >= 500 else "WARN",
                    f"/models returned HTTP {exc.code}.",
                    detail or "The local service did not provide a readable error body.",
                )
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            checks.append(Check("models_endpoint", "FAIL", "Could not reach /models.", str(exc)))
            next_actions.append("Start or repair the configured local OpenAI-compatible service, then rerun this stage check.")

        if not args.skip_chat_probe:
            chat_url = endpoint(str(target["base_url"]), "/chat/completions")
            try:
                request_json(
                    chat_url,
                    method="POST",
                    payload=build_chat_probe(str(target["model"])),
                    api_key=args.api_key,
                    timeout=args.timeout,
                )
                checks.append(Check("chat_probe", "OK", "Tiny /chat/completions probe succeeded."))
            except urllib.error.HTTPError as exc:
                detail = http_error_detail(exc)
                status = "FAIL"
                if exc.code == 500:
                    message = "Chat probe returned HTTP 500; the target model is not ready."
                    reason = (
                        "Likely causes: previous stage model still occupies memory; target model is too large for current "
                        "memory; local backend cannot hot-switch models; target model id is wrong; or the service needs "
                        "manual load/restart."
                    )
                    next_actions.append("Release/unload the previous stage model or manually switch the backend to the target model, then rerun this check.")
                    next_actions.append("If the target model still fails, choose a smaller QC model or restart the local service.")
                else:
                    message = f"Chat probe returned HTTP {exc.code}."
                    reason = "The configured chat endpoint rejected the target model probe."
                checks.append(Check("chat_probe", status, message, (detail + "\n" if detail else "") + reason))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                checks.append(Check("chat_probe", "FAIL", "Could not reach /chat/completions.", str(exc)))
                next_actions.append("Start or repair the configured chat service before running this stage.")
        else:
            checks.append(Check("chat_probe", "WARN", "Skipped /chat/completions probe by request."))
    elif not args.skip_api:
        checks.append(Check("api_probe", "FAIL", "Skipped live API checks because stage config is incomplete."))

    status = "FAIL" if any(check.status == "FAIL" for check in checks) else ("WARN" if any(check.status == "WARN" for check in checks) else "OK")
    report = {
        "schema_version": 1,
        "created_at": now_utc(),
        "stage": args.stage,
        "status": status,
        "target": target,
        "previous": previous,
        "checks": [asdict(check) for check in checks],
        "next_actions": next_actions,
    }
    if args.json_out:
        write_json(Path(args.json_out), report)
    print_report(report)
    return 0 if status != "FAIL" or args.allow_fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
