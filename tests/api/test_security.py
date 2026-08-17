"""Security tests — one per control in docs/04-threat-model.md.

An unchecked box is fine; a checked box without a test is a lie. This file is the evidence
for the audit document.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import register_and_login, requires_postgres

pytestmark = requires_postgres

TOPOLOGY = {"name": "t1", "spec": {"family": "waxman", "nodes": 10, "seed": 1}}


# ---------------------------------------------------------------- T2 authorization


def test_a_user_cannot_read_another_users_topology(client: TestClient) -> None:
    alice = register_and_login(client, "alice@example.com")
    created = client.post("/api/v1/topologies", json=TOPOLOGY, headers=alice)
    assert created.status_code == 201
    topology_id = created.json()["id"]
    client.post("/api/v1/auth/logout", headers=alice)

    bob = register_and_login(client, "bob@example.com")
    response = client.get(f"/api/v1/topologies/{topology_id}", headers=bob)
    assert response.status_code == 404, "must not confirm the object exists"


def test_a_user_cannot_delete_another_users_topology(client: TestClient) -> None:
    alice = register_and_login(client, "alice@example.com")
    topology_id = client.post("/api/v1/topologies", json=TOPOLOGY, headers=alice).json()["id"]
    client.post("/api/v1/auth/logout", headers=alice)

    bob = register_and_login(client, "bob@example.com")
    assert client.delete(f"/api/v1/topologies/{topology_id}", headers=bob).status_code == 404

    client.post("/api/v1/auth/logout", headers=bob)
    alice = register_and_login(client, "alice@example.com")
    assert client.get(f"/api/v1/topologies/{topology_id}", headers=alice).status_code == 200


def test_listing_never_leaks_another_users_objects(client: TestClient) -> None:
    alice = register_and_login(client, "alice@example.com")
    client.post("/api/v1/topologies", json=TOPOLOGY, headers=alice)
    client.post("/api/v1/auth/logout", headers=alice)

    bob = register_and_login(client, "bob@example.com")
    assert client.get("/api/v1/topologies", headers=bob).json() == []


def test_a_user_cannot_read_another_users_run(client: TestClient) -> None:
    alice = register_and_login(client, "alice@example.com")
    experiment = client.post(
        "/api/v1/experiments",
        json={
            "name": "e1",
            "topology": {"family": "waxman", "nodes": 8, "seed": 1},
            "scenario": {"flows": 5, "ticks": 5},
            "algorithms": ["cspf"],
            "trials": 1,
        },
        headers=alice,
    )
    assert experiment.status_code == 202
    experiment_id = experiment.json()["id"]
    client.post("/api/v1/auth/logout", headers=alice)

    bob = register_and_login(client, "bob@example.com")
    assert client.get(f"/api/v1/experiments/{experiment_id}", headers=bob).status_code == 404
    assert client.get(f"/api/v1/experiments/{experiment_id}/runs", headers=bob).status_code == 404


# ------------------------------------------------------------------------- T3 auth


def test_login_failure_is_generic_and_does_not_enumerate_users(client: TestClient) -> None:
    register_and_login(client, "real@example.com")
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "x"})

    missing = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever12345"}
    )
    wrong = client.post(
        "/api/v1/auth/login", json={"email": "real@example.com", "password": "wrongpassword123"}
    )
    assert missing.status_code == wrong.status_code == 401
    assert missing.json()["error"]["message"] == wrong.json()["error"]["message"]


def test_password_is_stored_hashed_never_in_plaintext(client: TestClient, schema) -> None:
    from api.models import User

    register_and_login(client, "hash@example.com", "a-very-good-password")
    with schema() as session:
        user = session.query(User).filter_by(email="hash@example.com").one()
    assert "a-very-good-password" not in user.password_hash
    assert user.password_hash.startswith("$argon2")


def test_short_and_common_passwords_are_rejected(client: TestClient) -> None:
    assert (
        client.post(
            "/api/v1/auth/register", json={"email": "s@example.com", "password": "short"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/auth/register", json={"email": "c@example.com", "password": "password1234"}
        ).status_code
        == 422
    )


def test_logout_actually_revokes_the_session(client: TestClient) -> None:
    headers = register_and_login(client, "revoke@example.com")
    assert client.get("/api/v1/auth/me").status_code == 200
    client.post("/api/v1/auth/logout", headers=headers)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_rotates_the_session_id(client: TestClient) -> None:
    register_and_login(client, "rotate@example.com")
    first = client.cookies.get("orbit_session")
    client.post(
        "/api/v1/auth/login",
        json={"email": "rotate@example.com", "password": "correct-horse-battery"},
    )
    assert client.cookies.get("orbit_session") != first


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    for method, path in (
        ("get", "/api/v1/topologies"),
        ("post", "/api/v1/topologies"),
        ("get", "/api/v1/experiments"),
    ):
        assert getattr(client, method)(path).status_code == 401


# ------------------------------------------------------------------------ T6 CSRF


def test_a_state_changing_request_without_a_csrf_token_is_refused(client: TestClient) -> None:
    register_and_login(client, "csrf@example.com")
    assert client.post("/api/v1/topologies", json=TOPOLOGY).status_code == 403


def test_a_wrong_csrf_token_is_refused(client: TestClient) -> None:
    register_and_login(client, "csrf2@example.com")
    response = client.post(
        "/api/v1/topologies", json=TOPOLOGY, headers={"X-CSRF-Token": "not-the-token"}
    )
    assert response.status_code == 403


def test_get_requests_do_not_need_a_csrf_token(client: TestClient) -> None:
    register_and_login(client, "csrf3@example.com")
    assert client.get("/api/v1/topologies").status_code == 200


# -------------------------------------------------------------- T1 resource caps


@pytest.mark.parametrize(
    "spec",
    [
        {"family": "waxman", "nodes": 100000},
        {"family": "waxman", "nodes": 1},
        {"family": "nonsense", "nodes": 10},
    ],
)
def test_oversized_or_invalid_specs_are_rejected_before_any_work(
    client: TestClient, spec: dict
) -> None:
    headers = register_and_login(client, "caps@example.com")
    response = client.post("/api/v1/topologies", json={"name": "x", "spec": spec}, headers=headers)
    assert response.status_code == 422


def test_unknown_fields_are_rejected_rather_than_silently_ignored(client: TestClient) -> None:
    headers = register_and_login(client, "extra@example.com")
    payload = {"name": "x", "spec": {"family": "waxman", "nodes": 10, "surprise": 1}}
    assert client.post("/api/v1/topologies", json=payload, headers=headers).status_code == 422


def test_registration_is_rate_limited(client: TestClient) -> None:
    codes = [
        client.post(
            "/api/v1/auth/register",
            json={"email": f"rl{i}@example.com", "password": "correct-horse-battery"},
        ).status_code
        for i in range(5)
    ]
    assert 429 in codes


def test_concurrent_experiment_quota_is_enforced(client: TestClient) -> None:
    headers = register_and_login(client, "quota@example.com")
    client.post("/api/v1/auth/logout", headers=headers)
    headers = register_and_login(client, "quota2@example.com")
    body = {
        "name": "e",
        "topology": {"family": "waxman", "nodes": 8, "seed": 1},
        "scenario": {"flows": 5, "ticks": 5},
        "algorithms": ["cspf"],
        "trials": 1,
    }
    first = client.post("/api/v1/experiments", json=body, headers=headers)
    second = client.post("/api/v1/experiments", json=body, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 429


def test_idempotency_key_prevents_a_duplicate_experiment(client: TestClient) -> None:
    headers = {**register_and_login(client, "idem@example.com"), "Idempotency-Key": "abc123"}
    body = {
        "name": "e",
        "topology": {"family": "waxman", "nodes": 8, "seed": 1},
        "scenario": {"flows": 5, "ticks": 5},
        "algorithms": ["cspf"],
        "trials": 1,
    }
    first = client.post("/api/v1/experiments", json=body, headers=headers)
    second = client.post("/api/v1/experiments", json=body, headers=headers)
    assert first.json()["id"] == second.json()["id"]


# ------------------------------------------------------- T11 information disclosure


def test_errors_never_leak_a_traceback(client: TestClient) -> None:
    response = client.get("/api/v1/topologies/not-a-uuid")
    assert response.status_code in (401, 422)
    body = response.text.lower()
    assert "traceback" not in body and "sqlalchemy" not in body


def test_every_error_carries_the_standard_shape(client: TestClient) -> None:
    body = client.get("/api/v1/topologies").json()
    assert set(body["error"]) == {"code", "message", "request_id"}


def test_a_password_never_reaches_the_logs(client: TestClient, caplog) -> None:
    secret = "unmistakable-password-1234"
    with caplog.at_level(logging.DEBUG):
        client.post("/api/v1/auth/register", json={"email": "log@example.com", "password": secret})
    assert secret not in caplog.text


# ------------------------------------------------------------------ security headers


def test_security_headers_are_present(client: TestClient) -> None:
    headers = client.get("/healthz").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["Referrer-Policy"] == "no-referrer"


def test_the_session_cookie_is_httponly_and_samesite(client: TestClient) -> None:
    register_and_login(client, "cookie@example.com")
    raw = "; ".join(v for k, v in client.headers.items())
    _ = raw
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "cookie@example.com", "password": "correct-horse-battery"},
    )
    set_cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie.replace("Lax", "lax")
