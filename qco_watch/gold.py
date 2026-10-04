"""Gold-set conversion + strict validation. Pure parsing/checking: it never edits, infers or fills in a label value, and never calls an LLM.
A value that cannot be parsed is nulled in the JSONL (original kept in '<field>_raw') and reported as a problem."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

LABEL_COLS = ["doc_id", "file_name", "source_url", "split", "is_qco", "qco_number", "title", "ministry", "notification_date", "products",
              "is_standards", "hs_codes_printed", "effective_date", "compliance_deadline", "change_type", "exemptions", "source_page",
              "source_quote", "label_notes"]
HS_COLS = ["product_text", "source_doc_id", "correct_hs6", "alt_hs6", "hs4_heading", "tariff_source", "confidence", "notes"]
from .extract.schema import CHANGE_TYPES  # noqa: E402

CHANGE_TYPES = list(CHANGE_TYPES)
SPLITS = ("dev", "test")
DATE_FIELDS = ("notification_date", "effective_date", "compliance_deadline")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_DEV, MIN_TEST, MIN_HS_ROWS, MAX_CHAPTER_SHARE = 10, 40, 30, 0.25


@dataclass
class Problem:
    level: str  # error | warning
    file: str
    row: int | None
    key: str | None
    field: str | None
    msg: str

    def line(self) -> str:
        where = f"{self.file}" + (f" row {self.row}" if self.row else "") + (f" ({self.key})" if self.key else "")
        return f"- **{where}**" + (f" `{self.field}`" if self.field else "") + f": {self.msg}"


@dataclass
class Result:
    labels: list[dict] = field(default_factory=list)
    product_hs: list[dict] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def errors(self): return [p for p in self.problems if p.level == "error"]
    @property
    def warnings(self): return [p for p in self.problems if p.level == "warning"]


def cell(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def split_list(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(";") if x.strip()]


def digits(v: str) -> str: return re.sub(r"[\s.]", "", v)


def norm_ws(s: str) -> str: return re.sub(r"\s+", " ", s).strip()


def _loose(s: str) -> str:
    from .extract.english import norm
    return norm(s)


def sanitize_name(name: str) -> str:
    """Same rule RawStore uses to build file names (so a source-site file name can be matched to its raw copy)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", unquote(name))[:80]


def read_csv(path: Path, cols: list[str], res: Result) -> list[dict] | None:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        head = [h.strip() for h in (rd.fieldnames or [])]
        missing, extra = [c for c in cols if c not in head], [h for h in head if h not in cols]
        if missing:
            res.problems.append(Problem("error", path.name, None, None, None, f"missing columns: {missing}")); return None
        if extra: res.problems.append(Problem("warning", path.name, None, None, None, f"unknown extra columns ignored: {extra}"))
        return [{(k or "").strip(): v for k, v in r.items()} for r in rd]


class RawIndex:
    """file_name -> raw file -> sha256 -> parsed text json."""

    def __init__(self, raw_dir: Path, text_dir: Path):
        self.text_dir, self.files = text_dir, {}
        for p in raw_dir.rglob("*") if raw_dir.exists() else []:
            if p.is_file() and not p.name.endswith(".meta.json"):
                self.files.setdefault(re.sub(r"^[0-9a-f]{12}_", "", p.name), []).append(p)
                self.files.setdefault(p.name, []).append(p)
        self._pages: dict[Path, dict[int, str]] = {}

    def find(self, file_name: str) -> tuple[Path | None, str]:
        hits = {p for k in {file_name, sanitize_name(file_name)} for p in self.files.get(k, [])}
        if not hits: return None, "no file in data/raw with this file_name"
        if len(hits) > 1: return None, f"ambiguous: {len(hits)} files in data/raw match"
        return hits.pop(), ""

    def text_json(self, raw: Path) -> tuple[Path | None, str]:
        try: sha = json.loads(raw.with_name(raw.name + ".meta.json").read_text())["sha256"]
        except Exception: return None, "raw file has no readable .meta.json sha256"
        cands = sorted(self.text_dir.glob(f"*_{sha[:10]}.json")) if self.text_dir.exists() else []
        return (cands[0], "") if cands else (None, "no parsed text in data/text for this file")

    def pages(self, raw: Path) -> tuple[dict[int, str] | None, str]:
        if raw in self._pages: return self._pages[raw], ""
        tj, why = self.text_json(raw)
        if tj is None: return None, why
        d = json.loads(tj.read_text())
        self._pages[raw] = {p["page"]: p["text"] for p in d["pages"]}
        return self._pages[raw], ""


