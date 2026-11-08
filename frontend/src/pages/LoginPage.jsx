import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { TrendingUp } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { errorMessage } from '../services/api'
import { Alert } from '../components/ui'

export default function LoginPage() {
  const { login, expired } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  useEffect(() => { document.title = 'Sign in · FolioLens' }, [])
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (!email || !password) { setError('Enter your email and password.'); return }
    setBusy(true)
    setError(null)
    try {
      await login(email.trim(), password)
      navigate(location.state?.from || '/', { replace: true })
    } catch (err) {
      setError(errorMessage(err, 'Sign-in failed.'))
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
            <h1 style={{ fontSize: 20 }}>Sign in</h1>
            <p className="muted">Access your private portfolio analysis.</p>
          </div>
          {expired && <Alert level="warning">Your session expired. Please sign in again.</Alert>}
          {error && <Alert level="error">{error}</Alert>}
          <form className="stack" onSubmit={submit} noValidate>
            <div className="field">
              <label htmlFor="email">Email</label>
              <input id="email" className="input" type="email" autoComplete="email" value={email}
                     onChange={e => setEmail(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input id="password" className="input" type="password" autoComplete="current-password" value={password}
                     onChange={e => setPassword(e.target.value)} required />
            </div>
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
          </form>
          <p className="small muted" style={{ textAlign: 'center' }}>
            No account yet? <Link to="/register">Create one</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
