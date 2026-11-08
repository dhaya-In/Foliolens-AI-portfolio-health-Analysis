"""Integration status: which providers are configured and when they last succeeded. Never returns keys."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.db.models import User
from app.deps import get_current_user
from app.services import ai_insights
from app.services.market_data import provider_status

router = APIRouter(tags=["status"])


@router.get("/api/health")
def liveness():
    return {"status": "ok", "service": "FolioLens API"}


@router.get("/api/status")
def integration_status(user: User = Depends(get_current_user)):
    s = get_settings()

    def st(name):
        return provider_status.get(name, {"last_success": None, "last_error": None, "last_error_at": None})

    market_ok = s.market_data_provider == "yahoo" or bool(s.market_data_api_key)
    news_ok = s.news_provider == "yahoo" or bool(s.news_api_key)
    return {
        "market_data": {"provider": s.market_data_provider, "configured": market_ok,
                        "requires_key": s.market_data_provider != "yahoo", **st(s.market_data_provider),
                        "message": None if market_ok else "MARKET_DATA_API_KEY is not set."},
        "news": {"provider": s.news_provider, "configured": news_ok, "requires_key": s.news_provider != "yahoo",
                 **st(s.news_provider), "message": None if news_ok else "FINANCIAL_NEWS_API_KEY is not set."},
        "ai": {"provider": s.ai_provider, "model": s.ai_model if ai_insights.ai_configured() else None,
               "configured": ai_insights.ai_configured(), **st("anthropic"),
               "message": None if ai_insights.ai_configured() else ai_insights.NOT_CONFIGURED},
        "cache_seconds": {"quotes": s.quote_cache_seconds, "news": s.news_cache_seconds,
                          "history": s.history_cache_seconds},
        "stale_after_seconds": s.stale_after_seconds,
    }
