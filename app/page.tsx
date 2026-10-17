'use client'

import { useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  FileSearch,
  Gauge,
  LayoutDashboard,
  Loader2,
  Menu,
  MoreHorizontal,
  Search,
  Settings,
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
  overridden?: boolean
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

// Demo data shown on first load (matches the v0 design)
const DEMO_CLAIMS: Claim[] = [
  {
    id: 'demo-1',
    claim_text: 'Standing desks can improve comfort and reduce sedentary time, but the evidence for a direct productivity boost is mixed.',
    confidence: 87,
    citations: [
      { source_title: 'Sit-Stand Desks and Workplace Health', source_url: 'ncbi.nlm.nih.gov/pmc/articles/PMC6224419', snippet: 'Sit-stand desk interventions were associated with reduced sitting time and improvements in musculoskeletal discomfort.', domain: 'nih.gov', color: 'bg-sky-400' },
      { source_title: 'The impact of sit-stand desks on work performance', source_url: 'cochranelibrary.com/cdsr/doi/10.1002/14651858', snippet: 'There is low-certainty evidence that sit-stand desks have little to no effect on work performance outcomes.', domain: 'cochranelibrary.com', color: 'bg-emerald-400' },
    ],
  },
  {
    id: 'demo-2',
    claim_text: 'Short-term use of a standing desk does not appear to harm typing speed, cognitive performance, or task accuracy.',
    confidence: 94,
    citations: [
      { source_title: 'Stand Up to Work: A Randomized Trial', source_url: 'jmir.org/2020/4/e16704', snippet: 'There were no significant differences in typing speed, cognitive function, or task accuracy between the groups.', domain: 'jmir.org', color: 'bg-violet-400' },
    ],
  },
  {
    id: 'demo-3',
    claim_text: 'The most reliable benefit comes from alternating between sitting and standing, rather than standing continuously.',
    confidence: 76,
    citations: [
      { source_title: 'Ergonomics and the Sit-Stand Workstation', source_url: 'osha.gov/ergonomics/stand-sit-workstations', snippet: 'Workers should be encouraged to change posture frequently and avoid prolonged periods in either a seated or standing position.', domain: 'osha.gov', color: 'bg-amber-400' },
    ],
  },
]

const DEMO_TRACE: TraceStep[] = [
  { step_order: 1, action: 'Interpreted question', detail: 'Productivity, health, and time horizon', time: '10:42:01' },
  { step_order: 2, action: 'Planned 3 sub-questions', detail: 'Performance · Comfort · Best practice', time: '10:42:02' },
  { step_order: 3, action: 'Searched 12 sources', detail: 'Academic research and workplace guidance', time: '10:42:04' },
  { step_order: 4, action: 'Extracted 9 candidate claims', detail: 'Ranked by evidence quality and relevance', time: '10:42:07' },
  { step_order: 5, action: 'Verified 3 claims', detail: 'Cross-checked against 4 independent sources', time: '10:42:09' },
]

const STAGE_MESSAGES = [
  'Planning sub-questions…',
  'Searching the web for sources…',
  'Extracting atomic claims…',
  'Linking citations and scoring confidence…',
  'Composing the answer…',
]

function Favicon({ color }: { color: string }) {
  return <span className={`grid size-6 shrink-0 place-items-center rounded-md ${color} text-[10px] font-black text-slate-950`}>↗</span>
}

const TRACE_ICONS = [Sparkles, SquareStack, Search, FileSearch, Check]

export default function Page() {
  const [active, setActive] = useState('Dashboard')
  const [question, setQuestion] = useState('Do standing desks actually improve productivity?')
  const [claims, setClaims] = useState<Claim[]>(DEMO_CLAIMS)
  const [trace, setTrace] = useState<TraceStep[]>(DEMO_TRACE)
  const [answer, setAnswer] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>('demo-1')
  const [flagged, setFlagged] = useState<string[]>([])
  const [flagNote, setFlagNote] = useState<string | null>(null)
  const [noteText, setNoteText] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [running, setRunning] = useState(false)
  const [stage, setStage] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [isLive, setIsLive] = useState(false)

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
      setIsLive(true)
    } catch (e: any) {
      setError('Could not reach the agent backend. Please try again in a moment.')
    } finally {
      clearInterval(stageTimer)
      setRunning(false)
      setStage(0)
    }
  }

  async function submitFlag(claimId: string) {
    const note = noteText.trim() || 'Flagged for review'
    setFlagged((f) => (f.includes(claimId) ? f : [...f, claimId]))
    setFlagNote(null)
    setNoteText('')
    try {
      await fetch(`${API_URL}/claims/${claimId}/override`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note }),
      })
    } catch {
      /* demo claims have no backend id; ignore */
    }
  }

  const avgConfidence = claims.length
    ? Math.round(claims.reduce((a, c) => a + c.confidence, 0) / claims.length)
    : 0

  return (
    <main className="min-h-screen bg-[#070b12] text-slate-100 selection:bg-[#FFC107] selection:text-slate-950">
      <div className="flex min-h-screen">
        <aside className={`${menuOpen ? 'translate-x-0' : '-translate-x-full'} fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-white/[0.07] bg-[#0a0f18] px-4 py-5 transition-transform md:static md:translate-x-0`}>
          <div className="flex items-center justify-between px-3">
            <div className="flex items-center gap-2.5"><div className="grid size-8 place-items-center rounded-lg bg-[#FFC107] text-slate-950"><Activity size={19} strokeWidth={2.8} /></div><span className="text-lg font-bold tracking-tight">Receipts<span className="text-[#FFC107]">.</span></span></div>
            <button onClick={() => setMenuOpen(false)} className="text-slate-500 md:hidden" aria-label="Close navigation"><X /></button>
          </div>
          <div className="mt-10 px-3 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-600">Workspace</div>
          <nav className="mt-3 flex flex-col gap-1">
            {[['Dashboard', LayoutDashboard], ['Runs', Timer], ['Sources', BookOpen], ['Settings', Settings]].map(([label, Icon]) => (
              <button key={label as string} onClick={() => setActive(label as string)} className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${active === label ? 'bg-[#FFC107]/10 text-[#FFC107]' : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'}`}><Icon size={17} />{label as string}{label === 'Runs' && <span className="ml-auto rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] text-slate-500">24</span>}</button>
            ))}
          </nav>
          <div className="mt-auto rounded-xl border border-cyan-300/10 bg-cyan-300/[0.04] p-4"><div className="flex items-center gap-2 text-xs font-semibold text-cyan-200"><Gauge size={15} /> Agent health</div><div className="mt-3 flex items-center gap-2"><span className="size-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]" /><span className="text-xs text-slate-400">All systems operational</span></div><div className="mt-3 h-1 overflow-hidden rounded-full bg-white/10"><div className="h-full w-[92%] rounded-full bg-cyan-300" /></div></div>
        </aside>
        {menuOpen && <button className="fixed inset-0 z-20 bg-black/60 md:hidden" onClick={() => setMenuOpen(false)} aria-label="Close navigation overlay" />}

        <section className="min-w-0 flex-1">
          <header className="flex h-16 items-center justify-between border-b border-white/[0.07] px-5 sm:px-8 lg:px-10"><div className="flex items-center gap-3"><button onClick={() => setMenuOpen(true)} className="text-slate-400 md:hidden" aria-label="Open navigation"><Menu /></button><div><p className="text-xs text-slate-500">Workspace / <span className="text-slate-300">{active}</span></p><h1 className="mt-0.5 text-sm font-semibold tracking-wide text-slate-200">Evidence dashboard</h1></div></div><div className="flex items-center gap-2">{isLive && <span className="hidden rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-1 text-[10px] font-bold text-emerald-300 sm:block">LIVE RUN</span>}<button className="hidden rounded-lg border border-white/[0.08] px-3 py-2 text-xs text-slate-400 hover:border-white/20 sm:block">Export run</button><button className="grid size-8 place-items-center rounded-full bg-[#FFC107] text-xs font-bold text-slate-950">JD</button></div></header>
          <div className="mx-auto max-w-[1480px] px-5 py-7 sm:px-8 lg:px-10 lg:py-9">
            <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#FFC107]">{isLive ? 'Live run · just now' : 'Run #0248 · demo data'}</p><h2 className="mt-2 text-2xl font-bold tracking-tight text-white sm:text-3xl">Good morning, Jamie<span className="text-[#FFC107]">.</span></h2><p className="mt-2 max-w-xl text-sm text-slate-500">Every answer, claim, and source — transparent by default.</p></div><button onClick={() => { setQuestion(''); setIsLive(false); }} className="flex items-center gap-2 self-start rounded-lg bg-[#FFC107] px-4 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-[#ffd34d] sm:self-auto"><Sparkles size={15} /> New question</button></div>
            <div className="mt-7 grid grid-cols-1 gap-3 sm:grid-cols-3"><Metric label="Questions answered" value="248" change="+12 this week" icon={CircleHelp} /><Metric label="Avg. confidence" value={`${avgConfidence}%`} change="this run" icon={Gauge} /><Metric label="Claims flagged" value={String(flagged.length || 7)} change="-18% vs last week" icon={AlertTriangle} warn /></div>

            <div className="mt-7 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.65fr)]">
              <div className="min-w-0">
                <div className="flex items-center gap-2 rounded-xl border border-[#FFC107]/35 bg-[#0d131d] p-2 shadow-[0_0_0_1px_rgba(255,193,7,0.04)]"><Search className="ml-2 shrink-0 text-[#FFC107]" size={18} /><input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && runAgent()} placeholder="Ask anything..." className="min-w-0 flex-1 bg-transparent px-2 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600" /><button onClick={runAgent} disabled={running} className="rounded-lg bg-[#FFC107] px-3.5 py-2 text-xs font-bold text-slate-950 hover:bg-[#ffd34d] disabled:opacity-60">{running ? <Loader2 size={13} className="animate-spin" /> : <>Run agent <ArrowUpRight size={13} className="ml-1 inline" /></>}</button></div>
                {running && <div className="mt-3 flex items-center gap-2 text-xs text-cyan-300"><Loader2 size={13} className="animate-spin" />{STAGE_MESSAGES[stage]}</div>}
                {error && <div className="mt-3 rounded-lg border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs text-rose-300">{error}</div>}
                {answer && <div className="mt-5 rounded-xl border border-[#FFC107]/25 bg-[#FFC107]/[0.04] p-4"><p className="text-[10px] font-bold uppercase tracking-[0.15em] text-[#FFC107]">Agent answer</p><p className="mt-2 text-sm leading-6 text-slate-200">{answer}</p></div>}
                <div className="mt-7 flex items-center justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Agent answer</p><p className="mt-1 text-sm text-slate-300">{claims.length} atomic claims <span className="text-slate-600">·</span> {claims.reduce((a, c) => a + c.citations.length, 0)} sources</p></div><button className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300">Most relevant <ChevronDown size={14} /></button></div>
                <div className="mt-4 flex flex-col gap-3">{claims.map((claim) => <ClaimCard key={claim.id} claim={claim} expanded={expanded === claim.id} onToggle={() => setExpanded(expanded === claim.id ? null : claim.id)} flagged={flagged.includes(claim.id)} onFlag={() => setFlagNote(flagNote === claim.id ? null : claim.id)} noteOpen={flagNote === claim.id} noteText={noteText} setNoteText={setNoteText} onSubmitNote={() => submitFlag(claim.id)} />)}</div>
              </div>
              <TracePanel steps={trace} running={running} stageMessage={STAGE_MESSAGES[stage]} />
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}

