"""Runs the extractor over a list of documents and stores one record per document. This is the ONLY place the eval stack calls an LLM."""
from __future__ import annotations

import json
from pathlib import Path

from ..extract.english import load_english
from ..extract.extractor import PROMPT_VERSION, extract
from ..extract.llm import LLMError


def safe_key(key: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in key)


def gold_items(labels: list[dict], idx, split: str) -> tuple[list[tuple[str, Path]], list[dict]]:
    """(doc_id, parsed-text json) for every gold document of `split`; second list = documents that cannot be located."""
    items, bad = [], []
    for l in labels:
        if l.get("split") != split: continue
        raw, why = idx.find(l.get("file_name") or "")
        tj, why2 = idx.text_json(raw) if raw else (None, why)
        if tj: items.append((l["doc_id"], tj))
        else: bad.append({"doc_id": l["doc_id"], "why": why2})
    return items, bad


def run_extraction(items: list[tuple[str, Path]], llm, out_dir: Path, *, log=print) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    recs = []
    for key, tj in items:
        before = dict(llm.usage)
        rec = {"doc_id": key, "model": llm.model, "prompt_version": PROMPT_VERSION, "status": "ok", "needs_review": True, "issues": [],
               "extraction": None, "error": None}
        try:
            r = extract(load_english(tj), llm)
            rec.update(needs_review=r.needs_review, issues=r.issues, extraction=r.extraction)
            if r.extraction is None:
                rec["status"] = "no_english_text" if any(i["field"] == "_input" for i in r.issues) else "schema_invalid"
        except LLMError as e:
            rec.update(status="invalid_json" if "invalid JSON" in str(e) else "llm_error", error=str(e)[:300])
        rec["usage"] = {k: llm.usage[k] - before[k] for k in ("input_tokens", "output_tokens")}
        (out_dir / f"{safe_key(key)}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False))
        recs.append(rec)
        log(f"{key}: {rec['status']} change={((rec['extraction'] or {}).get('change_type'))} issues={len(rec['issues'])}")
    return recs


def load_records(out_dir: Path) -> dict[str, dict]:
    return {r["doc_id"]: r for r in (json.loads(f.read_text()) for f in sorted(out_dir.glob("*.json")))}
