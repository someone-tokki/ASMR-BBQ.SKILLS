#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from manage_model_profile import config_path, load_profile, merge_project_config, merge_run_profile, resolve_stage, run_profile_path
from chat_client import build_chat_probe, chat_completion, error_body, list_models, resolve_provider_runtime


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


def http_error_detail(exc: urllib.error.HTTPError) -> str:
    return error_body(exc)


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

def similar_model_ids(target_model: str, ids: list[str], *, limit: int = 5) -> list[str]:
    target = target_model.lower()
    compact = target.replace("-", "").replace("_", "")
    scored: list[tuple[int, str]] = []
    for model_id in ids:
        mid = model_id.lower()
        mid_compact = mid.replace("-", "").replace("_", "")
        score = 0
        if target and target in mid:
            score += 100
        if compact and compact in mid_compact:
            score += 80
        for token in target.replace("_", "-").split("-"):
            if len(token) >= 3 and token in mid:
                score += 10
        if score:
            scored.append((score, model_id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[1] for item in scored[:limit]]


def behavior_probe_command(
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout: float,
    max_reasonable_sec: float,
    json_out: str,
) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).with_name("probe_chat_model_behavior.py")),
        base_url,
        model,
        "--provider",
        str(target.get("provider") or "openai-compatible"),
        "--timeout",
        str(timeout),
        "--max-reasonable-sec",
        str(max_reasonable_sec),
        "--allow-fail",
    ]
    if api_key:
        command.extend(["--api-key", api_key])
    if target.get("provider_profile"):
        command.extend(["--provider-profile", str(target["provider_profile"])])
    if json_out:
        command.extend(["--json-out", json_out])
    return command


def read_behavior_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def behavior_probe_check(
    *,
    target: dict[str, Any],
    api_key: str,
    timeout: float,
    max_reasonable_sec: float,
    json_out: str,
    require_non_thinking: bool,
) -> tuple[Check, list[str], dict[str, Any]]:
    command = behavior_probe_command(
        base_url=str(target["base_url"]),
        model=str(target["model"]),
        api_key=api_key,
        timeout=timeout,
        max_reasonable_sec=max_reasonable_sec,
        json_out=json_out,
    )
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    report = read_behavior_report(Path(json_out)) if json_out else {}
    if not report and completed.stdout.strip():
        try:
            report = json.loads(completed.stdout)
        except Exception:
            report = {}
    verdict = str(report.get("verdict") or "probe_failed")
    notes = [str(note) for note in report.get("notes", []) if str(note).strip()]
    details = "\n".join(notes) if notes else completed.stdout.strip()[:1000]
    if verdict == "ok_for_translation":
        return Check("behavior_probe", "OK", "Model behavior probe passed for fast JSON-style subtitle work.", details), [], report
    if verdict in {"auth_failed", "model_not_found", "model_load_failed", "backend_http_error"}:
        actions = [
            "Fix the local backend/model availability problem, then rerun the model-stage check before changing subtitle chunking or prompts.",
        ]
        if verdict == "model_not_found":
            actions.append("Use the exact model id exposed by /models in model_profile.json or run_profile.json.")
        if verdict == "model_load_failed":
            actions.append("Check the backend logs for weight shape, architecture support, memory pressure, or model conversion errors.")
            actions.append("If the same backend can run another model with no-thinking enabled, treat this as a model/backend compatibility failure rather than a Skill no-thinking policy failure.")
        return Check("behavior_probe", "FAIL", f"Model behavior probe verdict: {verdict}.", details), actions, report
    if verdict == "no_thinking_payload_rejected":
        return (
            Check("behavior_probe", "FAIL" if require_non_thinking else "WARN", "The model works without no-thinking controls but rejects the Skill no-thinking payload.", details),
            [
                "Use a model/backend that accepts no-thinking controls for structured subtitle work, or explicitly configure this model as reasoning and accept slower/manual review behavior.",
                "If this backend has a different no-thinking parameter name, update the Skill scripts before production use.",
            ],
            report,
        )
    actions = [
        "Use a non-reasoning instruct/translation model for bulk subtitle translation, or explicitly accept slower reasoning-model throughput.",
        "For oMLX/LM Studio/Ollama, prefer a verified non-reasoning instruct model such as Qwen2.5-Instruct for bulk translation unless the reasoning model passes this probe.",
    ]
    status = "FAIL" if require_non_thinking else "WARN"
    return Check("behavior_probe", status, f"Model behavior probe verdict: {verdict}.", details), actions, report


