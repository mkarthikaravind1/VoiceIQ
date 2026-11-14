import { useCallback, useEffect, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid } from 'recharts'
import { Header } from '../components/Header'
import { CallLog } from '../components/CallLog'
import { SentimentChart } from '../components/SentimentChart'
import { INK, SERIES_BLUE, intentColor, intentLabel, fmtSeconds, toolLabel } from '../utils/chartTheme'

const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
const when = (iso) => new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

const RESOLUTION = {
  resolved:   'bg-emerald-50 text-emerald-800',
  unresolved: 'bg-gray-100 text-gray-700',
  escalated:  'bg-amber-50 text-amber-900',
}

function Tile({ label, value, hint }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl px-4 py-3">
      <p className="text-xs text-gray-600">{label}</p>
      <p className="text-2xl font-display font-semibold text-gray-900 mt-1">{value}</p>
      {hint && <p className="text-[11px] text-gray-500 mt-0.5">{hint}</p>}
    </div>
  )
}

function Card({ title, subtitle, children }) {
  return (
    <section className="bg-white border border-gray-200 rounded-xl p-4">
      <p className="text-sm font-semibold text-gray-900">{title}</p>
      {subtitle && <p className="text-xs text-gray-600 mt-0.5 mb-3">{subtitle}</p>}
      {children}
    </section>
  )
}

const tooltipStyle = { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 6, fontSize: 11 }

