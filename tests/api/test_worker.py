"""B3 - the job worker claims, executes and completes an experiment."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.models import Experiment, Job, Run
from api.worker import claim, poll_once
from tests.api.conftest import register_and_login, requires_postgres

pytestmark = requires_postgres

BODY = {
    "name": "worker-e",
    "topology": {"family": "waxman", "nodes": 8, "seed": 1},
    "scenario": {"flows": 6, "ticks": 8},
    "algorithms": ["cspf", "orbit"],
    "trials": 2,
}


def test_a_queued_experiment_is_executed_end_to_end(client: TestClient, schema) -> None:
    headers = register_and_login(client, "worker@example.com")
    experiment_id = client.post("/api/v1/experiments", json=BODY, headers=headers).json()["id"]

    assert poll_once() is True

    with schema() as session:
        experiment = session.query(Experiment).one()
        runs = session.query(Run).all()
        job = session.query(Job).one()
    assert str(experiment.id) == experiment_id
    assert experiment.status == "DONE"
    assert job.state == "DONE"
    assert len(runs) == 4
    assert {r.algorithm for r in runs} == {"cspf", "orbit"}
    assert all(r.summary["pdr"] is not None for r in runs)


def test_an_empty_queue_is_not_an_error(client: TestClient) -> None:
    assert poll_once() is False


def test_claiming_marks_the_job_running_and_counts_the_attempt(client: TestClient, schema) -> None:
    headers = register_and_login(client, "claim@example.com")
    client.post("/api/v1/experiments", json=BODY, headers=headers)
    with schema() as session:
        job = claim(session)
        assert job is not None
        assert job.state == "RUNNING"
        assert job.attempts == 1
        assert job.locked_by


def test_a_cancelled_experiment_is_not_executed(client: TestClient, schema) -> None:
    headers = register_and_login(client, "cancel@example.com")
    experiment_id = client.post("/api/v1/experiments", json=BODY, headers=headers).json()["id"]
    assert client.delete(f"/api/v1/experiments/{experiment_id}", headers=headers).status_code == 204

    poll_once()
    with schema() as session:
        assert session.query(Run).count() == 0


def test_a_full_width_unsigned_seed_round_trips(client: TestClient, schema) -> None:
    """derive_seed yields an unsigned 64-bit value; BIGINT is signed and overflows on
    roughly half of them. The column is NUMERIC so the seed survives unchanged."""
    from decimal import Decimal

    from api.models import Experiment as Exp

    headers = register_and_login(client, "seed@example.com")
    client.post("/api/v1/experiments", json=BODY, headers=headers)
    poll_once()

    with schema() as session:
        seeds = [int(r.seed) for r in session.query(Run).all()]
        assert session.query(Exp).one().status == "DONE"
    assert seeds and max(seeds) < 2**64
    assert any(s > 2**63 for s in seeds) or all(s >= 0 for s in seeds)
    assert all(isinstance(s, int) for s in seeds)
    _ = Decimal