def print_report(report: dict[str, Any]) -> None:
    print(f"MODEL STAGE {report['stage']} {report['status']}")
    target = report["target"]
    extra = f" model_class={target.get('model_class')}" if target.get("model_class") else ""
    print(f"target: backend={target.get('backend')} base_url={target.get('base_url')} model={target.get('model')} interface={target.get('interface')}{extra}")
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
    parser.add_argument("--provider", default="", choices=["", "openai-compatible", "anthropic"], help="Override resolved chat provider.")
    parser.add_argument("--provider-profile", default="", help="Override resolved user-level provider registry profile.")
    parser.add_argument("--provider-registry", default="", help="Override provider registry path.")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--skip-api", action="store_true", help="Only resolve config; do not call /models or /chat/completions.")
    parser.add_argument("--probe-chat", action="store_true", help="Compatibility no-op; chat probe runs by default unless --skip-chat-probe is set.")
    parser.add_argument("--skip-chat-probe", action="store_true", help="Call /models only; skip the tiny chat completion probe.")
    parser.add_argument("--probe-behavior", action="store_true", help="Run a short model behavior probe for hidden thinking, empty responses, and latency.")
    parser.add_argument("--require-non-thinking", action="store_true", help="Fail if the behavior probe suggests hidden thinking, blank responses, or excessive latency.")
    parser.add_argument("--max-behavior-sec", type=float, default=12.0, help="Warning/fail threshold per tiny behavior probe request.")
    parser.add_argument("--behavior-json-out", default="", help="Optional behavior probe report path. Defaults next to --json-out when available.")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--allow-fail", action="store_true", help="Write/print report but return zero even when checks fail.")
    args = parser.parse_args()

    root = Path(args.project_root)
    profile = load_effective_profile(root, args.from_config, args.from_run_profile)
    target = resolve_stage(profile, args.stage)
    if args.provider:
        target["provider"] = args.provider
    if args.provider_profile:
        target["provider_profile"] = args.provider_profile
    runtime_args = argparse.Namespace(
        provider=target.get("provider") or "openai-compatible",
        provider_profile=target.get("provider_profile") or "",
        provider_registry=args.provider_registry,
        base_url=target.get("base_url") or "",
        model=target.get("model") or "",
        api_key=args.api_key,
    )
    runtime = resolve_provider_runtime(runtime_args, stage=args.stage)
    target["provider"] = runtime["provider"]
    target["provider_profile"] = runtime["provider_profile"]
    target["base_url"] = runtime["base_url"] or target.get("base_url", "")
    target["model"] = runtime["model"] or target.get("model", "")
    args.api_key = runtime["api_key"]
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
        try:
            if target.get("provider") == "anthropic":
                checks.append(Check("models_endpoint", "WARN", "Skipped /models; Anthropic native API does not use OpenAI-compatible /models."))
                ids = []
            else:
                ids = list_models(base_url=str(target["base_url"]), api_key=args.api_key, timeout=args.timeout)
            if not ids:
                if target.get("provider") != "anthropic":
                    checks.append(
                        Check(
                            "models_endpoint",
                            "WARN",
                            "/models responded but no model ids were parsed.",
                            "Some services do not expose a useful model list; the chat probe will be the binding check.",
                        )
                    )
            elif str(target["model"]) in ids:
                checks.append(Check("models_endpoint", "OK", f"Target model is listed by /models: {target['model']}"))
            else:
                similar = similar_model_ids(str(target["model"]), ids)
                detail = "Check the exact model id in the local backend or update model_profile.json/run_profile.json."
                if similar:
                    detail += " Similar exposed model id(s): " + ", ".join(similar)
                checks.append(
                    Check(
                        "models_endpoint",
                        "FAIL",
                        f"Target model is not listed by /models: {target['model']}",
                        detail,
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
            try:
                chat_completion(
                    provider=str(target.get("provider") or "openai-compatible"),
                    base_url=str(target["base_url"]),
                    api_key=args.api_key,
                    model=str(target["model"]),
                    payload=build_chat_probe(str(target["model"])),
                    timeout=args.timeout,
                )
                checks.append(Check("chat_probe", "OK", "Tiny chat probe succeeded."))
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

        should_probe_behavior = bool(args.probe_behavior or target.get("behavior_probe_required"))
        require_non_thinking = bool(args.require_non_thinking or target.get("require_non_thinking"))
        if args.stage == "translate" and str(target.get("model_class", "")).startswith("reasoning"):
            require_non_thinking = True
        if should_probe_behavior:
            behavior_out = args.behavior_json_out
            if not behavior_out and args.json_out:
                behavior_out = str(Path(args.json_out).with_suffix(".behavior.json"))
            check, actions, behavior_report = behavior_probe_check(
                target=target,
                api_key=args.api_key,
                timeout=args.timeout,
                max_reasonable_sec=args.max_behavior_sec,
                json_out=behavior_out,
                require_non_thinking=require_non_thinking,
            )
            checks.append(check)
            next_actions.extend(actions)
            target["behavior_probe"] = {
                "verdict": behavior_report.get("verdict", ""),
                "report_path": behavior_out,
            }
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
