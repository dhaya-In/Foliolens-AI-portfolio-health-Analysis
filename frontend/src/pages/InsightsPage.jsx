import { Fragment, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { Sparkles, RefreshCw, ShieldAlert, Eye, ExternalLink, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { api, errorMessage } from '../services/api'
import { useToast } from '../context/ToastContext'
import { Alert, Badge, Card, EmptyState, ErrorState, Freshness, Loading, PageHeader, useAsync } from '../components/ui'
import SymbolSearch from '../components/SymbolSearch'
import NewsList, { Article } from '../components/NewsList'
import { dateTime, money, num, pct, signClass } from '../utils/format'

const SIGNAL_CLASS = { buy: 'signal-buy', hold: 'signal-hold', reduce: 'signal-reduce', insufficient: 'signal-insufficient' }
const QUALITY_TONE = { High: 'pos', Medium: 'info', Low: 'warn', Insufficient: 'neg' }
const FUND_FMT = {
  'Profit margin': v => pct(v * 100, { sign: false }), 'Revenue growth (YoY)': v => pct(v * 100),
  'Earnings growth (YoY)': v => pct(v * 100), 'Return on equity': v => pct(v * 100, { sign: false }),
  'Dividend yield': v => (v > 1 ? `${num(v)}%` : pct(v * 100, { sign: false })), 'Market cap': v => num(v / 1e9, 1) + ' bn',
}

function Contribution({ f }) {
  if (!f.available) return <Badge>n/a</Badge>
  const Icon = f.contribution > 0 ? TrendingUp : f.contribution < 0 ? TrendingDown : Minus
  return <span className={`row num small ${signClass(f.contribution)}`} style={{ justifyContent: 'flex-end', gap: 4 }}><Icon size={13} />{f.contribution > 0 ? '+' : ''}{f.contribution}</span>
}

function PriceChart({ symbol }) {
  const [period, setPeriod] = useState('1y')
  const { data, error, loading } = useAsync(() => api.priceHistory(symbol, period), [symbol, period])
  return (
    <Card title="Price history" actions={
      <div className="seg" role="group" aria-label="Chart period">
        {['3mo', '6mo', '1y', '5y'].map(p => <button key={p} aria-pressed={period === p} onClick={() => setPeriod(p)}>{p.toUpperCase()}</button>)}
      </div>}>
      {loading ? <Loading label="Loading prices…" /> : error ? <ErrorState error={error} /> : (
        <div className="chart-box" role="img" aria-label={`${symbol} closing prices, ${period}`}>
          <ResponsiveContainer>
            <LineChart data={data.points} margin={{ left: 4, right: 8, top: 8 }}>
              <CartesianGrid stroke="#eef2f6" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
              <YAxis tick={{ fontSize: 11 }} width={60} domain={['auto', 'auto']} />
              <Tooltip />
              <Line dataKey="close" stroke="#1d4ed8" dot={false} strokeWidth={2} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

function Analysis({ symbol }) {
  const toast = useToast()
  const [aiLoading, setAiLoading] = useState(false)
  const [aiResult, setAiResult] = useState(null)
  const { data: s, error, loading, refreshing, reload } = useAsync((refresh) => api.insights(symbol, { refresh }), [symbol])

  const runAi = async () => {
    setAiLoading(true)
    try {
      const r = await api.insights(symbol, { ai: true })
      setAiResult(r.ai)
      if (r.ai.error) toast(r.ai.error, 'error')
    } catch (err) { toast(errorMessage(err), 'error') } finally { setAiLoading(false) }
  }
  const addWatch = async () => {
    try { await api.addWatch({ symbol: s.symbol }); toast(`${s.symbol} added to your watchlist.`) }
    catch (err) { toast(errorMessage(err), 'error') }
  }

  if (loading) return <Loading label={`Analysing ${symbol}: prices, fundamentals and news…`} />
  if (error && !s) return <Card><ErrorState error={error} onRetry={() => reload()} /></Card>

  const ai = aiResult || s.ai
  return (
    <div className="stack">
      <div className={`signal-banner ${SIGNAL_CLASS[s.signal_code]}`}>
        <div style={{ flex: '1 1 260px' }}>
          <div className="muted small">{s.name} · <strong>{s.symbol}</strong>{s.sector ? ` · ${s.sector}` : ''}</div>
          <div className="signal-name">{s.signal}</div>
          <div style={{ marginTop: 4 }}><strong>Why:</strong> {s.why}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="stat-value">{money(s.price, s.currency)}</div>
          <div className={`small ${signClass(s.change_pct)}`}>{pct(s.change_pct)} today</div>
          <div className="small muted">Market time: {dateTime(s.price_time)}</div>
          <div className="row" style={{ justifyContent: 'flex-end', marginTop: 4 }}>
            <Badge tone={QUALITY_TONE[s.evidence_quality.level]}>Evidence: {s.evidence_quality.level}</Badge>
            <Badge title={s.score_explanation}>Score {s.score > 0 ? '+' : ''}{s.score}</Badge>
          </div>
        </div>
      </div>
      <div className="row-wrap">
        <Freshness at={s.generated_at} stale={s.quote_stale} label="Analysis generated" onRefresh={() => { setAiResult(null); reload(true) }} refreshing={refreshing} />
        <span className="spacer" />
        <button className="btn btn-sm" onClick={addWatch}><Eye size={14} /> Add to watchlist</button>
      </div>
      {s.data_errors?.length > 0 && <Alert level="warning">Some data could not be fetched: {s.data_errors.map(e => `${e.source} (${e.message})`).join('; ')}</Alert>}

      <div className="grid grid-2">
        <Card title="Positive factors (verified data)">
          {s.positives.length ? <ul className="list-dot">{s.positives.map(p => <li key={p}>{p}</li>)}</ul> : <p className="muted">No factor scored positively.</p>}
        </Card>
        <Card title="Negative factors (verified data)">
          {s.negatives.length ? <ul className="list-dot">{s.negatives.map(p => <li key={p}>{p}</li>)}</ul> : <p className="muted">No factor scored negatively.</p>}
        </Card>
      </div>

      <Card title="How each factor influenced the signal" actions={<span className="hint">{s.evidence_quality.explanation}</span>}>
        {s.factors.map(f => (
          <div className="factor" key={f.name}>
            <div><strong>{f.name}</strong>{!f.available && <div className="hint">not evaluated</div>}</div>
            <div className="factor-value small"><div className="mono">{f.value}</div><div className="muted">{f.explanation}</div></div>
            <Contribution f={f} />
          </div>
        ))}
      </Card>

      <div className="grid grid-2">
        <Card title={<span className="row"><ShieldAlert size={16} /> Risks & uncertainty</span>}>
          <ul className="list-dot">{s.risks.map(r => <li key={r}>{r}</li>)}</ul>
        </Card>
        <Card title="What to monitor">
          <ul className="list-dot">{s.monitor.map(r => <li key={r}>{r}</li>)}</ul>
          <div className="card-title" style={{ marginTop: 14 }}>Is waiting for a lower price supported?</div>
          <p><Badge tone={s.wait_for_lower_price.supported ? 'warn' : undefined}>{s.wait_for_lower_price.supported ? 'Partly supported' : 'Not supported'}</Badge> {s.wait_for_lower_price.explanation}</p>
        </Card>
      </div>

      <PriceChart symbol={s.symbol} />

      <div className="grid grid-2">
        <Card title={`Positive news (${s.news.positive.length})`}>
          {s.news.positive.length ? s.news.positive.map(a => <Article key={a.url} a={a} />) : <p className="muted">None in the last 14 days.</p>}
        </Card>
        <Card title={`Negative news (${s.news.negative.length})`}>
          {s.news.negative.length ? s.news.negative.map(a => <Article key={a.url} a={a} />) : <p className="muted">None in the last 14 days.</p>}
        </Card>
      </div>

      <Card title={`All recent coverage (${s.news.recent?.length || 0}, last 14 days)`} actions={<span className="hint">Provider: {s.news.provider || '—'} · fetched {dateTime(s.news.fetched_at)}</span>}>
        {s.news.recent?.length ? s.news.recent.map(a => <Article key={a.url} a={a} />) : <p className="muted">No recent articles were returned for this stock.</p>}
      </Card>

      <div className="grid grid-2">
        <Card title="Financial indicators">
          {Object.keys(s.fundamentals).length === 0 ? <p className="muted">The provider reported no fundamentals for this stock.</p> : (
            <dl className="kv">{Object.entries(s.fundamentals).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{FUND_FMT[k] ? FUND_FMT[k](v) : num(v)}</dd></Fragment>)}</dl>
          )}
          {s.price_stats && (
            <dl className="kv" style={{ marginTop: 12 }}>
              <dt>1M / 3M / 6M return</dt><dd>{pct(s.price_stats.return_1m_pct, { digits: 1 })} / {pct(s.price_stats.return_3m_pct, { digits: 1 })} / {pct(s.price_stats.return_6m_pct, { digits: 1 })}</dd>
              <dt>50 / 200-day average</dt><dd>{num(s.price_stats.sma50)} / {num(s.price_stats.sma200)}</dd>
              <dt>Period high / low</dt><dd>{num(s.price_stats.period_high)} / {num(s.price_stats.period_low)}</dd>
              <dt>RSI (14)</dt><dd>{num(s.price_stats.rsi14, 0)}</dd>
            </dl>
          )}
          {s.position && <Alert level="info">You hold {num(s.position.quantity, 4)} shares ({s.position.weight_pct ?? '—'}% of portfolio, P/L {pct(s.position.gain_loss_pct)}).</Alert>}
        </Card>
        <Card title={<span className="row"><Sparkles size={16} /> AI interpretation</span>} actions={<Badge>separate from verified data</Badge>}>
          {!ai.configured ? <Alert level="info">AI is not configured. Set <code>AI_API_KEY</code> on the backend to enable an AI-written explanation of these facts.</Alert>
            : ai.interpretation ? (
              <div className="stack" style={{ gap: 8 }}>
                <p>{ai.interpretation.summary}</p>
                {ai.interpretation.key_uncertainties.length > 0 && <><div className="card-title">Key uncertainties</div><ul className="list-dot">{ai.interpretation.key_uncertainties.map(u => <li key={u}>{u}</li>)}</ul></>}
                <p className="hint">Written by {ai.interpretation.model} at {dateTime(ai.interpretation.generated_at)} using only the data on this page. It may contain mistakes.</p>
              </div>
            ) : (
              <div className="stack" style={{ gap: 8 }}>
                {ai.error && <Alert level="warning">{ai.error}</Alert>}
                <p className="muted">Ask the AI model to explain the computed signal in plain language. It cannot change the signal or add new facts.</p>
                <button className="btn" onClick={runAi} disabled={aiLoading || s.signal_code === 'insufficient'}><Sparkles size={14} /> {aiLoading ? 'Generating…' : 'Generate AI interpretation'}</button>
              </div>
            )}
        </Card>
      </div>

      <Card title="Sources">
        <table className="table">
          <thead><tr><th>Source</th><th>Provider</th><th>Date</th></tr></thead>
          <tbody>{s.sources.map((src, i) => (
            <tr key={i}>
              <td>{src.url ? <a href={src.url} target="_blank" rel="noopener noreferrer nofollow">{src.name} <ExternalLink size={11} /></a> : src.name}</td>
              <td className="small">{src.provider || '—'}</td>
              <td className="small">{typeof src.as_of === 'string' && src.as_of.length === 10 ? src.as_of : dateTime(src.as_of)}</td>
            </tr>))}
          </tbody>
        </table>
      </Card>
      <p className="disclaimer">{s.disclaimer}</p>
    </div>
  )
}

function MarketNews() {
  const [region, setRegion] = useState('india')
  const { data, error, loading, refreshing, reload } = useAsync((refresh) => api.news({ region, refresh }), [region])
  return (
    <Card title="Market news" actions={<>
      <div className="seg" role="group" aria-label="Region">
        {[['india', 'India'], ['us', 'US'], ['global', 'Global']].map(([k, l]) => <button key={k} aria-pressed={region === k} onClick={() => setRegion(k)}>{l}</button>)}
      </div>
      {data && <Freshness at={data.fetched_at} stale={data.stale} onRefresh={() => reload(true)} refreshing={refreshing} label="Fetched" />}
    </>}>
      {loading ? <Loading label="Fetching news…" /> : error && !data ? <ErrorState error={error} onRetry={() => reload()} /> : <>
        {data.stale && <Alert level="warning">Could not refresh news ({data.stale_reason}); showing cached articles.</Alert>}
        <NewsList articles={data.articles} />
        <p className="hint">Provider: {data.provider}. Headlines are shown as published; sentiment is an automated estimate.</p>
      </>}
    </Card>
  )
}

function HoldingsNews() {
  const { data, error, loading, refreshing, reload } = useAsync((refresh) => api.portfolioNews(refresh))
  if (loading) return <Loading label="Fetching news for your largest holdings…" />
  if (error && !data) return <Card><ErrorState error={error} onRetry={() => reload()} /></Card>
  if (!data.groups.length && !data.errors.length) return <Card><EmptyState title="No priced holdings">Import holdings to see stock-specific news.</EmptyState></Card>
  return (
    <div className="stack">
      <div className="row"><span className="spacer" /><button className="btn btn-sm" onClick={() => reload(true)} disabled={refreshing}><RefreshCw size={13} /> {refreshing ? 'Refreshing…' : 'Refresh news'}</button></div>
      {data.errors.map(e => <Alert key={e.ticker} level="warning">{e.ticker}: {e.message}</Alert>)}
      {data.groups.map(g => (
        <Card key={g.symbol} title={<span><Link to={`/insights/${g.ticker}`}>{g.ticker}</Link> <span className="muted small">{g.name}</span></span>}
              actions={<Freshness at={g.fetched_at} stale={g.stale} label="Fetched" />}>
          <NewsList articles={g.articles} />
        </Card>
      ))}
    </div>
  )
}

export default function InsightsPage() {
  const { symbol } = useParams()
  const navigate = useNavigate()
  const [tab, setTab] = useState('analysis')
  const tabs = [['analysis', 'Stock analysis'], ['market', 'Market news'], ['holdings', 'News for my holdings']]
  return (
    <div className="stack">
      <PageHeader title="Stock News & Insights" subtitle="Current financial news and transparent, evidence-based decision support" />
      <div className="tabs" role="tablist">
        {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === 'analysis' && (
        <div className="stack">
          <div className="row-wrap"><SymbolSearch onSelect={(s) => navigate(`/insights/${encodeURIComponent(s)}`)} /></div>
          {symbol ? <Analysis key={symbol} symbol={symbol.toUpperCase()} /> : (
            <Card><EmptyState title="Analyse a stock">
              Search for a company or ticker. The analysis combines live prices, price history, reported fundamentals,
              recent news and your own position into a transparent signal - with every factor and source shown.
            </EmptyState></Card>
          )}
        </div>
      )}
      {tab === 'market' && <MarketNews />}
      {tab === 'holdings' && <HoldingsNews />}
    </div>
  )
}
