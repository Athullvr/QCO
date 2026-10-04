import csv
import json
import subprocess
import sys
from pathlib import Path

from qco_watch.eval.retrieval import evaluate, select_rows
from qco_watch.gold import HS_COLS, LABEL_COLS

ROOT = Path(__file__).resolve().parents[1]
PAGE = "Footwear Order.\n  New Delhi, the 12th June,   2026\nIS 15844"


def setup(tmp_path, labels=(), hs=()):
    raw = tmp_path / "raw" / "h"; raw.mkdir(parents=True)
    (raw / "abc123abc123_Order.pdf").write_bytes(b"%PDF")
    (raw / "abc123abc123_Order.pdf.meta.json").write_text(json.dumps({"sha256": "f" * 64}))
    (tmp_path / "text").mkdir()
    (tmp_path / "text" / ("1_" + "f" * 10 + ".json")).write_text(json.dumps({"pages": [{"page": 1, "text": "x"}, {"page": 2, "text": PAGE}]}))
    (tmp_path / "hs").mkdir()
    (tmp_path / "hs" / "comtrade_H6.json").write_text(json.dumps({"results": [
        {"id": "6403", "text": "6403 - Footwear", "parent": "64"}, {"id": "640399", "text": "640399 - Footwear n.e.c.", "parent": "6403"}, {"id": "64", "text": "64 - Ch", "parent": "#"}]}))
    g = tmp_path / "gold"; g.mkdir()
    for name, cols, rows in (("labels.csv", LABEL_COLS, labels), ("product_hs.csv", HS_COLS, hs)):
        with open(g / name, "w", newline="") as f:
            w = csv.DictWriter(f, cols); w.writeheader()
            for r in rows: w.writerow({c: r.get(c, "") for c in cols})
    return g


def label(**kw):
    base = dict(doc_id="d1", file_name="Order.pdf", source_url="https://www.bis.gov.in/x.pdf", split="dev", is_qco="yes", notification_date="2026-06-12",
                products="Footwear; Boots ;", change_type="extension", source_page="2", source_quote="New Delhi, the 12th June, 2026", hs_codes_printed="6403 99")
    return {**base, **kw}


def run(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "scripts/gold_convert.py"), "--data-dir", str(tmp_path)], capture_output=True, text=True, cwd=ROOT)
    return p, (tmp_path / "gold" / "validation_report.md")


def jl(p): return [json.loads(l) for l in p.read_text().splitlines()]


def test_missing_inputs_create_templates_and_stop(tmp_path):
    p, _ = run(tmp_path)
    assert p.returncode == 2
    assert (tmp_path / "gold" / "labels.csv").read_text().strip() == ",".join(LABEL_COLS)
    assert (tmp_path / "gold" / "product_hs.csv").read_text().strip() == ",".join(HS_COLS)


def test_clean_conversion(tmp_path):
    setup(tmp_path, [label()], [dict(product_text="Footwear", source_doc_id="d1", correct_hs6="6403.99", hs4_heading="6403")])
    p, rep = run(tmp_path)
    assert p.returncode == 0, rep.read_text()
    o = jl(tmp_path / "gold" / "labels.jsonl")[0]
    assert o["is_qco"] is True and o["products"] == ["Footwear", "Boots"] and o["hs_codes"] == ["6403 99"] and "hs_codes_printed" not in o
    assert o["exemptions"] == [] and o["qco_number"] is None and o["source_page"] == 2
    h = jl(tmp_path / "gold" / "product_hs.jsonl")[0]
    assert h["correct_hs6"] == "640399" and h["alt_hs6"] == []


def test_problems_reported_without_editing_values(tmp_path):
    bad = [label(), label(), label(doc_id="d2", is_qco="", split="", notification_date="12/06/2026", change_type="Extension"),
           label(doc_id="d3", source_quote="New Delhi, the 13th June, 2026"), label(doc_id="d4", file_name="nope.pdf")]
    hs = [dict(product_text="a", source_doc_id="d1", correct_hs6="64039", hs4_heading="6403"),
          dict(product_text="b", source_doc_id="d1", correct_hs6="640399", hs4_heading="6404"),
          dict(product_text="c", source_doc_id="d1", correct_hs6="999999", hs4_heading="9999", alt_hs6="640399;12")]
    setup(tmp_path, bad, hs)
    p, rep = run(tmp_path)
    r = rep.read_text()
    assert p.returncode == 1
    for needle in ("duplicate doc_id", "blank is_qco", "split must be", "not a valid YYYY-MM-DD", "unknown change_type", "quote not found verbatim",
                   "no file in data/raw", "must be exactly 6 digits", "!= first 4 digits", "not in downloaded HS2022 list", "dev has", "no rows with change_type"):
        assert needle in r, needle
    rows = jl(tmp_path / "gold" / "labels.jsonl")
    assert rows[2]["notification_date"] is None and rows[2]["notification_date_raw"] == "12/06/2026"
    assert rows[2]["change_type"] is None and rows[2]["change_type_raw"] == "Extension"
    assert rows[3]["source_quote"] == "New Delhi, the 13th June, 2026"
    assert (tmp_path / "gold" / "labels.csv").read_text().count("13th June") == 1


def test_split_gate_and_metrics(tmp_path):
    g = setup(tmp_path)
    (g / "validation_summary.json").write_text('{"errors": 0, "warnings": 0}')
    p = subprocess.run([sys.executable, str(ROOT / "scripts/eval_run.py"), "--split", "test", "--gold-dir", str(g)], capture_output=True, text=True, cwd=ROOT)
    assert p.returncode != 0 and "--confirm-test" in p.stderr + p.stdout

    labels = [{"doc_id": "d1", "split": "dev"}, {"doc_id": "d2", "split": "test"}]
    rows = [{"product_text": "a", "source_doc_id": "d1", "correct_hs6": "640399", "alt_hs6": ["640411"]},
            {"product_text": "b", "source_doc_id": "d1", "correct_hs6": "630510", "alt_hs6": []},
            {"product_text": "c", "source_doc_id": "d2", "correct_hs6": "722000", "alt_hs6": []},
            {"product_text": "e", "source_doc_id": None, "correct_hs6": "722000", "alt_hs6": []}]
    dev, un = select_rows(rows, labels, "dev")
    assert [r["product_text"] for r in dev] == ["a", "b"] and [r["product_text"] for r in un] == ["e"]
    fake = {"a": ["640411", "x"] + ["000000"] * 8, "b": ["630590"] + ["111111"] * 9}
    out = evaluate(dev, lambda t, k: fake[t][:k])
    assert out["hs6"] == {"hit@1": 0.5, "hit@5": 0.5, "hit@10": 0.5}   # alt counts; b misses at 6 digits
    assert out["hs4"]["hit@1"] == 1.0 and out["by_chapter"]["64"]["hit@1"] == 1
    assert len(out["misses_not_in_top5"]) == 1 and out["misses_not_in_top5"][0]["top5"][0] == "630590"
