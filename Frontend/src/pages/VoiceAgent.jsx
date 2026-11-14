import { useState, useCallback, useRef } from 'react'
import { useVoiceSocket } from '../hooks/useVoiceSocket'
import { useAudioPlayer } from '../hooks/useAudioPlayer'
import { CallLog } from '../components/CallLog'
import { StatsBar } from '../components/StatsBar'
import { Header } from '../components/Header'
import { LANGUAGES, toolLabel } from '../utils/chartTheme'

// ── Mic Button with animated rings ───────────────────────────────────────────
function MicButton({ listening, onClick, disabled }) {
  return (
    <div className="relative flex items-center justify-center w-40 h-40">
      {listening && (
        <>
          <div className="absolute inset-0 rounded-full border-2 border-violet-600/40 ring-pulse-2" />
          <div className="absolute inset-3 rounded-full border-2 border-violet-500/50 ring-pulse-1" />
        </>
      )}
      <button
        onClick={onClick}
        disabled={disabled}
        aria-label={listening ? 'Stop listening' : 'Start listening'}
        className={`
          relative z-10 w-24 h-24 rounded-full flex items-center justify-center
          transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500
          ${listening
            ? 'bg-violet-600 shadow-violet-glow-lg scale-105'
          : 'bg-gray-100 hover:bg-gray-200 border border-gray-300'
          }
          ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}
        `}
      >
        {listening ? (
          <svg className="w-8 h-8 text-white" fill="currentColor" viewBox="0 0 24 24">
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
        ) : (
          <svg className="w-8 h-8 text-gray-600" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 1a4 4 0 0 1 4 4v6a4 4 0 0 1-8 0V5a4 4 0 0 1 4-4zm0 2a2 2 0 0 0-2 2v6a2 2 0 1 0 4 0V5a2 2 0 0 0-2-2zm-7 8a1 1 0 0 1 1 1 6 6 0 1 0 12 0 1 1 0 0 1 2 0 8 8 0 0 1-7 7.938V21h2a1 1 0 0 1 0 2H9a1 1 0 0 1 0-2h2v-2.062A8 8 0 0 1 4 12a1 1 0 0 1 1-1z" />
          </svg>
        )}
      </button>
    </div>
  )
}

// ── Status Pill ───────────────────────────────────────────────────────────────
// An error always wins, so it is never hidden behind "Listening..." or "Connecting...".
function StatusPill({ status, error, listening, connected, connecting }) {
  const label = error ? `Error: ${error}`
    : listening ? 'Listening...'
    : connected ? (status || 'Connected — tap to speak')
    : connecting ? 'Connecting...'
    : 'Offline — tap the mic to reconnect'

  const color = error ? 'text-red-600' : listening ? 'text-violet-600' : 'text-gray-600'
  const dot = error ? 'bg-red-500'
    : listening ? 'bg-violet-500 animate-pulse'
    : connected ? 'bg-emerald-500'
    : connecting ? 'bg-amber-400 animate-pulse'
    : 'bg-gray-400'

  return (
    <div className={`flex items-center gap-2 text-sm ${color} font-mono`} role="status">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
      {label}
    </div>
  )
}

// ── Post-call summary ────────────────────────────────────────────────────────
const RESOLUTION = {
  resolved:   { label: 'Resolved',   className: 'bg-emerald-50 text-emerald-800' },
  unresolved: { label: 'Unresolved', className: 'bg-gray-100 text-gray-700' },
  escalated:  { label: 'Escalated',  className: 'bg-amber-50 text-amber-900' },
}

