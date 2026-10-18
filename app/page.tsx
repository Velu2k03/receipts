'use client'

import { useState } from 'react'
import {
  Activity, AlertTriangle, ArrowUpRight, Check, ChevronDown, ChevronRight,
  FileSearch, LayoutDashboard, Loader2, Menu, Search, Sparkles, SquareStack, X,
} from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type Citation = { id?: string; source_title: string; source_url: string; snippet: string; domain: string; color: string }
type Claim = { id: string; claim_text: string; confidence: number; citations: Citation[]; overridden?: boolean }
type TraceStep = { step_order: number; action: string; detail: string; time: string }
const DOMAIN_COLORS = ['bg-sky-400', 'bg-emerald-400', 'bg-violet-400', 'bg-amber-400', 'bg-cyan-400', 'bg-rose-400']
function domainOf(url: string) { try { return new URL(url.startsWith('http') ? url : `https://${url}`).hostname.replace(/^www\./, '') } catch { return url.split('/')[0] } }
function colorFor(index: number) { return DOMAIN_COLORS[index % DOMAIN_COLORS.length] }

const DEMO_CLAIMS: Claim[] = [
  { id: 'demo-1', claim_text: 'Standing desks can improve comfort and reduce sedentary time, but evidence for a direct productivity boost is mixed.', confidence: 87, citations: [
    { source_title: 'Effects of a Workplace Sit-Stand Desk Intervention on Health and Productivity', source_url: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC8582919/', snippet: 'A workplace intervention study examining health and productivity outcomes of sit-stand desk use.', domain: 'pmc.ncbi.nlm.nih.gov', color: 'bg-sky-400' },
    { source_title: 'Standing Desks Linked to Increased Productivity', source_url: 'https://www.asid.org/news/new-study-use-of-standing-desks-in-workplace-linked-to-increased-productivity-improved-health', snippet: 'Industry reporting on a study linking standing desk use to productivity and health improvements.', domain: 'asid.org', color: 'bg-emerald-400' },
  ] },
  { id: 'demo-2', claim_text: 'Short-term use does not appear to harm typing speed, cognitive performance, or task accuracy.', confidence: 94, citations: [{ source_title: 'Do Standing Desks Increase Productivity? Evidence and Tips', source_url: 'https://updowndesk.com.au/blogs/news/standing-desk-productivity', snippet: 'An evidence review of standing desk research including effects on typing and focus.', domain: 'updowndesk.com.au', color: 'bg-violet-400' }] },
  { id: 'demo-3', claim_text: 'The most reliable benefit comes from alternating between sitting and standing, rather than standing continuously.', confidence: 76, citations: [{ source_title: 'Proof Standing Desks Make You More Productive', source_url: 'https://www.businessinsider.com/proof-standing-desks-you-more-productive-2013-9', snippet: 'Early reporting on research into standing desks and work performance.', domain: 'businessinsider.com', color: 'bg-amber-400' }] },
]
const DEMO_TRACE: TraceStep[] = [
  { step_order: 1, action: 'Interpreted question', detail: 'Productivity, health, and time horizon', time: '' },
  { step_order: 2, action: 'Planned 3 sub-questions', detail: 'Performance · Comfort · Best practice', time: '' },
  { step_order: 3, action: 'Searched 12 sources', detail: 'Academic research and workplace guidance', time: '' },
  { step_order: 4, action: 'Extracted 9 candidate claims', detail: 'Ranked by evidence quality and relevance', time: '' },
  { step_order: 5, action: 'Verified 3 claims', detail: 'Cross-checked against 4 independent sources', time: '' },
]
const STAGE_MESSAGES = ['Planning sub-questions…', 'Searching sources…', 'Extracting claims…', 'Scoring confidence…', 'Composing answer…']
const TRACE_ICONS = [Sparkles, SquareStack, Search, FileSearch, Check]

function Favicon({ color }: { color: string }) { return <span className={`grid size-6 shrink-0 place-items-center rounded-md ${color} text-[10px] font-black text-slate-950`}><ArrowUpRight size={13} /></span> }

type Verdict = 'neutral' | 'right' | 'flagged'

export default function Page() {
  const [question, setQuestion] = useState('Do standing desks actually improve productivity?')
  const [claims, setClaims] = useState<Claim[]>(DEMO_CLAIMS), [trace, setTrace] = useState<TraceStep[]>(DEMO_TRACE)
  const [answer, setAnswer] = useState<string | null>(null), [expanded, setExpanded] = useState<string | null>('demo-1')
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({}), [flagNote, setFlagNote] = useState<string | null>(null), [noteText, setNoteText] = useState('')
  const [menuOpen, setMenuOpen] = useState(false), [running, setRunning] = useState(false), [stage, setStage] = useState(0), [error, setError] = useState<string | null>(null), [traceOpen, setTraceOpen] = useState(false)

  async function runAgent() {
    if (!question.trim() || running) return
    setRunning(true); setError(null); setAnswer(null); setVerdicts({}); setFlagNote(null); setNoteText('')
    const timer = setInterval(() => setStage((s) => Math.min(s + 1, STAGE_MESSAGES.length - 1)), 9000)
    try {
      const res = await fetch(`${API_URL}/ask`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: question.trim() }) })
      if (!res.ok) throw new Error(`Backend returned ${res.status}`)
      const run = await res.json()
      const nextClaims: Claim[] = (run.claims || []).map((c: any, i: number) => ({ id: String(c.id ?? `claim-${i}`), claim_text: c.claim_text, confidence: c.confidence, citations: (c.citations || []).map((s: any, j: number) => ({ id: s.id, source_title: s.source_title, source_url: s.source_url, snippet: s.snippet, domain: domainOf(s.source_url), color: colorFor(j) })) }))
      setClaims(nextClaims); setTrace((run.trace_steps || []).map((t: any) => ({ step_order: t.step_order, action: t.action, detail: (t.detail || '').slice(0, 120), time: '' }))); setAnswer(run.answer || null); setExpanded(nextClaims[0]?.id ?? null)
    } catch { setError('Could not reach the agent backend. Please try again.') } finally { clearInterval(timer); setRunning(false); setStage(0) }
  }
  function setVerdict(claimId: string, verdict: Verdict) {
    setVerdicts((current) => ({ ...current, [claimId]: current[claimId] === verdict ? 'neutral' : verdict }))
    if (verdict === 'right' || verdict === 'neutral') { setFlagNote(null); setNoteText('') }
  }
  async function submitFlag(claimId: string) {
    setVerdict(claimId, 'flagged'); setFlagNote(null); const note = noteText.trim() || 'Flagged for review'; setNoteText('')
    try { await fetch(`${API_URL}/claims/${claimId}/override`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }) }) } catch { /* demo claims have no backend id */ }
  }
  return <main className="min-h-screen bg-[#070b12] text-slate-100 selection:bg-[#FFC107] selection:text-slate-950"><div className="flex min-h-screen">
    <aside className={`${menuOpen ? 'translate-x-0' : '-translate-x-full'} fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-white/[0.07] bg-[#0a0f18] px-5 py-6 transition-transform md:static md:translate-x-0`}>
      <div className="flex items-center justify-between"><div className="flex items-center gap-2.5"><div className="grid size-8 place-items-center rounded-lg bg-[#FFC107] text-slate-950"><Activity size={18} strokeWidth={2.8} /></div><span className="text-lg font-bold tracking-tight">Receipts<span className="text-[#FFC107]">.</span></span></div><button onClick={() => setMenuOpen(false)} className="text-slate-500 md:hidden" aria-label="Close navigation"><X /></button></div>
      <p className="mt-7 max-w-[170px] text-xs leading-5 text-slate-500">Evidence for every answer.</p>
      <nav className="mt-10 flex flex-col gap-1"><button className="flex items-center gap-3 rounded-lg bg-[#FFC107]/10 px-3 py-2.5 text-sm font-medium text-[#FFC107]" aria-current="page"><LayoutDashboard size={17} />Dashboard</button></nav>
    </aside>{menuOpen && <button className="fixed inset-0 z-20 bg-black/60 md:hidden" onClick={() => setMenuOpen(false)} aria-label="Close navigation overlay" />}
    <section className="min-w-0 flex-1"><header className="flex h-16 items-center border-b border-white/[0.07] px-5 sm:px-8"><button onClick={() => setMenuOpen(true)} className="mr-3 text-slate-400 md:hidden" aria-label="Open navigation"><Menu /></button><p className="text-xs text-slate-500">Dashboard</p></header>
      <div className="mx-auto max-w-5xl px-5 py-12 sm:px-8 lg:py-20"><div className="max-w-3xl"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#FFC107]">Ask Receipts</p><h1 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-5xl">See what the answer stands on.</h1><div className="mt-8 flex items-center gap-2 rounded-xl border border-[#FFC107]/35 bg-[#0d131d] p-2 shadow-[0_0_0_1px_rgba(255,193,7,0.04)]"><Search className="ml-2 shrink-0 text-[#FFC107]" size={19} /><input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing && e.keyCode !== 229) runAgent() }} placeholder="Ask anything..." className="min-w-0 flex-1 bg-transparent px-2 py-3 text-sm text-slate-100 outline-none placeholder:text-slate-600" /><button onClick={runAgent} disabled={running} className="rounded-lg bg-[#FFC107] px-4 py-2.5 text-xs font-bold text-slate-950 hover:bg-[#ffd34d] disabled:opacity-60">{running ? <Loader2 size={14} className="animate-spin" /> : <>Ask <ArrowUpRight size={13} className="ml-1 inline" /></>}</button></div>{running && <div className="mt-3 flex items-center gap-2 text-xs text-cyan-300"><Loader2 size={13} className="animate-spin" />{STAGE_MESSAGES[stage]}</div>}{error && <div className="mt-3 text-xs text-rose-300">{error}</div>}{answer && <p className="mt-8 text-base leading-7 text-slate-300">{answer}</p>}</div>
        <div className="mt-16 max-w-3xl"><div className="flex items-end justify-between border-b border-white/[0.07] pb-4"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Claims</p><p className="mt-2 text-sm text-slate-500">{claims.length} claims · {claims.reduce((a, c) => a + c.citations.length, 0)} sources</p></div></div><div className="mt-5 flex flex-col gap-3">{claims.map((claim) => <ClaimCard key={claim.id} claim={claim} expanded={expanded === claim.id} onToggle={() => setExpanded(expanded === claim.id ? null : claim.id)} verdict={verdicts[claim.id] || 'neutral'} onRight={() => setVerdict(claim.id, 'right')} onFlag={() => setFlagNote(flagNote === claim.id ? null : claim.id)} noteOpen={flagNote === claim.id} noteText={noteText} setNoteText={setNoteText} onSubmitNote={() => submitFlag(claim.id)} />)}</div></div>
        <TracePanel steps={trace} running={running} stageMessage={STAGE_MESSAGES[stage]} open={traceOpen} onToggle={() => setTraceOpen(!traceOpen)} />
      </div></section></div></main>
}

