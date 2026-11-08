"""Prices a user's stored holdings with live market data and computes portfolio totals.

All functions take the authenticated user's id and only ever query rows with that user_id.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import as_utc, utcnow
from app.db.models import Holding as HoldingRow
from app.db.models import PortfolioSnapshot
from app.models.schemas import Holding
from app.services import market_data
from app.services.http_client import ProviderError


def user_holdings(db: Session, user_id: int) -> list[HoldingRow]:
    return list(db.scalars(select(HoldingRow).where(HoldingRow.user_id == user_id).order_by(HoldingRow.ticker)))


def _ensure_symbols(db: Session, rows: list[HoldingRow]) -> list[dict]:
    """Retry symbol resolution for holdings imported while the provider was unavailable."""
    errors = []
    missing = [r for r in rows if not r.symbol]
    if not missing:
        return errors

    def resolve(row):
        try:
            return row, market_data.resolve_symbol(row.ticker), None
        except ProviderError as exc:
            return row, None, exc

    with ThreadPoolExecutor(max_workers=min(6, len(missing))) as pool:
        for row, sym, exc in pool.map(resolve, missing):
            if sym:
                row.symbol = sym
            elif exc is None:
                errors.append({"ticker": row.ticker, "kind": "not_found",
                               "message": f"{row.ticker}: no market listing found (tried {row.ticker}, .NS, .BO)."})
            else:
                errors.append({"ticker": row.ticker, **exc.public()})
    db.commit()
    return errors


def price_portfolio(db: Session, user_id: int, force: bool = False, with_profiles: bool = True) -> dict:
    rows = user_holdings(db, user_id)
    errors = _ensure_symbols(db, rows)
    symbols = [r.symbol for r in rows if r.symbol]
    quotes = market_data.get_quotes(symbols, force=force) if symbols else {}
    ok_symbols = [s for s, q in quotes.items() if isinstance(q, dict)]
    profiles = market_data.get_profiles(ok_symbols) if (with_profiles and ok_symbols) else {}

    holdings: list[Holding] = []
    fetched_times = []
    for r in rows:
        q = quotes.get(r.symbol) if r.symbol else None
        p = profiles.get(r.symbol) if r.symbol else None
        if isinstance(q, ProviderError):
            errors.append({"ticker": r.ticker, **q.public()})
            q = None
        if q:
            fetched_times.append(q["fetched_at"])
        holdings.append(Holding(
            id=r.id, ticker=r.ticker, symbol=r.symbol,
            company_name=(p or {}).get("name") or (q or {}).get("name") or r.ticker,
            quantity=r.quantity, avg_buy_price=r.avg_buy_price,
            current_price=q["price"] if q else None,
            previous_close=q.get("previous_close") if q else None,
            currency=(q or {}).get("currency") or (p or {}).get("currency"),
            sector=(p or {}).get("sector") or ("Unknown" if q else None),
            beta=(p or {}).get("beta"),
            price_time=q.get("market_time") if q else None,
            stale=bool(q and q.get("stale")),
        ))

    priced = [h for h in holdings if h.priced]
    currencies = Counter(h.currency or "UNKNOWN" for h in priced)
    primary = currencies.most_common(1)[0][0] if currencies else None
    in_primary = [h for h in priced if (h.currency or "UNKNOWN") == primary]
    other_currency = [h.ticker for h in priced if (h.currency or "UNKNOWN") != primary]

    total_value = sum(h.current_value for h in in_primary)
    total_cost = sum(h.cost_basis for h in in_primary)
    day_change = sum(h.day_change for h in in_primary if h.day_change is not None)
    prev_value = total_value - day_change
    totals = {
        "currency": primary,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "gain_loss": round(total_value - total_cost, 2),
        "gain_loss_pct": round((total_value - total_cost) / total_cost * 100, 2) if total_cost else None,
        "day_change": round(day_change, 2),
        "day_change_pct": round(day_change / prev_value * 100, 2) if prev_value else None,
        "holdings_count": len(holdings),
        "priced_count": len(priced),
        "unpriced": [h.ticker for h in holdings if not h.priced],
        "excluded_other_currency": other_currency,
    }
    if primary and in_primary:
        _maybe_snapshot(db, user_id, primary, total_value, total_cost, len(in_primary))
    return {
        "holdings": holdings,
        "primary_holdings": in_primary,
        "totals": totals,
        "errors": errors,
        "last_refreshed": max(fetched_times) if fetched_times else None,
        "oldest_price": min(fetched_times) if fetched_times else None,
        "any_stale": any(h.stale for h in holdings),
    }


def _maybe_snapshot(db: Session, user_id: int, currency: str, value: float, cost: float, n: int) -> None:
    last = db.scalar(select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)
                     .order_by(PortfolioSnapshot.taken_at.desc()).limit(1))
    if last and as_utc(last.taken_at) > utcnow() - timedelta(hours=1) and last.currency == currency:
        return
    db.add(PortfolioSnapshot(user_id=user_id, currency=currency, total_value=round(value, 2),
                             total_cost=round(cost, 2), priced_holdings=n))
    db.commit()


def holding_to_dict(h: Holding, total_value: float | None = None) -> dict:
    d = h.model_dump()
    d.update({
        "market_value": round(h.current_value, 2) if h.priced else None,
        "cost_basis": round(h.cost_basis, 2),
        "gain_loss": round(h.gain_loss, 2) if h.gain_loss is not None else None,
        "gain_loss_pct": round(h.gain_loss_pct, 2) if h.gain_loss_pct is not None else None,
        "day_change": round(h.day_change, 2) if h.day_change is not None else None,
        "day_change_pct": round((h.current_price - h.previous_close) / h.previous_close * 100, 2)
        if (h.current_price is not None and h.previous_close) else None,
        "weight_pct": round(h.current_value / total_value * 100, 2) if (total_value and h.priced) else None,
    })
    return d
