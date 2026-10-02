"""Probe candidate official sources: reachability, robots.txt, whether plain HTTP is enough. Writes data/reports/sources.json.
Uses only plain HTTP, respects robots.txt and rate limits. Does not spend Anakin credits."""
import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qco_watch.config import settings  # noqa: E402
from qco_watch.fetcher.polite import Politeness  # noqa: E402

TARGETS = [
    ("BIS home", "https://www.bis.gov.in/", r"(?i)bureau of indian standards"),
    ("BIS upcoming QCOs table", "https://www.bis.gov.in/upcoming-qcos-notified-and-due-for-implementation/", r'id="myTable"'),
    ("BIS WP media API (QCO PDFs)", "https://www.bis.gov.in/wp-json/wp/v2/media?search=quality%20control&per_page=5&_fields=source_url,date", r"^\s*\["),
    ("BIS qcocell", "https://qcocell.bis.gov.in/", None),
    ("DGFT notifications page", "https://www.dgft.gov.in/CP/?opt=notification", r"(?i)\.pdf"),
    ("DGFT content API", "https://content.dgft.gov.in/Website/dgftprod/notificationlist", None),
    ("e-Gazette home", "https://egazette.gov.in/", r"(?i)egazette"),
    ("e-Gazette (old domain)", "https://egazette.nic.in/", None),
    ("DPIIT (MoCI)", "https://dpiit.gov.in/", None),
    ("MeitY", "https://www.meity.gov.in/", None),
    ("Dept of Chemicals", "https://chemicals.gov.in/", None),
    ("Ministry of Steel", "https://steel.gov.in/", None),
    ("India Code", "https://www.indiacode.nic.in/", None),
]

pol = Politeness(settings.user_agent, settings.min_request_interval_s)
rows = []
for name, url, marker in TARGETS:
    row = {"name": name, "url": url, "robots_allows": pol.allowed(url)}
    if row["robots_allows"]:
        pol.wait(url)
        try:
            r = requests.get(url, headers={"User-Agent": settings.user_agent}, timeout=30)
            body = r.text
            row.update(status=r.status_code, bytes=len(r.content), final_url=r.url,
                       marker_found=(bool(re.search(marker, body, re.M)) if marker else None),
                       js_shell_suspected=len(re.sub(r"(?s)<(script|style).*?</\1>|<[^>]+>|\s+", " ", body).strip()) < 800)
        except requests.RequestException as e:
            row.update(status=None, error=type(e).__name__)
    rows.append(row)
    print(row)
settings.report_dir.mkdir(parents=True, exist_ok=True)
(settings.report_dir / "sources.json").write_text(json.dumps(rows, indent=1))
