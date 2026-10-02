"""BIS (bis.gov.in) discovery via the public WordPress REST media endpoint (verified reachable with plain HTTP,
not disallowed by robots.txt: only /wp-admin/ is). Each hit is a QCO / amendment / rescission PDF upload."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

from qco_watch.fetcher.chain import FetcherChain

BASE = "https://www.bis.gov.in"
MEDIA = BASE + "/wp-json/wp/v2/media?search={q}&per_page=100&page={page}&orderby=date&order=desc&_fields=source_url,title,date,mime_type"
RELEVANT = re.compile(r"quality[-_ ]control|\bqco\b|\bqc[-_ ]order", re.I)


@dataclass
class Candidate:
    url: str
    title: str
    published_at: date
    source: str = "bis"


def discover(chain: FetcherChain, limit: int = 50, query: str = "quality control", max_pages: int = 3) -> list[Candidate]:
    out: dict[str, Candidate] = {}
    for page in range(1, max_pages + 1):
        url = MEDIA.format(q=query.replace(" ", "%20"), page=page)
        try:
            r = chain.fetch(url, kind="listing", expect=r"^\s*\[")
        except Exception:
            break
        for m in json.loads(r.content):
            su = m.get("source_url")
            if not isinstance(su, str) or not su.lower().endswith(".pdf"): continue
            title = re.sub(r"<[^>]+>", "", (m.get("title") or {}).get("rendered", "") if isinstance(m.get("title"), dict) else "")
            if RELEVANT.search(su) or RELEVANT.search(title):
                out.setdefault(su, Candidate(su, title or su.rsplit("/", 1)[-1], date.fromisoformat(m["date"][:10])))
        if len(out) >= limit: break
    return sorted(out.values(), key=lambda c: c.published_at, reverse=True)[:limit]
