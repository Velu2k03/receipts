# Receipts backend (FastAPI)

Evidence-trail agent API. Endpoints: `POST /ask`, `GET /runs/{id}`, `POST /claims/{id}/override`, `GET /evidence/insights`, `GET /health`.

Env vars: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `GEMINI_API_KEY`, plus the optional sponsor integration variables below.

Run locally: `pip install -r requirements.txt && uvicorn app:app --port 8000`

Run tests: `python -m unittest test_memory_engine test_zetaris_client` and `python test_pipeline.py`. Test isolation: the memory engine resolves its DB and audit paths from the environment at construction time, and every test module points those paths at a temp directory before importing the app, so the suites may run in any order without writing fixtures to the real data/memory.db.

## Meterless H-MEM evidence memory

`memory_engine.py` implements the Meterless H-MEM engine as two services:

- `MemoryStoreService` persists verified claims (with their citations and confidence scores) from completed runs into a local SQLite store.
- `MemoryRetrievalService` scores stored claims against a new question and returns the relevant ones.

In `app.py`, `/ask` consults the evidence memory before the pipeline runs, so prior verified claims are returned alongside the new run in the `memory_claims` field, and the run trace records the step "Checked evidence memory: N prior claims found". After a run completes, its evidenced claims are stored so future questions can retrieve them. Memory failures never break the `/ask` flow.

## Nightshift provider layer

`llm_provider.py` routes model calls. Meterless Nightshift, an OpenAI-compatible endpoint, is the primary provider when configured:

- `METERLESS_BASE_URL`: e.g. `http://127.0.0.1:8088/v1`. The provider only activates when this variable is explicitly set.
- `METERLESS_RUNTIME_TOKEN`: bearer token for the Nightshift runtime.
- `METERLESS_MODEL`: defaults to `meterless/auto`.

Every request carries the header `meterless-app: receipts`. If Nightshift is not configured, or a call to it fails, generation falls back automatically to the Gemini path.

## Zetaris data layer

`zetaris_client.py` exposes the evidence store to Zetaris as a virtual data layer. On every `GET /evidence/insights` call the store is exported to `data/zetaris/runs.csv`, `data/zetaris/claims.csv` and `data/zetaris/sources.csv`, and the aggregates (top sources by claim count, average confidence per source domain, claims per run, claims at 90 percent confidence or higher) are answered through Zetaris when an instance is configured:

- `ZETARIS_BASE_URL`: origin of the Zetaris web UI, e.g. `http://localhost:3000`
- `ZETARIS_API_KEY`: token from Zetaris Management, API Tokens
- `ZETARIS_ORG_ID`: numeric organisation ID from Zetaris Management

Register the exported CSVs once in a running Zetaris instance using `scripts/register_zetaris_sources.py` (or the matching statements in `scripts/register_zetaris_sources.sql`). With no instance configured, or if it fails, the same aggregates are computed locally; the response names the serving engine (`"engine": "zetaris"` or `"engine": "local"`) and every call is logged to `logs/zetaris-audit.jsonl`. Zetaris needs a machine with 6 to 8 GB of RAM available for its Docker stack.
