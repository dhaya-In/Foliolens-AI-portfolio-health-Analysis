from datetime import timedelta

import jwt

from app.core import security
from app.core.config import get_settings
from tests.conftest import PASSWORD, csrf, make_client, register


def login(c, email="alice@example.com", password=PASSWORD):
    return c.post("/api/auth/login", json={"email": email, "password": password}, headers=csrf(c))


def test_register_sets_httponly_cookies_and_no_token_in_body(client):
    r = register(client, "alice@example.com")
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert "password" not in str(body).lower() and "token" not in body
    set_cookie = " ".join(r.headers.get_list("set-cookie"))
    assert "fl_access=" in set_cookie and "fl_refresh=" in set_cookie
    assert set_cookie.count("HttpOnly") >= 2
    assert client.get("/api/auth/me").status_code == 200


def test_password_is_hashed_with_argon2id(client):
    register(client, "alice@example.com")
    from app.db.models import User
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        u = db.query(User).one()
        assert u.password_hash.startswith("$argon2id$")
        assert PASSWORD not in u.password_hash


def test_duplicate_email_rejected(client):
    assert register(client, "alice@example.com").status_code == 201
    c2 = make_client()
    r = register(c2, "ALICE@example.com")
    assert r.status_code == 409


def test_weak_password_and_missing_fields(client):
    r = register(client, "weak@example.com", "short")
    assert r.status_code == 422 and "Password must contain" in r.json()["detail"]
    r = client.post("/api/auth/register", json={"email": "x@example.com"}, headers=csrf(client))
    assert r.status_code == 422
    r = client.post("/api/auth/register", json={"email": "not-an-email", "password": PASSWORD}, headers=csrf(client))
    assert r.status_code == 422


def test_login_success_and_generic_failure_messages(user_a):
    c = make_client()
    assert login(c).status_code == 200
    c2 = make_client()
    wrong_pw = login(c2, password="WrongPassword1")
    unknown = login(c2, email="nobody@example.com")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["detail"] == unknown.json()["detail"]  # no account enumeration via message


def test_protected_endpoints_require_auth(client):
    for path in ("/api/auth/me", "/api/portfolio/holdings", "/api/watchlist", "/api/imports/export/holdings.csv",
                 "/api/reports/pnl.csv", "/api/insights/TCS", "/api/news", "/api/status"):
        assert client.get(path).status_code == 401, path


def test_expired_token_rejected(user_a):
    claims = security.decode_access_token(user_a.cookies.get("fl_access"))
    expired = security.create_access_token(int(claims["sub"]), claims["sid"],
                                            now=security.utcnow() - timedelta(hours=1), lifetime=timedelta(minutes=5))
    c = make_client()
    r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["detail"] == "Session expired."


def test_tampered_wrong_audience_and_alg_none_tokens_rejected(user_a):
    token = user_a.cookies.get("fl_access")
    claims = security.decode_access_token(token)
    s = get_settings()
    c = make_client()
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    wrong_aud = jwt.encode({**claims, "aud": "someone-else"}, s.jwt_secret_key, algorithm="HS256")
    wrong_key = jwt.encode(claims, "x" * 40, algorithm="HS256")
    none_alg = jwt.encode(claims, key=None, algorithm="none")
    for bad in (tampered, wrong_aud, wrong_key, none_alg, "garbage"):
        assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_logout_invalidates_existing_access_token(user_a):
    token = user_a.cookies.get("fl_access")
    assert user_a.post("/api/auth/logout", headers=csrf(user_a)).status_code == 204
    c = make_client()
    r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_refresh_rotation_and_reuse_detection(user_a):
    old_refresh = user_a.cookies.get("fl_refresh")
    r = user_a.post("/api/auth/refresh", headers=csrf(user_a))
    assert r.status_code == 200
    new_refresh = user_a.cookies.get("fl_refresh")
    assert new_refresh and new_refresh != old_refresh

    attacker = make_client()
    attacker.cookies.set("fl_refresh", old_refresh, path="/api/auth")
    assert attacker.post("/api/auth/refresh", headers=csrf(attacker)).status_code == 401
    # Reuse of a rotated token revokes the whole session, so the legitimate client is signed out too.
    assert user_a.post("/api/auth/refresh", headers=csrf(user_a)).status_code == 401
    assert user_a.get("/api/auth/me").status_code == 401


def test_csrf_required_for_cookie_authenticated_writes(user_a):
    r = user_a.post("/api/portfolio/holdings", json={"ticker": "TCS", "quantity": 1, "avg_buy_price": 10})
    assert r.status_code == 403
    r = user_a.post("/api/portfolio/holdings", json={"ticker": "TCS", "quantity": 1, "avg_buy_price": 10},
                    headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    r = user_a.post("/api/portfolio/holdings", json={"ticker": "TCS", "quantity": 1, "avg_buy_price": 10},
                    headers=csrf(user_a))
    assert r.status_code == 201


def test_login_rate_limited(user_a):
    c = make_client()
    codes = [login(c, password="WrongPassword1").status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[-1] == 429


def test_password_change_revokes_other_sessions(user_a):
    other = make_client()
    assert login(other).status_code == 200
    r = user_a.post("/api/users/me/password", json={"current_password": PASSWORD, "new_password": "NewPassw0rd!x"},
                    headers=csrf(user_a))
    assert r.status_code == 204
    assert user_a.get("/api/auth/me").status_code == 200
    assert other.get("/api/auth/me").status_code == 401


def test_security_headers_and_safe_errors(user_a):
    r = user_a.get("/api/portfolio/holdings/../../etc/passwd")
    assert r.status_code == 404
    assert "Traceback" not in r.text
    r = user_a.get("/api/auth/me")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "no-store" in r.headers["Cache-Control"]


def test_timestamps_are_timezone_aware(user_a):
    me = user_a.get("/api/auth/me").json()
    assert me["created_at"].endswith(("Z", "+00:00")), me["created_at"]
    sessions = user_a.get("/api/users/me/sessions").json()
    assert sessions[0]["last_used_at"].endswith(("Z", "+00:00"))
