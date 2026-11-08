"""Session issuance, refresh-token rotation (with reuse detection) and revocation."""
from __future__ import annotations

from datetime import timedelta

from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.db.models import ActivityLog, AuthSession, RefreshToken, User


class RefreshError(Exception):
    pass


def log_activity(db: Session, user_id: int, kind: str, message: str, security_event: bool = False) -> None:
    db.add(ActivityLog(user_id=user_id, kind=kind, message=message[:300], is_security_event=security_event))


def _issue_refresh(db: Session, session: AuthSession) -> str:
    s = get_settings()
    raw = security.new_refresh_token()
    db.add(RefreshToken(
        session_id=session.id,
        token_hash=security.hash_token(raw),
        expires_at=security.utcnow() + timedelta(days=s.refresh_token_days),
    ))
    return raw


def start_session(db: Session, user: User, user_agent: str) -> tuple[str, str]:
    """Create a session; returns (access_token, refresh_token). Caller commits."""
    s = get_settings()
    session = AuthSession(
        user_id=user.id,
        user_agent=(user_agent or "")[:200],
        expires_at=security.utcnow() + timedelta(days=s.refresh_token_days),
    )
    db.add(session)
    db.flush()
    refresh = _issue_refresh(db, session)
    return security.create_access_token(user.id, session.id), refresh


def rotate(db: Session, raw_refresh: str) -> tuple[User, str, str]:
    """Exchange a refresh token for a new access+refresh pair. Caller commits."""
    now = security.utcnow()
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == security.hash_token(raw_refresh)))
    if token is None:
        raise RefreshError("unknown")
    session = db.get(AuthSession, token.session_id)
    if session is None or session.revoked_at is not None:
        raise RefreshError("revoked")
    if token.used_at is not None:
        # A rotated token was replayed: assume theft and kill the whole session family.
        revoke_session(db, session, "refresh_reuse")
        log_activity(db, session.user_id, "security", "A reused sign-in token was detected; that session was signed out.", True)
        db.commit()
        raise RefreshError("reused")
    if security.as_utc(token.expires_at) <= now or security.as_utc(session.expires_at) <= now:
        raise RefreshError("expired")
    token.used_at = now
    session.last_used_at = now
    user = db.get(User, session.user_id)
    if user is None:
        raise RefreshError("unknown")
    new_refresh = _issue_refresh(db, session)
    return user, security.create_access_token(user.id, session.id), new_refresh


def revoke_session(db: Session, session: AuthSession, reason: str) -> None:
    if session.revoked_at is None:
        session.revoked_at = security.utcnow()
        session.revoke_reason = reason


def revoke_all_sessions(db: Session, user_id: int, reason: str, except_session: str | None = None) -> None:
    stmt = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if except_session:
        stmt = stmt.where(AuthSession.id != except_session)
    db.execute(stmt.values(revoked_at=security.utcnow(), revoke_reason=reason))


# ------------------------------------------------------------------ cookies

def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    s = get_settings()
    common = dict(secure=s.cookie_secure, samesite=s.cookie_samesite, domain=s.cookie_domain)
    response.set_cookie(security.ACCESS_COOKIE, access, max_age=s.access_token_minutes * 60,
                        httponly=True, path="/api", **common)
    response.set_cookie(security.REFRESH_COOKIE, refresh, max_age=s.refresh_token_days * 86400,
                        httponly=True, path="/api/auth", **common)


def set_csrf_cookie(response: Response, token: str) -> None:
    s = get_settings()
    # Readable by our JS on purpose (double-submit pattern); it is not a credential on its own.
    response.set_cookie(security.CSRF_COOKIE, token, max_age=s.refresh_token_days * 86400,
                        httponly=False, path="/", secure=s.cookie_secure,
                        samesite=s.cookie_samesite, domain=s.cookie_domain)


def clear_auth_cookies(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(security.ACCESS_COOKIE, path="/api", domain=s.cookie_domain)
    response.delete_cookie(security.REFRESH_COOKIE, path="/api/auth", domain=s.cookie_domain)
