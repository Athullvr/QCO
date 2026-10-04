
"""Schema. Every extracted fact (product, HS code, event) carries provenance:
document_id + source_page + source_quote."""
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1536
Json = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


def _now(): return mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    source: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(20), default="document")  # document | listing
    title: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[date | None] = mapped_column(Date)
    current_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    content_type: Mapped[str | None] = mapped_column(String(100))
    raw_path: Mapped[str | None] = mapped_column(Text)
    text_path: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    parse_status: Mapped[str | None] = mapped_column(String(30))
    first_seen_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
    last_changed_at: Mapped[datetime] = _now()
    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="document")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = _now()
    fetcher: Mapped[str] = mapped_column(String(20))
    credits_used: Mapped[float] = mapped_column(Float, default=0)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    http_status: Mapped[int | None] = mapped_column(Integer)
    raw_path: Mapped[str] = mapped_column(Text)
    document: Mapped[Document] = relationship(back_populates="versions")
    __table_args__ = (UniqueConstraint("document_id", "sha256"),)


class FetchLog(Base):
    __tablename__ = "fetch_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(Text, index=True)
    ts: Mapped[datetime] = _now()
    fetcher: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str] = mapped_column(String(30))  # ok | cache_hit | not_modified | blocked | error | robots_disallowed | budget
    http_status: Mapped[int | None] = mapped_column(Integer)
    credits_used: Mapped[float] = mapped_column(Float, default=0)
    detail: Mapped[str | None] = mapped_column(Text)


class AnakinLedger(Base):
    __tablename__ = "anakin_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = _now()
    url: Mapped[str] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(String(100))
    credits: Mapped[float] = mapped_column(Float)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)


class Qco(Base):
    __tablename__ = "qco"
    id: Mapped[int] = mapped_column(primary_key=True)
    qco_number: Mapped[str | None] = mapped_column(String(200), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    ministry: Mapped[str | None] = mapped_column(Text)
    notification_date: Mapped[date | None] = mapped_column(Date)
    is_qco: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _now()
    events: Mapped[list["QcoEvent"]] = relationship(back_populates="qco")


class QcoEvent(Base):
    __tablename__ = "qco_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    qco_id: Mapped[int | None] = mapped_column(ForeignKey("qco.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    change_type: Mapped[str | None] = mapped_column(String(20))  # new|amended|extended|relaxed|withdrawn
    notification_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)
    compliance_deadline: Mapped[date | None] = mapped_column(Date)
    exemptions: Mapped[list | None] = mapped_column(Json)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_quote: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    extractor_version: Mapped[str | None] = mapped_column(String(50))
    raw_extraction: Mapped[dict | None] = mapped_column(Json)
    created_at: Mapped[datetime] = _now()
    qco: Mapped[Qco | None] = relationship(back_populates="events")


class QcoProduct(Base):
    __tablename__ = "qco_product"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("qco_event.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    is_standard: Mapped[str | None] = mapped_column(String(200))
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_quote: Mapped[str | None] = mapped_column(Text)


class QcoHsMap(Base):
    __tablename__ = "qco_hs_map"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("qco_event.id", ondelete="CASCADE"), index=True)
    qco_id: Mapped[int | None] = mapped_column(ForeignKey("qco.id", ondelete="CASCADE"), index=True)
    hs_code: Mapped[str] = mapped_column(String(8))  # digits only, length 2/4/6/8
    hs_level: Mapped[int] = mapped_column(Integer)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_quote: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (Index("ix_qco_hs_map_prefix", "hs_code", postgresql_ops={"hs_code": "text_pattern_ops"}),)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    alert_mode: Mapped[str] = mapped_column(String(10), default="immediate")  # immediate | digest
    created_at: Mapped[datetime] = _now()


class WatchCode(Base):
    __tablename__ = "watch_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    hs_code: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("user_id", "hs_code"),)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("qco_event.id"), index=True)
    watch_code: Mapped[str] = mapped_column(String(8))
    matched_hs_code: Mapped[str] = mapped_column(String(8))
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(15), default="pending")  # pending|sent|failed
    source_url: Mapped[str] = mapped_column(Text)
    source_page: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict | None] = mapped_column(Json)
    created_at: Mapped[datetime] = _now()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("user_id", "event_id", "watch_code", "matched_hs_code"),)


class ReviewQueue(Base):
    __tablename__ = "review_queue"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("qco_event.id"))
    reason: Mapped[str] = mapped_column(String(60))  # ocr_failure|low_confidence|invalid_hs|bad_date|no_hs_codes|...
    details: Mapped[dict | None] = mapped_column(Json)
    status: Mapped[str] = mapped_column(String(15), default="open")
    created_at: Mapped[datetime] = _now()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HsMaster(Base):
    __tablename__ = "hs_master"
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    level: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)


class TextChunk(Base):
    __tablename__ = "text_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class LlmCache(Base):
    __tablename__ = "llm_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(doc_sha + prompt_version + model)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    provider: Mapped[str | None] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(100))
    output: Mapped[dict] = mapped_column(Json)
    created_at: Mapped[datetime] = _now()
