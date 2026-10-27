# Receipts architecture

Two runtimes ship the same idea, and they are not the same deployment.
Confusing them is the easiest way to misread this repo, so this file
keeps them apart.

## Request flow

```
User question
  -> Next.js frontend (Vercel)
  -> Supabase Edge Function "api" (production path)
       init -> planner -> searcher (Tavily) -> extractor/scorer
       -> storage (Supabase Postgres) -> composer
  -> Answer + scored claims + citations + trace
       + Looks right / Flag controls
```

The Python pipeline in `backend/` is a reference implementation of the
same stages. It is not what serves receipts-livid.vercel.app. It exists
so the sponsor integrations can be run, tested, and read locally
without a Supabase project.

```
User question (Python reference)
  -> FastAPI POST /ask
  -> memory (H-MEM retrieval, before planning)
  -> init -> planner -> searcher (DuckDuckGo)
  -> extractor/linker/scorer (Gemini, or Nightshift first)
  -> storage (Supabase + local H-MEM store)
  -> composer
  -> RunResponse: answer, claims, citations, trace, memory_claims
```

Trace actions, in order, for the Python pipeline: init, memory,
planner, searcher, extractor_scorer, storage, composer. The hosted
Edge Function trace is init, planner, searcher, extractor_scorer,
storage, composer. The memory step exists only in the Python pipeline;
the hosted demo does not include the H-MEM feature.

## What each part does

| Part | File | Job |
|---|---|---|
| Frontend | `app/page.tsx` | Ask, show answer, claims, citations, trace, Looks right / Flag |
| Hosted backend | `supabase/functions/api/index.ts` | Plan, Tavily search, Gemini extract/score/compose, Supabase storage |
| Python pipeline | `backend/app.py` | Same stages plus H-MEM retrieval, DuckDuckGo search, quote validation |
| Evidence memory | `backend/memory_engine.py` | H-MEM: `MemoryStoreService` stores verified claims; `MemoryRetrievalService` returns related prior claims for a new question |
| Provider layer | `backend/llm_provider.py` | Nightshift first when `METERLESS_BASE_URL` is set, otherwise Gemini; failures fall back to Gemini and are logged |
| Data layer | `backend/zetaris_client.py` | Exports runs/claims/sources to CSV, registers them in Zetaris, answers `GET /evidence/insights` through Zetaris when configured, otherwise locally |
| Quote gate | `backend/app.py`, `supabase/functions/api/index.ts` | Drops a citation whose snippet stops mid-sentence or is not verbatim in its source; drops the claim only if no valid citation remains; never completes or invents a quote |

## Built when

Pre-existing work, built Oct 17-18, 2026, before the hackathon
window, and declared as such in the submission:

- Next.js frontend, hosted Supabase Edge Function backend, original
  Python pipeline, original pitch deck.

Built in the window, Oct 22-27, 2026:

- Meterless H-MEM evidence memory, wired into `POST /ask`
  (`backend/memory_engine.py`)
- Meterless Nightshift provider layer with logged Gemini fallback
  (`backend/llm_provider.py`)
- Zetaris data layer and `GET /evidence/insights`
  (`backend/zetaris_client.py`, `backend/scripts/`)
- Quote-completeness validation in both backends, with regression
  tests (`backend/test_quote_validation.py`)
- Test-isolation fix for the memory store
- README sponsor section, `metadata.json`, pitch deck v2, demo video

## Sponsor wiring, honestly

- H-MEM: built and test-covered in the Python pipeline. The hosted
  demo does not include it.
- Nightshift: built as the primary provider in the Python pipeline
  when configured. No live Nightshift run has happened yet, because
  the runtime is not installed on the participant machine. The hosted
  demo runs on Gemini.
- Zetaris: built as the virtual data layer over the exported evidence
  CSVs. No live Zetaris run has happened yet, for the same reason.
  With no instance configured, `GET /evidence/insights` answers
  locally and names `"engine": "local"` in its response.
- Cursor: not used. Development used Muse AI assistance. This is
  disclosed, not claimed otherwise. Cursor is optional for this event.
- NVIDIA: no Nemotron model is used in the current build.

## Known limits

- The Edge Function TypeScript code mirrors the Python quote
  validation but has no unit-test harness in this repo; a live
  retest after redeploy is the check for that backend.
- Old runs already stored in Supabase keep their stored quotes; the
  quote gate does not repair them.
- A truncated search snippet that already looks like a complete
  fragment cannot be detected as truncated by the validator.
- There is no Unified Semantic Layer document, DDL, or data-quality
  rule evidence yet for the Zetaris scoring criteria published Oct 27.
  The current Zetaris work is the CSV data layer and the insights
  endpoint, not a USL package.
- The demo video v1 is pre-sponsor: it shows no H-MEM feature and
  no live Nightshift request.
