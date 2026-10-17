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
  Menu,
  MoreHorizontal,
  Search,
  Settings,
  Sparkles,
  SquareStack,
  Timer,
  X,
} from 'lucide-react'

const claims = [
  {
    id: 1,
    confidence: 87,
    text: 'Standing desks can improve comfort and reduce sedentary time, but the evidence for a direct productivity boost is mixed.',
    citations: [
      {
        title: 'Sit-Stand Desks and Workplace Health',
        domain: 'nih.gov',
        url: 'ncbi.nlm.nih.gov/pmc/articles/PMC6224419',
        quote: 'Sit-stand desk interventions were associated with reduced sitting time and improvements in musculoskeletal discomfort.',
        color: 'bg-sky-400',
      },
      {
        title: 'The impact of sit-stand desks on work performance',
        domain: 'cochranelibrary.com',
        url: 'cochranelibrary.com/cdsr/doi/10.1002/14651858',
        quote: 'There is low-certainty evidence that sit-stand desks have little to no effect on work performance outcomes.',
        color: 'bg-emerald-400',
      },
    ],
  },
  {
    id: 2,
    confidence: 94,
    text: 'Short-term use of a standing desk does not appear to harm typing speed, cognitive performance, or task accuracy.',
    citations: [
      {
        title: 'Stand Up to Work: A Randomized Trial',
        domain: 'jmir.org',
        url: 'jmir.org/2020/4/e16704',
        quote: 'There were no significant differences in typing speed, cognitive function, or task accuracy between the groups.',
        color: 'bg-violet-400',
      },
    ],
  },
  {
    id: 3,
    confidence: 76,
    text: 'The most reliable benefit comes from alternating between sitting and standing, rather than standing continuously.',
    citations: [
      {
        title: 'Ergonomics and the Sit-Stand Workstation',
        domain: 'osha.gov',
        url: 'osha.gov/ergonomics/stand-sit-workstations',
        quote: 'Workers should be encouraged to change posture frequently and avoid prolonged periods in either a seated or standing position.',
        color: 'bg-amber-400',
      },
    ],
  },
]

const trace = [
  { icon: Sparkles, label: 'Interpreted question', detail: 'Productivity, health, and time horizon', time: '10:42:01', color: 'text-[#FFC107]' },
  { icon: SquareStack, label: 'Planned 3 sub-questions', detail: 'Performance · Comfort · Best practice', time: '10:42:02', color: 'text-cyan-300' },
  { icon: Search, label: 'Searched 12 sources', detail: 'Academic research and workplace guidance', time: '10:42:04', color: 'text-cyan-300' },
  { icon: FileSearch, label: 'Extracted 9 candidate claims', detail: 'Ranked by evidence quality and relevance', time: '10:42:07', color: 'text-cyan-300' },
  { icon: Check, label: 'Verified 3 claims', detail: 'Cross-checked against 4 independent sources', time: '10:42:09', color: 'text-emerald-300' },
]

function Favicon({ color }: { color: string }) {
  return <span className={`grid size-6 shrink-0 place-items-center rounded-md ${color} text-[10px] font-black text-slate-950`}>↗</span>
}

