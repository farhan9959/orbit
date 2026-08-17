"""Authentication, sessions, CSRF and rate limiting (threat model T3, T6, T1).

Assumptions and failure modes:
* Argon2id via argon2-cffi. Verification is constant-time and the failure message is
  deliberately generic, so the login endpoint is not a user-enumeration oracle.
* Sessions are server-side records, so logout genuinely revokes rather than relying on the
  client discarding a token. Session ids rotate on login (session fixation).
* CSRF uses double-submit: the token lives in the session record and must be echoed in a
  header on every non-GET. `SameSite=Lax` alone is not relied upon, because its behaviour
  varies by browser and request type.
* Rate limits are a fixed-window counter in Postgres rather than a new Redis container, for
  a deployment that is one node.
"""

from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_session
from api.models import RateLimit, SessionRecord, User

SESSION_COOKIE = "orbit_session"
CSRF_HEADER = "X-CSRF-Token"
MIN_PASSWORD_LENGTH = 12

COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1234",
        "123456789012",
        "qwertyuiop12",
        "letmeinplease",
        "administrator",
        "orbitorbitorbit",
    }
)

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, Exception):
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    if password.lower() in COMMON_PASSWORDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="password is too common")


def new_session(session: Session, user: User) -> SessionRecord:
    record = SessionRecord(
        id=secrets.token_urlsafe(32),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
    )
    session.add(record)
    session.flush()
    return record


def revoke_sessions(session: Session, user_id: uuid.UUID) -> None:
    for record in session.execute(
        select(SessionRecord).where(SessionRecord.user_id == user_id)
    ).scalars():
        session.delete(record)


def _expired(record: SessionRecord) -> bool:
    settings = get_settings()
    now = datetime.now(UTC)
    created = record.created_at
    seen = record.last_seen_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    if now - created > timedelta(seconds=settings.session_absolute_seconds):
        return True
    return now - seen > timedelta(seconds=settings.session_idle_seconds)


def current_session(request: Request, session: Session = Depends(get_session)) -> SessionRecord:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    record = session.get(SessionRecord, token)
    if record is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    if _expired(record):
        session.delete(record)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="session expired")
    record.last_seen_at = datetime.now(UTC)
    return record


def current_user(
    request: Request,
    record: SessionRecord = Depends(current_session),
    session: Session = Depends(get_session),
) -> User:
    user = session.get(User, record.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        supplied = request.headers.get(CSRF_HEADER, "")
        if not supplied or not hmac.compare_digest(supplied, record.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="invalid CSRF token")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "ADMIN":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin only")
    return user


def enforce_rate_limit(session: Session, key: str, limit: int, window_seconds: int) -> None:
    now = datetime.now(UTC)
    record = session.get(RateLimit, key)
    if record is None:
        session.add(RateLimit(key=key, window_start=now, count=1))
        session.flush()
        return
    start = record.window_start
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if now - start > timedelta(seconds=window_seconds):
        record.window_start = now
        record.count = 1
        session.flush()
        return
    record.count += 1
    session.flush()
    if record.count > limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={"Retry-After": str(window_seconds)},
        )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
