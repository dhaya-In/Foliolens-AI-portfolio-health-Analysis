"""Evidence-based decision-support signals.

The signal is a deterministic, explainable sum of factor contributions computed from real data
(price history, fundamentals, news sentiment, the user's own position). Each factor states whether
its data was available; unavailable factors contribute nothing and lower the evidence quality.
This is NOT a price prediction and NOT personalised financial advice.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services import analytics
from app.services.market_data import FUNDAMENTAL_FIELDS as _FUND_LABELS

SIGNALS = {
    "buy": "Potential Buy / Consider Buying",
    "hold": "Hold / Wait",
    "reduce": "Potential Sell / Reduce Exposure",
    "insufficient": "Insufficient Data",
}

DISCLAIMER = (
    "Decision-support only, not financial advice. Signals summarise past prices, reported fundamentals "
    "and recent news using fixed rules; they do not predict future prices. Do your own research or "
    "consult a licensed adviser before trading."
)

RECENT_NEWS_DAYS = 14


def _fmt_pct(v: float | None, digits: int = 1) -> str:
    return "n/a" if v is None else f"{v:+.{digits}f}%"


def _factor(name, available, contribution, value_text, explanation):
    direction = "positive" if contribution > 0 else "negative" if contribution < 0 else "neutral"
    return {"name": name, "available": available, "contribution": round(contribution, 2),
            "direction": direction if available else "unavailable", "value": value_text,
            "explanation": explanation}


def build_signal(*, quote: dict | None, profile: dict | None, history: dict | None, news: dict | None,
                 position: dict | None) -> dict:
    now = datetime.now(timezone.utc)
    points = (history or {}).get("points") or []
    stats = analytics.price_stats(points) if points else None
    price = quote["price"] if quote else None
    fundamentals = (profile or {}).get("fundamentals") or {}
    factors: list[dict] = []

    # 1. Trend ---------------------------------------------------------------------------
    if stats and stats["sma50"] and stats["sma200"] and price:
        s50, s200 = stats["sma50"], stats["sma200"]
        if price > s50 > s200:
            c, txt = 1.5, "Price is above its 50-day average, which is above its 200-day average (established uptrend)."
        elif price < s50 < s200:
            c, txt = -1.5, "Price is below its 50-day average, which is below its 200-day average (established downtrend)."
        else:
            c, txt = 0.0, "Price and moving averages are not aligned in either direction (mixed trend)."
        factors.append(_factor("Price trend", True, c, f"price {price:,.2f} · 50d {s50:,.2f} · 200d {s200:,.2f}", txt))
    else:
        factors.append(_factor("Price trend", False, 0, "n/a", "Needs at least 200 trading days of price history."))

    # 2. Momentum ------------------------------------------------------------------------
    r3, r6 = (stats or {}).get("return_3m_pct"), (stats or {}).get("return_6m_pct")
    if r3 is not None and r6 is not None:
        avg = (r3 + r6) / 2
        c = 1.0 if avg > 10 else -1.0 if avg < -10 else 0.0
        factors.append(_factor("Momentum (3m / 6m)", True, c, f"3m {_fmt_pct(r3)} · 6m {_fmt_pct(r6)}",
                               "Strong recent gains" if c > 0 else "Sustained recent losses" if c < 0
                               else "Recent returns are modest; momentum is not decisive."))
    else:
        factors.append(_factor("Momentum (3m / 6m)", False, 0, "n/a", "Needs about 6 months of price history."))

    # 3. RSI -----------------------------------------------------------------------------
    rsi = (stats or {}).get("rsi14")
    if rsi is not None:
        c = -0.5 if rsi > 70 else 0.5 if rsi < 30 else 0.0
        txt = ("RSI above 70: the recent rise is stretched; this often precedes pauses, but is not a reliable timing signal."
               if rsi > 70 else
               "RSI below 30: recent selling is stretched; this sometimes precedes rebounds, but trends can persist."
               if rsi < 30 else "RSI is in its normal 30-70 range.")
        factors.append(_factor("RSI (14-day)", True, c, f"{rsi:.0f}", txt))
    else:
        factors.append(_factor("RSI (14-day)", False, 0, "n/a", "Needs at least 15 days of prices."))

    # 4. Volatility ----------------------------------------------------------------------
    vol = (stats or {}).get("volatility_pct")
    if vol is not None:
        c = -0.5 if vol > 45 else 0.25 if vol < 20 else 0.0
        factors.append(_factor("Volatility (annualised)", True, c, f"{vol:.1f}%",
                               "High volatility - large swings in both directions are common." if vol > 45 else
                               "Low volatility relative to typical stocks." if vol < 20 else
                               "Volatility is in a typical range for equities."))
    else:
        factors.append(_factor("Volatility (annualised)", False, 0, "n/a", "Needs at least a month of prices."))

    # 5. Valuation -----------------------------------------------------------------------
    pe = fundamentals.get("trailingPE")
    if pe is not None:
        c = -0.5 if pe > 60 else 0.5 if 0 < pe < 15 else 0.0
        factors.append(_factor("Valuation (trailing P/E)", True, c, f"{pe:.1f}",
                               ("A high P/E means the price already assumes strong future growth." if pe > 60 else
                                "A low P/E can indicate an inexpensive stock - or a business the market expects to shrink."
                                if pe < 15 else "P/E is in a middle range.")
                               + " P/E is compared against fixed bands, not the company's own sector, so treat it as a rough guide."))
    else:
        factors.append(_factor("Valuation (trailing P/E)", False, 0, "n/a",
                               "Not reported by the data provider (or the company has negative earnings)."))

    # 6. Profitability & growth ----------------------------------------------------------
    margin, growth = fundamentals.get("profitMargins"), fundamentals.get("revenueGrowth")
    if margin is not None or growth is not None:
        c, parts = 0.0, []
        if margin is not None:
            c += 0.5 if margin > 0.15 else -1.0 if margin < 0 else 0
            parts.append(f"margin {margin * 100:.1f}%")
        if growth is not None:
            c += 0.5 if growth > 0.10 else -0.5 if growth < 0 else 0
            parts.append(f"revenue growth {growth * 100:+.1f}%")
        factors.append(_factor("Profitability & growth", True, c, " · ".join(parts),
                               "Based on the most recent figures reported by the data provider."))
    else:
        factors.append(_factor("Profitability & growth", False, 0, "n/a", "Margins and growth were not reported."))

    # 7. Leverage ------------------------------------------------------------------------
    de = fundamentals.get("debtToEquity")
    if de is not None:
        c = -0.5 if de > 200 else 0.0
        factors.append(_factor("Leverage (debt / equity)", True, c, f"{de:.0f}%",
                               "High debt relative to equity raises risk if conditions worsen." if de > 200
                               else "Leverage is not unusually high. (Banks and financials naturally carry high ratios.)"))
    else:
        factors.append(_factor("Leverage (debt / equity)", False, 0, "n/a", "Not reported."))

    # 8. News sentiment ------------------------------------------------------------------
    articles = (news or {}).get("articles") or []
    recent = [a for a in articles if a.get("published_at") and
              (now - a["published_at"]).days <= RECENT_NEWS_DAYS]
    pos = [a for a in recent if a["sentiment"]["label"] == "positive"]
    neg = [a for a in recent if a["sentiment"]["label"] == "negative"]
    contradictory = len(pos) >= 2 and len(neg) >= 2
    if len(recent) >= 3:
        net = (len(pos) - len(neg)) / len(recent)
        c = 1.0 if net > 0.3 else -1.0 if net < -0.3 else 0.0
        if contradictory:
            c /= 2
        factors.append(_factor("News sentiment", True, c,
                               f"{len(pos)} positive · {len(neg)} negative · {len(recent) - len(pos) - len(neg)} neutral (last {RECENT_NEWS_DAYS} days)",
                               ("Coverage is contradictory, so its weight is halved. " if contradictory else "")
                               + "Sentiment labels come from " + (recent[0]["sentiment"]["method"]) +
                               "; a headline's tone does not establish that it moved or will move the price."))
    else:
        factors.append(_factor("News sentiment", False, 0, f"{len(recent)} recent article(s)",
                               f"Fewer than 3 articles in the last {RECENT_NEWS_DAYS} days - not enough to judge sentiment."))

    # 9. Portfolio concentration ---------------------------------------------------------
    weight = (position or {}).get("weight_pct")
    if position:
        c = -1.0 if weight and weight > 20 else -0.5 if weight and weight > 10 else 0.0
        factors.append(_factor("Your position size", True, c,
                               f"{weight:.1f}% of your portfolio" if weight is not None else "held (weight unknown)",
                               "A single stock above 20% of a portfolio is a concentration risk regardless of its outlook."
                               if c <= -1 else "Over 10% in one stock adds concentration risk." if c < 0
                               else "Position size is within a diversified range."))
    else:
        factors.append(_factor("Your position size", True, 0, "not held", "You do not currently hold this stock."))

    # ---------------------------------------------------------------------- evidence quality
    has_quote = price is not None
    history_full = bool(stats and stats["observations"] >= 200)
    history_min = bool(stats and stats["observations"] >= 60)
    has_fund = len([k for k in ("trailingPE", "profitMargins", "revenueGrowth", "debtToEquity") if k in fundamentals]) >= 2
    has_news = len(recent) >= 3
    groups = {"Price history (200+ days)": history_full, "Fundamentals (2+ metrics)": has_fund,
              f"Recent news (3+ in {RECENT_NEWS_DAYS} days)": has_news}
    n_groups = sum(groups.values())
    stale = bool(quote and quote.get("stale"))

    if not has_quote or not history_min:
        level = "Insufficient"
    else:
        level = {3: "High", 2: "Medium", 1: "Low", 0: "Low"}[n_groups]
        if stale and level != "Low":
            level = {"High": "Medium", "Medium": "Low"}[level]

    score = sum(f["contribution"] for f in factors if f["available"])
    concentration_flag = bool(weight and weight > 20)
    if level == "Insufficient":
        code = "insufficient"
        why = "There is not enough reliable price data to assess this stock" + (
            " (no current quote)." if not has_quote else " (fewer than 60 trading days of history).")
    elif score >= 2.0 and level in ("High", "Medium"):
        code = "buy"
        why = "Most available evidence points the same positive direction."
    elif score <= -2.0 and (level in ("High", "Medium") or concentration_flag):
        code = "reduce"
        why = "Several available factors point negative" + (" and your position is concentrated." if concentration_flag else ".")
    else:
        code = "hold"
        why = ("The available evidence is mixed or not strong enough to justify acting now."
               if level != "Low" else "Evidence quality is low, so the analysis defaults to Hold / Wait.")
    if code == "reduce" and not position:
        why += " Since you don't hold it, this means the evidence does not support buying now."

    available = [f for f in factors if f["available"]]
    positives = [f"{f['name']}: {f['explanation']}" for f in available if f["contribution"] > 0]
    negatives = [f"{f['name']}: {f['explanation']}" for f in available if f["contribution"] < 0]

    risks = []
    if vol is not None and vol > 35:
        risks.append(f"Annualised volatility of {vol:.0f}% means double-digit moves within weeks are plausible.")
    mdd = (stats or {}).get("max_drawdown_pct")
    if mdd is not None and mdd < -25:
        risks.append(f"The stock fell {abs(mdd):.0f}% from a peak within the analysed period.")
    if concentration_flag:
        risks.append(f"This stock is {weight:.0f}% of your portfolio - one adverse event would hurt the whole portfolio.")
    if contradictory:
        risks.append("Recent news is contradictory; the situation may be changing.")
    if neg:
        risks.append(f"{len(neg)} recent article(s) carry negative tone - read them to judge their materiality.")
    if de is not None and de > 200:
        risks.append("High leverage increases sensitivity to interest rates and downturns.")
    missing = [f["name"] for f in factors if not f["available"]]
    if missing:
        risks.append("Not evaluated (data unavailable): " + ", ".join(missing) + ".")
    if stale:
        risks.append("The latest quote could not be refreshed; a cached price is shown.")
    if quote and quote.get("market_closed_or_delayed"):
        risks.append("The market price is not current (market closed or delayed feed).")

    monitor = []
    if stats and stats["sma50"]:
        monitor.append(f"Whether the price holds {'above' if price and price > stats['sma50'] else 'below'} its 50-day average (~{stats['sma50']:,.2f}).")
    if stats and stats["sma200"]:
        monitor.append(f"The 200-day average (~{stats['sma200']:,.2f}) as a longer-term trend reference.")
    monitor.append("The next quarterly results: revenue growth, margins and management guidance.")
    if has_news or recent:
        monitor.append("Follow-ups to the news items listed below - confirmed developments matter more than headlines.")
    if position:
        monitor.append("Your position weight if the price moves sharply.")

    # Waiting for a lower price ----------------------------------------------------------
    hi = (stats or {}).get("period_high")
    near_high = bool(price and hi and price >= hi * 0.97)
    r1 = (stats or {}).get("return_1m_pct")
    if not stats:
        wait = {"supported": False, "explanation": "No price history is available to evaluate this."}
    elif (rsi is not None and rsi > 70) or (near_high and r1 is not None and r1 > 10):
        wait = {"supported": True, "explanation":
                "Partly. The price is stretched relative to its recent range"
                + (f" (RSI {rsi:.0f})" if rsi is not None and rsi > 70 else "")
                + (f", within 3% of its period high after a {r1:.0f}% one-month gain" if near_high and r1 and r1 > 10 else "")
                + ". Pullbacks after such moves are common, but their timing and size cannot be predicted - waiting can also mean missing further gains."}
    elif factors[0]["available"] and factors[0]["contribution"] < 0:
        wait = {"supported": True, "explanation":
                "As risk management, not a prediction: the stock is in a downtrend. Some investors wait for the trend to stabilise "
                "(for example the price reclaiming its 50-day average) before buying."}
    else:
        wait = {"supported": False, "explanation":
                "No. Nothing in the available data indicates the price is stretched, so assuming it will fall would be speculation."}

    def brief(a):
        return {k: a.get(k) for k in ("title", "source", "url", "published_at", "sentiment", "summary")}

    sources = [{"name": "Market data", "provider": (quote or {}).get("provider"), "as_of": (quote or {}).get("market_time")},
               {"name": "Price history", "provider": (history or {}).get("provider"), "as_of": (stats or {}).get("last_date")},
               {"name": "Company profile & fundamentals", "provider": (profile or {}).get("provider"),
                "as_of": (profile or {}).get("fetched_at")}]
    sources += [{"name": a["title"], "provider": a["source"], "url": a["url"], "as_of": a["published_at"]} for a in recent[:10]]

    return {
        "symbol": (quote or {}).get("symbol") or (profile or {}).get("symbol"),
        "name": (profile or {}).get("name") or (quote or {}).get("name"),
        "sector": (profile or {}).get("sector"),
        "industry": (profile or {}).get("industry"),
        "price": price,
        "currency": (quote or {}).get("currency") or (profile or {}).get("currency"),
        "change_pct": (quote or {}).get("change_pct"),
        "price_time": (quote or {}).get("market_time"),
        "fetched_at": (quote or {}).get("fetched_at"),
        "quote_stale": stale,
        "signal_code": code,
        "signal": SIGNALS[code],
        "why": why,
        "score": round(score, 2),
        "score_explanation": "Sum of factor contributions. >= +2 with Medium/High evidence -> Potential Buy; "
                             "<= -2 -> Potential Sell / Reduce; otherwise Hold / Wait.",
        "evidence_quality": {
            "level": level,
            "groups": groups,
            "explanation": f"{n_groups} of 3 evidence groups available" + (", quote is stale" if stale else "")
                           + ". Quality reflects how much verified data the signal rests on, not the probability of being right.",
        },
        "factors": factors,
        "positives": positives,
        "negatives": negatives,
        "risks": risks,
        "monitor": monitor,
        "wait_for_lower_price": wait,
        "price_stats": stats,
        "fundamentals": {lbl: fundamentals[k] for k, lbl in _FUND_LABELS.items() if k in fundamentals},
        "news": {"positive": [brief(a) for a in pos[:5]], "negative": [brief(a) for a in neg[:5]],
                 "recent": [brief(a) for a in recent[:10]],
                 "recent_count": len(recent), "provider": (news or {}).get("provider"),
                 "fetched_at": (news or {}).get("fetched_at")},
        "position": position,
        "sources": sources,
        "disclaimer": DISCLAIMER,
        "generated_at": now,
    }

