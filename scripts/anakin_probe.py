"""Test Anakin on 3-5 pages and report credits per page. Spends real credits (hard-capped by ANAKIN_MAX_CREDITS).
Usage: ANAKIN_MAX_CREDITS=5 python scripts/anakin_probe.py [--dry-run]"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import settings  # noqa: E402
from qco_watch.fetcher import AnakinFetcher, CreditLedger, FetchError, Politeness, RawStore  # noqa: E402

PAGES = [  # listing/JS/blocked candidates found by probe_sources.py
    "https://egazette.gov.in/",                                  # plain requests: SSL chain verification fails
    "https://www.dgft.gov.in/CP/?opt=notification",              # notification list (DataTables/JS heavy)
    "https://www.dpiit.gov.in/",                                 # tiny HTML shell for plain requests
    "https://www.meity.gov.in/",                                 # tiny HTML shell for plain requests
]


def text_len(b: bytes) -> int:
    return len(re.sub(r"(?s)<(script|style).*?</\1>|<[^>]+>|\s+", " ", b.decode("utf-8", "ignore")).strip())


key = settings.anakin_api_key.get_secret_value()
ledger = CreditLedger(settings.anakin_ledger)
fx = AnakinFetcher(key, RawStore(settings.anakin_cache_dir), ledger, max_credits=settings.anakin_max_credits, base_url=settings.anakin_base_url)
pol = Politeness(settings.user_agent, settings.min_request_interval_s)
print(f"key set: {bool(key)} | max credits: {settings.anakin_max_credits} | already spent: {ledger.spent()}")
print(f"estimated cost for {len(PAGES)} pages: {sum(fx.estimate_cost(u) for u in PAGES)} credits (1/page, cached=0)")
if "--dry-run" in sys.argv or not fx.enabled:
    sys.exit(0 if "--dry-run" in sys.argv else "Anakin not enabled: need ANAKIN_API_KEY and ANAKIN_MAX_CREDITS>0")
rows = []
for u in PAGES:
    before = ledger.spent()
    if not pol.allowed(u):
        rows.append({"url": u, "result": "skipped: robots.txt"}); continue
    try:
        r = fx.fetch(u, kind="listing")
        rows.append({"url": u, "result": "ok", "bytes": len(r.content), "visible_text_chars": text_len(r.content),
                     "credits": round(ledger.spent() - before, 2), "from_cache": r.from_cache})
    except FetchError as e:
        rows.append({"url": u, "result": f"error: {str(e)[:150]}", "credits": round(ledger.spent() - before, 2)})
    print(rows[-1])
tot = ledger.spent()
print(json.dumps({"pages": rows, "total_spent": tot, "avg_credits_per_page": round(tot / max(1, len([r for r in rows if r['result'] == 'ok'])), 2)}, indent=1))
settings.report_dir.mkdir(parents=True, exist_ok=True)
(settings.report_dir / "anakin_probe.json").write_text(json.dumps(rows, indent=1))
