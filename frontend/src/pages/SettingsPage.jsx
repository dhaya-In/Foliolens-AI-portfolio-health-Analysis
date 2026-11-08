import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LogOut, Monitor, ShieldCheck, Plug } from 'lucide-react'
import { api, errorMessage } from '../services/api'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { Alert, Badge, Card, ConfirmDialog, ErrorState, Loading, Modal, PageHeader, useAsync } from '../components/ui'
import { passwordChecks } from './RegisterPage'
import { dateTime, timeAgo } from '../utils/format'

function Profile() {
  const { user, setUser } = useAuth()
  const toast = useToast()
  const [name, setName] = useState(user.display_name)
  const [busy, setBusy] = useState(false)
  const save = async (e) => {
    e.preventDefault(); setBusy(true)
    try { setUser(await api.updateProfile(name.trim())); toast('Profile updated.') }
    catch (err) { toast(errorMessage(err), 'error') } finally { setBusy(false) }
  }
  return (
    <Card title="Profile">
      <form className="stack" onSubmit={save}>
        <div className="field"><label htmlFor="p-email">Email</label><input id="p-email" className="input" value={user.email} disabled /></div>
        <div className="field"><label htmlFor="p-name">Display name</label><input id="p-name" className="input" maxLength={80} value={name} onChange={e => setName(e.target.value)} /></div>
        <p className="hint">Member since {dateTime(user.created_at)} · last sign-in {dateTime(user.last_login_at)}</p>
        <div><button className="btn btn-primary" disabled={busy || !name.trim()}>{busy ? 'Saving…' : 'Save profile'}</button></div>
      </form>
    </Card>
  )
}

function Password() {
  const { user } = useAuth()
  const toast = useToast()
  const [f, setF] = useState({ current: '', next: '', confirm: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const checks = passwordChecks(f.next, user.email)
  const submit = async (e) => {
    e.preventDefault(); setError(null)
    if (!checks.every(c => c.ok)) return setError('New password does not meet the requirements: ' + checks.filter(c => !c.ok).map(c => c.label.toLowerCase()).join(', ') + '.')
    if (f.next !== f.confirm) return setError('New passwords do not match.')
    setBusy(true)
    try { await api.changePassword(f.current, f.next); setF({ current: '', next: '', confirm: '' }); toast('Password changed. Other sessions were signed out.') }
    catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }
  return (
    <Card title={<span className="row"><ShieldCheck size={16} /> Change password</span>}>
      <form className="stack" onSubmit={submit}>
        {error && <Alert level="error">{error}</Alert>}
        <div className="field"><label htmlFor="pw-cur">Current password</label><input id="pw-cur" className="input" type="password" autoComplete="current-password" value={f.current} onChange={e => setF({ ...f, current: e.target.value })} required /></div>
        <div className="field"><label htmlFor="pw-new">New password</label><input id="pw-new" className="input" type="password" autoComplete="new-password" value={f.next} onChange={e => setF({ ...f, next: e.target.value })} required /></div>
        <div className="field"><label htmlFor="pw-conf">Confirm new password</label><input id="pw-conf" className="input" type="password" autoComplete="new-password" value={f.confirm} onChange={e => setF({ ...f, confirm: e.target.value })} required /></div>
        <div><button className="btn btn-primary" disabled={busy}>{busy ? 'Changing…' : 'Change password'}</button></div>
      </form>
    </Card>
  )
}

function Sessions() {
  const toast = useToast()
  const { data, error, loading, reload } = useAsync(() => api.sessions())
  const [busy, setBusy] = useState(false)
  const revoke = async () => {
    setBusy(true)
    try { await api.revokeOtherSessions(); toast('Signed out of all other sessions.'); reload() }
    catch (err) { toast(errorMessage(err), 'error') } finally { setBusy(false) }
  }
  return (
    <Card title={<span className="row"><Monitor size={16} /> Active sessions</span>}
          actions={<button className="btn btn-sm" onClick={revoke} disabled={busy || !data || data.length < 2}>Sign out other sessions</button>}>
      {loading ? <Loading /> : error ? <ErrorState error={error} /> : (
        <ul className="list-plain">{data.map(s => (
          <li key={s.id} className="row" style={{ alignItems: 'baseline' }}>
            <span className="spacer small" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }} title={s.user_agent}>{s.user_agent || 'Unknown device'}</span>
            {s.current && <Badge tone="pos">this device</Badge>}
            <span className="muted small">active {timeAgo(s.last_used_at)}</span>
          </li>))}
        </ul>
      )}
    </Card>
  )
}

