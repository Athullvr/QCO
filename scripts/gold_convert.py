"""Convert hand-labelled gold CSVs -> JSONL with strict validation. No LLM, never edits a label value.
Usage: python scripts/gold_convert.py [--gold-dir DIR] [--data-dir DIR]
Default dirs come from DATA_DIR (./data) because /data is not writable in a dev shell: <data>/gold, <data>/raw, <data>/text, <data>/hs.
Missing input CSV -> an empty header-only template is created and the run stops (exit 2). Hard errors -> exit 1."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import settings  # noqa: E402
from qco_watch.gold import HS_COLS, LABEL_COLS, Problem, RawIndex, Result, convert_labels, convert_product_hs, read_csv, report_md, write_jsonl  # noqa: E402
from qco_watch.hsmap import source  # noqa: E402


def run(gold: Path, data: Path) -> int:
    gold.mkdir(parents=True, exist_ok=True)
    lab, hs = gold / "labels.csv", gold / "product_hs.csv"
    missing = [(p, c) for p, c in ((lab, LABEL_COLS), (hs, HS_COLS)) if not p.exists()]
    if missing:
        for p, cols in missing: p.write_text(",".join(cols) + "\n", encoding="utf-8"); print(f"created empty template: {p}")
        print("Input CSV(s) were missing - templates created. Fill them in and re-run. Stopping.")
        return 2
    res = Result()
    rows = read_csv(lab, LABEL_COLS, res)
    if rows is not None: convert_labels(rows, RawIndex(data / "raw", data / "text"), res)
    hrows = read_csv(hs, HS_COLS, res)
    if hrows is not None:
        hsf, codes = data / "hs" / "comtrade_H6.json", None
        if hrows and not hsf.exists():
            res.problems.append(Problem("error", "product_hs.csv", None, None, None, f"HS2022 list not found at {hsf} (run scripts/hs_map_spike.py once to download it)"))
        elif hrows: codes = {e.code for e in source.load(hsf)}
        docs = {o["doc_id"]: o["split"] for o in res.labels if o["doc_id"]} if rows is not None else None
        convert_product_hs(hrows, codes, docs, res)
    write_jsonl(gold / "labels.jsonl", res.labels)
    write_jsonl(gold / "product_hs.jsonl", res.product_hs)
    (gold / "validation_report.md").write_text(report_md(res), encoding="utf-8")
    (gold / "validation_summary.json").write_text(json.dumps({"errors": len(res.errors), "warnings": len(res.warnings)}))
    print(f"labels: {len(res.labels)} rows | product_hs: {len(res.product_hs)} rows | errors: {len(res.errors)} | warnings: {len(res.warnings)}")
    print(f"report: {gold / 'validation_report.md'}")
    return 1 if res.errors else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=settings.data_dir)
    ap.add_argument("--gold-dir", type=Path)
    a = ap.parse_args()
    sys.exit(run(a.gold_dir or a.data_dir / "gold", a.data_dir))
