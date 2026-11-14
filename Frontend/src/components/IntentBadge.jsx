import { intentColor, intentLabel } from '../utils/chartTheme'

// The dot carries the colour; the text stays in normal ink so it is readable.
export function IntentBadge({ intent, confidence }) {
  if (!intent) return null

  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-mono text-gray-600">
      <span className="w-2 h-2 rounded-full" style={{ background: intentColor(intent) }} />
      {intentLabel(intent)}
      {confidence != null && (
        <span className="text-gray-500 ml-0.5">{(confidence * 100).toFixed(0)}%</span>
      )}
    </span>
  )
}
