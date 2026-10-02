import pymupdf as fitz

from qco_watch.parser import parse_pdf


def make_pdf(texts):
    d = fitz.open()
    for t in texts:
        p = d.new_page()
        if t: p.insert_text((72, 72), t)
    return d.tobytes()


def test_pages_numbered_and_text_extracted():
    r = parse_pdf(make_pdf(["Quality Control Order 2026 page one with enough text to count", "Second page has more than forty characters of text ok"]), ocr=False)
    assert r.page_count == 2 and [p.page for p in r.pages] == [1, 2] and r.status == "ok"
    assert "Quality Control Order" in r.pages[0].text and "===== PAGE 2 =====" in r.as_text()


def test_blank_page_flagged_needs_ocr_when_ocr_unavailable():
    r = parse_pdf(make_pdf(["Enough text on this page to pass the minimum threshold, yes.", ""]), ocr=False)
    assert r.status == "needs_ocr" and r.pages[1].method == "none" and r.warnings


def test_garbage_input_is_error_not_crash():
    assert parse_pdf(b"not a pdf").status == "error"
