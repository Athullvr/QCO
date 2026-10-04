"""Eval harness. Usage:
  python scripts/eval_run.py --task retrieval  --split dev|test [--confirm-test]
  python scripts/eval_run.py --task extraction --split dev|test --run RUN [--confirm-test]   (scores stored extraction records; NO LLM calls here)
The test split refuses to run without --confirm-test. Refuses if the last gold validation had errors (--allow-gold-errors to override)."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import settings  # noqa: E402
from qco_watch.eval.gates import gate_split, require_valid_gold  # noqa: E402
from qco_watch.eval.retrieval import evaluate, load_jsonl, select_rows  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--split", choices=["dev", "test"], required=True)
ap.add_argument("--confirm-test", action="store_true")
ap.add_argument("--task", choices=["retrieval", "extraction"], default="retrieval")
ap.add_argument("--run", help="extraction run name = folder under data/extractions/ (extraction task)")
ap.add_argument("--allow-gold-errors", action="store_true")
ap.add_argument("--gold-dir", type=Path, default=settings.data_dir / "gold")
a = ap.parse_args()

gate_split(a.split, a.confirm_test)
require_valid_gold(a.gold_dir, a.allow_gold_errors)
settings.report_dir.mkdir(parents=True, exist_ok=True)
labels = load_jsonl(a.gold_dir / "labels.jsonl")

if a.task == "extraction":
    from qco_watch.eval.extraction import format_report, score  # noqa: E402
    from qco_watch.eval.runner import load_records  # noqa: E402
    if not a.run: sys.exit("--run is required for the extraction task (a folder under data/extractions/)")
    d = settings.data_dir / "extractions" / a.run
    if not d.exists(): sys.exit(f"{d} not found - run scripts/extract_run.py --split {a.split} --run {a.run} first")
    out = score([l for l in labels if l["split"] == a.split], load_records(d))
    out.update(split=a.split, run=a.run)
    (settings.report_dir / f"eval_extraction_{a.run}_{a.split}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    print(format_report(out))
    sys.exit(0)

from qco_watch.hsmap import source  # noqa: E402
from qco_watch.hsmap.index import HsIndex, LocalEmbedder  # noqa: E402

rows, unassigned = select_rows(load_jsonl(a.gold_dir / "product_hs.jsonl"), labels, a.split)
index = HsIndex(source.load(settings.data_dir / "hs" / "comtrade_H6.json"), LocalEmbedder(), settings.data_dir / "hs")
out = evaluate(rows, lambda t, k: [e.code for e, _ in index.search(t, k)])
out.update(split=a.split, embedder=index.embedder.name, rows_unassigned_excluded=len(unassigned))
(settings.report_dir / f"eval_retrieval_{a.split}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))

print(f"retrieval eval [{a.split}] n={out['n']} (unassigned rows excluded: {len(unassigned)})")
for lvl in ("hs6", "hs4"): print(f"  {lvl}: " + "  ".join(f"{k}={v}" for k, v in out[lvl].items()))
print("by chapter:")
for ch, d in out["by_chapter"].items(): print(f"  {ch}: n={d['n']} " + " ".join(f"{k}={d[k]}/{d['n']}" for k in ("hit@1", "hit@5", "hit@10")))
print(f"misses (not in top 5): {len(out['misses_not_in_top5'])}")
for m in out["misses_not_in_top5"]:
    print(f"  - {m['product_text']!r} want {m['correct_hs6']}{('/' + ','.join(m['alt_hs6'])) if m['alt_hs6'] else ''} (rank<=10: {m['found_at_rank_within_10']}) got {m['top5']}")
