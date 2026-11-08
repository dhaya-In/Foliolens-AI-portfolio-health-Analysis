"""Password hashing (Argon2id), JWT access tokens, opaque refresh tokens and CSRF tokens."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

# argon2-cffi defaults to Argon2id with RFC 9106 "low memory" parameters.
_hasher = PasswordHasher()
# Used to spend the same time on logins for unknown emails (reduces account enumeration).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

JWT_ALGORITHM = "HS256"

ACCESS_COOKIE = "fl_access"
REFRESH_COOKIE = "fl_refresh"
CSRF_COOKIE = "fl_csrf"
CSRF_HEADER = "X-CSRF-Token"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on round-trip; treat stored naive datetimes as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problems(password: str, email: str | None = None) -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if len(password) > 128:
        problems.append("at most 128 characters")
    if not re.search(r"[a-z]", password):
        problems.append("a lowercase letter")
    if not re.search(r"[A-Z]", password):
        problems.append("an uppercase letter")
    if not re.search(r"\d", password):
        problems.append("a digit")
    if email:
        local = email.split("@")[0].lower()
        if len(local) >= 4 and local in password.lower():
            problems.append("no part of your email address")
    return problems


# ---------------------------------------------------------------- JWT access tokens

class TokenError(Exception):
    pass


def create_access_token(user_id: int, session_id: str, now: datetime | None = None,
                        lifetime: timedelta | None = None) -> str:
    s = get_settings()
    now = now or utcnow()
    exp = now + (lifetime or timedelta(minutes=s.access_token_minutes))
    payload = {
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "sub": str(user_id),
        "sid": session_id,
        "typ": "access",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    s = get_settings()
    try:
        claims = jwt.decode(
            token,
            s.jwt_secret_key,
            algorithms=[JWT_ALGORITHM],  # pinned: rejects alg=none and algorithm confusion
            audience=s.jwt_audience,
            issuer=s.jwt_issuer,
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "sid", "jti"]},
            leeway=5,
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("invalid") from exc
    if claims.get("typ") != "access" or not str(claims.get("sub", "")).isdigit():
        raise TokenError("invalid")
    return claims


# ---------------------------------------------------------------- refresh + CSRF tokens

def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Refresh tokens are stored only as SHA-256 hashes (they are high-entropy, so no salt needed)."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)
