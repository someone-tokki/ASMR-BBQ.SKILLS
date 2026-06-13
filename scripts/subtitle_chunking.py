#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


RISK_TERMS = [
    "耳舐め",
    "耳舐",
    "耳なめ",
    "おちんちん",
    "ちんちん",
    "射精",
    "中出し",
    "フェラ",
    "手コキ",
    "乳首",
    "挿入",
    "騎乗位",
    "キス",
    "喘",
    "耳舔",
    "舔耳",
    "射精",
    "口交",
    "手冲",
    "乳头",
    "插入",
    "骑乘",
]


@dataclass(frozen=True)
class Chunk:
    chunk_no: int
    items: list[dict[str, Any]]
    context_before: list[dict[str, Any]]
    context_after: list[dict[str, Any]]
    reason: str

    @property
    def target_indexes(self) -> list[int]:
        return [int(item["i"]) for item in self.items]


def item_text(item: dict[str, Any]) -> str:
    parts = [str(item.get(key, "")) for key in ("text", "ja", "zh")]
    return "\n".join(part for part in parts if part)


def item_chars(item: dict[str, Any]) -> int:
    return len(item_text(item))


def item_risk_score(item: dict[str, Any]) -> int:
    text = item_text(item)
    score = sum(1 for term in RISK_TERMS if term in text)
    if len(text) > 140:
        score += 1
    if "\n" in str(item.get("zh", "")):
        score += 1
    if any(marker in text for marker in ["???", "？？？", "�", "□"]):
        score += 2
    if any("\u3040" <= ch <= "\u30ff" for ch in str(item.get("zh", ""))):
        score += 1
    return score


def time_gap(prev: dict[str, Any], current: dict[str, Any]) -> float:
    try:
        return float(current.get("start", 0.0)) - float(prev.get("end", 0.0))
    except Exception:
        return 0.0


def natural_boundary(prev: dict[str, Any], current: dict[str, Any], *, gap_seconds: float) -> bool:
    if time_gap(prev, current) >= gap_seconds:
        return True
    text = item_text(prev).strip()
    if text.endswith(("。", "！", "？", "…", "……", ".", "!", "?")) and len(text) >= 18:
        return True
    return False


def add_halo(items: list[dict[str, Any]], chunks: list[tuple[list[dict[str, Any]], str]], halo: int) -> list[Chunk]:
    index_to_position = {int(item["i"]): pos for pos, item in enumerate(items)}
    result: list[Chunk] = []
    for chunk_no, (target_items, reason) in enumerate(chunks, start=1):
        start_pos = index_to_position[int(target_items[0]["i"])]
        end_pos = index_to_position[int(target_items[-1]["i"])]
        before = items[max(0, start_pos - halo) : start_pos]
        after = items[end_pos + 1 : end_pos + 1 + halo]
        result.append(
            Chunk(
                chunk_no=chunk_no,
                items=target_items,
                context_before=before,
                context_after=after,
                reason=reason,
            )
        )
    return result


def build_semantic_chunks(
    items: list[dict[str, Any]],
    *,
    mode: str,
    chunk_size: int,
    min_chunk_size: int,
    max_chunk_size: int,
    target_chars: int,
    hard_chars: int,
    halo: int = 0,
    gap_seconds: float = 1.2,
    risk_score_fn: Callable[[dict[str, Any]], int] = item_risk_score,
) -> list[Chunk]:
    if not items:
        return []
    if mode == "fixed":
        fixed = [(items[start : start + chunk_size], "fixed_size") for start in range(0, len(items), chunk_size)]
        return add_halo(items, fixed, halo)

    raw_chunks: list[tuple[list[dict[str, Any]], str]] = []
    current: list[dict[str, Any]] = []
    chars = 0
    risk = 0
    last_reason = "end"
    for item in items:
        if current:
            prev = current[-1]
            gap_boundary = natural_boundary(prev, item, gap_seconds=gap_seconds)
            if len(current) >= min_chunk_size and chars >= target_chars and gap_boundary:
                raw_chunks.append((current, "semantic_gap_or_sentence"))
                current = []
                chars = 0
                risk = 0
        current.append(item)
        chars += item_chars(item)
        risk += risk_score_fn(item)
        current_len = len(current)
        should_cut = False
        if current_len >= max_chunk_size:
            should_cut = True
            last_reason = "max_chunk_size"
        elif current_len >= min_chunk_size and chars >= hard_chars:
            should_cut = True
            last_reason = "hard_chars"
        elif current_len >= min_chunk_size and risk >= 5:
            should_cut = True
            last_reason = "risk_density"
        elif current_len >= chunk_size and chars >= target_chars:
            should_cut = True
            last_reason = "target_chars"
        if should_cut:
            raw_chunks.append((current, last_reason))
            current = []
            chars = 0
            risk = 0
            last_reason = "end"
    if current:
        raw_chunks.append((current, last_reason))
    return add_halo(items, raw_chunks, halo)


def build_chunks_from_indexes(
    items: list[dict[str, Any]],
    target_index_groups: list[list[int]],
    *,
    halo: int,
    reason: str = "manifest_reuse",
) -> list[Chunk]:
    by_index = {int(item["i"]): item for item in items}
    raw: list[tuple[list[dict[str, Any]], str]] = []
    for group in target_index_groups:
        target = [by_index[index] for index in group if index in by_index]
        if target and len(target) == len(group):
            raw.append((target, reason))
    return add_halo(items, raw, halo)


def chunk_summary(chunk: Chunk) -> dict[str, Any]:
    return {
        "start_i": chunk.target_indexes[0],
        "end_i": chunk.target_indexes[-1],
        "target_indexes": chunk.target_indexes,
        "context_before_indexes": [int(item["i"]) for item in chunk.context_before],
        "context_after_indexes": [int(item["i"]) for item in chunk.context_after],
        "count": len(chunk.items),
        "chars": sum(item_chars(item) for item in chunk.items),
        "risk_score": sum(item_risk_score(item) for item in chunk.items),
        "reason": chunk.reason,
    }
