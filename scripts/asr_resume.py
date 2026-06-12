from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from subtitle_io import parse_srt_text


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def audio_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": path.as_posix(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def output_paths(audio_path: Path, out_dir: Path) -> tuple[Path, Path]:
    return out_dir / f"{audio_path.stem}.ja.asr.json", out_dir / f"{audio_path.stem}.ja.asr.srt"


def srt_is_complete(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        return bool(parse_srt_text(path.read_text(encoding="utf-8")))
    except Exception:
        return False


def load_json_result(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def write_srt_from_segments(segments: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        index = 1
        for segment in segments:
            text = " ".join(str(segment.get("text", "")).split())
            if not text:
                continue
            start = float(segment.get("start", 0.0))
            end = max(start + 0.1, float(segment.get("end", start + 1.0)))
            fh.write(f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n\n")
            index += 1
    temp.replace(output)


def write_srt_from_result(data: dict[str, Any], output: Path) -> bool:
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        text = str(data.get("text", "")).strip()
        segments = [{"start": 0.0, "end": 1.0, "text": text}] if text else []
    write_srt_from_segments(segments, output)
    return srt_is_complete(output)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "entries": {}}
    if not isinstance(data, dict):
        return {"version": 1, "entries": {}}
    data.setdefault("version", 1)
    data.setdefault("entries", {})
    if not isinstance(data["entries"], dict):
        data["entries"] = {}
    return data


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = now_utc()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def record_manifest(
    manifest: dict[str, Any],
    *,
    audio_path: Path,
    backend: str,
    model: str,
    base_url: str,
    json_path: Path,
    srt_path: Path,
    status: str,
    message: str = "",
) -> None:
    manifest.setdefault("entries", {})[audio_path.as_posix()] = {
        "audio": audio_fingerprint(audio_path),
        "backend": backend,
        "model": model,
        "base_url": base_url,
        "json_path": json_path.as_posix(),
        "srt_path": srt_path.as_posix(),
        "status": status,
        "message": message,
        "updated_at": now_utc(),
    }


def reusable_outputs(audio_path: Path, out_dir: Path) -> tuple[bool, str]:
    json_path, srt_path = output_paths(audio_path, out_dir)
    if srt_is_complete(srt_path):
        return True, "srt_complete"
    data = load_json_result(json_path)
    if data and write_srt_from_result(data, srt_path):
        return True, "rebuilt_srt_from_json"
    return False, "missing_or_incomplete"


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
