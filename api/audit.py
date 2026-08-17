"""Audit trail, separate from the application log (docs/02-architecture.md §6)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from api.models import AuditLog


def record(
    session: Session,
    actor_id: uuid.UUID | None,
    action: str,
    object_type: str | None = None,
    object_id: uuid.UUID | None = None,
    request: Request | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            ip=request.client.host if request and request.client else None,
            user_agent=(request.headers.get("user-agent") if request else None),
            meta=meta or {},
        )
    )
