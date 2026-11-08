import { useEffect, useRef, useState, useCallback } from 'react'
import { AlertTriangle, Info, CheckCircle2, XCircle, RefreshCw, Inbox } from 'lucide-react'
import { errorMessage } from '../services/api'
import { dateTime, isStale, timeAgo } from '../utils/format'

export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children && <div className="row-wrap">{children}</div>}
    </div>
  )
}

export function Card({ title, actions, children, pad = true, className = '' }) {
  return (
    <section className={`card ${className}`} aria-label={typeof title === 'string' ? title : undefined}>
      {(title || actions) && (
        <div className="card-head">
          {typeof title === 'string' ? <h2>{title}</h2> : title}
          {actions && <div className="row-wrap">{actions}</div>}
        </div>
      )}
      {pad ? <div className="card-body">{children}</div> : children}
    </section>
  )
}

export function Stat({ label, value, sub, subClass = '', icon }) {
  return (
    <div className="card card-pad">
      <div className="stat-label">{icon}{label}</div>
      <div className="stat-value">{value}</div>
      {sub !== undefined && <div className={`stat-sub ${subClass}`}>{sub}</div>}
    </div>
  )
}

export function Spinner({ label = 'Loading' }) {
  return <div className="spinner" role="status" aria-label={label} />
}

export function Loading({ label = 'Loading data…' }) {
  return <div className="state"><Spinner label={label} /><span>{label}</span></div>
}

export function EmptyState({ title, children, action, icon = <Inbox size={28} className="muted" /> }) {
  return (
    <div className="state">
      {icon}
      <h3>{title}</h3>
      {children && <div style={{ maxWidth: 460 }}>{children}</div>}
      {action}
    </div>
  )
}

export function ErrorState({ error, onRetry, title = 'Could not load this data' }) {
  return (
    <div className="state" role="alert">
      <XCircle size={28} color="var(--neg)" />
      <h3>{title}</h3>
      <div style={{ maxWidth: 520 }}>{typeof error === 'string' ? error : errorMessage(error)}</div>
      {onRetry && <button className="btn" onClick={onRetry}><RefreshCw size={14} /> Try again</button>}
    </div>
  )
}

const ICONS = { error: XCircle, warning: AlertTriangle, info: Info, success: CheckCircle2 }
export function Alert({ level = 'info', children }) {
  const Icon = ICONS[level] || Info
  return <div className={`alert alert-${level}`} role={level === 'error' ? 'alert' : undefined}><Icon size={16} /><div>{children}</div></div>
}

export function Badge({ tone, children, title }) {
  return <span className={`badge ${tone ? 'badge-' + tone : ''}`} title={title}>{children}</span>
}

/** Shows when data was last fetched, flags it stale, and offers a refresh. */
export function Freshness({ at, staleAfter = 900, stale, onRefresh, refreshing, label = 'Updated' }) {
  const isOld = stale || isStale(at, staleAfter)
  return (
    <span className="freshness">
      <span className={`dot ${isOld ? 'stale' : ''}`} aria-hidden="true" />
      <span title={dateTime(at)}>
        {at ? `${label} ${timeAgo(at)}` : 'Not yet loaded'}
        {isOld && at && <strong style={{ color: 'var(--warn)' }}> · stale</strong>}
      </span>
      {onRefresh && (
        <button className="btn btn-sm" onClick={onRefresh} disabled={refreshing} aria-label="Refresh data">
          <RefreshCw size={13} className={refreshing ? 'spin' : ''} /> {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      )}
    </span>
  )
}

export function Modal({ open, title, children, onClose, footer }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement
    ref.current?.querySelector('input, button, select, textarea')?.focus()
    const onKey = (e) => e.key === 'Escape' && onClose?.()
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); prev?.focus?.() }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" ref={ref}>
        <div className="modal-head" id="modal-title">{title}</div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

export function ConfirmDialog({ open, title, message, confirmLabel = 'Confirm', danger, busy, onConfirm, onCancel }) {
  return (
    <Modal open={open} title={title} onClose={onCancel} footer={<>
      <button className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
      <button className={`btn ${danger ? 'btn-danger-solid' : 'btn-primary'}`} onClick={onConfirm} disabled={busy}>
        {busy ? 'Working…' : confirmLabel}
      </button>
    </>}>
      {message}
    </Modal>
  )
}

/** Small data-fetching hook: { data, error, loading, reload(refresh) }. */
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true, refreshing: false })
  const seq = useRef(0)
  const run = useCallback(async (refresh = false) => {
    const id = ++seq.current
    setState(s => ({ ...s, loading: !s.data, refreshing: !!s.data, error: refresh ? s.error : null }))
    try {
      const data = await fn(refresh)
      if (id === seq.current) setState({ data, error: null, loading: false, refreshing: false })
    } catch (error) {
      if (id === seq.current) setState(s => ({ ...s, error, loading: false, refreshing: false }))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { run(false) }, [run])
  return { ...state, reload: run }
}
