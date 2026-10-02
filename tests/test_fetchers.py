import json
from datetime import datetime, timezone

import pytest

from qco_watch.fetcher import (AnakinFetcher, BudgetExceeded, CreditLedger, DropFolderFetcher, FetchError, FetcherChain, RawStore,
                               sha256_bytes)
from qco_watch.fetcher.base import FetchResult, Fetcher
from qco_watch.fetcher.http import looks_blocked_or_js_shell


class Stub(Fetcher):
    def __init__(self, name, result=None, err=None): self.name, self.result, self.err, self.calls = name, result, err, 0
    def fetch(self, url, *, kind="document", expect=None):
        self.calls += 1
        if self.err: raise self.err
        return self.result


def res(url, name):
    b = b"x"; return FetchResult(url, b, sha256_bytes(b), name)


def test_chain_falls_back_http_anakin_drop():
    u = "https://x/y"
    http, ana, drop = Stub("http", err=FetchError("403", blocked=True, status=403)), Stub("anakin", err=FetchError("off", blocked=True)), Stub("drop", res(u, "drop"))
    assert FetcherChain(http, ana, drop).fetch(u, kind="listing").fetcher == "drop"
    assert (http.calls, ana.calls, drop.calls) == (1, 1, 1)


def test_anakin_never_used_for_documents():
    u = "https://x/a.pdf"
    http, ana, drop = Stub("http", err=FetchError("403", blocked=True)), Stub("anakin", res(u, "anakin")), Stub("drop", res(u, "drop"))
    assert FetcherChain(http, ana, drop).fetch(u, kind="document").fetcher == "drop"
    assert ana.calls == 0


def test_robots_disallow_stops_chain():
    u = "https://x/y"
    http, drop = Stub("http", err=FetchError("robots", outcome="robots_disallowed")), Stub("drop", res(u, "drop"))
    with pytest.raises(FetchError): FetcherChain(http, None, drop).fetch(u)
    assert drop.calls == 0


def test_anakin_hard_stop_and_cache(tmp_path):
    led = CreditLedger(tmp_path / "l.jsonl")
    led.log("u", 4.0)
    fx = AnakinFetcher("k", RawStore(tmp_path / "c"), led, max_credits=5)
    assert fx.estimate_cost("https://a/b") == 1.0
    led.log("u2", 1.0)
    with pytest.raises(BudgetExceeded): fx.fetch("https://a/b", kind="listing")  # 5 + 1 > 5, no network call made


def test_anakin_cache_hit_costs_nothing(tmp_path):
    store = RawStore(tmp_path / "c")
    store.put(FetchResult("https://a/b", b"<html>", sha256_bytes(b"<html>"), "anakin", credits_used=1))
    fx = AnakinFetcher("k", store, CreditLedger(tmp_path / "l.jsonl"), max_credits=1)
    r = fx.fetch("https://a/b", kind="listing")
    assert r.from_cache and r.credits_used == 0 and fx.estimate_cost("https://a/b") == 0


def test_anakin_disabled_without_key(tmp_path):
    fx = AnakinFetcher("", RawStore(tmp_path), CreditLedger(tmp_path / "l"), max_credits=10)
    with pytest.raises(FetchError): fx.fetch("https://a/b", kind="listing")


def test_drop_folder(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    d = DropFolderFetcher(tmp_path)
    assert d.fetch("https://anything/a.pdf").sha256 == sha256_bytes(b"%PDF-1.4")
    assert [r.url for r in d.scan()] == ["drop://a.pdf"]
    with pytest.raises(FetchError): d.fetch("https://anything/missing.pdf")


def test_store_roundtrip_has_metadata(tmp_path):
    s = RawStore(tmp_path)
    s.put(FetchResult("https://h/p/q.pdf", b"abc", sha256_bytes(b"abc"), "http", credits_used=0))
    g = s.get("https://h/p/q.pdf")
    assert g.content == b"abc" and g.meta["fetcher"] == "http" and g.meta["url"] == "https://h/p/q.pdf" and g.meta["sha256"] == sha256_bytes(b"abc")


def test_js_shell_detection():
    assert looks_blocked_or_js_shell(b"<html><noscript>enable js</noscript></html>", r"id=\"myTable\"")
    assert looks_blocked_or_js_shell(b"Please solve this CAPTCHA", None)
    assert looks_blocked_or_js_shell(b"<table id=\"myTable\">", r"id=\"myTable\"") is None
