# Receipts

**Every AI answer ships with a clickable evidence trail.**

Receipts is an evidence-first AI research agent. Ask it a question and it does
not just hand you an answer: it shows the key findings behind the answer, a
confidence score for each one, the exact sources and quotes each finding stands
on, and a step-by-step trace of how the answer was produced. If something looks
wrong, you can flag it.

Built for the Open Agent Hackathon 2026, Track 02: The Agent That Can Explain Why.

**Live demo:** https://receipts-livid.vercel.app

## Why

AI agents give answers nobody can explain or check. When an agent hallucinates,
the developer who shipped it gets blamed and has no record of what the answer
was based on. Receipts fixes that at the root: the evidence ships WITH the
answer, not in a separate audit tool nobody opens.

## How it works

1. **Plan** — the question is broken into sub-questions.
2. **Search** — live web search (Tavily) gathers sources for each sub-question.
3. **Extract** — atomic claims are pulled from the sources, each tied to the
   exact quote that supports it.
4. **Score** — every claim gets a confidence score.
5. **Compose** — the final answer is assembled from the scored claims, with
   citations intact.

Every run also produces a trace ("How it found this") listing each step in
order, and every claim carries **Looks right** / **Flag** controls so a human
can mark bad evidence.

## Architecture

Two runtimes, kept apart on purpose. The hosted demo is served by the
Supabase Edge Function, not by the Python pipeline. Full detail,
including the trace steps for each runtime, is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Samples, with each one
labelled live, test fixture, or response shape, are in
[`docs/SAMPLES.md`](docs/SAMPLES.md).

```
User question
  -> Next.js frontend (Vercel)
  -> Supabase Edge Function "api" (production)
       init -> planner -> searcher (Tavily) -> extractor/scorer
       -> storage (Supabase Postgres) -> composer
  -> Answer + scored claims + citations + trace + Looks right / Flag
```

Python reference pipeline (`backend/`, FastAPI): the same stages,
plus H-MEM retrieval before planning, DuckDuckGo search, and the
quote-completeness gate. It is where the sponsor integrations run
and are tested locally.

| Layer | Technology |
|---|---|
| Frontend | Next.js (App Router), React, Tailwind CSS, shadcn/ui — deployed on Vercel |
| Backend (production) | Supabase Edge Function (`supabase/functions/api`, Deno) + Supabase Postgres |
| Backend (reference) | Python pipeline in `backend/` (FastAPI) — same stages, kept for local development and sponsor testing |
| AI model | Google Gemini for planning, extraction, scoring, composition (hosted demo: `gemini-3.1-flash-lite`; Python reference pipeline: `gemini-3.8-flash`, or Nightshift first when configured) |
| Search | Tavily API for live web sources (hosted); DuckDuckGo (Python reference) |

### Pick your way in

| You want to | Do this | Time |
|---|---|---|
| Try it | Open https://receipts-livid.vercel.app, ask a question | 0 min |
| Run the frontend locally | `pnpm install`, set `NEXT_PUBLIC_API_URL`, `pnpm dev` | 5 min |
| Run the Python pipeline | `cd backend`, `pip install -r requirements.txt`, `uvicorn app:app --port 8000` | 5 min, plus API keys |
| Run the tests | See backend/README.md; all suites are offline | 2 min |

### Built when

Pre-existing, Oct 17-18, 2026, declared in the submission: Next.js
frontend, hosted Supabase Edge Function backend, original Python
pipeline, original pitch deck.

Built in the hackathon window, Oct 22-27, 2026: Meterless H-MEM
evidence memory, Meterless Nightshift provider layer with Gemini
fallback, Zetaris data layer with `GET /evidence/insights`,
quote-completeness validation in both backends, test-isolation fix,
README sponsor section, `metadata.json`, pitch deck v2, demo video.

### Known limits

- Live Nightshift and Zetaris runtimes are not yet installed on the
  participant machine, so the hosted demo runs on Gemini and the
  local insights path. Sponsor paths are built and test-covered in
  the repo pipeline, not yet proven live.
- The demo video v1 is pre-sponsor: no H-MEM feature, no live
  Nightshift request.
- The Edge Function TypeScript quote validation has no unit-test
  harness in this repo; a live retest after redeploy is its check.
- No Unified Semantic Layer document, DDL, or data-quality rule
  evidence exists yet for the Zetaris scoring criteria published
  Oct 27. That is a gap, stated in `docs/ARCHITECTURE.md`, not hidden.

## Sponsor integrations (Open Agent Hackathon)

Receipts integrates both Open Agent Hackathon sponsor platforms in the
Python pipeline under `backend/`:

- **Meterless H-MEM engine.** The H-MEM engine, implemented as
  `MemoryStoreService` and `MemoryRetrievalService` in
  `backend/memory_engine.py`, powers the evidence memory feature:
  verified claims from completed runs are stored with their citations
  and confidence scores, then retrieved and returned with later
  questions whose answers they support.
- **Meterless Nightshift.** Nightshift is the primary AI provider when
  configured via the `METERLESS_BASE_URL`, `METERLESS_RUNTIME_TOKEN`
  and `METERLESS_MODEL` environment variables. If Nightshift is not
  configured or a call fails, generation falls back automatically to
  Gemini. The provider layer lives in `backend/llm_provider.py`.
- **Zetaris.** Zetaris serves as the virtual data layer over the
  exported evidence store (runs, claims and sources CSV files) for the
  `GET /evidence/insights` feature, implemented in
  `backend/zetaris_client.py`. The SQL that registers the exported
  files in a Zetaris instance is in `backend/scripts/`, and the
  detailed setup steps are in the Zetaris section below.

Status, stated plainly: all three integrations are built and
test-covered in the repo pipeline, with mocked-HTTP tests for the
sponsor paths. The live Nightshift and Zetaris runtimes are not yet
installed on the participant's machine, so the hosted demo runs the
same pipeline logic with Gemini as the model provider and the local
aggregates path for insights. The sponsor paths activate when those
runtimes are configured.

## Setup

### Frontend

```bash
pnpm install
```

Copy `.env.example` to `.env.local` and fill in your values
(placeholders only in the example, no real keys):

```bash
NEXT_PUBLIC_API_URL=https://<your-project>.supabase.co/functions/v1/api
```

Run:

```bash
pnpm dev        # local development
pnpm build      # production build
```

### Backend (Supabase Edge Function)

Deploy the function in `supabase/functions/api` to your Supabase project and
set these secrets in the Supabase dashboard (Project Settings → Edge Functions):

- `GEMINI_API_KEY` — Google AI Studio API key
- `TAVILY_API_KEY` — Tavily search API key

### Backend (Python reference pipeline)

```bash
cd backend
pip install -r requirements.txt
uvicorn app:app --reload
```

Requires the same `GEMINI_API_KEY` and `TAVILY_API_KEY` environment variables
plus Supabase project credentials.

## Usage

1. Open the live demo (or your local frontend).
2. Type any question and press **Ask**.
3. Read the answer summary, then scan the key findings and their confidence
   scores.
4. Expand a finding to see its sources, with links and the exact supporting
   quotes.
5. Use **Looks right** or **Flag** on any claim, and open **How it found this**
   for the full step trace.

## Dependencies

Frontend (see `package.json`): Next.js, React, Tailwind CSS, shadcn/ui,
@base-ui/react, lucide-react, @vercel/analytics.

Python pipeline (see `backend/requirements.txt`): FastAPI, uvicorn, supabase,
google-generativeai, duckduckgo-search, pydantic, httpx.

External services: Google Gemini API, Tavily API, Supabase (Postgres + Edge
Functions), Vercel (hosting).

## Zetaris evidence data layer (optional)

The Python pipeline can expose its evidence store (the verified claims
kept by the local H-MEM memory engine) to [Zetaris](https://www.zetaris.com)
as a virtual data layer, so aggregate questions over the evidence are
answered with federated SQL instead of in-process code.

How it works:

1. On every `GET /evidence/insights` call, the store is exported to
   `data/zetaris/runs.csv`, `data/zetaris/claims.csv` and
   `data/zetaris/sources.csv`.
2. `scripts/register_zetaris_sources.py` prints the Lightning SQL that
   registers those files in a running Zetaris instance (a
   `receipts_evidence` Lightning database with three CSV file tables);
   `scripts/register_zetaris_sources.sql` is the same statements with a
   path placeholder. Run them once in the Zetaris SQL Workspace.
3. Set the environment and restart the app:

   ```bash
   ZETARIS_BASE_URL=http://localhost:3000   # Zetaris web UI origin
   ZETARIS_API_KEY=<key from Management, API Tokens>
   ZETARIS_ORG_ID=<numeric ID from Management, Organisation>
   ```

4. `GET /evidence/insights` now answers through Zetaris (top sources
   by claim count, average confidence per source domain, claims per
   run, claims at 90 percent confidence or higher) and names the
   serving engine in the response (`"engine": "zetaris"`). With no
   instance configured, or if the instance fails, the same aggregates
   are computed locally and the response says `"engine": "local"`.
   Every insights call is logged to `logs/zetaris-audit.jsonl`.

Zetaris needs a machine with enough RAM for its Docker stack (6 to 8
GB); it does not have to be the machine serving this app, but the
instance must be able to read the exported CSV paths.

## License

MIT