export default function Analytics() {
  const [summary, setSummary] = useState(null)
  const [calls, setCalls] = useState([])
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([
        fetch('/api/analytics/summary').then(r => { if (!r.ok) throw new Error(r.statusText); return r.json() }),
        fetch('/api/analytics/calls').then(r => { if (!r.ok) throw new Error(r.statusText); return r.json() }),
      ])
      setSummary(s)
      setCalls(c.calls)
      setError(null)
    } catch {
      setError('Could not load analytics — is the backend running?')
    }
  }, [])

  useEffect(() => { load() }, [load])

  const openCall = async (id) => {
    try {
      const r = await fetch(`/api/analytics/calls/${id}`)
      if (r.ok) setDetail(await r.json())
    } catch { /* list stays usable */ }
  }

  const intents = (summary?.intents || []).map(i => ({ name: intentLabel(i.intent), n: i.n, color: intentColor(i.intent) }))
  const perDay = (summary?.per_day || []).map(d => ({ day: d.day.slice(5), calls: d.calls }))

  return (
    <div className="h-screen overflow-hidden bg-gray-50 flex flex-col">
      <Header>
        <button onClick={load} className="text-xs text-gray-600 hover:text-gray-900">Refresh</button>
      </Header>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-6xl mx-auto space-y-4">
          {error && <p className="text-sm text-red-600">{error}</p>}

          {summary && summary.calls === 0 && (
            <p className="text-sm text-gray-600 bg-white border border-gray-200 rounded-xl px-4 py-3">
              No finished calls yet. Have a conversation on the Agent page and press “End call and summarise” — it shows up here.
            </p>
          )}

          {/* Headline numbers */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Tile label="Calls" value={summary?.calls ?? '—'} hint={`${summary?.turns ?? 0} turns`} />
            <Tile label="Resolved by AI" value={pct(summary?.resolution_rate)} hint="of finished calls" />
            <Tile label="Escalated" value={pct(summary?.escalation_rate)} hint="handed to a human" />
            <Tile label="Est. satisfaction" value={summary?.avg_csat != null ? `${summary.avg_csat.toFixed(1)}/5` : '—'} hint="model's estimate, not a survey" />
            <Tile label="Time to first audio" value={fmtSeconds(summary?.avg_ttfa_ms)} hint="average, from end of speech" />
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <Card title="What callers asked for" subtitle="Turns by intent">
              {intents.length === 0 ? <p className="text-sm text-gray-600">No data yet.</p> : (
                <div style={{ height: Math.max(120, intents.length * 34) }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={intents} layout="vertical" margin={{ top: 0, right: 24, bottom: 0, left: 8 }} barCategoryGap={8}>
                      <XAxis type="number" hide allowDecimals={false} />
                      <YAxis type="category" dataKey="name" width={112} tick={{ fontSize: 12, fill: INK.secondary }} tickLine={false} axisLine={false} />
                      <Tooltip cursor={{ fill: '#f3f4f6' }} contentStyle={tooltipStyle} formatter={(v) => [v, 'turns']} />
                      <Bar dataKey="n" radius={[0, 4, 4, 0]} barSize={16} isAnimationActive={false}
                        label={{ position: 'right', fontSize: 11, fill: INK.secondary }}>
                        {intents.map((d, i) => <Cell key={i} fill={d.color} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>

            <Card title="Calls per day" subtitle="Last 14 days with activity">
              {perDay.length === 0 ? <p className="text-sm text-gray-600">No data yet.</p> : (
                <div style={{ height: 160 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={perDay} margin={{ top: 8, right: 8, bottom: 0, left: -24 }}>
                      <CartesianGrid vertical={false} stroke={INK.grid} />
                      <XAxis dataKey="day" tick={{ fontSize: 11, fill: INK.muted }} tickLine={false} axisLine={{ stroke: INK.grid }} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: INK.muted }} tickLine={false} axisLine={false} />
                      <Tooltip cursor={{ fill: '#f3f4f6' }} contentStyle={tooltipStyle} />
                      <Bar dataKey="calls" fill={SERIES_BLUE} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <Card title="Knowledge gaps" subtitle="Questions the help articles could not answer — candidates for new FAQs">
              {(summary?.knowledge_gaps || []).length === 0 ? <p className="text-sm text-gray-600">None recorded.</p> : (
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs text-gray-600">
                    <th className="font-normal pb-1">Searched for</th><th className="font-normal pb-1 text-right">Times</th>
                  </tr></thead>
                  <tbody>
                    {summary.knowledge_gaps.map((g, i) => (
                      <tr key={i} className="border-t border-gray-100">
                        <td className="py-1.5 text-gray-900">{g.question}</td>
                        <td className="py-1.5 text-right font-mono text-gray-800">{g.n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>

            <Card title="Actions completed by the agent" subtitle="Changes made to orders after the caller confirmed">
              {(summary?.actions || []).length === 0 ? <p className="text-sm text-gray-600">None yet.</p> : (
                <table className="w-full text-sm">
                  <tbody>
                    {summary.actions.map((a, i) => (
                      <tr key={i} className="border-t border-gray-100 first:border-t-0">
                        <td className="py-1.5 text-gray-900">{toolLabel(a.action)}</td>
                        <td className="py-1.5 text-right font-mono text-gray-800">{a.n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>

          <Card title="Recent calls" subtitle="Select a call to read it">
            {calls.length === 0 ? <p className="text-sm text-gray-600">No calls yet.</p> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs text-gray-600">
                    <th className="font-normal pb-1">Started</th><th className="font-normal pb-1">Channel</th>
                    <th className="font-normal pb-1">Outcome</th><th className="font-normal pb-1 text-right">Turns</th>
                    <th className="font-normal pb-1 text-right">Satisfaction</th><th className="font-normal pb-1 pl-4">Summary</th>
                  </tr></thead>
                  <tbody>
                    {calls.map(c => (
                      <tr key={c.id} onClick={() => openCall(c.id)} tabIndex={0}
                        onKeyDown={e => e.key === 'Enter' && openCall(c.id)}
                        className="border-t border-gray-100 hover:bg-gray-50 cursor-pointer focus:outline-none focus:bg-violet-50">
                        <td className="py-2 text-gray-900 whitespace-nowrap">{when(c.started_at)}</td>
                        <td className="py-2 text-gray-700">{c.channel}</td>
                        <td className="py-2">
                          <span className={`px-1.5 py-0.5 rounded text-xs ${RESOLUTION[c.resolution] || 'bg-violet-50 text-violet-800'}`}>
                            {c.resolution || 'in progress'}
                          </span>
                        </td>
                        <td className="py-2 text-right font-mono text-gray-800">{c.turns}</td>
                        <td className="py-2 text-right font-mono text-gray-800">{c.csat != null ? `${c.csat}/5` : '—'}</td>
                        <td className="py-2 pl-4 text-gray-700 max-w-md truncate">{c.summary || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Call detail */}
      {detail && (
        <div className="fixed inset-0 bg-black/30 flex justify-end z-20" onClick={() => setDetail(null)}>
          <div className="w-full max-w-lg bg-white h-full flex flex-col p-6 shadow-xl" onClick={e => e.stopPropagation()}
            role="dialog" aria-label="Call detail">
            <div className="flex items-start justify-between mb-3">
              <div>
                <p className="text-lg font-display font-semibold text-gray-900">Call {detail.id}</p>
                <p className="text-xs text-gray-600">{when(detail.started_at)} · {detail.channel} · {(detail.language || '').toUpperCase()}</p>
              </div>
              <button onClick={() => setDetail(null)} className="text-sm text-gray-600 hover:text-gray-900">Close</button>
            </div>
            {detail.summary && <p className="text-sm text-gray-900 leading-relaxed mb-3">{detail.summary}</p>}
            <div className="flex flex-wrap gap-2 mb-4 text-xs">
              {(detail.topics || []).map((t, i) => <span key={i} className="px-2 py-0.5 rounded bg-violet-50 text-violet-700">{t}</span>)}
            </div>
            <p className="text-xs uppercase tracking-widest text-gray-900 font-display mb-2">Sentiment</p>
            <SentimentChart turns={detail.turn_list} height={100} />
            <p className="text-xs uppercase tracking-widest text-gray-900 font-display mt-4 mb-2">Transcript</p>
            <div className="flex-1 min-h-0 flex flex-col">
              <CallLog entries={detail.turn_list.map(t => ({ ...t, speaker: t.speaker === 'caller' ? 'ai' : t.speaker }))} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
