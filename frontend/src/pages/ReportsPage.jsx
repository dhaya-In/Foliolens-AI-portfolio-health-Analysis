import { useMemo, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell, LineChart, Line, ReferenceLine, Legend } from 'recharts'
import { Download } from 'lucide-react'
import { api, downloadFile, errorMessage } from '../services/api'
import { useToast } from '../context/ToastContext'
import { Card, EmptyState, ErrorState, Loading, PageHeader, useAsync } from '../components/ui'
import { AllocationPie } from '../components/charts'
import { money, pct, signClass, dateTime } from '../utils/format'

const REPORTS = [
  ['/reports/pnl.csv', 'Profit & loss report', 'Per-holding cost, value, P/L, day change and weight, with totals.'],
  ['/reports/allocation.csv', 'Allocation report', 'Sector and holding weights.'],
  ['/reports/performance.csv?period=1y', 'Performance report (1Y)', 'Historical value of current holdings plus recorded snapshots.'],
  ['/imports/export/holdings.csv', 'Holdings export', 'Re-importable holdings CSV.'],
]

export default function ReportsPage() {
  const toast = useToast()
  const [period, setPeriod] = useState('1y')
  const [downloading, setDownloading] = useState(null)
  const holdings = useAsync(() => api.holdings())
  const history = useAsync(() => api.history(period), [period])

  const pl = useMemo(() => (holdings.data?.holdings || []).filter(h => h.gain_loss !== null)
    .map(h => ({ ticker: h.ticker, gain: h.gain_loss, pct: h.gain_loss_pct })).sort((a, b) => b.gain - a.gain), [holdings.data])
  const alloc = useMemo(() => (holdings.data?.holdings || []).filter(h => h.weight_pct !== null)
    .map(h => ({ name: h.ticker, value: h.weight_pct })).sort((a, b) => b.value - a.value), [holdings.data])

  const download = async (path, label) => {
    setDownloading(path)
    try { const n = await downloadFile(path, 'report.csv'); toast(`Downloaded ${n}.`) }
    catch (err) { toast(errorMessage(err, `${label} failed.`), 'error') } finally { setDownloading(null) }
  }

  const t = holdings.data?.totals
  const ccy = t?.currency
  return (
    <div className="stack">
      <PageHeader title="Reports & Analytics" subtitle="Performance, allocation and profit/loss from your live portfolio data" />
      <Card title="Downloadable reports">
        <div className="grid grid-2">
          {REPORTS.map(([path, label, desc]) => (
            <div key={path} className="row" style={{ alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
              <div><strong>{label}</strong><div className="muted small">{desc}</div></div>
              <button className="btn btn-sm" onClick={() => download(path, label)} disabled={downloading === path}>
                <Download size={14} /> {downloading === path ? 'Preparing…' : 'CSV'}
              </button>
            </div>
          ))}
        </div>
      </Card>

      {holdings.loading ? <Loading /> : holdings.error ? <Card><ErrorState error={holdings.error} onRetry={() => holdings.reload()} /></Card>
        : !holdings.data.holdings.length ? <Card><EmptyState title="No holdings yet">Import holdings to see reports.</EmptyState></Card> : <>
          <Card title="Historical performance" actions={
            <div className="seg" role="group" aria-label="Period">
              {['3mo', '6mo', '1y', '2y', '5y'].map(p => <button key={p} aria-pressed={period === p} onClick={() => setPeriod(p)}>{p.toUpperCase()}</button>)}
            </div>}>
            {history.loading ? <Loading label="Loading history…" /> : history.error ? <ErrorState error={history.error} onRetry={() => history.reload()} /> : history.data.points.length < 2 ? <p className="muted">Not enough history.</p> : <>
              <div className="chart-box" style={{ height: 300 }} role="img" aria-label="Historical value of current holdings compared with cost basis">
                <ResponsiveContainer>
                  <LineChart data={history.data.points} margin={{ left: 8, right: 8, top: 8 }}>
                    <CartesianGrid stroke="#eef2f6" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                    <YAxis tick={{ fontSize: 11 }} width={70} domain={['auto', 'auto']} tickFormatter={(v) => money(v, ccy, { compact: true })} />
                    <Tooltip formatter={(v) => money(v, ccy)} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <ReferenceLine y={history.data.cost_basis} stroke="#94a3b8" strokeDasharray="4 4" label={{ value: 'Cost basis', fontSize: 11, fill: '#64748b', position: 'insideTopLeft' }} />
                    <Line name="Value of current holdings" dataKey="value" stroke="#1d4ed8" dot={false} strokeWidth={2} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="hint">Current quantities valued at historical closing prices (past trades not included).
                {history.data.stats && <> Return {pct(history.data.stats.period_return_pct)}, volatility {history.data.stats.volatility_pct?.toFixed(1)}%, max drawdown {history.data.stats.max_drawdown_pct?.toFixed(1)}%.</>}
                {history.data.missing.length > 0 && ` Missing history: ${history.data.missing.join(', ')}.`}</p>
            </>}
          </Card>

          <div className="grid grid-2">
            <Card title="Profit / loss by holding">
              <div className="chart-box" role="img" aria-label="Profit and loss per holding bar chart">
                <ResponsiveContainer>
                  <BarChart data={pl} margin={{ left: 8, right: 8, top: 8 }}>
                    <CartesianGrid stroke="#eef2f6" vertical={false} />
                    <XAxis dataKey="ticker" tick={{ fontSize: 10.5 }} interval={0} angle={-30} textAnchor="end" height={50} />
                    <YAxis tick={{ fontSize: 11 }} width={70} tickFormatter={(v) => money(v, ccy, { compact: true })} />
                    <Tooltip formatter={(v) => money(v, ccy)} />
                    <ReferenceLine y={0} stroke="#94a3b8" />
                    <Bar dataKey="gain" name="P/L" isAnimationActive={false}>{pl.map(d => <Cell key={d.ticker} fill={d.gain >= 0 ? '#047857' : '#b91c1c'} />)}</Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="Allocation by holding"><AllocationPie data={alloc} height={280} /></Card>
          </div>

          <Card pad={false} title="Profit & loss summary">
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Stock</th><th className="num">Cost basis</th><th className="num">Market value</th><th className="num">P/L</th><th className="num">P/L %</th></tr></thead>
                <tbody>
                  {holdings.data.holdings.map(h => (
                    <tr key={h.id}><td>{h.ticker}</td><td className="num">{money(h.cost_basis, h.currency)}</td><td className="num">{money(h.market_value, h.currency)}</td>
                      <td className={`num ${signClass(h.gain_loss)}`}>{money(h.gain_loss, h.currency)}</td><td className={`num ${signClass(h.gain_loss_pct)}`}>{pct(h.gain_loss_pct)}</td></tr>
                  ))}
                  <tr style={{ fontWeight: 700 }}><td>Total ({ccy})</td><td className="num">{money(t.total_cost, ccy)}</td><td className="num">{money(t.total_value, ccy)}</td>
                    <td className={`num ${signClass(t.gain_loss)}`}>{money(t.gain_loss, ccy)}</td><td className={`num ${signClass(t.gain_loss_pct)}`}>{pct(t.gain_loss_pct)}</td></tr>
                </tbody>
              </table>
            </div>
          </Card>
          {history.data?.snapshots?.length > 0 && (
            <Card title="Recorded valuations" actions={<span className="hint">Saved automatically when your portfolio is priced (max hourly)</span>}>
              <div className="table-wrap" style={{ maxHeight: 260, overflowY: 'auto' }}>
                <table className="table"><thead><tr><th>Time</th><th className="num">Value</th><th className="num">Cost</th></tr></thead>
                  <tbody>{[...history.data.snapshots].reverse().map(s => <tr key={s.taken_at}><td>{dateTime(s.taken_at)}</td><td className="num">{money(s.total_value, s.currency)}</td><td className="num">{money(s.total_cost, s.currency)}</td></tr>)}</tbody>
                </table>
              </div>
            </Card>
          )}
        </>}
    </div>
  )
}
