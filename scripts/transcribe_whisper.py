#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".webm"}


def srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_srt(segments: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        index = 1
        for segment in segments:
            text = " ".join(str(segment.get("text", "")).split())
            if not text:
                continue
            start = float(segment.get("start", 0.0))
            end = max(start + 0.1, float(segment.get("end", start + 1.0)))
            fh.write(f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n\n")
            index += 1


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
    args = parser.parse_args()

    try:
        import whisper
    except ImportError as exc:
        raise SystemExit(
            "Python package `whisper` is not available. Run scripts/setup_whisper_backend.py after user approval "
            "to install openai-whisper and download the selected model."
        ) from exc

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)
    audio_files = collect_audio(input_path, args.glob, args.recursive)
    if not audio_files:
        raise SystemExit(f"No supported audio files found: {input_path}")

    model = whisper.load_model(args.model, device=args.device)
    for audio_path in audio_files:
        print(f"TRANSCRIBING {audio_path}", flush=True)
        result = model.transcribe(
            str(audio_path),
            language=args.language,
            task="transcribe",
            verbose=False,
            fp16=args.fp16,
            condition_on_previous_text=False,
            initial_prompt="これは日本語の成人向けASMR音声です。囁き、吐息、間、擬音が多いです。",
        )
        json_path = out_dir / f"{audio_path.stem}.ja.asr.json"
        srt_path = out_dir / f"{audio_path.stem}.ja.asr.srt"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_srt(result.get("segments", []), srt_path)
        print(f"WROTE {json_path}")
        print(f"WROTE {srt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