function Metric({ label, value, change, icon: Icon, warn = false }: { label: string; value: string; change: string; icon: typeof Gauge; warn?: boolean }) { return <div className="rounded-xl border border-white/[0.07] bg-[#0b111b] p-4"><div className="flex items-center justify-between"><span className="text-xs text-slate-500">{label}</span><Icon size={16} className={warn ? 'text-[#FFC107]' : 'text-cyan-300'} /></div><div className="mt-2 flex items-end gap-2"><span className="text-2xl font-bold tracking-tight text-slate-100">{value}</span><span className={`mb-1 text-[10px] ${warn ? 'text-emerald-300' : 'text-cyan-300'}`}>{change}</span></div></div> }

function ClaimCard({ claim, expanded, onToggle, flagged, onFlag, noteOpen, noteText, setNoteText, onSubmitNote }: {
  claim: Claim; expanded: boolean; onToggle: () => void; flagged: boolean; onFlag: () => void;
  noteOpen: boolean; noteText: string; setNoteText: (s: string) => void; onSubmitNote: () => void
}) {
  return <article className={`rounded-xl border bg-[#0b111b] transition ${expanded ? 'border-cyan-300/25' : 'border-white/[0.07]'}`}>
    <button onClick={onToggle} className="flex w-full items-start gap-3 p-4 text-left sm:p-5"><span className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-md text-xs font-bold ${expanded ? 'bg-cyan-300 text-slate-950' : 'bg-white/[0.07] text-slate-500'}`}>{claim.id.startsWith('demo') ? claim.id.replace('demo-', '') : '•'}</span><span className="min-w-0 flex-1 text-sm font-medium leading-6 text-slate-200">{claim.claim_text}</span><span className="flex shrink-0 items-center gap-2 text-xs font-bold text-cyan-300"><span className="hidden sm:inline">{claim.confidence}%</span><span className="h-1.5 w-12 overflow-hidden rounded-full bg-white/10 sm:w-16"><span className="block h-full rounded-full bg-cyan-300" style={{ width: `${claim.confidence}%` }} /></span>{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span></button>
    {expanded && <div className="border-t border-white/[0.06] px-4 pb-4 pt-4 sm:px-5 sm:pb-5"><div className="mb-4 flex items-center justify-between"><span className="text-[10px] font-bold uppercase tracking-[0.15em] text-slate-600">Supporting evidence</span><span className="text-xs text-slate-500">Confidence <strong className="text-cyan-300">{claim.confidence}/100</strong></span></div><div className="flex flex-col gap-2">{claim.citations.map((citation, i) => <div key={`${citation.source_url}-${i}`} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3"><div className="flex gap-3"><Favicon color={citation.color} /><div className="min-w-0"><p className="text-xs font-semibold text-slate-200">{citation.source_title}</p><a href={citation.source_url.startsWith('http') ? citation.source_url : `https://${citation.source_url}`} target="_blank" rel="noreferrer" className="mt-1 block truncate text-[11px] text-slate-600 hover:text-cyan-300">{citation.domain} · {citation.source_url}</a><p className="mt-3 border-l-2 border-[#FFC107]/60 pl-3 text-xs leading-5 text-slate-400">“{citation.snippet}”</p></div></div></div>)}</div><div className="mt-4 flex flex-wrap items-center gap-2"><button className="flex items-center gap-1.5 rounded-md border border-emerald-400/20 px-2.5 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-400/10"><Check size={13} /> Looks right</button><button onClick={onFlag} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium ${flagged ? 'border-[#FFC107]/50 bg-[#FFC107]/10 text-[#FFC107]' : 'border-white/10 text-slate-500 hover:border-[#FFC107]/40 hover:text-[#FFC107]'}`}><AlertTriangle size={13} /> {flagged ? 'Flagged' : 'Flag'}</button>{noteOpen && <span className="flex min-w-[180px] flex-1 items-center gap-2"><input autoFocus value={noteText} onChange={(e) => setNoteText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && onSubmitNote()} placeholder="Add a note (optional)" className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-slate-200 outline-none focus:border-[#FFC107]/50" /><button onClick={onSubmitNote} className="rounded-md bg-[#FFC107] px-2.5 py-1.5 text-xs font-bold text-slate-950">Save</button></span>}</div></div>}
  </article>
}

