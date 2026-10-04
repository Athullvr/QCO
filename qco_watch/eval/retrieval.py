"""Retrieval eval for product_hs.jsonl. Pure retrieval (vector search only; no LLM rerank, no query expansion).
A hit = correct_hs6 OR any alt_hs6 is among the top-k results. Heading level: first 4 digits of the results vs {correct, alts} headings."""
from __future__ import annotations

import json
from pathlib import Path

KS = (1, 5, 10)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def select_rows(hs_rows: list[dict], labels: list[dict], split: str) -> tuple[list[dict], list[dict]]:
    """Rows whose source_doc_id belongs to `split`; second list = rows that cannot be assigned (reported, never silently dropped)."""
    sp = {l["doc_id"]: l["split"] for l in labels}
    usable = [r for r in hs_rows if r.get("correct_hs6") and r.get("product_text")]
    return [r for r in usable if sp.get(r["source_doc_id"]) == split], [r for r in usable if sp.get(r["source_doc_id"]) is None]


def evaluate(rows: list[dict], search) -> dict:
    """search(text, k) -> list of 6-digit codes, best first."""
    kmax, hits6, hits4, chap, misses = max(KS), {k: 0 for k in KS}, {k: 0 for k in KS}, {}, []
    for r in rows:
        gold6 = {r["correct_hs6"], *r.get("alt_hs6", [])}
        gold4 = {c[:4] for c in gold6}
        res = search(r["product_text"], kmax)
        ch = chap.setdefault(r["correct_hs6"][:2], {"n": 0, **{f"hit@{k}": 0 for k in KS}})
        ch["n"] += 1
        for k in KS:
            h6, h4 = any(c in gold6 for c in res[:k]), any(c[:4] in gold4 for c in res[:k])
            hits6[k] += h6; hits4[k] += h4; ch[f"hit@{k}"] += h6
        if not any(c in gold6 for c in res[:5]):
            rank = next((i + 1 for i, c in enumerate(res) if c in gold6), None)
            misses.append({"product_text": r["product_text"], "source_doc_id": r.get("source_doc_id"), "correct_hs6": r["correct_hs6"],
                           "alt_hs6": r.get("alt_hs6", []), "found_at_rank_within_10": rank, "top5": res[:5]})
    n = len(rows)
    rate = lambda d: {f"hit@{k}": (round(v / n, 4) if n else None) for k, v in d.items()}
    return {"n": n, "hs6": rate(hits6), "hs4": rate(hits4), "by_chapter": dict(sorted(chap.items())), "misses_not_in_top5": misses}
