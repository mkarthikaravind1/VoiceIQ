// One place for chart colours and labels, so every chart and badge agrees.
// Colours are assigned to an entity in a fixed order and never by rank —
// "FAQ" is the same blue in the pie, the bars and the badges.

export const INK = {
  primary: '#0b0b0b',
  secondary: '#52514e',
  muted: '#898781',
  grid: '#e1e0d9',
}

export const INTENTS = {
  faq:          { label: 'FAQ',           color: '#2a78d6' },
  order_lookup: { label: 'Order lookup',  color: '#eb6834' },
  order_action: { label: 'Order action',  color: '#1baf7a' },
  escalate:     { label: 'Escalation',    color: '#eda100' },
  smalltalk:    { label: 'Small talk',    color: '#e87ba4' },
  other:        { label: 'Other',         color: '#008300' },
  human_agent:  { label: 'Human agent',   color: '#6250d6' },
  unknown:      { label: 'Unclear',       color: '#898781' },
}

export const intentLabel = (intent) => INTENTS[intent]?.label || intent
export const intentColor = (intent) => INTENTS[intent]?.color || INK.muted

// Stages of one turn, in the order they happen
export const LATENCY_STAGES = [
  { key: 'endpoint_ms', label: 'Waiting for silence', color: '#c3c2b7' },
  { key: 'stt_ms',      label: 'Speech to text',      color: '#2a78d6' },
  { key: 'triage_ms',   label: 'Understanding',       color: '#eb6834' },
  { key: 'llm_ms',      label: 'Writing first sentence', color: '#1baf7a' },
  { key: 'tts_ms',      label: 'Voice synthesis',     color: '#eda100' },
]

export const SERIES_BLUE = '#2a78d6'

// What the agent is doing, in words a caller understands
export const TOOL_LABELS = {
  search_faq: 'Searching help articles',
  verify_customer: 'Verifying identity',
  get_order_status: 'Looking up the order',
  cancel_order: 'Order cancellation',
  start_return: 'Return request',
  update_shipping_address: 'Address change',
  escalate_to_human: 'Handing over to a person',
}

export const toolLabel = (name) => TOOL_LABELS[name] || name

export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिन्दी (Hindi)' },
  { code: 'ta', label: 'தமிழ் (Tamil)' },
  { code: 'auto', label: 'Auto-detect' },
]

export const fmtSeconds = (ms) => (ms == null ? '—' : `${(ms / 1000).toFixed(1)}s`)
