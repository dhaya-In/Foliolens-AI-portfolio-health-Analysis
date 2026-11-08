import { Link } from 'react-router-dom'
import { Wallet, PiggyBank, TrendingUp, CalendarClock, FileUp } from 'lucide-react'
import { api } from '../services/api'
import { Alert, Badge, Card, EmptyState, ErrorState, Freshness, Loading, PageHeader, Stat, useAsync } from '../components/ui'
import { AllocationPie } from '../components/charts'
import { dateTime, money, pct, signClass } from '../utils/format'

export default function OverviewPage() {
  const { data, error, loading, refreshing, reload } = useAsync((refresh) => api.overview(refresh))

  if (loading) return <><PageHeader title="Overview" /><Loading label="Pricing your portfolio with live market data…" /></>
  if (error && !data) return <><PageHeader title="Overview" /><Card><ErrorState error={error} onRetry={() => reload()} /></Card></>

  const t = data.totals
  const ccy = t.currency
  const header = (
    <PageHeader title="Overview" subtitle="Your portfolio at a glance">
      <Freshness at={data.last_refreshed} stale={data.any_stale} staleAfter={data.stale_after_seconds}
                 onRefresh={() => reload(true)} refreshing={refreshing} label="Prices updated" />
    </PageHeader>
  )

  if (t.holdings_count === 0) {
    return <>{header}<Card><EmptyState title="Your portfolio is empty"
      action={<Link className="btn btn-primary" to="/import"><FileUp size={15} /> Import a CSV</Link>}>
      Import your broker&apos;s holdings CSV or add holdings manually on the My Portfolio page.
    </EmptyState></Card></>
  }

  return (
    <div className="stack">
      {header}
      {error && <Alert level="warning">Refresh failed: showing previously loaded data.</Alert>}
      <div className="grid grid-4">
        <Stat icon={<Wallet size={14} />} label="Portfolio value" value={money(t.total_value, ccy)}
              sub={`${t.priced_count} of ${t.holdings_count} holdings priced`} />
        <Stat icon={<PiggyBank size={14} />} label="Total invested" value={money(t.total_cost, ccy)} sub="Cost basis of priced holdings" />
        <Stat icon={<TrendingUp size={14} />} label="Overall profit / loss" value={money(t.gain_loss, ccy)}
              sub={pct(t.gain_loss_pct)} subClass={signClass(t.gain_loss)} />
        <Stat icon={<CalendarClock size={14} />} label="Today's change" value={money(t.day_change, ccy)}
              sub={pct(t.day_change_pct)} subClass={signClass(t.day_change)} />
      </div>

      {data.alerts.length > 0 && (
        <Card title="Alerts">
          <div className="stack" style={{ gap: 8 }}>
            {data.alerts.map((a, i) => <Alert key={i} level={a.level}>{a.message}</Alert>)}
          </div>
        </Card>
      )}

      <div className="grid grid-2-1">
        <Card title="Sector allocation" actions={data.health_score !== null &&
          <Link to="/health" className="small">Health score <strong>{data.health_score}</strong>/100 →</Link>}>
          <AllocationPie data={data.sector_allocation} />
        </Card>
        <Card title="Largest holdings" actions={<Link to="/portfolio" className="small">View all →</Link>}>
          <ul className="list-plain">
            {data.top_holdings.map(h => (
              <li key={h.ticker} className="row">
                <Link to={`/insights/${h.ticker}`} style={{ fontWeight: 600, minWidth: 90 }}>{h.ticker}</Link>
                <div className="bar-track spacer" aria-hidden="true"><div style={{ width: `${Math.min(100, h.weight_pct)}%` }} /></div>
                <span className="num small" style={{ minWidth: 52 }}>{h.weight_pct}%</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="Today's movers">
          {data.top_gainers.length === 0 ? <p className="muted">No daily change data yet.</p> : (
            <table className="table">
              <thead><tr><th>Stock</th><th className="num">Price</th><th className="num">Day</th></tr></thead>
              <tbody>
                {[...data.top_gainers, ...data.top_losers].map(h => (
                  <tr key={h.ticker}>
                    <td><Link to={`/insights/${h.ticker}`}>{h.ticker}</Link> <span className="muted small">{h.company_name}</span></td>
                    <td className="num">{money(h.current_price, h.currency)}</td>
                    <td className={`num ${signClass(h.day_change_pct)}`}>{pct(h.day_change_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Recent activity">
          {data.activity.length === 0 ? <p className="muted">No activity yet.</p> : (
            <ul className="list-plain">
              {data.activity.map((a, i) => (
                <li key={i} className="row" style={{ alignItems: 'baseline' }}>
                  <Badge tone={a.kind === 'security' ? 'info' : undefined}>{a.kind}</Badge>
                  <span className="spacer">{a.message}</span>
                  <span className="muted small">{dateTime(a.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {(t.unpriced.length > 0 || t.excluded_other_currency.length > 0) && (
        <p className="muted small">Totals use {ccy} holdings with a live price. Excluded: {[...t.unpriced, ...t.excluded_other_currency].join(', ')}.</p>
      )}
    </div>
  )
}
