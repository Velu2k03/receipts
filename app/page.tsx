'use client'

import { useEffect, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  FileSearch,
  Gauge,
  LayoutDashboard,
  Loader2,
  Menu,
  Search,
  Sparkles,
  SquareStack,
  Timer,
  X,
} from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type Citation = {
  id?: string
  source_title: string
  source_url: string
  snippet: string
  domain: string
  color: string
}

type Claim = {
  id: string
  claim_text: string
  confidence: number
  citations: Citation[]
}

type TraceStep = {
  step_order: number
  action: string
  detail: string
  time: string
}

const DOMAIN_COLORS = ['bg-sky-400', 'bg-emerald-400', 'bg-violet-400', 'bg-amber-400', 'bg-cyan-400', 'bg-rose-400']

function domainOf(url: string): string {
  try {
    return new URL(url.startsWith('http') ? url : `https://${url}`).hostname.replace(/^www\./, '')
  } catch {
    return url.split('/')[0]
  }
}

function colorFor(index: number): string {
  return DOMAIN_COLORS[index % DOMAIN_COLORS.length]
}

// Plain-words labels for the agent's internal step names
function plainStep(action: string): string {
  const map: Record<string, string> = {
    init: 'Got your question',
    planner: 'Broke it into smaller questions',
    searcher: 'Searched the web',
    extractor_scorer: 'Pulled out key findings',
    storage: 'Saved the evidence',
    composer: 'Wrote the answer',
  }
  return map[action] ?? action.replace(/_/g, ' ')
}

const EXAMPLE_CLAIMS: Claim[] = [
  {
    id: 'demo-1',
    claim_text: 'Standing desks can improve comfort and reduce sitting time, but the evidence for a direct productivity boost is mixed.',
    confidence: 87,
    citations: [
      { source_title: 'Sit-Stand Desks and Workplace Health', source_url: 'ncbi.nlm.nih.gov/pmc/articles/PMC6224419', snippet: 'Sit-stand desk interventions were associated with reduced sitting time and improvements in musculoskeletal discomfort.', domain: 'nih.gov', color: 'bg-sky-400' },
      { source_title: 'The impact of sit-stand desks on work performance', source_url: 'cochranelibrary.com/cdsr/doi/10.1002/14651858', snippet: 'There is low-certainty evidence that sit-stand desks have little to no effect on work performance outcomes.', domain: 'cochranelibrary.com', color: 'bg-emerald-400' },
    ],
  },
  {
    id: 'demo-2',
    claim_text: 'Short-term use of a standing desk does not appear to harm typing speed or thinking performance.',
    confidence: 94,
    citations: [
      { source_title: 'Stand Up to Work: A Randomized Trial', source_url: 'jmir.org/2020/4/e16704', snippet: 'There were no significant differences in typing speed, cognitive function, or task accuracy between the groups.', domain: 'jmir.org', color: 'bg-violet-400' },
    ],
  },
  {
    id: 'demo-3',
    claim_text: 'The most reliable benefit comes from alternating between sitting and standing, not standing all day.',
    confidence: 76,
    citations: [
      { source_title: 'Ergonomics and the Sit-Stand Workstation', source_url: 'osha.gov/ergonomics/stand-sit-workstations', snippet: 'Workers should be encouraged to change posture frequently and avoid prolonged periods in either a seated or standing position.', domain: 'osha.gov', color: 'bg-amber-400' },
    ],
  },
]

const EXAMPLE_TRACE: TraceStep[] = [
  { step_order: 1, action: 'init', detail: 'Question understood', time: '' },
  { step_order: 2, action: 'planner', detail: 'Made 3 smaller questions to search', time: '' },
  { step_order: 3, action: 'searcher', detail: 'Read 12 web pages', time: '' },
  { step_order: 4, action: 'extractor_scorer', detail: 'Picked the 3 best-supported findings', time: '' },
  { step_order: 5, action: 'composer', detail: 'Wrote the answer', time: '' },
]

const STAGE_MESSAGES = [
  'Breaking your question into smaller ones…',
  'Searching the web for sources…',
  'Pulling out the key findings…',
  'Checking each finding against its sources…',
  'Writing the answer…',
]

