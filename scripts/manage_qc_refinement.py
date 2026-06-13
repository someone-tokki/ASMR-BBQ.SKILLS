#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from subtitle_io import parse_srt_text


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_config(project_root: Path) -> dict[str, Any]:
    config_path = project_root if project_root.name == "project_config.json" else project_root / "project_config.json"
    return json.loads(config_path.read_text(encoding="utf-8"))


def next_round_dir(project_root: Path) -> Path:
    root = project_root / "qc_refinement"
    root.mkdir(parents=True, exist_ok=True)
    existing = sorted(path for path in root.glob("round_*") if path.is_dir())
    numbers: list[int] = []
    for path in existing:
        try:
            numbers.append(int(path.name.replace("round_", "")))
        except ValueError:
            continue
    number = max(numbers, default=0) + 1
    return root / f"round_{number:02d}"


def path_value(config: dict[str, Any], section: str, key: str) -> str:
    return str(config.get(section, {}).get(key, "") or "")


def load_dlsite_info(config: dict[str, Any]) -> dict[str, Any] | None:
    artifacts = config.get("artifacts", {})
    paths = config.get("paths", {})
    candidates = []
    if artifacts.get("dlsite_work_info"):
        candidates.append(Path(str(artifacts["dlsite_work_info"])))
    project_root = str(paths.get("project_root") or "")
    if project_root:
        candidates.append(Path(project_root) / "dlsite_work_info.json")
    work_id = str(config.get("work_id") or "")
    if work_id:
        candidates.append(Path("generated_subtitles") / work_id / "dlsite_work_info.json")
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            return data if isinstance(data, dict) else None
    return None


def collect_srt_samples(directory: Path, pattern: str, *, max_files: int = 6, max_items_per_file: int = 3) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    samples: list[dict[str, Any]] = []
    for path in sorted(directory.glob(pattern))[:max_files]:
        try:
            subtitles = parse_srt_text(path.read_text(encoding="utf-8"))
        except Exception:
            samples.append({"file": path.name, "error": "failed to parse"})
            continue
        sample_items = [
            {"i": subtitle.index, "text": subtitle.content}
            for subtitle in subtitles[:max_items_per_file]
            if subtitle.content.strip()
        ]
        samples.append({"file": path.name, "count": len(subtitles), "samples": sample_items})
    return samples


