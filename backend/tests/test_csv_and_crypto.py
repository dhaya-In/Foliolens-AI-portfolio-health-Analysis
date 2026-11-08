import csv
import io
from datetime import timedelta

import pytest

from app.core import crypto
from app.core.config import get_settings
from app.core.security import utcnow
from app.db.models import CsvUpload, Holding
from app.db.session import SessionLocal
from tests.conftest import SAMPLE_CSV, csrf, import_sample, upload


# ------------------------------------------------------------------ crypto

def test_aes_gcm_roundtrip_and_tamper_detection():
    aad = crypto.associated_data(1, "a" * 32)
    blob = crypto.encrypt(b"secret,portfolio", aad)
    assert b"secret" not in blob
    assert crypto.decrypt(blob, aad) == b"secret,portfolio"
    assert crypto.encrypt(b"same", aad) != crypto.encrypt(b"same", aad)  # random nonce
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(tampered, aad)
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(blob, crypto.associated_data(2, "a" * 32))  # another user's AAD
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(blob, aad, key=b"x" * 32)  # wrong key
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(b"junk", aad)


# ------------------------------------------------------------------ upload validation

def test_valid_upload_previews_and_stores_only_ciphertext(user_a):
    r = upload(user_a)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mapping"]["confidence"] == "high"
    assert body["validation"]["valid_count"] == 3 and body["validation"]["ready"]
    assert body["preview_rows"][0]["Symbol"] == "RELIANCE"
    with SessionLocal() as db:
        up = db.get(CsvUpload, body["upload_id"])
        assert b"RELIANCE" not in up.ciphertext
        assert up.ciphertext.startswith(b"FL1")
        assert up.expires_at is not None


@pytest.mark.parametrize("name,data,ctype,status", [
    ("portfolio.xlsx", SAMPLE_CSV, "text/csv", 422),
    ("portfolio.csv", b"", "text/csv", 422),
    ("portfolio.csv", b"PK\x03\x04binary", "text/csv", 422),
    ("portfolio.csv", b"Symbol,Qty\x00\n", "text/csv", 422),
    ("portfolio.csv", SAMPLE_CSV, "application/x-msdownload", 422),
    ("portfolio.csv", b"Symbol,Qty,Avg Price\n", "text/csv", 422),
])
def test_invalid_uploads_rejected(user_a, name, data, ctype, status):
    r = upload(user_a, data, name, ctype)
    assert r.status_code == status, r.text
    assert "Traceback" not in r.text


def test_oversized_upload_rejected(user_a):
    big = b"Symbol,Qty,Avg Price\n" + b"TCS,1,100\n" * (get_settings().csv_max_bytes // 10 + 10)
    r = upload(user_a, big)
    assert r.status_code == 413


def test_row_level_validation_errors_reported(user_a):
    data = b"Symbol,Qty,Avg Price\nTCS,5,100\n=HYPERLINK(\"x\"),1,1\nINFY,-3,100\nRELIANCE,abc,100\nTCS,5,200\n"
    body = upload(user_a, data).json()
    v = body["validation"]
    assert v["valid_count"] == 1  # TCS merged
    assert v["error_count"] == 3
    assert any("weighted average" in w for w in v["warnings"])
    problems = {e["line"]: e["problems"] for e in v["errors"]}
    assert "invalid ticker" in problems[3] and "quantity must be greater than 0" in problems[4]


def test_confirm_imports_and_deletes_staged_upload(user_a):
    res = import_sample(user_a)
    assert res["imported"] == 3
    with SessionLocal() as db:
        assert db.query(CsvUpload).count() == 0
        assert db.query(Holding).count() == 3
    h = user_a.get("/api/portfolio/holdings").json()
    assert h["totals"]["total_value"] == pytest.approx(10 * 1200 + 5 * 2400 + 8 * 1100)
    assert h["totals"]["gain_loss"] == pytest.approx(32800 - 28000)
    assert h["last_refreshed"] is not None


def test_merge_mode_keeps_existing_holdings(user_a):
    import_sample(user_a)
    body = upload(user_a, b"Symbol,Qty,Avg Price\nAAPL,2,150\n").json()
    r = user_a.post("/api/imports/confirm", json={"upload_id": body["upload_id"], "mapping": body["mapping"],
                                                  "mode": "merge"}, headers=csrf(user_a))
    assert r.status_code == 200
    assert len(user_a.get("/api/portfolio/holdings").json()["holdings"]) == 4


def test_expired_upload_cannot_be_confirmed(user_a):
    body = upload(user_a).json()
    with SessionLocal() as db:
        db.get(CsvUpload, body["upload_id"]).expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    r = user_a.post("/api/imports/confirm", json={"upload_id": body["upload_id"], "mapping": body["mapping"]},
                    headers=csrf(user_a))
    assert r.status_code == 404


def test_cancel_upload(user_a):
    body = upload(user_a).json()
    assert user_a.delete(f"/api/imports/{body['upload_id']}", headers=csrf(user_a)).status_code == 204
    assert user_a.delete(f"/api/imports/{body['upload_id']}", headers=csrf(user_a)).status_code == 404


def test_export_escapes_formula_injection(user_a):
    from app.services.csv_parser import excel_safe
    assert excel_safe("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert excel_safe("+1") == "'+1" and excel_safe("@SUM(A1)") == "'@SUM(A1)"
    assert excel_safe(-5.2) == "-5.2" and excel_safe("TCS") == "TCS"

    import_sample(user_a)
    r = user_a.get("/api/imports/export/holdings.csv")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment;")
    assert "no-store" in r.headers["cache-control"]
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][0] == "Symbol" and {row[0] for row in rows[1:]} == {"INFY", "RELIANCE", "TCS"}


def test_exported_csv_can_be_reimported(user_a):
    import_sample(user_a)
    exported = user_a.get("/api/imports/export/holdings.csv").content
    body = upload(user_a, exported, "export.csv").json()
    assert body["mapping"]["confidence"] == "high"
    assert body["validation"]["valid_count"] == 3


def test_filename_is_sanitised(user_a):
    r = upload(user_a, SAMPLE_CSV, "../../etc/evil<script>.csv")
    assert r.status_code == 201
    assert r.json()["filename"] == "evil_script_.csv"
