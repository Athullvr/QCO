"""Extraction scoring. Pure functions: NO LLM calls. Compares flattened extractor output with gold labels (labels.jsonl field names)."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

SCALARS = ["is_qco", "qco_number", "title", "ministry", "notification_date", "effective_date", "compliance_deadline", "change_type"]
LISTS = ["products", "is_standards", "hs_codes"]
EXACT = {"is_qco", "qco_number", "notification_date", "effective_date", "compliance_deadline", "change_type"}  # strict equality after strip()
NOT_SCORED = ["exemptions (extractor has no such field)", "source_page / source_quote (evidence pointers, not comparable)"]
EXAMPLES = 3


def _v(f): return f["value"] if f else None


def flatten(rec: dict) -> dict:
    """Extractor record ({value,page,quote} facts) -> labels.jsonl field names. order_title->title, product names->products, codes->hs_codes."""
    ex = rec.get("extraction") or {}
    return {"is_qco": ex.get("is_qco"), "qco_number": _v(ex.get("qco_number")), "title": _v(ex.get("order_title")), "ministry": _v(ex.get("ministry")),
            "notification_date": _v(ex.get("notification_date")), "effective_date": _v(ex.get("effective_date")),
            "compliance_deadline": _v(ex.get("compliance_deadline")), "change_type": ex.get("change_type"),
            "products": [p["name"] for p in ex.get("products", [])],
            "is_standards": [s for p in ex.get("products", []) for s in p.get("is_standards", [])],
            "hs_codes": [h["code"] for h in ex.get("hs_codes", [])]}


def count_cited(ex: dict | None) -> int:
    if not ex: return 0
    single = ["is_qco_quote", "qco_number", "order_title", "ministry", "change_type_quote", "notification_date", "effective_date", "compliance_deadline"]
    return sum(1 for f in single if ex.get(f)) + len(ex.get("products", [])) + len(ex.get("hs_codes", []))


def _txt(s): return re.sub(r"\s+", " ", s).strip().casefold().rstrip(".,;:") if isinstance(s, str) else s
def _std(s): return re.sub(r"\s+", "", s).casefold()
def _hs(s): return re.sub(r"\D", "", s)
LIST_NORM = {"products": _txt, "is_standards": _std, "hs_codes": _hs}


def same(field: str, g, p) -> bool:
    if g is None or p is None: return g is p
    if field in EXACT: return (g.strip() if isinstance(g, str) else g) == (p.strip() if isinstance(p, str) else p)
    return _txt(g) == _txt(p)


def _prf(tp, fp, fn):
    pr, rc = (tp / (tp + fp) if tp + fp else None), (tp / (tp + fn) if tp + fn else None)
    f1 = 2 * pr * rc / (pr + rc) if pr and rc else (0.0 if pr is not None and rc is not None else None)
    r4 = lambda x: None if x is None else round(x, 4)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": r4(pr), "recall": r4(rc), "f1": r4(f1)}


def score(gold: list[dict], records: dict[str, dict]) -> dict:
    rows = [g for g in gold if g["doc_id"] in records]
    ids_missing = [g["doc_id"] for g in gold if g["doc_id"] not in records]
    res: dict = {"n_gold": len(gold), "n_scored": len(rows), "not_run": ids_missing, "not_scored_fields": NOT_SCORED}
    errors: dict = defaultdict(lambda: defaultdict(list))
    stat = {f: Counter() for f in SCALARS}
    conf = Counter()
    lst = {f: Counter() for f in LISTS}
    q = Counter()
    status = Counter()
    for g in rows:
        rec = records[g["doc_id"]]
        status[rec["status"]] += 1
        pred = flatten(rec)
        for f in SCALARS:
            gv, pv = g.get(f), pred[f]
            s = stat[f]; s["n"] += 1
            if gv is not None: s["gold_present"] += 1
            if same(f, gv, pv):
                s["correct"] += 1; s["correct_present"] += gv is not None
            else:
                kind = "missing" if pv is None else ("spurious" if gv is None else "wrong")
                s[kind] += 1
                if len(errors[f][kind]) < EXAMPLES: errors[f][kind].append({"doc_id": g["doc_id"], "gold": gv, "pred": pv})
        conf[(g.get("change_type"), pred["change_type"])] += 1
        for f in LISTS:
            n = LIST_NORM[f]
            gs, ps = {n(x) for x in g.get(f, [])}, {n(x) for x in pred[f]}
            lst[f]["tp"] += len(gs & ps); lst[f]["fp"] += len(ps - gs); lst[f]["fn"] += len(gs - ps)
            if (ps - gs or gs - ps) and len(errors[f]["diff"]) < EXAMPLES:
                errors[f]["diff"].append({"doc_id": g["doc_id"], "false_positives": sorted(ps - gs), "false_negatives": sorted(gs - ps)})
        ex = rec.get("extraction")
        q["verified"] += count_cited(ex)
        for i in rec.get("issues", []): q[i.get("code", "other")] += 1
    res["fields"] = {}
    for f, s in stat.items():
        n, gp = s["n"], s["gold_present"]
        res["fields"][f] = {"accuracy": round(s["correct"] / n, 4) if n else None, "n": n,
                            "accuracy_when_gold_present": round(s["correct_present"] / gp, 4) if gp else None, "n_gold_present": gp,
                            "wrong": s["wrong"], "missing": s["missing"], "spurious": s["spurious"]}
    neg = [g for g in rows if g.get("is_qco") is False]
    pos = [g for g in rows if g.get("is_qco") is True]
    fp = sum(1 for g in neg if flatten(records[g["doc_id"]])["is_qco"] is True)
    fn = sum(1 for g in pos if flatten(records[g["doc_id"]])["is_qco"] is not True)
    res["is_qco"] = {"n_gold_false": len(neg), "false_positives": fp, "false_positive_rate": round(fp / len(neg), 4) if neg else None,
                     "n_gold_true": len(pos), "false_negatives": fn, "false_negative_rate": round(fn / len(pos), 4) if pos else None}
    res["change_type_confusion"] = {f"{g}->{p}": n for (g, p), n in sorted(conf.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))}
    res["lists"] = {f: _prf(c["tp"], c["fp"], c["fn"]) for f, c in lst.items()}
    res["hs_codes_note"] = "hs_codes are only those printed in the document; gold hs_codes_printed is usually empty, so any prediction there is a false positive."
    tot = q["verified"] + q["quote_not_found"]
    res["quotes"] = {"verified": q["verified"], "failed": q["quote_not_found"], "share_verified": round(q["verified"] / tot, 4) if tot else None,
                     "date_unsupported": q["date_unsupported"], "standard_not_found": q["standard_not_found"], "hs_not_printed": q["hs_not_printed"]}
    res["run_status"] = dict(status)
    res["json_validity_rate"] = round(status["ok"] / len(rows), 4) if rows else None
    res["errors"] = {f: dict(d) for f, d in errors.items()}
    return res


def format_report(r: dict) -> str:
    L = [f"extraction eval: scored {r['n_scored']}/{r['n_gold']} gold docs" + (f" (not run: {r['not_run']})" if r["not_run"] else ""),
         f"run status: {r['run_status']}  json/schema validity: {r['json_validity_rate']}",
         "per-field accuracy (null==null counts correct | when gold present | wrong/missing/spurious):"]
    for f, d in r["fields"].items():
        L.append(f"  {f:20} {d['accuracy']}  | {d['accuracy_when_gold_present']} (n={d['n_gold_present']}) | {d['wrong']}/{d['missing']}/{d['spurious']}")
    i = r["is_qco"]
    L.append(f"is_qco false-positive rate: {i['false_positive_rate']} ({i['false_positives']}/{i['n_gold_false']})  false-negative: {i['false_negative_rate']} ({i['false_negatives']}/{i['n_gold_true']})")
    L.append("lists (micro P/R/F1):")
    for f, d in r["lists"].items(): L.append(f"  {f:14} P={d['precision']} R={d['recall']} F1={d['f1']}  tp={d['tp']} fp={d['fp']} fn={d['fn']}")
    q = r["quotes"]
    L.append(f"quotes verified: {q['share_verified']} ({q['verified']} ok, {q['failed']} failed) | dates unsupported by quote: {q['date_unsupported']} | IS stds not found: {q['standard_not_found']} | HS dropped as not printed: {q['hs_not_printed']}")
    L.append(f"change_type confusion (gold->pred): {r['change_type_confusion']}")
    L.append("error examples:")
    for f, kinds in r["errors"].items():
        for kind, ex in kinds.items():
            for e in ex: L.append(f"  [{f}/{kind}] " + ", ".join(f"{k}={v!r}" for k, v in e.items()))
    L.append("not scored: " + "; ".join(r["not_scored_fields"]))
    return "\n".join(L)