export default function Page() {
  const [active, setActive] = useState('Dashboard')
  const [question, setQuestion] = useState('Do standing desks actually improve productivity?')
  const [expanded, setExpanded] = useState<number | null>(1)
  const [flagged, setFlagged] = useState<number[]>([])
  const [flagNote, setFlagNote] = useState<number | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)

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
          <div className="mt-auto rounded-xl border border-cyan-300/10 bg-cyan-300/[0.04] p-4"><div className="flex items-center gap-2 text-xs font-semibold text-cyan-200"><Gauge size={15} /> Agent health</div><div className="mt-3 flex items-center gap-2"><span className="size-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]"/><span className="text-xs text-slate-400">All systems operational</span></div><div className="mt-3 h-1 overflow-hidden rounded-full bg-white/10"><div className="h-full w-[92%] rounded-full bg-cyan-300" /></div></div>
        </aside>
        {menuOpen && <button className="fixed inset-0 z-20 bg-black/60 md:hidden" onClick={() => setMenuOpen(false)} aria-label="Close navigation overlay" />}

        <section className="min-w-0 flex-1">
          <header className="flex h-16 items-center justify-between border-b border-white/[0.07] px-5 sm:px-8 lg:px-10"><div className="flex items-center gap-3"><button onClick={() => setMenuOpen(true)} className="text-slate-400 md:hidden" aria-label="Open navigation"><Menu /></button><div><p className="text-xs text-slate-500">Workspace / <span className="text-slate-300">{active}</span></p><h1 className="mt-0.5 text-sm font-semibold tracking-wide text-slate-200">Evidence dashboard</h1></div></div><div className="flex items-center gap-2"><button className="hidden rounded-lg border border-white/[0.08] px-3 py-2 text-xs text-slate-400 hover:border-white/20 sm:block">Export run</button><button className="grid size-8 place-items-center rounded-full bg-[#FFC107] text-xs font-bold text-slate-950">JD</button></div></header>
          <div className="mx-auto max-w-[1480px] px-5 py-7 sm:px-8 lg:px-10 lg:py-9">
            <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#FFC107]">Run #0248 · just now</p><h2 className="mt-2 text-2xl font-bold tracking-tight text-white sm:text-3xl">Good morning, Jamie<span className="text-[#FFC107]">.</span></h2><p className="mt-2 max-w-xl text-sm text-slate-500">Every answer, claim, and source — transparent by default.</p></div><button onClick={() => setQuestion('')} className="flex items-center gap-2 self-start rounded-lg bg-[#FFC107] px-4 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-[#ffd34d] sm:self-auto"><Sparkles size={15} /> New question</button></div>
            <div className="mt-7 grid grid-cols-1 gap-3 sm:grid-cols-3"><Metric label="Questions answered" value="248" change="+12 this week" icon={CircleHelp} /><Metric label="Avg. confidence" value="86.4%" change="+2.1% vs last week" icon={Gauge} /><Metric label="Claims flagged" value={String(flagged.length || 7)} change="-18% vs last week" icon={AlertTriangle} warn /></div>

            <div className="mt-7 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.65fr)]">
              <div className="min-w-0"><div className="flex items-center gap-2 rounded-xl border border-[#FFC107]/35 bg-[#0d131d] p-2 shadow-[0_0_0_1px_rgba(255,193,7,0.04)]"><Search className="ml-2 shrink-0 text-[#FFC107]" size={18} /><input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask anything..." className="min-w-0 flex-1 bg-transparent px-2 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600" /><button className="rounded-lg bg-[#FFC107] px-3.5 py-2 text-xs font-bold text-slate-950 hover:bg-[#ffd34d]">Run agent <ArrowUpRight size={13} className="ml-1 inline" /></button></div><div className="mt-7 flex items-center justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Agent answer</p><p className="mt-1 text-sm text-slate-300">3 atomic claims <span className="text-slate-600">·</span> 4 sources <span className="text-slate-600">·</span> 8.7s</p></div><button className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300">Most relevant <ChevronDown size={14} /></button></div><div className="mt-4 flex flex-col gap-3">{claims.map((claim) => <ClaimCard key={claim.id} claim={claim} expanded={expanded === claim.id} onToggle={() => setExpanded(expanded === claim.id ? null : claim.id)} flagged={flagged.includes(claim.id)} onFlag={() => { setFlagged(flagged.includes(claim.id) ? flagged.filter((id) => id !== claim.id) : [...flagged, claim.id]); setFlagNote(flagNote === claim.id ? null : claim.id) }} noteOpen={flagNote === claim.id} />)}</div></div>
              <TracePanel />
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}

function Metric({ label, value, change, icon: Icon, warn = false }: { label: string; value: string; change: string; icon: typeof Gauge; warn?: boolean }) { return <div className="rounded-xl border border-white/[0.07] bg-[#0b111b] p-4"><div className="flex items-center justify-between"><span className="text-xs text-slate-500">{label}</span><Icon size={16} className={warn ? 'text-[#FFC107]' : 'text-cyan-300'} /></div><div className="mt-2 flex items-end gap-2"><span className="text-2xl font-bold tracking-tight text-slate-100">{value}</span><span className={`mb-1 text-[10px] ${warn ? 'text-emerald-300' : 'text-cyan-300'}`}>{change}</span></div></div> }

