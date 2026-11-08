from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.ratelimit import enforce
from app.db.models import AuthSession, RefreshToken, User
from app.db.session import get_db
from app.deps import get_current_user
from app.models.schemas import LoginRequest, RegisterRequest, UserOut
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVALID_LOGIN = "Invalid email or password."


@router.get("/csrf")
def csrf(request: Request, response: Response):
    """Issue (or re-use) the CSRF cookie. The SPA sends it back in the X-CSRF-Token header."""
    token = request.cookies.get(security.CSRF_COOKIE) or security.new_csrf_token()
    auth_service.set_csrf_cookie(response, token)
    return {"csrf_token": token}


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    enforce(request, "register", get_settings().register_rate_limit)
    email = body.email.lower()
    problems = security.password_problems(body.password, email)
    if problems:
        raise HTTPException(status_code=422, detail="Password must contain " + ", ".join(problems) + ".")
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists. Try signing in.")
    user = User(email=email, password_hash=security.hash_password(body.password),
                display_name=body.display_name or email.split("@")[0])
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists. Try signing in.")
    access, refresh = auth_service.start_session(db, user, request.headers.get("user-agent", ""))
    user.last_login_at = security.utcnow()
    auth_service.log_activity(db, user.id, "account", "Account created.", True)
    db.commit()
    auth_service.set_auth_cookies(response, access, refresh)
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    s = get_settings()
    enforce(request, "login", s.login_rate_limit)
    # Second bucket keyed on the email alone slows distributed guessing against one account.
    enforce(request, "login-email", "10/900", extra_key=email, include_ip=False)
    user = db.scalar(select(User).where(User.email == email))
    # verify_password always runs a full Argon2 verification, even for unknown emails.
    if not security.verify_password(body.password, user.password_hash if user else None) or user is None:
        raise HTTPException(status_code=401, detail=INVALID_LOGIN)
    if security.password_needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(body.password)
    access, refresh = auth_service.start_session(db, user, request.headers.get("user-agent", ""))
    user.last_login_at = security.utcnow()
    auth_service.log_activity(db, user.id, "security", "Signed in.", True)
    db.commit()
    auth_service.set_auth_cookies(response, access, refresh)
    return user


@router.post("/refresh", response_model=UserOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    enforce(request, "refresh", get_settings().refresh_rate_limit)
    raw = request.cookies.get(security.REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    try:
        user, access, new_refresh = auth_service.rotate(db, raw)
    except auth_service.RefreshError:
        db.rollback()
        # Return the error *with* cleared cookies.
        resp = Response(status_code=401, content='{"detail":"Session expired. Please sign in again."}',
                        media_type="application/json")
        auth_service.clear_auth_cookies(resp)
        return resp
    db.commit()
    auth_service.set_auth_cookies(response, access, new_refresh)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: Session = Depends(get_db)):
    """Revoke the current session (works with an expired access token, via the refresh cookie)."""
    session_id = None
    token = request.cookies.get(security.ACCESS_COOKIE)
    if token:
        try:
            session_id = security.decode_access_token(token)["sid"]
        except security.TokenError:
            session_id = None
    if session_id is None and request.cookies.get(security.REFRESH_COOKIE):
        rt = db.scalar(select(RefreshToken).where(
            RefreshToken.token_hash == security.hash_token(request.cookies[security.REFRESH_COOKIE])))
        session_id = rt.session_id if rt else None
    if session_id:
        session = db.get(AuthSession, session_id)
        if session:
            auth_service.revoke_session(db, session, "logout")
            auth_service.log_activity(db, session.user_id, "security", "Signed out.", True)
            db.commit()
    resp = Response(status_code=204)
    auth_service.clear_auth_cookies(resp)
    return resp


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
