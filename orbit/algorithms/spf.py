"""Baselines B1 (static shortest path) and B2 (shortest path with reconvergence).

Assumptions and failure modes:
* Both are capacity-blind by design. B2 will happily move 800 Mbps onto a 100 Mbps link;
  that limitation is the point of the comparison, not an oversight.
* B1 computes once and never again, so a flow whose path contains a failed element stays
  blackholed for the rest of the run.
* Path cost is propagation delay. With uniform delays this degenerates to hop count.
* Reconvergence timing (flooding delay, SPF hold-down) is modelled by the detector, which
  decides when a change becomes visible; these classes react to the view they are given.
"""

from __future__ import annotations

from collections.abc import Sequence

from orbit.algorithms.base import BaseAlgorithm
from orbit.algorithms.paths import LinkCost, latency_cost, route_from_tree, shortest_path_tree
from orbit.events import Event, EventType
from orbit.model import (
    Flow,
    FlowId,
    GraphView,
    LinkId,
    NodeId,
    Route,
    RoutingState,
    placement_links,
)


def _routes_for(view: GraphView, flows: Sequence[Flow], cost: LinkCost) -> dict[FlowId, Route]:
    topology = view.topology
    allowed = lambda link: topology.is_usable(link.id)  # noqa: E731
    by_source: dict[NodeId, dict[NodeId, LinkId]] = {}
    routing: dict[FlowId, Route] = {}

    for flow in sorted(flows, key=lambda item: item.id):
        if flow.src not in by_source:
            _, predecessor = shortest_path_tree(topology, flow.src, cost=cost, allowed=allowed)
            by_source[flow.src] = predecessor
        route = route_from_tree(topology, by_source[flow.src], flow.src, flow.dst)
        if route is not None:
            routing[flow.id] = route
    return routing


class StaticShortestPath(BaseAlgorithm):
    name = "spf-static"

    def __init__(self, cost: LinkCost = latency_cost) -> None:
        super().__init__()
        self._cost = cost
        self._computed: dict[FlowId, Route] | None = None

    def reset(self) -> None:
        super().reset()
        self._computed = None

    def recompute(
        self, view: GraphView, flows: Sequence[Flow], previous: RoutingState
    ) -> RoutingState:
        if self._computed is None:
            self._computed = _routes_for(view, flows, self._cost)
        return self._computed


class ReconvergingShortestPath(BaseAlgorithm):
    name = "spf-reconverge"

    def __init__(self, cost: LinkCost = latency_cost) -> None:
        super().__init__()
        self._cost = cost

    def recompute(
        self, view: GraphView, flows: Sequence[Flow], previous: RoutingState
    ) -> RoutingState:
        routing = _routes_for(view, flows, self._cost)
        for flow_id in sorted(routing):
            before = previous.get(flow_id)
            if before is not None and placement_links(before) != routing[flow_id].links:
                self.emit(
                    Event(
                        view.observed_at_tick,
                        EventType.FLOW_REROUTED,
                        {"flow": flow_id, "via": "RECONVERGENCE"},
                    )
                )
        for flow_id in sorted(previous):
            if flow_id not in routing:
                self.emit(
                    Event(
                        view.observed_at_tick,
                        EventType.FLOW_BLACKHOLED,
                        {"flow": flow_id},
                    )
                )
        return routing
