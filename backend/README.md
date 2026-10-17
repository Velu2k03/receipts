# Receipts backend (FastAPI)

Evidence-trail agent API. Endpoints: `POST /ask`, `GET /runs/{id}`, `POST /claims/{id}/override`, `GET /health`.

Env vars: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `GEMINI_API_KEY`.

Run locally: `pip install -r requirements.txt && uvicorn app:app --port 8000`
