import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell, Pencil, Trash2, Newspaper } from 'lucide-react'
import { api, errorMessage } from '../services/api'
import { useToast } from '../context/ToastContext'
import { Alert, Badge, Card, ConfirmDialog, EmptyState, ErrorState, Freshness, Loading, Modal, PageHeader, useAsync } from '../components/ui'
import SymbolSearch from '../components/SymbolSearch'
import NewsList from '../components/NewsList'
import { dateTime, money, pct, signClass } from '../utils/format'

function AlertForm({ item, onSave, onCancel, busy, error }) {
  const [f, setF] = useState({ note: item.note || '', alert_above: item.alert_above ?? '', alert_below: item.alert_below ?? '' })
  const submit = (e) => {
    e.preventDefault()
    onSave({ note: f.note, alert_above: f.alert_above === '' ? null : Number(f.alert_above), alert_below: f.alert_below === '' ? null : Number(f.alert_below) })
  }
  return (
    <form className="stack" onSubmit={submit}>
      {error && <Alert level="error">{error}</Alert>}
      <div className="grid grid-2">
        <div className="field"><label htmlFor="w-above">Alert when price ≥</label>
          <input id="w-above" className="input" type="number" min="0" step="any" value={f.alert_above} onChange={e => setF({ ...f, alert_above: e.target.value })} /></div>
        <div className="field"><label htmlFor="w-below">Alert when price ≤</label>
          <input id="w-below" className="input" type="number" min="0" step="any" value={f.alert_below} onChange={e => setF({ ...f, alert_below: e.target.value })} /></div>
      </div>
      <div className="field"><label htmlFor="w-note">Note</label>
        <input id="w-note" className="input" maxLength={200} value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></div>
      <p className="hint">Alerts are checked whenever you open FolioLens (Overview and this page); no emails are sent.</p>
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
      </div>
    </form>
  )
}

function SymbolNews({ symbol }) {
  const { data, error, loading } = useAsync(() => api.news({ symbol, limit: 6 }), [symbol])
  if (loading) return <Loading label="Loading news…" />
  if (error) return <ErrorState error={error} />
  return <><NewsList articles={data.articles} /><p className="hint">Fetched {dateTime(data.fetched_at)} from {data.provider}.</p></>
}

export default function WatchlistPage() {
  const toast = useToast()
  const { data, error, loading, refreshing, reload } = useAsync((refresh) => api.watchlist(refresh))
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [newsFor, setNewsFor] = useState(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState(null)
  const [adding, setAdding] = useState(false)

  const add = async (symbol) => {
    setAdding(true)
    try { const r = await api.addWatch({ symbol }); toast(`${r.symbol} added to watchlist.`); reload() }
    catch (err) { toast(errorMessage(err), 'error') } finally { setAdding(false) }
  }
  const save = async (values) => {
    setBusy(true); setFormError(null)
    try { await api.updateWatch(editing.id, values); toast('Alert saved.'); setEditing(null); reload() }
    catch (err) { setFormError(errorMessage(err)) } finally { setBusy(false) }
  }
  const remove = async () => {
    setBusy(true)
    try { await api.deleteWatch(deleting.id); toast(`${deleting.symbol} removed.`); setDeleting(null); reload() }
    catch (err) { toast(errorMessage(err), 'error') } finally { setBusy(false) }
  }

  const latest = data?.items.map(i => i.quote?.fetched_at).filter(Boolean).sort().pop()
  return (
    <div className="stack">
      <PageHeader title="Market Watchlist" subtitle="Track stocks you don't own yet, with price alerts and news">
        {data && <Freshness at={latest} stale={data.items.some(i => i.quote?.stale)} onRefresh={() => reload(true)} refreshing={refreshing} label="Prices updated" />}
      </PageHeader>
      <Card><div className="row-wrap"><SymbolSearch id="watch-search" onSelect={add} placeholder="Add a stock: search company or ticker" />{adding && <span className="muted small">Adding…</span>}</div></Card>
      {loading ? <Loading /> : error && !data ? <Card><ErrorState error={error} onRetry={() => reload()} /></Card> : (
        <Card pad={false} title={`${data.items.length} watched`}>
          {data.items.length === 0 ? <EmptyState title="Your watchlist is empty">Search above to add a stock.</EmptyState> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Stock</th><th className="num">Price</th><th className="num">Change</th><th>Alerts</th><th>Note</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>{data.items.map(i => (
                  <tr key={i.id}>
                    <td><Link to={`/insights/${i.symbol}`} style={{ fontWeight: 600 }}>{i.symbol}</Link><div className="muted small">{i.quote?.name}</div></td>
                    <td className="num" title={i.quote ? `Market time ${dateTime(i.quote.market_time)}` : ''}>
                      {i.quote ? money(i.quote.price, i.quote.currency) : <Badge tone="neg" title={i.error?.message}>unavailable</Badge>}
                      {i.quote?.stale && <> <Badge tone="warn">stale</Badge></>}
                    </td>
                    <td className={`num ${signClass(i.quote?.change_pct)}`}>{pct(i.quote?.change_pct)}</td>
                    <td className="small">
                      {i.alert_above != null && <div>≥ {money(i.alert_above, i.quote?.currency)} {i.alerts_triggered.includes('above') && <Badge tone="info"><Bell size={11} /> reached</Badge>}</div>}
                      {i.alert_below != null && <div>≤ {money(i.alert_below, i.quote?.currency)} {i.alerts_triggered.includes('below') && <Badge tone="info"><Bell size={11} /> reached</Badge>}</div>}
                      {i.alert_above == null && i.alert_below == null && <span className="muted">none</span>}
                    </td>
                    <td className="small muted">{i.note}</td>
                    <td><div className="row" style={{ justifyContent: 'flex-end', gap: 2 }}>
                      <button className="icon-btn" aria-label={`News for ${i.symbol}`} onClick={() => setNewsFor(i.symbol)}><Newspaper size={15} /></button>
                      <button className="icon-btn" aria-label={`Edit alerts for ${i.symbol}`} onClick={() => { setFormError(null); setEditing(i) }}><Pencil size={15} /></button>
                      <button className="icon-btn" aria-label={`Remove ${i.symbol}`} onClick={() => setDeleting(i)}><Trash2 size={15} /></button>
                    </div></td>
                  </tr>))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
      {newsFor && <Card title={`News · ${newsFor}`} actions={<button className="btn btn-sm" onClick={() => setNewsFor(null)}>Close</button>}><SymbolNews symbol={newsFor} /></Card>}
      <Modal open={!!editing} title={`Alerts · ${editing?.symbol}`} onClose={() => !busy && setEditing(null)}>
        {editing && <AlertForm item={editing} onSave={save} onCancel={() => setEditing(null)} busy={busy} error={formError} />}
      </Modal>
      <ConfirmDialog open={!!deleting} title={`Remove ${deleting?.symbol}?`} danger busy={busy} confirmLabel="Remove"
                     message="It will be removed from your watchlist with its alerts." onConfirm={remove} onCancel={() => setDeleting(null)} />
    </div>
  )
}
