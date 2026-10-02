from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import requests

from .base import FetchError, FetchResult, Fetcher
from .polite import Politeness
from .store import RawStore, sha256_bytes

BLOCK_STATUS = {401, 403, 406, 429, 451, 503}


def looks_blocked_or_js_shell(body: bytes, expect: str | None) -> str | None:
    t = body.decode("utf-8", "ignore")
    if expect and not re.search(expect, t): return f"expected pattern {expect!r} absent (JS shell / block page?)"
    if re.search(r"(?i)captcha|access denied|request rejected|are you a robot", t[:20000]): return "captcha/block page"
    return None


class HttpFetcher(Fetcher):
    """Plain requests by default; render=True uses Playwright (lazy import, needs `playwright install chromium`)."""
    name = "http"

    def __init__(self, store: RawStore, polite: Politeness, *, ttl_hours: float = 12, timeout: float = 45, render: bool = False):
        self.store, self.polite, self.ttl, self.timeout, self.render = store, polite, timedelta(hours=ttl_hours), timeout, render
        self.s = requests.Session(); self.s.headers.update({"User-Agent": polite.ua, "Accept-Language": "en-IN,en;q=0.8"})

    def fetch(self, url, *, kind="document", expect=None) -> FetchResult:
        cached = self.store.get(url)
        if cached and cached.fetcher == self.name:
            if kind == "document" or datetime.now(timezone.utc) - cached.fetched_at < self.ttl:
                cached.from_cache = True; cached.credits_used = 0; return cached
        if not self.polite.allowed(url): raise FetchError("disallowed by robots.txt", outcome="robots_disallowed")
        self.polite.wait(url)
        hdr = {}
        if cached and kind == "listing":
            if cached.meta.get("etag"): hdr["If-None-Match"] = cached.meta["etag"]
            if cached.meta.get("last_modified"): hdr["If-Modified-Since"] = cached.meta["last_modified"]
        try:
            body, status, ctype, resp_hdr = self._render(url) if self.render else self._get(url, hdr)
        except requests.RequestException as e:
            raise FetchError(f"{type(e).__name__}: {e}", blocked=True) from e
        if status == 304 and cached:
            self.store.touch(url); cached.from_cache = True; cached.credits_used = 0; cached.meta["outcome"] = "not_modified"; return cached
        if status in BLOCK_STATUS: raise FetchError(f"HTTP {status}", blocked=True, status=status)
        if status >= 400: raise FetchError(f"HTTP {status}", status=status)
        if kind == "listing" and (why := looks_blocked_or_js_shell(body, expect)): raise FetchError(why, blocked=True, status=status)
        if kind == "document" and not body: raise FetchError("empty body", status=status)
        r = FetchResult(url=url, content=body, sha256=sha256_bytes(body), fetcher=self.name, content_type=ctype, http_status=status)
        return self.store.put(r, {"etag": resp_hdr.get("ETag"), "last_modified": resp_hdr.get("Last-Modified")})

    def _get(self, url, hdr, attempts: int = 3):
        for i in range(attempts):
            try:
                r = self.s.get(url, headers=hdr, timeout=self.timeout, allow_redirects=True)
                return r.content, r.status_code, r.headers.get("content-type"), r.headers
            except (requests.ConnectionError, requests.Timeout):
                if i == attempts - 1: raise
                time.sleep(2 * (i + 1)); self.polite.wait(url)

    def _render(self, url):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page(user_agent=self.polite.ua)
            resp = pg.goto(url, wait_until="networkidle", timeout=int(self.timeout * 1000))
            html = pg.content().encode(); b.close()
        return html, resp.status if resp else 200, "text/html", {}
