"""Corpus-level parse quality over <data>/text/*.json (regex heuristics only; no extraction/guessing)."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import settings  # noqa: E402

rows = []
for f in sorted(settings.text_dir.glob("*.json")):
    d = json.loads(f.read_text()); t = "\n".join(p["text"] for p in d["pages"])
    en = len(re.findall(r"[A-Za-z]", t)); dev = len(re.findall(r"[\u0900-\u097F]", t))
    rows.append({"file": f.name, "pages": d["page_count"], "status": d["status"], "chars": len(t),
                 "english_letters": en, "devanagari": dev,
                 "has_english_body": en > 400,
                 "mentions_hs_or_itc": bool(re.search(r"(?i)\b(HS|ITC[- ]?HS|H\.S\.|tariff)\b.{0,40}(code|heading|chapter)|\bHSN\b", t)),
                 "has_8digit_codes": len(re.findall(r"\b\d{4}[ .]?\d{2}[ .]?\d{2}\b", t)),
                 "has_so_number": bool(re.search(r"(?i)\bS\.?\s?O\.?\s*\d+\s*\((E|अ)\)|का\.?\s?आ\.?", t)),
                 "mentions_IS_standard": bool(re.search(r"\bIS\s*\d+", t))})
n = len(rows)
agg = lambda k: sum(1 for r in rows if r[k])
out = {"docs": n, "pages": sum(r["pages"] for r in rows), "status": {s: sum(1 for r in rows if r["status"] == s) for s in {r["status"] for r in rows}},
       "english_body": agg("has_english_body"), "mention_hs_words": agg("mentions_hs_or_itc"),
       "docs_with_8digit_like_numbers": sum(1 for r in rows if r["has_8digit_codes"]),
       "so_number_found": agg("has_so_number"), "mentions_IS_standard": agg("mentions_IS_standard"),
       "median_chars": sorted(r["chars"] for r in rows)[n // 2] if n else 0}
print(json.dumps(out, indent=1))
(settings.report_dir / "parse_quality.json").write_text(json.dumps({"summary": out, "docs": rows}, indent=1))
for r in rows:
    if r["status"] != "ok" or not r["has_english_body"] or not r["so_number" if False else "has_so_number"]: print("CHECK", r["file"], r["status"], r["pages"], r["chars"], r["english_letters"], r["has_so_number"])
