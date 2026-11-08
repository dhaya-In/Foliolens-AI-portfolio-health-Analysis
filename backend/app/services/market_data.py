"""Market data: quotes, company profiles/fundamentals, price history and symbol search.

Providers
- "yahoo"   (default, no key): Yahoo Finance via the yfinance library. Covers NSE (.NS), BSE (.BO),
            US and most global listings. Unofficial API - it can rate-limit or change without notice.
- "finnhub" (MARKET_DATA_API_KEY): Finnhub REST API for quotes and company profiles. The free tier
            covers mainly US listings. History and search still come from Yahoo.

Every value carries the provider's own market timestamp (`market_time`) plus our `fetched_at`,
and a `stale` flag when we fall back to an older cached value after a provider failure.
"""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.core.cache import TTLCache, cached_call
from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.http_client import ProviderError, get_json

log = get_logger(__name__)

_cache = TTLCache()
_status_lock = threading.Lock()
provider_status: dict[str, dict] = {}

FUNDAMENTAL_FIELDS = {
    "trailingPE": "Trailing P/E",
    "forwardPE": "Forward P/E",
    "priceToBook": "Price / Book",
    "profitMargins": "Profit margin",
    "revenueGrowth": "Revenue growth (YoY)",
    "earningsGrowth": "Earnings growth (YoY)",
    "returnOnEquity": "Return on equity",
    "debtToEquity": "Debt / Equity (%)",
    "dividendYield": "Dividend yield",
    "marketCap": "Market cap",
}


def _record(provider: str, ok: bool, error: str | None = None) -> None:
    with _status_lock:
        st = provider_status.setdefault(provider, {"last_success": None, "last_error": None, "last_error_at": None})
        if ok:
            st["last_success"] = datetime.now(timezone.utc)
        else:
            st["last_error"] = error
            st["last_error_at"] = datetime.now(timezone.utc)


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _yf():
    import yfinance as yf  # imported lazily: heavy import, and lets tests run without network
    return yf


_NOT_FOUND_ERRORS = {"YFPricesMissingError", "YFTickerMissingError", "YFTzMissingError", "YFInvalidPeriodError"}


def _yahoo_error(exc: Exception, symbol: str = "") -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    name = type(exc).__name__
    if name in _NOT_FOUND_ERRORS:
        return ProviderError("yahoo", "not_found", f"No market data for {symbol or 'this symbol'}.")
    if "RateLimit" in name:
        return ProviderError("yahoo", "rate_limited", "Yahoo Finance is rate-limiting requests. Try again in a few minutes.")
    return ProviderError("yahoo", "unavailable", f"Yahoo Finance request failed ({name}).")


