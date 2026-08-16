"""Baseline B3: equal-cost multi-path (RFC 2992).

Assumptions and failure modes:
* The split is equal across all equal-cost paths regardless of residual capacity, which is
  the defining limitation of ECMP and the reason B4 exists.
* Splitting is per-flow-share, not per-packet. Real ECMP hashes flows onto paths; modelling
  a fractional split is the standard flow-level approximation and it flatters ECMP slightly,
  which is the safe direction for a baseline.
* Benefit depends entirely on whether equal-cost paths exist, so results are reported per
  topology family rather than pooled.
* The number of paths per flow is capped; beyond the cap the split is over the first paths
  in deterministic order.
"""

from __future__ import annotations

from collections.abc import Sequence

from orbit.algorithms.base import BaseAlgorithm
from orbit.algorithms.paths import LinkCost, equal_cost_routes, latency_cost
from orbit.events import Event, EventType
from orbit.model import Flow, FlowId, GraphView, LinkId, NodeId, PathSet, Placement, RoutingState


class EqualCostMultiPath(BaseAlgorithm):
    name = "ecmp"

    def __init__(self, cost: LinkCost = latency_cost, max_paths: int = 8) -> None:
        super().__init__()
        self._cost = cost
        self._max_paths = max_paths

    def recompute(
        self, view: GraphView, flows: Sequence[Flow], previous: RoutingState
    ) -> RoutingState:
        topology = view.topology
        allowed = lambda link: topology.is_usable(link.id)  # noqa: E731
        routing: dict[FlowId, Placement] = {}
        cache: dict[tuple[NodeId, NodeId], PathSet | None] = {}

        for flow in sorted(flows, key=lambda item: item.id):
            key = (flow.src, flow.dst)
            if key not in cache:
                routes = equal_cost_routes(
                    topology,
                    flow.src,
                    flow.dst,
                    cost=self._cost,
                    allowed=allowed,
                    limit=self._max_paths,
                )
                cache[key] = PathSet.equal_split(routes) if routes else None
            placement = cache[key]
            if placement is None:
                if flow.id in previous:
                    self.emit(
                        Event(
                            view.observed_at_tick,
                            EventType.FLOW_BLACKHOLED,
                            {"flow": flow.id},
                        )
                    )
                continue
            before = previous.get(flow.id)
            if before is not None and _links_of(before) != _links_of(placement):
                self.emit(
                    Event(
                        view.observed_at_tick,
                        EventType.FLOW_REROUTED,
                        {"flow": flow.id, "via": "ECMP"},
                    )
                )
            routing[flow.id] = placement
        return routing


def _links_of(placement: Placement) -> tuple[tuple[LinkId, ...], ...]:
    if isinstance(placement, PathSet):
        return tuple(route.links for route in placement.routes)
    return (placement.links,)
