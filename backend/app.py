import os
import json
import asyncio
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
import google.generativeai as genai
from duckduckgo_search import DDGS

# primp 2.0.1 (bundled with duckduckgo-search 7.x) only accepts the plain
# "chrome" impersonation profile; restrict DDGS's random pick accordingly.
DDGS._impersonates = ("chrome",)

# ==============================================================================
# Environment & Client Setup
# ==============================================================================

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[WARNING] SUPABASE_URL or SUPABASE_ANON_KEY is missing from environment.")

if not GEMINI_API_KEY:
    print("[WARNING] GEMINI_API_KEY is missing from environment.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-3.8-flash")

thread_pool = ThreadPoolExecutor(max_workers=10)

# ==============================================================================
# FastAPI Application
# ==============================================================================

app = FastAPI(
    title="Receipts - AI Agent with Evidence Trail",
    version="1.0.0",
    description="Answers user queries backed by atomic claims, live DuckDuckGo citations, and trace steps.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# Pydantic Schemas
# ==============================================================================

class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, description="The user query to answer")

class OverrideRequest(BaseModel):
    note: str = Field(..., min_length=1, description="Audit note or override reason")

class CitationSchema(BaseModel):
    id: Optional[str] = None
    claim_id: Optional[str] = None
    source_title: str
    source_url: str
    snippet: str

class OverrideSchema(BaseModel):
    id: Optional[str] = None
    claim_id: Optional[str] = None
    note: str
    created_at: Optional[str] = None

class ClaimSchema(BaseModel):
    id: Optional[str] = None
    run_id: Optional[str] = None
    claim_text: str
    confidence: int
    citations: List[CitationSchema] = []
    overrides: List[OverrideSchema] = []

class TraceStepSchema(BaseModel):
    id: Optional[str] = None
    run_id: Optional[str] = None
    step_order: int
    action: str
    detail: str

class RunResponse(BaseModel):
    id: str
    question: str
    status: str
    created_at: Optional[str] = None
    answer: Optional[str] = None
    trace_steps: List[TraceStepSchema] = []
    claims: List[ClaimSchema] = []

# ==============================================================================
# DB Helper Functions (Non-blocking & Safe)
# ==============================================================================

def _db_insert(table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if not supabase:
        raise RuntimeError("Supabase client is unconfigured.")
    res = supabase.table(table).insert(data).execute()
    return res.data[0] if res.data else {}

def _db_update(table: str, match_col: str, match_val: Any, data: Dict[str, Any]) -> None:
    if not supabase:
        return
    supabase.table(table).update(data).eq(match_col, match_val).execute()

async def db_insert(table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return await asyncio.to_thread(_db_insert, table, data)

async def db_update(table: str, match_col: str, match_val: Any, data: Dict[str, Any]) -> None:
    await asyncio.to_thread(_db_update, table, match_col, match_val, data)

async def record_trace(run_id: str, step_order: int, action: str, detail: str) -> None:
    try:
        await db_insert("trace_steps", {
            "run_id": run_id,
            "step_order": step_order,
            "action": action,
            "detail": detail[:4000] if detail else ""
        })
    except Exception as exc:
        print(f"[Trace Logging Error] step={step_order}, action={action}: {exc}")

# ==============================================================================
# External Pipeline Tasks with Timeouts
# ==============================================================================

async def run_gemini_json(prompt: str, timeout_sec: float = 25.0) -> Any:
    """Invokes Gemini 2.0 Flash in JSON mode with a strict timeout."""
    def _call():
        return gemini_model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )

    response = await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout_sec)
    cleaned = response.text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    return json.loads(cleaned)

