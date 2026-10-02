"""Hash-based new/modified/unchanged detection, backed by documents + document_versions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models import Document, DocumentVersion
from .fetcher.base import FetchResult


class Change(str, Enum):
    NEW = "new"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


@dataclass
class Detection:
    change: Change
    document: Document
    previous_sha256: str | None = None


def record_fetch(db: Session, r: FetchResult, *, source: str, kind: str = "document", title: str | None = None,
                 published_at=None) -> Detection:
    """Upsert the document, add a version row if the hash is new, and say what changed. Caller commits."""
    now = datetime.now(timezone.utc)
    doc = db.scalar(select(Document).where(Document.url == r.url))
    if doc is None:
        doc = Document(url=r.url, source=source, kind=kind, title=title, published_at=published_at)
        change, prev = Change.NEW, None
        db.add(doc)
    else:
        prev = doc.current_sha256
        change = Change.UNCHANGED if prev == r.sha256 else Change.MODIFIED
        doc.last_seen_at = now
        if title and not doc.title: doc.title = title
    if change != Change.UNCHANGED:
        doc.current_sha256, doc.last_changed_at = r.sha256, now
        doc.content_type, doc.raw_path = r.content_type, r.raw_path
        db.flush()
        if not db.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id == doc.id, DocumentVersion.sha256 == r.sha256)):
            db.add(DocumentVersion(document_id=doc.id, sha256=r.sha256, fetched_at=r.fetched_at, fetcher=r.fetcher,
                                   credits_used=r.credits_used, size_bytes=len(r.content), http_status=r.http_status,
                                   raw_path=r.raw_path or ""))
    db.flush()
    return Detection(change, doc, prev)
