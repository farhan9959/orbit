"""Live-session control surface: inject, switch algorithm, and the SSE stream (F13, F29, F30)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.routes.live import _SESSIONS, _frame, _snapshot
from tests.api.conftest import register_and_login, requires_postgres

pytestmark = requires_postgres

SMALL = {"nodes": 12, "flows": 20, "offered_load": 0.9, "failure": "none"}


def _session(client: TestClient, email: str) -> tuple[str, dict[str, str]]:
    headers = register_and_login(client, email)
    response = client.post("/api/v1/sessions", json=SMALL, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"], headers


def test_injecting_a_critical_link_takes_links_down(client: TestClient) -> None:
    session_id, headers = _session(client, "inject@example.com")
    before = client.post(
        f"/api/v1/sessions/{session_id}/control", json={"action": "step"}, headers=headers
    )
    assert before.status_code == 200

    response = client.post(
        f"/api/v1/sessions/{session_id}/inject",
        json={"kind": "critical_link", "count": 2},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["injections"] == 1
    assert body["injected"]["kind"] == "LINK_DOWN"
    assert len(body["injected"]["targets"]) == 2

    assert sum(_frame(_SESSIONS[session_id])["linkDown"]) >= 2, "the failure must reach the wire"


def test_every_injectable_kind_is_accepted(client: TestClient) -> None:
    session_id, headers = _session(client, "kinds@example.com")
    for kind in ("random_link", "random_node", "srlg", "surge"):
        response = client.post(
            f"/api/v1/sessions/{session_id}/inject", json={"kind": kind}, headers=headers
        )
        assert response.status_code == 200, f"{kind}: {response.text}"


def test_an_unknown_injection_kind_is_rejected(client: TestClient) -> None:
    session_id, headers = _session(client, "badkind@example.com")
    response = client.post(
        f"/api/v1/sessions/{session_id}/inject", json={"kind": "rm -rf"}, headers=headers
    )
    assert response.status_code == 422


def test_a_client_cannot_name_the_element_to_fail(client: TestClient) -> None:
    """Targets are chosen server-side; `extra=forbid` rejects a client-supplied target."""
    session_id, headers = _session(client, "targets@example.com")
    response = client.post(
        f"/api/v1/sessions/{session_id}/inject",
        json={"kind": "random_link", "targets": ["n000>n001"]},
        headers=headers,
    )
    assert response.status_code == 422


def test_switching_algorithm_keeps_the_world_and_changes_the_controller(
    client: TestClient,
) -> None:
    session_id, headers = _session(client, "switch@example.com")
    for _ in range(3):
        client.post(
            f"/api/v1/sessions/{session_id}/control", json={"action": "step"}, headers=headers
        )
    tick_before = client.post(
        f"/api/v1/sessions/{session_id}/control", json={"action": "step"}, headers=headers
    ).json()["tick"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/algorithm", json={"algorithm": "cspf"}, headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["algorithm"] == "cspf"
    assert body["tick"] > tick_before, "the clock carries over rather than restarting"

    live = _SESSIONS[session_id]
    assert _snapshot(live)["algorithm"] == "cspf"
    assert live.simulation.algorithm.name == "cspf"


def test_an_unknown_algorithm_is_rejected(client: TestClient) -> None:
    session_id, headers = _session(client, "badalgo@example.com")
    response = client.post(
        f"/api/v1/sessions/{session_id}/algorithm",
        json={"algorithm": "orbit-ceiling-0.6"},
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("path", "payload"),
    [("inject", {"kind": "random_link"}), ("algorithm", {"algorithm": "cspf"})],
)
def test_another_user_cannot_touch_the_session(
    client: TestClient, path: str, payload: dict[str, object]
) -> None:
    session_id, _ = _session(client, f"owner-{path}@example.com")
    intruder = register_and_login(client, f"intruder-{path}@example.com")
    response = client.post(f"/api/v1/sessions/{session_id}/{path}", json=payload, headers=intruder)
    assert response.status_code == 404, "an unowned session must not even be distinguishable"


@pytest.mark.parametrize(
    ("path", "payload"),
    [("inject", {"kind": "random_link"}), ("algorithm", {"algorithm": "cspf"})],
)
def test_the_new_routes_require_a_csrf_token(
    client: TestClient, path: str, payload: dict[str, object]
) -> None:
    session_id, _ = _session(client, f"csrf-{path}@example.com")
    response = client.post(f"/api/v1/sessions/{session_id}/{path}", json=payload)
    assert response.status_code == 403


def test_the_stream_refuses_a_session_the_caller_does_not_own(client: TestClient) -> None:
    """Authorisation is decided before the response streams, so this returns rather than hangs."""
    session_id, _ = _session(client, "streamowner@example.com")
    intruder = register_and_login(client, "streamintruder@example.com")
    assert client.get(f"/api/v1/sessions/{session_id}/stream", headers=intruder).status_code == 404


def test_the_wire_format_is_positional_against_the_snapshot(client: TestClient) -> None:
    """Checked against the publisher's own encoders rather than over the socket.

    The SSE endpoint is deliberately endless — it yields until the client disconnects — so
    reading it to completion from an in-process test client deadlocks. The contract worth
    testing is that a delta's arrays index the snapshot's nodes and links, and that is a
    property of these two functions rather than of the transport.
    """
    live = _SESSIONS[_session(client, "wire@example.com")[0]]
    snapshot, delta = _snapshot(live), _frame(live)

    assert snapshot["type"] == "snapshot"
    assert len(snapshot["nodes"]) == 12
    assert len(delta["util"]) == len(snapshot["links"]), "util is indexed by the snapshot's links"
    assert len(delta["linkDown"]) == len(snapshot["links"])
    assert len(delta["nodeDown"]) == len(snapshot["nodes"])
    assert all(value >= 0.0 for value in delta["util"])
    assert set(delta["demanded"]) <= {"CRITICAL", "HIGH", "NORMAL", "LOW"}


def test_a_delta_merge_coalesces_rather_than_queues(client: TestClient) -> None:
    """The backpressure story: a slow client sees a lower frame rate, never a backlog."""
    live = _SESSIONS[_session(client, "coalesce@example.com")[0]]
    live.merge(_frame(live))
    first = live.pending["tick"]
    live.merge(_frame(live))
    assert live.pending["tick"] > first, "a second frame overwrites rather than enqueues"
    assert live.take()["tick"] > first
    assert live.take() is None
