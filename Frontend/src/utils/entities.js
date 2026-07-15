const PATTERNS = [
  { type: 'order',   regex: /\b(order\s*#?\d{3,6}|\b\d{4,6}\b)/gi,  color: 'text-violet-600 font-semibold' },
  { type: 'email',   regex: /\b[\w.+-]+@[\w-]+\.\w+\b/gi,            color: 'text-blue-500' },
  { type: 'phone',   regex: /\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b/gi,     color: 'text-emerald-600' },
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

  matches.sort((a, b) => a.start - b.start)

  const parts = []
  let cursor = 0
  for (const match of matches) {
    if (match.start > cursor) parts.push({ text: text.slice(cursor, match.start), type: 'plain' })
    parts.push(match)
    cursor = match.end
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), type: 'plain' })
  return parts
}