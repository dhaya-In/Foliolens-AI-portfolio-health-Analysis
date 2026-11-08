import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { AlertTriangle, CheckCircle2, Lightbulb, Sparkles, HelpCircle } from 'lucide-react'
import { api } from '../services/api'
import { Alert, Badge, Card, EmptyState, ErrorState, Freshness, Loading, PageHeader, Stat, useAsync } from '../components/ui'
import { AllocationPie } from '../components/charts'
import { dateTime, money, pct } from '../utils/format'

const STATUS = { good: ['pos', 'Healthy'], watch: ['warn', 'Watch'], risk: ['neg', 'Risk'], unknown: [undefined, 'No data'] }
const INSIGHT_ICON = { risk: <AlertTriangle size={16} color="var(--neg)" />, positive: <CheckCircle2 size={16} color="var(--pos)" />, suggestion: <Lightbulb size={16} color="var(--warn)" /> }
const scoreTone = (s) => (s >= 70 ? 'pos' : s >= 45 ? '' : 'neg')

export default function HealthPage() {
  const [period, setPeriod] = useState('1y')
  const { data, error, loading, refreshing, reload } = useAsync((refresh) => api.health(period, refresh), [period])

  const header = (
    <PageHeader title="Portfolio Health" subtitle="Diversification, concentration and risk based on live data">
      <div className="seg" role="group" aria-label="History period">
        {[['6mo', '6M'], ['1y', '1Y'], ['2y', '2Y']].map(([k, l]) => <button key={k} aria-pressed={period === k} onClick={() => setPeriod(k)}>{l}</button>)}
      </div>
      {data && <Freshness at={data.last_refreshed} stale={data.any_stale} staleAfter={data.stale_after_seconds} onRefresh={() => reload(true)} refreshing={refreshing} />}
    </PageHeader>
  )
  if (loading) return <>{header}<Loading label="Analysing price history and risk…" /></>
  if (error && !data) return <>{header}<Card><ErrorState error={error} onRetry={() => reload()} /></Card></>
  if (data.empty) return <>{header}<Card><EmptyState title="No priced holdings to analyse" action={<Link className="btn btn-primary" to="/import">Import holdings</Link>}>Health metrics need at least one holding with a live price.</EmptyState></Card></>

  const m = data.metrics
  const ccy = data.totals.currency
  const hist = data.history
  const ins = data.insights

  return (
    <div className="stack">
      {header}
      <div className="grid grid-4">
        <Stat label="Health score" value={<span className={scoreTone(m.health_score)}>{m.health_score}<span className="muted small">/100</span></span>}
              sub={m.health_score >= 70 ? 'Good shape' : m.health_score >= 45 ? 'Some risks' : 'Needs attention'} />
        <Stat label="Diversification" value={<span className={scoreTone(m.diversification_score)}>{m.diversification_score}<span className="muted small">/100</span></span>}
              sub={m.diversification_score >= 70 ? 'Well spread' : 'Concentrated'} />
        <Stat label="Portfolio beta" value={m.portfolio_beta ?? '—'}
              sub={m.portfolio_beta !== null ? `${m.beta_coverage_pct}% of value has beta data` : 'Beta unavailable'} />
        <Stat label={`Volatility (${period})`} value={hist.stats?.volatility_pct != null ? `${hist.stats.volatility_pct.toFixed(1)}%` : '—'}
              sub={hist.stats?.max_drawdown_pct != null ? `Max drawdown ${hist.stats.max_drawdown_pct.toFixed(1)}%` : 'Not enough history'} />
      </div>

      <Card title="Risk indicators">
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Indicator</th><th>Value</th><th>Status</th><th>What it means</th></tr></thead>
            <tbody>{data.indicators.map(i => (
              <tr key={i.name}>
                <td style={{ fontWeight: 600 }}>{i.name}</td>
                <td className="mono">{i.value}</td>
                <td><Badge tone={STATUS[i.status][0]}>{STATUS[i.status][1]}</Badge></td>
                <td className="muted small">{i.explanation}</td>
              </tr>))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid grid-2-1">
        <Card title={`Value of current holdings · ${period}`} actions={hist.stats?.period_return_pct != null &&
          <span className={`small ${hist.stats.period_return_pct >= 0 ? 'pos' : 'neg'}`}>{pct(hist.stats.period_return_pct)} over period</span>}>
          {hist.points.length < 2 ? <p className="muted">Not enough price history.</p> : (
            <div className="chart-box" role="img" aria-label={`Historical value chart from ${hist.points[0].date} to ${hist.points[hist.points.length - 1].date}`}>
              <ResponsiveContainer>
                <AreaChart data={hist.points} margin={{ left: 8, right: 8, top: 8 }}>
                  <CartesianGrid stroke="#eef2f6" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                  <YAxis tick={{ fontSize: 11 }} width={70} tickFormatter={(v) => money(v, ccy, { compact: true })} domain={['auto', 'auto']} />
                  <Tooltip formatter={(v) => money(v, ccy)} />
                  <Area type="monotone" dataKey="value" stroke="#1d4ed8" fill="#dbeafe" strokeWidth={2} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
          <p className="hint">{hist.note}{hist.missing.length > 0 && ` No history for: ${hist.missing.join(', ')}.`}</p>
        </Card>
        <Card title="Sector exposure">
          <AllocationPie data={data.sector_breakdown} height={250} />
          {data.sector_breakdown.some(s => s.name === 'Unknown') && <p className="hint">“Unknown” = the provider did not report a sector.</p>}
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="Concentration by holding">
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Stock</th><th>Sector</th><th className="num">Weight</th><th className="num">Beta</th><th className="num">Volatility</th><th className="num">Max DD</th></tr></thead>
              <tbody>{data.weights.map(w => (
                <tr key={w.ticker}>
                  <td><Link to={`/insights/${w.ticker}`}>{w.ticker}</Link></td>
                  <td className="small muted">{w.sector}</td>
                  <td className={`num ${w.weight_pct > 20 ? 'neg' : ''}`}>{w.weight_pct}%</td>
                  <td className="num">{w.beta ?? '—'}</td>
                  <td className="num">{w.volatility_pct != null ? `${w.volatility_pct.toFixed(1)}%` : '—'}</td>
                  <td className="num">{w.max_drawdown_pct != null ? `${w.max_drawdown_pct.toFixed(1)}%` : '—'}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title={<span className="row">{ins.source === 'ai' ? <Sparkles size={16} /> : <HelpCircle size={16} />} Insights</span>}
              actions={<Badge tone={ins.source === 'ai' ? 'info' : undefined}>{ins.source === 'ai' ? `AI interpretation · ${ins.model}` : 'Rule-based'}</Badge>}>
          {ins.notice && <div style={{ marginBottom: 10 }}><Alert level="info">{ins.notice}</Alert></div>}
          <ul className="list-plain">
            {ins.insights.map((i, k) => (
              <li key={k} className="row" style={{ alignItems: 'flex-start' }}>
                {INSIGHT_ICON[i.insight_type] || INSIGHT_ICON.suggestion}
                <div><div className="small muted" style={{ textTransform: 'capitalize' }}>{i.insight_type}</div>{i.content}</div>
              </li>
            ))}
          </ul>
          <p className="hint" style={{ marginTop: 10 }}>Generated {dateTime(ins.generated_at)} from the metrics above. Not financial advice.</p>
        </Card>
      </div>
    </div>
  )
}
