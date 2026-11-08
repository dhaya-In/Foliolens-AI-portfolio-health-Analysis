import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api, ensureCsrf, setSessionExpiredHandler } from '../services/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [expired, setExpired] = useState(false)

  const userRef = useRef(null)
  userRef.current = user

  useEffect(() => {
    // Only show "session expired" to someone who was signed in, not to a first-time visitor.
    setSessionExpiredHandler(() => { if (userRef.current) setExpired(true); setUser(null) })
    ensureCsrf()
      .then(() => api.me())
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email, password) => {
    const u = await api.login(email, password)
    setExpired(false)
    setUser(u)
    return u
  }, [])

  const register = useCallback(async (email, password, name) => {
    const u = await api.register(email, password, name)
    setExpired(false)
    setUser(u)
    return u
  }, [])

  const logout = useCallback(async () => {
    try { await api.logout() } finally { setUser(null) }
  }, [])

  const value = useMemo(() => ({ user, setUser, loading, expired, login, register, logout }),
    [user, loading, expired, login, register, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
