"""Registration, login, logout and identity."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.audit import record as audit
from api.config import get_settings
from api.db import get_session
from api.models import User
from api.schemas import LoginRequest, RegisterRequest, UserOut
from api.security import (
    SESSION_COOKIE,
    client_ip,
    current_session,
    current_user,
    enforce_rate_limit,
    hash_password,
    new_session,
    revoke_sessions,
    validate_password_strength,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

GENERIC_LOGIN_FAILURE = "invalid email or password"


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.session_absolute_seconds,
        path="/",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
def register(
    payload: RegisterRequest, request: Request, session: Session = Depends(get_session)
) -> UserOut:
    enforce_rate_limit(session, f"register:{client_ip(request)}", limit=3, window_seconds=3600)
    validate_password_strength(payload.password)

    existing = (
        session.execute(select(User).where(User.email == payload.email.lower())).scalars().first()
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="email already registered")

    first_user = session.execute(select(User).limit(1)).scalars().first() is None
    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role="ADMIN" if first_user else "USER",
    )
    session.add(user)
    session.flush()
    audit(session, user.id, "auth.register", "user", user.id, request)
    return UserOut(id=user.id, email=user.email, role=user.role)


@router.post("/login", response_model=UserOut)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> UserOut:
    enforce_rate_limit(
        session, f"login:{client_ip(request)}:{payload.email.lower()}", limit=5, window_seconds=900
    )
    enforce_rate_limit(session, f"login-ip:{client_ip(request)}", limit=20, window_seconds=3600)

    user = (
        session.execute(select(User).where(User.email == payload.email.lower())).scalars().first()
    )
    if user is None or not verify_password(user.password_hash, payload.password):
        audit(session, None, "auth.login_failed", "user", None, request)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=GENERIC_LOGIN_FAILURE)

    revoke_sessions(session, user.id)
    record = new_session(session, user)
    user.last_login_at = datetime.now(UTC)
    _set_cookie(response, record.id)
    audit(session, user.id, "auth.login", "user", user.id, request)
    return UserOut(id=user.id, email=user.email, role=user.role, csrf_token=record.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> Response:
    revoke_sessions(session, user.id)
    response.delete_cookie(SESSION_COOKIE, path="/")
    audit(session, user.id, "auth.logout", "user", user.id, request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user), record=Depends(current_session)) -> UserOut:
    return UserOut(id=user.id, email=user.email, role=user.role, csrf_token=record.csrf_token)
