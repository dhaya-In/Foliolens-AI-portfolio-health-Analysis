"""Pydantic request/response schemas and the in-memory Holding view used by the metrics engine."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-&_^=]{0,24}$")


def normalize_ticker(value: str) -> str:
    v = str(value).strip().upper()
    if not TICKER_RE.fullmatch(v):
        raise ValueError("Ticker may contain only letters, digits and . - & _ ^ = (max 25 chars).")
    return v


# ------------------------------------------------------------------ analytics view

class Holding(BaseModel):
    """A priced holding. current_price is None when no live price could be obtained -
    we never substitute the purchase price as if it were a market price."""
    id: Optional[int] = None
    ticker: str
    symbol: Optional[str] = None
    company_name: Optional[str] = None
    quantity: float
    avg_buy_price: float
    current_price: Optional[float] = None
    previous_close: Optional[float] = None
    currency: Optional[str] = None
    sector: Optional[str] = None
    beta: Optional[float] = None
    price_time: Optional[datetime] = None
    stale: bool = False

    @property
    def priced(self) -> bool:
        return self.current_price is not None

    @property
    def current_value(self) -> float:
        return self.quantity * self.current_price if self.current_price is not None else 0.0

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_buy_price

    @property
    def gain_loss(self) -> float | None:
        return self.current_value - self.cost_basis if self.priced else None

    @property
    def gain_loss_pct(self) -> float | None:
        if not self.priced or self.cost_basis == 0:
            return None
        return (self.current_value - self.cost_basis) / self.cost_basis * 100

    @property
    def day_change(self) -> float | None:
        if self.current_price is None or self.previous_close is None:
            return None
        return (self.current_price - self.previous_close) * self.quantity


class ColumnMapping(BaseModel):
    ticker: Optional[str] = None
    quantity: Optional[str] = None
    avg_price: Optional[str] = None
    confidence: str = "manual"
    raw_columns: list[str] = []


class PortfolioMetrics(BaseModel):
    diversification_score: float
    concentration_top_holding_pct: float
    concentration_top_sector_pct: float
    top_holding_ticker: str
    top_sector: str
    portfolio_beta: Optional[float]
    beta_coverage_pct: float
    health_score: float
    total_value: float
    total_gain_loss_pct: float


class AIInsight(BaseModel):
    insight_type: str
    content: str


# ------------------------------------------------------------------ auth / users

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(default="", max_length=80)

    @field_validator("display_name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        return re.sub(r"[\x00-\x1f<>]", "", v).strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    display_name: str
    created_at: datetime
    last_login_at: Optional[datetime] = None


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(max_length=80)

    @field_validator("display_name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        return re.sub(r"[\x00-\x1f<>]", "", v).strip()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class SessionOut(BaseModel):
    id: str
    user_agent: str
    created_at: datetime
    last_used_at: datetime
    current: bool


# ------------------------------------------------------------------ portfolio / imports / watchlist

class HoldingIn(BaseModel):
    ticker: str
    quantity: float = Field(gt=0, le=1e9)
    avg_buy_price: float = Field(gt=0, le=1e9)

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, v: str) -> str:
        return normalize_ticker(v)


class HoldingUpdate(BaseModel):
    quantity: float = Field(gt=0, le=1e9)
    avg_buy_price: float = Field(gt=0, le=1e9)


class ImportConfirm(BaseModel):
    upload_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    mapping: ColumnMapping
    mode: Literal["replace", "merge"] = "replace"


class WatchlistIn(BaseModel):
    symbol: str
    note: str = Field(default="", max_length=200)
    alert_above: Optional[float] = Field(default=None, gt=0, le=1e9)
    alert_below: Optional[float] = Field(default=None, gt=0, le=1e9)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, v: str) -> str:
        return normalize_ticker(v)


class WatchlistUpdate(BaseModel):
    note: str = Field(default="", max_length=200)
    alert_above: Optional[float] = Field(default=None, gt=0, le=1e9)
    alert_below: Optional[float] = Field(default=None, gt=0, le=1e9)
