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

| Layer | Technology |
|---|---|
| Frontend | Next.js (App Router), React, Tailwind CSS, shadcn/ui — deployed on Vercel |
| Backend (production) | Supabase Edge Function (`supabase/functions/api`, Deno) + Supabase Postgres |
| Backend (reference) | The original Python pipeline in `backend/` (FastAPI) — same stages, kept for local development |
| AI model | Google Gemini (`gemini-3.8-flash`) for planning, extraction, scoring, composition |
| Search | Tavily API for live web sources |

## Setup

### Frontend

```bash
pnpm install
```

Create `.env.local`:

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
google-generativeai, duckduckgo-search, pydantic.

External services: Google Gemini API, Tavily API, Supabase (Postgres + Edge
Functions), Vercel (hosting).

## License

MIT
