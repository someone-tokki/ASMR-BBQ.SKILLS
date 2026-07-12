#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import uuid
import urllib.error
import urllib.request
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


def transcribe(audio_path: Path, *, base_url: str, api_key: str, model: str, language: str, timeout: int, prompt: str) -> dict:
    url = base_url.rstrip("/") + "/audio/transcriptions"
    fields = {
        "model": model,
        "language": language,
        "response_format": "verbose_json",
    }
    if prompt:
        fields["prompt"] = prompt
    body, boundary = multipart_body(
        fields,
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
        return [input_path] if not input_path.name.startswith("._") and input_path.suffix.lower() in AUDIO_EXTENSIONS else []
    glob_pattern = f"**/{pattern}" if recursive else pattern
    return sorted(path for path in input_path.glob(glob_pattern) if path.is_file() and not path.name.startswith("._") and path.suffix.lower() in AUDIO_EXTENSIONS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe audio through a local OpenAI-compatible /audio/transcriptions endpoint.")
    parser.add_argument("input", help="Audio file or directory.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--api-key", default="local-placeholder")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--language", default="ja")
    parser.add_argument(
        "--prompt",
        default="これは日本語の成人向けASMR音声です。囁き、吐息、間、擬音が多いです。",
        help="Optional ASR prompt for compatible /audio/transcriptions endpoints.",
    )
    parser.add_argument("--glob", default="*.wav")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--manifest", default="", help="ASR resume manifest path. Defaults to <out-dir>/asr_manifest.json.")
    parser.add_argument("--backend-label", default="local-asr-api", help="Backend label recorded in the ASR manifest.")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Do not skip complete existing outputs.")
    parser.add_argument("--force", action="store_true", help="Transcribe even when reusable outputs already exist.")
    add_preflight_args(parser)
    parser.set_defaults(resume=True)
    args = parser.parse_args()
    enforce_preflight(args, "asr")

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)
    manifest_path = Path(args.manifest) if args.manifest else out_dir / "asr_manifest.json"
    manifest = load_manifest(manifest_path)
    audio_files = collect_audio(input_path, args.glob, args.recursive)
    if not audio_files:
        raise SystemExit(f"No supported audio files found: {input_path}")

    for audio_path in audio_files:
        json_path, srt_path = output_paths(audio_path, out_dir)
        if args.resume and not args.force:
            reusable, reason = reusable_outputs(audio_path, out_dir)
            if reusable:
                record_manifest(
                    manifest,
                    audio_path=audio_path,
                    backend=args.backend_label,
                    model=args.model,
                    base_url=args.base_url,
                    json_path=json_path,
                    srt_path=srt_path,
                    status="skipped",
                    message=reason,
                )
                save_manifest(manifest_path, manifest)
                print(f"SKIP_EXISTING {srt_path}")
                continue
        print(f"TRANSCRIBING {audio_path}", flush=True)
        try:
            data = transcribe(
                audio_path,
                base_url=args.base_url,
                api_key=args.api_key,
                model=args.model,
                language=args.language,
                timeout=args.timeout,
                prompt=args.prompt,
            )
            write_json_atomic(json_path, data)
            write_srt_from_result(data, srt_path)
            record_manifest(
                manifest,
                audio_path=audio_path,
                backend=args.backend_label,
                model=args.model,
                base_url=args.base_url,
                json_path=json_path,
                srt_path=srt_path,
                status="success",
            )
            save_manifest(manifest_path, manifest)
        except Exception as exc:
            record_manifest(
                manifest,
                audio_path=audio_path,
                backend=args.backend_label,
                model=args.model,
                base_url=args.base_url,
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