function ClaimCard({ claim, expanded, onToggle, flagged, onFlag, noteOpen }: { claim: typeof claims[number]; expanded: boolean; onToggle: () => void; flagged: boolean; onFlag: () => void; noteOpen: boolean }) { return <article className={`rounded-xl border bg-[#0b111b] transition ${expanded ? 'border-cyan-300/25' : 'border-white/[0.07]'}`}><button onClick={onToggle} className="flex w-full items-start gap-3 p-4 text-left sm:p-5"><span className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-md text-xs font-bold ${expanded ? 'bg-cyan-300 text-slate-950' : 'bg-white/[0.07] text-slate-500'}`}>{claim.id}</span><span className="min-w-0 flex-1 text-sm font-medium leading-6 text-slate-200">{claim.text}</span><span className="flex shrink-0 items-center gap-2 text-xs font-bold text-cyan-300"><span className="hidden sm:inline">{claim.confidence}%</span><span className="h-1.5 w-12 overflow-hidden rounded-full bg-white/10 sm:w-16"><span className="block h-full rounded-full bg-cyan-300" style={{ width: `${claim.confidence}%` }} /></span>{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span></button>{expanded && <div className="border-t border-white/[0.06] px-4 pb-4 pt-4 sm:px-5 sm:pb-5"><div className="mb-4 flex items-center justify-between"><span className="text-[10px] font-bold uppercase tracking-[0.15em] text-slate-600">Supporting evidence</span><span className="text-xs text-slate-500">Confidence <strong className="text-cyan-300">{claim.confidence}/100</strong></span></div><div className="flex flex-col gap-2">{claim.citations.map((citation) => <div key={citation.url} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3"><div className="flex gap-3"><Favicon color={citation.color} /><div className="min-w-0"><p className="text-xs font-semibold text-slate-200">{citation.title}</p><p className="mt-1 truncate text-[11px] text-slate-600">{citation.domain} · {citation.url}</p><p className="mt-3 border-l-2 border-[#FFC107]/60 pl-3 text-xs leading-5 text-slate-400">“{citation.quote}”</p></div></div></div>)}</div><div className="mt-4 flex flex-wrap items-center gap-2"><button className="flex items-center gap-1.5 rounded-md border border-emerald-400/20 px-2.5 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-400/10"><Check size={13} /> Looks right</button><button onClick={onFlag} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium ${flagged ? 'border-[#FFC107]/50 bg-[#FFC107]/10 text-[#FFC107]' : 'border-white/10 text-slate-500 hover:border-[#FFC107]/40 hover:text-[#FFC107]'}`}><AlertTriangle size={13} /> {flagged ? 'Flagged' : 'Flag'}</button>{noteOpen && <input autoFocus placeholder="Add a note (optional)" className="min-w-[180px] flex-1 rounded-md border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-slate-200 outline-none focus:border-[#FFC107]/50" />}</div></div>}</article> }

function TracePanel() { return <aside className="h-fit rounded-xl border border-white/[0.07] bg-[#0b111b] xl:sticky xl:top-6"><div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-4"><div><p className="text-sm font-semibold text-slate-200">Trace</p><p className="mt-1 text-xs text-slate-600">What the agent did, in order</p></div><button className="text-slate-600 hover:text-slate-300" aria-label="More trace options"><MoreHorizontal size={18} /></button></div><div className="p-5"><div className="relative flex flex-col gap-0">{trace.map((step, index) => { const Icon = step.icon; return <div key={step.label} className="relative flex gap-3 pb-6 last:pb-0"><div className="relative z-10 grid size-7 shrink-0 place-items-center rounded-lg border border-white/10 bg-[#0b111b]"><Icon size={14} className={step.color} /></div>{index < trace.length - 1 && <div className="absolute left-[13px] top-7 h-[calc(100%-16px)] w-px bg-white/[0.08]" />}<div className="min-w-0 flex-1 pt-0.5"><div className="flex items-start justify-between gap-2"><p className="text-xs font-semibold text-slate-300">{step.label}</p><time className="shrink-0 text-[10px] text-slate-600">{step.time}</time></div><p className="mt-1 text-[11px] leading-4 text-slate-600">{step.detail}</p></div></div> })}</div></div><div className="border-t border-white/[0.06] px-5 py-4"><div className="flex items-center justify-between text-xs"><span className="text-slate-600">Run duration</span><span className="font-semibold text-slate-300">8.7 seconds</span></div></div></aside> }
