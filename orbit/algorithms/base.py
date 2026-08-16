"""The routing-algorithm interface every baseline and ORBIT implements.

Assumptions and failure modes:
* `recompute` receives a `GraphView`, never the ground-truth topology. Routing over stale
  knowledge is a modelled behaviour, not a bug (docs/03-simulation-model.md §6).
* A flow absent from the returned mapping is BLACKHOLED for that tick.
* Implementations must be deterministic; they own no RNG unless seeded explicitly.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from orbit.events import Event
from orbit.model import Flow, GraphView, RoutingState


@runtime_checkable
class RoutingAlgorithm(Protocol):
    name: str

    def recompute(
        self, view: GraphView, flows: Sequence[Flow], previous: RoutingState
    ) -> RoutingState: ...

    def drain_events(self) -> tuple[Event, ...]: ...

    def reset(self) -> None: ...


class BaseAlgorithm:
    name = "base"

    def __init__(self) -> None:
        self._events: list[Event] = []

    def emit(self, event: Event) -> None:
        self._events.append(event)

    def drain_events(self) -> tuple[Event, ...]:
        drained = tuple(self._events)
        self._events.clear()
        return drained

    def reset(self) -> None:
        self._events.clear()

    def recompute(
        self, view: GraphView, flows: Sequence[Flow], previous: RoutingState
    ) -> RoutingState:
        raise NotImplementedError


class StaticRouting(BaseAlgorithm):
    name = "static-routing"

    def __init__(self, routing: RoutingState) -> None:
        super().__init__()
        self._routing = routing

    def recompute(
        self, view: GraphView, flows: Sequence[Flow], previous: RoutingState
    ) -> RoutingState:
        return self._routing
