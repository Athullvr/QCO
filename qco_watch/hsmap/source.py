"""HS description list loader.

PROPOSED SOURCE (official, no invented codes): the UN Statistics Division / UN Comtrade copy of the WCO Harmonized System,
edition HS2022 ("H6"): https://comtrade.un.org/data/cache/classificationH6.json  (verified reachable, 6,700+ entries: 2/4/6-digit with parent links).
Limits: (1) 6-digit only; India's 8-digit ITC-HS national lines (DGFT) are not included - the DGFT download is behind a dynamic page and still to be located.
(2) HS2022 retired/split some subheadings (e.g. 8541.40 -> 8541.42/.43); notifications that predate 2022 may use codes absent here.
(3) The nomenclature text is WCO-copyrighted; check licence terms before redistributing the list (we only store it locally)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

URL = "https://comtrade.un.org/data/cache/classificationH6.json"
SOURCE_NAME = "UN Comtrade HS2022 (WCO nomenclature)"


@dataclass(frozen=True)
class HsEntry:
    code: str
    level: int
    description: str  # own text, without the code prefix
    context: str  # "heading text > ..." chain used for retrieval only


def load(path: str | Path) -> list[HsEntry]:
    rows = {r["id"]: r for r in json.loads(Path(path).read_text())["results"] if r["id"].isdigit()}

    def own(r): return r["text"].split(" - ", 1)[-1].strip()

    out = []
    for code, r in rows.items():
        if len(code) not in (4, 6): continue
        chain, p = [], r
        while p and p["id"].isdigit():
            chain.append(own(p)); p = rows.get(p["parent"])
        out.append(HsEntry(code, len(code), own(r), " > ".join(reversed(chain))))
    return sorted(out, key=lambda e: e.code)
