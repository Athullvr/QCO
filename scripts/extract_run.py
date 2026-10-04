"""Phase 2a: run the extractor over parsed documents in data/text/*.json (English pages only).
Usage: python scripts/extract_run.py [--limit N] [--doc 10_905b16193a]
Needs LLM_PROVIDER / LLM_API_KEY / LLM_MODEL (use the strongest model available). Output: data/extractions/<stem>.json + data/reports/extraction_summary.json
Results are cached by (model, prompt, text) in data/llm_cache/, so re-runs cost nothing."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import settings  # noqa: E402
from qco_watch.extract.english import load_english  # noqa: E402
from qco_watch.extract.extractor import PROMPT_VERSION, extract  # noqa: E402
from qco_watch.extract.llm import build_llm  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--doc")
a = ap.parse_args()

llm = build_llm(settings, "extract")
out_dir = settings.data_dir / "extractions"; out_dir.mkdir(parents=True, exist_ok=True)
files = sorted(settings.text_dir.glob("*.json"))
if a.doc: files = [f for f in files if f.stem == a.doc]
if a.limit: files = files[:a.limit]

stats, rows = Counter(), []
for f in files:
    pages = load_english(f)
    try:
        r = extract(pages, llm)
    except Exception as e:  # noqa: BLE001
        stats["llm_error"] += 1; rows.append({"doc": f.stem, "error": str(e)[:200]}); continue
    (out_dir / f.name).write_text(json.dumps({"doc": f.stem, "model": r.model, "prompt_version": PROMPT_VERSION, "needs_review": r.needs_review,
                                              "issues": r.issues, "extraction": r.extraction}, indent=1, ensure_ascii=False))
    ex = r.extraction or {}
    stats["needs_review" if r.needs_review else "clean"] += 1
    stats["is_qco"] += bool(ex.get("is_qco"))
    stats["hs_codes_printed"] += bool(ex.get("hs_codes"))
    for k in ("notification_date", "effective_date", "compliance_deadline"): stats[f"has_{k}"] += bool(ex.get(k))
    stats["has_products"] += bool(ex.get("products"))
    rows.append({"doc": f.stem, "needs_review": r.needs_review, "issues": len(r.issues)})
    print(f"{f.stem}: change={ex.get('change_type')} products={len(ex.get('products', []))} issues={len(r.issues)}")

settings.report_dir.mkdir(parents=True, exist_ok=True)
(settings.report_dir / "extraction_summary.json").write_text(json.dumps({"model": llm.model, "prompt_version": PROMPT_VERSION, "docs": len(files), "stats": dict(stats), "rows": rows}, indent=1))
print(dict(stats))
