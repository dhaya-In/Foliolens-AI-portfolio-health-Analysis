import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { TrendingUp, Check, X } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { errorMessage } from '../services/api'
import { Alert } from '../components/ui'

export function passwordChecks(pw, email = '') {
  const local = (email.split('@')[0] || '').toLowerCase()
  return [
    { ok: pw.length >= 10, label: 'At least 10 characters' },
    { ok: /[a-z]/.test(pw), label: 'A lowercase letter' },
    { ok: /[A-Z]/.test(pw), label: 'An uppercase letter' },
    { ok: /\d/.test(pw), label: 'A digit' },
    { ok: !(local.length >= 4 && pw.toLowerCase().includes(local)), label: 'Does not contain your email name' },
  ]
}

export default function RegisterPage() {
  const { register } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [form, setForm] = useState({ name: '', email: '', password: '', confirm: '' })
  const [error, setError] = useState(null)
  useEffect(() => { document.title = 'Create account · FolioLens' }, [])
  const [busy, setBusy] = useState(false)
  const checks = useMemo(() => passwordChecks(form.password, form.email), [form.password, form.email])
  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    if (!form.email || !form.password) return setError('Email and password are required.')
    if (!checks.every(c => c.ok)) return setError('Password does not meet the requirements.')
    if (form.password !== form.confirm) return setError('Passwords do not match.')
    setBusy(true)
    setError(null)
    try {
      await register(form.email.trim(), form.password, form.name.trim())
      toast('Account created. Welcome to FolioLens!')
      navigate('/import', { replace: true })
    } catch (err) {
      setError(errorMessage(err, 'Registration failed.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="brand"><span className="brand-mark"><TrendingUp size={17} color="#fff" /></span>
          <span>Folio<span className="accent">Lens</span></span></div>
        <div className="card card-pad stack">
          <div>
            <h1 style={{ fontSize: 20 }}>Create your account</h1>
            <p className="muted">Each account has its own private portfolio.</p>
          </div>
          {error && <Alert level="error">{error}</Alert>}
          <form className="stack" onSubmit={submit} noValidate>
            <div className="field">
              <label htmlFor="name">Display name <span className="muted">(optional)</span></label>
              <input id="name" className="input" autoComplete="name" maxLength={80} value={form.name} onChange={set('name')} />
            </div>
            <div className="field">
              <label htmlFor="email">Email</label>
              <input id="email" className="input" type="email" autoComplete="email" value={form.email} onChange={set('email')} required />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input id="password" className="input" type="password" autoComplete="new-password" value={form.password}
                     onChange={set('password')} required aria-describedby="pw-rules" />
              <ul id="pw-rules" className="list-plain small" style={{ gap: 2, marginTop: 4 }}>
                {checks.map(c => (
                  <li key={c.label} className={c.ok ? 'pos' : 'muted'} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    {c.ok ? <Check size={13} /> : <X size={13} />} {c.label}
                  </li>
                ))}
              </ul>
            </div>
            <div className="field">
              <label htmlFor="confirm">Confirm password</label>
              <input id="confirm" className="input" type="password" autoComplete="new-password" value={form.confirm}
                     onChange={set('confirm')} required aria-invalid={!!form.confirm && form.confirm !== form.password} />
            </div>
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Creating account…' : 'Create account'}</button>
          </form>
          <p className="small muted" style={{ textAlign: 'center' }}>Already registered? <Link to="/login">Sign in</Link></p>
        </div>
      </div>
    </div>
  )
}
