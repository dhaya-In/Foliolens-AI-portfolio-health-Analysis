"""CSV import (upload -> validate/preview -> confirm) and secure export.

Uploaded bytes are validated, then stored only as AES-256-GCM ciphertext bound to (user_id, upload_id),
kept for CSV_UPLOAD_TTL_MINUTES at most, and deleted once the import is confirmed or cancelled.
"""
from __future__ import annotations

import csv
import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import get_settings
from app.core.security import as_utc, utcnow
from app.db.models import CsvUpload, Holding as HoldingRow, User
from app.db.session import get_db
from app.deps import get_current_user
from app.models.schemas import ColumnMapping, ImportConfirm
from app.services import csv_parser, market_data
from app.services.auth_service import log_activity
from app.services.http_client import ProviderError
from app.services.portfolio_service import holding_to_dict, price_portfolio

router = APIRouter(prefix="/api/imports", tags=["csv import/export"])

NO_STORE = {"Cache-Control": "no-store, private", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}


def purge_expired_uploads(db: Session) -> int:
    res = db.execute(delete(CsvUpload).where(CsvUpload.expires_at < utcnow()))
    db.commit()
    return res.rowcount or 0


def _load_upload(db: Session, user: User, upload_id: str) -> tuple[CsvUpload, str]:
    up = db.scalar(select(CsvUpload).where(CsvUpload.id == upload_id, CsvUpload.user_id == user.id))
    if up is None or as_utc(up.expires_at) < utcnow():
        raise HTTPException(status_code=404, detail="Upload not found or expired. Please upload the file again.")
    try:
        text = crypto.decrypt(up.ciphertext, crypto.associated_data(user.id, up.id)).decode("utf-8")
    except (crypto.DecryptionError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="Stored upload failed its integrity check. Please upload again.")
    return up, text


def _validation(df, mapping: ColumnMapping) -> dict:
    if not (mapping.ticker and mapping.quantity and mapping.avg_price):
        return {"ready": False, "valid_count": 0, "error_count": 0, "errors": [], "warnings": [],
                "valid_preview": [], "message": "Choose the ticker, quantity and average price columns."}
    try:
        rows, errors, warnings = csv_parser.build_holdings(df, mapping)
    except csv_parser.CsvValidationError as exc:
        return {"ready": False, "valid_count": 0, "error_count": 0, "errors": [], "warnings": [],
                "valid_preview": [], "message": str(exc)}
    return {"ready": len(rows) > 0, "valid_count": len(rows), "error_count": len(errors),
            "errors": errors[:100], "warnings": warnings, "valid_preview": rows[:20],
            "message": None if rows else "No valid holding rows were found."}


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_csv(request: Request, file: UploadFile = File(...), user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    s = get_settings()
    purge_expired_uploads(db)
    # Read at most max+1 bytes so an oversized upload can't exhaust memory.
    data = await file.read(s.csv_max_bytes + 1)
    try:
        text = csv_parser.validate_upload(file.filename, file.content_type, data)
        df = csv_parser.parse_csv_text(text)
    except csv_parser.CsvValidationError as exc:
        raise HTTPException(status_code=422 if len(data) <= s.csv_max_bytes else 413, detail=str(exc))

    mapping = csv_parser.detect_columns(list(df.columns))
    # Replace any previous pending upload of this user - only one staged import at a time.
    db.execute(delete(CsvUpload).where(CsvUpload.user_id == user.id))
    up = CsvUpload(user_id=user.id, original_filename=csv_parser.safe_filename(file.filename),
                   size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), ciphertext=b"",
                   expires_at=utcnow() + timedelta(minutes=s.csv_upload_ttl_minutes))
    db.add(up)
    db.flush()
    up.ciphertext = crypto.encrypt(text.encode("utf-8"), crypto.associated_data(user.id, up.id))
    db.commit()
    return {
        "upload_id": up.id,
        "filename": up.original_filename,
        "size_bytes": up.size_bytes,
        "expires_at": up.expires_at,
        "row_count": len(df),
        "mapping": mapping.model_dump(),
        "columns": [str(c) for c in df.columns],
        "preview_rows": csv_parser.preview_rows(df),
        "validation": _validation(df, mapping),
    }


