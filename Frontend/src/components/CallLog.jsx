import { useEffect, useRef } from 'react'
import { IntentBadge } from './IntentBadge'
import { LatencyBar } from './LatencyBar'
import { highlightEntities } from '../utils/entities'
import { toolLabel } from '../utils/chartTheme'

const SPEAKERS = {
  ai:     { label: 'AI',    className: 'text-violet-600' },
  human:  { label: 'Agent', className: 'text-emerald-700' },
  system: { label: 'Info',  className: 'text-gray-500' },
}

function sentimentFace(score) {
  if (score == null) return ''
  return score < -0.5 ? '😠' : score < 0 ? '😐' : '🙂'
}

export function CallLog({ entries, showLatency = true }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries])

  if (entries.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
        Call transcript will appear here
      </div>
    )
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto space-y-3 pr-1">
      {entries.map((entry, i) => {
        const speaker = SPEAKERS[entry.speaker] || SPEAKERS.ai
        return (
          <div key={i} className="space-y-1">
            {/* Caller */}
            {entry.transcript && (
              <div className="flex items-start gap-2">
                <span className="text-xs text-gray-900 mt-0.5 font-mono w-10 shrink-0">
                  You {sentimentFace(entry.sentiment)}
                </span>
                <p className="text-sm text-gray-900 leading-relaxed">
                  {highlightEntities(entry.transcript).map((p, j) =>
                    p.type === 'plain'
                      ? <span key={j}>{p.text}</span>
                      : <span key={j} className={p.color}>{p.text}</span>
                  )}
                </p>
              </div>
            )}

            {/* Reply */}
            {entry.response && (
              <div className="flex items-start gap-2">
                <span className={`text-xs mt-0.5 font-mono w-10 shrink-0 ${speaker.className}`}>{speaker.label}</span>
                <div className="space-y-1 min-w-0 flex-1">
                  <p className="text-sm text-gray-900 leading-relaxed">{entry.response}</p>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    {entry.speaker !== 'human' && entry.speaker !== 'system' && (
                      <IntentBadge intent={entry.intent} confidence={entry.confidence} />
                    )}
                    {(entry.tools || []).map((tool, j) => (
                      <span key={j} className="bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded text-[11px] font-mono">
                        {toolLabel(tool)}
                      </span>
                    ))}
                    {entry.summary?.resolution === 'action_done' && (
                      <span className="bg-emerald-50 text-emerald-800 px-1.5 py-0.5 rounded text-[11px] font-mono">✓ done</span>
                    )}
                    {entry.summary?.escalated && (
                      <span className="bg-amber-50 text-amber-900 px-1.5 py-0.5 rounded text-[11px] font-mono">escalated</span>
                    )}
                  </div>
                  {showLatency && <LatencyBar timings={entry.timings} />}
                </div>
              </div>
            )}

            {i < entries.length - 1 && <div className="border-b border-gray-200 mt-2" />}
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}
