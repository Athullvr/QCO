"""English-only view of a parsed gazette. Any line containing Devanagari is dropped (the Hindi text layer is mis-decoded
and must never reach the extractor). Page numbers are preserved so citations stay valid."""
from __future__ import annotations

import json
import re
from pathlib import Path

DEVANAGARI = re.compile(r"[\u0900-\u097F]")
MIN_EN_CHARS = 80


def english_pages(parsed: dict) -> list[tuple[int, str]]:
    out = []
    for p in parsed["pages"]:
        lines = [l.rstrip() for l in p["text"].splitlines() if not DEVANAGARI.search(l)]
        text = "\n".join(l for l in lines if l.strip())
        if len(text) >= MIN_EN_CHARS: out.append((p["page"], text))
    return out


def load_english(json_path: str | Path) -> list[tuple[int, str]]:
    return english_pages(json.loads(Path(json_path).read_text()))


def norm(s: str) -> str:
    """Whitespace/quote-normalised form used to verify that a quote really occurs in the page."""
    s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'").replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", s).strip().lower()
