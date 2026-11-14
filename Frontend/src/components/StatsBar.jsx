import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { SentimentChart } from './SentimentChart'
import { LatencyLegend } from './LatencyBar'
import { intentColor, intentLabel, fmtSeconds } from '../utils/chartTheme'

export function StatsBar({ entries }) {
  const aiTurns = entries.filter(e => e.speaker === 'ai' || !e.speaker)

  // Tally intents
  const counts = aiTurns.reduce((acc, e) => {
    if (e.intent) acc[e.intent] = (acc[e.intent] || 0) + 1
    return acc
  }, {})
  const data = Object.entries(counts).map(([intent, value]) => ({
    name: intentLabel(intent), value, color: intentColor(intent),
  }))

  // Time from the caller going quiet to the first audio of the reply
  const timed = aiTurns.filter(e => e.timings?.ttfa_ms != null)
  const avgTtfa = timed.length > 0
    ? timed.reduce((s, e) => s + e.timings.ttfa_ms, 0) / timed.length
    : null

  return (
    <div className="border-t border-gray-200 pt-4 mt-4 space-y-4">
      <div>
        <p className="text-xs text-gray-600 uppercase tracking-widest mb-2 font-display">Caller sentiment</p>
        <SentimentChart turns={aiTurns} />
      </div>

      <div>
        <p className="text-xs text-gray-600 uppercase tracking-widest mb-3 font-display">Session Stats</p>
        <div className="flex items-center gap-4">
          {data.length > 0 ? (
            <div className="w-16 h-16 shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data} dataKey="value" cx="50%" cy="50%" innerRadius={16} outerRadius={28}
                    stroke="#f9fafb" strokeWidth={2} isAnimationActive={false}>
                    {data.map((d, i) => <Cell key={i} fill={d.color} />)}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: '#ffffff', border: '1px solid #e5e7eb', borderRadius: 6, fontSize: 11 }}
                    itemStyle={{ color: '#374151' }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="w-16 h-16 rounded-full border-2 border-gray-200 flex items-center justify-center">
              <span className="text-gray-400 text-xs">—</span>
            </div>
          )}

          <div className="flex-1 space-y-1">
            {data.map((d, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full" style={{ background: d.color }} />
                  <span className="text-gray-600">{d.name}</span>
                </div>
                <span className="font-mono text-gray-800">{d.value}</span>
              </div>
            ))}
          </div>

          <div className="text-right shrink-0">
            <p className="text-2xl font-display font-semibold text-gray-900">{aiTurns.length}</p>
            <p className="text-xs text-gray-600">turns</p>
            <p className="text-sm font-mono text-gray-800 mt-1">{fmtSeconds(avgTtfa)}</p>
            <p className="text-xs text-gray-600">avg to first audio</p>
          </div>
        </div>
        {timed.length > 0 && <LatencyLegend />}
      </div>
    </div>
  )
}