@router.post("/validate")
def validate_mapping(body: ImportConfirm, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, text = _load_upload(db, user, body.upload_id)
    df = csv_parser.parse_csv_text(text)
    return _validation(df, body.mapping)


@router.post("/confirm")
def confirm_import(body: ImportConfirm, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    up, text = _load_upload(db, user, body.upload_id)
    df = csv_parser.parse_csv_text(text)
    try:
        rows, errors, warnings = csv_parser.build_holdings(df, body.mapping)
    except csv_parser.CsvValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not rows:
        raise HTTPException(status_code=422, detail="No valid holding rows to import.")

    def resolve(r):
        try:
            return r["ticker"], market_data.resolve_symbol(r["ticker"])
        except ProviderError:
            return r["ticker"], None

    with ThreadPoolExecutor(max_workers=min(8, len(rows))) as pool:
        symbols = dict(pool.map(resolve, rows))

    # One transaction: either every change (and the upload deletion) is committed, or none is.
    try:
        existing = {h.ticker: h for h in db.scalars(select(HoldingRow).where(HoldingRow.user_id == user.id))}
        if body.mode == "replace":
            for h in existing.values():
                db.delete(h)
            db.flush()
            existing = {}
        added = updated = 0
        for r in rows:
            if r["ticker"] in existing:
                h = existing[r["ticker"]]
                h.quantity, h.avg_buy_price = r["quantity"], r["avg_buy_price"]
                h.symbol = symbols.get(r["ticker"]) or h.symbol
                updated += 1
            else:
                db.add(HoldingRow(user_id=user.id, ticker=r["ticker"], symbol=symbols.get(r["ticker"]),
                                  quantity=r["quantity"], avg_buy_price=r["avg_buy_price"]))
                added += 1
        db.delete(up)
        log_activity(db, user.id, "import",
                     f"Imported {len(rows)} holdings from CSV ({body.mode}); {len(errors)} row(s) skipped.")
        db.commit()
    except Exception:
        db.rollback()
        raise
    unresolved = [t for t, s in symbols.items() if not s]
    return {"imported": len(rows), "added": added, "updated": updated, "skipped": len(errors),
            "errors": errors[:100], "warnings": warnings, "unresolved": unresolved, "mode": body.mode}


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_upload(upload_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    res = db.execute(delete(CsvUpload).where(CsvUpload.id == upload_id, CsvUpload.user_id == user.id))
    db.commit()
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="Upload not found or expired.")


def csv_response(filename: str, header: list[str], rows: list[list]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    w.writerow([csv_parser.excel_safe(h) for h in header])
    for r in rows:
        w.writerow([csv_parser.excel_safe(v) for v in r])
    return Response(content=buf.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={**NO_STORE, "Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/holdings.csv")
def export_holdings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Re-importable export of the signed-in user's holdings, with current prices where available."""
    priced = price_portfolio(db, user.id, with_profiles=False)
    header = ["Symbol", "Quantity", "Avg Price", "Current Price", "Currency", "Market Value", "Gain/Loss",
              "Gain/Loss %", "Price Time (UTC)"]
    rows = []
    for h in priced["holdings"]:
        d = holding_to_dict(h)
        rows.append([h.ticker, h.quantity, h.avg_buy_price, h.current_price, h.currency, d["market_value"],
                     d["gain_loss"], d["gain_loss_pct"], h.price_time.isoformat() if h.price_time else ""])
    log_activity(db, user.id, "export", "Exported holdings CSV.")
    db.commit()
    return csv_response("foliolens-holdings.csv", header, rows)
