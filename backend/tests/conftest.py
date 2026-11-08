"""Test configuration. External providers are replaced with deterministic fakes here (tests only);
the live integrations are exercised separately by tests/test_live_providers.py."""
import base64
import os
import tempfile
from datetime import date, datetime, timedelta, timezone

_tmp = tempfile.mkdtemp(prefix="foliolens-test-")
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{os.path.join(_tmp, 'test.db')}",
    "JWT_SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
    "CSV_ENCRYPTION_KEY": base64.b64encode(b"k" * 32).decode(),
    "AI_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "MARKET_DATA_PROVIDER": "yahoo",
    "FINANCIAL_NEWS_PROVIDER": "yahoo",
    "LOGIN_RATE_LIMIT": "5/60",
    "API_RATE_LIMIT": "1000/60",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.ratelimit import limiter  # noqa: E402
from app.db.session import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import market_data, news  # noqa: E402
from app.services.http_client import ProviderError  # noqa: E402

PRICES = {"RELIANCE.NS": 1200.0, "TCS.NS": 2400.0, "INFY.NS": 1100.0, "AAPL": 230.0}
SECTORS = {"RELIANCE.NS": "Energy", "TCS.NS": "Technology", "INFY.NS": "Technology", "AAPL": "Technology"}


def fake_quote(symbol):
    if symbol not in PRICES:
        raise ProviderError("yahoo", "not_found", f"No price data for {symbol}.")
    p = PRICES[symbol]
    return {"symbol": symbol, "name": symbol.split(".")[0] + " Ltd", "price": p, "previous_close": p * 0.99,
            "change": p * 0.01, "change_pct": 1.01, "currency": "USD" if symbol == "AAPL" else "INR",
            "exchange": "NSE", "fifty_two_week_high": p * 1.2, "fifty_two_week_low": p * 0.8,
            "market_time": datetime.now(timezone.utc), "provider": "yahoo"}


def fake_profile(symbol):
    return {"symbol": symbol, "name": symbol.split(".")[0] + " Ltd", "sector": SECTORS.get(symbol, "Unknown"),
            "industry": None, "beta": 1.1, "currency": "INR", "country": "India", "website": None, "summary": None,
            "fundamentals": {"trailingPE": 25.0, "profitMargins": 0.2, "revenueGrowth": 0.12, "debtToEquity": 40.0},
            "provider": "yahoo"}


def fake_history(symbol, period):
    base = PRICES.get(symbol)
    if base is None:
        raise ProviderError("yahoo", "not_found", "no history")
    start = date(2025, 10, 1)
    # steady uptrend, ending at the current price
    return [{"date": (start + timedelta(days=i)).isoformat(), "close": round(base * (0.7 + 0.3 * i / 259), 4)}
            for i in range(260)]


def fake_news(queries, limit):
    now = datetime.now(timezone.utc)
    return [news._article(title=f"{queries[0]} profit surges to record", source="Example Wire", author=None,
                          published_at=now - timedelta(days=1), url="https://example.com/a1", summary=None,
                          tickers=[queries[0]], provider="yahoo"),
            news._article(title=f"{queries[0]} wins major contract", source="Example Wire", author=None,
                          published_at=now - timedelta(days=2), url="https://example.com/a2", summary=None,
                          tickers=[queries[0]], provider="yahoo"),
            news._article(title=f"{queries[0]} shares rise after strong growth", source="Example Wire", author=None,
                          published_at=now - timedelta(days=3), url="https://example.com/a3", summary=None,
                          tickers=[queries[0]], provider="yahoo")]


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    limiter.reset()
    market_data.clear_cache()
    news.clear_cache()
    monkeypatch.setattr(market_data, "_yahoo_quote", fake_quote)
    monkeypatch.setattr(market_data, "_yahoo_profile", fake_profile)
    monkeypatch.setattr(market_data, "_yahoo_history", fake_history)
    monkeypatch.setattr(market_data, "_yahoo_search", lambda q: [{"symbol": "TCS.NS", "name": "TCS Ltd", "exchange": "NSE", "type": "EQUITY"}])
    monkeypatch.setattr(news, "_yahoo_news", fake_news)
    yield


def make_client() -> TestClient:
    c = TestClient(app, base_url="http://testserver")
    c.get("/api/auth/csrf")
    return c


def csrf(c: TestClient) -> dict:
    return {"X-CSRF-Token": c.cookies.get("fl_csrf")}


PASSWORD = "CorrectHorse9Battery"


def register(c: TestClient, email: str, password: str = PASSWORD):
    return c.post("/api/auth/register", json={"email": email, "password": password}, headers=csrf(c))


@pytest.fixture
def client():
    return make_client()


@pytest.fixture
def user_a():
    c = make_client()
    assert register(c, "alice@example.com").status_code == 201
    return c


@pytest.fixture
def user_b():
    c = make_client()
    assert register(c, "bob@example.com").status_code == 201
    return c


SAMPLE_CSV = b"""Holdings as of 19-Jun-2026
Symbol,Net Qty,Avg. Cost Price,LTP
RELIANCE,10,1000.00,1200
TCS,5,2000.00,2400
INFY,8,1000.00,1100
Total,,,
"""


def upload(c: TestClient, data: bytes = SAMPLE_CSV, name: str = "portfolio.csv", ctype: str = "text/csv"):
    return c.post("/api/imports/upload", files={"file": (name, data, ctype)}, headers=csrf(c))


def import_sample(c: TestClient, data: bytes = SAMPLE_CSV):
    up = upload(c, data)
    assert up.status_code == 201, up.text
    body = up.json()
    r = c.post("/api/imports/confirm", json={"upload_id": body["upload_id"], "mapping": body["mapping"],
                                             "mode": "replace"}, headers=csrf(c))
    assert r.status_code == 200, r.text
    return r.json()