function Favicon({ color }: { color: string }) {
  return <span className={`grid size-6 shrink-0 place-items-center rounded-md ${color} text-[10px] font-black text-slate-950`}>↗</span>
}

const TRACE_ICONS = [Sparkles, SquareStack, Search, FileSearch, Check]

export default function Page() {
  const [question, setQuestion] = useState('')
  const [claims, setClaims] = useState<Claim[]>(EXAMPLE_CLAIMS)
  const [trace, setTrace] = useState<TraceStep[]>(EXAMPLE_TRACE)
  const [answer, setAnswer] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>('demo-1')
  const [looksRight, setLooksRight] = useState<string[]>([])
  const [flagged, setFlagged] = useState<string[]>([])
  const [flagNote, setFlagNote] = useState<string | null>(null)
  const [noteText, setNoteText] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [running, setRunning] = useState(false)
  const [stage, setStage] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [isLive, setIsLive] = useState(false)
  const [backendOk, setBackendOk] = useState<boolean | null>(null)

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => setBackendOk(r.ok))
      .catch(() => setBackendOk(false))
  }, [])

  async function runAgent() {
    if (!question.trim() || running) return
    setRunning(true)
    setError(null)
    setAnswer(null)
    const stageTimer = setInterval(() => setStage((s) => Math.min(s + 1, STAGE_MESSAGES.length - 1)), 9000)
    try {
      const res = await fetch(`${API_URL}/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question.trim() }),
      })
      if (!res.ok) throw new Error(`Backend returned ${res.status}`)
      const run = await res.json()
      const mappedClaims: Claim[] = (run.claims || []).map((c: any, i: number) => ({
        id: String(c.id ?? `claim-${i}`),
        claim_text: c.claim_text,
        confidence: c.confidence,
        citations: (c.citations || []).map((s: any, j: number) => ({
          id: s.id,
          source_title: s.source_title,
          source_url: s.source_url,
          snippet: s.snippet,
          domain: domainOf(s.source_url),
          color: colorFor(j),
        })),
      }))
      const mappedTrace: TraceStep[] = (run.trace_steps || []).map((t: any) => ({
        step_order: t.step_order,
        action: t.action,
        detail: (t.detail || '').slice(0, 120),
        time: new Date().toLocaleTimeString('en-GB'),
      }))
      setClaims(mappedClaims)
      setTrace(mappedTrace)
      setAnswer(run.answer || null)
      setExpanded(mappedClaims[0]?.id ?? null)
      setLooksRight([])
      setFlagged([])
      setIsLive(true)
      setBackendOk(true)
    } catch {
      setError('Could not reach the answer engine. Check your connection and try again.')
      setBackendOk(false)
    } finally {
      clearInterval(stageTimer)
      setRunning(false)
      setStage(0)
    }
  }

  function toggleLooksRight(claimId: string) {
    setLooksRight((v) => (v.includes(claimId) ? v.filter((id) => id !== claimId) : [...v, claimId]))
    setFlagged((v) => v.filter((id) => id !== claimId))
    if (flagNote === claimId) { setFlagNote(null); setNoteText('') }
  }

  async function submitFlag(claimId: string) {
    const note = noteText.trim() || 'Flagged for review'
    setFlagged((f) => (f.includes(claimId) ? f : [...f, claimId]))
    setLooksRight((v) => v.filter((id) => id !== claimId))
    setFlagNote(null)
    setNoteText('')
    if (!claimId.startsWith('demo')) {
      try {
        await fetch(`${API_URL}/claims/${claimId}/override`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note }),
        })
      } catch { /* ignore */ }
    }
  }

  function newQuestion() {
    setQuestion('')
    setError(null)
    setIsLive(false)
    setClaims(EXAMPLE_CLAIMS)
    setTrace(EXAMPLE_TRACE)
    setAnswer(null)
    setExpanded('demo-1')
  }

  function exportRun() {
    const data = JSON.stringify({ question: isLive ? question : 'Example', answer, claims, trace }, null, 2)
    const blob = new Blob([data], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'receipts-run.json'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const avgConfidence = claims.length
    ? Math.round(claims.reduce((a, c) => a + c.confidence, 0) / claims.length)
    : 0
  const sourceCount = claims.reduce((a, c) => a + c.citations.length, 0)

  return (
    <main className="min-h-screen bg-[#070b12] text-slate-100 selection:bg-[#FFC107] selection:text-slate-950">
      <div className="flex min-h-screen">
        <aside className={`${menuOpen ? 'translate-x-0' : '-translate-x-full'} fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-white/[0.07] bg-[#0a0f18] px-4 py-5 transition-transform md:static md:translate-x-0`}>
          <div className="flex items-center justify-between px-3">
            <div className="flex items-center gap-2.5"><div className="grid size-8 place-items-center rounded-lg bg-[#FFC107] text-slate-950"><Activity size={19} strokeWidth={2.8} /></div><span className="text-lg font-bold tracking-tight">Receipts<span className="text-[#FFC107]">.</span></span></div>
            <button onClick={() => setMenuOpen(false)} className="text-slate-500 md:hidden" aria-label="Close navigation"><X /></button>
          </div>
          <div className="mt-10 px-3 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-600">How it works</div>
          <div className="mt-3 flex flex-col gap-3 px-3">
            {[
              ['1. You ask', 'Type any question you want checked.'],
              ['2. It searches', 'The web is searched for real sources.'],
              ['3. You get proof', 'Every finding shows its sources and how sure it is.'],
            ].map(([title, body]) => (
              <div key={title} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
                <p className="text-xs font-bold text-[#FFC107]">{title}</p>
                <p className="mt-1 text-xs leading-5 text-slate-500">{body}</p>
              </div>
            ))}
          </div>
          <div className="mt-auto rounded-xl border border-cyan-300/10 bg-cyan-300/[0.04] p-4">
            <div className="flex items-center gap-2 text-xs font-semibold text-cyan-200"><Gauge size={15} /> Answer engine</div>
            <div className="mt-3 flex items-center gap-2">
              <span className={`size-2 rounded-full ${backendOk === false ? 'bg-rose-400 shadow-[0_0_8px_#fb7185]' : backendOk ? 'bg-emerald-400 shadow-[0_0_8px_#34d399]' : 'bg-slate-500'}`} />
              <span className="text-xs text-slate-400">{backendOk === null ? 'Checking…' : backendOk ? 'Connected' : 'Offline'}</span>
            </div>
          </div>
        </aside>
        {menuOpen && <button className="fixed inset-0 z-20 bg-black/60 md:hidden" onClick={() => setMenuOpen(false)} aria-label="Close navigation overlay" />}

        <section className="min-w-0 flex-1">
          <header className="flex h-16 items-center justify-between border-b border-white/[0.07] px-5 sm:px-8 lg:px-10">
            <div className="flex items-center gap-3">
              <button onClick={() => setMenuOpen(true)} className="text-slate-400 md:hidden" aria-label="Open navigation"><Menu /></button>
              <div><h1 className="text-sm font-semibold tracking-wide text-slate-200">Evidence for every answer</h1></div>
            </div>
            <div className="flex items-center gap-2">
              {isLive
                ? <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-1 text-[10px] font-bold text-emerald-300">LIVE ANSWER</span>
                : <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] font-bold text-slate-500">EXAMPLE</span>}
              <button onClick={exportRun} className="hidden rounded-lg border border-white/[0.08] px-3 py-2 text-xs text-slate-400 hover:border-white/20 sm:block">Save answer</button>
            </div>
          </header>

          <div className="mx-auto max-w-[1480px] px-5 py-7 sm:px-8 lg:px-10 lg:py-9">
            <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
              <div>
                <h2 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">Ask anything<span className="text-[#FFC107]">.</span></h2>
                <p className="mt-2 max-w-xl text-sm text-slate-500">Get an answer where every key finding shows its sources and how sure it is.</p>
              </div>
              <button onClick={newQuestion} className="flex items-center gap-2 self-start rounded-lg bg-[#FFC107] px-4 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-[#ffd34d] sm:self-auto"><Sparkles size={15} /> New question</button>
            </div>

            <div className="mt-7 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Metric label="Key findings" value={String(claims.length)} icon={CircleHelp} />
              <Metric label="Sources cited" value={String(sourceCount)} icon={FileSearch} />
              <Metric label="Average certainty" value={`${avgConfidence}%`} icon={Gauge} />
            </div>

            <div className="mt-7 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.65fr)]">
              <div className="min-w-0">
                <div className="flex items-center gap-2 rounded-xl border border-[#FFC107]/35 bg-[#0d131d] p-2">
                  <Search className="ml-2 shrink-0 text-[#FFC107]" size={18} />
                  <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && runAgent()} placeholder="Ask anything..." className="min-w-0 flex-1 bg-transparent px-2 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600" />
                  <button onClick={runAgent} disabled={running} className="rounded-lg bg-[#FFC107] px-3.5 py-2 text-xs font-bold text-slate-950 hover:bg-[#ffd34d] disabled:opacity-60">{running ? <Loader2 size={13} className="animate-spin" /> : <>Ask <ArrowUpRight size={13} className="ml-1 inline" /></>}</button>
                </div>
                {running && <div className="mt-3 flex items-center gap-2 text-xs text-cyan-300"><Loader2 size={13} className="animate-spin" />{STAGE_MESSAGES[stage]}</div>}
                {error && <div className="mt-3 rounded-lg border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs text-rose-300">{error}</div>}
                {answer && <div className="mt-5 rounded-xl border border-[#FFC107]/25 bg-[#FFC107]/[0.04] p-4"><p className="text-[10px] font-bold uppercase tracking-[0.15em] text-[#FFC107]">Answer in brief</p><p className="mt-2 text-sm leading-6 text-slate-200">{answer}</p></div>}

                <div className="mt-7"><p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Key findings</p><p className="mt-1 text-sm text-slate-300">{claims.length} findings <span className="text-slate-600">·</span> {sourceCount} sources</p></div>
                <div className="mt-4 flex flex-col gap-3">
                  {claims.map((claim) => (
                    <ClaimCard
                      key={claim.id}
                      claim={claim}
                      expanded={expanded === claim.id}
                      onToggle={() => setExpanded(expanded === claim.id ? null : claim.id)}
                      looksRight={looksRight.includes(claim.id)}
                      flagged={flagged.includes(claim.id)}
                      onLooksRight={() => toggleLooksRight(claim.id)}
                      onFlag={() => setFlagNote(flagNote === claim.id ? null : claim.id)}
                      noteOpen={flagNote === claim.id}
                      noteText={noteText}
                      setNoteText={setNoteText}
                      onSubmitNote={() => submitFlag(claim.id)}
                    />
                  ))}
                </div>
              </div>
              <TracePanel steps={trace} running={running} stageMessage={STAGE_MESSAGES[stage]} />
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}

function Metric({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Gauge }) {
  return <div className="rounded-xl border border-white/[0.07] bg-[#0b111b] p-4"><div className="flex items-center justify-between"><span className="text-xs text-slate-500">{label}</span><Icon size={16} className="text-cyan-300" /></div><div className="mt-2"><span className="text-2xl font-bold tracking-tight text-slate-100">{value}</span></div></div>
}

function ClaimCard({ claim, expanded, onToggle, looksRight, flagged, onLooksRight, onFlag, noteOpen, noteText, setNoteText, onSubmitNote }: {
  claim: Claim; expanded: boolean; onToggle: () => void;
  looksRight: boolean; flagged: boolean;
  onLooksRight: () => void; onFlag: () => void;
  noteOpen: boolean; noteText: string; setNoteText: (s: string) => void; onSubmitNote: () => void
}) {
  return <article className={`rounded-xl border bg-[#0b111b] transition ${expanded ? 'border-cyan-300/25' : 'border-white/[0.07]'}`}>
    <button onClick={onToggle} className="flex w-full items-start gap-3 p-4 text-left sm:p-5">
      <span className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-md text-xs font-bold ${expanded ? 'bg-cyan-300 text-slate-950' : 'bg-white/[0.07] text-slate-500'}`}>•</span>
      <span className="min-w-0 flex-1 text-sm font-medium leading-6 text-slate-200">{claim.claim_text}</span>
      <span className="flex shrink-0 items-center gap-2 text-xs font-bold text-cyan-300"><span className="hidden sm:inline">{claim.confidence}% sure</span><span className="h-1.5 w-12 overflow-hidden rounded-full bg-white/10 sm:w-16"><span className="block h-full rounded-full bg-cyan-300" style={{ width: `${claim.confidence}%` }} /></span>{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
    </button>
    {expanded && <div className="border-t border-white/[0.06] px-4 pb-4 pt-4 sm:px-5 sm:pb-5">
      <div className="mb-4 flex items-center justify-between"><span className="text-[10px] font-bold uppercase tracking-[0.15em] text-slate-600">Where this comes from</span><span className="text-xs text-slate-500"><strong className="text-cyan-300">{claim.confidence}%</strong> sure</span></div>
      <div className="flex flex-col gap-2">{claim.citations.map((citation, i) => <div key={`${citation.source_url}-${i}`} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3"><div className="flex gap-3"><Favicon color={citation.color} /><div className="min-w-0"><p className="text-xs font-semibold text-slate-200">{citation.source_title}</p><a href={citation.source_url.startsWith('http') ? citation.source_url : `https://${citation.source_url}`} target="_blank" rel="noreferrer" className="mt-1 block truncate text-[11px] text-slate-600 hover:text-cyan-300">{citation.domain}</a><p className="mt-3 border-l-2 border-[#FFC107]/60 pl-3 text-xs leading-5 text-slate-400">“{citation.snippet}”</p></div></div></div>)}</div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button onClick={onLooksRight} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium ${looksRight ? 'border-emerald-400/50 bg-emerald-400/10 text-emerald-300' : 'border-emerald-400/20 text-emerald-300 hover:bg-emerald-400/10'}`}><Check size={13} /> Looks right</button>
        <button onClick={onFlag} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium ${flagged ? 'border-[#FFC107]/50 bg-[#FFC107]/10 text-[#FFC107]' : 'border-white/10 text-slate-500 hover:border-[#FFC107]/40 hover:text-[#FFC107]'}`}><AlertTriangle size={13} /> {flagged ? 'Flagged — thanks' : 'Flag a problem'}</button>
        {noteOpen && <span className="flex min-w-[180px] flex-1 items-center gap-2"><input autoFocus value={noteText} onChange={(e) => setNoteText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && onSubmitNote()} placeholder="What looks wrong? (optional)" className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-slate-200 outline-none focus:border-[#FFC107]/50" /><button onClick={onSubmitNote} className="rounded-md bg-[#FFC107] px-2.5 py-1.5 text-xs font-bold text-slate-950">Send</button></span>}
      </div>
    </div>}
  </article>
}

function TracePanel({ steps, running, stageMessage }: { steps: TraceStep[]; running: boolean; stageMessage: string }) {
  return <aside className="h-fit rounded-xl border border-white/[0.07] bg-[#0b111b] xl:sticky xl:top-6">
    <div className="border-b border-white/[0.06] px-5 py-4"><p className="text-sm font-semibold text-slate-200">How it found this</p><p className="mt-1 text-xs text-slate-600">Each step, in order</p></div>
    <div className="p-5"><div className="relative flex flex-col gap-0">{steps.map((step, index) => { const Icon = TRACE_ICONS[index % TRACE_ICONS.length]; return <div key={`${step.step_order}-${index}`} className="relative flex gap-3 pb-6 last:pb-0"><div className="relative z-10 grid size-7 shrink-0 place-items-center rounded-lg border border-white/10 bg-[#0b111b]"><Icon size={14} className={index === 0 ? 'text-[#FFC107]' : 'text-cyan-300'} /></div>{index < steps.length - 1 && <div className="absolute left-[13px] top-7 h-[calc(100%-16px)] w-px bg-white/[0.08]" />}<div className="min-w-0 flex-1 pt-0.5"><p className="text-xs font-semibold text-slate-300">{plainStep(step.action)}</p>{step.detail && <p className="mt-1 text-[11px] leading-4 text-slate-600">{step.detail}</p>}{step.time && <p className="mt-0.5 text-[10px] text-slate-700">{step.time}</p>}</div></div> })}</div>{running && <div className="mt-2 flex items-center gap-2 border-t border-white/[0.06] pt-4 text-xs text-cyan-300"><Loader2 size={13} className="animate-spin" />{stageMessage}</div>}</div>
  </aside>
}
