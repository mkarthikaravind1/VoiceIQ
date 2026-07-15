const INTENT_COLORS = {
  faq:          'text-violet-400',
  order_lookup: 'text-blue-400',
  escalate:     'text-amber-400',
  unknown:      'text-gray-400',
}

const INTENT_LABELS = {
  faq:          'FAQ',
  order_lookup: 'Order Lookup',
  escalate:     'Escalation',
  unknown:      'Unknown',
}

export function IntentBadge({ intent, confidence }) {
  if (!intent) return null
  const color = INTENT_COLORS[intent] || 'text-gray-400'
  const label = INTENT_LABELS[intent] || intent

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-mono ${color}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-80" />
      {label}
      {confidence != null && (
        <span className="opacity-50 ml-1">{(confidence * 100).toFixed(0)}%</span>
      )}
    </span>
  )
}
