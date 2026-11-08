"""Downloadable reports (CSV). Every report is built only from the signed-in user's data."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PortfolioSnapshot, User
from app.db.session import get_db
from app.deps import get_current_user
from app.routers.imports import csv_response
from app.services import analytics, metrics_engine
from app.services.auth_service import log_activity
from app.services.portfolio_service import holding_to_dict, price_portfolio

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")


@router.get("/pnl.csv")
def pnl_report(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    priced = price_portfolio(db, user.id)
    total = priced["totals"]["total_value"]
    rows = []
    for h in priced["holdings"]:
        d = holding_to_dict(h, total if (h.currency or "UNKNOWN") == priced["totals"]["currency"] else None)
        rows.append([h.ticker, h.company_name, h.sector, h.currency, h.quantity, round(h.avg_buy_price, 4),
                     h.current_price, d["cost_basis"], d["market_value"], d["gain_loss"], d["gain_loss_pct"],
                     d["day_change"], d["weight_pct"], h.price_time.isoformat() if h.price_time else "",
                     "yes" if h.stale else "no"])
    t = priced["totals"]
    rows.append([])
    rows.append(["TOTAL (" + (t["currency"] or "-") + ")", "", "", t["currency"], "", "", "", t["total_cost"],
                 t["total_value"], t["gain_loss"], t["gain_loss_pct"], t["day_change"], 100 if t["total_value"] else "",
                 "", ""])
    log_activity(db, user.id, "export", "Downloaded profit/loss report.")
    db.commit()
    return csv_response(f"foliolens-pnl-{_stamp()}.csv",
                        ["Symbol", "Company", "Sector", "Currency", "Quantity", "Avg Price", "Current Price",
                         "Cost Basis", "Market Value", "Gain/Loss", "Gain/Loss %", "Day Change", "Weight %",
                         "Price Time (UTC)", "Stale Price"], rows)


@router.get("/allocation.csv")
def allocation_report(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    priced = price_portfolio(db, user.id)
    primary = priced["primary_holdings"]
    sectors = metrics_engine.calculate_sector_breakdown(primary)
    total = priced["totals"]["total_value"]
    rows = [["Sector", name, pct] for name, pct in sectors.items()]
    rows += [["Holding", h.ticker, round(h.current_value / total * 100, 2) if total else None] for h in
             sorted(primary, key=lambda x: x.current_value, reverse=True)]
    log_activity(db, user.id, "export", "Downloaded allocation report.")
    db.commit()
    return csv_response(f"foliolens-allocation-{_stamp()}.csv", ["Type", "Name", "Weight %"], rows)


@router.get("/performance.csv")
def performance_report(period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y)$"),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    priced = price_portfolio(db, user.id, with_profiles=False)
    hist = analytics.portfolio_history(priced["primary_holdings"], period)
    snaps = db.scalars(select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user.id)
                       .order_by(PortfolioSnapshot.taken_at)).all()
    rows = [["Historical value of current holdings", p["date"], p["value"], ""] for p in hist["points"]]
    rows += [["Recorded snapshot", s.taken_at.isoformat(), s.total_value, s.total_cost] for s in snaps]
    log_activity(db, user.id, "export", "Downloaded performance report.")
    db.commit()
    return csv_response(f"foliolens-performance-{period}-{_stamp()}.csv",
                        ["Series", "Date", "Value", "Cost Basis"], rows)
