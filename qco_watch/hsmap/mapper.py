"""Product -> candidate HS codes: vector retrieval + LLM rerank. EVERY result is `needs_review`; nothing is ever certain.
Guards: the reranker may only choose codes from the retrieved candidate set (anything else is discarded); without an LLM we
return retrieval order with confidence=None (similarity is NOT a probability)."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .index import HsIndex

NOTICE = "Candidate only - automatically suggested, not verified. Needs human review against the official tariff. Informational only."
MAX_CONF = 0.9

SYSTEM = """You help a compliance analyst shortlist Harmonized System (HS) subheadings for a product named in an Indian Quality Control Order.
You are given the product text and a numbered list of CANDIDATE HS codes with their official descriptions.
Choose up to 5 candidates that could cover the product, best first. Use ONLY codes from the list. Give each a confidence in [0,1]
(your honest estimate that the code covers the product; use low values when the product name is vague or the candidates are generic) and a one-line reason.
If none plausibly fits, return an empty list. Never output a code that is not in the list."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["matches"], "properties": {"matches": {"type": "array", "maxItems": 5, "items": {
    "type": "object", "additionalProperties": False, "required": ["code", "confidence", "reason"],
    "properties": {"code": {"type": "string"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "reason": {"type": "string"}}}}}}


EXPAND_SYSTEM = """Rewrite a product name from an Indian Quality Control Order as up to 3 short phrases in the style of Harmonized System
nomenclature text (generic goods category, material, use - e.g. a named chemical -> its chemical class). Do not output codes."""
EXPAND_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["phrases"],
                 "properties": {"phrases": {"type": "array", "maxItems": 3, "items": {"type": "string"}}}}


@dataclass
class Candidate:
    code: str
    description: str
    heading_context: str
    retrieval_score: float
    confidence: float | None
    reason: str | None
    status: str = "needs_review"


def map_product(product: str, index: HsIndex, llm=None, *, standards: list[str] | None = None, k: int = 30) -> dict:
    q = product + (" (" + "; ".join(standards) + ")" if standards else "")
    hits = index.search(q, k)
    if llm is not None:  # query expansion: recall fix for product names that HS text never uses (e.g. 'lauric acid')
        extra = [x for ph in llm.json_call(EXPAND_SYSTEM, q, EXPAND_SCHEMA, name="expand_query").get("phrases", [])[:3] for x in index.search(ph, k // 2)]
        best: dict[str, tuple] = {}
        for e, sc in hits + extra:
            if e.code not in best or sc > best[e.code][1]: best[e.code] = (e, sc)
        hits = sorted(best.values(), key=lambda t: -t[1])[: k + k // 2]
    by = {e.code: (e, s) for e, s in hits}
    ranked, mode = [], "retrieval_only"
    if llm is not None:
        user = f"Product: {product}\nIS standards: {', '.join(standards or []) or 'n/a'}\n\nCANDIDATES:\n" + "\n".join(
            f"{e.code} | {e.context}" for e, _ in hits)
        raw = llm.json_call(SYSTEM, user, SCHEMA, name="rank_candidates")
        for m in raw.get("matches", []):
            if m["code"] in by and all(m["code"] != r[0] for r in ranked):
                ranked.append((m["code"], min(float(m["confidence"]), MAX_CONF), m["reason"]))
        mode = "llm_rerank"
    if not ranked:  # no LLM or reranker returned nothing usable
        ranked = [(e.code, None, None) for e, _ in hits[:5]]
        if llm is not None: mode = "llm_rerank_empty_fallback_to_retrieval"
    cands = [Candidate(c, by[c][0].description, by[c][0].context, round(by[c][1], 4), conf, reason) for c, conf, reason in ranked[:5]]
    return {"product": product, "standards": standards or [], "mode": mode, "status": "needs_review", "notice": NOTICE,
            "candidates": [asdict(c) for c in cands], "embedder": index.embedder.name}
