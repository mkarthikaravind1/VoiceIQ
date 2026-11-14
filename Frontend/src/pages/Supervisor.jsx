import { useEffect, useRef, useState } from 'react'
import { Header } from '../components/Header'
import { CallLog } from '../components/CallLog'
import { SentimentChart } from '../components/SentimentChart'

const WS_URL = (import.meta.env.VITE_WS_URL
  ?? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/voice`)
  .replace(/\/ws\/voice$/, '/ws/supervisor')

const STATUS = {
  escalated: { label: 'Needs a human', className: 'bg-amber-100 text-amber-900' },
  human:     { label: 'With you',      className: 'bg-emerald-100 text-emerald-900' },
  active:    { label: 'With AI',       className: 'bg-violet-100 text-violet-800' },
  ended:     { label: 'Ended',         className: 'bg-gray-200 text-gray-700' },
}
const ORDER = { escalated: 0, human: 1, active: 2, ended: 3 }

// Server turns → the shape CallLog renders
const toEntries = (turns) => turns.map(t => ({
  speaker: t.speaker === 'caller' ? 'ai' : t.speaker,
  transcript: t.transcript,
  response: t.response,
  intent: t.intent,
  confidence: t.confidence,
  sentiment: t.sentiment,
  tools: t.tools,
  timings: t.timings,
}))

const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

export default function Supervisor() {
  const [calls, setCalls] = useState({})
  const [selectedId, setSelectedId] = useState(null)
  const [connected, setConnected] = useState(false)
  const [notice, setNotice] = useState(null)
  const [draft, setDraft] = useState('')
  const wsRef = useRef(null)

  useEffect(() => {
    let closed = false
    let retry

    const open = () => {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data)
        if (msg.type === 'snapshot') {
          setCalls(Object.fromEntries(msg.calls.map(c => [c.call_id, c])))
        } else if (msg.type === 'call') {
          setCalls(prev => ({ ...prev, [msg.call.call_id]: msg.call }))
        } else if (msg.type === 'error') {
          setNotice(msg.message)
        }
      }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) retry = setTimeout(open, 2000)   // keep the board alive across server restarts
      }
    }
    open()

    return () => {
      closed = true
      clearTimeout(retry)
      const ws = wsRef.current
      if (ws) {
        ws.onclose = null
        ws.close()
      }
    }
  }, [])

  const list = Object.values(calls).sort(
    (a, b) => ORDER[a.status] - ORDER[b.status] || b.started_at.localeCompare(a.started_at)
  )
  const selected = calls[selectedId] || list[0] || null
  const waiting = list.filter(c => c.status === 'escalated').length

  const send = (payload) => {
    setNotice(null)
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify(payload))
  }

  const say = (e) => {
    e.preventDefault()
    if (!draft.trim() || !selected) return
    send({ action: 'say', call_id: selected.call_id, text: draft.trim() })
    setDraft('')
  }

  const live = selected && selected.status !== 'ended'

  return (
    <div className="h-screen overflow-hidden bg-white flex flex-col">
      <Header>
        <span className={`flex items-center gap-1.5 text-xs font-mono ${connected ? 'text-gray-600' : 'text-red-600'}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-500' : 'bg-red-500'}`} />
          {connected ? 'Live' : 'Reconnecting…'}
        </span>
      </Header>

      <div className="flex-1 flex overflow-hidden">
        {/* Call list */}
        <aside className="w-80 border-r border-gray-200 bg-gray-50 flex flex-col min-h-0">
          <div className="px-4 py-3 border-b border-gray-200">
            <p className="text-xs uppercase tracking-widest text-gray-900 font-display">Calls</p>
            <p className="text-xs text-gray-600 mt-0.5">
              {waiting > 0 ? `${waiting} waiting for a human` : 'No one is waiting'}
            </p>
          </div>
          <div className="flex-1 overflow-y-auto">
            {list.length === 0 && (
              <p className="text-sm text-gray-600 p-4">
                No calls yet. Open the Agent page in another tab and start talking — the call appears here live.
              </p>
            )}
            {list.map(call => {
              const st = STATUS[call.status]
              const last = [...call.turns].reverse().find(t => t.transcript)
              return (
                <button key={call.call_id} onClick={() => setSelectedId(call.call_id)}
                  className={`w-full text-left px-4 py-3 border-b border-gray-200 transition-colors
                    ${selected?.call_id === call.call_id ? 'bg-white' : 'hover:bg-gray-100'}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className={`px-1.5 py-0.5 rounded text-[11px] font-medium ${st.className}`}>{st.label}</span>
                    <span className="text-[11px] font-mono text-gray-600">
                      {call.channel === 'phone' ? '☎ phone' : 'web'} · {clock(call.started_at)}
                    </span>
                  </div>
                  <p className="text-sm text-gray-900 mt-1.5 truncate">
                    {call.verified_customer || 'Unverified caller'}
                  </p>
                  <p className="text-xs text-gray-600 truncate">{last ? `"${last.transcript}"` : '—'}</p>
                </button>
              )
            })}
          </div>
        </aside>

        {/* Selected call */}
        {!selected ? (
          <div className="flex-1 flex items-center justify-center text-sm text-gray-600">Select a call</div>
        ) : (
          <main className="flex-1 flex min-w-0">
            <section className="flex-1 flex flex-col min-h-0 p-6">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <p className="text-lg font-display font-semibold text-gray-900">
                    {selected.verified_customer || 'Unverified caller'}
                  </p>
                  <p className="text-xs text-gray-600 font-mono">
                    Call {selected.call_id} · {selected.language.toUpperCase()} · {selected.turns.length} turns
                  </p>
                </div>
                {live && (selected.mode === 'human' ? (
                  <button onClick={() => send({ action: 'release', call_id: selected.call_id })}
                    className="text-sm px-3 py-1.5 rounded-md border border-gray-300 text-gray-800 hover:bg-gray-100">
                    Hand back to AI
                  </button>
                ) : (
                  <button onClick={() => send({ action: 'takeover', call_id: selected.call_id })}
                    className="text-sm px-3 py-1.5 rounded-md bg-violet-600 text-white hover:bg-violet-700">
                    Take over call
                  </button>
                ))}
              </div>

              <div className="flex-1 min-h-0 flex flex-col border border-gray-200 rounded-xl p-4 bg-gray-50">
                <CallLog entries={toEntries(selected.turns)} showLatency={false} />
              </div>

              {live && (
                <form onSubmit={say} className="mt-3 flex gap-2">
                  <input value={draft} onChange={e => setDraft(e.target.value)}
                    placeholder={selected.mode === 'human'
                      ? 'Type a reply — it is spoken to the caller'
                      : 'Type a reply to take over and speak to the caller'}
                    aria-label="Reply to the caller"
                    className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
                  <button type="submit" disabled={!draft.trim()}
                    className="px-4 py-2 rounded-md bg-violet-600 text-white text-sm disabled:opacity-40">
                    Speak
                  </button>
                </form>
              )}
              {notice && <p className="text-xs text-red-600 mt-2">{notice}</p>}
            </section>

            {/* Briefing */}
            <aside className="w-80 border-l border-gray-200 p-6 space-y-5 overflow-y-auto">
              {selected.escalated && (
                <div>
                  <p className="text-xs uppercase tracking-widest text-gray-900 font-display mb-2">Handoff briefing</p>
                  <p className="text-xs text-gray-600 mb-2">Why: {selected.escalate_reason}</p>
                  {selected.handoff_summary ? (
                    <div className="text-sm text-gray-900 whitespace-pre-line leading-relaxed bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                      {selected.handoff_summary}
                    </div>
                  ) : (
                    <p className="text-sm text-gray-600">Writing the briefing…</p>
                  )}
                </div>
              )}

              <div>
                <p className="text-xs uppercase tracking-widest text-gray-900 font-display mb-2">Sentiment</p>
                <SentimentChart turns={selected.turns} height={110} />
              </div>

              <div>
                <p className="text-xs uppercase tracking-widest text-gray-900 font-display mb-2">Caller</p>
                <dl className="text-sm space-y-1">
                  <div className="flex justify-between"><dt className="text-gray-600">Identity</dt>
                    <dd className="text-gray-900">{selected.verified_customer ? 'Verified' : 'Not verified'}</dd></div>
                  <div className="flex justify-between"><dt className="text-gray-600">Channel</dt>
                    <dd className="text-gray-900">{selected.channel}</dd></div>
                  <div className="flex justify-between"><dt className="text-gray-600">Started</dt>
                    <dd className="text-gray-900">{clock(selected.started_at)}</dd></div>
                </dl>
              </div>

              {selected.analysis && (
                <div>
                  <p className="text-xs uppercase tracking-widest text-gray-900 font-display mb-2">After the call</p>
                  <p className="text-sm text-gray-900 leading-relaxed">{selected.analysis.summary}</p>
                  <p className="text-xs text-gray-600 mt-1">
                    {selected.analysis.resolution} · est. satisfaction {selected.analysis.csat}/5
                  </p>
                </div>
              )}
            </aside>
          </main>
        )}
      </div>
    </div>
  )
}