def render_context_profile(config: dict[str, Any], *, mode: str, focus: str, user_guidance: str) -> str:
    work_id = str(config.get("work_id") or "UNKNOWN")
    project_type = str(config.get("project_type") or "unknown")
    paths = config.get("paths", {})
    settings = config.get("settings", {})
    asr_dir_text = str(paths.get("asr_dir") or "")
    zh_srt_dir_text = str(paths.get("zh_srt_dir") or "")
    asr_dir = Path(asr_dir_text) if asr_dir_text else Path("__missing_asr_dir__")
    zh_srt_dir = Path(zh_srt_dir_text) if zh_srt_dir_text else Path("__missing_zh_srt_dir__")
    final_dir = str(paths.get("final_dir") or "")
    script_path = str(paths.get("script_path") or "")
    notes = config.get("notes", [])
    dlsite_info = load_dlsite_info(config)

    ja_samples = collect_srt_samples(asr_dir, "*.ja.asr.srt")
    zh_samples = collect_srt_samples(zh_srt_dir, "*.zh.srt")
    track_names = sorted({sample["file"].replace(".ja.asr.srt", "").replace(".zh.srt", "") for sample in ja_samples + zh_samples})

    lines = [
        f"# QC Context Profile - {work_id}",
        "",
        "## Round Mode",
        "",
        f"- mode: `{mode}`",
        f"- focus: {focus or '自动情境 QC'}",
        f"- user_guidance: {user_guidance or '无；由 agent 自动识别作品情境和当前字幕问题'}",
        "",
        "## Project",
        "",
        f"- work_id: `{work_id}`",
        f"- project_type: `{project_type}`",
        f"- output_format: `{settings.get('output_format', 'unknown')}`",
        f"- has_script: {'yes' if script_path else 'no'}",
        f"- final_dir: `{final_dir or '未记录'}`",
    ]
    if notes:
        lines.extend(["- project_notes:"] + [f"  - {note}" for note in notes])

    if dlsite_info:
        lines.extend(
            [
                "",
                "## DLsite Metadata",
                "",
                f"- source_url: `{dlsite_info.get('source_url', '')}`",
                f"- title: {dlsite_info.get('title', '') or '未取得'}",
                f"- circle: {dlsite_info.get('circle', '') or '未取得'}",
                f"- date_published: {dlsite_info.get('date_published', '') or '未取得'}",
            ]
        )
        keywords = dlsite_info.get("keywords")
        if isinstance(keywords, list) and keywords:
            lines.append("- keywords: " + " / ".join(str(item) for item in keywords[:30]))
        description = str(dlsite_info.get("description") or "").strip()
        if description:
            lines.extend(["- description:", f"  {description[:600]}"])
        if dlsite_info.get("error"):
            lines.append(f"- fetch_error: {dlsite_info['error']}")

    lines.extend(
        [
            "",
            "## Track Names",
            "",
        ]
    )
    if track_names:
        lines.extend([f"- {name}" for name in track_names[:20]])
    else:
        lines.append("- 未发现可抽样的 SRT 文件。")

    lines.extend(
        [
            "",
            "## Auto Context For QC",
            "",
            "- 先根据轨道名、日文 ASR、当前中文字幕判断作品主题、角色关系、称呼、语气强度和成人场景词。",
            "- 如果存在 DLsite metadata，把标题、社团、标签和简介作为低强度上下文；不要把商品介绍当成逐字台本。",
            "- 优先检查影响意义的问题：ASR 同音误识别、成人行为词错配、人称/称呼不稳、上下文逻辑断裂、字幕太机器翻译。",
            "- 不要把可接受字幕大面积改写成另一种风格；只输出明确值得修的候选项。",
            "- ASMR 字幕要保留亲密感和口语感，但不能为了润色而改变剧情或时间轴。",
            "- 本轮模型 QC 必须调用项目配置的本地/指定 QC 模型接口；agent 自身模型只能编排、读报告和做证据审查，不能替代 QC 模型。",
        ]
    )
    if mode == "guided":
        lines.append("- 本轮必须额外遵循用户引导词；如果用户引导词和源文证据冲突，优先保留源文意义并在问题说明里指出冲突。")

    lines.extend(["", "## JA ASR Samples", ""])
    for sample in ja_samples:
        lines.append(f"### {sample.get('file', '')}")
        if sample.get("error"):
            lines.append(f"- {sample['error']}")
            continue
        lines.append(f"- count: {sample.get('count', 0)}")
        for item in sample.get("samples", []):
            lines.append(f"- #{item['i']}: {item['text']}")
        lines.append("")

    lines.extend(["", "## Current ZH Samples", ""])
    for sample in zh_samples:
        lines.append(f"### {sample.get('file', '')}")
        if sample.get("error"):
            lines.append(f"- {sample['error']}")
            continue
        lines.append(f"- count: {sample.get('count', 0)}")
        for item in sample.get("samples", []):
            lines.append(f"- #{item['i']}: {item['text']}")
        lines.append("")

    lines.extend(
        [
            "## Reference Reminder",
            "",
            "- Before accepting suggestions, agent should still check `references/style.md`, `references/terms.md`, and `references/risk-notes.md` when relevant.",
            "- The model QC output remains candidate evidence only; final edits require agent evidence review.",
            "- Model QC means the configured local/project QC model call. Agent self-review is not a substitute for this round.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_manifest(config: dict[str, Any], round_dir: Path, *, mode: str, focus: str, user_guidance: str) -> dict[str, Any]:
    work_id = str(config.get("work_id") or round_dir.parent.parent.name)
    asr_dir = path_value(config, "paths", "asr_dir")
    zh_srt_dir = path_value(config, "paths", "zh_srt_dir")
    qc_model = path_value(config, "models", "qc_model") or path_value(config, "models", "translate_model")
    base_url = path_value(config, "models", "qc_base_url") or path_value(config, "models", "translate_base_url") or "http://127.0.0.1:8000/v1"
    qc_chunk_size = config.get("settings", {}).get("qc_chunk_size", 18)
    readability_max_cps = config.get("settings", {}).get("readability_max_cps", 10.0)

    return {
        "created_at": now_utc(),
        "work_id": work_id,
        "mode": mode,
        "focus": focus,
        "user_guidance": user_guidance,
        "inputs": {
            "asr_dir": asr_dir,
            "zh_srt_dir": zh_srt_dir,
        },
        "models": {
            "qc_model": qc_model,
            "base_url": base_url,
            "qc_chunk_size": qc_chunk_size,
            "invocation_discipline": "Run QC through the configured local/project QC endpoint; agent self-QC is not a substitute.",
        },
        "artifacts": {
            "context_profile": (round_dir / "context_profile.md").as_posix(),
            "qc_report": (round_dir / "qc_report.json").as_posix(),
            "qc_review": (round_dir / "qc_review.md").as_posix(),
            "qc_review_items": (round_dir / "qc_review_items.json").as_posix(),
            "qc_apply_report": (round_dir / "qc_apply_report.json").as_posix(),
            "backup_dir": (round_dir / "backup").as_posix(),
            "validate_report": (round_dir / "validate_report.json").as_posix(),
            "risk_report": (round_dir / "risk_report.json").as_posix(),
            "readability_report": (round_dir / "readability_report.json").as_posix(),
        },
        "settings": {
            "readability_max_cps": readability_max_cps,
        },
        "status": "created",
    }


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def render_next_steps(manifest: dict[str, Any]) -> str:
    inputs = manifest["inputs"]
    models = manifest["models"]
    artifacts = manifest["artifacts"]
    settings = manifest["settings"]
    focus = manifest.get("focus", "")
    mode = manifest.get("mode", "auto")
    user_guidance = manifest.get("user_guidance", "")
    context = f"追加 QC 精修 mode={mode}; focus={focus or 'auto'}"
    if user_guidance:
        context += f"; user_guidance={user_guidance}"
    api_key = "$TRANSLATE_API_KEY"

    return "\n".join(
        [
            "# QC Refinement Round",
            "",
            "Model invocation discipline: this round must call the configured local/project QC chat model via `scripts/qc_srt_omlx.py`. Agent self-review may prepare focus and accept/reject decisions, but it is not model QC. If the endpoint/model is unavailable, stop and fix the backend selection instead of substituting the agent model.",
            "",
            "1. Run focused model QC:",
            "",
            "```bash",
            "python scripts/qc_srt_omlx.py \\",
            f"  --asr-dir {shell_quote(inputs['asr_dir'])} \\",
            f"  --zh-dir {shell_quote(inputs['zh_srt_dir'])} \\",
            f"  --out {shell_quote(artifacts['qc_report'])} \\",
            f"  --api-key {api_key} \\",
            f"  --base-url {shell_quote(models['base_url'])} \\",
            f"  --model {shell_quote(models['qc_model'])} \\",
            f"  --chunk-size {models['qc_chunk_size']} \\",
            "  --chunk-mode dynamic \\",
            f"  --context {shell_quote(context)} \\",
            f"  --context-file {shell_quote(artifacts['context_profile'])}",
            "```",
            "",
            "2. Normalize QC suggestions:",
            "",
            "```bash",
            "python scripts/review_qc_report.py \\",
            f"  {shell_quote(artifacts['qc_report'])} \\",
            f"  --asr-dir {shell_quote(inputs['asr_dir'])} \\",
            f"  --zh-dir {shell_quote(inputs['zh_srt_dir'])} \\",
            f"  --out {shell_quote(artifacts['qc_review'])} \\",
            f"  --json-out {shell_quote(artifacts['qc_review_items'])}",
            "```",
            "",
            "3. Agent reviews evidence and edits `qc_review_items.json`: set `decision` to `accept`, `reject`, or `defer`; set `replacement` when needed.",
            "",
            "4. Dry-run accepted decisions:",
            "",
            "```bash",
            "python scripts/apply_qc_decisions.py \\",
            f"  {shell_quote(artifacts['qc_review_items'])} \\",
            f"  --zh-dir {shell_quote(inputs['zh_srt_dir'])} \\",
            f"  --json-out {shell_quote(artifacts['qc_apply_report'])}",
            "```",
            "",
            "5. Apply accepted decisions:",
            "",
            "```bash",
            "python scripts/apply_qc_decisions.py \\",
            f"  {shell_quote(artifacts['qc_review_items'])} \\",
            f"  --zh-dir {shell_quote(inputs['zh_srt_dir'])} \\",
            "  --apply \\",
            f"  --backup-dir {shell_quote(artifacts['backup_dir'])} \\",
            f"  --json-out {shell_quote(artifacts['qc_apply_report'])}",
            "```",
            "",
            "6. Rerun checks:",
            "",
            "```bash",
            "python scripts/validate_subtitles.py \\",
            f"  --asr-dir {shell_quote(inputs['asr_dir'])} \\",
            f"  --zh-dir {shell_quote(inputs['zh_srt_dir'])} \\",
            f"  --json-out {shell_quote(artifacts['validate_report'])}",
            "",
            "python scripts/scan_subtitle_risks.py \\",
            f"  {shell_quote(inputs['zh_srt_dir'])} \\",
            f"  --json-out {shell_quote(artifacts['risk_report'])}",
            "",
            "python scripts/subtitle_readability.py \\",
            f"  {shell_quote(inputs['zh_srt_dir'])} \\",
            f"  --max-cps {settings['readability_max_cps']} \\",
            f"  --json-out {shell_quote(artifacts['readability_report'])}",
            "```",
            "",
            "Repeat another refinement round only if the user still wants more line-level polish or unresolved issues remain.",
            "",
        ]
    )


def count_json_items(path: Path) -> int | None:
    if not path.exists():
        return None
    if path.suffix.lower() != ".json":
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return sum(len(value) for value in data.values() if isinstance(value, list))
    if isinstance(data, list):
        return len(data)
    return None


def summarize(manifest_path: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts", {})
    lines = [
        f"work_id: {manifest.get('work_id', '')}",
        f"mode: {manifest.get('mode', '')}",
        f"focus: {manifest.get('focus', '')}",
        f"user_guidance: {manifest.get('user_guidance', '')}",
    ]
    for key in ["context_profile", "qc_report", "qc_review_items", "qc_apply_report", "validate_report", "risk_report", "readability_report"]:
        path = Path(artifacts.get(key, ""))
        count = count_json_items(path) if str(path) else None
        if path.exists():
            detail = f"{count} items" if count is not None else "exists"
        else:
            detail = "missing"
        lines.append(f"{key}: {path.as_posix()} ({detail})")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or summarize optional post-mandatory-QC refinement rounds.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Create a new QC refinement round manifest and command checklist.")
    start.add_argument("project_root", help="Project output root with project_config.json.")
    start.add_argument("--mode", default="auto", choices=["auto", "guided"], help="auto builds context from project artifacts; guided also records user guidance.")
    start.add_argument("--focus", default="", help="User dissatisfaction or polish focus for this refinement round.")
    start.add_argument("--user-guidance", default="", help="User guidance, style notes, or specific translation problems for guided refinement.")
    start.add_argument("--out", help="Optional path for the rendered command checklist. Defaults to <round>/next_steps.md.")

    summary = subparsers.add_parser("summary", help="Summarize a refinement round manifest.")
    summary.add_argument("manifest", help="Path to a round manifest.json.")

    args = parser.parse_args()

    if args.command == "start":
        if args.mode == "guided" and not args.user_guidance.strip():
            raise SystemExit("--user-guidance is required when --mode guided.")
        project_root = Path(args.project_root)
        config = read_config(project_root)
        round_dir = next_round_dir(project_root)
        round_dir.mkdir(parents=True, exist_ok=False)
        manifest = build_manifest(config, round_dir, mode=args.mode, focus=args.focus, user_guidance=args.user_guidance)
        context_profile = render_context_profile(
            config,
            mode=args.mode,
            focus=args.focus,
            user_guidance=args.user_guidance,
        )
        manifest_path = round_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        Path(manifest["artifacts"]["context_profile"]).write_text(context_profile, encoding="utf-8")
        steps = render_next_steps(manifest)
        out = Path(args.out) if args.out else round_dir / "next_steps.md"
        out.write_text(steps, encoding="utf-8")
        print(manifest_path.as_posix())
        print(out.as_posix())
        return 0

    print(summarize(Path(args.manifest)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
