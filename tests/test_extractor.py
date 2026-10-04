import json
from pathlib import Path

from qco_watch.extract.english import english_pages
from qco_watch.extract.extractor import extract, validate

TXT = """THE GAZETTE OF INDIA : EXTRAORDINARY
MINISTRY OF COMMERCE AND INDUSTRY
(Department For Promotion of Industry and Internal Trade)
ORDER
New Delhi, the 12th June, 2026
S.O. 3038(E).— In exercise of the powers conferred by section 16 of the Bureau of Indian Standards Act, 2016, makes the following Order
2. (a) in the third proviso, for figures, letters and word "31st July, 2026", the figures "31st July, 2027" shall be substituted;
Footwear: IS 15844 : 2010. Reference ITC code 6403 99 for example."""


def pages(): return [(2, TXT)]


def good():
    return {"is_qco": True, "is_qco_quote": {"page": 2, "quote": "makes the following Order"},
            "ministry": {"page": 2, "quote": "MINISTRY OF COMMERCE AND INDUSTRY", "value": "Ministry of Commerce and Industry"},
            "change_type": "extension", "change_type_quote": {"page": 2, "quote": 'the figures "31st July, 2027" shall be substituted'},
            "notification_date": {"page": 2, "quote": "New Delhi, the 12th June, 2026", "value": "2026-06-12"},
            "compliance_deadline": {"page": 2, "quote": 'the figures "31st July, 2027"', "value": "2027-07-31"},
            "products": [{"page": 2, "quote": "Footwear: IS 15844 : 2010", "name": "Footwear", "is_standards": ["IS 15844 : 2010"]}],
            "hs_codes": []}


class Fake:
    model = "fake"
    def __init__(self, out): self.out = out
    def json_call(self, *a, **k): return self.out


def test_valid_extraction_has_no_issues():
    r = extract(pages(), Fake(good()))
    assert r.issues == [] and not r.needs_review
    assert r.extraction["compliance_deadline"]["value"] == "2027-07-31"


def test_hallucinated_quote_is_dropped_and_flagged():
    g = good(); g["notification_date"]["quote"] = "New Delhi, the 13th June, 2026"
    r = validate(g, pages())
    assert r.extraction["notification_date"] is None and r.needs_review


def test_date_must_match_quote():
    g = good(); g["compliance_deadline"]["value"] = "2027-08-31"
    r = validate(g, pages())
    assert r.extraction["compliance_deadline"] is None
    assert any(i["field"] == "compliance_deadline" for i in r.issues)


def test_hs_code_must_be_printed_in_document():
    g = good(); g["hs_codes"] = [{"page": 2, "quote": "Reference ITC code 6403 99", "code": "6403 99"},
                                 {"page": 2, "quote": "Footwear: IS 15844 : 2010", "code": "6404"}]
    r = validate(g, pages())
    assert [h["code"] for h in r.extraction["hs_codes"]] == ["640399"]
    assert any(i["field"] == "hs_codes" for i in r.issues)


def test_old_change_type_vocabulary_rejected():
    for old in ("amended", "extended", "relaxed", "withdrawn"):
        g = good(); g["change_type"] = old
        assert validate(g, pages()).extraction is None
    g = good(); g["change_type"] = "unclear"
    assert validate(g, pages()).extraction["change_type"] == "unclear"


def test_unknown_field_rejected():
    g = good(); g["surprise"] = 1
    assert validate(g, pages()).extraction is None


def test_english_filter_drops_devanagari_lines():
    parsed = {"pages": [{"page": 1, "text": "आदेश भारत सरकार\n" + "English line about the Order. " * 5}]}
    out = english_pages(parsed)
    assert out and "आ" not in out[0][1]


def test_precommit_hook_blocks_env(tmp_path):
    import subprocess
    hook = Path(__file__).resolve().parents[1] / ".githooks" / "pre-commit"
    def run(*names):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        for n in names:
            f = tmp_path / n; f.parent.mkdir(parents=True, exist_ok=True); f.write_text("x")
            subprocess.run(["git", "add", "-f", n], cwd=tmp_path, check=True)
        return subprocess.run(["bash", str(hook)], cwd=tmp_path, capture_output=True).returncode
    assert run(".env.example", "a.py") == 0
    assert run(".env") == 1
    assert run(".venv/lib/x.py") == 1