function CallSummaryCard({ summary, onClose }) {
  const res = RESOLUTION[summary.resolution] || RESOLUTION.unresolved
  return (
    <div className="max-w-sm w-full bg-white border border-gray-200 rounded-xl px-4 py-3 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs uppercase tracking-widest text-gray-600 font-display">Call summary</p>
        <button onClick={onClose} className="text-xs text-gray-600 hover:text-gray-900">Dismiss</button>
      </div>
      <p className="text-sm text-gray-900 leading-relaxed">{summary.summary}</p>
      <div className="flex flex-wrap items-center gap-2 mt-3 text-xs">
        <span className={`px-2 py-0.5 rounded font-medium ${res.className}`}>{res.label}</span>
        {summary.csat != null && (
          <span className="px-2 py-0.5 rounded bg-gray-100 text-gray-700" title="Estimated customer satisfaction, 1 to 5">
            Est. satisfaction {summary.csat}/5
          </span>
        )}
        {(summary.topics || []).map((t, i) => (
          <span key={i} className="px-2 py-0.5 rounded bg-violet-50 text-violet-700">{t}</span>
        ))}
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function VoiceAgent() {
  const [entries,   setEntries]   = useState([])
  const [status,    setStatus]    = useState('')
  const [error,     setError]     = useState(null)
  const [pending,   setPending]   = useState(null)   // turn in progress: { turn_id, transcript, partial, tools }
  const [language,  setLanguage]  = useState({ code: 'en', hasVoice: true })
  const [verified,  setVerified]  = useState(null)   // customer name once verified
  const [escalated, setEscalated] = useState(false)
  const [mode,      setMode]      = useState('ai')   // 'ai' | 'human'
  const [summary,   setSummary]   = useState(null)
  const [ending,    setEnding]    = useState(false)

  const pendingRef = useRef(null)
  // Messages for turns up to this id belong to an interrupted turn — ignore them
  const ignoreUpToRef = useRef(0)

  const { playChunk, stopPlayback } = useAudioPlayer()

  const updatePending = (next) => {
    pendingRef.current = next
    setPending(next)
  }

  const onMessage = useCallback((msg) => {
    const stale = msg.turn_id != null && msg.turn_id <= ignoreUpToRef.current

    switch (msg.type) {
      case 'barge_in': {
        // The caller started speaking: stop the agent's voice now
        stopPlayback()
        setError(null)
        if (msg.turn_id != null) ignoreUpToRef.current = msg.turn_id
        // Interrupted before the reply was complete — keep what was said so far
        const p = pendingRef.current
        if (p) {
          setEntries(prev => [...prev, { speaker: 'ai', transcript: p.transcript, response: p.partial || '', turn_id: p.turn_id }])
          updatePending(null)
        }
        break
      }
      case 'transcript':
        if (stale) break
        setError(null)
        updatePending({ turn_id: msg.turn_id, transcript: msg.text, partial: '', tools: [] })
        break
      case 'tool':
        if (stale || !pendingRef.current) break
        updatePending({ ...pendingRef.current, tools: [...pendingRef.current.tools, msg.name] })
        break
      case 'partial':
        // The reply grows sentence by sentence while the model is still writing
        if (stale || !pendingRef.current) break
        updatePending({ ...pendingRef.current, partial: msg.text })
        break
      case 'response': {
        if (stale) break
        // Read the transcript now: the state updater below runs later, after pending is cleared
        const heard = msg.speaker && msg.speaker !== 'ai' ? '' : (pendingRef.current?.transcript || '')
        setEntries(prev => [...prev, {
          speaker: msg.speaker || 'ai',
          transcript: heard,
          response: msg.text,
          intent: msg.intent,
          confidence: msg.confidence,
          summary: msg.summary,
          sentiment: msg.sentiment_score,
          sentiment_text: msg.sentiment_text,
          tools: msg.tools,
          turn_id: msg.turn_id,
        }])
        if (msg.should_escalate) setEscalated(true)
        updatePending(null)
        break
      }
      case 'metrics':
        setEntries(prev => prev.map(e => (e.turn_id === msg.turn_id ? { ...e, timings: msg.timings } : e)))
        break
      case 'audio':
        if (!stale) playChunk(msg.data)
        break
      case 'verified':
        setVerified(msg.name)
        break
      case 'language':
        setLanguage({ code: msg.locked === false ? 'auto' : msg.language, hasVoice: msg.has_voice !== false })
        break
      case 'handoff':
        setMode(msg.mode)
        break
      case 'call_summary':
        setEnding(false)
        setSummary(msg)
        setVerified(null)
        setEscalated(false)
        setMode('ai')
        break
      case 'status':
        setStatus(msg.message)
        break
      case 'error':
        setError(msg.message)
        setEnding(false)
        updatePending(null)   // a failed turn never sends a response
        break
      default:
        break
    }
  }, [playChunk, stopPlayback])

  const onClose = useCallback(() => {
    stopPlayback()
    updatePending(null)
    setEnding(false)
  }, [stopPlayback])

  const { connected, connecting, listening, startListening, stopListening, sendControl } =
    useVoiceSocket({ onMessage, onClose })

  const handleMicClick = async () => {
    setError(null)
    if (listening) stopListening()
    else {
      setSummary(null)
      await startListening()
    }
  }

  const handleEndCall = () => {
    if (listening) stopListening()
    stopPlayback()
    setEnding(true)
    sendControl({ action: 'end_call' })
  }

  const handleLanguage = (e) => {
    setLanguage({ code: e.target.value, hasVoice: true })
    sendControl({ action: 'set_language', language: e.target.value })
  }

  const handleClear = () => {
    setEntries([])
    setEscalated(false)
    setSummary(null)
  }

  return (
    <div className="h-screen overflow-hidden bg-white flex flex-col">
      <Header>
        {entries.length > 0 && (
          <button onClick={handleClear} className="text-xs text-gray-600 hover:text-gray-900 transition-colors">
            Clear log
          </button>
        )}
      </Header>

      <div className="flex-1 flex overflow-hidden">

        {/* Left — Voice Interface */}
        <div className="flex-1 flex flex-col items-center justify-center gap-6 p-8 border-r border-gray-200 overflow-y-auto">
          <div className="text-center max-w-sm">
            <h1 className="font-display text-3xl font-bold text-gray-900 mb-2">
              Customer Service
              <span className="text-violet-500"> Agent</span>
            </h1>
            <p className="text-sm text-gray-600">
              Ask about policies, check an order, cancel or return one, or ask for a human agent.
            </p>
          </div>

          {/* Call controls */}
          <div className="flex items-center gap-3 text-xs">
            <label className="flex items-center gap-2 text-gray-600">
              Language
              <select value={language.code} onChange={handleLanguage} disabled={!connected}
                className="border border-gray-300 rounded-md px-2 py-1 text-xs bg-white text-gray-900">
                {LANGUAGES.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}
              </select>
            </label>
            {verified && (
              <span className="px-2 py-1 rounded-md bg-emerald-50 text-emerald-800 font-medium">
                ✓ Verified: {verified}
              </span>
            )}
          </div>
          {!language.hasVoice && (
            <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-3 py-1.5 max-w-sm text-center">
              No voice is installed for this language, so replies are shown as text only.
            </p>
          )}

          {/* Handoff states */}
          {mode === 'human' ? (
            <div className="max-w-sm w-full bg-emerald-50 border border-emerald-300 rounded-xl px-4 py-3" role="alert">
              <p className="text-sm font-semibold text-emerald-900">A human agent is on the call</p>
              <p className="text-xs text-emerald-800 mt-0.5">Keep talking — they can hear you and will reply.</p>
            </div>
          ) : escalated && (
            <div className="max-w-sm w-full bg-amber-50 border border-amber-300 rounded-xl px-4 py-3 flex items-start gap-3" role="alert">
              <span className="mt-1 w-2 h-2 rounded-full bg-amber-500 animate-pulse shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-semibold text-amber-900">Waiting for a human agent</p>
                <p className="text-xs text-amber-800 mt-0.5">
                  This call is flagged on the Supervisor page, where an agent can take it over.
                </p>
              </div>
            </div>
          )}

          <MicButton listening={listening} onClick={handleMicClick} disabled={ending} />

          <StatusPill status={status} error={error} listening={listening} connected={connected} connecting={connecting} />

          {entries.length > 0 && !summary && (
            <button onClick={handleEndCall} disabled={ending || !connected}
              className="text-xs px-3 py-1.5 rounded-md border border-gray-300 text-gray-700 hover:bg-gray-100 disabled:opacity-50">
              {ending ? 'Summarising…' : 'End call and summarise'}
            </button>
          )}

          {summary && <CallSummaryCard summary={summary} onClose={() => setSummary(null)} />}

          {/* Turn in progress */}
          {pending && (
            <div className="max-w-sm w-full bg-gray-50 border border-gray-200 rounded-xl px-4 py-3">
              <p className="text-xs text-gray-600 mb-1 font-mono">Heard</p>
              <p className="text-sm text-gray-900">"{pending.transcript}"</p>
              {pending.partial ? (
                <p className="text-sm text-violet-800 mt-2 leading-relaxed">{pending.partial}</p>
              ) : (
                <div className="flex items-center gap-1 mt-2">
                  {[0,1,2].map(i => (
                    <div key={i} className="w-1 h-3 bg-violet-500 rounded-full animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }} />
                  ))}
                  <span className="text-xs text-gray-600 ml-2">
                    {pending.tools.length > 0 ? `${toolLabel(pending.tools[pending.tools.length - 1])}…` : 'Thinking…'}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Quick prompts */}
          {!listening && entries.length === 0 && !summary && (
            <div className="max-w-sm w-full space-y-2">
              <p className="text-xs text-gray-600 text-center mb-3">Try asking</p>
              {[
                'What is your return policy?',
                'Where is my order 1002?  (phone ends 5678)',
                'Cancel order 1003  (phone ends 2468)',
              ].map((q, i) => (
                <div key={i} className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-600 text-center">
                  "{q}"
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right — Live Log + Stats */}
        <div className="w-[26rem] flex flex-col min-h-0 p-6 bg-gray-50">
          <div className="flex items-center justify-between mb-4">
            <p className="text-xs text-gray-900 uppercase tracking-widest font-display">Live Log</p>
            <span className="text-xs font-mono text-gray-700">{entries.length} turns</span>
          </div>

          <div className="flex-1 min-h-0 flex flex-col">
            <CallLog entries={entries} />
          </div>

          <StatsBar entries={entries} />
        </div>
      </div>
    </div>
  )
}