function TracePanel({ steps, running, stageMessage }: { steps: TraceStep[]; running: boolean; stageMessage: string }) {
  return <aside className="h-fit rounded-xl border border-white/[0.07] bg-[#0b111b] xl:sticky xl:top-6"><div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-4"><div><p className="text-sm font-semibold text-slate-200">Trace</p><p className="mt-1 text-xs text-slate-600">What the agent did, in order</p></div><button className="text-slate-600 hover:text-slate-300" aria-label="More trace options"><MoreHorizontal size={18} /></button></div><div className="p-5"><div className="relative flex flex-col gap-0">{steps.map((step, index) => { const Icon = TRACE_ICONS[index % TRACE_ICONS.length]; return <div key={`${step.step_order}-${index}`} className="relative flex gap-3 pb-6 last:pb-0"><div className="relative z-10 grid size-7 shrink-0 place-items-center rounded-lg border border-white/10 bg-[#0b111b]"><Icon size={14} className={index === 0 ? 'text-[#FFC107]' : 'text-cyan-300'} /></div>{index < steps.length - 1 && <div className="absolute left-[13px] top-7 h-[calc(100%-16px)] w-px bg-white/[0.08]" />}<div className="min-w-0 flex-1 pt-0.5"><div className="flex items-start justify-between gap-2"><p className="text-xs font-semibold text-slate-300">{step.action}</p><time className="shrink-0 text-[10px] text-slate-600">{step.time}</time></div><p className="mt-1 text-[11px] leading-4 text-slate-600">{step.detail}</p></div></div> })}</div>{running && <div className="mt-2 flex items-center gap-2 border-t border-white/[0.06] pt-4 text-xs text-cyan-300"><Loader2 size={13} className="animate-spin" />{stageMessage}</div>}</div><div className="border-t border-white/[0.06] px-5 py-4"><div className="flex items-center justify-between text-xs"><span className="text-slate-600">Run duration</span><span className="font-semibold text-slate-300">{running ? 'running…' : `${steps.length * 1.7}s`}</span></div></div></aside>
}