def _search_ddg(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    """Performs synchronous DuckDuckGo search."""
    items = []
    with DDGS(timeout=10) as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            items.append({
                "title": r.get("title", "No Title"),
                "href": r.get("href", ""),
                "body": r.get("body", "")
            })
    return items

async def search_subquestion(query: str, timeout_sec: float = 12.0) -> List[Dict[str, str]]:
    """Safe async wrapper around DuckDuckGo search with timeout."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(_search_ddg, query, 8), timeout=timeout_sec)
    except Exception as exc:
        print(f"[DDG Search Error] Query '{query}': {exc}")
        return []

# ==============================================================================
# API Endpoints
# ==============================================================================

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok"}


@app.post("/ask", response_model=RunResponse, tags=["Receipts Pipeline"])
async def ask_pipeline(payload: AskRequest):
    """
    Executes the 8-stage evidence pipeline:
    1. Initialize run & trace
    2. Planner (break into 3 sub-questions)
    3. Searcher (DDG top 8 per query)
    4. Extractor (up to 6 factual claims)
    5. Linker (1-3 exact citations per claim)
    6. Scorer (0-100 confidence based on agreement)
    7. Storage (persist claims & citations)
    8. Composer (2-3 sentence answer & set status to done)
    """
    question = payload.question.strip()
    run_id = None
    step_order = 1

    # (1) Initialize run
    try:
        run_record = await db_insert("runs", {
            "question": question,
            "status": "running"
        })
        run_id = str(run_record.get("id"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initialize run in Supabase: {exc}"
        )

    await record_trace(run_id, step_order, "init", f"Run initialized for question: '{question}'")
    step_order += 1

    # (2) Planner: Generate 3 sub-questions
    sub_questions = []
    try:
        planner_prompt = f"""
        You are a research planner. Break down the following primary question into EXACTLY 3 specific, diverse sub-questions designed for web search engines to locate factual evidence.

        Question: "{question}"

        Return JSON matching this format:
        {{
            "sub_questions": [
                "sub-question 1",
                "sub-question 2",
                "sub-question 3"
            ]
        }}
        """
        plan_json = await run_gemini_json(planner_prompt, timeout_sec=15.0)
        sub_questions = plan_json.get("sub_questions", [])[:3]
    except Exception as exc:
        print(f"[Planner Warning] Gemini planner failed: {exc}")

    # Fallback if planner returned fewer than 3
    while len(sub_questions) < 3:
        sub_questions.append(f"{question} aspect {len(sub_questions) + 1}")

    await record_trace(
        run_id,
        step_order,
        "planner",
        f"Generated 3 sub-questions: {json.dumps(sub_questions)}"
    )
    step_order += 1

    # (3) Searcher: Fetch top 8 DuckDuckGo results per sub-question
    search_tasks = [search_subquestion(sq) for sq in sub_questions]
    search_results_per_query = await asyncio.gather(*search_tasks)

    all_results: List[Dict[str, str]] = []
    seen_urls = set()
    for batch in search_results_per_query:
        for res in batch:
            url = res.get("href")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(res)

    await record_trace(
        run_id,
        step_order,
        "searcher",
        f"Collected {len(all_results)} distinct web sources across {len(sub_questions)} sub-questions."
    )
    step_order += 1

    # Edge Case: If zero or empty search results
    if not all_results:
        honest_claim_text = "Insufficient evidence was found on the web to substantiate any factual claims."
        claim_rec = await db_insert("claims", {
            "run_id": run_id,
            "claim_text": honest_claim_text,
            "confidence": 0
        })
        honest_answer = "Evidence was insufficient to provide a verified answer to this question."

        # Mark done
        try:
            await db_update("runs", "id", run_id, {"status": "done"})
        except Exception:
            pass

        await record_trace(run_id, step_order, "composer", honest_answer)

        return RunResponse(
            id=run_id,
            question=question,
            status="done",
            answer=honest_answer,
            trace_steps=[
                TraceStepSchema(step_order=1, action="init", detail="Run initialized"),
                TraceStepSchema(step_order=2, action="planner", detail=json.dumps(sub_questions)),
                TraceStepSchema(step_order=3, action="searcher", detail="No search results retrieved"),
                TraceStepSchema(step_order=4, action="composer", detail=honest_answer),
            ],
            claims=[
                ClaimSchema(
                    id=str(claim_rec.get("id")),
                    run_id=run_id,
                    claim_text=honest_claim_text,
                    confidence=0,
                    citations=[],
                    overrides=[]
                )
            ]
        )

    # (4, 5, 6) Extractor, Linker, and Scorer via Gemini
    # Compact search results payload for context
    compact_evidence = []
    for idx, r in enumerate(all_results[:24]):
        compact_evidence.append({
            "source_id": idx + 1,
            "title": r["title"],
            "url": r["href"],
            "snippet": r["body"]
        })

    extraction_prompt = f"""
    You are an evidence analyst. Read the search evidence below and answer the primary question:
    Primary Question: "{question}"

    Evidence sources:
    {json.dumps(compact_evidence, indent=2)}

    Tasks:
    1. EXTRACT up to 6 atomic, factual claims directly relevant to answering the primary question. Every claim MUST be directly supported by at least one source snippet.
    2. LINK 1 to 3 citations per claim as {{source_title, source_url, snippet}} where 'snippet' is an EXACT quote taken from the source's snippet.
    3. SCORE confidence (0 to 100) per claim based on how many independent sources agree with it and how direct the evidence is.

    Output format:
    {{
        "claims": [
            {{
                "claim_text": "...",
                "confidence": 85,
                "citations": [
                    {{
                        "source_title": "...",
                        "source_url": "...",
                        "snippet": "..."
                    }}
                ]
            }}
        ]
    }}
    """

    extracted_claims_data = []
    try:
        extraction_res = await run_gemini_json(extraction_prompt, timeout_sec=30.0)
        extracted_claims_data = extraction_res.get("claims", [])[:6]
    except Exception as exc:
        print(f"[Extractor/Scorer Warning] Gemini failed: {exc}")

    # Fallback claim if extraction yielded nothing
    if not extracted_claims_data:
        extracted_claims_data = [{
            "claim_text": "Web search returned documents, but no verifiable atomic claims could be derived.",
            "confidence": 10,
            "citations": []
        }]

    await record_trace(
        run_id,
        step_order,
        "extractor_scorer",
        f"Extracted {len(extracted_claims_data)} atomic claims with citations and confidence scores."
    )
    step_order += 1

    # (7) Persist claims and citations into Supabase
    hydrated_claims: List[ClaimSchema] = []
    for c_data in extracted_claims_data:
        claim_text = c_data.get("claim_text", "").strip()
        confidence = int(c_data.get("confidence", 50))
        citations_data = c_data.get("citations", [])[:3]

        claim_rec = await db_insert("claims", {
            "run_id": run_id,
            "claim_text": claim_text,
            "confidence": max(0, min(100, confidence))
        })
        c_id = str(claim_rec.get("id"))

        hydrated_citations: List[CitationSchema] = []
        for cite in citations_data:
            s_title = cite.get("source_title", "Web Source")
            s_url = cite.get("source_url", "")
            s_snippet = cite.get("snippet", "")
            cite_rec = await db_insert("citations", {
                "claim_id": c_id,
                "source_title": s_title,
                "source_url": s_url,
                "snippet": s_snippet
            })
            hydrated_citations.append(CitationSchema(
                id=str(cite_rec.get("id")) if cite_rec else None,
                claim_id=c_id,
                source_title=s_title,
                source_url=s_url,
                snippet=s_snippet
            ))

        hydrated_claims.append(ClaimSchema(
            id=c_id,
            run_id=run_id,
            claim_text=claim_text,
            confidence=confidence,
            citations=hydrated_citations,
            overrides=[]
        ))

    await record_trace(run_id, step_order, "storage", f"Stored {len(hydrated_claims)} claims and citations.")
    step_order += 1

    # (8) Composer: 2 to 3 sentence direct answer to original question
    composer_prompt = f"""
    You are the final synthesizer for 'Receipts'.
    Write a concise, 2 to 3 sentence direct answer to the user's question, relying ONLY on the verified factual claims below.

    Question: "{question}"
    Verified Claims:
    {json.dumps([c.claim_text for c in hydrated_claims], indent=2)}

    Return JSON:
    {{
        "answer": "2 to 3 sentences answering the question directly."
    }}
    """
    composed_answer = ""
    try:
        composer_res = await run_gemini_json(composer_prompt, timeout_sec=15.0)
        composed_answer = composer_res.get("answer", "").strip()
    except Exception as exc:
        print(f"[Composer Warning] Gemini composer failed: {exc}")
        composed_answer = " ".join([c.claim_text for c in hydrated_claims[:2]])

    # Mark run done in Supabase
    try:
        await db_update("runs", "id", run_id, {"status": "done"})
    except Exception as exc:
        print(f"[DB Update Warning] Failed setting run status to done: {exc}")

    await record_trace(run_id, step_order, "composer", composed_answer)

    # Return the complete run object
    return await get_run_details(run_id, direct_answer=composed_answer)


@app.get("/runs/{run_id}", response_model=RunResponse, tags=["Receipts Pipeline"])
async def get_run(run_id: str):
    """Returns one run with its claims, citations, and trace_steps in order."""
    return await get_run_details(run_id)


async def get_run_details(run_id: str, direct_answer: Optional[str] = None) -> RunResponse:
    if not supabase:
        raise HTTPException(status_code=500, detail="Database client is not configured.")

    # 1. Fetch run
    def _fetch_all():
        run_res = supabase.table("runs").eq("id", run_id).execute()
        if not run_res.data:
            return None, [], [], [], []
        run_data = run_res.data[0]

        # Fetch traces ordered
        traces_res = supabase.table("trace_steps").eq("run_id", run_id).order("step_order").execute()

        # Fetch claims
        claims_res = supabase.table("claims").eq("run_id", run_id).execute()
        claim_ids = [c["id"] for c in claims_res.data] if claims_res.data else []

        citations_data = []
        overrides_data = []
        if claim_ids:
            citations_res = supabase.table("citations").in_("claim_id", claim_ids).execute()
            citations_data = citations_res.data or []

            overrides_res = supabase.table("overrides").in_("claim_id", claim_ids).execute()
            overrides_data = overrides_res.data or []

        return run_data, traces_res.data or [], claims_res.data or [], citations_data, overrides_data

    try:
        run_data, traces_data, claims_data, citations_data, overrides_data = await asyncio.to_thread(_fetch_all)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}")

    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run with ID {run_id} not found.")

    # Organize citations and overrides per claim
    citations_by_claim: Dict[str, List[CitationSchema]] = {}
    for cite in citations_data:
        cid = str(cite["claim_id"])
        citations_by_claim.setdefault(cid, []).append(CitationSchema(
            id=str(cite.get("id")),
            claim_id=cid,
            source_title=cite.get("source_title", ""),
            source_url=cite.get("source_url", ""),
            snippet=cite.get("snippet", "")
        ))

    overrides_by_claim: Dict[str, List[OverrideSchema]] = {}
    for ov in overrides_data:
        cid = str(ov["claim_id"])
        overrides_by_claim.setdefault(cid, []).append(OverrideSchema(
            id=str(ov.get("id")),
            claim_id=cid,
            note=ov.get("note", ""),
            created_at=ov.get("created_at")
        ))

    claims_list: List[ClaimSchema] = []
    for c in claims_data:
        cid = str(c["id"])
        claims_list.append(ClaimSchema(
            id=cid,
            run_id=run_id,
            claim_text=c.get("claim_text", ""),
            confidence=int(c.get("confidence", 0)),
            citations=citations_by_claim.get(cid, []),
            overrides=overrides_by_claim.get(cid, [])
        ))

    trace_steps_list: List[TraceStepSchema] = []
    found_answer = direct_answer
    for t in traces_data:
        trace_steps_list.append(TraceStepSchema(
            id=str(t.get("id")),
            run_id=run_id,
            step_order=int(t.get("step_order", 0)),
            action=t.get("action", ""),
            detail=t.get("detail", "")
        ))
        if t.get("action") == "composer" and not found_answer:
            found_answer = t.get("detail")

    return RunResponse(
        id=str(run_data["id"]),
        question=run_data.get("question", ""),
        status=run_data.get("status", "unknown"),
        created_at=run_data.get("created_at"),
        answer=found_answer,
        trace_steps=trace_steps_list,
        claims=claims_list
    )


@app.post("/claims/{claim_id}/override", tags=["Receipts Pipeline"])
async def override_claim(claim_id: str, payload: OverrideRequest):
    """Stores a human or audit override note for a specific claim."""
    note = payload.note.strip()
    try:
        created_override = await db_insert("overrides", {
            "claim_id": claim_id,
            "note": note
        })
        return {
            "status": "success",
            "message": "Override note successfully recorded.",
            "override": created_override
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record override: {exc}"
        )


# ==============================================================================
# Main Entry Point
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
