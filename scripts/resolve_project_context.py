#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


RJ_RE = re.compile(r"(RJ\d{6,10})", re.IGNORECASE)


def normalize_work_id(value: str) -> str:
    match = RJ_RE.search(value)
    if match:
        return match.group(1).upper()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return cleaned or "unknown_work"


def path_candidates(paths: list[Path]) -> list[str]:
    values: list[str] = []
    for path in paths:
        values.append(path.as_posix())
        values.extend(path.parts)
        values.extend(parent.name for parent in path.parents)
    values.append(Path.cwd().as_posix())
    values.extend(Path.cwd().parts)
    return values


def infer_work_id(paths: list[Path], explicit: str | None) -> tuple[str, str]:
    if explicit:
        return normalize_work_id(explicit), "explicit"
    for value in path_candidates(paths):
        match = RJ_RE.search(value)
        if match:
            return match.group(1).upper(), f"path:{value}"
    if paths:
        first = paths[0]
        base = first.name if first.name else first.parent.name
        return normalize_work_id(base), f"fallback:{base}"
    return normalize_work_id(Path.cwd().name), "fallback:cwd"


def likely_file_path(path: Path) -> bool:
    if path.exists():
        return path.is_file()
    return bool(path.suffix)


def infer_source_project_dir(paths: list[Path], work_id: str) -> Path:
    normalized_work_id = normalize_work_id(work_id)
    for raw_path in paths:
        path = raw_path.parent if likely_file_path(raw_path) else raw_path
        for candidate in [path, *path.parents]:
            if normalize_work_id(candidate.name) == normalized_work_id:
                return candidate
    if paths:
        first = paths[0]
        return first.parent if likely_file_path(first) else first
    return Path.cwd()


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.expanduser().as_posix()


def build_context(args: argparse.Namespace) -> dict:
    sources = [Path(value).expanduser() for value in args.sources]
    work_id, source = infer_work_id(sources, args.work_id)
    source_project_dir = Path(args.source_project_dir).expanduser() if args.source_project_dir else infer_source_project_dir(sources, work_id)
    output_root = Path(args.output_root).expanduser() if args.output_root else None
    if args.project_root:
        project_root = Path(args.project_root).expanduser()
    elif output_root:
        project_root = output_root / work_id
    else:
        project_root = source_project_dir / args.project_dir_name
    final_subtitle_dir = (
        Path(args.final_subtitle_dir).expanduser()
        if args.final_subtitle_dir
        else source_project_dir / args.final_subtitle_dir_name
    )

    if args.source_audio_dir:
        source_audio_dir = Path(args.source_audio_dir).expanduser()
    elif sources:
        source_audio_dir = sources[0].parent if likely_file_path(sources[0]) else sources[0]
    else:
        source_audio_dir = Path("")
    if args.mkdir:
        project_root.mkdir(parents=True, exist_ok=True)
        final_subtitle_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    try:
        resolved_project_root = project_root.resolve()
        resolved_source_audio = source_audio_dir.resolve()
        resolved_source_project = source_project_dir.resolve()
        resolved_project_root.relative_to(resolved_source_audio)
        if resolved_source_audio != resolved_source_project and resolved_project_root != resolved_source_audio:
            warnings.append("project_root is inside source_audio_dir; confirm the source path is the ASMR package root, not a narrow audio subfolder.")
    except (ValueError, OSError):
        pass

    return {
        "work_id": work_id,
        "work_id_source": source,
        "project_root": display_path(project_root),
        "output_root": display_path(output_root) if output_root else "",
        "source_project_dir": display_path(source_project_dir),
        "final_subtitle_dir": display_path(final_subtitle_dir),
        "source_audio_dir": display_path(source_audio_dir) if source_audio_dir else "",
        "warnings": warnings,
        "notes": [
            "By default, project_root is a subtitle_project folder under the source ASMR work directory. Use it for generated ASR, SRT work files, QC reports, and learning drafts.",
            "Use final_subtitle_dir for deliverable .zh.vtt/.zh.srt files. By default it is a subtitles folder under the source ASMR work directory.",
            "Do not write work artifacts into a narrow audio-only subfolder unless the user explicitly chooses that as project_root.",
            "If a parent folder is named like RJxxxx, that RJ number is the work_id even when the immediate audio folder has a generic name.",
        ],
    }


def print_shell(context: dict) -> None:
    print(f"WORK_ID={context['work_id']}")
    print(f"PROJECT_ROOT={context['project_root']}")
    print(f"SOURCE_PROJECT_DIR={context['source_project_dir']}")
    print(f"FINAL_SUBTITLE_DIR={context['final_subtitle_dir']}")
    if context.get("source_audio_dir"):
        print(f"SOURCE_AUDIO_DIR={context['source_audio_dir']}")
    for warning in context.get("warnings", []):
        print(f"WARNING: {warning}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve ASMR work_id and workspace output paths before starting a subtitle project.")
    parser.add_argument("sources", nargs="*", help="Source audio/script/project paths. Parent folders are scanned for RJ IDs.")
    parser.add_argument("--work-id", help="Explicit work ID. Overrides path inference.")
    parser.add_argument("--source-audio-dir", help="Explicit source audio directory to record.")
    parser.add_argument("--source-project-dir", help="Explicit source ASMR work directory. Defaults to the RJ parent folder when present.")
    parser.add_argument("--output-root", help="Optional alternate output root. If set, project_root defaults to <output-root>/<work_id>.")
    parser.add_argument("--project-root", help="Explicit project output root. Defaults to <source ASMR work directory>/<project-dir-name>.")
    parser.add_argument("--project-dir-name", default="subtitle_project", help="Folder name created under the source ASMR work directory for project artifacts and intermediate files.")
    parser.add_argument("--final-subtitle-dir", help="Explicit final subtitle delivery directory.")
    parser.add_argument("--final-subtitle-dir-name", default="subtitles", help="Folder name created under the source ASMR work directory for final .zh.vtt/.zh.srt files.")
    parser.add_argument("--mkdir", action="store_true", help="Create the project_root directory.")
    parser.add_argument("--json-out", help="Write context JSON.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of shell-style key/value output.")
    args = parser.parse_args()

    context = build_context(args)
    if args.json:
        print(json.dumps(context, ensure_ascii=False, indent=2))
    else:
        print_shell(context)
    if args.json_out:
        out_path = Path(args.json_out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"WROTE {display_path(out_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
