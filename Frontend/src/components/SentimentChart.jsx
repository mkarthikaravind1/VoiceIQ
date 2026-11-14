import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from 'recharts'
import { INK, SERIES_BLUE } from '../utils/chartTheme'

function SentimentTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="bg-white border border-gray-200 rounded-md px-2 py-1.5 text-[11px] shadow-sm max-w-[220px]">
      <p className="font-semibold text-gray-900">Turn {p.turn}: {p.sentiment.toFixed(2)}</p>
      {p.sentiment_text != null && p.sentiment_text !== p.sentiment && (
        <p className="text-gray-600">Words alone: {p.sentiment_text.toFixed(2)} · voice raised</p>
      )}
      {p.transcript && <p className="text-gray-600 truncate">"{p.transcript}"</p>}
    </div>
  )
}

// Caller sentiment turn by turn (words and voice combined), -1 to +1.
// Two turns in a row under the dashed line trigger a handoff.
export function SentimentChart({ turns, height = 90 }) {
  const data = turns
    .filter(t => t.sentiment != null)
    .map((t, i) => ({ turn: i + 1, sentiment: t.sentiment, sentiment_text: t.sentiment_text, transcript: t.transcript }))

  if (data.length === 0) {
    return <p className="text-xs text-gray-500">Sentiment appears after the first turn.</p>
  }

  return (
    <div style={{ height }} role="img"
      aria-label={`Caller sentiment per turn: ${data.map(d => d.sentiment.toFixed(1)).join(', ')}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -28 }}>
          <XAxis dataKey="turn" tick={{ fontSize: 10, fill: INK.muted }} tickLine={false} axisLine={{ stroke: INK.grid }} />
          <YAxis domain={[-1, 1]} ticks={[-1, 0, 1]} tick={{ fontSize: 10, fill: INK.muted }} tickLine={false} axisLine={false} />
          <ReferenceLine y={0} stroke={INK.grid} />
          <ReferenceLine y={-0.5} stroke={INK.muted} strokeDasharray="3 3"
            label={{ value: 'handoff line', position: 'insideBottomRight', fontSize: 9, fill: INK.muted }} />
          <Tooltip content={<SentimentTooltip />} cursor={{ stroke: INK.grid }} />
          <Line type="monotone" dataKey="sentiment" stroke={SERIES_BLUE} strokeWidth={2}
            dot={{ r: 4, fill: SERIES_BLUE, stroke: '#fff', strokeWidth: 2 }}
            activeDot={{ r: 5 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