function Integrations() {
  const { data, error, loading } = useAsync(() => api.status())
  const row = (label, s) => (
    <tr key={label}>
      <td style={{ fontWeight: 600 }}>{label}</td>
      <td>{s.provider}{s.model ? ` · ${s.model}` : ''}</td>
      <td>{s.configured ? <Badge tone="pos">configured</Badge> : <Badge tone="warn">not configured</Badge>}</td>
      <td className="small">{s.last_success ? `OK ${timeAgo(s.last_success)}` : '—'}{s.last_error && <div className="neg">Last error {timeAgo(s.last_error_at)}: {s.last_error}</div>}{s.message && <div className="muted">{s.message}</div>}</td>
    </tr>
  )
  return (
    <Card title={<span className="row"><Plug size={16} /> Data integrations</span>}>
      {loading ? <Loading /> : error ? <ErrorState error={error} /> : (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Service</th><th>Provider</th><th>Status</th><th>Health</th></tr></thead>
          <tbody>{row('Market data', data.market_data)}{row('Financial news', data.news)}{row('AI insights', data.ai)}</tbody>
        </table></div>
      )}
      <p className="hint" style={{ marginTop: 8 }}>API keys are configured on the server only and are never sent to the browser.</p>
    </Card>
  )
}

function Activity() {
  const { data, error, loading } = useAsync(() => api.activity())
  return (
    <Card title="Security & activity log">
      {loading ? <Loading /> : error ? <ErrorState error={error} /> : (
        <div style={{ maxHeight: 280, overflowY: 'auto' }}><ul className="list-plain">{data.map((a, i) => (
          <li key={i} className="row small" style={{ alignItems: 'baseline' }}>
            <Badge tone={a.security ? 'info' : undefined}>{a.kind}</Badge><span className="spacer">{a.message}</span><span className="muted">{dateTime(a.created_at)}</span>
          </li>))}</ul></div>
      )}
    </Card>
  )
}

export default function SettingsPage() {
  const { logout } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [confirmLogout, setConfirmLogout] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [pw, setPw] = useState('')
  const [delErr, setDelErr] = useState(null)
  const [busy, setBusy] = useState(false)

  const doLogout = async () => { await logout(); toast('Signed out.', 'info'); navigate('/login', { replace: true }) }
  const doDelete = async () => {
    setBusy(true); setDelErr(null)
    try { await api.deleteAccount(pw); await logout().catch(() => {}); toast('Account and all its data deleted.', 'info'); navigate('/register', { replace: true }) }
    catch (err) { setDelErr(errorMessage(err)) } finally { setBusy(false) }
  }

  return (
    <div className="stack">
      <PageHeader title="Profile & Settings" subtitle="Account, security and integrations">
        <button className="btn" onClick={() => setConfirmLogout(true)}><LogOut size={15} /> Log out</button>
      </PageHeader>
      <div className="grid grid-2"><Profile /><Password /></div>
      <div className="grid grid-2"><Sessions /><Integrations /></div>
      <Activity />
      <Card title="Danger zone">
        <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
          <div><strong>Delete account</strong><div className="muted small">Permanently deletes your account, holdings, watchlist, uploads and history.</div></div>
          <button className="btn btn-danger" onClick={() => { setPw(''); setDelErr(null); setDeleteOpen(true) }}>Delete account</button>
        </div>
      </Card>
      <ConfirmDialog open={confirmLogout} title="Log out?" message="You will need to sign in again." confirmLabel="Log out"
                     onConfirm={doLogout} onCancel={() => setConfirmLogout(false)} />
      <Modal open={deleteOpen} title="Delete your account?" onClose={() => !busy && setDeleteOpen(false)} footer={<>
        <button className="btn" onClick={() => setDeleteOpen(false)} disabled={busy}>Cancel</button>
        <button className="btn btn-danger-solid" onClick={doDelete} disabled={busy || !pw}>{busy ? 'Deleting…' : 'Delete permanently'}</button>
      </>}>
        <div className="stack" style={{ gap: 10 }}>
          <p>This cannot be undone. Enter your password to confirm.</p>
          {delErr && <Alert level="error">{delErr}</Alert>}
          <div className="field"><label htmlFor="del-pw">Password</label><input id="del-pw" className="input" type="password" autoComplete="current-password" value={pw} onChange={e => setPw(e.target.value)} /></div>
        </div>
      </Modal>
    </div>
  )
}
