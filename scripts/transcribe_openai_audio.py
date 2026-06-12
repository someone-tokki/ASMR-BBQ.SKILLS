#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import uuid
import urllib.error
import urllib.request
from pathlib import Path


AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".webm"}


def srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_srt_from_segments(data: dict, output: Path) -> None:
    segments = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(segments, list) or not segments:
        text = str(data.get("text", "")).strip() if isinstance(data, dict) else ""
        segments = [{"start": 0.0, "end": 1.0, "text": text}] if text else []

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


def multipart_body(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----asmr-subs-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(str(value).encode())
        chunks.append(b"\r\n")

    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode()
    )
    chunks.append(file_path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def transcribe(audio_path: Path, *, base_url: str, api_key: str, model: str, language: str, timeout: int) -> dict:
    url = base_url.rstrip("/") + "/audio/transcriptions"
    body, boundary = multipart_body(
        {
            "model": model,
            "language": language,
            "response_format": "verbose_json",
        },
        "file",
        audio_path,
    )
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ASR API returned HTTP {exc.code} from {url}: {detail[:500]}") from exc
    except Exception as exc:
        raise RuntimeError(f"Cannot reach local ASR API at {url}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ASR API did not return JSON verbose transcription: {raw[:500]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("ASR API JSON response must be an object")
    return data


def collect_audio(input_path: Path, pattern: str, recursive: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in AUDIO_EXTENSIONS else []
    glob_pattern = f"**/{pattern}" if recursive else pattern
    return sorted(path for path in input_path.glob(glob_pattern) if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe audio through a local OpenAI-compatible /audio/transcriptions endpoint.")
    parser.add_argument("input", help="Audio file or directory.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--api-key", default="local-placeholder")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--glob", default="*.wav")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)
    audio_files = collect_audio(input_path, args.glob, args.recursive)
    if not audio_files:
        raise SystemExit(f"No supported audio files found: {input_path}")

    for audio_path in audio_files:
        print(f"TRANSCRIBING {audio_path}", flush=True)
        data = transcribe(
            audio_path,
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.model,
            language=args.language,
            timeout=args.timeout,
        )
        json_path = out_dir / f"{audio_path.stem}.ja.asr.json"
        srt_path = out_dir / f"{audio_path.stem}.ja.asr.srt"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_srt_from_segments(data, srt_path)
        print(f"WROTE {json_path}")
        print(f"WROTE {srt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