def _with_retries(fn, symbol: str = "", attempts: int = 3):
    """Run a yfinance call, retrying transient network errors (bounded, with backoff).
    'Not found' and rate-limit errors are not retried."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            err = _yahoo_error(exc, symbol)
            if err.kind != "unavailable" or attempt == attempts - 1:
                raise err from exc
            time.sleep(0.6 * (attempt + 1))


# ------------------------------------------------------------------ Yahoo implementation

def _yahoo_quote(symbol: str) -> dict:
    s = get_settings()

    def fetch():
        t = _yf().Ticker(symbol)
        h = t.history(period="5d", interval="1d", timeout=s.provider_timeout_seconds, raise_errors=True)
        return h, (t.history_metadata or {})

    hist, meta = _with_retries(fetch, symbol)
    price = _num(meta.get("regularMarketPrice"))
    if price is None or hist is None or hist.empty:
        raise ProviderError("yahoo", "not_found", f"No price data for {symbol}.")
    closes = [c for c in (_num(x) for x in hist["Close"].tolist()) if c is not None]
    prev = closes[-2] if len(closes) >= 2 else _num(meta.get("chartPreviousClose"))
    mt = meta.get("regularMarketTime")
    market_time = mt.to_pydatetime().astimezone(timezone.utc) if hasattr(mt, "to_pydatetime") else (
        datetime.fromtimestamp(mt, timezone.utc) if isinstance(mt, (int, float)) else None)
    return {
        "symbol": symbol,
        "name": meta.get("longName") or meta.get("shortName") or symbol,
        "price": price,
        "previous_close": prev,
        "change": (price - prev) if prev else None,
        "change_pct": ((price - prev) / prev * 100) if prev else None,
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "fifty_two_week_high": _num(meta.get("fiftyTwoWeekHigh")),
        "fifty_two_week_low": _num(meta.get("fiftyTwoWeekLow")),
        "market_time": market_time,
        "provider": "yahoo",
    }


def _yahoo_profile(symbol: str) -> dict:
    info = _with_retries(lambda: _yf().Ticker(symbol).get_info() or {}, symbol)
    if not info or (info.get("quoteType") is None and info.get("longName") is None):
        raise ProviderError("yahoo", "not_found", f"No company profile for {symbol}.")
    fundamentals = {k: _num(info.get(k)) for k in FUNDAMENTAL_FIELDS if _num(info.get(k)) is not None}
    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "beta": _num(info.get("beta")),
        "currency": info.get("currency"),
        "country": info.get("country"),
        "website": info.get("website"),
        "summary": (info.get("longBusinessSummary") or "")[:800] or None,
        "fundamentals": fundamentals,
        "provider": "yahoo",
    }


def _yahoo_history(symbol: str, period: str) -> list[dict]:
    s = get_settings()
    hist = _with_retries(lambda: _yf().Ticker(symbol).history(
        period=period, interval="1d", timeout=s.provider_timeout_seconds, raise_errors=True, auto_adjust=True), symbol)
    if hist is None or hist.empty:
        raise ProviderError("yahoo", "not_found", f"No price history for {symbol}.")
    out = []
    for idx, close in zip(hist.index, hist["Close"].tolist()):
        c = _num(close)
        if c is not None:
            out.append({"date": idx.date().isoformat(), "close": round(c, 4)})
    return out


def _yahoo_search(query: str) -> list[dict]:
    res = _with_retries(lambda: _yf().Search(query, max_results=10, news_count=0, raise_errors=True,
                                             timeout=get_settings().provider_timeout_seconds))
    quotes = res.quotes or []
    return [
        {"symbol": q.get("symbol"), "name": q.get("longname") or q.get("shortname") or q.get("symbol"),
         "exchange": q.get("exchDisp") or q.get("exchange"), "type": q.get("quoteType")}
        for q in quotes if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF", "INDEX", "MUTUALFUND")
    ]


# ------------------------------------------------------------------ Finnhub implementation

FINNHUB = "https://finnhub.io/api/v1"


def _finnhub_key() -> str:
    key = get_settings().market_data_api_key
    if not key:
        raise ProviderError("finnhub", "not_configured",
                            "MARKET_DATA_PROVIDER=finnhub but MARKET_DATA_API_KEY is not set (get one at https://finnhub.io/register).")
    return key


def _finnhub_quote(symbol: str) -> dict:
    data = get_json("finnhub", f"{FINNHUB}/quote", {"symbol": symbol, "token": _finnhub_key()}, secret_params=("token",))
    price = _num(data.get("c")) if isinstance(data, dict) else None
    if not price:
        raise ProviderError("finnhub", "not_found", f"No price data for {symbol} (Finnhub free tier covers mainly US listings).")
    prev = _num(data.get("pc"))
    ts = data.get("t")
    return {
        "symbol": symbol, "name": symbol, "price": price, "previous_close": prev,
        "change": (price - prev) if prev else None,
        "change_pct": ((price - prev) / prev * 100) if prev else None,
        "currency": None, "exchange": None,
        "fifty_two_week_high": None, "fifty_two_week_low": None,
        "market_time": datetime.fromtimestamp(ts, timezone.utc) if ts else None,
        "provider": "finnhub",
    }


def _finnhub_profile(symbol: str) -> dict:
    data = get_json("finnhub", f"{FINNHUB}/stock/profile2", {"symbol": symbol, "token": _finnhub_key()})
    if not data:
        raise ProviderError("finnhub", "not_found", f"No company profile for {symbol}.")
    return {
        "symbol": symbol, "name": data.get("name") or symbol, "sector": data.get("finnhubIndustry"),
        "industry": data.get("finnhubIndustry"), "beta": None, "currency": data.get("currency"),
        "country": data.get("country"), "website": data.get("weburl"), "summary": None,
        "fundamentals": {"marketCap": _num(data.get("marketCapitalization")) * 1e6} if _num(data.get("marketCapitalization")) else {},
        "provider": "finnhub",
    }


# ------------------------------------------------------------------ public API

def _wrap(provider: str, fn):
    def call():
        try:
            value = fn()
        except ProviderError as exc:
            if exc.kind != "not_found":
                _record(provider, False, exc.message)
            raise
        _record(provider, True)
        return value
    return call


def _attach_meta(result) -> dict:
    value = dict(result.value)
    value["fetched_at"] = result.fetched_at
    value["stale"] = result.stale
    if result.stale:
        value["stale_reason"] = result.error
    return value


def get_quote(symbol: str, force: bool = False) -> dict:
    s = get_settings()
    provider = s.market_data_provider
    fn = _finnhub_quote if provider == "finnhub" else _yahoo_quote
    res = cached_call(_cache, f"quote:{provider}:{symbol}", s.quote_cache_seconds,
                      _wrap(provider, lambda: fn(symbol)), force=force)
    q = _attach_meta(res)
    # Also flag quotes whose provider timestamp is old (e.g. market closed / delayed feed).
    mt = q.get("market_time")
    q["market_closed_or_delayed"] = bool(mt and (datetime.now(timezone.utc) - mt).total_seconds() > s.stale_after_seconds)
    return q


def get_profile(symbol: str) -> dict:
    s = get_settings()
    provider = s.market_data_provider
    fn = _finnhub_profile if provider == "finnhub" else _yahoo_profile
    res = cached_call(_cache, f"profile:{provider}:{symbol}", s.profile_cache_seconds, _wrap(provider, lambda: fn(symbol)))
    return _attach_meta(res)


def get_history(symbol: str, period: str = "1y") -> dict:
    if period not in {"1mo", "3mo", "6mo", "1y", "2y", "5y"}:
        raise ValueError("Unsupported period")
    s = get_settings()
    res = cached_call(_cache, f"history:{symbol}:{period}", s.history_cache_seconds,
                      _wrap("yahoo", lambda: _yahoo_history(symbol, period)))
    return {"symbol": symbol, "period": period, "points": res.value, "fetched_at": res.fetched_at,
            "stale": res.stale, "provider": "yahoo"}


def search(query: str) -> list[dict]:
    res = cached_call(_cache, f"search:{query.lower()}", 3600, _wrap("yahoo", lambda: _yahoo_search(query)))
    return res.value


def resolve_symbol(ticker: str) -> str | None:
    """Map a broker ticker (e.g. RELIANCE) to a priceable symbol (e.g. RELIANCE.NS)."""
    entry, fresh = _cache.get(f"resolve:{ticker}", 86400)
    if entry is not None and fresh:
        return entry.value
    if "." in ticker or ticker.startswith("^"):
        candidates = [ticker]
    else:
        # TICKER_SUFFIXES sets the listing preference, e.g. ".NS,.BO," = NSE, then BSE, then the bare
        # symbol (US). Without it a bare "INFY" would resolve to the US ADR instead of the NSE share.
        candidates = [f"{ticker}{sfx}" for sfx in get_settings().ticker_suffixes]
    for cand in candidates:
        try:
            get_quote(cand)
        except ProviderError as exc:
            if exc.kind == "not_found":
                continue
            raise  # provider outage: don't fall through to a less-preferred listing or cache a miss
        _cache.set(f"resolve:{ticker}", cand)
        return cand
    _cache.set(f"resolve:{ticker}", None)
    return None


def get_quotes(symbols: list[str], force: bool = False) -> dict[str, dict | ProviderError]:
    out: dict[str, dict | ProviderError] = {}
    unique = list(dict.fromkeys(symbols))

    def one(sym):
        try:
            return sym, get_quote(sym, force=force)
        except ProviderError as exc:
            return sym, exc

    with ThreadPoolExecutor(max_workers=min(4, max(1, len(unique)))) as pool:
        for sym, val in pool.map(one, unique):
            out[sym] = val
    return out


def get_profiles(symbols: list[str]) -> dict[str, dict | None]:
    unique = list(dict.fromkeys(symbols))

    def one(sym):
        try:
            return sym, get_profile(sym)
        except ProviderError:
            return sym, None

    with ThreadPoolExecutor(max_workers=min(4, max(1, len(unique)))) as pool:
        return dict(pool.map(one, unique))


def clear_cache() -> None:
    _cache.clear()
