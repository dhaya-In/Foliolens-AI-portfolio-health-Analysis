"""Request dependencies: database session and the authenticated user."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core import security
from app.core.ratelimit import enforce
from app.core.config import get_settings
from app.db.models import AuthSession, User
from app.db.session import get_db

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(security.ACCESS_COOKIE)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise UNAUTHORIZED
    try:
        claims = security.decode_access_token(token)
    except security.TokenError as exc:
        detail = "Session expired." if str(exc) == "expired" else "Invalid session."
        raise HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"}) from exc

    session = db.get(AuthSession, claims["sid"])
    if (
        session is None
        or session.revoked_at is not None
        or security.as_utc(session.expires_at) <= security.utcnow()
        or session.user_id != int(claims["sub"])
    ):
        raise HTTPException(status_code=401, detail="Session has been signed out.")
    user = db.get(User, int(claims["sub"]))
    if user is None:
        raise UNAUTHORIZED
    request.state.user_id = user.id
    request.state.session_id = session.id
    # General per-user API limit (protects the market-data providers' quotas too).
    enforce(request, "api", get_settings().api_rate_limit, extra_key=str(user.id))
    return user
