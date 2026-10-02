"""PDF -> per-page text with provenance. Digital text first (PyMuPDF); OCR (Hindi+English) for pages with no/poor text.

Known issue (verified on BIS gazette PDFs): the Hindi text layer is extracted with wrong conjuncts/matras
(e.g. 'जून' -> 'िून'). English text is reliable. We flag `devanagari_ratio` and prefer OCR for Hindi when available.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import asdict, dataclass, field

import fitz  # PyMuPDF

MIN_CHARS_PER_PAGE = 40
DEVANAGARI = re.compile(r"[\u0900-\u097F]")


@dataclass
class Page:
    page: int  # 1-based, as printed in citations
    text: str
    method: str  # text | ocr | none
    chars: int = 0
    ocr_confidence: float | None = None


@dataclass
class ParsedDoc:
    pages: list[Page]
    page_count: int
    status: str  # ok | partial_ocr_unavailable | needs_ocr | ocr_done | empty | error
    warnings: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict: return asdict(self)

    def as_text(self) -> str:
        return "\n".join(f"\n===== PAGE {p.page} =====\n{p.text}" for p in self.pages)


def ocr_available(langs: str = "eng+hin") -> tuple[bool, str]:
    if not shutil.which("tesseract"): return False, "tesseract binary not installed"
    try:
        import pytesseract
        have = set(pytesseract.get_languages())
    except Exception as e:  # noqa: BLE001
        return False, f"pytesseract error: {e}"
    missing = [l for l in langs.split("+") if l not in have]
    return (not missing), (f"missing tesseract langs: {missing}" if missing else "ok")


def _ocr_page(page: "fitz.Page", langs: str) -> tuple[str, float | None]:
    import pytesseract
    from PIL import Image
    pix = page.get_pixmap(dpi=300)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    d = pytesseract.image_to_data(img, lang=langs, output_type=pytesseract.Output.DICT)
    confs = [float(c) for c, t in zip(d["conf"], d["text"]) if t.strip() and float(c) >= 0]
    return pytesseract.image_to_string(img, lang=langs), (sum(confs) / len(confs) if confs else None)


def parse_pdf(data: bytes, *, ocr: bool = True, langs: str = "eng+hin") -> ParsedDoc:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        return ParsedDoc([], 0, "error", [f"cannot open PDF: {e}"])
    pages, warns = [], []
    can_ocr, why = ocr_available(langs) if ocr else (False, "ocr disabled")
    low = 0
    for i, pg in enumerate(doc, start=1):
        t = pg.get_text("text").strip()
        if len(t) >= MIN_CHARS_PER_PAGE:
            pages.append(Page(i, t, "text", len(t)))
            continue
        low += 1
        if can_ocr:
            t2, conf = _ocr_page(pg, langs)
            pages.append(Page(i, t2.strip(), "ocr", len(t2.strip()), conf))
        else:
            pages.append(Page(i, t, "none", len(t)))
    n = len(pages)
    total = sum(p.chars for p in pages)
    dev = sum(len(DEVANAGARI.findall(p.text)) for p in pages)
    letters = sum(len(re.findall(r"[A-Za-z\u0900-\u097F]", p.text)) for p in pages) or 1
    if n == 0: status = "empty"
    elif low == 0: status = "ok"
    elif can_ocr: status = "ocr_done"
    else:
        status = "needs_ocr"
        warns.append(f"{low}/{n} pages have no usable text layer and OCR is unavailable ({why})")
    if dev / letters > 0.2:
        warns.append("Devanagari text layer present: extraction of Hindi is unreliable (wrong matras/conjuncts); rely on English text or OCR")
    return ParsedDoc(pages, n, status, warns, {"chars": total, "low_text_pages": low, "devanagari_ratio": round(dev / letters, 3),
                                              "ocr_available": can_ocr, "ocr_note": why})
