"""API test fixtures. Each test gets an isolated schema in the real PostgreSQL.

SQLite is not substituted: the model uses `jsonb`, and testing against a different engine
than production ships would be testing something other than what runs.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://orbit:orbitpw@127.0.0.1:55432/orbit")
os.environ.setdefault("SESSION_SECRET", "test-secret-value-at-least-32-bytes-long!!")

from api import db as db_module
from api.config import get_settings
from api.main import create_app
from api.models import Base

BASE_URL = "postgresql+psycopg://orbit:orbitpw@127.0.0.1:55432/orbit"


def postgres_available() -> bool:
    try:
        create_engine(BASE_URL).connect().close()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not postgres_available(), reason="PostgreSQL not reachable on 127.0.0.1:55432"
)


@pytest.fixture
def schema(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    name = f"t{uuid.uuid4().hex[:12]}"
    engine = create_engine(BASE_URL, future=True)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{name}"'))

    scoped = create_engine(BASE_URL, future=True, connect_args={"options": f"-csearch_path={name}"})
    Base.metadata.create_all(scoped)
    factory = sessionmaker(bind=scoped, expire_on_commit=False, future=True)

    monkeypatch.setattr(db_module, "_engine", scoped)
    monkeypatch.setattr(db_module, "_factory", factory)
    get_settings.cache_clear()
    try:
        yield factory
    finally:
        scoped.dispose()
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        engine.dispose()


@pytest.fixture
def client(schema: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def register_and_login(
    client: TestClient, email: str, password: str = "correct-horse-battery"
) -> dict[str, str]:
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}
