import { Suspense, useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Briefcase, FileUp, HeartPulse, Newspaper, Eye, BarChart3, Settings,
  LogOut, PanelLeftClose, PanelLeftOpen, Menu, TrendingUp,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { Loading } from './ui'

export const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/portfolio', label: 'My Portfolio', icon: Briefcase },
  { to: '/import', label: 'CSV Import & Export', icon: FileUp },
  { to: '/health', label: 'Portfolio Health', icon: HeartPulse },
  { to: '/insights', label: 'News & Insights', icon: Newspaper },
  { to: '/watchlist', label: 'Market Watchlist', icon: Eye },
  { to: '/reports', label: 'Reports & Analytics', icon: BarChart3 },
  { to: '/settings', label: 'Profile & Settings', icon: Settings },
]

function readCollapsed() {
  try { return localStorage.getItem('fl_sidebar_collapsed') === '1' } catch { return false }
}

export default function Layout() {
  const { user, logout } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => { setMobileOpen(false) }, [location.pathname])
  useEffect(() => {
    try { localStorage.setItem('fl_sidebar_collapsed', collapsed ? '1' : '0') } catch { /* ignore */ }
  }, [collapsed])
  useEffect(() => {
    const current = NAV.find(n => (n.end ? location.pathname === n.to : location.pathname.startsWith(n.to)))
    document.title = current ? `${current.label} · FolioLens` : 'FolioLens'
  }, [location.pathname])

  const onLogout = async () => {
    await logout()
    toast('You have been signed out.', 'info')
    navigate('/login', { replace: true })
  }
  const initials = (user?.display_name || user?.email || '?').slice(0, 1).toUpperCase()

  return (
    <div className="shell">
      <a href="#main" className="sr-only">Skip to content</a>
      <aside className={`sidebar ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'open' : ''}`} aria-label="Main navigation">
        <div className="brand">
          <span className="brand-mark"><TrendingUp size={17} color="#fff" /></span>
          <span className="brand-text">Folio<span className="accent">Lens</span></span>
        </div>
        <nav>
          <ul className="nav">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <li key={to}>
                <NavLink to={to} end={end} title={collapsed ? label : undefined}>
                  <Icon size={18} aria-hidden="true" />
                  <span className="nav-label">{label}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="sidebar-foot">
          <div className="sidebar-user" title={user?.email}>
            <span className="avatar" aria-hidden="true">{initials}</span>
            <span className="sidebar-user-text" style={{ minWidth: 0 }}>
              <div style={{ color: '#fff', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis' }}>{user?.display_name}</div>
              <div className="small" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{user?.email}</div>
            </span>
          </div>
          <button className="sidebar-btn collapse-toggle" onClick={() => setCollapsed(c => !c)}
                  aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={!collapsed}>
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            <span className="nav-label">Collapse</span>
          </button>
          <button className="sidebar-btn" onClick={onLogout}>
            <LogOut size={18} /><span className="nav-label">Log out</span>
          </button>
        </div>
      </aside>
      <div className={`scrim ${mobileOpen ? 'show' : ''}`} onClick={() => setMobileOpen(false)} aria-hidden="true" />
      <div className="main">
        <header className="topbar">
          <button className="icon-btn" onClick={() => setMobileOpen(true)} aria-label="Open navigation menu"
                  aria-expanded={mobileOpen}><Menu size={20} /></button>
          <strong>Folio<span style={{ color: '#93c5fd' }}>Lens</span></strong>
        </header>
        <main id="main" className="content" tabIndex={-1}>
          <Suspense fallback={<Loading label="Loading page…" />}><Outlet /></Suspense>
        </main>
      </div>
    </div>
  )
}
