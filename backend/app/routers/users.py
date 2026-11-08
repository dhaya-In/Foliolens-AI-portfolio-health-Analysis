"""Profile, security settings and account management for the signed-in user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.ratelimit import enforce
from app.db.models import ActivityLog, AuthSession, User
from app.db.session import get_db
from app.deps import get_current_user
from app.models.schemas import (
    ChangePasswordRequest, DeleteAccountRequest, SessionOut, UpdateProfileRequest, UserOut,
)
from app.services import auth_service

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: UpdateProfileRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.display_name = body.display_name
    auth_service.log_activity(db, user.id, "account", "Profile updated.")
    db.commit()
    return user


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: ChangePasswordRequest, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    enforce(request, "password", get_settings().login_rate_limit, extra_key=str(user.id))
    if not security.verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    problems = security.password_problems(body.new_password, user.email)
    if problems:
        raise HTTPException(status_code=422, detail="Password must contain " + ", ".join(problems) + ".")
    user.password_hash = security.hash_password(body.new_password)
    # Sign out every other session; the current one stays signed in.
    auth_service.revoke_all_sessions(db, user.id, "password_change", except_session=request.state.session_id)
    auth_service.log_activity(db, user.id, "security", "Password changed; other sessions signed out.", True)
    db.commit()


@router.get("/me/sessions", response_model=list[SessionOut])
def list_sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None),
                                                AuthSession.expires_at > security.utcnow())
                      .order_by(AuthSession.last_used_at.desc())).all()
    return [SessionOut(id=r.id, user_agent=r.user_agent, created_at=r.created_at, last_used_at=r.last_used_at,
                       current=r.id == request.state.session_id) for r in rows]


@router.post("/me/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
def revoke_other_sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    auth_service.revoke_all_sessions(db, user.id, "user_revoked", except_session=request.state.session_id)
    auth_service.log_activity(db, user.id, "security", "Signed out of all other sessions.", True)
    db.commit()


@router.get("/me/activity")
def activity(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ActivityLog).where(ActivityLog.user_id == user.id)
                      .order_by(ActivityLog.created_at.desc()).limit(50)).all()
    return [{"kind": r.kind, "message": r.message, "created_at": r.created_at, "security": r.is_security_event}
            for r in rows]


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(body: DeleteAccountRequest, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    enforce(request, "password", get_settings().login_rate_limit, extra_key=str(user.id))
    if not security.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    db.delete(user)  # cascades to holdings, uploads, watchlist, snapshots, sessions, activity
    db.commit()
    resp = Response(status_code=204)
    auth_service.clear_auth_cookies(resp)
    return resp
