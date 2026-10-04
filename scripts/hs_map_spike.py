"""Phase 2b spike. Usage:
  python scripts/hs_map_spike.py "LED lamps" "Jute bags" [--no-llm]
  python scripts/hs_map_spike.py --from-extractions        # products from data/extractions/*.json
Downloads the HS2022 list (UN Comtrade copy of the WCO nomenclature) once into data/hs/. Output: data/reports/hs_mapping_spike.json"""
import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import settings  # noqa: E402
from qco_watch.extract.llm import build_llm  # noqa: E402
from qco_watch.hsmap import source  # noqa: E402
from qco_watch.hsmap.index import HsIndex, LocalEmbedder, OpenAIEmbedder  # noqa: E402
from qco_watch.hsmap.mapper import map_product  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("products", nargs="*")
ap.add_argument("--from-extractions", action="store_true")
ap.add_argument("--no-llm", action="store_true")
a = ap.parse_args()

f = settings.data_dir / "hs" / "comtrade_H6.json"
if not f.exists():
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(requests.get(source.URL, headers={"User-Agent": settings.user_agent}, timeout=90).content)
entries = source.load(f)
emb = (OpenAIEmbedder(settings.llm_api_key.get_secret_value(), settings.embed_model) if settings.embed_provider == "openai" else LocalEmbedder())
index = HsIndex(entries, emb, settings.data_dir / "hs")
llm = None if a.no_llm or not (settings.llm_provider and settings.llm_api_key.get_secret_value()) else build_llm(settings, "hsmap")

items = [(p, []) for p in a.products]
if a.from_extractions:
    for jf in sorted((settings.data_dir / "extractions").glob("*.json")):
        ex = (json.loads(jf.read_text()).get("extraction") or {})
        items += [(p["name"], p["is_standards"]) for p in ex.get("products", [])]
out = [map_product(p, index, llm, standards=s) for p, s in items]
print(f"{len(entries)} HS entries | embedder={emb.name} | rerank={'LLM ' + llm.model if llm else 'OFF (no LLM configured)'}")
for r in out:
    print(f"\n{r['product']}  [{r['mode']}]  -- needs_review")
    for c in r["candidates"]:
        print(f"  {c['code']}  conf={c['confidence']}  sim={c['retrieval_score']}  {c['description'][:90]}")
settings.report_dir.mkdir(parents=True, exist_ok=True)
(settings.report_dir / "hs_mapping_spike.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
