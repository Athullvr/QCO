"""Pure helpers for scripts/compare_models.py (no LLM calls)."""
from __future__ import annotations


def cost_usd(usage: dict, model_cfg: dict) -> float | None:
    pi, po = model_cfg.get("price_in_per_mtok"), model_cfg.get("price_out_per_mtok")
    if pi is None or po is None: return None
    return round(usage["input_tokens"] / 1e6 * pi + usage["output_tokens"] / 1e6 * po, 4)


def summarize(model_cfg: dict, usage: dict, sc: dict, cost: float | None) -> dict:
    return {"name": model_cfg["name"], "model": model_cfg["model"], "cost_usd": cost, "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"], "cached_calls": usage["cached_calls"], "json_validity_rate": sc["json_validity_rate"],
            "run_status": sc["run_status"], "quote_failures": sc["quotes"]["failed"], "quote_share_verified": sc["quotes"]["share_verified"],
            "field_accuracy": {f: d["accuracy"] for f, d in sc["fields"].items()}, "list_f1": {f: d["f1"] for f, d in sc["lists"].items()}}
