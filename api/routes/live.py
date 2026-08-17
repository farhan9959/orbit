"""Live sessions over SSE (requirements F29, F30; architecture §5).

Assumptions and failure modes:
* Deltas are **coalesced, not queued**. The publisher keeps one pending delta per session
  and merges into it, so a slow client sees a lower frame rate rather than a growing
  backlog. That is the backpressure story.
* A full snapshot is sent on connect and every 50 deltas, so a reconnecting client
  resynchronises without replaying history.
* Live sessions are capped harder than experiments (<= 100 nodes) and expire on inactivity;
  they hold memory and are for demonstration, not measurement.
* SSE rather than WebSockets: traffic is one-directional, it is plain HTTP, it reconnects
  automatically, and cookie auth works without a token-in-querystring hack.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.db import get_session
from api.models import User
from api.security import current_user, enforce_rate_limit
from experiments.runner import make_algorithm
from orbit.engine import (
    FailureEvent,
    FailureKind,
    FailureSchedule,
    Simulation,
    SimulationConfig,
    highest_betweenness_links,
    random_links,
    random_nodes,
)
from orbit.model import Topology
from orbit.scenarios import (
    FailureScenario,
    ScenarioSpec,
    TopologyFamily,
    build_schedule,
    build_topology,
    build_traffic,
)

router = APIRouter(prefix="/api/v1/sessions", tags=["live"])

MAX_LIVE_NODES = 100
MAX_LIVE_SESSIONS_PER_USER = 2
SNAPSHOT_EVERY = 50
PUBLISH_HZ = 4.0


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: int = Field(default=30, ge=2, le=MAX_LIVE_NODES)
    flows: int = Field(default=60, ge=1, le=500)
    algorithm: str = "orbit"
    failure: str = "critical_link"
    offered_load: float = Field(default=0.9, gt=0.0, le=3.0)


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(pattern="^(start|pause|step|reset)$")


class InjectRequest(BaseModel):
    """Interactive failure injection (requirement F13).

    `kind` is a closed set, and targets are chosen **server-side** from the session's own
    topology rather than named by the client. A client that could name arbitrary element
    ids would be enumerating a topology it has not been shown, and would be able to send
    ids belonging to somebody else's session.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern="^(critical_link|random_link|random_node|srlg|surge)$")
    count: int = Field(default=1, ge=1, le=10)
    factor: float = Field(default=2.5, gt=0.0, le=10.0)


class AlgorithmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm: str = Field(pattern="^(spf-static|spf-reconverge|ecmp|cspf|orbit)$")


@dataclass
class LiveSession:
    id: str
    owner_id: uuid.UUID
    simulation: Simulation
    schedule: FailureSchedule
    algorithm: str
    running: bool = False
    deltas: int = 0
    pending: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    injections: int = 0

    def merge(self, delta: dict[str, Any]) -> None:
        if self.pending is None:
            self.pending = delta
        else:
            self.pending.update(delta)

    def take(self) -> dict[str, Any] | None:
        pending, self.pending = self.pending, None
        return pending


_SESSIONS: dict[str, LiveSession] = {}


def _owned(session_id: str, user: User) -> LiveSession:
    live = _SESSIONS.get(session_id)
    if live is None or (live.owner_id != user.id and user.role != "ADMIN"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return live


@router.post("", status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict[str, str]:
    enforce_rate_limit(session, f"sessions:{user.id}", limit=5, window_seconds=3600)
    mine = [s for s in _SESSIONS.values() if s.owner_id == user.id]
    if len(mine) >= MAX_LIVE_SESSIONS_PER_USER:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="live session cap reached")

    spec = ScenarioSpec(
        family=TopologyFamily.WAXMAN,
        nodes=payload.nodes,
        flows=payload.flows,
        offered_load=payload.offered_load,
        ticks=20000,
        failure=FailureScenario(payload.failure),
    )
    seed = spec.seed_for(0)
    topology = build_topology(spec, seed)
    schedule = build_schedule(spec, topology, seed)
    simulation = Simulation(
        topology,
        build_traffic(spec, topology, seed),
        make_algorithm(payload.algorithm),
        SimulationConfig(validate_each_recompute=False),
        schedule=schedule,
    )
    live = LiveSession(
        id=uuid.uuid4().hex,
        owner_id=user.id,
        simulation=simulation,
        schedule=schedule,
        algorithm=payload.algorithm,
    )
    _SESSIONS[live.id] = live
    return {"id": live.id}


@router.post("/{session_id}/control")
def control(
    session_id: str, payload: ControlRequest, user: User = Depends(current_user)
) -> dict[str, Any]:
    live = _owned(session_id, user)
    if payload.action == "start":
        live.running = True
    elif payload.action == "pause":
        live.running = False
    elif payload.action == "reset":
        live.running = False
        live.simulation.reset()
        live.deltas = 0
    else:
        live.merge(_frame(live))
    return _state(live)


@router.post("/{session_id}/inject")
def inject(
    session_id: str, payload: InjectRequest, user: User = Depends(current_user)
) -> dict[str, Any]:
    """Fail something in a running session, right now (requirement F13)."""
    live = _owned(session_id, user)
    topology = live.simulation.topology
    now = live.simulation.time_s

    if payload.kind == "surge":
        event = FailureEvent(now, FailureKind.CONGESTION_SURGE, factor=payload.factor)
    elif payload.kind == "critical_link":
        event = FailureEvent(
            now, FailureKind.LINK_DOWN, highest_betweenness_links(topology, payload.count)
        )
    elif payload.kind == "random_link":
        targets = random_links(topology, payload.count / max(1, len(topology.links)), live.deltas)
        event = FailureEvent(now, FailureKind.LINK_DOWN, targets)
    elif payload.kind == "random_node":
        targets = random_nodes(topology, payload.count / max(1, len(topology.nodes)), live.deltas)
        event = FailureEvent(now, FailureKind.NODE_DOWN, targets)
    else:
        tags = sorted({tag for link in topology.links.values() for tag in link.srlg})
        if not tags:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="topology has no SRLG tags")
        event = FailureEvent(now, FailureKind.SRLG_DOWN, tuple(tags[: payload.count]))

    if event.kind is not FailureKind.CONGESTION_SURGE and not event.targets:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="nothing left to fail")

    live.schedule.inject(event)
    live.injections += 1
    live.merge(_frame(live))
    return _state(live) | {"injected": {"kind": event.kind.value, "targets": list(event.targets)}}


