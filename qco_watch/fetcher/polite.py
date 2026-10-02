"""robots.txt compliance + per-host rate limiting."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests


class Politeness:
    def __init__(self, user_agent: str, min_interval_s: float = 2.0, timeout: float = 20):
        self.ua, self.interval, self.timeout = user_agent, min_interval_s, timeout
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _load(self, base: str) -> RobotFileParser | None:
        """None = no usable robots.txt (404, HTML error page, unreachable) -> nothing is disallowed."""
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": self.ua}, timeout=self.timeout)
            ctype = r.headers.get("content-type", "")
            if r.status_code != 200 or "html" in ctype.lower(): return None
            rp = RobotFileParser(); rp.parse(r.text.splitlines()); return rp
        except requests.RequestException:
            return None

    def allowed(self, url: str) -> bool:
        u = urlparse(url); base = f"{u.scheme}://{u.netloc}"
        if base not in self._robots: self._robots[base] = self._load(base)
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.ua, url)

    def wait(self, url: str):
        host = urlparse(url).netloc
        with self._lock:
            delay = self._last.get(host, 0) + self.interval - time.monotonic()
            if delay > 0: time.sleep(delay)
            self._last[host] = time.monotonic()
