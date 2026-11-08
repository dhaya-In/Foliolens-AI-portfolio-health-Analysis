"""Live integration tests against the real providers. Opt-in, because they need network access:

    FOLIOLENS_LIVE_TESTS=1 pytest tests/test_live_providers.py
"""
import os

import pytest

from app.services import ai_insights, market_data, news

pytestmark = pytest.mark.skipif(os.environ.get("FOLIOLENS_LIVE_TESTS") != "1", reason="live tests disabled")


@pytest.fixture(autouse=True)
def _real_providers(monkeypatch):
    monkeypatch.undo()  # drop the fakes installed by conftest
    market_data.clear_cache()
    news.clear_cache()


def test_yahoo_quote_profile_history():
    q = market_data.get_quote("RELIANCE.NS")
    assert q["price"] > 0 and q["currency"] == "INR" and q["market_time"] is not None
    h = market_data.get_history("RELIANCE.NS", "1y")
    assert len(h["points"]) > 200
    p = market_data.get_profile("RELIANCE.NS")
    assert p["name"] and p["sector"]


def test_symbol_resolution_and_search():
    assert market_data.resolve_symbol("TCS") == "TCS.NS"
    assert market_data.resolve_symbol("DEFINITELYNOTATICKER") is None
    assert any(r["symbol"] == "INFY.NS" for r in market_data.search("infosys"))


def test_yahoo_news():
    res = news.get_news(symbol="TCS.NS", query="Tata Consultancy Services", limit=10)
    assert res["articles"], "no articles returned"
    a = res["articles"][0]
    assert a["title"] and a["url"].startswith("http") and a["source"] and a["published_at"]


@pytest.mark.skipif(not os.environ.get("AI_API_KEY"), reason="AI_API_KEY not set")
def test_anthropic_interpretation():
    from tests.test_market_and_signals import _inputs
    from app.services import signals
    q, p, h = _inputs()
    sig = signals.build_signal(quote=q, profile=p, history=h, news={"articles": []}, position=None)
    out = ai_insights.interpret_signal(sig)
    assert out["summary"]
