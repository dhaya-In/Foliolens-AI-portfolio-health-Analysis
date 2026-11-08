"""User A must never be able to read, change or analyse user B's data (and vice versa)."""
from tests.conftest import csrf, import_sample, upload


def test_portfolios_are_private(user_a, user_b):
    import_sample(user_a)
    assert len(user_a.get("/api/portfolio/holdings").json()["holdings"]) == 3
    assert user_b.get("/api/portfolio/holdings").json()["holdings"] == []
    assert user_b.get("/api/portfolio/overview").json()["totals"]["holdings_count"] == 0
    assert user_b.get("/api/portfolio/health").json()["empty"] is True


def test_cannot_modify_other_users_holding_by_id(user_a, user_b):
    import_sample(user_a)
    hid = user_a.get("/api/portfolio/holdings").json()["holdings"][0]["id"]
    assert user_b.put(f"/api/portfolio/holdings/{hid}", json={"quantity": 1, "avg_buy_price": 1},
                      headers=csrf(user_b)).status_code == 404
    assert user_b.delete(f"/api/portfolio/holdings/{hid}", headers=csrf(user_b)).status_code == 404
    assert len(user_a.get("/api/portfolio/holdings").json()["holdings"]) == 3


def test_cannot_use_other_users_upload(user_a, user_b):
    body = upload(user_a).json()
    payload = {"upload_id": body["upload_id"], "mapping": body["mapping"], "mode": "replace"}
    assert user_b.post("/api/imports/confirm", json=payload, headers=csrf(user_b)).status_code == 404
    assert user_b.post("/api/imports/validate", json=payload, headers=csrf(user_b)).status_code == 404
    assert user_b.delete(f"/api/imports/{body['upload_id']}", headers=csrf(user_b)).status_code == 404
    # A's upload is untouched and still confirmable by A.
    assert user_a.post("/api/imports/confirm", json=payload, headers=csrf(user_a)).status_code == 200


def test_ciphertext_bound_to_owner():
    """Even if a row's owner were changed in the DB, decryption fails for the other user."""
    from app.core import crypto
    blob = crypto.encrypt(b"data", crypto.associated_data(1, "u" * 32))
    try:
        crypto.decrypt(blob, crypto.associated_data(2, "u" * 32))
    except crypto.DecryptionError:
        pass
    else:
        raise AssertionError("decrypted with another user's binding")


def test_uploads_do_not_overwrite_other_users(user_a, user_b):
    import_sample(user_a)
    import_sample(user_b, b"Symbol,Qty,Avg Price\nAAPL,1,100\n")
    assert {h["ticker"] for h in user_a.get("/api/portfolio/holdings").json()["holdings"]} == {"RELIANCE", "TCS", "INFY"}
    assert {h["ticker"] for h in user_b.get("/api/portfolio/holdings").json()["holdings"]} == {"AAPL"}


def test_exports_and_reports_are_scoped(user_a, user_b):
    import_sample(user_a)
    for path in ("/api/imports/export/holdings.csv", "/api/reports/pnl.csv", "/api/reports/allocation.csv"):
        text = user_b.get(path).content.decode("utf-8-sig")
        assert "RELIANCE" not in text, path


def test_watchlist_is_private(user_a, user_b):
    r = user_a.post("/api/watchlist", json={"symbol": "TCS", "alert_above": 3000}, headers=csrf(user_a))
    assert r.status_code == 201
    wid = r.json()["id"]
    assert user_b.get("/api/watchlist").json()["items"] == []
    assert user_b.delete(f"/api/watchlist/{wid}", headers=csrf(user_b)).status_code == 404
    assert user_b.put(f"/api/watchlist/{wid}", json={"note": "x"}, headers=csrf(user_b)).status_code == 404
    assert len(user_a.get("/api/watchlist").json()["items"]) == 1


def test_activity_and_sessions_are_private(user_a, user_b):
    import_sample(user_a)
    assert all("Imported" not in a["message"] for a in user_b.get("/api/users/me/activity").json())
    assert len(user_b.get("/api/users/me/sessions").json()) == 1


def test_account_deletion_removes_only_own_data(user_a, user_b):
    import_sample(user_a)
    import_sample(user_b)
    r = user_a.request("DELETE", "/api/users/me", json={"password": "CorrectHorse9Battery"}, headers=csrf(user_a))
    assert r.status_code == 204
    assert user_a.get("/api/auth/me").status_code == 401
    assert len(user_b.get("/api/portfolio/holdings").json()["holdings"]) == 3
