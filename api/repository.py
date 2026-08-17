"""Scoped data access — the control that prevents broken object-level authorization.

Threat model T2. Ownership is enforced *here*, not in route handlers, and there is no
unscoped accessor to call. A handler that forgets to check cannot accidentally succeed,
because the only way to reach an object is through a repository bound to a principal.

That distinction is the whole point: per-handler checks are how IDOR happens, because
eventually someone adds a handler and forgets one.

Assumptions and failure modes:
* ADMIN bypasses the owner filter. That is deliberate and is the only bypass.
* A miss returns None, and callers surface 404 rather than 403 for objects the user may not
  know exist, so the API is not an existence oracle.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import Experiment, Run, Scenario, Topology, User

ADMIN = "ADMIN"


class ScopedRepository[Owned: (Topology, Scenario, Experiment)]:
    def __init__(self, session: Session, model: type[Owned], principal: User) -> None:
        self._session = session
        self._model = model
        self._principal = principal

    def _scoped(self):
        statement = select(self._model)
        if self._principal.role != ADMIN:
            statement = statement.where(self._model.owner_id == self._principal.id)
        return statement

    def list(self, limit: int = 50, offset: int = 0) -> Sequence[Owned]:
        statement = (
            self._scoped().order_by(self._model.created_at.desc()).limit(limit).offset(offset)
        )
        return list(self._session.execute(statement).scalars())

    def get(self, object_id: uuid.UUID) -> Owned | None:
        statement = self._scoped().where(self._model.id == object_id)
        return self._session.execute(statement).scalars().first()

    def add(self, obj: Owned) -> Owned:
        obj.owner_id = self._principal.id
        self._session.add(obj)
        self._session.flush()
        return obj

    def delete(self, obj: Owned) -> None:
        self._session.delete(obj)
        self._session.flush()


def for_user(session: Session, principal: User) -> dict[str, ScopedRepository]:
    return {
        "topologies": ScopedRepository(session, Topology, principal),
        "scenarios": ScopedRepository(session, Scenario, principal),
        "experiments": ScopedRepository(session, Experiment, principal),
    }


def run_for_user(session: Session, principal: User, run_id: uuid.UUID) -> Run | None:
    """Runs are reached through their experiment, so the same ownership filter applies."""
    statement = (
        select(Run).join(Experiment, Run.experiment_id == Experiment.id).where(Run.id == run_id)
    )
    if principal.role != ADMIN:
        statement = statement.where(Experiment.owner_id == principal.id)
    return session.execute(statement).scalars().first()
