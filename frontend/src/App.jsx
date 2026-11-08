import { lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ToastProvider } from './context/ToastContext'
import Layout from './components/Layout'
import { Loading } from './components/ui'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'

// Pages are code-split so the charts library only loads when a page needs it.
const OverviewPage = lazy(() => import('./pages/OverviewPage'))
const PortfolioPage = lazy(() => import('./pages/PortfolioPage'))
const ImportExportPage = lazy(() => import('./pages/ImportExportPage'))
const HealthPage = lazy(() => import('./pages/HealthPage'))
const InsightsPage = lazy(() => import('./pages/InsightsPage'))
const WatchlistPage = lazy(() => import('./pages/WatchlistPage'))
const ReportsPage = lazy(() => import('./pages/ReportsPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))

function RequireAuth({ children }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <Loading label="Checking your session…" />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

function PublicOnly({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <Loading label="Checking your session…" />
  return user ? <Navigate to="/" replace /> : children
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<PublicOnly><LoginPage /></PublicOnly>} />
            <Route path="/register" element={<PublicOnly><RegisterPage /></PublicOnly>} />
            <Route element={<RequireAuth><Layout /></RequireAuth>}>
              <Route index element={<OverviewPage />} />
              <Route path="portfolio" element={<PortfolioPage />} />
              <Route path="import" element={<ImportExportPage />} />
              <Route path="health" element={<HealthPage />} />
              <Route path="insights" element={<InsightsPage />} />
              <Route path="insights/:symbol" element={<InsightsPage />} />
              <Route path="watchlist" element={<WatchlistPage />} />
              <Route path="reports" element={<ReportsPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}
