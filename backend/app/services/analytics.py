"""Price-history analytics: returns, volatility, drawdown, moving averages, RSI and a
"current holdings over time" series (what today's holdings would have been worth historically)."""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor

from app.models.schemas import Holding
from app.services import market_data
from app.services.http_client import ProviderError

TRADING_DAYS = 252


def _returns(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]


def annualized_volatility(closes: list[float]) -> float | None:
    r = _returns(closes)
    if len(r) < 20:
        return None
    mean = sum(r) / len(r)
    var = sum((x - mean) ** 2 for x in r) / (len(r) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS) * 100


def max_drawdown(closes: list[float]) -> float | None:
    if len(closes) < 2:
        return None
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    return mdd * 100


def sma(closes: list[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(len(closes) - n, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g, avg_l = sum(gains) / n, sum(losses) / n
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


def pct_return(closes: list[float], days: int) -> float | None:
    if len(closes) <= days or not closes[-days - 1]:
        return None
    return (closes[-1] / closes[-days - 1] - 1) * 100


def price_stats(points: list[dict]) -> dict:
    closes = [p["close"] for p in points]
    hi, lo = (max(closes), min(closes)) if closes else (None, None)
    return {
        "observations": len(closes),
        "first_date": points[0]["date"] if points else None,
        "last_date": points[-1]["date"] if points else None,
        "return_1m_pct": pct_return(closes, 21),
        "return_3m_pct": pct_return(closes, 63),
        "return_6m_pct": pct_return(closes, 126),
        "return_1y_pct": pct_return(closes, min(len(closes) - 1, 250)) if len(closes) > 200 else None,
        "volatility_pct": annualized_volatility(closes),
        "max_drawdown_pct": max_drawdown(closes),
        "sma50": sma(closes, 50),
        "sma200": sma(closes, 200),
        "rsi14": rsi(closes),
        "period_high": hi,
        "period_low": lo,
        "last_close": closes[-1] if closes else None,
    }


def portfolio_history(holdings: list[Holding], period: str = "1y") -> dict:
    """Value of the *current* holdings across past dates (constant quantities). This is a
    hypothetical series - it ignores past buys/sells - and is labelled as such in the UI."""
    priced = [h for h in holdings if h.symbol and h.priced]
    if not priced:
        return {"points": [], "missing": [], "stats": None}

    def fetch(h):
        try:
            return h, market_data.get_history(h.symbol, period)
        except ProviderError:
            return h, None

    with ThreadPoolExecutor(max_workers=min(8, len(priced))) as pool:
        results = list(pool.map(fetch, priced))

    series, missing, per_holding = {}, [], {}
    for h, hist in results:
        if not hist or len(hist["points"]) < 2:
            missing.append(h.ticker)
            continue
        series[h.ticker] = ({p["date"]: p["close"] for p in hist["points"]}, h.quantity)
        per_holding[h.ticker] = {
            "volatility_pct": annualized_volatility([p["close"] for p in hist["points"]]),
            "max_drawdown_pct": max_drawdown([p["close"] for p in hist["points"]]),
        }
    if not series:
        return {"points": [], "missing": missing, "stats": None, "per_holding": {}}

    # Use dates where every included holding has a close, so the series isn't distorted by gaps.
    common = sorted(set.intersection(*(set(s[0]) for s in series.values())))
    points = [{"date": d, "value": round(sum(px[d] * qty for px, qty in series.values()), 2)} for d in common]
    values = [p["value"] for p in points]
    stats = {
        "volatility_pct": annualized_volatility(values),
        "max_drawdown_pct": max_drawdown(values),
        "period_return_pct": (values[-1] / values[0] - 1) * 100 if len(values) > 1 and values[0] else None,
        "observations": len(values),
    }
    return {"points": points, "missing": missing, "stats": stats, "per_holding": per_holding,
            "included": list(series)}
