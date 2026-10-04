# QCO Watch

Monitors India's BIS Quality Control Orders (QCOs), extracts structured facts from the gazette notifications, and (later phases) alerts users when a change affects the HS codes they watch.

> Informational only. Check the official notification.

**Trust rule:** every extracted fact keeps `document + page + verbatim quote`. Unknown is `null`, never guessed. HS codes are only kept if literally printed in the document; product-to-HS mappings are candidates marked `needs_review`.

## Pipeline

```
sources (BIS, DGFT, ministries) -> fetcher chain (HTTP -> Anakin -> drop folder) -> raw store
  -> change detector (sha256) -> PDF parser (OCR fallback) -> English-only text
  -> LLM extractor + deterministic quote/date/HS checks -> review queue
  -> HS candidate mapping (vector search + LLM rerank, needs_review)
```

| Phase | Status |
|---|---|
| 1. Fetch, change detection, parsing | done |
| 2a. Extractor (products, IS standards, ministry, dates, `change_type`, `is_qco`) | built, not yet run on real data |
| 2b. HS mapping spike (HS2022 list from UN Comtrade) | built (spike) |
| Gold-set conversion + eval harness | built |
| 3. Matcher, alerts, API | planned |
| 4. RAG Q&A | planned |

`change_type` values: `new, amendment, extension, relaxation, withdrawal, unclear`.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # fill in values; .env is git-ignored
scripts/install_hooks.sh      # pre-commit hook: blocks .env and .venv
.venv/bin/python -m pytest -q
```

Key settings (see `.env.example`): `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, optional `LLM_BASE_URL` for OpenAI-compatible endpoints (e.g. Gemini), `LLM_JSON_MODE`, `ANAKIN_API_KEY`.

## Common commands

| Task | Command |
|---|---|
| Fetch + parse BIS notifications | `python scripts/phase1_run.py --limit 50` |
| Convert and validate gold CSVs | `python scripts/gold_convert.py` |
| Run extractor on a gold split (calls the LLM) | `python scripts/extract_run.py --split dev --run NAME` |
| Score extraction | `python scripts/eval_run.py --task extraction --split dev --run NAME` |
| Score HS retrieval | `python scripts/eval_run.py --task retrieval --split dev` |
| Compare models on the same N documents | `python scripts/compare_models.py --config configs/models.json --split dev --n 10` |
| Try HS candidate mapping | `python scripts/hs_map_spike.py "Jute bags"` |

The `test` split needs `--confirm-test`; tuning on test data invalidates results.

## Layout

- `qco_watch/fetcher/`, `parser/`, `sources/`: Phase 1 ingestion
- `qco_watch/extract/`: English filter, schema, LLM client, extractor and validator
- `qco_watch/hsmap/`: HS list loader, vector index, candidate mapper
- `qco_watch/eval/`, `qco_watch/gold.py`: gold-set validation and scoring
- `scripts/`: runnable entry points; `tests/`: pytest suite
- `data/gold/` (labels, tracked), `data/raw`, `data/text`, `data/reports` (git-ignored)

See `ARCHITECTURE.md` for design details and assumptions.
