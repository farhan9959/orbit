"""Request and response schemas with the caps from threat model T1.

A spec is data. Nothing here is ever executed, interpreted as a filesystem path, or
deserialised with anything but a strict model. `extra="forbid"` is deliberate: silently
ignoring unknown keys is how a typo in a benchmark spec becomes a run that measured
something other than what was asked for.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

MAX_NODES = 500
MAX_LINKS = 5000
MAX_FLOWS = 2000
MAX_TICKS = 20000
MAX_TRIALS = 50
MAX_ALGORITHMS = 8

ALGORITHM_NAMES = (
    "spf-static",
    "spf-reconverge",
    "ecmp",
    "cspf",
    "orbit",
    "orbit-no-protection",
    "orbit-no-preemption",
    "orbit-no-damping",
    "orbit-no-fallback",
    "orbit-restoration-only",
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(Strict):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)


class LoginRequest(Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(Strict):
    id: uuid.UUID
    email: str
    role: str
    csrf_token: str | None = None


class TopologySpec(Strict):
    family: Literal["grid", "ring", "waxman", "scale_free"] = "waxman"
    nodes: int = Field(default=50, ge=2, le=MAX_NODES)
    seed: int = Field(default=0, ge=-(2**31), le=2**31)
    capacity_mbps: float = Field(default=100.0, gt=0.0, le=1_000_000.0)


class TopologyCreate(Strict):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[\w \-.:]+$")
    spec: TopologySpec


class TopologyOut(Strict):
    id: uuid.UUID
    name: str
    spec: dict[str, Any]
    node_count: int
    link_count: int
    created_at: datetime


class ScenarioSpecIn(Strict):
    flows: int = Field(default=100, ge=1, le=MAX_FLOWS)
    offered_load: float = Field(default=0.7, gt=0.0, le=5.0)
    ticks: int = Field(default=150, ge=1, le=MAX_TICKS)
    failure: Literal[
        "none",
        "random_node_10",
        "random_node_30",
        "random_node_50",
        "critical_link",
        "regional_srlg",
        "congestion_surge",
        "cascading",
    ] = "critical_link"
    control_mode: Literal["CENTRALISED", "DISTRIBUTED"] = "CENTRALISED"


class ScenarioCreate(Strict):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[\w \-.:]+$")
    spec: ScenarioSpecIn


class ScenarioOut(Strict):
    id: uuid.UUID
    name: str
    spec: dict[str, Any]
    created_at: datetime


class ExperimentCreate(Strict):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[\w \-.:]+$")
    topology: TopologySpec
    scenario: ScenarioSpecIn
    algorithms: list[Literal[ALGORITHM_NAMES]] = Field(  # type: ignore[valid-type]
        default_factory=lambda: ["cspf", "orbit"], min_length=1, max_length=MAX_ALGORITHMS
    )
    trials: int = Field(default=5, ge=1, le=MAX_TRIALS)


class ExperimentOut(Strict):
    id: uuid.UUID
    name: str
    status: str
    spec: dict[str, Any]
    created_at: datetime
    run_count: int = 0


class RunOut(Strict):
    id: uuid.UUID
    experiment_id: uuid.UUID
    algorithm: str
    trial: int
    seed: int
    status: str
    summary: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None


class ErrorBody(Strict):
    code: str
    message: str
    request_id: str


class ErrorResponse(Strict):
    error: ErrorBody
