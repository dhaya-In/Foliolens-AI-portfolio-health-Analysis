from datetime import datetime, timedelta, timezone

import pytest

from app.core.cache import TTLCache, cached_call
from app.services import market_data, signals
from app.services.http_client import ProviderError
from tests.conftest import csrf, fake_history, fake_profile, fake_quote, import_sample


def test_stale_cache_used_when_provider_fails():
    cache = TTLCache()
    first = cached_call(cache, "k", -1, lambda: 42)
    assert first.value == 42 and not first.stale

    def boom():
        raise ProviderError("yahoo", "unavailable", "down")

    second = cached_call(cache, "k", -1, boom)
    assert second.value == 42 and second.stale and second.error == "down"
    with pytest.raises(ProviderError):
        cached_call(TTLCache(), "other", 0, boom)  # no cached value -> real error, never fake data


def test_unresolvable_ticker_is_unpriced_not_faked(user_a):
    import_sample(user_a, b"Symbol,Qty,Avg Price\nTCS,1,100\nNOTREAL,5,100\n")
    data = user_a.get("/api/portfolio/holdings").json()
    bad = next(h for h in data["holdings"] if h["ticker"] == "NOTREAL")
    assert bad["current_price"] is None and bad["market_value"] is None
    assert data["totals"]["unpriced"] == ["NOTREAL"]
    assert data["totals"]["total_value"] == 2400.0  # only the priced holding counts
    assert any(e["ticker"] == "NOTREAL" for e in data["errors"])


def test_listing_preference_prefers_nse_then_us(user_a):
    assert market_data.resolve_symbol("INFY") == "INFY.NS"
    assert market_data.resolve_symbol("AAPL") == "AAPL"


def test_provider_outage_returns_503_with_message(user_a, monkeypatch):
    def down(symbol):
        raise ProviderError("yahoo", "unavailable", "Yahoo Finance request failed (ConnectError).")
    monkeypatch.setattr(market_data, "_yahoo_quote", down)
    r = user_a.get("/api/market/quote/ZZZ")
    assert r.status_code == 503 and "Yahoo" in r.json()["detail"]


def test_finnhub_without_key_reports_configuration_error(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "")
    from app.core import config
    config.get_settings.cache_clear()
    try:
        with pytest.raises(ProviderError) as exc:
            market_data._finnhub_quote("AAPL")
        assert exc.value.kind == "not_configured" and "MARKET_DATA_API_KEY" in exc.value.message
    finally:
        config.get_settings.cache_clear()


def test_ai_not_configured_is_explicit(user_a):
    import_sample(user_a)
    ins = user_a.get("/api/portfolio/health").json()["insights"]
    assert ins["source"] == "rules" and "AI_API_KEY" in ins["notice"]
    analysis = user_a.get("/api/insights/TCS?ai=true").json()
    assert analysis["ai"]["configured"] is False and analysis["ai"]["interpretation"] is None
    assert "AI_API_KEY" in analysis["ai"]["error"]


def _news(n, label):
    now = datetime.now(timezone.utc)
    return {"provider": "test", "fetched_at": now, "articles": [
        {"title": f"t{i}", "source": "s", "url": f"https://e.com/{i}", "published_at": now - timedelta(days=1),
         "summary": None, "sentiment": {"label": label, "score": 1.0, "method": "keyword heuristic"}}
        for i in range(n)]}


def _inputs(symbol="TCS.NS"):
    q = fake_quote(symbol)
    q.update({"fetched_at": datetime.now(timezone.utc), "stale": False})
    p = fake_profile(symbol)
    p["fetched_at"] = datetime.now(timezone.utc)
    return q, p, {"points": fake_history(symbol, "1y"), "provider": "yahoo"}


def test_signal_insufficient_without_history():
    q, p, _ = _inputs()
    res = signals.build_signal(quote=q, profile=p, history=None, news=None, position=None)
    assert res["signal_code"] == "insufficient" and res["evidence_quality"]["level"] == "Insufficient"
    res = signals.build_signal(quote=None, profile=None, history=None, news=None, position=None)
    assert res["signal"] == "Insufficient Data"


def test_signal_buy_with_strong_consistent_evidence():
    q, p, h = _inputs()
    res = signals.build_signal(quote=q, profile=p, history=h, news=_news(5, "positive"), position=None)
    assert res["evidence_quality"]["level"] == "High"
    assert res["signal_code"] == "buy", res["factors"]
    assert res["positives"] and res["sources"] and res["disclaimer"]
    assert all(f["available"] for f in res["factors"])


def test_concentration_pushes_toward_reduce():
    q, p, h = _inputs()
    h["points"] = list(reversed(h["points"]))  # downtrend
    res = signals.build_signal(quote={**q, "price": h["points"][-1]["close"]}, profile=p, history=h,
                               news=_news(5, "negative"), position={"weight_pct": 35.0, "quantity": 1})
    assert res["signal_code"] == "reduce"
    assert any("35%" in r for r in res["risks"])


def test_missing_news_marks_factor_unavailable_and_lowers_quality():
    q, p, h = _inputs()
    res = signals.build_signal(quote=q, profile=p, history=h, news={"articles": []}, position=None)
    news_factor = next(f for f in res["factors"] if f["name"] == "News sentiment")
    assert news_factor["available"] is False and res["evidence_quality"]["level"] == "Medium"
    assert any("Not evaluated" in r for r in res["risks"])


def test_insights_endpoint_uses_own_position(user_a, user_b):
    import_sample(user_a)
    a = user_a.get("/api/insights/TCS").json()
    b = user_b.get("/api/insights/TCS").json()
    assert a["position"] is not None and a["position"]["quantity"] == 5
    assert b["position"] is None


def test_news_endpoint_returns_provider_articles(user_a):
    r = user_a.get("/api/news", params={"symbol": "TCS"}).json()
    assert r["articles"] and all(a["url"].startswith("https://") for a in r["articles"])
    assert r["articles"][0]["sentiment"]["method"] == "keyword heuristic"
    assert r["fetched_at"]


def test_watchlist_alerts(user_a):
    user_a.post("/api/watchlist", json={"symbol": "TCS", "alert_above": 2000}, headers=csrf(user_a))
    item = user_a.get("/api/watchlist").json()["items"][0]
    assert item["symbol"] == "TCS.NS" and item["alerts_triggered"] == ["above"]
    bad = user_a.post("/api/watchlist", json={"symbol": "INFY", "alert_above": 10, "alert_below": 20},
                      headers=csrf(user_a))
    assert bad.status_code == 422
