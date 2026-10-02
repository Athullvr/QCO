"""Http -> Anakin (listing pages only) -> Drop folder."""
from __future__ import annotations

import logging

from .base import BudgetExceeded, FetchError, FetchResult, Fetcher

log = logging.getLogger(__name__)


class FetcherChain:
    def __init__(self, http: Fetcher, anakin: Fetcher | None, drop: Fetcher | None):
        self.http, self.anakin, self.drop = http, anakin, drop
        self.attempts: list[dict] = []  # outcome log of every try, for the report and fetch_log

    def fetch(self, url: str, *, kind: str = "document", expect: str | None = None, allow_anakin: bool = True) -> FetchResult:
        steps = [self.http]
        if self.anakin and kind == "listing" and allow_anakin: steps.append(self.anakin)
        if self.drop: steps.append(self.drop)
        last: FetchError | None = None
        for f in steps:
            try:
                r = f.fetch(url, kind=kind, expect=expect)
                self.attempts.append({"url": url, "fetcher": f.name, "outcome": "cache_hit" if r.from_cache else "ok", "credits": r.credits_used})
                return r
            except FetchError as e:
                last = e
                self.attempts.append({"url": url, "fetcher": f.name, "outcome": e.outcome, "status": e.status, "detail": str(e)[:200]})
                log.warning("%s failed for %s: %s", f.name, url, e)
                if e.outcome == "robots_disallowed": raise  # never route around robots.txt via other fetchers
        raise last or FetchError("no fetcher configured")
