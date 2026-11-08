import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Pencil, Trash2, ArrowUpDown, ArrowUp, ArrowDown, Search } from 'lucide-react'
import { api, errorMessage } from '../services/api'
import { useToast } from '../context/ToastContext'
import {
  Alert, Badge, Card, ConfirmDialog, EmptyState, ErrorState, Freshness, Loading, Modal, PageHeader, useAsync,
} from '../components/ui'
import { money, num, pct, signClass, dateTime } from '../utils/format'

const COLUMNS = [
  { key: 'ticker', label: 'Stock' },
  { key: 'quantity', label: 'Qty', num: true },
  { key: 'avg_buy_price', label: 'Avg price', num: true },
  { key: 'current_price', label: 'Current', num: true },
  { key: 'market_value', label: 'Market value', num: true },
  { key: 'gain_loss', label: 'P/L', num: true },
  { key: 'gain_loss_pct', label: 'P/L %', num: true },
  { key: 'day_change_pct', label: 'Day %', num: true },
  { key: 'weight_pct', label: 'Weight', num: true },
]

export function sortHoldings(rows, key, dir) {
  return [...rows].sort((a, b) => {
    const av = a[key], bv = b[key]
    if (av === null || av === undefined) return 1
    if (bv === null || bv === undefined) return -1
    const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv
    return dir === 'asc' ? cmp : -cmp
  })
}

