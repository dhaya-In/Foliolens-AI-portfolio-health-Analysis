from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ActivityLog, Holding as HoldingRow, PortfolioSnapshot, User, WatchlistItem
from app.db.session import get_db
from app.deps import get_current_user
from app.models.schemas import HoldingIn, HoldingUpdate
from app.services import ai_insights, analytics, market_data, metrics_engine
from app.services.auth_service import log_activity
from app.services.http_client import ProviderError
from app.services.portfolio_service import holding_to_dict, price_portfolio

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _owned_holding(db: Session, user: User, holding_id: int) -> HoldingRow:
    # Ownership is part of the query: another user's id simply isn't found (404, no existence leak).
    row = db.scalar(select(HoldingRow).where(HoldingRow.id == holding_id, HoldingRow.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Holding not found.")
    return row


def _meta(priced: dict) -> dict:
    return {"last_refreshed": priced["last_refreshed"], "oldest_price": priced["oldest_price"],
            "any_stale": priced["any_stale"], "stale_after_seconds": get_settings().stale_after_seconds,
            "errors": priced["errors"]}


def _holdings_payload(priced: dict) -> list[dict]:
    totals = priced["totals"]
    out = []
    for h in priced["holdings"]:
        same_ccy = (h.currency or "UNKNOWN") == totals["currency"]
        out.append(holding_to_dict(h, totals["total_value"] if same_ccy else None))
    return out


@router.get("/holdings")
def list_holdings(refresh: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    priced = price_portfolio(db, user.id, force=refresh)
    return {"holdings": _holdings_payload(priced), "totals": priced["totals"], **_meta(priced)}


@router.post("/holdings", status_code=status.HTTP_201_CREATED)
def add_holding(body: HoldingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.scalar(select(HoldingRow.id).where(HoldingRow.user_id == user.id, HoldingRow.ticker == body.ticker)):
        raise HTTPException(status_code=409, detail=f"{body.ticker} is already in your portfolio. Edit it instead.")
    try:
        symbol = market_data.resolve_symbol(body.ticker)
    except ProviderError:
        symbol = None  # provider down: keep the holding, resolve later
    row = HoldingRow(user_id=user.id, ticker=body.ticker, symbol=symbol,
                     quantity=body.quantity, avg_buy_price=body.avg_buy_price)
    db.add(row)
    log_activity(db, user.id, "portfolio", f"Added {body.ticker}.")
    db.commit()
    return {"id": row.id, "ticker": row.ticker, "symbol": row.symbol,
            "warning": None if symbol else f"No market listing found yet for {body.ticker}; it will show as unpriced."}


@router.put("/holdings/{holding_id}")
def update_holding(holding_id: int, body: HoldingUpdate, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    row = _owned_holding(db, user, holding_id)
    row.quantity, row.avg_buy_price = body.quantity, body.avg_buy_price
    log_activity(db, user.id, "portfolio", f"Updated {row.ticker}.")
    db.commit()
    return {"id": row.id, "ticker": row.ticker, "quantity": row.quantity, "avg_buy_price": row.avg_buy_price}


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(holding_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _owned_holding(db, user, holding_id)
    log_activity(db, user.id, "portfolio", f"Removed {row.ticker}.")
    db.delete(row)
    db.commit()


@router.get("/overview")
def overview(refresh: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    priced = price_portfolio(db, user.id, force=refresh)
    totals = priced["totals"]
    primary = priced["primary_holdings"]
    holdings = _holdings_payload(priced)
    metrics = metrics_engine.compute_all_metrics(primary, {h.ticker: h.beta for h in primary}) if primary else None
    sectors = metrics_engine.calculate_sector_breakdown(primary) if primary else {}

    movers = sorted([h for h in holdings if h["day_change_pct"] is not None],
                    key=lambda h: h["day_change_pct"], reverse=True)
    alerts = []
    if metrics and metrics.concentration_top_holding_pct > 20:
        alerts.append({"level": "warning", "message": f"{metrics.top_holding_ticker} is "
                       f"{metrics.concentration_top_holding_pct}% of your portfolio (concentration risk)."})
    if metrics and metrics.concentration_top_sector_pct > 40:
        alerts.append({"level": "warning", "message": f"{metrics.top_sector} sector is "
                       f"{metrics.concentration_top_sector_pct}% of your portfolio."})
    if totals["unpriced"]:
        alerts.append({"level": "error", "message": "No live price for: " + ", ".join(totals["unpriced"])
                       + ". These holdings are excluded from totals."})
    if totals["excluded_other_currency"]:
        alerts.append({"level": "info", "message": "Holdings in another currency are excluded from totals: "
                       + ", ".join(totals["excluded_other_currency"]) + "."})
    if priced["any_stale"]:
        alerts.append({"level": "warning", "message": "Some prices could not be refreshed; cached values are shown."})
    for w in db.scalars(select(WatchlistItem).where(WatchlistItem.user_id == user.id)):
        if w.alert_above is None and w.alert_below is None:
            continue
        try:
            q = market_data.get_quote(w.symbol)
        except ProviderError:
            continue
        if w.alert_above is not None and q["price"] >= w.alert_above:
            alerts.append({"level": "info", "message": f"Watchlist: {w.symbol} is at {q['price']:,.2f}, above your alert of {w.alert_above:,.2f}."})
        if w.alert_below is not None and q["price"] <= w.alert_below:
            alerts.append({"level": "info", "message": f"Watchlist: {w.symbol} is at {q['price']:,.2f}, below your alert of {w.alert_below:,.2f}."})

    activity = db.scalars(select(ActivityLog).where(ActivityLog.user_id == user.id)
                          .order_by(ActivityLog.created_at.desc()).limit(8)).all()
    return {
        "totals": totals,
        "health_score": metrics.health_score if metrics else None,
        "diversification_score": metrics.diversification_score if metrics else None,
        "sector_allocation": [{"name": k, "value": v} for k, v in sectors.items()],
        "top_holdings": sorted([h for h in holdings if h["weight_pct"] is not None],
                               key=lambda h: h["weight_pct"], reverse=True)[:5],
        "top_gainers": movers[:3],
        "top_losers": list(reversed(movers[-3:])) if len(movers) > 3 else [],
        "alerts": alerts,
        "activity": [{"kind": a.kind, "message": a.message, "created_at": a.created_at} for a in activity],
        **_meta(priced),
    }


@router.get("/health")
def health(period: str = Query("1y", pattern="^(6mo|1y|2y)$"), refresh: bool = False,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    priced = price_portfolio(db, user.id, force=refresh)
    primary = priced["primary_holdings"]
    if not primary:
        return {"empty": True, "metrics": None, **_meta(priced), "totals": priced["totals"]}
    betas = {h.ticker: h.beta for h in primary}
    metrics = metrics_engine.compute_all_metrics(primary, betas)
    sectors = metrics_engine.calculate_sector_breakdown(primary)
    hist = analytics.portfolio_history(primary, period)
    total = metrics.total_value
    weights = sorted(({"ticker": h.ticker, "weight_pct": round(h.current_value / total * 100, 2), "beta": h.beta,
                       "sector": h.sector, **hist.get("per_holding", {}).get(h.ticker, {})}
                      for h in primary), key=lambda x: x["weight_pct"], reverse=True)

    indicators = []

    def ind(name, value, status_, explanation):
        indicators.append({"name": name, "value": value, "status": status_, "explanation": explanation})

    ind("Diversification", f"{metrics.diversification_score}/100",
        "good" if metrics.diversification_score >= 70 else "watch" if metrics.diversification_score >= 45 else "risk",
        "Based on the Herfindahl index of holding weights: 100 = evenly spread, 0 = all in one stock.")
    ind("Largest holding", f"{metrics.top_holding_ticker} · {metrics.concentration_top_holding_pct}%",
        "good" if metrics.concentration_top_holding_pct <= 10 else "watch" if metrics.concentration_top_holding_pct <= 20 else "risk",
        "Above ~10-20% in one stock, a single company's problems can dominate your results.")
    ind("Largest sector", f"{metrics.top_sector} · {metrics.concentration_top_sector_pct}%",
        "good" if metrics.concentration_top_sector_pct <= 25 else "watch" if metrics.concentration_top_sector_pct <= 40 else "risk",
        "Stocks in one sector tend to fall together when that industry has a bad period.")
    if metrics.portfolio_beta is not None:
        ind("Portfolio beta", f"{metrics.portfolio_beta} ({metrics.beta_coverage_pct}% of value covered)",
            "good" if abs(metrics.portfolio_beta - 1) < 0.2 else "watch",
            "Beta compares historical sensitivity to the market: 1.2 means ~20% larger swings than the index.")
    else:
        ind("Portfolio beta", "unavailable", "unknown", "The data provider did not report beta for these holdings.")
    if hist.get("stats") and hist["stats"]["volatility_pct"] is not None:
        v = hist["stats"]["volatility_pct"]
        ind("Volatility (annualised)", f"{v:.1f}%", "good" if v < 18 else "watch" if v < 28 else "risk",
            "Standard deviation of daily returns of your current holdings over the period, annualised.")
        ind("Max drawdown", f"{hist['stats']['max_drawdown_pct']:.1f}%",
            "good" if hist["stats"]["max_drawdown_pct"] > -15 else "watch" if hist["stats"]["max_drawdown_pct"] > -30 else "risk",
            "The largest peak-to-trough fall of your current holdings during the period.")
    else:
        ind("Volatility", "unavailable", "unknown", "Not enough price history was available.")

    return {
        "empty": False,
        "metrics": metrics.model_dump(),
        "sector_breakdown": [{"name": k, "value": v} for k, v in sectors.items()],
        "weights": weights,
        "indicators": indicators,
        "history": {"period": period, "points": hist["points"], "stats": hist.get("stats"),
                    "missing": hist.get("missing", []),
                    "note": "Value of your current holdings at past prices (constant quantities); past trades are not included."},
        "insights": ai_insights.portfolio_insights(primary, metrics, priced["totals"]["currency"]),
        "totals": priced["totals"],
        **_meta(priced),
    }


@router.get("/history")
def history(period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y)$"),
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    priced = price_portfolio(db, user.id, with_profiles=False)
    hist = analytics.portfolio_history(priced["primary_holdings"], period)
    snaps = db.scalars(select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user.id)
                       .order_by(PortfolioSnapshot.taken_at)).all()
    return {
        "period": period,
        "currency": priced["totals"]["currency"],
        "points": hist["points"], "stats": hist.get("stats"), "missing": hist.get("missing", []),
        "cost_basis": priced["totals"]["total_cost"],
        "snapshots": [{"taken_at": s.taken_at, "total_value": s.total_value, "total_cost": s.total_cost,
                       "currency": s.currency} for s in snaps],
        **_meta(priced),
    }
