#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from preflight_gate import add_preflight_args, enforce_preflight
from asr_resume import (
    load_manifest,
    output_paths,
    record_manifest,
    reusable_outputs,
    save_manifest,
    write_json_atomic,
    write_srt_from_result,
)


AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".webm"}


def collect_audio(input_path: Path, pattern: str, recursive: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in AUDIO_EXTENSIONS else []
    glob_pattern = f"**/{pattern}" if recursive else pattern
    return sorted(path for path in input_path.glob(glob_pattern) if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe Japanese ASMR audio with local Python openai-whisper.")
    parser.add_argument("input", help="Audio file or directory.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--glob", default="*.wav")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--device", default=None, help="Optional whisper device, such as cpu or cuda.")
    parser.add_argument("--fp16", action="store_true", help="Enable fp16. Leave off for CPU/default portability.")
    parser.add_argument(
        "--initial-prompt",
        default="これは日本語の成人向けASMR音声です。囁き、吐息、間、擬音が多いです。",
        help="Initial Whisper prompt for vocabulary/tone continuity.",
    )
    parser.add_argument("--manifest", default="", help="ASR resume manifest path. Defaults to <out-dir>/asr_manifest.json.")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Do not skip complete existing outputs.")
    parser.add_argument("--force", action="store_true", help="Transcribe even when reusable outputs already exist.")
    add_preflight_args(parser)
    parser.set_defaults(resume=True)
    args = parser.parse_args()
    enforce_preflight(args, "asr")

    try:
        import whisper
    except ImportError as exc:
        raise SystemExit(
            "Python package `whisper` is not available. Run scripts/setup_whisper_backend.py after user approval "
            "to install openai-whisper and download the selected model."
        ) from exc

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)
    manifest_path = Path(args.manifest) if args.manifest else out_dir / "asr_manifest.json"
    manifest = load_manifest(manifest_path)
    audio_files = collect_audio(input_path, args.glob, args.recursive)
    if not audio_files:
        raise SystemExit(f"No supported audio files found: {input_path}")

    pending_audio: list[Path] = []
    for audio_path in audio_files:
        json_path, srt_path = output_paths(audio_path, out_dir)
        if args.resume and not args.force:
            reusable, reason = reusable_outputs(audio_path, out_dir)
            if reusable:
                record_manifest(
                    manifest,
                    audio_path=audio_path,
                    backend="python-whisper",
                    model=args.model,
                    base_url="",
                    json_path=json_path,
                    srt_path=srt_path,
                    status="skipped",
                    message=reason,
                )
                save_manifest(manifest_path, manifest)
                print(f"SKIP_EXISTING {srt_path}")
                continue
        pending_audio.append(audio_path)

    if not pending_audio:
        return 0

    model = whisper.load_model(args.model, device=args.device)
    for audio_path in pending_audio:
        json_path, srt_path = output_paths(audio_path, out_dir)
        print(f"TRANSCRIBING {audio_path}", flush=True)
        try:
            result = model.transcribe(
                str(audio_path),
                language=args.language,
                task="transcribe",
                verbose=False,
                fp16=args.fp16,
                condition_on_previous_text=False,
                initial_prompt=args.initial_prompt,
            )
            write_json_atomic(json_path, result)
            write_srt_from_result(result, srt_path)
            record_manifest(
                manifest,
                audio_path=audio_path,
                backend="python-whisper",
                model=args.model,
                base_url="",
                json_path=json_path,
                srt_path=srt_path,
                status="success",
            )
            save_manifest(manifest_path, manifest)
        except Exception as exc:
            record_manifest(
                manifest,
                audio_path=audio_path,
                backend="python-whisper",
                model=args.model,
                base_url="",
                json_path=json_path,
                srt_path=srt_path,
                status="error",
                message=str(exc),
            )
            save_manifest(manifest_path, manifest)
            raise
        print(f"WROTE {json_path}")
        print(f"WROTE {srt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
