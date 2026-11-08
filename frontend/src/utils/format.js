const SYMBOLS = { INR: '₹', USD: '$', EUR: '€', GBP: '£', JPY: '¥' }

export function money(value, currency, { compact = false, digits = 2 } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const opts = compact
    ? { notation: 'compact', maximumFractionDigits: 1 }
    : { minimumFractionDigits: digits, maximumFractionDigits: digits }
  const locale = currency === 'INR' ? 'en-IN' : 'en-US'
  const n = new Intl.NumberFormat(locale, opts).format(value)
  const sym = SYMBOLS[currency] ?? (currency ? currency + ' ' : '')
  return (value < 0 ? '-' : '') + sym + n.replace('-', '')
}

export function num(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(value)
}

export function pct(value, { sign = true, digits = 2 } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${sign && value > 0 ? '+' : ''}${value.toFixed(digits)}%`
}

export function signClass(value) {
  if (value === null || value === undefined) return ''
  return value > 0 ? 'pos' : value < 0 ? 'neg' : ''
}

export function dateTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function timeAgo(value, now = Date.now()) {
  if (!value) return 'never'
  const s = Math.round((now - new Date(value).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}

export function isStale(value, staleAfterSeconds = 900, now = Date.now()) {
  if (!value) return true
  return (now - new Date(value).getTime()) / 1000 > staleAfterSeconds
}
