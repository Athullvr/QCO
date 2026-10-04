"""Phase 2: which sources can supply amendment / extension / relaxation / rescission notices? Plain HTTP only (no Anakin credits),
robots.txt + rate limit respected, TLS verification never disabled. Output: data/reports/amendment_sources.json

For each ministry/portal home page we DISCOVER links whose text/URL mention quality control / QCO / notification and test those,
instead of guessing paths."""
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import settings  # noqa: E402
from qco_watch.fetcher.polite import Politeness  # noqa: E402

pol = Politeness(settings.user_agent, settings.min_request_interval_s)
KW = re.compile(r"quality[\s-]*control|\bqco\b|notification|gazette|order", re.I)
CHANGE = {"amendment": r"amend", "extension": r"extend|extension|postpone|deferr|further time", "relaxation": r"relax|exempt", "rescission": r"rescind|rescission|revok|withdraw"}


def get(url, **kw):
    if not pol.allowed(url): return {"url": url, "outcome": "robots_disallowed"}, None
    pol.wait(url)
    try:
        r = requests.get(url, headers={"User-Agent": settings.user_agent}, timeout=40, **kw)
    except requests.RequestException as e:
        return {"url": url, "outcome": "error", "error": f"{type(e).__name__}: {str(e)[:140]}"}, None
    return {"url": url, "outcome": "ok" if r.ok else f"http_{r.status_code}", "status": r.status_code, "bytes": len(r.content)}, r


def analyse_page(url, limit_links=40):
    row, r = get(url)
    if not r or not r.ok: return row
    soup = BeautifulSoup(r.text, "lxml")
    text = soup.get_text(" ", strip=True)
    links = [(a.get_text(" ", strip=True), urljoin(url, a["href"])) for a in soup.find_all("a", href=True)]
    pdfs = [(t, h) for t, h in links if h.lower().split("?")[0].endswith(".pdf")]
    row.update(visible_text_chars=len(text), js_shell_suspected=len(text) < 800, pdf_links=len(pdfs),
               change_keyword_pdf_titles={k: sum(1 for t, h in pdfs if re.search(p, t + " " + h, re.I)) for k, p in CHANGE.items()},
               relevant_links=[(t[:80], h) for t, h in links if KW.search(t) and not h.lower().endswith(".pdf")][:limit_links])
    return row


report = {"bis_media_api": {}, "portals": []}

# 1. BIS: how many amendment/extension/relaxation/rescission QCO PDFs does the WP media API expose?
for label, q in [("amendment", "quality control amendment"), ("extension", "quality control extension"), ("relaxation", "quality control relaxation"),
                 ("rescission", "quality control rescind")]:
    row, r = get(f"https://www.bis.gov.in/wp-json/wp/v2/media?search={quote(q)}&per_page=100&_fields=source_url,title,date")
    if r and r.ok:
        items = [m for m in r.json() if str(m.get("source_url", "")).lower().endswith(".pdf")]
        row.update(pdf_hits=len(items), newest=max((m["date"][:10] for m in items), default=None),
                   matching_title_or_url=sum(1 for m in items if re.search(CHANGE[label], m["source_url"] + json.dumps(m.get("title")), re.I)))
    report["bis_media_api"][label] = row
    print(label, {k: v for k, v in row.items() if k != "url"})

# 2. Portals: home page + discovered relevant sub-pages
PORTALS = [("e-Gazette", "https://egazette.gov.in/"), ("DGFT notifications", "https://www.dgft.gov.in/CP/?opt=notification"),
           ("DGFT public notices", "https://www.dgft.gov.in/CP/?opt=public-notice"), ("DGFT trade notices", "https://www.dgft.gov.in/CP/?opt=trade-notice"),
           ("DPIIT", "https://www.dpiit.gov.in/"), ("MeitY", "https://www.meity.gov.in/"), ("Dept of Chemicals", "https://chemicals.gov.in/"),
           ("Ministry of Steel", "https://steel.gov.in/"), ("BIS upcoming QCOs", "https://www.bis.gov.in/upcoming-qcos-notified-and-due-for-implementation/")]
for name, url in PORTALS:
    row = analyse_page(url); row["name"] = name
    subs = []
    for t, h in (row.pop("relevant_links", []) if row.get("outcome") == "ok" else []):
        if re.search(r"quality[\s-]*control|\bqco\b", t + h, re.I) and len(subs) < 3 and urljoin(url, h) != url:
            s = analyse_page(h, limit_links=0); s["link_text"] = t; s.pop("relevant_links", None); subs.append(s)
    row["qco_subpages_tested"] = subs
    report["portals"].append(row)
    print(name, row.get("outcome"), row.get("error", ""), "pdfs:", row.get("pdf_links"), "subpages:", [(s["outcome"], s.get("pdf_links")) for s in subs])

# 3. e-Gazette search: is the search form reachable without a captcha-solving step?
eg = next(p for p in report["portals"] if p["name"] == "e-Gazette")
if eg.get("outcome") != "ok":
    try:
        requests.get("https://egazette.gov.in/", timeout=20)
    except requests.exceptions.SSLError as e:
        eg["ssl_detail"] = str(e)[:300]
    except requests.RequestException:
        pass

settings.report_dir.mkdir(parents=True, exist_ok=True)
(settings.report_dir / "amendment_sources.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str))