function HoldingForm({ initial, onSubmit, onCancel, busy, error }) {
  const [f, setF] = useState({ ticker: initial?.ticker || '', quantity: initial?.quantity ?? '', avg_buy_price: initial?.avg_buy_price ?? '' })
  const editing = !!initial
  const submit = (e) => {
    e.preventDefault()
    onSubmit({ ticker: f.ticker.trim().toUpperCase(), quantity: Number(f.quantity), avg_buy_price: Number(f.avg_buy_price) })
  }
  return (
    <form className="stack" onSubmit={submit} id="holding-form">
      {error && <Alert level="error">{error}</Alert>}
      <div className="field">
        <label htmlFor="h-ticker">Ticker</label>
        <input id="h-ticker" className="input" value={f.ticker} disabled={editing} required maxLength={25}
               placeholder="e.g. TCS, RELIANCE, AAPL" onChange={e => setF({ ...f, ticker: e.target.value })} />
        {!editing && <span className="hint">NSE listing is tried first, then BSE, then US.</span>}
      </div>
      <div className="grid grid-2">
        <div className="field">
          <label htmlFor="h-qty">Quantity</label>
          <input id="h-qty" className="input" type="number" min="0" step="any" required value={f.quantity}
                 onChange={e => setF({ ...f, quantity: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="h-avg">Average buy price</label>
          <input id="h-avg" className="input" type="number" min="0" step="any" required value={f.avg_buy_price}
                 onChange={e => setF({ ...f, avg_buy_price: e.target.value })} />
        </div>
      </div>
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : editing ? 'Save changes' : 'Add holding'}</button>
      </div>
    </form>
  )
}

export default function PortfolioPage() {
  const toast = useToast()
  const { data, error, loading, refreshing, reload } = useAsync((refresh) => api.holdings(refresh))
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState({ key: 'market_value', dir: 'desc' })
  const [editing, setEditing] = useState(null) // null | {} (new) | holding
  const [deleting, setDeleting] = useState(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState(null)

  const rows = useMemo(() => {
    if (!data) return []
    const q = query.trim().toLowerCase()
    let r = data.holdings.filter(h => !q || h.ticker.toLowerCase().includes(q) || (h.company_name || '').toLowerCase().includes(q) || (h.sector || '').toLowerCase().includes(q))
    if (filter === 'gainers') r = r.filter(h => h.gain_loss > 0)
    if (filter === 'losers') r = r.filter(h => h.gain_loss < 0)
    if (filter === 'unpriced') r = r.filter(h => h.current_price === null)
    return sortHoldings(r, sort.key, sort.dir)
  }, [data, query, filter, sort])

  const toggleSort = (key) => setSort(s => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))

  const save = async (values) => {
    setBusy(true); setFormError(null)
    try {
      if (editing?.id) {
        await api.updateHolding(editing.id, { quantity: values.quantity, avg_buy_price: values.avg_buy_price })
        toast(`${editing.ticker} updated.`)
      } else {
        const res = await api.addHolding(values)
        toast(res.warning || `${res.ticker} added${res.symbol ? ` (${res.symbol})` : ''}.`, res.warning ? 'info' : 'success')
      }
      setEditing(null)
      reload()
    } catch (err) {
      setFormError(errorMessage(err))
    } finally { setBusy(false) }
  }

  const remove = async () => {
    setBusy(true)
    try {
      await api.deleteHolding(deleting.id)
      toast(`${deleting.ticker} removed.`)
      setDeleting(null)
      reload()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally { setBusy(false) }
  }

  const header = (
    <PageHeader title="My Portfolio" subtitle="Holdings valued at live market prices">
      {data && <Freshness at={data.last_refreshed} stale={data.any_stale} staleAfter={data.stale_after_seconds}
                          onRefresh={() => reload(true)} refreshing={refreshing} label="Prices updated" />}
      <button className="btn btn-primary" onClick={() => { setFormError(null); setEditing({}) }}><Plus size={15} /> Add holding</button>
    </PageHeader>
  )

  const modal = (
    <>
      <Modal open={!!editing} title={editing?.id ? `Edit ${editing.ticker}` : 'Add holding'} onClose={() => !busy && setEditing(null)}>
        {editing && <HoldingForm initial={editing.id ? editing : null} onSubmit={save} onCancel={() => setEditing(null)} busy={busy} error={formError} />}
      </Modal>
      <ConfirmDialog open={!!deleting} title={`Remove ${deleting?.ticker}?`} danger busy={busy} confirmLabel="Remove"
                     message="This removes the holding from your portfolio. It does not place any trade."
                     onConfirm={remove} onCancel={() => setDeleting(null)} />
    </>
  )

  if (loading) return <>{header}<Loading label="Loading holdings and live prices…" /></>
  if (error && !data) return <>{header}<Card><ErrorState error={error} onRetry={() => reload()} /></Card>{modal}</>

  const t = data.totals
  return (
    <div className="stack">
      {header}
      {data.errors.length > 0 && (
        <Alert level="warning">
          <strong>Some prices are unavailable:</strong>
          <ul className="list-dot">{data.errors.map((e, i) => <li key={i}>{e.message}</li>)}</ul>
        </Alert>
      )}
      <Card pad={false} title={`${data.holdings.length} holdings · ${money(t.total_value, t.currency)}`}
            actions={<>
              <div className="row" style={{ position: 'relative' }}>
                <Search size={14} className="muted" style={{ position: 'absolute', left: 10 }} aria-hidden="true" />
                <label htmlFor="h-search" className="sr-only">Search holdings</label>
                <input id="h-search" className="input" style={{ paddingLeft: 30, width: 220 }} placeholder="Search ticker, name, sector"
                       value={query} onChange={e => setQuery(e.target.value)} />
              </div>
              <div className="seg" role="group" aria-label="Filter holdings">
                {[['all', 'All'], ['gainers', 'Gainers'], ['losers', 'Losers'], ['unpriced', 'Unpriced']].map(([k, l]) => (
                  <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>
                ))}
              </div>
            </>}>
        {data.holdings.length === 0 ? (
          <EmptyState title="No holdings yet" action={<Link className="btn btn-primary" to="/import">Import a CSV</Link>}>
            Add holdings manually or import a broker CSV.
          </EmptyState>
        ) : rows.length === 0 ? <EmptyState title="No holdings match your filters" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  {COLUMNS.map(c => (
                    <th key={c.key} className={c.num ? 'num' : ''} aria-sort={sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                      <button className="th-sort" onClick={() => toggleSort(c.key)}>
                        {c.label}
                        {sort.key === c.key ? (sort.dir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />) : <ArrowUpDown size={12} opacity={0.4} />}
                      </button>
                    </th>
                  ))}
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map(h => (
                  <tr key={h.id}>
                    <td>
                      <Link to={`/insights/${h.ticker}`} style={{ fontWeight: 600 }}>{h.ticker}</Link>
                      {h.stale && <> <Badge tone="warn" title="Price could not be refreshed">stale</Badge></>}
                      <div className="muted small">{h.company_name !== h.ticker ? h.company_name : ''}{h.sector ? ` · ${h.sector}` : ''}</div>
                    </td>
                    <td className="num">{num(h.quantity, 4)}</td>
                    <td className="num">{money(h.avg_buy_price, h.currency)}</td>
                    <td className="num" title={h.price_time ? `Market time ${dateTime(h.price_time)}` : 'No live price'}>
                      {h.current_price === null ? <Badge tone="neg">no price</Badge> : money(h.current_price, h.currency)}
                    </td>
                    <td className="num">{money(h.market_value, h.currency)}</td>
                    <td className={`num ${signClass(h.gain_loss)}`}>{money(h.gain_loss, h.currency)}</td>
                    <td className={`num ${signClass(h.gain_loss_pct)}`}>{pct(h.gain_loss_pct)}</td>
                    <td className={`num ${signClass(h.day_change_pct)}`}>{pct(h.day_change_pct)}</td>
                    <td className="num">{h.weight_pct === null ? '—' : `${h.weight_pct}%`}</td>
                    <td>
                      <div className="row" style={{ justifyContent: 'flex-end', gap: 2 }}>
                        <button className="icon-btn" aria-label={`Edit ${h.ticker}`} onClick={() => { setFormError(null); setEditing(h) }}><Pencil size={15} /></button>
                        <button className="icon-btn" aria-label={`Remove ${h.ticker}`} onClick={() => setDeleting(h)}><Trash2 size={15} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="muted small">Weights and totals include {t.currency || '—'} holdings with a live price. Prices come from the configured market-data provider; hover a price for its market timestamp.</p>
      {modal}
    </div>
  )
}
