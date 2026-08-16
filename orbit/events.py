"""Structured control-plane events (requirement F21)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    FAILURE_INJECTED = "FAILURE_INJECTED"
    FAILURE_DETECTED = "FAILURE_DETECTED"
    FLOW_REROUTED = "FLOW_REROUTED"
    FLOW_PREEMPTED = "FLOW_PREEMPTED"
    FLOW_BLACKHOLED = "FLOW_BLACKHOLED"
    FLOW_RESTORED = "FLOW_RESTORED"
    RECONVERGED = "RECONVERGED"
    CASCADE_FAILURE = "CASCADE_FAILURE"


@dataclass(frozen=True, slots=True)
class Event:
    tick: int
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
