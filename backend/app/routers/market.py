"""Market data, news and stock-analysis endpoints (all require authentication)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db
from app.deps import get_current_user
from app.models.schemas import normalize_ticker
from app.services import ai_insights, market_data, news, signals
from app.services.http_client import ProviderError
from app.services.portfolio_service import holding_to_dict, price_portfolio

router = APIRouter(tags=["market & insights"])

STATUS_FOR_KIND = {"not_found": 404, "not_configured": 503, "auth": 502, "rate_limited": 503,
                   "unavailable": 503, "bad_response": 502}


def provider_http_error(exc: ProviderError) -> HTTPException:
    return HTTPException(status_code=STATUS_FOR_KIND.get(exc.kind, 502), detail=exc.message,
                         headers={"X-Provider-Error": exc.kind})


def _symbol(value: str) -> str:
    try:
        return normalize_ticker(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


SymbolPath = Path(..., min_length=1, max_length=25)


@router.get("/api/market/search")
def search(q: str = Query(..., min_length=1, max_length=60), user: User = Depends(get_current_user)):
    try:
        return {"results": market_data.search(q.strip())}
    except ProviderError as exc:
        raise provider_http_error(exc)


@router.get("/api/market/quote/{symbol}")
def quote(symbol: str = SymbolPath, refresh: bool = False, user: User = Depends(get_current_user)):
    sym = _symbol(symbol)
    try:
        resolved = market_data.resolve_symbol(sym) or sym
        return market_data.get_quote(resolved, force=refresh)
    except ProviderError as exc:
        raise provider_http_error(exc)


@router.get("/api/market/history/{symbol}")
def history(symbol: str = SymbolPath, period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y)$"),
            user: User = Depends(get_current_user)):
    sym = _symbol(symbol)
    try:
        return market_data.get_history(market_data.resolve_symbol(sym) or sym, period)
    except ProviderError as exc:
        raise provider_http_error(exc)


# ------------------------------------------------------------------ news

@router.get("/api/news")
def get_news(symbol: str | None = Query(None, max_length=25), q: str | None = Query(None, max_length=80),
             region: str = Query("india", pattern="^(india|us|global)$"), limit: int = Query(12, ge=1, le=30),
             refresh: bool = False, user: User = Depends(get_current_user)):
    try:
        if symbol:
            sym = _symbol(symbol)
            resolved = market_data.resolve_symbol(sym) or sym
            name = None
            try:
                name = market_data.get_profile(resolved).get("name")
            except ProviderError:
                pass
            return news.get_news(symbol=resolved, query=name or resolved, limit=limit, force=refresh)
        return news.get_news(query=q or news.MARKET_QUERIES[region], limit=limit, force=refresh)
    except ProviderError as exc:
        raise provider_http_error(exc)


@router.get("/api/news/portfolio")
def portfolio_news(refresh: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """News for the user's five largest priced holdings."""
    priced = price_portfolio(db, user.id, with_profiles=True)
    top = sorted([h for h in priced["holdings"] if h.priced and h.symbol],
                 key=lambda h: h.current_value, reverse=True)[:5]

    def fetch(h):
        try:
            return h, news.get_news(symbol=h.symbol, query=h.company_name or h.symbol, limit=5, force=refresh), None
        except ProviderError as exc:
            return h, None, exc

    groups, errors = [], []
    with ThreadPoolExecutor(max_workers=5) as pool:
        for h, res, exc in pool.map(fetch, top):
            if exc:
                errors.append({"ticker": h.ticker, **exc.public()})
            else:
                groups.append({"ticker": h.ticker, "symbol": h.symbol, "name": h.company_name, **res})
    return {"groups": groups, "errors": errors}


# ------------------------------------------------------------------ analysis / signals

@router.get("/api/insights/{symbol}")
def analyze(symbol: str = SymbolPath, refresh: bool = False, ai: bool = False,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sym = _symbol(symbol)
    try:
        resolved = market_data.resolve_symbol(sym)
    except ProviderError as exc:
        raise provider_http_error(exc)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"No market listing found for {sym}. Try searching by company name.")

    errors = []

    def safe(name, fn):
        try:
            return fn()
        except ProviderError as exc:
            errors.append({"source": name, **exc.public()})
            return None

    quote = safe("quote", lambda: market_data.get_quote(resolved, force=refresh))
    profile = safe("profile", lambda: market_data.get_profile(resolved))
    hist = safe("history", lambda: market_data.get_history(resolved, "1y"))
    news_res = safe("news", lambda: news.get_news(symbol=resolved, query=(profile or {}).get("name") or resolved,
                                                  limit=15, force=refresh))

    # The user's own position (only theirs) feeds the concentration factor.
    position = None
    priced = price_portfolio(db, user.id, with_profiles=False)
    total = priced["totals"]["total_value"]
    for h in priced["holdings"]:
        if h.symbol == resolved or h.ticker == sym:
            d = holding_to_dict(h, total if (h.currency or "UNKNOWN") == priced["totals"]["currency"] else None)
            position = {k: d[k] for k in ("quantity", "avg_buy_price", "market_value", "gain_loss_pct", "weight_pct")}
            break

    result = signals.build_signal(quote=quote, profile=profile, history=hist, news=news_res, position=position)
    result["data_errors"] = errors
    result["ai"] = {"configured": ai_insights.ai_configured(), "interpretation": None, "error": None}
    if ai:
        if result["signal_code"] == "insufficient":
            result["ai"]["error"] = "AI interpretation is skipped when data is insufficient."
        else:
            try:
                result["ai"]["interpretation"] = ai_insights.interpret_signal(result)
            except ai_insights.AIError as exc:
                result["ai"]["error"] = exc.message
    return result
