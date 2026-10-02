"""Anakin.io URL scraper. Listing pages / JS / blocked sites ONLY (it returns rendered HTML/markdown, not binaries).

Credit controls: on-disk response cache (24h+ TTL, never refetched while fresh), append-only ledger,
hard stop at ANAKIN_MAX_CREDITS checked BEFORE every request. Cost is computed from Anakin's published
pricing (URL scrape = 1 credit, +1 with browser actions, cached = 0) unless the API reports its own figure.
Docs: https://anakin.io/docs/api-reference/url-scraper/submit-scrape-job
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .base import BudgetExceeded, FetchError, FetchResult, Fetcher
from .store import RawStore, sha256_bytes

CREDITS_PER_SCRAPE = 1.0


class CreditLedger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def entries(self) -> list[dict]:
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()] if self.path.exists() else []

    def spent(self) -> float: return sum(e["credits"] for e in self.entries())

    def log(self, url: str, credits: float, *, job_id: str | None = None, cached: bool = False, note: str = ""):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "url": url, "credits": credits,
                                "job_id": job_id, "cached": cached, "note": note}) + "\n")


class AnakinFetcher(Fetcher):
    name = "anakin"

    def __init__(self, api_key: str, cache: RawStore, ledger: CreditLedger, *, max_credits: int,
                 base_url: str = "https://api.anakin.io/v1", ttl_hours: float = 24, timeout: float = 120,
                 use_browser: bool = True, poll_s: float = 3.0):
        self.key, self.cache, self.ledger, self.max_credits = api_key, cache, ledger, max_credits
        self.base, self.ttl, self.timeout, self.use_browser, self.poll_s = base_url.rstrip("/"), timedelta(hours=ttl_hours), timeout, use_browser, poll_s

    @property
    def enabled(self) -> bool: return bool(self.key) and self.max_credits > 0

    def estimate_cost(self, url: str) -> float:
        c = self.cache.get(url)
        return 0.0 if c and datetime.now(timezone.utc) - c.fetched_at < self.ttl else CREDITS_PER_SCRAPE

    def _check_budget(self, cost: float):
        spent = self.ledger.spent()
        if spent + cost > self.max_credits:
            raise BudgetExceeded(f"Anakin hard stop: spent {spent} + {cost} > ANAKIN_MAX_CREDITS={self.max_credits}")

    def fetch(self, url, *, kind="listing", expect=None) -> FetchResult:
        if kind != "listing": raise FetchError("AnakinFetcher is for listing pages only", blocked=True)
        if not self.enabled: raise FetchError("Anakin disabled (set ANAKIN_API_KEY and ANAKIN_MAX_CREDITS>0)", blocked=True)
        c = self.cache.get(url)
        if c and c.fetcher == self.name and datetime.now(timezone.utc) - c.fetched_at < self.ttl:
            c.from_cache = True; c.credits_used = 0; return c
        self._check_budget(CREDITS_PER_SCRAPE)
        h = {"X-API-Key": self.key, "Content-Type": "application/json"}
        body = {"url": url, "formats": ["html", "markdown"], "useBrowser": self.use_browser, "country": "in"}
        try:
            r = requests.post(f"{self.base}/url-scraper", json=body, headers=h, timeout=60)
            if r.status_code == 402: raise BudgetExceeded("Anakin reports insufficient credits")
            if r.status_code >= 400: raise FetchError(f"Anakin submit HTTP {r.status_code}: {r.text[:200]}", status=r.status_code)
            job = r.json()["jobId"]
            deadline = time.monotonic() + self.timeout
            while True:
                time.sleep(self.poll_s)
                d = requests.get(f"{self.base}/url-scraper/{job}", headers=h, timeout=60).json()
                if d.get("status") in ("completed", "failed"): break
                if time.monotonic() > deadline: raise FetchError(f"Anakin job {job} timed out")
        except requests.RequestException as e:
            raise FetchError(f"Anakin request failed: {type(e).__name__}") from e  # message excludes headers/key
        reported = d.get("creditsUsed", d.get("credits"))
        cost = 0.0 if d.get("cached") else float(reported if reported is not None else CREDITS_PER_SCRAPE)
        note = "reported by API" if reported is not None else "computed from published pricing; API did not report credits"
        if d.get("status") == "failed":
            self.ledger.log(url, 0.0, job_id=job, note=f"failed (refunded per docs): {d.get('error')}")
            raise FetchError(f"Anakin job failed: {d.get('error')}", blocked=True)
        self.ledger.log(url, cost, job_id=job, cached=bool(d.get("cached")), note=note)
        html = (d.get("html") or d.get("cleanedHtml") or "").encode()
        if not html: raise FetchError("Anakin returned no HTML")
        res = FetchResult(url=url, content=html, sha256=sha256_bytes(html), fetcher=self.name, content_type="text/html",
                          credits_used=cost)
        return self.cache.put(res, {"anakin_job": job, "anakin_cached": d.get("cached"), "markdown_len": len(d.get("markdown") or "")})
