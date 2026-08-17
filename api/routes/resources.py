"""Topologies, scenarios, experiments and runs — all reached through scoped repositories."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.audit import record as audit
from api.db import get_session
from api.models import Experiment, Job, Run, Scenario, Topology, User
from api.repository import for_user, run_for_user
from api.schemas import (
    ExperimentCreate,
    ExperimentOut,
    RunOut,
    ScenarioCreate,
    ScenarioOut,
    TopologyCreate,
    TopologyOut,
)
from api.security import client_ip, current_user, enforce_rate_limit
from orbit.scenarios import ScenarioSpec, TopologyFamily, build_topology

router = APIRouter(prefix="/api/v1", tags=["resources"])

NOT_FOUND = "not found"


def _missing() -> HTTPException:
    """404 rather than 403, so the API does not confirm that an object exists."""
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


@router.get("/topologies", response_model=list[TopologyOut])
def list_topologies(
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list[TopologyOut]:
    repos = for_user(session, user)
    return [
        TopologyOut(
            id=item.id,
            name=item.name,
            spec=item.spec,
            node_count=item.node_count,
            link_count=item.link_count,
            created_at=item.created_at,
        )
        for item in repos["topologies"].list(min(limit, 200), offset)
    ]


@router.post("/topologies", response_model=TopologyOut, status_code=status.HTTP_201_CREATED)
def create_topology(
    payload: TopologyCreate,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> TopologyOut:
    spec = ScenarioSpec(
        family=TopologyFamily(payload.spec.family),
        nodes=payload.spec.nodes,
        link_capacity_mbps=payload.spec.capacity_mbps,
    )
    built = build_topology(spec, payload.spec.seed)
    topology = Topology(
        name=payload.name,
        spec=payload.spec.model_dump(),
        node_count=len(built.nodes),
        link_count=len(built.links),
        seed=payload.spec.seed,
    )
    for_user(session, user)["topologies"].add(topology)
    audit(session, user.id, "topology.create", "topology", topology.id, request)
    return TopologyOut(
        id=topology.id,
        name=topology.name,
        spec=topology.spec,
        node_count=topology.node_count,
        link_count=topology.link_count,
        created_at=topology.created_at,
    )


@router.get("/topologies/{topology_id}", response_model=TopologyOut)
def get_topology(
    topology_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> TopologyOut:
    item = for_user(session, user)["topologies"].get(topology_id)
    if item is None:
        raise _missing()
    return TopologyOut(
        id=item.id,
        name=item.name,
        spec=item.spec,
        node_count=item.node_count,
        link_count=item.link_count,
        created_at=item.created_at,
    )


@router.delete("/topologies/{topology_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topology(
    topology_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> None:
    repo = for_user(session, user)["topologies"]
    item = repo.get(topology_id)
    if item is None:
        raise _missing()
    repo.delete(item)
    audit(session, user.id, "topology.delete", "topology", topology_id, request)


@router.get("/scenarios", response_model=list[ScenarioOut])
def list_scenarios(
    session: Session = Depends(get_session), user: User = Depends(current_user)
) -> list[ScenarioOut]:
    return [
        ScenarioOut(id=i.id, name=i.name, spec=i.spec, created_at=i.created_at)
        for i in for_user(session, user)["scenarios"].list()
    ]


@router.post("/scenarios", response_model=ScenarioOut, status_code=status.HTTP_201_CREATED)
def create_scenario(
    payload: ScenarioCreate,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> ScenarioOut:
    scenario = Scenario(name=payload.name, spec=payload.spec.model_dump())
    for_user(session, user)["scenarios"].add(scenario)
    audit(session, user.id, "scenario.create", "scenario", scenario.id, request)
    return ScenarioOut(
        id=scenario.id, name=scenario.name, spec=scenario.spec, created_at=scenario.created_at
    )


@router.get("/scenarios/{scenario_id}", response_model=ScenarioOut)
def get_scenario(
    scenario_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> ScenarioOut:
    item = for_user(session, user)["scenarios"].get(scenario_id)
    if item is None:
        raise _missing()
    return ScenarioOut(id=item.id, name=item.name, spec=item.spec, created_at=item.created_at)


def _run_count(session: Session, experiment_id: uuid.UUID) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(Run).where(Run.experiment_id == experiment_id)
        ).scalar_one()
    )


@router.post("/experiments", response_model=ExperimentOut, status_code=status.HTTP_202_ACCEPTED)
def create_experiment(
    payload: ExperimentCreate,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ExperimentOut:
    """202 with a resource to poll, not 200 with results: benchmarks take minutes."""
    enforce_rate_limit(session, f"experiments:{user.id}", limit=10, window_seconds=3600)

    running = session.execute(
        select(func.count())
        .select_from(Experiment)
        .where(Experiment.owner_id == user.id, Experiment.status.in_(("QUEUED", "RUNNING")))
    ).scalar_one()
    quota = 4 if user.role == "ADMIN" else 1
    if running >= quota:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="concurrent experiment quota reached"
        )

    if idempotency_key:
        existing = (
            session.execute(
                select(Experiment).where(
                    Experiment.owner_id == user.id, Experiment.idempotency_key == idempotency_key
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            return ExperimentOut(
                id=existing.id,
                name=existing.name,
                status=existing.status,
                spec=existing.spec,
                created_at=existing.created_at,
                run_count=_run_count(session, existing.id),
            )

    experiment = Experiment(
        name=payload.name,
        spec=payload.model_dump(),
        status="QUEUED",
        idempotency_key=idempotency_key,
    )
    for_user(session, user)["experiments"].add(experiment)
    session.add(Job(experiment_id=experiment.id, state="QUEUED"))
    audit(session, user.id, "experiment.create", "experiment", experiment.id, request)
    return ExperimentOut(
        id=experiment.id,
        name=experiment.name,
        status=experiment.status,
        spec=experiment.spec,
        created_at=experiment.created_at,
    )


@router.get("/experiments", response_model=list[ExperimentOut])
def list_experiments(
    session: Session = Depends(get_session), user: User = Depends(current_user)
) -> list[ExperimentOut]:
    return [
        ExperimentOut(
            id=i.id,
            name=i.name,
            status=i.status,
            spec=i.spec,
            created_at=i.created_at,
            run_count=_run_count(session, i.id),
        )
        for i in for_user(session, user)["experiments"].list()
    ]


@router.get("/experiments/{experiment_id}", response_model=ExperimentOut)
def get_experiment(
    experiment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> ExperimentOut:
    item = for_user(session, user)["experiments"].get(experiment_id)
    if item is None:
        raise _missing()
    return ExperimentOut(
        id=item.id,
        name=item.name,
        status=item.status,
        spec=item.spec,
        created_at=item.created_at,
        run_count=_run_count(session, item.id),
    )


@router.delete("/experiments/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_experiment(
    experiment_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> None:
    repo = for_user(session, user)["experiments"]
    item = repo.get(experiment_id)
    if item is None:
        raise _missing()
    item.status = "CANCELLED"
    for job in session.execute(select(Job).where(Job.experiment_id == experiment_id)).scalars():
        job.state = "CANCELLED"
    audit(session, user.id, "experiment.cancel", "experiment", experiment_id, request)


@router.get("/experiments/{experiment_id}/runs", response_model=list[RunOut])
def list_runs(
    experiment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list[RunOut]:
    if for_user(session, user)["experiments"].get(experiment_id) is None:
        raise _missing()
    runs = session.execute(
        select(Run).where(Run.experiment_id == experiment_id).order_by(Run.trial)
    ).scalars()
    return [
        RunOut(
            id=r.id,
            experiment_id=r.experiment_id,
            algorithm=r.algorithm,
            trial=r.trial,
            seed=r.seed,
            status=r.status,
            summary=r.summary,
            started_at=r.started_at,
            finished_at=r.finished_at,
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> RunOut:
    run = run_for_user(session, user, run_id)
    if run is None:
        raise _missing()
    return RunOut(
        id=run.id,
        experiment_id=run.experiment_id,
        algorithm=run.algorithm,
        trial=run.trial,
        seed=run.seed,
        status=run.status,
        summary=run.summary,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


_ = client_ip
