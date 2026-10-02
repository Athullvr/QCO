"""Raw file store + metadata sidecars. Layout: <root>/<host>/<urlhash>_<name>[.meta.json]"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from .base import FetchResult


def sha256_bytes(b: bytes) -> str: return hashlib.sha256(b).hexdigest()


class RawStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, url: str) -> Path:
        u = urlparse(url)
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", unquote(Path(u.path).name) or "index")[:80]
        if u.query: name += "_" + hashlib.sha1(u.query.encode()).hexdigest()[:6]
        if "." not in name[-6:]: name += ".html"
        return self.root / u.netloc / f"{hashlib.sha1(url.encode()).hexdigest()[:12]}_{name}"

    def get(self, url: str) -> FetchResult | None:
        p = self.path_for(url)
        mp = p.with_name(p.name + ".meta.json")
        if not (p.exists() and mp.exists()): return None
        m = json.loads(mp.read_text())
        content = p.read_bytes()
        return FetchResult(url=url, content=content, sha256=m["sha256"], fetcher=m["fetcher"], content_type=m.get("content_type"),
                           http_status=m.get("http_status"), credits_used=m.get("credits_used", 0),
                           fetched_at=datetime.fromisoformat(m["fetched_at"]), raw_path=str(p), meta=m)

    def put(self, r: FetchResult, extra: dict | None = None) -> FetchResult:
        p = self.path_for(r.url)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
        r.raw_path = str(p)
        r.meta = {"url": r.url, "fetched_at": r.fetched_at.isoformat(), "sha256": r.sha256, "fetcher": r.fetcher,
                  "credits_used": r.credits_used, "http_status": r.http_status, "content_type": r.content_type,
                  "size_bytes": len(r.content), **(extra or {})}
        p.with_name(p.name + ".meta.json").write_text(json.dumps(r.meta, indent=1))
        return r

    def touch(self, url: str, extra: dict | None = None):
        p = self.path_for(url); mp = p.with_name(p.name + ".meta.json")
        m = json.loads(mp.read_text()); m["fetched_at"] = datetime.now(timezone.utc).isoformat(); m.update(extra or {})
        mp.write_text(json.dumps(m, indent=1))
