import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'

const COLORS = {
  faq:          '#8b5cf6',
  order_lookup: '#60a5fa',
  escalate:     '#fbbf24',
  unknown:      '#4b5563',
}

const LABELS = {
  faq:          'FAQ',
  order_lookup: 'Orders',
  escalate:     'Escalated',
  unknown:      'Unknown',
}

export function StatsBar({ entries }) {
  // Tally intents
  const counts = entries.reduce((acc, e) => {
    if (e.intent) acc[e.intent] = (acc[e.intent] || 0) + 1
    return acc
  }, {})

  const data = Object.entries(counts).map(([intent, value]) => ({
    name:  LABELS[intent] || intent,
    value,
    color: COLORS[intent] || '#6b7280',
  }))

  const avgLatency = entries.length > 0
    ? (entries.reduce((s, e) => s + (e.latency || 0), 0) / entries.length / 1000).toFixed(1)
    : '—'

  return (
    <div className="border-t border-gray-200 pt-4 mt-4">
      <p className="text-xs text-gray-500 uppercase tracking-widest mb-3 font-display">Session Stats</p>
      <div className="flex items-center gap-4">
        {/* Mini pie */}
        {data.length > 0 ? (
          <div className="w-16 h-16 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={data} dataKey="value" cx="50%" cy="50%" innerRadius={16} outerRadius={28} strokeWidth={0}>
                  {data.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#0f0f1a', border: '1px solid #252545', borderRadius: 6, fontSize: 11 }}
                  itemStyle={{ color: '#e5e7eb' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="w-16 h-16 rounded-full border-2 border-surface-600 flex items-center justify-center">
            <span className="text-gray-700 text-xs">—</span>
          </div>
        )}

        {/* Counts */}
        <div className="flex-1 space-y-1">
          {data.map((d, i) => (
            <div key={i} className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: d.color }} />
                <span className="text-gray-400">{d.name}</span>
              </div>
              <span className="font-mono text-gray-300">{d.value}</span>
            </div>
          ))}
        </div>

        {/* Metrics */}
        <div className="text-right shrink-0">
          <p className="text-2xl font-display font-semibold text-violet-400">{entries.length}</p>
          <p className="text-xs text-gray-600">calls</p>
          <p className="text-sm font-mono text-gray-300 mt-1">{avgLatency}s</p>
          <p className="text-xs text-gray-600">avg</p>
        </div>
      </div>
    </div>
  )
}
