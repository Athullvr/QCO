"""Run the extractor (LLM CALLS HAPPEN HERE). English pages only.
  python scripts/extract_run.py --split dev|test [--confirm-test] [--run NAME] [--limit N]   # gold documents of that split
  python scripts/extract_run.py [--limit N]                                                    # every parsed document in data/text (no gold)
Needs LLM_PROVIDER / LLM_API_KEY / LLM_MODEL (+ LLM_BASE_URL for OpenAI-compatible endpoints such as Gemini).
Output: data/extractions/<run>/<doc>.json ; responses are cached in data/llm_cache/, so re-runs are free."""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import settings  # noqa: E402
from qco_watch.eval.gates import gate_split, require_valid_gold  # noqa: E402
from qco_watch.eval.retrieval import load_jsonl  # noqa: E402
from qco_watch.eval.runner import gold_items, run_extraction  # noqa: E402
from qco_watch.extract.llm import build_llm  # noqa: E402
from qco_watch.gold import RawIndex  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--split", choices=["dev", "test"])
ap.add_argument("--confirm-test", action="store_true")
ap.add_argument("--run")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--allow-gold-errors", action="store_true")
a = ap.parse_args()

if a.split:
    gate_split(a.split, a.confirm_test)
    gold = settings.data_dir / "gold"
    require_valid_gold(gold, a.allow_gold_errors)
    items, bad = gold_items(load_jsonl(gold / "labels.jsonl"), RawIndex(settings.raw_dir, settings.text_dir), a.split)
    if bad: print(f"WARNING: {len(bad)} gold docs have no parsed text and are skipped: {bad}")
else:
    items = [(f.stem, f) for f in sorted(settings.text_dir.glob("*.json"))]
if a.limit: items = items[:a.limit]

llm = build_llm(settings, "extract")
run = a.run or re.sub(r"[^A-Za-z0-9._-]+", "_", llm.model) + (f"_{a.split}" if a.split else "_corpus")
recs = run_extraction(items, llm, settings.data_dir / "extractions" / run)
summary = {"run": run, "model": llm.model, "docs": len(recs), "status": dict(Counter(r["status"] for r in recs)),
           "needs_review": sum(r["needs_review"] for r in recs), "tokens": llm.usage}
settings.report_dir.mkdir(parents=True, exist_ok=True)
(settings.report_dir / f"extraction_run_{run}.json").write_text(json.dumps(summary, indent=1))
print(summary)
