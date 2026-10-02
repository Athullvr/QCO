"""Phase 1 pipeline: fetch -> change detection -> parse -> text on disk."""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from sqlalchemy.orm import Session

from .change_detector import Change, record_fetch
from .config import Settings
from .db.models import FetchLog, ReviewQueue
from .fetcher import FetcherChain, FetchError
from .fetcher.base import FetchResult
from .parser import parse_pdf

log = logging.getLogger(__name__)


def write_text(settings: Settings, doc_id: int, sha: str, parsed) -> Path:
    settings.text_dir.mkdir(parents=True, exist_ok=True)
    stem = settings.text_dir / f"{doc_id}_{sha[:10]}"
    stem.with_suffix(".json").write_text(json.dumps(parsed.to_dict(), ensure_ascii=False, indent=1))
    stem.with_suffix(".txt").write_text(parsed.as_text())
    return stem.with_suffix(".json")


def process_result(db: Session, settings: Settings, r: FetchResult, *, source: str, title: str | None, published_at, stats: Counter, parse_rows: list):
    det = record_fetch(db, r, source=source, title=title, published_at=published_at)
    doc = det.document
    stats[f"change_{det.change.value}"] += 1
    if det.change == Change.UNCHANGED and doc.text_path and Path(doc.text_path).exists():
        return
    if not (r.content[:5] == b"%PDF-"):
        stats["not_pdf"] += 1
        db.add(ReviewQueue(document_id=doc.id, reason="not_a_pdf", details={"content_type": r.content_type}))
        return
    parsed = parse_pdf(r.content)
    doc.text_path, doc.page_count, doc.parse_status = str(write_text(settings, doc.id, r.sha256, parsed)), parsed.page_count, parsed.status
    stats[f"parse_{parsed.status}"] += 1
    parse_rows.append({"doc_id": doc.id, "url": r.url, "pages": parsed.page_count, "status": parsed.status, **parsed.metrics, "warnings": parsed.warnings})
    if parsed.status in ("needs_ocr", "empty", "error"):
        db.add(ReviewQueue(document_id=doc.id, reason="ocr_failure" if parsed.status == "needs_ocr" else f"parse_{parsed.status}",
                           details={"warnings": parsed.warnings}))


def log_attempts(db: Session, chain: FetcherChain, start: int):
    for a in chain.attempts[start:]:
        db.add(FetchLog(url=a["url"], fetcher=a["fetcher"], outcome=a["outcome"], http_status=a.get("status"),
                        credits_used=a.get("credits", 0) or 0, detail=a.get("detail")))
