import { useEffect, useRef } from 'react'
import { IntentBadge } from './IntentBadge'
import { highlightEntities } from '../utils/entities'

export function CallLog({ entries }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries])

  if (entries.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-black text-sm">
        Call transcript will appear here
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto space-y-3 pr-1">
      {entries.map((entry, i) => (
        <div key={i} className="space-y-1">
          {/* User transcript */}
          <div className="flex items-start gap-2">
            <span className="text-xs text-black mt-0.5 font-mono w-6 shrink-0">
              You {entry.sentiment != null
                ? entry.sentiment < -0.5 ? '😠'
                  : entry.sentiment < 0 ? '😐'
                    : '🙂'
                : ''}
            </span>
            <p className="text-sm text-black leading-relaxed">
              {highlightEntities(entry.transcript).map((p, j) =>
                p.type === 'plain'
                  ? <span key={j}>{p.text}</span>
                  : <span key={j} className={p.color}>{p.text}</span>
              )}
            </p>
          </div>

          {/* Agent response */}
          {entry.response && (
            <div className="flex items-start gap-2">
              <span className="text-xs text-violet-500 mt-0.5 font-mono w-6 shrink-0">AI</span>
              <div className="space-y-1">
                <p className="text-sm text-black leading-relaxed">{entry.response}</p>
                {!entry.summary?.escalated && (
                  <IntentBadge intent={entry.intent} confidence={entry.confidence} />
                )}
              </div>
            </div>
          )}

          {entry.summary && (
              <div className="mt-1 flex flex-wrap gap-1 text-xs font-mono">
                {!entry.summary.escalated && (
                  < span className="bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
                      {entry.summary.resolution}
                  </span>
            )}
            {entry.summary.order_id && (
              <span className="bg-violet-50 text-violet-600 px-1.5 py-0.5 rounded">
                #{entry.summary.order_id}
              </span>
            )}
            {entry.summary.escalated && (
              <span className="bg-red-50 text-red-500 px-1.5 py-0.5 rounded">escalated</span>
            )}
            <span className="bg-gray-100 text-gray-400 px-1.5 py-0.5 rounded">
              {entry.summary.duration_s}s
            </span>
          </div>
        )}

          {i < entries.length - 1 && (
            <div className="border-b border-gray-200 mt-2" />
          )}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
