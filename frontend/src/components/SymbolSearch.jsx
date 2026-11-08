import { useEffect, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { api } from '../services/api'

/** Company / ticker search backed by the market-data provider's search endpoint. */
export default function SymbolSearch({ onSelect, placeholder = 'Search company or ticker (e.g. Infosys, TCS, AAPL)', id = 'symbol-search' }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState(null)
  const timer = useRef(null)
  const box = useRef(null)

  useEffect(() => {
    clearTimeout(timer.current)
    if (q.trim().length < 2) { setResults([]); setStatus(null); return }
    timer.current = setTimeout(async () => {
      setStatus('loading')
      try {
        const r = await api.search(q.trim())
        setResults(r.results); setStatus(r.results.length ? null : 'empty'); setOpen(true)
      } catch { setStatus('error'); setOpen(true) }
    }, 350)
    return () => clearTimeout(timer.current)
  }, [q])

  useEffect(() => {
    const close = (e) => box.current && !box.current.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const choose = (sym) => { setOpen(false); setQ(''); onSelect(sym) }
  const submit = (e) => { e.preventDefault(); if (q.trim()) choose(q.trim().toUpperCase()) }

  return (
    <form onSubmit={submit} ref={box} style={{ position: 'relative', flex: 1, minWidth: 240 }} role="search">
      <label htmlFor={id} className="sr-only">Search company or ticker</label>
      <Search size={15} className="muted" style={{ position: 'absolute', left: 11, top: 11 }} aria-hidden="true" />
      <input id={id} className="input" style={{ paddingLeft: 32 }} value={q} placeholder={placeholder} autoComplete="off"
             onChange={e => setQ(e.target.value)} onFocus={() => results.length && setOpen(true)}
             aria-autocomplete="list" aria-controls={`${id}-list`} aria-expanded={open} />
      {open && (
        <ul className="search-results" id={`${id}-list`} role="listbox">
          {status === 'loading' && <li className="muted small" style={{ padding: 10 }}>Searching…</li>}
          {status === 'empty' && <li className="muted small" style={{ padding: 10 }}>No matches. Press Enter to try “{q.toUpperCase()}”.</li>}
          {status === 'error' && <li className="small" style={{ padding: 10, color: 'var(--neg)' }}>Search is unavailable right now. Press Enter to analyse the ticker directly.</li>}
          {results.map(r => (
            <li key={r.symbol} role="option" aria-selected="false">
              <button type="button" onClick={() => choose(r.symbol)}>
                <strong>{r.symbol}</strong><span className="spacer">{r.name}</span><span className="muted small">{r.exchange}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </form>
  )
}
