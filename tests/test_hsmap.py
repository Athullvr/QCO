import numpy as np

from qco_watch.hsmap.index import HsIndex
from qco_watch.hsmap.mapper import map_product
from qco_watch.hsmap.source import HsEntry


class Emb:
    name = "fake"
    def embed(self, texts, *, query=False):
        return np.array([[1.0 if w in t.lower() else 0.0 for w in ("jute", "steel", "footwear")] for t in texts], dtype=np.float32) + 0.01


ENTRIES = [HsEntry("630510", 6, "Sacks of jute", "Sacks > jute"), HsEntry("721420", 6, "Steel bars", "Bars > steel"),
           HsEntry("640399", 6, "Footwear", "Footwear > footwear")]


class FakeLLM:
    model = "fake"
    def __init__(self, matches): self.m = matches
    def json_call(self, *a, **k): return {"matches": self.m}


def idx(): return HsIndex(ENTRIES, Emb())


def test_retrieval_only_is_needs_review_without_confidence():
    r = map_product("jute bags", idx(), None)
    assert r["status"] == "needs_review" and r["candidates"][0]["code"] == "630510"
    assert all(c["confidence"] is None and c["status"] == "needs_review" for c in r["candidates"])


def test_rerank_discards_invented_codes_and_caps_confidence():
    r = map_product("jute bags", idx(), FakeLLM([{"code": "999999", "confidence": 1, "reason": "x"},
                                                  {"code": "630510", "confidence": 1.0, "reason": "jute"}]))
    assert [c["code"] for c in r["candidates"]] == ["630510"]
    assert r["candidates"][0]["confidence"] <= 0.9 and r["candidates"][0]["status"] == "needs_review"
