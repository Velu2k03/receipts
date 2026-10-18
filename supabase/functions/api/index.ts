// Receipts API as a Supabase Edge Function (Deno + TypeScript).
// Mirrors the FastAPI backend: POST /ask, GET /runs/:id,
// POST /claims/:id/override, GET /health.
/// <reference lib="deno.ns" />

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.3";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_KEY = Deno.env.get("SUPABASE_ANON_KEY") ?? Deno.env.get("SUPABASE_KEY") ?? "";
const GEMINI_API_KEY = Deno.env.get("GEMINI_API_KEY") ?? "";
const GEMINI_MODEL = "gemini-3.1-flash-lite";

const supabase = createClient(SUPABASE_URL, SUPABASE_KEY);

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Gemini helper (REST, JSON mode, with timeout)
// ---------------------------------------------------------------------------
export async function geminiJson(prompt: string, timeoutMs = 30000): Promise<any> {
  const delays = [5000, 15000];
  let lastErr: unknown = null;
  for (let attempt = 0; attempt <= delays.length; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig: { responseMimeType: "application/json" },
          }),
          signal: ctrl.signal,
        }
      );
      if ((res.status === 429 || res.status === 503) && attempt < delays.length) {
        lastErr = new Error(`Gemini HTTP ${res.status}`);
        await new Promise((r) => setTimeout(r, delays[attempt]));
        continue;
      }
      if (!res.ok) throw new Error(`Gemini HTTP ${res.status}`);
      const data = await res.json();
      let text: string = data.candidates?.[0]?.content?.parts?.[0]?.text ?? "";
      text = text.trim();
      if (text.startsWith("```")) {
        text = text.replace(/^```(json)?/, "").replace(/```$/, "").trim();
      }
      return JSON.parse(text);
    } catch (e) {
      lastErr = e;
      const msg = String(e);
      if ((msg.includes("429") || msg.includes("503")) && attempt < delays.length) {
        await new Promise((r) => setTimeout(r, delays[attempt]));
        continue;
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastErr;
}

// ---------------------------------------------------------------------------
// Tavily web search (AI-optimized search API)
// ---------------------------------------------------------------------------
type SearchResult = { title: string; href: string; body: string };

function stripTags(s: string): string {
  return s.replace(/<[^>]*>/g, "").replace(/&amp;/g, "&").replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").trim();
}

export async function searchTavily(query: string, maxResults = 8, timeoutMs = 15000): Promise<SearchResult[]> {
  const apiKey = Deno.env.get("TAVILY_API_KEY");
  if (!apiKey) {
    console.error("[Tavily] TAVILY_API_KEY environment variable is missing");
    return [];
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);

  try {
    const res = await fetch("https://api.tavily.com/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        api_key: apiKey,
        query,
        search_depth: "advanced",
        max_results: maxResults,
        include_answer: false,
        include_raw_content: false,
      }),
      signal: ctrl.signal,
    });

    if (!res.ok) {
      const errText = await res.text().catch(() => "");
      console.error("[Tavily]", query, `HTTP ${res.status}: ${errText}`.slice(0, 120));
      return [];
    }

    const data = await res.json();
    const results = Array.isArray(data?.results) ? data.results : [];

    return results
      .filter((r: { url?: string }) => Boolean(r?.url))
      .map((r: { title?: string; url: string; content?: string }) => ({
        title: r.title || "Web Source",
        href: r.url,
        body: r.content || "",
      }));
  } catch (e) {
    console.error("[Tavily]", query, String(e).slice(0, 120));
    return [];
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// DB helpers
// ---------------------------------------------------------------------------
async function dbInsert(table: string, data: Record<string, unknown>) {
  const { data: row, error } = await supabase.from(table).insert(data).select().single();
  if (error) throw new Error(`${table} insert: ${error.message}`);
  return row;
}

async function recordTrace(runId: string, stepOrder: number, action: string, detail: string) {
  try {
    await dbInsert("trace_steps", {
      run_id: runId,
      step_order: stepOrder,
      action,
      detail: (detail || "").slice(0, 4000),
    });
  } catch (e) {
    console.error("[trace]", stepOrder, action, String(e).slice(0, 120));
  }
}

// ---------------------------------------------------------------------------
// GET /runs/:id — assemble full run payload
// ---------------------------------------------------------------------------
async function getRunDetails(runId: string, directAnswer?: string) {
  const { data: run, error: runErr } = await supabase.from("runs").select("*").eq("id", runId).single();
  if (runErr || !run) return json({ detail: `Run ${runId} not found` }, 404);

  const [{ data: traces }, { data: claimsRows }] = await Promise.all([
    supabase.from("trace_steps").select("*").eq("run_id", runId).order("step_order"),
    supabase.from("claims").select("*").eq("run_id", runId),
  ]);

  const claimIds = (claimsRows ?? []).map((c: any) => c.id);
  let citationsRows: any[] = [];
  let overridesRows: any[] = [];
  if (claimIds.length > 0) {
    const [cits, ovs] = await Promise.all([
      supabase.from("citations").select("*").in("claim_id", claimIds),
      supabase.from("overrides").select("*").in("claim_id", claimIds),
    ]);
    citationsRows = cits.data ?? [];
    overridesRows = ovs.data ?? [];
  }

  const byClaim = (rows: any[]) => {
    const map: Record<string, any[]> = {};
    for (const r of rows) {
      const cid = String(r.claim_id);
      (map[cid] = map[cid] || []).push(r);
    }
    return map;
  };
  const citsByClaim = byClaim(citationsRows);
  const ovsByClaim = byClaim(overridesRows);

  const claims = (claimsRows ?? []).map((c: any) => {
    const cid = String(c.id);
    return {
      id: cid,
      run_id: runId,
      claim_text: c.claim_text,
      confidence: c.confidence,
      citations: (citsByClaim[cid] ?? []).map((s: any) => ({
        id: String(s.id),
        claim_id: cid,
        source_title: s.source_title,
        source_url: s.source_url,
        snippet: s.snippet,
      })),
      overrides: (ovsByClaim[cid] ?? []).map((o: any) => ({
        id: String(o.id),
        claim_id: cid,
        note: o.note,
        created_at: o.created_at,
      })),
    };
  });

  let answer = directAnswer;
  const steps = (traces ?? []).map((t: any) => {
    if (t.action === "composer" && !answer) answer = t.detail;
    return {
      id: String(t.id),
      run_id: runId,
      step_order: t.step_order,
      action: t.action,
      detail: t.detail,
    };
  });

  return json({
    id: String(run.id),
    question: run.question,
    status: run.status,
    created_at: run.created_at,
    answer: answer ?? null,
    trace_steps: steps,
    claims,
  });
}

// ---------------------------------------------------------------------------
// POST /ask — the 8-stage evidence pipeline
// ---------------------------------------------------------------------------
async function handleAsk(question: string) {
  question = question.trim();
  let runId: string;
  try {
    const row = await dbInsert("runs", { question, status: "running" });
    runId = String(row.id);
  } catch (e) {
    return json({ detail: `Failed to initialize run: ${String(e).slice(0, 200)}` }, 500);
  }

  let step = 1;
  await recordTrace(runId, step++, "init", `Run initialized for question: '${question}'`);

  // (2) Planner
  let subQuestions: string[] = [];
  try {
    const plan = await geminiJson(
      `You are the research planner for Receipts, an evidence-first question-answering system.

Given the user's primary question, generate EXACTLY 3 distinct web-search questions that together gather reliable evidence needed to answer it.

Requirements:
- Each question must be independently searchable and focused on a specific factual issue.
- Cover complementary angles, not three paraphrases of the same question.
- Prefer concrete, search-friendly wording with relevant keywords and established terminology.
- Investigate: (a) direct evidence for the main claim, (b) evidence quality, limitations, or conflicting findings, (c) conditions or factors that change the answer.
- Do not assume the user's premise is true. Search for evidence that could support or contradict it.
- Avoid vague phrases like 'tell me about' and unnecessary multi-part questions.
- Do not answer the user's question. Generate search queries only.

Return valid JSON with this exact structure:
{ "sub_questions": ["question 1", "question 2", "question 3"] }

User question: "${question}"`,
      60000
    );
    subQuestions = (plan.sub_questions ?? []).slice(0, 3);
  } catch (e) {
    console.error("[planner]", String(e).slice(0, 120));
  }
  while (subQuestions.length < 3) subQuestions.push(`${question} aspect ${subQuestions.length + 1}`);
  await recordTrace(runId, step++, "planner", `Generated 3 sub-questions: ${JSON.stringify(subQuestions)}`);

  // (3) Searcher
  const settled = await Promise.allSettled(subQuestions.map((q) => searchTavily(q)));
  const batches: SearchResult[][] = [];
  settled.forEach((outcome, index) => {
    if (outcome.status === "fulfilled") {
      batches.push(outcome.value);
    } else {
      console.error("[search] rejected", index, String(outcome.reason).slice(0, 200));
      batches.push([]);
    }
  });
  const seen = new Set<string>();
  const allResults: SearchResult[] = [];
  for (const b of batches) {
    for (const r of b) {
      if (r.href && !seen.has(r.href)) {
        seen.add(r.href);
        allResults.push(r);
      }
    }
  }
  await recordTrace(runId, step++, "searcher",
    `Collected ${allResults.length} distinct web sources across ${subQuestions.length} sub-questions.`);

  // Edge case: no search results
  if (allResults.length === 0) {
    const honest = "Evidence was insufficient to provide a verified answer to this question.";
    const claimRow = await dbInsert("claims", {
      run_id: runId,
      claim_text: "Insufficient evidence was found on the web to substantiate any factual claims.",
      confidence: 0,
    });
    await supabase.from("runs").update({ status: "done" }).eq("id", runId);
    await recordTrace(runId, step++, "composer", honest);
    return getRunDetails(runId, honest).then(async (resp) => {
      void claimRow;
      return resp;
    });
  }

  // (4,5,6) Extractor / Linker / Scorer
  const compact = allResults.slice(0, 24).map((r, i) => ({
    source_id: i + 1, title: r.title, url: r.href, snippet: r.body,
  }));
  let extracted: any[] = [];
  try {
    const res = await geminiJson(
      `You are the evidence extraction component of Receipts, an evidence-first research system.

Extract up to 6 distinct, atomic factual claims that directly help answer the user's question, using ONLY the supplied search results.

Evidence rules:
- Extract a claim only when the supplied source text supports it.
- Return FEWER than 6 claims when the evidence is limited. Two strong claims beat zero claims. Returning zero claims is appropriate ONLY when no useful factual claim can be verified from the supplied material.
- Each claim must express one factual proposition.
- Each claim must have 1 to 3 citations. ONE strong citation is sufficient for a narrowly scoped claim.
- Each citation: {source_title, source_url, snippet} where snippet is an EXACT verbatim quote copied from the source's supplied snippet text.
- Never invent quotes, URLs, statistics, or source details.
- A snippet is evidence only for what it actually says. Do not infer beyond it.
- Include conflicting or qualifying evidence when it changes the interpretation.
- Assign confidence 0-100 based on strength of the supplied evidence, not plausibility.
- Do not answer from prior knowledge.

Return valid JSON:
{ "claims": [ { "claim_text": "...", "confidence": 85, "citations": [ { "source_title": "...", "source_url": "...", "snippet": "..." } ] } ] }

User question: "${question}"

Supplied sources:
${JSON.stringify(compact)}`,
      40000
    );
    extracted = (res.claims ?? []).slice(0, 6);
  } catch (e) {
    console.error("[extractor]", String(e).slice(0, 150));
  }
  if (extracted.length === 0) {
    extracted = [{
      claim_text: "Web search returned documents, but no verifiable atomic claims could be derived.",
      confidence: 10,
      citations: [],
    }];
  }
  await recordTrace(runId, step++, "extractor_scorer",
    `Extracted ${extracted.length} atomic claims with citations and confidence scores.`);

  // (7) Storage
  for (const c of extracted) {
    const claimText = String(c.claim_text ?? "").trim();
    const confidence = Math.max(0, Math.min(100, parseInt(c.confidence ?? 50, 10) || 50));
    const claimRow = await dbInsert("claims", { run_id: runId, claim_text: claimText, confidence });
    for (const s of (c.citations ?? []).slice(0, 3)) {
      await dbInsert("citations", {
        claim_id: claimRow.id,
        source_title: s.source_title ?? "Web Source",
        source_url: s.source_url ?? "",
        snippet: s.snippet ?? "",
      });
    }
  }
  await recordTrace(runId, step++, "storage", `Stored ${extracted.length} claims and citations.`);

  // (8) Composer
  let answer = "";
  try {
    const comp = await geminiJson(
      `You are the final synthesizer for 'Receipts'. Write a concise, 2 to 3 sentence direct answer to the user's question, relying ONLY on the verified factual claims below.\n\nQuestion: "${question}"\nVerified Claims:\n${JSON.stringify(extracted.map((c: any) => c.claim_text))}\n\nReturn JSON:\n{ "answer": "2 to 3 sentences answering the question directly." }`,
      15000
    );
    answer = String(comp.answer ?? "").trim();
  } catch (e) {
    console.error("[composer]", String(e).slice(0, 120));
    answer = extracted.slice(0, 2).map((c: any) => c.claim_text).join(" ");
  }

  await supabase.from("runs").update({ status: "done" }).eq("id", runId);
  await recordTrace(runId, step++, "composer", answer);

  return getRunDetails(runId, answer);
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
if (import.meta.main) {
Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const url = new URL(req.url);
  let path = url.pathname;
  // Supabase gateways differ: strip whichever function prefix is present.
  for (const prefix of ["/functions/v1/api", "/api"]) {
    if (path === prefix || path.startsWith(prefix + "/")) {
      path = path.slice(prefix.length) || "/";
      break;
    }
  }
  console.log(req.method, path);

  try {
    if (path === "/health" && req.method === "GET") {
      return json({ status: "ok" });
    }

    if (path === "/ask" && req.method === "POST") {
      const body = await req.json().catch(() => ({}));
      const question = String(body.question ?? "");
      if (question.trim().length < 2) return json({ detail: "question is required" }, 400);
      return await handleAsk(question);
    }

    const runMatch = path.match(/^\/runs\/([^/]+)$/);
    if (runMatch && req.method === "GET") {
      return await getRunDetails(runMatch[1]);
    }

    const ovMatch = path.match(/^\/claims\/([^/]+)\/override$/);
    if (ovMatch && req.method === "POST") {
      const body = await req.json().catch(() => ({}));
      const note = String(body.note ?? "").trim();
      if (!note) return json({ detail: "note is required" }, 400);
      try {
        const row = await dbInsert("overrides", { claim_id: ovMatch[1], note });
        return json({ status: "success", message: "Override note successfully recorded.", override: row });
      } catch (e) {
        return json({ detail: `Failed to record override: ${String(e).slice(0, 200)}` }, 500);
      }
    }

    return json({ detail: "not found" }, 404);
  } catch (e) {
    console.error("[unhandled]", String(e).slice(0, 200));
    return json({ detail: "internal error" }, 500);
  }
});
}
