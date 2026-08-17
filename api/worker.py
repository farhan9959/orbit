"""Job worker: claims experiments with FOR UPDATE SKIP LOCKED and executes them.

Assumptions and failure modes:
* SKIP LOCKED means several workers can poll the same table without blocking each other and
  without a broker. The queue holds tens of jobs on one node, which is why Celery/Redis was
  rejected: a broker, a result backend and a new failure mode for no benefit.
* A crashed worker leaves its job locked. `attempts` is incremented on claim so a poison job
  cannot be retried forever.
* Benchmarks run in the worker, never in a request, because they take minutes.
"""

from __future__ import annotations

import socket
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import session_scope
from api.models import Experiment, Job, Run
from api.observability import active_runs, configure_logging, control_seconds, run_duration
from experiments.runner import run_one
from orbit.detect import DetectorConfig
from orbit.scenarios import FailureScenario, ScenarioSpec, TopologyFamily

MAX_ATTEMPTS = 3
WORKER_ID = f"{socket.gethostname()}:{id(object())}"


def claim(session: Session) -> Job | None:
    statement = (
        select(Job)
        .where(Job.state == "QUEUED", Job.attempts < MAX_ATTEMPTS)
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.execute(statement).scalars().first()
    if job is None:
        return None
    job.state = "RUNNING"
    job.attempts += 1
    job.locked_at = datetime.now(UTC)
    job.locked_by = WORKER_ID
    session.flush()
    return job


def spec_from(payload: dict) -> ScenarioSpec:
    topology = payload["topology"]
    scenario = payload["scenario"]
    return ScenarioSpec(
        family=TopologyFamily(topology["family"]),
        nodes=topology["nodes"],
        flows=scenario["flows"],
        offered_load=scenario["offered_load"],
        ticks=scenario["ticks"],
        failure=FailureScenario(scenario["failure"]),
        control_mode=scenario["control_mode"],
        link_capacity_mbps=topology["capacity_mbps"],
    )


def execute_job(session: Session, job: Job) -> None:
    experiment = session.get(Experiment, job.experiment_id)
    if experiment is None or experiment.status == "CANCELLED":
        job.state = "CANCELLED"
        return

    experiment.status = "RUNNING"
    experiment.started_at = datetime.now(UTC)
    session.flush()

    payload = experiment.spec
    spec = spec_from(payload)
    for algorithm in payload["algorithms"]:
        for trial in range(payload["trials"]):
            session.refresh(experiment)
            if experiment.status == "CANCELLED":
                job.state = "CANCELLED"
                return
            active_runs.inc()
            started = time.perf_counter()
            try:
                record = run_one(spec, algorithm, trial, experiment.name, DetectorConfig())
            finally:
                active_runs.dec()
            run_duration.labels(algorithm=algorithm).observe(time.perf_counter() - started)
            control_seconds.labels(algorithm=algorithm).observe(record.control_seconds)
            session.add(
                Run(
                    experiment_id=experiment.id,
                    algorithm=algorithm,
                    trial=trial,
                    seed=record.seed,
                    status="DONE",
                    summary={
                        "pdr": record.pdr,
                        "pdr_critical": record.pdr_critical,
                        "pdr_high": record.pdr_high,
                        "pdr_low": record.pdr_low,
                        "throughput_mbps": record.throughput_mbps,
                        "control_seconds": record.control_seconds,
                        "reroutes": record.reroutes,
                        "preemptions": record.preemptions,
                        "cascade_depth": record.cascade_depth,
                        "censored": record.censored,
                    },
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                )
            )
            session.flush()

    experiment.status = "DONE"
    experiment.finished_at = datetime.now(UTC)
    job.state = "DONE"


def poll_once() -> bool:
    with session_scope() as session:
        job = claim(session)
        if job is None:
            return False
        try:
            execute_job(session, job)
        except Exception as error:
            job.state = "QUEUED" if job.attempts < MAX_ATTEMPTS else "FAILED"
            job.error = str(error)[:2000]
            experiment = session.get(Experiment, job.experiment_id)
            if experiment is not None and job.state == "FAILED":
                experiment.status = "FAILED"
        return True


def main(poll_seconds: float = 1.0) -> None:
    configure_logging()
    while True:
        if not poll_once():
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
