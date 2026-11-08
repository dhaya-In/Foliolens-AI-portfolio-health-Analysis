import axios from 'axios'

// All requests go to the same origin (/api, proxied by Vite in dev). Auth uses HttpOnly
// cookies set by the backend, so no token is ever stored in JS-accessible storage.
// State-changing requests carry the double-submit CSRF token from the fl_csrf cookie.

export const http = axios.create({ baseURL: '/api', withCredentials: true, timeout: 90000 })

export function readCookie(name, cookieString = typeof document !== 'undefined' ? document.cookie : '') {
  const match = cookieString.split(';').map(c => c.trim()).find(c => c.startsWith(name + '='))
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null
}

let csrfPromise = null
export async function ensureCsrf() {
  if (readCookie('fl_csrf')) return readCookie('fl_csrf')
  if (!csrfPromise) csrfPromise = http.get('/auth/csrf').finally(() => { csrfPromise = null })
  await csrfPromise
  return readCookie('fl_csrf')
}

const UNSAFE = new Set(['post', 'put', 'patch', 'delete'])
http.interceptors.request.use(async (config) => {
  if (UNSAFE.has((config.method || 'get').toLowerCase())) {
    config.headers['X-CSRF-Token'] = await ensureCsrf()
  }
  return config
})

// ---- silent access-token renewal ------------------------------------------------------
let refreshing = null
let onSessionExpired = () => {}
export function setSessionExpiredHandler(fn) { onSessionExpired = fn }

const NO_REFRESH = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout', '/auth/csrf']

http.interceptors.response.use(
  (r) => r,
  async (error) => {
    const cfg = error.config || {}
    const status = error.response?.status
    if (status === 403 && /CSRF/i.test(error.response?.data?.detail || '') && !cfg._csrfRetry) {
      // CSRF cookie missing/rotated: fetch a fresh one and retry once.
      cfg._csrfRetry = true
      document.cookie = 'fl_csrf=; Max-Age=0; path=/'
      await ensureCsrf()
      return http(cfg)
    }
    if (status === 401 && !cfg._retried && !NO_REFRESH.some(p => (cfg.url || '').startsWith(p))) {
      cfg._retried = true
      try {
        if (!refreshing) refreshing = http.post('/auth/refresh').finally(() => { refreshing = null })
        await refreshing
        return http(cfg)
      } catch {
        onSessionExpired()
      }
    }
    return Promise.reject(error)
  },
)

export function errorMessage(err, fallback = 'Something went wrong. Please try again.') {
  if (!err) return fallback
  if (err.code === 'ECONNABORTED') return 'The request timed out. The data provider may be slow - try again.'
  if (!err.response) return 'Cannot reach the FolioLens server. Check that the backend is running.'
  const d = err.response.data
  if (typeof d?.detail === 'string') return d.detail
  return fallback
}

// ---- endpoints ------------------------------------------------------------------------
const get = (url, params) => http.get(url, { params }).then(r => r.data)

export const api = {
  // auth
  me: () => get('/auth/me'),
  login: (email, password) => http.post('/auth/login', { email, password }).then(r => r.data),
  register: (email, password, display_name) => http.post('/auth/register', { email, password, display_name }).then(r => r.data),
  logout: () => http.post('/auth/logout'),

  // portfolio
  overview: (refresh) => get('/portfolio/overview', { refresh }),
  holdings: (refresh) => get('/portfolio/holdings', { refresh }),
  addHolding: (h) => http.post('/portfolio/holdings', h).then(r => r.data),
  updateHolding: (id, h) => http.put(`/portfolio/holdings/${id}`, h).then(r => r.data),
  deleteHolding: (id) => http.delete(`/portfolio/holdings/${id}`),
  health: (period, refresh) => get('/portfolio/health', { period, refresh }),
  history: (period) => get('/portfolio/history', { period }),

  // csv import / export
  uploadCsv: (file, onProgress) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/imports/upload', form, {
      onUploadProgress: (e) => onProgress && e.total && onProgress(Math.round((e.loaded / e.total) * 100)),
    }).then(r => r.data)
  },
  validateImport: (upload_id, mapping) => http.post('/imports/validate', { upload_id, mapping }).then(r => r.data),
  confirmImport: (upload_id, mapping, mode) => http.post('/imports/confirm', { upload_id, mapping, mode }).then(r => r.data),
  cancelImport: (upload_id) => http.delete(`/imports/${upload_id}`),

  // market, news & insights
  search: (q) => get('/market/search', { q }),
  quote: (symbol, refresh) => get(`/market/quote/${encodeURIComponent(symbol)}`, { refresh }),
  priceHistory: (symbol, period) => get(`/market/history/${encodeURIComponent(symbol)}`, { period }),
  news: (params) => get('/news', params),
  portfolioNews: (refresh) => get('/news/portfolio', { refresh }),
  insights: (symbol, { refresh = false, ai = false } = {}) => get(`/insights/${encodeURIComponent(symbol)}`, { refresh, ai }),
  status: () => get('/status'),

  // watchlist
  watchlist: (refresh) => get('/watchlist', { refresh }),
  addWatch: (item) => http.post('/watchlist', item).then(r => r.data),
  updateWatch: (id, item) => http.put(`/watchlist/${id}`, item).then(r => r.data),
  deleteWatch: (id) => http.delete(`/watchlist/${id}`),

  // user / settings
  updateProfile: (display_name) => http.patch('/users/me', { display_name }).then(r => r.data),
  changePassword: (current_password, new_password) => http.post('/users/me/password', { current_password, new_password }),
  sessions: () => get('/users/me/sessions'),
  revokeOtherSessions: () => http.post('/users/me/sessions/revoke-others'),
  activity: () => get('/users/me/activity'),
  deleteAccount: (password) => http.delete('/users/me', { data: { password } }),
}

// Authenticated file download (cookies are sent; the file never touches a public URL).
export async function downloadFile(path, fallbackName) {
  const res = await http.get(path, { responseType: 'blob' })
  const cd = res.headers['content-disposition'] || ''
  const name = (cd.match(/filename="([^"]+)"/) || [])[1] || fallbackName
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return name
}
