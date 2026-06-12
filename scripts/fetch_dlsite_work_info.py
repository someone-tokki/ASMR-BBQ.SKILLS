#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RJ_RE = re.compile(r"\b(RJ\d{6,10})\b", re.IGNORECASE)


class PageMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.json_ld_texts: list[str] = []
        self._in_title = False
        self._json_ld_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = attr.get("property") or attr.get("name")
            content = attr.get("content")
            if key and content:
                self.meta[key.lower()] = html.unescape(content).strip()
        elif tag == "script" and attr.get("type", "").lower() == "application/ld+json":
            self._json_ld_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._json_ld_depth:
            self._json_ld_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif self._json_ld_depth:
            self.json_ld_texts.append(data)


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def extract_work_id(value: str) -> str:
    match = RJ_RE.search(value)
    if not match:
        raise ValueError(f"Could not find RJ work ID in {value!r}")
    return match.group(1).upper()


def dlsite_url(work_id: str, *, site: str) -> str:
    return f"https://www.dlsite.com/{site}/work/=/product_id/{work_id}.html"


def fetch_text(url: str, *, timeout: int) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; asmr-subtitle-translator/1.0)",
            "Accept-Language": "ja-JP,ja;q=0.9,zh-CN;q=0.8,en;q=0.7",
            "Cookie": "adultchecked=1; locale=ja_JP",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def safe_json_loads(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def flatten_json_ld(values: list[Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(flatten_json_ld(value))
        elif isinstance(value, dict):
            graph = value.get("@graph")
            if isinstance(graph, list):
                flattened.extend(flatten_json_ld(graph))
            flattened.append(value)
    return flattened


def clean_text(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text


def listify(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(listify(item))
        return result
    if isinstance(value, dict):
        for key in ["name", "alternateName", "label"]:
            if value.get(key):
                return [clean_text(value[key])]
        return []
    text = clean_text(value)
    return [text] if text else []


def first_json_value(objects: list[dict[str, Any]], keys: list[str]) -> str:
    for obj in objects:
        for key in keys:
            if key in obj:
                values = listify(obj[key])
                if values:
                    return values[0]
    return ""


def parse_keywords(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,、/|]", value)
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        item = clean_text(part)
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def parse_page(html_text: str, *, work_id: str, source_url: str) -> dict[str, Any]:
    parser = PageMetadataParser()
    parser.feed(html_text)
    json_values = [value for text in parser.json_ld_texts if (value := safe_json_loads(text.strip())) is not None]
    json_objects = flatten_json_ld(json_values)

    title = (
        first_json_value(json_objects, ["name", "headline"])
        or parser.meta.get("og:title", "")
        or clean_text(" ".join(parser.title_parts))
    )
    description = (
        first_json_value(json_objects, ["description"])
        or parser.meta.get("description", "")
        or parser.meta.get("og:description", "")
    )
    image = first_json_value(json_objects, ["image", "thumbnailUrl"]) or parser.meta.get("og:image", "")
    circle = first_json_value(json_objects, ["brand", "publisher", "author", "creator"])
    date_published = first_json_value(json_objects, ["datePublished", "dateCreated"])

    keywords = parse_keywords(parser.meta.get("keywords", ""))
    json_keywords: list[str] = []
    for obj in json_objects:
        json_keywords.extend(listify(obj.get("keywords")))
        json_keywords.extend(listify(obj.get("genre")))
    for item in json_keywords:
        for keyword in parse_keywords(item):
            if keyword not in keywords:
                keywords.append(keyword)

    return {
        "fetched_at": now_utc(),
        "work_id": work_id,
        "source_url": source_url,
        "title": title,
        "circle": circle,
        "description": description,
        "image": image,
        "date_published": date_published,
        "keywords": keywords,
        "meta": parser.meta,
        "json_ld": json_objects,
        "notes": [],
    }


def build_error_payload(work_id: str, source_url: str, error: str) -> dict[str, Any]:
    return {
        "fetched_at": now_utc(),
        "work_id": work_id,
        "source_url": source_url,
        "error": error,
        "notes": ["DLsite metadata fetch failed; do not block ASMR subtitle workflow."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch or parse DLsite work metadata for an RJ work ID.")
    parser.add_argument("work", help="RJ work ID, project path, or text containing an RJ ID.")
    parser.add_argument("--site", default="maniax", help="DLsite section, default: maniax.")
    parser.add_argument("--out", help="Write JSON metadata to this path. Defaults to stdout.")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--html", help="Parse a local HTML file instead of fetching the DLsite page.")
    parser.add_argument("--allow-fail", action="store_true", help="Write an error JSON and return 0 if fetching fails.")
    args = parser.parse_args()

    try:
        work_id = extract_work_id(args.work)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    source_url = dlsite_url(work_id, site=args.site)
    try:
        html_text = Path(args.html).read_text(encoding="utf-8") if args.html else fetch_text(source_url, timeout=args.timeout)
        payload = parse_page(html_text, work_id=work_id, source_url=source_url)
        exit_code = 0
    except (OSError, HTTPError, URLError, TimeoutError, ValueError) as exc:
        payload = build_error_payload(work_id, source_url, str(exc))
        exit_code = 0 if args.allow_fail else 1

    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")

    if payload.get("error"):
        print(f"DLsite fetch failed: {payload['error']}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
