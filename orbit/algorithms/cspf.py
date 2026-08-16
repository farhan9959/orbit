"""Baseline B4: congestion-aware shortest path (CSPF on residual capacity).

This is the strong baseline. It is capacity-aware but priority-blind, so the ORBIT-vs-CSPF
difference isolates the contribution of priority awareness specifically.

Assumptions and failure modes:
* Flows are placed in arrival order (sorted by id for determinism), each reserving its
  demand against a running residual-capacity table. Placement is greedy and therefore
  suboptimal; the LP gap analysis quantifies by how much.
* Links with insufficient residual capacity for the whole demand are pruned before the
  shortest-path computation, so a flow either fits end to end or is not placed.
* A flow that cannot be placed at full demand falls back to the unconstrained shortest path
  rather than being blackholed, because a real CSPF deployment forwards best-effort rather
  than dropping the traffic at the ingress. Without this, CSPF would look artificially bad
  on delivery ratio and artificially good on latency.
* The cost blends latency and utilisation. Both weights are tuned by the same sweep budget
  given to ORBIT's parameters (docs/05-methodology.md B3 rule 4).
"""

from __future__ import annotations

from collections.abc import Sequence

from orbit.algorithms.base import BaseAlgorithm
from orbit.algorithms.paths import route_from_tree, shortest_path_tree
from orbit.events import Event, EventType
from orbit.model import (
    Flow,
    FlowId,
    GraphView,
    Link,
    LinkId,
    Placement,
    Route,
    RoutingState,
    Topology,
)


class ConstrainedShortestPath(BaseAlgorithm):
    name = "cspf"

    def __init__(self, latency_weight: float = 1.0, utilisation_weight: float = 10.0) -> None:
        super().__init__()
        self._latency_weight = latency_weight
        self._utilisation_weight = utilisation_weight

    def recompute(
        self, view: GraphView, flows: Sequence[Flow], previous: RoutingState
    ) -> RoutingState:
        topology = view.topology
        residual: dict[LinkId, float] = {
            link_id: topology.link(link_id).effective_capacity_mbps for link_id in topology.links
        }
        routing: dict[FlowId, Placement] = {}

        ordered = sorted(flows, key=lambda item: (-item.demand_mbps, item.id))
        for flow in ordered:
            route = self._place(topology, residual, flow)
            if route is None:
                if flow.id in previous:
                    self.emit(
                        Event(
                            view.observed_at_tick,
                            EventType.FLOW_BLACKHOLED,
                            {"flow": flow.id},
                        )
                    )
                continue
            for link_id in route.links:
                residual[link_id] = max(0.0, residual[link_id] - flow.demand_mbps)
            before = previous.get(flow.id)
            if before is not None and _links_of(before) != route.links:
                self.emit(
                    Event(
                        view.observed_at_tick,
                        EventType.FLOW_REROUTED,
                        {"flow": flow.id, "via": "CSPF"},
                    )
                )
            routing[flow.id] = route
        return routing

    def _cost(self, residual: dict[LinkId, float], topology_link: Link) -> float:
        capacity = topology_link.effective_capacity_mbps
        free = residual.get(topology_link.id, 0.0)
        utilisation = 1.0 - (free / capacity) if capacity > 0.0 else 1.0
        return (
            self._latency_weight * topology_link.prop_delay_ms
            + self._utilisation_weight * utilisation
        )

    def _place(self, topology: Topology, residual: dict[LinkId, float], flow: Flow) -> Route | None:
        def fits(link: Link) -> bool:
            return topology.is_usable(link.id) and residual.get(link.id, 0.0) >= flow.demand_mbps

        def usable(link: Link) -> bool:
            return bool(topology.is_usable(link.id))

        for allowed in (fits, usable):
            _, predecessor = shortest_path_tree(
                topology, flow.src, cost=lambda link: self._cost(residual, link), allowed=allowed
            )
            route = route_from_tree(topology, predecessor, flow.src, flow.dst)
            if route is not None:
                return route
        return None


def _links_of(placement: Placement) -> tuple[LinkId, ...]:
    if isinstance(placement, Route):
        return placement.links
    return placement.routes[0].links
