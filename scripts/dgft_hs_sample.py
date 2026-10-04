"""Sample N DGFT notification PDFs (random, seeded) and report whether they print HS / ITC-HS codes.
Usage: python scripts/dgft_hs_sample.py [--n 10] [--seed 7]   -> data/reports/dgft_hs_sample.json
Plain HTTP only, robots.txt + rate limit respected via the fetcher chain. No Anakin."""
import argparse
import json
import random
import re
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import settings  # noqa: E402
from qco_watch.fetcher import FetchError, build_chain  # noqa: E402
from qco_watch.parser import parse_pdf  # noqa: E402

LIST_URL = "https://www.dgft.gov.in/CP/?opt=notification"
PDF_RE = re.compile(r'https://content\.dgft\.gov\.in/Website/[^"\'<>]+?\.pdf', re.I)
DOTTED = re.compile(r"(?<![\d.])\d{4}\.\d{2}(?:\.\d{2})?(?![\d.])")
EIGHT = re.compile(r"(?<![\d./-])\d{8}(?![\d/-])")
KEYWORD = re.compile(r"ITC\s*[-(]?\s*HS|HS\s+code|ITC\s+code|tariff\s+item|Chapter\s+\d{1,2}\b|Schedule\s*[-]?\s*1", re.I)

_ocr = None


def rapid_ocr_text(data: bytes, max_pages: int = 6) -> tuple[str, int]:
    """Fallback OCR (rapidocr-onnxruntime, English) because the tesseract binary is not installed in this environment."""
    global _ocr
    import numpy as np
    import pymupdf
    from rapidocr_onnxruntime import RapidOCR
    _ocr = _ocr or RapidOCR()
    doc, out = pymupdf.open(stream=data, filetype="pdf"), []
    for pg in list(doc)[:max_pages]:
        pix = pg.get_pixmap(dpi=200)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
        res, _ = _ocr(img)
        out.append("\n".join(r[1] for r in (res or [])))
    return "\n".join(out), min(len(doc), max_pages)


ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=10)
ap.add_argument("--seed", type=int, default=7)
args = ap.parse_args()

chain = build_chain(settings); chain.anakin = None
listing = chain.fetch(LIST_URL, kind="listing", expect=r"(?i)\.pdf").content.decode("utf8", "replace")
urls = sorted(set(PDF_RE.findall(listing)))
print(f"{len(urls)} PDF links on DGFT notifications page")
random.Random(args.seed).shuffle(urls)

rows, tried = [], 0
for u in urls:
    if len(rows) >= args.n or tried >= args.n * 3: break
    tried += 1
    row = {"url": u, "file": unquote(u.rsplit("/", 1)[-1])}
    try:
        r = chain.fetch(u, kind="document")
    except FetchError as e:
        rows.append({**row, "status": "fetch_failed", "error": str(e)[:150]}); continue
    if r.content[:5] != b"%PDF-":
        rows.append({**row, "status": "not_pdf"}); continue
    p = parse_pdf(r.content, ocr=False)
    text = "\n".join(pg.text for pg in p.pages)
    ocr_used = False
    if len(text) < 200:
        text, _ = rapid_ocr_text(r.content); ocr_used = True
    ctx = lambda m: text[max(0, m.start() - 60): m.end() + 40].replace("\n", " ")
    dotted, eight, kw = list(DOTTED.finditer(text)), list(EIGHT.finditer(text)), list(KEYWORD.finditer(text))
    subj = re.search(r"(?is)subject\s*[:\-]?\s*(.{0,200})", text)
    rows.append({**row, "status": p.status, "pages": p.page_count, "chars": len(text), "ocr_used": ocr_used,
                 "subject": re.sub(r"\s+", " ", subj.group(1)).strip() if subj else None,
                 "dotted_codes": len(dotted), "eight_digit_numbers": len(eight), "keyword_hits": len(kw),
                 "samples": [ctx(m) for m in (dotted[:2] + eight[:2] + kw[:2])], "head": re.sub(r"\s+", " ", text[:300])})

readable = [r for r in rows if r.get("chars", 0) > 200]
with_codes = [r for r in readable if r["dotted_codes"] or r["eight_digit_numbers"]]
summary = {"sampled": len(rows), "readable_text": len(readable), "unreadable_or_failed": len(rows) - len(readable),
           "with_code_like_numbers": len(with_codes), "with_hs_keywords": sum(1 for r in readable if r["keyword_hits"])}
settings.report_dir.mkdir(parents=True, exist_ok=True)
(settings.report_dir / "dgft_hs_sample.json").write_text(json.dumps({"summary": summary, "docs": rows}, indent=1, ensure_ascii=False))
print(json.dumps(summary))
for r in rows:
    print(f"- {r['file'][:55]:55} {r['status']:10} pages={r.get('pages')} chars={r.get('chars')} dotted={r.get('dotted_codes')} 8d={r.get('eight_digit_numbers')} kw={r.get('keyword_hits')}")
