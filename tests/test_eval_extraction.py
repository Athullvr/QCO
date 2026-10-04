import json
import subprocess
import sys
from pathlib import Path

import pytest

from qco_watch.eval.compare import cost_usd
from qco_watch.eval.extraction import flatten, score
from qco_watch.eval.runner import load_records, run_extraction
from qco_watch.extract.llm import HttpLLM, LLMError, inline_refs
from qco_watch.extract.schema import Extraction

ROOT = Path(__file__).resolve().parents[1]
TXT = ("MINISTRY OF COMMERCE AND INDUSTRY\nORDER\nNew Delhi, the 12th June, 2026\nS.O. 3038(E).— In exercise of the powers conferred by section 16 of the Act, "
       "makes the following Order further to amend the Footwear (Quality Control) Order, 2024.\nFootwear: IS 15844 : 2010.\n" + "filler text " * 10)


def good(**kw):
    d = {"is_qco": True, "is_qco_quote": {"page": 1, "quote": "makes the following Order"},
         "qco_number": {"page": 1, "quote": "S.O. 3038(E)", "value": "S.O. 3038(E)"},
         "ministry": {"page": 1, "quote": "MINISTRY OF COMMERCE AND INDUSTRY", "value": "Ministry of Commerce and Industry"},
         "order_title": {"page": 1, "quote": "Footwear (Quality Control) Order, 2024", "value": "Footwear (Quality Control) Order, 2024"},
         "change_type": "amendment", "change_type_quote": {"page": 1, "quote": "further to amend the Footwear"},
         "notification_date": {"page": 1, "quote": "New Delhi, the 12th June, 2026", "value": "2026-06-12"},
         "products": [{"page": 1, "quote": "Footwear: IS 15844 : 2010", "name": "Footwear", "is_standards": ["IS 15844 : 2010"]}], "hs_codes": []}
    d.update(kw); return d


class Fake:
    model = "fake"
    def __init__(self, out=None, exc=None): self.out, self.exc, self.usage = out, exc, {"calls": 0, "cached_calls": 0, "input_tokens": 0, "output_tokens": 0}
    def json_call(self, *a, **k):
        if self.exc: raise self.exc
        self.usage["input_tokens"] += 100; self.usage["output_tokens"] += 10
        return self.out


def make_text(tmp_path):
    p = tmp_path / "t.json"; p.write_text(json.dumps({"pages": [{"page": 1, "text": TXT}]})); return p


def test_flatten_maps_to_label_names():
    rec = {"extraction": Extraction.model_validate(good()).model_dump(mode="json")}
    f = flatten(rec)
    assert f["title"] == "Footwear (Quality Control) Order, 2024" and f["qco_number"] == "S.O. 3038(E)" and f["products"] == ["Footwear"]
    assert f["is_standards"] == ["IS 15844 : 2010"] and f["hs_codes"] == [] and f["notification_date"] == "2026-06-12"
    assert flatten({"extraction": None})["is_qco"] is None


