"""Phase 2a extractor: English pages -> LLM (strict JSON) -> deterministic grounding checks.
The LLM only *proposes*; code verifies every quote against the page text, every date against its quote, and every HS code
against the document text. Anything that fails is dropped from the value and recorded in `issues` (=> review queue)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .english import norm
from .schema import Extraction

PROMPT_VERSION = "p2a-v1"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]

SYSTEM = """You extract structured facts from Indian Government of India Gazette notifications (English text only) about
Quality Control Orders (QCOs) issued under the Bureau of Indian Standards Act, 2016.
Rules:
- Use ONLY the supplied text. Never use outside knowledge. If a value is not stated, return null (or an empty list).
- Every value needs `page` (from the ===== PAGE n ===== marker) and `quote`: a VERBATIM excerpt (max 300 chars) copied from that page.
- change_type: new = a new QCO; amended = other amendment of an existing QCO; extended = a compliance/commencement date is postponed;
  relaxed = exemptions/relaxations added or conditions eased; withdrawn = rescinded/revoked/omitted. If several apply choose the dominant one and explain in notes.
- notification_date = date printed under 'New Delhi, the ...' (date of the Order). effective_date = when it comes into force (a 'date of publication in the Official Gazette'
  commencement means effective_date = notification_date, quote that sentence). compliance_deadline = the date by which goods must conform; for an extension use the NEW date.
- products: goods the Order covers, with the IS standard(s) printed for each (verbatim IS numbers). For an amendment that only changes dates, list the products of the principal order if named in the text.
- hs_codes: MUST be an empty list unless an HS / ITC-HS / tariff code is literally printed in the text. Never infer codes from product names.
- is_qco: true for QCOs and their amendments/extensions/relaxations/rescissions; false for anything else (e.g. DGFT trade policy, general notices).
- Dates are ISO 8601 (YYYY-MM-DD)."""


@dataclass
class Result:
    extraction: dict | None
    issues: list[dict] = field(default_factory=list)
    needs_review: bool = False
    model: str = ""
    prompt_version: str = PROMPT_VERSION


def build_user(pages: list[tuple[int, str]]) -> str:
    return "\n".join(f"\n===== PAGE {n} =====\n{t}" for n, t in pages)


def _quote_ok(quote: str, page: int, pages: dict[int, str]) -> bool:
    q = norm(quote)
    return bool(q) and page in pages and q in pages[page]


def _date_matches(d: date, quote: str) -> bool:
    q = quote.lower()
    if str(d.year) not in q or re.search(rf"(?<!\d)0?{d.day}(?!\d)", q) is None: return False
    mon = MONTHS[d.month - 1]
    return mon in q or mon[:3] in q or re.search(rf"[./-]0?{d.month}[./-]", q) is not None


def _norm_code(c: str) -> str: return re.sub(r"\D", "", c)


def validate(raw: dict, pages: list[tuple[int, str]]) -> Result:
    issues: list[dict] = []
    pm = {n: norm(t) for n, t in pages}
    full_digits = {n: re.sub(r"[^\d]", "", t) for n, t in pm.items()}
    try:
        ex = Extraction.model_validate(raw)
    except Exception as e:  # noqa: BLE001
        return Result(None, [{"field": "_schema", "problem": str(e)[:500]}], True)
    d = ex.model_dump(mode="json")

    def check(field_name: str, fact: dict | None, *, is_date: bool = False) -> dict | None:
        if fact is None: return None
        if not _quote_ok(fact["quote"], fact["page"], pm):
            issues.append({"field": field_name, "problem": "quote not found on cited page", "quote": fact["quote"][:120], "page": fact["page"]}); return None
        if is_date and not _date_matches(date.fromisoformat(fact["value"]), fact["quote"]):
            issues.append({"field": field_name, "problem": "date not supported by its quote", "value": fact["value"], "quote": fact["quote"][:120]}); return None
        return fact

    for f in ("order_title", "ministry", "is_qco_quote", "change_type_quote"): d[f] = check(f, d[f])
    for f in ("notification_date", "effective_date", "compliance_deadline"): d[f] = check(f, d[f], is_date=True)
    if d["change_type"] and not d["change_type_quote"]:
        issues.append({"field": "change_type", "problem": "no verified supporting quote; keeping value but flagged", "value": d["change_type"]})
    if d["is_qco"] is not None and not d["is_qco_quote"]:
        issues.append({"field": "is_qco", "problem": "no verified supporting quote", "value": d["is_qco"]})

    prods = []
    for p in d["products"]:
        if not _quote_ok(p["quote"], p["page"], pm):
            issues.append({"field": "products", "problem": "quote not found on cited page", "name": p["name"], "page": p["page"]}); continue
        std_ok = []
        for s in p["is_standards"]:
            if norm(s) in pm[p["page"]] or norm(s) in " ".join(pm.values()): std_ok.append(s)
            else: issues.append({"field": "is_standards", "problem": "IS standard string not found in document", "value": s})
        p["is_standards"] = std_ok
        prods.append(p)
    d["products"] = prods

    hs = []
    for h in d["hs_codes"]:
        digits = _norm_code(h["code"])
        if len(digits) not in (2, 4, 6, 8) or not _quote_ok(h["quote"], h["page"], pm) or digits not in full_digits.get(h["page"], ""):
            issues.append({"field": "hs_codes", "problem": "code not literally printed on cited page; dropped", "value": h["code"]}); continue
        hs.append({**h, "code": digits})
    d["hs_codes"] = hs

    required_missing = [k for k in ("notification_date", "change_type") if not d[k]]
    if d["is_qco"] and required_missing:
        issues.append({"field": "_required", "problem": f"missing: {required_missing}"})
    return Result(d, issues, needs_review=bool(issues) or d["is_qco"] is None)


def extract(pages: list[tuple[int, str]], llm) -> Result:
    if not pages: return Result(None, [{"field": "_input", "problem": "no English text pages"}], True, llm.model)
    raw = llm.json_call(SYSTEM, build_user(pages), Extraction.model_json_schema(), name="record_extraction")
    r = validate(raw, pages)
    r.model = llm.model
    return r