function ClaimCard({ claim, expanded, onToggle, verdict, onRight, onFlag, noteOpen, noteText, setNoteText, onSubmitNote }: { claim: Claim; expanded: boolean; onToggle: () => void; verdict: Verdict; onRight: () => void; onFlag: () => void; noteOpen: boolean; noteText: string; setNoteText: (s: string) => void; onSubmitNote: () => void }) {
  return <article className={`rounded-xl border bg-[#0b111b] transition ${expanded ? 'border-cyan-300/25' : 'border-white/[0.07]'}`}><button onClick={onToggle} className="flex w-full items-start gap-4 p-5 text-left sm:p-6"><span className={`mt-1 grid size-6 shrink-0 place-items-center rounded-md text-xs font-bold ${expanded ? 'bg-cyan-300 text-slate-950' : 'bg-white/[0.07] text-slate-500'}`}>{claim.id.startsWith('demo') ? claim.id.replace('demo-', '') : '•'}</span><span className="min-w-0 flex-1 text-base font-medium leading-7 text-slate-100 sm:text-lg">{claim.claim_text}</span><span className="flex shrink-0 items-center gap-2 pt-1 text-xs font-bold text-cyan-300"><span>{claim.confidence}%</span><span className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-white/10 sm:block"><span className="block h-full rounded-full bg-cyan-300" style={{ width: `${claim.confidence}%` }} /></span>{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span></button>{expanded && <div className="border-t border-white/[0.06] px-5 pb-5 pt-5 sm:px-6"><div className="flex flex-col gap-2">{claim.citations.map((citation, i) => <div key={`${citation.source_url}-${i}`} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3"><div className="flex gap-3"><Favicon color={citation.color} /><div className="min-w-0"><p className="text-xs font-semibold text-slate-200">{citation.source_title}</p><a href={citation.source_url} target="_blank" rel="noreferrer" className="mt-1 block truncate text-[11px] text-slate-600 hover:text-cyan-300">{citation.domain} · {citation.source_url}</a><p className="mt-3 border-l-2 border-[#FFC107]/60 pl-3 text-xs leading-5 text-slate-400">“{citation.snippet}”</p></div></div></div>)}</div><div className="mt-4 flex flex-wrap items-center gap-2"><button onClick={onRight} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium ${verdict === 'right' ? 'border-emerald-400/50 bg-emerald-400/10 text-emerald-300' : 'border-emerald-400/20 text-emerald-300'}`}><Check size={13} />Looks right</button><button onClick={onFlag} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium ${verdict === 'flagged' ? 'border-rose-400/50 bg-rose-400/10 text-rose-300' : 'border-rose-400/20 text-rose-300'}`}><AlertTriangle size={13} />{verdict === 'flagged' ? 'Unflag' : 'Flag'}</button></div>{noteOpen && verdict !== 'flagged' && <div className="mt-3 flex gap-2"><input autoFocus value={noteText} onChange={(e) => setNoteText(e.target.value)} placeholder="What should be checked?" className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/20 px-3 py-2 text-xs text-slate-200 outline-none focus:border-rose-300/50" /><button onClick={onSubmitNote} className="rounded-md bg-rose-400/15 px-3 py-2 text-xs font-semibold text-rose-200">Save flag</button></div>}</div>}</article>
}

