import { ExternalLink } from 'lucide-react'
import { Badge } from './ui'
import { dateTime, timeAgo } from '../utils/format'

const TONE = { positive: 'pos', negative: 'neg', neutral: undefined }

export function SentimentBadge({ sentiment }) {
  if (!sentiment) return null
  const why = sentiment.matched_positive?.length || sentiment.matched_negative?.length
    ? `Method: ${sentiment.method}. Terms: ${[...(sentiment.matched_positive || []).map(w => '+' + w), ...(sentiment.matched_negative || []).map(w => '-' + w)].join(', ')}`
    : `Method: ${sentiment.method}`
  return <Badge tone={TONE[sentiment.label]} title={why}>{sentiment.label}</Badge>
}

export function Article({ a }) {
  return (
    <article className="article">
      <a className="article-title" href={a.url} target="_blank" rel="noopener noreferrer nofollow">
        {a.title} <ExternalLink size={12} aria-label="(opens in a new tab)" />
      </a>
      <div className="row-wrap small muted">
        <span>{a.source || 'Unknown source'}{a.author ? ` · ${a.author}` : ''}</span>
        <span title={dateTime(a.published_at)}>· {a.published_at ? `${dateTime(a.published_at)} (${timeAgo(a.published_at)})` : 'date not provided'}</span>
        {a.old && <Badge tone="warn">older than 7 days</Badge>}
        <SentimentBadge sentiment={a.sentiment} />
        {[...new Set(a.tickers || [])].slice(0, 4).map(t => <Badge key={t}>{t}</Badge>)}
      </div>
      {a.summary ? <p className="small" style={{ color: 'var(--text-2)' }}>{a.summary}</p>
        : <p className="small muted">No summary provided by the source - open the article to read it.</p>}
    </article>
  )
}

export default function NewsList({ articles }) {
  if (!articles?.length) return <p className="muted">No articles were returned by the news provider.</p>
  return <div>{articles.map((a, i) => <Article key={`${a.url}-${i}`} a={a} />)}</div>
}
