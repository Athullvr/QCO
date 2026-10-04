"""Compare models on the SAME N gold documents (LLM CALLS HAPPEN HERE).
  python scripts/compare_models.py --config configs/models.json --split dev --n 10 [--confirm-test]
Documents = first N of the split sorted by doc_id (deterministic). Prints cost, JSON validity, quote-verification failures, per-field accuracy."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import settings  # noqa: E402
from qco_watch.eval.compare import cost_usd, summarize  # noqa: E402
from qco_watch.eval.extraction import score  # noqa: E402
from qco_watch.eval.gates import gate_split, require_valid_gold  # noqa: E402
from qco_watch.eval.retrieval import load_jsonl  # noqa: E402
from qco_watch.eval.runner import gold_items, run_extraction  # noqa: E402
from qco_watch.extract.llm import build_llm  # noqa: E402
from qco_watch.gold import RawIndex  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--config", type=Path, default=Path("configs/models.json"))
ap.add_argument("--split", choices=["dev", "test"], default="dev")
ap.add_argument("--n", type=int, default=10)
ap.add_argument("--confirm-test", action="store_true")
ap.add_argument("--allow-gold-errors", action="store_true")
a = ap.parse_args()

gate_split(a.split, a.confirm_test)
gold = settings.data_dir / "gold"
require_valid_gold(gold, a.allow_gold_errors)
cfg = json.loads(a.config.read_text())["models"]
labels = load_jsonl(gold / "labels.jsonl")
items, bad = gold_items(labels, RawIndex(settings.raw_dir, settings.text_dir), a.split)
items = sorted(items)[:a.n]
if bad: print(f"WARNING: {len(bad)} gold docs have no parsed text: {bad}")
ids = {k for k, _ in items}
gold_rows = [l for l in labels if l["doc_id"] in ids]
print(f"{len(items)} documents x {len(cfg)} models, split={a.split}")

rows = []
for m in cfg:
    key = os.environ.get(m["api_key_env"], "")
    if not key: print(f"SKIP {m['name']}: environment variable {m['api_key_env']} is not set"); continue
    llm = build_llm(settings, f"compare_{m['name']}", provider=m["provider"], api_key=key, model=m["model"], base_url=m.get("base_url"),
                    json_mode=m.get("json_mode", "json_schema"))
    recs = run_extraction(items, llm, settings.data_dir / "extractions" / f"compare_{a.split}_{m['name']}", log=lambda *_: None)
    sc = score(gold_rows, {r["doc_id"]: r for r in recs})
    rows.append(summarize(m, llm.usage, sc, cost_usd(llm.usage, m)))

settings.report_dir.mkdir(parents=True, exist_ok=True)
(settings.report_dir / f"model_comparison_{a.split}.json").write_text(json.dumps(rows, indent=1, default=str))
for r in rows:
    print(f"\n== {r['name']} ({r['model']})")
    print(f"  cost: {r['cost_usd'] if r['cost_usd'] is not None else 'n/a (price not in config)'} USD | tokens in/out: {r['input_tokens']}/{r['output_tokens']} | cached calls: {r['cached_calls']}")
    print(f"  JSON/schema validity: {r['json_validity_rate']} {r['run_status']} | quote verification failures: {r['quote_failures']} (verified share {r['quote_share_verified']})")
    print("  accuracy: " + "  ".join(f"{k}={v}" for k, v in r["field_accuracy"].items()))
    print("  list F1:  " + "  ".join(f"{k}={v}" for k, v in r["list_f1"].items()))
