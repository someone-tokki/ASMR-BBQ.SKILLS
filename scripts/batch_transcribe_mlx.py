#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from asr_resume import (
    load_manifest,
    output_paths,
    record_manifest,
    reusable_outputs,
    save_manifest,
    write_json_atomic,
    write_srt_from_result,
)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--glob", default="*.wav")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--word-timestamps", action="store_true")
    parser.add_argument("--manifest", default="", help="ASR resume manifest path. Defaults to <out-dir>/asr_manifest.json.")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Do not skip complete existing outputs.")
    parser.add_argument("--force", action="store_true", help="Transcribe even when reusable outputs already exist.")
    parser.set_defaults(resume=True)
    args = parser.parse_args()

    try:
        import mlx_whisper
    except ImportError as exc:
        raise SystemExit(
            "mlx_whisper is not available. This script is only for the explicitly selected mlx_whisper ASR route; "
            "do not auto-install ASR packages or download models. Choose an existing .ja.asr.srt, an installed external ASR command/service, "
            "or explicitly approve mlx_whisper setup."
        ) from exc

    audio_dir = Path(args.audio_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest) if args.manifest else out_dir / "asr_manifest.json"
    manifest = load_manifest(manifest_path)

    files = sorted(path for path in audio_dir.glob(args.glob) if path.is_file() and not path.name.startswith("._"))
    for audio in files:
        json_path, srt_path = output_paths(audio, out_dir)
        if args.resume and not args.force:
            reusable, reason = reusable_outputs(audio, out_dir)
            if reusable:
                record_manifest(
                    manifest,
                    audio_path=audio,
                    backend="mlx_whisper",
                    model=args.model,
                    base_url="",
                    json_path=json_path,
                    srt_path=srt_path,
                    status="skipped",
                    message=reason,
                )
                save_manifest(manifest_path, manifest)
                print(f"SKIP_EXISTING {srt_path}", flush=True)
                continue
        print(f"TRANSCRIBING {audio.name}", flush=True)
        try:
            result = mlx_whisper.transcribe(
                str(audio),
                path_or_hf_repo=args.model,
                language=args.language,
                task="transcribe",
                verbose=False,
                word_timestamps=args.word_timestamps,
                condition_on_previous_text=False,
                initial_prompt="これは日本語の成人向けASMR音声です。囁き、吐息、間、擬音が多いです。",
            )
            write_json_atomic(json_path, result)
            write_srt_from_result(result, srt_path)
            record_manifest(
                manifest,
                audio_path=audio,
                backend="mlx_whisper",
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
                audio_path=audio,
                backend="mlx_whisper",
                model=args.model,
                base_url="",
                json_path=json_path,
                srt_path=srt_path,
                status="error",
                message=str(exc),
            )
            save_manifest(manifest_path, manifest)
            raise
        print(f"WROTE {srt_path}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