function TracePanel({ steps, running, stageMessage, open, onToggle }: { steps: TraceStep[]; running: boolean; stageMessage: string; open: boolean; onToggle: () => void }) {
  return <section className="mt-14 max-w-3xl rounded-xl border border-white/[0.07] bg-[#0b111b]"><button onClick={onToggle} className="flex w-full items-center gap-3 px-5 py-4 text-left"><span className="grid size-7 place-items-center rounded-lg border border-white/10 text-cyan-300"><FileSearch size={14} /></span><span className="flex-1"><span className="block text-sm font-semibold text-slate-200">How it found this</span><span className="mt-1 block text-xs text-slate-600">{running ? stageMessage : `${steps.length} steps`}</span></span>{open ? <ChevronDown size={17} className="text-slate-500" /> : <ChevronRight size={17} className="text-slate-500" />}</button>{open && <div className="border-t border-white/[0.06] px-5 py-5"><div className="flex flex-col gap-4">{steps.map((step, index) => { const Icon = TRACE_ICONS[index % TRACE_ICONS.length]; return <div key={`${step.step_order}-${index}`} className="flex gap-3"><div className="grid size-7 shrink-0 place-items-center rounded-lg border border-white/10 bg-[#0b111b]"><Icon size={14} className={index === 0 ? 'text-[#FFC107]' : 'text-cyan-300'} /></div><div><p className="text-sm text-slate-300">{step.action}</p><p className="mt-1 text-xs text-slate-600">{step.detail}</p></div></div>})}</div></div>}</section>
}
