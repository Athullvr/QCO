# QCO Watch – Architecture

> Informational only. Check the official notification.

Monitors India's BIS Quality Control Orders (QCOs), extracts structured data, and alerts users only when a change
affects HS codes they watch. **Trust rule:** every extracted fact keeps `document_id + page + quoted text`. Unknown = `null`, never guessed.

## Data flow

```
sources ─► fetcher chain ─► raw store ─► change_detector ─► parser ─► text store
 (BIS,     Http → Anakin →   data/raw      sha256 vs DB     PDF→pages   data/text
  DGFT…)   Drop folder       + .meta.json   new/modified     (+OCR)      N_<sha>.json/.txt
                                                                   │
                  Phase 2: extractor(LLM, JSON schema) ► validator ► store ► review_queue
                  Phase 3: matcher(prefix, deterministic) ► alerts ► API/dashboard
                  Phase 4: RAG (pgvector chunks) ► cited answers
```

## Modules (`qco_watch/`)

| Module | Status | Notes |
|---|---|---|
| `config.py` | P1 | pydantic-settings; secrets only from env/.env (`SecretStr`, never logged). |
| `fetcher/` | P1 | `Fetcher` interface; `HttpFetcher`, `AnakinFetcher`, `DropFolderFetcher`; `FetcherChain`. |
| `change_detector.py` | P1 | `record_fetch()` → `NEW / MODIFIED / UNCHANGED` by sha256; keeps `document_versions`. |
| `parser/pdf.py` | P1 | PyMuPDF per-page text; OCR (tesseract eng+hin) for pages with <40 chars; quality metrics + warnings. |
| `sources/bis.py` | P1 | Discovery via BIS WordPress media API. |
| `pipeline.py` | P1 | fetch → detect → parse → write text; unparseable docs go to `review_queue`. |
| `db/models.py`, `alembic/` | P1 | Full schema incl. `qco, qco_event, qco_product, qco_hs_map, users, watch_codes, alerts, review_queue`, plus `documents, document_versions, fetch_log, anakin_ledger, hs_master, text_chunks (vector), llm_cache`. |
| extractor / validator / eval | P2 | LLM only extracts; strict JSON schema; **needs a stronger model**. |
| matcher / alerts / api | P3 | Matching is plain code: watch `8541` matches QCO code `854140` (either direction of the hierarchy). |
| qa (RAG) | P4 | pgvector retrieval; answer must cite chunk. |

## Fetcher design

* One interface: `fetch(url, kind='document'|'listing', expect=regex) -> FetchResult(content, sha256, fetcher, credits_used, from_cache, …)`.
* **Order:** Http → Anakin → Drop. Anakin is **only** tried for `kind='listing'` (it returns rendered HTML, not PDFs) and only when enabled
  (`ANAKIN_API_KEY` set and `ANAKIN_MAX_CREDITS > 0`). A 403/429/captcha/JS-shell/SSL failure on Http is "blocked" and triggers fallback.
* **robots.txt** is checked per host before each Http request (a robots 404/HTML error page = no rules). A robots disallow stops the chain
  (we do not route around it with another fetcher). Per-host rate limit: `MIN_REQUEST_INTERVAL_S` (default 2 s). Honest `User-Agent`.
* **Raw cache:** `data/raw/<host>/<urlhash>_<name>` + `.meta.json` (url, fetched_at, sha256, fetcher, credits_used, http_status, etag, last-modified).
  Documents (PDFs) are immutable → never refetched. Listings re-fetched after `LISTING_TTL_HOURS` using `If-None-Match/If-Modified-Since`.
* **Anakin credit controls:** own response cache (24 h TTL, cached = 0 credits) · append-only ledger `data/anakin_ledger.jsonl` (one line per request,
  mirrored by table `anakin_ledger`) · budget checked **before** every request: `spent + cost > ANAKIN_MAX_CREDITS` ⇒ `BudgetExceeded`, no call made ·
  `scripts/anakin_probe.py --dry-run` prints the estimate; run it on 3-5 pages before any full run.
  Cost = 1 credit/URL scrape (published pricing; JS rendering is free, actions +1). The API response does not report credits, so the ledger records
  the computed cost and says so in `note`; reconcile against the Anakin dashboard.
* **Drop folder:** `data/drop/*.pdf` are ingested by `phase1_run.py` as source `drop` (url `drop://<name>`); also used as last-resort by file name.
* Playwright rendering is available in `HttpFetcher(render=True)` (lazy import; requires `playwright install chromium`, which the Dockerfile does).

## Parser

Digital text first; a page with <40 chars goes to OCR (`eng+hin`). If tesseract is missing the doc is `needs_ocr` and queued for review (never silently empty).
Output `data/text/<doc_id>_<sha10>.json` (`pages[{page,text,method,chars}]`, status, warnings, metrics) and a `.txt` with `===== PAGE n =====` markers.
Known limit: BIS gazette PDFs are bilingual; the **Hindi text layer is mis-decoded** (wrong matras/conjuncts). English text is clean, so Phase 2 should extract
from English pages and use Hindi only via OCR.

## Assumptions (please correct)

1. `DATA_DIR` defaults to `./data` (mounted as `/data` in Docker), because `/data` is not writable in a normal dev shell.
2. "QCO notification" = gazette orders/amendments/rescissions/suspensions published as PDFs on bis.gov.in (found via its WP media API).
3. Notifications almost never contain HS codes (0 of 50 sampled). HS codes will therefore come from a **product → HS** reference (the `hs_master` list plus
   a curated/LLM-proposed mapping that is always flagged for review) – never invented. The HS master list source still has to be chosen (Phase 2).
4. Embedding dimension is 1536 in the schema (`EMBEDDING_DIM`); revisit when the embedding model is chosen in Phase 4.
5. Dev DB without Docker: `scripts/dev_db.py` (embedded Postgres+pgvector). Normal path is `docker compose up`.

## Model-cost guidance

Cheap model OK: scaffolding, tests, change_type fallback, RAG answers. **Stronger model recommended:** extractor (Phase 2), eval error analysis.
