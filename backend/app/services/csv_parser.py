"""CSV validation, header/column auto-detection and row-level cleaning for portfolio imports."""
from __future__ import annotations

import io
import re

import pandas as pd

from app.core.config import get_settings
from app.models.schemas import TICKER_RE, ColumnMapping

COLUMN_ALIASES = {
    "ticker": ["symbol", "scrip", "ticker", "instrument", "stock symbol", "trading symbol", "tradingsymbol",
               "stock", "scrip name", "security"],
    "quantity": ["qty", "quantity", "shares", "units", "qty.", "net qty", "holding quantity", "quantity available"],
    "avg_price": ["avg cost", "avg_price", "avg. cost price", "buy price", "average price", "avg cost price",
                  "purchase price", "buy avg", "average cost", "avg price", "avg. price", "average buy price"],
}

ALLOWED_CONTENT_TYPES = {
    "text/csv", "application/csv", "text/plain", "application/vnd.ms-excel",
    "text/comma-separated-values", "application/octet-stream", "",
}
MAX_COLUMNS = 60
MAX_CELL_CHARS = 200
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]")


class CsvValidationError(ValueError):
    pass


def safe_filename(name: str | None) -> str:
    """Strip any path components and unusual characters; we never use this as a filesystem path."""
    base = re.split(r"[\\/]", name or "upload.csv")[-1]
    base = SAFE_FILENAME.sub("_", base).strip(" .") or "upload.csv"
    return base[:120]


