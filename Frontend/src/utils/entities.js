const PATTERNS = [
  { type: 'email',   regex: /\b[\w.+-]+@[\w-]+\.\w+\b/gi,            color: 'text-blue-500' },
  { type: 'phone',   regex: /\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b/gi,     color: 'text-emerald-600' },
  // Only numbers the speaker tied to an order ("order 1002", "order number 1002", "#1002"),
  // so years, prices and phone digits are not coloured as order IDs.
  { type: 'order',   regex: /\border\s*(?:id|number|no\.?)?\s*#?\s*\d{3,6}\b|#\d{3,6}\b/gi, color: 'text-violet-600 font-semibold' },
]

export function highlightEntities(text) {
  if (!text) return [{ text, type: 'plain' }]

  const matches = []
  for (const { type, regex, color } of PATTERNS) {
    let m
    regex.lastIndex = 0
    while ((m = regex.exec(text)) !== null) {
      matches.push({ start: m.index, end: m.index + m[0].length, text: m[0], type, color })
    }
  }

  if (matches.length === 0) return [{ text, type: 'plain' }]

  // Earliest first; at the same position the longer match wins
  matches.sort((a, b) => a.start - b.start || b.end - a.end)

  const parts = []
  let cursor = 0
  for (const match of matches) {
    if (match.start < cursor) continue   // overlaps one already emitted — skip, don't duplicate text
    if (match.start > cursor) parts.push({ text: text.slice(cursor, match.start), type: 'plain' })
    parts.push(match)
    cursor = match.end
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), type: 'plain' })
  return parts
}