def convert_labels(rows: list[dict], idx: RawIndex, res: Result, fname="labels.csv") -> None:
    seen: dict[str, list[int]] = {}
    for n, r in enumerate(rows, start=2):
        doc_id = cell(r["doc_id"])
        E = lambda f, m: res.problems.append(Problem("error", fname, n, doc_id, f, m))
        W = lambda f, m: res.problems.append(Problem("warning", fname, n, doc_id, f, m))
        o: dict = {"doc_id": doc_id, "file_name": cell(r["file_name"]), "source_url": cell(r["source_url"])}
        if not doc_id: E("doc_id", "blank doc_id")
        else: seen.setdefault(doc_id, []).append(n)
        sp = cell(r["split"])
        if sp not in SPLITS: E("split", f"split must be 'dev' or 'test', got {sp!r}"); o["split_raw"] = sp; sp = None
        o["split"] = sp
        q = cell(r["is_qco"])
        if q in ("yes", "no"): o["is_qco"] = q == "yes"
        else:
            E("is_qco", "blank is_qco" if q is None else f"is_qco must be 'yes' or 'no', got {q!r}")
            o["is_qco"] = None
            if q is not None: o["is_qco_raw"] = q
        for f in ("qco_number", "title", "ministry"): o[f] = cell(r[f])
        for f in DATE_FIELDS:
            v = cell(r[f]); o[f] = v
            if v is not None:
                try:
                    if not ISO.match(v): raise ValueError
                    date.fromisoformat(v)
                except ValueError:
                    E(f, f"not a valid YYYY-MM-DD date: {v!r}"); o[f] = None; o[f + "_raw"] = v
        o["products"], o["is_standards"] = split_list(r["products"]), split_list(r["is_standards"])
        o["hs_codes"] = split_list(r["hs_codes_printed"])
        for c in o["hs_codes"]:
            if len(digits(c)) not in (2, 4, 6, 8) or not digits(c).isdigit(): E("hs_codes_printed", f"not a 2/4/6/8-digit code: {c!r}")
        ct = cell(r["change_type"])
        if ct is not None and ct not in CHANGE_TYPES:
            E("change_type", f"unknown change_type {ct!r}; allowed: {CHANGE_TYPES}"); o["change_type_raw"] = ct; ct = None
        o["change_type"] = ct
        o["exemptions"] = split_list(r["exemptions"])
        pg_raw, quote = cell(r["source_page"]), cell(r["source_quote"])
        pg = None
        if pg_raw is not None:
            if pg_raw.isdigit() and int(pg_raw) >= 1: pg = int(pg_raw)
            else: E("source_page", f"source_page must be a positive integer, got {pg_raw!r}"); o["source_page_raw"] = pg_raw
        o["source_page"], o["source_quote"], o["label_notes"] = pg, quote, cell(r["label_notes"])
        if quote and pg_raw is None: E("source_page", "source_quote given but source_page blank")
        if pg_raw and not quote: W("source_quote", "source_page given but source_quote blank")

        fn = o["file_name"]
        if not fn: E("file_name", "blank file_name")
        else:
            raw, why = idx.find(fn)
            if raw is None: E("file_name", why)
            else:
                pages, why = idx.pages(raw)
                if pages is None: E("file_name", why)
                elif quote and pg:
                    if pg not in pages: E("source_page", f"page {pg} does not exist (document has {len(pages)} pages)")
                    else:
                        nq = norm_ws(quote)
                        if nq not in norm_ws(pages[pg]):
                            hint = ""
                            if _loose(quote) in _loose(pages[pg]): hint = " (matches only after case/quote-character normalisation)"
                            else:
                                other = [p for p, t in pages.items() if nq in norm_ws(t)]
                                if other: hint = f" (found verbatim on page(s) {other})"
                            E("source_quote", f"quote not found verbatim on page {pg}{hint}: {quote[:100]!r}")
        res.labels.append(o)
    for d, ns in seen.items():
        if len(ns) > 1:
            for n in ns: res.problems.append(Problem("error", fname, n, d, "doc_id", f"duplicate doc_id (rows {ns})"))

    sc, cc = Counter(o["split"] for o in res.labels if o["split"]), Counter(o["change_type"] or "(blank)" for o in res.labels)
    src = Counter((urlparse(o["source_url"] or "").netloc or "(none)") for o in res.labels)
    res.stats["labels"] = {"rows": len(rows), "per_split": dict(sc), "per_change_type": dict(cc), "per_source": dict(src)}
    if rows:
        if sc.get("dev", 0) < MIN_DEV: res.problems.append(Problem("warning", fname, None, None, "split", f"dev has {sc.get('dev', 0)} documents (< {MIN_DEV})"))
        if sc.get("test", 0) < MIN_TEST: res.problems.append(Problem("warning", fname, None, None, "split", f"test has {sc.get('test', 0)} documents (< {MIN_TEST})"))
        for c in CHANGE_TYPES[:-1]:
            if cc.get(c, 0) == 0: res.problems.append(Problem("warning", fname, None, None, "change_type", f"no rows with change_type={c!r} ('unclear' not required)"))