@router.post("/{session_id}/algorithm")
def switch_algorithm(
    session_id: str, payload: AlgorithmRequest, user: User = Depends(current_user)
) -> dict[str, Any]:
    """Hand the running session to a different controller (requirement F29).

    The world carries over — same topology, same traffic, same failures already injected,
    same tick — so the switch shows two controllers meeting the identical situation.
    """
    live = _owned(session_id, user)
    live.simulation.switch_algorithm(make_algorithm(payload.algorithm))
    live.algorithm = payload.algorithm
    live.merge(_frame(live))
    return _state(live)


def _state(live: LiveSession) -> dict[str, Any]:
    return {
        "tick": live.simulation.tick,
        "running": live.running,
        "algorithm": live.algorithm,
        "injections": live.injections,
    }


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def close_session(session_id: str, user: User = Depends(current_user)) -> None:
    _owned(session_id, user)
    _SESSIONS.pop(session_id, None)


def _frame(live: LiveSession) -> dict[str, Any]:
    """One tick, encoded positionally against the snapshot's node and link ordering.

    `util`, `linkDown` and `nodeDown` are arrays rather than id lists so the dashboard can
    feed them straight to the same canvas it uses for replayed runs. At the 100-node session
    cap that is a few hundred rounded floats at 4 Hz.
    """
    result = live.simulation.step()
    base = live.simulation.topology
    truth = result.topology or base
    delivered: dict[str, float] = {}
    demanded: dict[str, float] = {}
    for sample in result.samples:
        delivered[sample.priority.name] = (
            delivered.get(sample.priority.name, 0.0) + sample.delivered_mbps
        )
        demanded[sample.priority.name] = (
            demanded.get(sample.priority.name, 0.0) + sample.demand_mbps
        )
    links = sorted(base.links)
    return {
        "tick": result.tick,
        "time_s": round(result.time_s, 3),
        "delivered": {k: round(v, 2) for k, v in sorted(delivered.items())},
        "demanded": {k: round(v, 2) for k, v in sorted(demanded.items())},
        "blackholed": sum(1 for s in result.samples if s.blackholed),
        "util": [_utilisation(truth, result.link_load, lid) for lid in links],
        "linkDown": [0 if truth.is_usable(lid) else 1 for lid in links],
        "nodeDown": [0 if truth.node(nid).is_up else 1 for nid in sorted(base.nodes)],
        "cascadeDepth": live.schedule.cascade_depth,
        "events": [{"type": e.type.value, "payload": e.payload} for e in result.events[:20]],
    }


def _utilisation(truth: Topology, load: Mapping[str, float], link_id: str) -> float:
    capacity = truth.link(link_id).capacity_mbps
    return round(load.get(link_id, 0.0) / capacity, 4) if capacity > 0 else 0.0


def _snapshot(live: LiveSession) -> dict[str, Any]:
    topology = live.simulation.topology
    return {
        "type": "snapshot",
        "tick": live.simulation.tick,
        "algorithm": live.algorithm,
        "nodes": sorted(topology.nodes),
        "links": [
            {"id": lid, "src": topology.link(lid).src, "dst": topology.link(lid).dst}
            for lid in sorted(topology.links)
        ],
    }


@router.get("/{session_id}/stream")
async def stream(
    session_id: str, request: Request, user: User = Depends(current_user)
) -> StreamingResponse:
    live = _owned(session_id, user)

    async def publish():
        yield f"data: {json.dumps(_snapshot(live))}\n\n"
        while True:
            if await request.is_disconnected():
                break
            if live.running:
                live.merge(_frame(live))
                live.deltas += 1
            payload = live.take()
            if payload is not None:
                if live.deltas % SNAPSHOT_EVERY == 0:
                    yield f"data: {json.dumps(_snapshot(live))}\n\n"
                yield f"data: {json.dumps({'type': 'delta', **payload})}\n\n"
            await asyncio.sleep(1.0 / PUBLISH_HZ)

    return StreamingResponse(
        publish(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
