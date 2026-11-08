"""Financial news.

Providers
- "yahoo"     (default, no key): Yahoo Finance news search via yfinance. Headline, publisher, link,
              time and related tickers; no summaries or author names.
- "marketaux" (FINANCIAL_NEWS_API_KEY): https://www.marketaux.com - adds descriptions, snippets and
              entity-level sentiment scores. Free tier: 100 requests/day, 3 articles per request.

Articles are returned exactly as the provider supplied them. Nothing is generated.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.cache import TTLCache, cached_call
from app.core.config import get_settings
from app.core.logging import get_logger
from app.services import sentiment
from app.services.http_client import ProviderError, get_json
from app.services.market_data import _record, _with_retries, _yf

log = get_logger(__name__)
_cache = TTLCache()

# Yahoo's news search works best with index symbols and short terms; results are merged and de-duplicated.
MARKET_QUERIES = {
    "india": ["^NSEI", "^BSESN", "Sensex"],
    "us": ["^GSPC", "Wall Street"],
    "global": ["global markets", "stock market"],
}


def _article(*, title, source, author, published_at, url, summary, tickers, provider, provider_sentiment=None):
    text = f"{title or ''}. {summary or ''}"
    if provider_sentiment is not None:
        sent = {"label": sentiment.label_from_score(provider_sentiment), "score": round(provider_sentiment, 2),
                "method": f"{provider} entity sentiment", "matched_positive": [], "matched_negative": []}
    else:
        sent = sentiment.score_text(text)
    return {
        "title": title,
        "source": source,
        "author": author,
        "published_at": published_at,
        "url": url,
        "summary": summary,
        "tickers": list(dict.fromkeys(t for t in tickers if t)),
        "provider": provider,
        "sentiment": sent,
    }


def _safe_url(url: str | None) -> str | None:
    return url if url and url.startswith(("https://", "http://")) else None


def _yahoo_news(queries: list[str], limit: int) -> list[dict]:
    items, seen, failures = [], set(), []
    for q in queries:
        try:
            res = _with_retries(lambda: _yf().Search(q, max_results=0, news_count=limit, raise_errors=True,
                                                     timeout=get_settings().provider_timeout_seconds))
        except ProviderError as exc:
            failures.append(exc)
            continue
        for n in res.news or []:
            key = n.get("uuid") or n.get("link")
            if key not in seen:
                seen.add(key)
                items.append(n)
    if failures and len(failures) == len(queries):
        raise failures[0]
    out = []
    for n in items:
        ts = n.get("providerPublishTime")
        out.append(_article(
            title=n.get("title"), source=n.get("publisher"), author=None,
            published_at=datetime.fromtimestamp(ts, timezone.utc) if isinstance(ts, (int, float)) else None,
            url=_safe_url(n.get("link")), summary=None, tickers=n.get("relatedTickers") or [], provider="yahoo",
        ))
    return [a for a in out if a["title"] and a["url"]]


def _marketaux_news(symbol: str | None, query: str | None, limit: int) -> list[dict]:
    key = get_settings().news_api_key
    if not key:
        raise ProviderError("marketaux", "not_configured",
                            "FINANCIAL_NEWS_PROVIDER=marketaux but FINANCIAL_NEWS_API_KEY is not set (get one at https://www.marketaux.com/register).")
    params = {"api_token": key, "language": "en", "limit": min(limit, 50)}
    if symbol:
        params.update({"symbols": symbol, "filter_entities": "true"})
    elif query:
        params["search"] = query
    data = get_json("marketaux", "https://api.marketaux.com/v1/news/all", params, secret_params=("api_token",))
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        code = str(err.get("code", ""))
        kind = "auth" if "token" in code or "auth" in code else "rate_limited" if "limit" in code else "bad_response"
        raise ProviderError("marketaux", kind, f"Marketaux error: {err.get('message', code)}")
    out = []
    for n in (data.get("data") if isinstance(data, dict) else None) or []:
        ents = n.get("entities") or []
        scores = [e.get("sentiment_score") for e in ents
                  if e.get("sentiment_score") is not None and (not symbol or e.get("symbol") == symbol)]
        published = n.get("published_at")
        try:
            published_dt = datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None
        except ValueError:
            published_dt = None
        out.append(_article(
            title=n.get("title"), source=n.get("source"), author=None, published_at=published_dt,
            url=_safe_url(n.get("url")), summary=n.get("description") or n.get("snippet"),
            tickers=[e.get("symbol") for e in ents if e.get("symbol")], provider="marketaux",
            provider_sentiment=(sum(scores) / len(scores)) if scores else None,
        ))
    return [a for a in out if a["title"] and a["url"]]


def _fetch(symbol: str | None, query: str | list[str], limit: int) -> list[dict]:
    provider = get_settings().news_provider
    try:
        if provider == "marketaux":
            text = query if isinstance(query, str) else " ".join(q for q in query if not q.startswith("^")) or "stock market"
            items = _marketaux_news(symbol, None if symbol else text, limit)
        else:
            queries = [query] if isinstance(query, str) else list(query)
            if symbol:
                # Yahoo news search works best with the bare ticker ("TCS"), so query it alongside the name.
                queries = list(dict.fromkeys([symbol.split(".")[0], query]))
            items = _yahoo_news(queries, limit)
    except ProviderError as exc:
        _record(exc.provider, False, exc.message)
        raise
    _record(provider, True)
    items.sort(key=lambda a: a["published_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:limit * 2]


def get_news(symbol: str | None = None, query: str | list[str] | None = None, limit: int = 10,
             force: bool = False) -> dict:
    s = get_settings()
    q = query or symbol or MARKET_QUERIES["india"]
    res = cached_call(_cache, f"news:{s.news_provider}:{symbol}:{q}:{limit}", s.news_cache_seconds,
                      lambda: _fetch(symbol, q, limit), force=force)
    now = datetime.now(timezone.utc)
    articles = []
    for a in res.value:
        a = dict(a)
        age_h = (now - a["published_at"]).total_seconds() / 3600 if a["published_at"] else None
        a["age_hours"] = round(age_h, 1) if age_h is not None else None
        a["old"] = bool(age_h is not None and age_h > 24 * 7)
        articles.append(a)
    return {
        "articles": articles,
        "provider": s.news_provider,
        "query": q if isinstance(q, str) else ", ".join(q),
        "symbol": symbol,
        "fetched_at": res.fetched_at,
        "stale": res.stale,
        "stale_reason": res.error,
    }


def clear_cache() -> None:
    _cache.clear()