def test_runner_and_scoring_end_to_end_with_fake_llm(tmp_path):
    items = [("d1", make_text(tmp_path)), ("d2", make_text(tmp_path))]
    out = tmp_path / "run"
    recs = run_extraction(items[:1], Fake(good()), out, log=lambda *_: None)
    recs += run_extraction(items[1:], Fake(exc=LLMError("invalid JSON from model: x")), out, log=lambda *_: None)
    assert recs[0]["status"] == "ok" and recs[0]["usage"] == {"input_tokens": 100, "output_tokens": 10}
    assert recs[1]["status"] == "invalid_json"
    gold = [{"doc_id": "d1", "is_qco": True, "qco_number": "S.O. 3038(E)", "title": "footwear (quality control) order, 2024", "ministry": None,
             "notification_date": "2026-06-12", "effective_date": None, "compliance_deadline": None, "change_type": "extension",
             "products": ["footwear"], "is_standards": ["IS 15844:2010"], "hs_codes": []},
            {"doc_id": "d2", "is_qco": False, "change_type": None, "products": [], "is_standards": [], "hs_codes": []},
            {"doc_id": "d3", "is_qco": True, "products": [], "is_standards": [], "hs_codes": []}]
    s = score(gold, load_records(out))
    assert s["n_scored"] == 2 and s["not_run"] == ["d3"]
    assert s["fields"]["qco_number"]["accuracy"] == 1.0 and s["fields"]["title"]["accuracy_when_gold_present"] == 1.0   # normalised text match
    assert s["fields"]["change_type"]["wrong"] == 1 and s["change_type_confusion"]["extension->amendment"] == 1
    assert s["fields"]["ministry"]["spurious"] == 1
    assert s["is_qco"]["false_positive_rate"] == 0.0 and s["is_qco"]["n_gold_false"] == 1
    assert s["lists"]["products"]["recall"] == 1.0 and s["lists"]["is_standards"]["recall"] == 1.0
    assert s["json_validity_rate"] == 0.5 and s["quotes"]["share_verified"] == 1.0
    assert s["errors"]["change_type"]["wrong"][0]["gold"] == "extension"


def test_hallucinated_quote_counts_against_verification_share(tmp_path):
    bad = good(ministry={"page": 1, "quote": "MINISTRY OF MAGIC", "value": "x"})
    recs = run_extraction([("d1", make_text(tmp_path))], Fake(bad), tmp_path / "r", log=lambda *_: None)
    s = score([{"doc_id": "d1", "is_qco": True, "products": [], "is_standards": [], "hs_codes": []}], {"d1": recs[0]})
    assert s["quotes"]["failed"] == 1 and s["quotes"]["share_verified"] < 1


def test_hs_false_positive_when_gold_empty():
    rec = {"doc_id": "d", "status": "ok", "issues": [], "extraction": {"hs_codes": [{"code": "640399", "page": 1, "quote": "q"}], "products": []}}
    s = score([{"doc_id": "d", "hs_codes": [], "products": [], "is_standards": []}], {"d": rec})
    assert s["lists"]["hs_codes"]["fp"] == 1 and s["lists"]["hs_codes"]["precision"] == 0.0


def test_inline_refs_and_openai_compatible_url(monkeypatch):
    flat = inline_refs(Extraction.model_json_schema())
    assert "$defs" not in json.dumps(flat) and "$ref" not in json.dumps(flat)
    seen = {}

    class R:
        status_code = 200
        def json(self): return {"choices": [{"message": {"content": '{"a": 1}'}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
    monkeypatch.setattr("qco_watch.extract.llm.requests.post", lambda url, **kw: seen.update(url=url, body=kw["json"]) or R())
    llm = HttpLLM("openai", "k", "m", base_url="https://generativelanguage.googleapis.com/v1beta/openai/", json_mode="json_object")
    assert llm.json_call("s", "u", {"type": "object"}) == {"a": 1}
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert seen["body"]["response_format"] == {"type": "json_object"} and llm.usage["input_tokens"] == 7
    with pytest.raises(LLMError): HttpLLM("openai", "k", "m", json_mode="nope")


def test_cost():
    u = {"input_tokens": 2_000_000, "output_tokens": 500_000}
    assert cost_usd(u, {"price_in_per_mtok": 1.0, "price_out_per_mtok": 4.0}) == 4.0
    assert cost_usd(u, {"price_in_per_mtok": None, "price_out_per_mtok": 4.0}) is None


def test_extraction_eval_is_gated_on_test(tmp_path):
    (tmp_path / "validation_summary.json").write_text('{"errors": 0}')
    p = subprocess.run([sys.executable, str(ROOT / "scripts/eval_run.py"), "--task", "extraction", "--split", "test", "--run", "x", "--gold-dir", str(tmp_path)],
                       capture_output=True, text=True, cwd=ROOT)
    assert p.returncode != 0 and "--confirm-test" in p.stderr + p.stdout
