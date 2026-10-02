from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from .base import FetchError, FetchResult, Fetcher
from .store import sha256_bytes


class DropFolderFetcher(Fetcher):
    """Manually placed files in <data>/drop. fetch(url) matches by file name; scan() lists everything."""
    name = "drop"

    def __init__(self, drop_dir: Path):
        self.dir = Path(drop_dir)

    def _result(self, p: Path, url: str) -> FetchResult:
        b = p.read_bytes()
        return FetchResult(url=url, content=b, sha256=sha256_bytes(b), fetcher=self.name,
                           content_type="application/pdf" if p.suffix.lower() == ".pdf" else None, raw_path=str(p), from_cache=True)

    def fetch(self, url, *, kind="document", expect=None) -> FetchResult:
        name = Path(unquote(urlparse(url).path)).name
        p = self.dir / name
        if not name or not p.is_file(): raise FetchError(f"{name!r} not in drop folder", blocked=True)
        return self._result(p, url)

    def scan(self) -> list[FetchResult]:
        return [self._result(p, f"drop://{p.name}") for p in sorted(self.dir.glob("*.pdf"))]
