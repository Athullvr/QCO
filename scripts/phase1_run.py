"""Download + parse up to N real QCO notifications into <data>/raw and <data>/text.
Usage: python scripts/phase1_run.py [--limit 50] [--allow-anakin]
Anakin is used only for LISTING pages and only if --allow-anakin AND the key/budget are set (it is not needed for BIS)."""
import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import DISCLAIMER, settings  # noqa: E402
from qco_watch.db.session import SessionLocal  # noqa: E402
from qco_watch.fetcher import FetchError, build_chain  # noqa: E402
from qco_watch.pipeline import log_attempts, process_result  # noqa: E402
from qco_watch.sources import bis  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=50)
ap.add_argument("--allow-anakin", action="store_true")
args = ap.parse_args()
logging.basicConfig(level=logging.INFO, format="%(message)s")

chain = build_chain(settings)
if not args.allow_anakin: chain.anakin = None
for d in (settings.raw_dir, settings.text_dir, settings.drop_dir, settings.gold_dir, settings.report_dir): d.mkdir(parents=True, exist_ok=True)

cands = bis.discover(chain, limit=args.limit)
print(f"discovered {len(cands)} BIS QCO PDFs (newest {cands[0].published_at} .. oldest {cands[-1].published_at})")
stats, parse_rows, failures = Counter(), [], []
with SessionLocal() as db:
    for c in cands:
        start = len(chain.attempts)
        try:
            r = chain.fetch(c.url, kind="document")
            process_result(db, settings, r, source=c.source, title=c.title, published_at=c.published_at, stats=stats, parse_rows=parse_rows)
            stats[f"fetcher_{r.fetcher}" + ("_cache" if r.from_cache else "")] += 1
            stats["credits"] += r.credits_used
        except FetchError as e:
            failures.append({"url": c.url, "error": str(e)}); stats["fetch_failed"] += 1
        log_attempts(db, chain, start)
        db.commit()
    # manual drop folder
    drop = chain.drop
    for r in (drop.scan() if drop else []):
        process_result(db, settings, r, source="drop", title=r.url.removeprefix("drop://"), published_at=None, stats=stats, parse_rows=parse_rows)
        stats["fetcher_drop"] += 1
    db.commit()

n = len(parse_rows)
pages = sum(p["pages"] for p in parse_rows)
summary = {
    "disclaimer": DISCLAIMER,
    "stats": dict(stats),
    "raw_files": sum(1 for p in settings.raw_dir.rglob("*") if p.is_file() and not p.name.endswith(".meta.json")),
    "text_json_files": len(list(settings.text_dir.glob("*.json"))),
    "parsed_docs_this_run": n, "pages_this_run": pages,
    "avg_chars_per_page": round(sum(p["chars"] for p in parse_rows) / max(1, pages)),
    "docs_with_devanagari_gt_20pct": sum(1 for p in parse_rows if p["devanagari_ratio"] > 0.2),
    "docs_needing_ocr": [p["url"] for p in parse_rows if p["status"] == "needs_ocr"],
    "failures": failures,
    "anakin_credits_spent_total": __import__("qco_watch.fetcher", fromlist=["CreditLedger"]).CreditLedger(settings.anakin_ledger).spent(),
}
(settings.report_dir / "phase1_summary.json").write_text(json.dumps({**summary, "parse": parse_rows}, indent=1, ensure_ascii=False))
print(json.dumps(summary, indent=1, ensure_ascii=False))
