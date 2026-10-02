import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from qco_watch.change_detector import Change, record_fetch
from qco_watch.db.models import Base
from qco_watch.fetcher import sha256_bytes
from qco_watch.fetcher.base import FetchResult


@pytest.fixture
def db():
    pgserver = pytest.importorskip("pgserver")
    import tempfile
    srv = pgserver.get_server(tempfile.mkdtemp())
    eng = create_engine(srv.get_uri().replace("postgresql://", "postgresql+psycopg://", 1))
    with eng.begin() as c: c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(eng)
    with Session(eng) as s: yield s
    srv.cleanup()


def r(b): return FetchResult("https://x/a.pdf", b, sha256_bytes(b), "http", raw_path="/tmp/a")


def test_new_unchanged_modified(db):
    assert record_fetch(db, r(b"v1"), source="bis").change == Change.NEW
    assert record_fetch(db, r(b"v1"), source="bis").change == Change.UNCHANGED
    d = record_fetch(db, r(b"v2"), source="bis")
    assert d.change == Change.MODIFIED and d.previous_sha256 == sha256_bytes(b"v1")
    assert len(d.document.versions) == 2
