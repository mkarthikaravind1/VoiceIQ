import { useState, useCallback, useRef } from 'react'
import { useVoiceSocket } from '../hooks/useVoiceSocket'
import { useAudioPlayer } from '../hooks/useAudioPlayer'
import { CallLog } from '../components/CallLog'
import { StatsBar } from '../components/StatsBar'

// ── Mic Button with animated rings ───────────────────────────────────────────
function MicButton({ listening, onClick, disabled }) {
  return (
    <div className="relative flex items-center justify-center w-40 h-40">
      {/* Outer ring */}
      {listening && (
        <>
          <div className="absolute inset-0 rounded-full border-2 border-violet-600/40 ring-pulse-2" />
          <div className="absolute inset-3 rounded-full border-2 border-violet-500/50 ring-pulse-1" />
        </>
      )}
      {/* Button */}
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
          // Stop icon
          <svg className="w-8 h-8 text-white" fill="currentColor" viewBox="0 0 24 24">
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
        ) : (
          // Mic icon
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

  const color = error ? 'text-red-600'
    : listening ? 'text-violet-500'
    : connected ? 'text-gray-500'
    : 'text-gray-500'

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

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function VoiceAgent() {
  const [entries,       setEntries]       = useState([])
  const [status,        setStatus]        = useState('')
  const [error,         setError]         = useState(null)
  const [escalated,     setEscalated]     = useState(false)
  const [pendingEntry,  setPendingEntry]  = useState(null)
  const startTimeRef = useRef(null)
  const pendingEntryRef = useRef(null)
  // Messages for turns up to this id belong to an interrupted turn — ignore them
  const ignoreUpToRef = useRef(0)

  const { playChunk, stopPlayback } = useAudioPlayer()

  const isStale = (msg) => msg.turn_id != null && msg.turn_id <= ignoreUpToRef.current

  const clearPending = () => {
    pendingEntryRef.current = null
    setPendingEntry(null)
  }

  // Server heard the user start speaking (barge-in): stop the agent's voice now.
  const onBargeIn = useCallback((msg) => {
    stopPlayback()
    setError(null)
    if (msg.turn_id != null) ignoreUpToRef.current = msg.turn_id
    // Interrupted before the agent answered — keep what the user said in the log
    const pending = pendingEntryRef.current
    if (pending) {
      setEntries(prev => [...prev, { transcript: pending.transcript, response: '', ts: Date.now() }])
      clearPending()
    }
  }, [stopPlayback])

  const onTranscript = useCallback((msg) => {
    if (isStale(msg)) return
    setError(null)
    startTimeRef.current = Date.now()
    pendingEntryRef.current = { transcript: msg.text, language: msg.language }
    setPendingEntry({ transcript: msg.text, language: msg.language })
  }, [])

  const onResponse = useCallback((msg) => {
    if (isStale(msg)) return
    const latency = startTimeRef.current ? Date.now() - startTimeRef.current : null
    setEntries(prev => [...prev, {
      transcript: pendingEntryRef.current?.transcript || '',
      response: msg.text,
      intent: msg.intent,
      confidence: msg.confidence,
      latency,
      summary: msg.summary,
      sentiment: msg.sentiment_score,
      ts: Date.now(),
    }])
    if (msg.should_escalate) setEscalated(true)
    clearPending()
  }, [])

  const onStatus = useCallback((msg) => setStatus(msg.message), [])
  const onError  = useCallback((msg) => {
    setError(msg.message)
    // A failed turn never sends a response — don't leave "Processing..." stuck
    clearPending()
  }, [])
  const onClose = useCallback(() => {
    stopPlayback()
    clearPending()
  }, [stopPlayback])
  const onAudio = useCallback((msg) => {
    if (!isStale(msg)) playChunk(msg.data)
  }, [playChunk])

  const { connected, connecting, listening, startListening, stopListening } =
    useVoiceSocket({ onTranscript, onResponse, onStatus, onError, onAudio, onBargeIn, onClose })

  const handleMicClick = async () => {
    setError(null)
    if (listening) stopListening()
    else await startListening()
  }

  const handleClear = () => {
    setEntries([])
    setEscalated(false)
  }

  return (
    <div className="h-screen overflow-hidden bg-white flex flex-col">
      {/* Header */}
      <header className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-violet-600 flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 1a4 4 0 0 1 4 4v6a4 4 0 0 1-8 0V5a4 4 0 0 1 4-4zm-7 10a1 1 0 0 1 1 1 6 6 0 1 0 12 0 1 1 0 0 1 2 0 8 8 0 0 1-7 7.938V21h2a1 1 0 0 1 0 2H9a1 1 0 0 1 0-2h2v-2.062A8 8 0 0 1 4 12a1 1 0 0 1 1-1z" />
            </svg>
          </div>
          <span className="font-display font-semibold text-lg tracking-tight">VoiceIQ</span>
          <span className="text-xs text-gray-500 font-mono">v1.0</span>
        </div>
        <div className="flex items-center gap-3">
          {entries.length > 0 && (
            <button onClick={handleClear} className="text-xs text-gray-600 hover:text-gray-900 transition-colors">
              Clear log
            </button>
          )}
          <a href="/docs" target="_blank" rel="noreferrer" className="text-xs text-gray-600 hover:text-violet-600 transition-colors font-mono">
            API docs ↗
          </a>
        </div>
      </header>

      {/* Body */}
      <div className="flex-1 flex overflow-hidden">

        {/* Left — Voice Interface */}
        <div className="flex-1 flex flex-col items-center justify-center gap-8 p-8 border-r border-gray-200">
          <div className="text-center max-w-xs">
            <h1 className="font-display text-3xl font-bold text-gray-900 mb-2">
              Customer Service
              <span className="text-violet-500"> Agent</span>
            </h1>
            <p className="text-sm text-gray-500">
              Ask FAQs related to orders, returns, shipping or say "Human Agent" to escalate.
            </p>
          </div>

          {/* Escalation alert */}
          {escalated && (
            <div className="max-w-sm w-full bg-amber-50 border border-amber-300 rounded-xl px-4 py-3 flex items-start gap-3" role="alert">
              <span className="mt-1 w-2 h-2 rounded-full bg-amber-500 animate-pulse shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-semibold text-amber-900">Escalated to a human agent</p>
                <p className="text-xs text-amber-800 mt-0.5">
                  This call has been flagged for handoff. A support agent will take over from here.
                </p>
              </div>
              <button onClick={() => setEscalated(false)} className="text-xs text-amber-800 hover:text-amber-950">
                Dismiss
              </button>
            </div>
          )}

          <MicButton
            listening={listening}
            onClick={handleMicClick}
            disabled={false}
          />

          <StatusPill status={status} error={error} listening={listening} connected={connected} connecting={connecting} />

          {/* Pending transcript */}
          {pendingEntry && (
            <div className="max-w-sm w-full bg-gray-50 border border-gray-200 rounded-xl px-4 py-3">
              <p className="text-xs text-gray-500 mb-1 font-mono">Heard</p>
              <p className="text-sm text-gray-800">"{pendingEntry.transcript}"</p>
              <div className="flex gap-1 mt-2">
                {[0,1,2].map(i => (
                  <div key={i} className="w-1 h-3 bg-violet-500 rounded-full animate-bounce"
                    style={{ animationDelay: `${i * 0.15}s` }} />
                ))}
                <span className="text-xs text-gray-600 ml-2">Processing...</span>
              </div>
            </div>
          )}

          {/* Quick prompts */}
          {!listening && entries.length === 0 && (
            <div className="max-w-sm w-full space-y-2">
              <p className="text-xs text-gray-600 text-center mb-3">Try asking</p>
              {[
                'What is your return policy?',
                'Check my order ID 1002',
                'How long does shipping take?',
              ].map((q, i) => (
                <div key={i} className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-600 text-center">
                  "{q}"
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right — Live Log + Stats */}
        <div className="w-96 flex flex-col min-h-0 p-6 bg-gray-50">
          <div className="flex items-center justify-between mb-4">
            <p className="text-xs text-black uppercase tracking-widest font-display">Live Log</p>
            <span className="text-xs font-mono text-black">{entries.length} calls</span>
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