def convert_product_hs(rows: list[dict], hs_codes: set[str] | None, label_docs: dict[str, str | None] | None, res: Result, fname="product_hs.csv") -> None:
    chapters, seen = Counter(), set()
    for n, r in enumerate(rows, start=2):
        pt = cell(r["product_text"])
        E = lambda f, m: res.problems.append(Problem("error", fname, n, pt, f, m))
        W = lambda f, m: res.problems.append(Problem("warning", fname, n, pt, f, m))
        o: dict = {"product_text": pt, "source_doc_id": cell(r["source_doc_id"])}
        if not pt: E("product_text", "blank product_text")
        if o["source_doc_id"] and label_docs is not None and o["source_doc_id"] not in label_docs:
            E("source_doc_id", f"doc_id {o['source_doc_id']!r} not in labels.csv")
        elif not o["source_doc_id"]: W("source_doc_id", "blank source_doc_id: row cannot be assigned to dev/test and is excluded from split evals")
        c_raw = cell(r["correct_hs6"])
        c = digits(c_raw) if c_raw else None
        if c is None: E("correct_hs6", "blank correct_hs6")
        elif not (c.isdigit() and len(c) == 6): E("correct_hs6", f"must be exactly 6 digits after stripping dots/spaces, got {c_raw!r}"); o["correct_hs6_raw"] = c_raw; c = None
        o["correct_hs6"] = c
        alts = []
        for a in split_list(r["alt_hs6"]):
            d = digits(a)
            if d.isdigit() and len(d) == 6: alts.append(d)
            else: E("alt_hs6", f"must be exactly 6 digits, got {a!r}"); o.setdefault("alt_hs6_raw", []).append(a)
        o["alt_hs6"] = alts
        h_raw = cell(r["hs4_heading"])
        h = digits(h_raw) if h_raw else None
        if h is None: E("hs4_heading", "blank hs4_heading (not auto-filled)")
        elif not (h.isdigit() and len(h) == 4): E("hs4_heading", f"must be exactly 4 digits, got {h_raw!r}"); o["hs4_heading_raw"] = h_raw; h = None
        elif c and h != c[:4]: E("hs4_heading", f"hs4_heading {h} != first 4 digits of correct_hs6 {c}")
        o["hs4_heading"] = h
        o["tariff_source"], o["confidence"], o["notes"] = cell(r["tariff_source"]), cell(r["confidence"]), cell(r["notes"])
        if hs_codes is not None:
            for code, f in [(c, "correct_hs6")] + [(a, "alt_hs6") for a in alts]:
                if code and code not in hs_codes:
                    W(f, f"{code} not in downloaded HS2022 list (retired/renamed code? left unchanged)")
        if c: chapters[c[:2]] += 1
        k = (pt, o["source_doc_id"], c)
        if k in seen: W("product_text", "duplicate row (same product_text, source_doc_id, correct_hs6)")
        seen.add(k)
        res.product_hs.append(o)
    total = sum(chapters.values())
    res.stats["product_hs"] = {"rows": len(rows), "per_chapter": dict(sorted(chapters.items()))}
    if rows and len(rows) < MIN_HS_ROWS: res.problems.append(Problem("warning", fname, None, None, None, f"only {len(rows)} rows (< {MIN_HS_ROWS})"))
    for ch, k in chapters.items():
        if total and k / total > MAX_CHAPTER_SHARE:
            res.problems.append(Problem("warning", fname, None, None, "correct_hs6", f"chapter {ch} has {k}/{total} rows ({k / total:.0%} > {MAX_CHAPTER_SHARE:.0%})"))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def report_md(res: Result) -> str:
    out = ["# Gold set validation report", "", f"**Status: {'FAILED' if res.errors else 'OK'}** - {len(res.errors)} error(s), {len(res.warnings)} warning(s).",
           "", "Errors are hard problems (bad format, missing files/pages, quotes not found, ...) and make the converter exit non-zero. "
           "No label value was edited; unparseable values are null in the JSONL with the original in `<field>_raw`.", "", "## Counts", "", "```json",
           json.dumps(res.stats, indent=1, ensure_ascii=False), "```", ""]
    for title, items in (("Errors", res.errors), ("Warnings", res.warnings)):
        out += [f"## {title} ({len(items)})", ""] + ([p.line() for p in items] or ["None."]) + [""]
    return "\n".join(out)
