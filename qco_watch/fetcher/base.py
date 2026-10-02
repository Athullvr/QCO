from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class FetchResult:
    url: str
    content: bytes
    sha256: str
    fetcher: str
    content_type: str | None = None
    http_status: int | None = 200
    credits_used: float = 0.0
    from_cache: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_path: str | None = None
    meta: dict = field(default_factory=dict)


class FetchError(Exception):
    """blocked=True means 'this fetcher can't get it, try the next one' (403/429/captcha/JS shell)."""

    def __init__(self, msg: str, *, blocked: bool = False, status: int | None = None, outcome: str = "error"):
        super().__init__(msg)
        self.blocked, self.status, self.outcome = blocked, status, outcome


class BudgetExceeded(FetchError):
    def __init__(self, msg: str):
        super().__init__(msg, blocked=True, outcome="budget")


class Fetcher(ABC):
    name: str

    @abstractmethod
    def fetch(self, url: str, *, kind: str = "document", expect: str | None = None) -> FetchResult:
        """kind: 'document' (immutable file, e.g. PDF) or 'listing' (page that changes).
        expect: regex that must appear in a listing body, else it is treated as a JS shell/blocked."""