def validate_upload(filename: str | None, content_type: str | None, data: bytes) -> str:
    """Validate the raw upload and return the decoded text."""
    s = get_settings()
    if not filename or not filename.lower().endswith(".csv"):
        raise CsvValidationError("Only .csv files are accepted.")
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype not in ALLOWED_CONTENT_TYPES:
        raise CsvValidationError(f"Unexpected file type '{ctype}'. Please upload a plain CSV file.")
    if len(data) == 0:
        raise CsvValidationError("The file is empty.")
    if len(data) > s.csv_max_bytes:
        raise CsvValidationError(f"File is too large. Maximum size is {s.csv_max_bytes // 1024} KB.")
    if b"\x00" in data:
        raise CsvValidationError("The file contains binary data and is not a valid CSV.")
    if data[:4] in (b"PK\x03\x04", b"\xd0\xcf\x11\xe0") or data[:5] == b"%PDF-":
        raise CsvValidationError("This looks like an Excel/ZIP/PDF file. Export it as CSV first.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise CsvValidationError("Could not read the file encoding. Save it as UTF-8 CSV.")


def _normalize(col: str) -> str:
    return str(col).strip().lower().replace(".", "").replace("_", " ")


def detect_columns(df_columns: list[str]) -> ColumnMapping:
    normalized_map = {_normalize(c): c for c in df_columns}
    result = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if _normalize(alias) in normalized_map:
                result[field] = normalized_map[_normalize(alias)]
                break

    matched_count = sum(1 for v in result.values() if v)
    if matched_count == 3:
        confidence = "high"
    elif matched_count > 0:
        confidence = "low"
    else:
        confidence = "manual_review_needed"

    return ColumnMapping(
        ticker=result.get("ticker"),
        quantity=result.get("quantity"),
        avg_price=result.get("avg_price"),
        confidence=confidence,
        raw_columns=[str(c) for c in df_columns],
    )


def _looks_like_real_header(columns: list[str]) -> bool:
    if len(columns) <= 1:
        return False
    unnamed_ratio = sum(1 for c in columns if str(c).startswith("Unnamed")) / max(len(columns), 1)
    if unnamed_ratio >= 0.5:
        return False
    mapping = detect_columns(columns)
    matched = sum([mapping.ticker is not None, mapping.quantity is not None, mapping.avg_price is not None])
    return matched >= 1


def parse_csv_text(text: str) -> pd.DataFrame:
    """Find the header row (broker exports often have title lines on top) and parse as strings."""
    s = get_settings()
    last_df = None
    for skip in range(0, 5):
        try:
            df = pd.read_csv(io.StringIO(text), skiprows=skip, dtype=str, keep_default_na=False,
                             nrows=s.csv_max_rows + 1, engine="python", on_bad_lines="error")
        except Exception:  # noqa: BLE001 - try the next candidate header row
            continue
        last_df = df
        if _looks_like_real_header(list(df.columns)):
            break
    if last_df is None:
        raise CsvValidationError("Could not parse this CSV. Check that it is comma-separated with a header row.")
    df = last_df
    if len(df.columns) > MAX_COLUMNS:
        raise CsvValidationError(f"Too many columns ({len(df.columns)}). Maximum is {MAX_COLUMNS}.")
    if len(df) > s.csv_max_rows:
        raise CsvValidationError(f"Too many rows. Maximum is {s.csv_max_rows}.")
    if df.empty:
        raise CsvValidationError("The CSV has a header but no data rows.")
    df.columns = [str(c).strip()[:MAX_CELL_CHARS] for c in df.columns]
    return df


def parse_csv_bytes(file_bytes: bytes) -> pd.DataFrame:
    """Backwards-compatible helper (used by tests/tools)."""
    return parse_csv_text(validate_upload("upload.csv", "text/csv", file_bytes))


def _to_number(raw: str) -> float | None:
    v = str(raw).strip().replace(",", "").replace("₹", "").replace("$", "")
    if not v:
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return f if f == f and abs(f) != float("inf") else None


def build_holdings(df: pd.DataFrame, mapping: ColumnMapping) -> tuple[list[dict], list[dict], list[str]]:
    """Return (valid_rows, row_errors, warnings). Duplicate tickers are merged with a weighted average."""
    if not (mapping.ticker and mapping.quantity and mapping.avg_price):
        raise CsvValidationError("Column mapping is incomplete: choose the ticker, quantity and average price columns.")
    for col in (mapping.ticker, mapping.quantity, mapping.avg_price):
        if col not in df.columns:
            raise CsvValidationError(f"Column '{col[:60]}' is not in this file.")
    if len({mapping.ticker, mapping.quantity, mapping.avg_price}) < 3:
        raise CsvValidationError("Ticker, quantity and price must be three different columns.")

    merged: dict[str, dict] = {}
    errors: list[dict] = []
    warnings: list[str] = []
    for i, row in df.iterrows():
        line = int(i) + 2  # 1-based, plus header line
        raw_ticker = str(row[mapping.ticker]).strip()
        raw_qty, raw_price = row[mapping.quantity], row[mapping.avg_price]
        if not raw_ticker and not str(raw_qty).strip() and not str(raw_price).strip():
            continue
        if raw_ticker.lower() in {"total", "grand total", "totals"}:
            continue
        ticker = raw_ticker.upper()
        problems = []
        if len(raw_ticker) > 25 or not TICKER_RE.fullmatch(ticker):
            problems.append("invalid ticker")
        qty, price = _to_number(raw_qty), _to_number(raw_price)
        if qty is None:
            problems.append("quantity is not a number")
        elif qty <= 0 or qty > 1e9:
            problems.append("quantity must be greater than 0")
        if price is None:
            problems.append("average price is not a number")
        elif price <= 0 or price > 1e9:
            problems.append("average price must be greater than 0")
        if problems:
            errors.append({"line": line, "ticker": raw_ticker[:25], "problems": problems})
            continue
        if ticker in merged:
            prev = merged[ticker]
            total_qty = prev["quantity"] + qty
            prev["avg_buy_price"] = (prev["avg_buy_price"] * prev["quantity"] + price * qty) / total_qty
            prev["quantity"] = total_qty
            warnings.append(f"{ticker} appears more than once; rows were combined using a weighted average price.")
        else:
            merged[ticker] = {"ticker": ticker, "quantity": qty, "avg_buy_price": price}
    return list(merged.values()), errors, sorted(set(warnings))


def preview_rows(df: pd.DataFrame, n: int = 8) -> list[dict]:
    rows = df.head(n).to_dict(orient="records")
    return [{str(k): str(v)[:MAX_CELL_CHARS] for k, v in r.items()} for r in rows]


# ------------------------------------------------------------------ exports

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "|")


def excel_safe(value) -> str:
    """Neutralise spreadsheet formula injection (CWE-1236) in exported cells."""
    if value is None:
        return ""
    s = str(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return s  # genuine numbers (incl. negatives) are safe and must stay numeric
    if s.startswith(_FORMULA_PREFIXES):
        return "'" + s
    return s
