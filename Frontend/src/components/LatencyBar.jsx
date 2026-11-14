import { LATENCY_STAGES, fmtSeconds } from '../utils/chartTheme'

// Where the time went in one turn, from the caller going quiet to the first
// audio of the reply. One stacked bar; each segment is a pipeline stage.
export function LatencyBar({ timings, showLegend = false }) {
  if (!timings || timings.ttfa_ms == null) return null

  const stages = LATENCY_STAGES
    .map(s => ({ ...s, ms: timings[s.key] || 0 }))
    .filter(s => s.ms > 0)
  const total = stages.reduce((sum, s) => sum + s.ms, 0)
  if (total === 0) return null

  return (
    <div className="mt-1.5">
      <div className="flex items-center gap-2">
        <div className="flex-1 flex gap-[2px] h-2" role="img"
          aria-label={`First audio after ${fmtSeconds(timings.ttfa_ms)}: ` +
            stages.map(s => `${s.label} ${fmtSeconds(s.ms)}`).join(', ')}>
          {stages.map((s, i) => (
            <div
              key={s.key}
              title={`${s.label}: ${fmtSeconds(s.ms)}`}
              className={`h-full min-w-[3px] ${i === 0 ? 'rounded-l' : ''} ${i === stages.length - 1 ? 'rounded-r' : ''}`}
              style={{ width: `${(s.ms / total) * 100}%`, background: s.color }}
            />
          ))}
        </div>
        <span className="text-[11px] font-mono text-gray-600 shrink-0" title="Time from end of speech to first audio">
          {fmtSeconds(timings.ttfa_ms)} to first audio
        </span>
      </div>
      {showLegend && <LatencyLegend />}
    </div>
  )
}

export function LatencyLegend() {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1.5">
      {LATENCY_STAGES.map(s => (
        <span key={s.key} className="flex items-center gap-1 text-[11px] text-gray-600">
          <span className="w-2 h-2 rounded-sm" style={{ background: s.color }} />
          {s.label}
        </span>
      ))}
    </div>
  )
}
