#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_srt(segments: list[dict], output: Path) -> None:
    with output.open("w", encoding="utf-8") as fh:
        index = 1
        for segment in segments:
            text = " ".join(segment.get("text", "").split())
            if not text:
                continue
            fh.write(f"{index}\n")
            fh.write(f"{srt_time(segment['start'])} --> {srt_time(segment['end'])}\n")
            fh.write(f"{text}\n\n")
            index += 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--glob", default="*.wav")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--word-timestamps", action="store_true")
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

    files = sorted(audio_dir.glob(args.glob))
    for audio in files:
        print(f"TRANSCRIBING {audio.name}", flush=True)
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
        json_path = out_dir / f"{audio.stem}.ja.asr.json"
        srt_path = out_dir / f"{audio.stem}.ja.asr.srt"
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        write_srt(result.get("segments", []), srt_path)
        print(f"WROTE {srt_path}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
