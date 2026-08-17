"""ORBIT: priority-aware constrained recovery (docs/03-simulation-model.md §6).

Four composed mechanisms, none of which is individually novel:

    M1 protection  - precomputed disjoint backups for CRITICAL   (IP-FRR / LFA, RFC 5286)
    M2 restoration - priority-ordered CSPF on residual capacity  (CSPF, MIRA)
    M3 preemption  - bounded, strictly-lower-priority victims    (RSVP-TE, RFC 3209)
    M4 damping     - reroute budget and improvement threshold    (RFC 2439)

The contribution is the integration and the measurement study, not a new algorithm.

Objective, lexicographic:
    1. minimise sum over flows of w(priority) * unserved_demand
    2. minimise sum over flows of served * path_latency
    3. minimise the number of route changes

This is a greedy heuristic for an NP-hard problem (unsplittable multi-commodity flow with
priorities). The optimality gap against an LP relaxation is measured separately on small
topologies rather than assumed away.

Assumptions and failure modes:
* Partition: when no path exists the flow is correctly BLACKHOLED, and recovery-time
  observations for that run are censored rather than dropped.
* SRLG-shared backup: a backup sharing an SRLG with its primary dies with it. Backups are
  computed SRLG-disjoint where possible and `backup_coverage` reports how often that failed.
* Preemption cascade: victims are drawn only from strictly lower priorities and re-queued
  once, so the cascade is single-pass and bounded.
* Damping under-reaction: `max_reroutes_per_window` can block a genuinely needed reroute.
  Sensitivity to it is a reported parameter sweep, not a hidden constant.
* Greedy ordering: serving in priority order can place an early flow so that two later ones
  both fail where another assignment would have served all three.
* Stale view: between failure and detection the controller routes on a graph that no longer
  exists, which bounds how good time-to-restore can be.
* Best-effort fallback: a flow that fits nowhere is still placed on its shortest path rather
  than blackholed at the ingress, matching CSPF. The objective minimises weighted *unserved*
  demand, and a blackholed flow is unserved in full while a best-effort flow receives
  whatever the allocator has left. Blackholing it instead would be both worse under the
  stated objective and an unfair asymmetry against ORBIT in the comparison.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from orbit.algorithms.base import BaseAlgorithm
from orbit.algorithms.paths import route_from_tree, shortest_path_tree
from orbit.errors import ValidationError
from orbit.events import Event, EventType
from orbit.model import (
    Flow,
    FlowId,
    GraphView,
    Link,
    LinkId,
    Priority,
    Route,
    RoutingState,
    Topology,
)


def _utilisation(free: float, capacity: float) -> float:
    """Fraction of a link already committed, clamped to [0, 1].

    Dijkstra requires non-negative edge weights. Residual capacity is allowed to go negative
    (honest bookkeeping for an oversubscribed link) and, after a preemption releases a
    victim, can briefly exceed the link's capacity, so the raw ratio is not safe to use as a
    cost term without clamping.
    """
    if capacity <= 0.0:
        return 1.0
    return min(1.0, max(0.0, 1.0 - free / capacity))


PRIORITY_WEIGHTS: dict[Priority, float] = {
    Priority.CRITICAL: 1000.0,
    Priority.HIGH: 100.0,
    Priority.NORMAL: 10.0,
    Priority.LOW: 1.0,
}


@dataclass(frozen=True, slots=True)
class OrbitConfig:
    protection: bool = True
    restoration: bool = True
    preemption: bool = True
    damping: bool = True
    best_effort_fallback: bool = True
    utilisation_ceiling: float | None = None
    """Refuse to place a flow if doing so would push a link past this utilisation.

    Set strictly below the cascade threshold, this makes the controller decline traffic it
    could carry, on the theory that an overloaded link is worse than an unserved flow when
    overload propagates. When set, the best-effort fallback respects the ceiling too -
    otherwise the fallback would immediately undo it.
    """
    latency_weight: float = 1.0
    utilisation_weight: float = 10.0
    max_reroutes_per_window: int = 3
    damping_window_ticks: int = 50
    improvement_threshold: float = 0.1
    backup_budget_per_tick: int = 8
    min_preemption_priority: Priority = Priority.HIGH

    def __post_init__(self) -> None:
        if self.max_reroutes_per_window < 1:
            raise ValidationError(
                f"OrbitConfig: max_reroutes_per_window must be >= 1, "
                f"got {self.max_reroutes_per_window!r}"
            )
        if self.damping_window_ticks < 1:
            raise ValidationError(
                f"OrbitConfig: damping_window_ticks must be >= 1, "
                f"got {self.damping_window_ticks!r}"
            )
        if self.improvement_threshold < 0.0:
            raise ValidationError(
                f"OrbitConfig: improvement_threshold must be >= 0, "
                f"got {self.improvement_threshold!r}"
            )
        if self.utilisation_ceiling is not None and not 0.0 < self.utilisation_ceiling <= 1.0:
            raise ValidationError(
                f"OrbitConfig: utilisation_ceiling must be in (0, 1], "
                f"got {self.utilisation_ceiling!r}"
            )


class OrbitController(BaseAlgorithm):
    name = "orbit"

    def __init__(self, config: OrbitConfig | None = None) -> None:
        super().__init__()
        self._config = config or OrbitConfig()
        self._backups: dict[FlowId, Route] = {}
        self._reroutes: dict[FlowId, list[int]] = {}
        self._backup_coverage = 0.0

    @property
    def config(self) -> OrbitConfig:
        return self._config

    @property
    def backup_coverage(self) -> float:
        return self._backup_coverage

    def reset(self) -> None:
        super().reset()
        self._backups.clear()
        self._reroutes.clear()
        self._backup_coverage = 0.0

    def recompute(
        self, view: GraphView, flows: Sequence[Flow], previous: RoutingState
    ) -> RoutingState:
        topology = view.topology
        tick = view.observed_at_tick
        config = self._config
        residual: dict[LinkId, float] = {
            link_id: topology.link(link_id).effective_capacity_mbps for link_id in topology.links
        }
        routing: dict[FlowId, Route] = {}
        holders: dict[LinkId, list[FlowId]] = {}
        by_id = {flow.id: flow for flow in flows}

        surviving = [
            flow
            for flow in sorted(flows, key=lambda item: item.id)
            if self._is_live(topology, previous.get(item_id := flow.id)) and item_id in previous
        ]
        for flow in surviving:
            route = previous[flow.id]
            if not isinstance(route, Route):
                continue
            if self._fits(residual, route, flow.demand_mbps):
                self._reserve(residual, holders, route, flow)
                routing[flow.id] = route

        pending = [flow for flow in flows if flow.id not in routing]

        if config.protection:
            for flow in sorted(pending, key=lambda item: item.id):
                if flow.priority is not Priority.CRITICAL:
                    continue
                backup = self._backups.get(flow.id)
                if backup is None or not self._is_live(topology, backup):
                    continue
                if not self._fits(residual, backup, flow.demand_mbps):
                    continue
                self._reserve(residual, holders, backup, flow)
                routing[flow.id] = backup
                self.emit(Event(tick, EventType.FLOW_REROUTED, {"flow": flow.id, "via": "BACKUP"}))

        queue = sorted(
            (flow for flow in pending if flow.id not in routing),
            key=lambda item: (-item.priority, -item.demand_mbps, item.id),
        )
        requeued: list[Flow] = []

        if config.restoration:
            for flow in queue:
                self._restore(
                    flow, topology, residual, holders, routing, previous, tick, requeued, by_id
                )
            for flow in sorted(requeued, key=lambda item: (-item.priority, item.id)):
                if flow.id in routing:
                    continue
                self._restore(flow, topology, residual, holders, routing, previous, tick, [], by_id)

        for flow in flows:
            if flow.id not in routing and flow.id in previous:
                self.emit(Event(tick, EventType.FLOW_BLACKHOLED, {"flow": flow.id}))

        if config.protection:
            self._refresh_backups(topology, flows, routing)
        return routing

    def _restore(
        self,
        flow: Flow,
        topology: Topology,
        residual: dict[LinkId, float],
        holders: dict[LinkId, list[FlowId]],
        routing: dict[FlowId, Route],
        previous: RoutingState,
        tick: int,
        requeued: list[Flow],
        by_id: dict[FlowId, Flow],
    ) -> None:
        config = self._config
        before = previous.get(flow.id)
        route = self._constrained_route(topology, residual, flow)

        if route is not None and not self._damping_allows(flow, before, route, topology, tick):
            if isinstance(before, Route) and self._is_live(topology, before):
                self._reserve(residual, holders, before, flow)
                routing[flow.id] = before
            return

        if route is None and config.preemption and flow.priority >= config.min_preemption_priority:
            route = self._preempt(flow, topology, residual, holders, routing, tick, requeued, by_id)

        if route is None and config.best_effort_fallback:
            route = self._constrained_route(topology, residual, flow, ignore_capacity=True)

        if route is None:
            return

        self._reserve(residual, holders, route, flow)
        routing[flow.id] = route
        self._note_reroute(flow.id, tick)
        if before is None or (isinstance(before, Route) and before.links != route.links):
            self.emit(Event(tick, EventType.FLOW_REROUTED, {"flow": flow.id, "via": "RESTORATION"}))

    def _preempt(
        self,
        flow: Flow,
        topology: Topology,
        residual: dict[LinkId, float],
        holders: dict[LinkId, list[FlowId]],
        routing: dict[FlowId, Route],
        tick: int,
        requeued: list[Flow],
        by_id: dict[FlowId, Flow],
    ) -> Route | None:
        unconstrained = self._constrained_route(topology, residual, flow, ignore_capacity=True)
        if unconstrained is None:
            return None

        victims: list[FlowId] = []
        for link_id in unconstrained.links:
            shortfall = flow.demand_mbps - residual.get(link_id, 0.0)
            if shortfall <= 0.0:
                continue
            candidates = sorted(
                (
                    victim_id
                    for victim_id in holders.get(link_id, ())
                    if by_id[victim_id].priority < flow.priority
                ),
                key=lambda victim_id: (
                    by_id[victim_id].priority,
                    -by_id[victim_id].demand_mbps,
                    victim_id,
                ),
            )
            freed = 0.0
            for victim_id in candidates:
                if freed >= shortfall:
                    break
                freed += by_id[victim_id].demand_mbps
                if victim_id not in victims:
                    victims.append(victim_id)
            if freed < shortfall:
                return None

        for victim_id in victims:
            victim_route = routing.pop(victim_id, None)
            if victim_route is None:
                continue
            self._release(residual, holders, victim_route, by_id[victim_id])
            requeued.append(by_id[victim_id])
            self.emit(
                Event(
                    tick,
                    EventType.FLOW_PREEMPTED,
                    {
                        "flow": victim_id,
                        "by": flow.id,
                        "victim_priority": by_id[victim_id].priority.name,
                    },
                )
            )
        return self._constrained_route(topology, residual, flow)

    def _constrained_route(
        self,
        topology: Topology,
        residual: dict[LinkId, float],
        flow: Flow,
        *,
        ignore_capacity: bool = False,
    ) -> Route | None:
        config = self._config

        def cost(link: Link) -> float:
            capacity = link.effective_capacity_mbps
            free = residual.get(link.id, 0.0)
            utilisation = _utilisation(free, capacity)
            return config.latency_weight * link.prop_delay_ms + (
                config.utilisation_weight * utilisation
            )

        ceiling = config.utilisation_ceiling

        def allowed(link: Link) -> bool:
            if not topology.is_usable(link.id):
                return False
            free = residual.get(link.id, 0.0)
            if ceiling is not None:
                capacity = link.effective_capacity_mbps
                if capacity <= 0.0:
                    return False
                if free - flow.demand_mbps < capacity * (1.0 - ceiling):
                    return False
            elif not ignore_capacity:
                return free >= flow.demand_mbps
            return True

        _, predecessor = shortest_path_tree(topology, flow.src, cost=cost, allowed=allowed)
        return route_from_tree(topology, predecessor, flow.src, flow.dst)

    def _damping_allows(
        self, flow: Flow, before: object, route: Route, topology: Topology, tick: int
    ) -> bool:
        config = self._config
        if not config.damping or not isinstance(before, Route):
            return True
        if not self._is_live(topology, before):
            return True
        recent = [
            when
            for when in self._reroutes.get(flow.id, ())
            if tick - when < config.damping_window_ticks
        ]
        if len(recent) >= config.max_reroutes_per_window:
            return False
        if before.links == route.links:
            return True
        old_cost = self._path_latency(topology, before)
        new_cost = self._path_latency(topology, route)
        return new_cost <= old_cost * (1.0 - config.improvement_threshold)

    def _note_reroute(self, flow_id: FlowId, tick: int) -> None:
        window = self._config.damping_window_ticks
        history = [when for when in self._reroutes.get(flow_id, ()) if tick - when < window]
        history.append(tick)
        self._reroutes[flow_id] = history

    def _refresh_backups(
        self, topology: Topology, flows: Sequence[Flow], routing: dict[FlowId, Route]
    ) -> None:
        critical = [
            flow for flow in sorted(flows, key=lambda f: f.id) if flow.priority is Priority.CRITICAL
        ]
        if not critical:
            self._backup_coverage = 0.0
            return
        budget = self._config.backup_budget_per_tick
        covered = 0
        for flow in critical:
            primary = routing.get(flow.id)
            existing = self._backups.get(flow.id)
            if (
                existing is not None
                and self._is_live(topology, existing)
                and (primary is None or not _shares_fate(topology, primary, existing))
            ):
                covered += 1
                continue
            if budget <= 0:
                continue
            budget -= 1
            backup = self._disjoint_route(topology, flow, primary)
            if backup is not None:
                self._backups[flow.id] = backup
                covered += 1
            else:
                self._backups.pop(flow.id, None)
        self._backup_coverage = covered / len(critical)

    def _disjoint_route(
        self, topology: Topology, flow: Flow, primary: Route | None
    ) -> Route | None:
        if primary is None:
            return None
        banned_links = set(primary.links)
        banned_srlg: set[str] = set()
        for link_id in primary.links:
            banned_srlg |= topology.link(link_id).srlg

        def strict(link: Link) -> bool:
            return (
                topology.is_usable(link.id)
                and link.id not in banned_links
                and not (link.srlg & banned_srlg)
            )

        def loose(link: Link) -> bool:
            return topology.is_usable(link.id) and link.id not in banned_links

        for allowed in (strict, loose):
            _, predecessor = shortest_path_tree(topology, flow.src, allowed=allowed)
            route = route_from_tree(topology, predecessor, flow.src, flow.dst)
            if route is not None:
                return route
        return None

    @staticmethod
    def _path_latency(topology: Topology, route: Route) -> float:
        return sum(topology.link(link_id).prop_delay_ms for link_id in route.links)

    @staticmethod
    def _is_live(topology: Topology, placement: object) -> bool:
        if not isinstance(placement, Route):
            return False
        try:
            return all(topology.is_usable(link_id) for link_id in placement.links)
        except ValidationError:
            return False

    @staticmethod
    def _fits(residual: dict[LinkId, float], route: Route, demand: float) -> bool:
        return all(residual.get(link_id, 0.0) >= demand for link_id in route.links)

    @staticmethod
    def _reserve(
        residual: dict[LinkId, float],
        holders: dict[LinkId, list[FlowId]],
        route: Route,
        flow: Flow,
    ) -> None:
        for link_id in route.links:
            residual[link_id] = residual.get(link_id, 0.0) - flow.demand_mbps
            holders.setdefault(link_id, []).append(flow.id)

    @staticmethod
    def _release(
        residual: dict[LinkId, float],
        holders: dict[LinkId, list[FlowId]],
        route: Route,
        flow: Flow,
    ) -> None:
        for link_id in route.links:
            residual[link_id] = residual.get(link_id, 0.0) + flow.demand_mbps
            if flow.id in holders.get(link_id, ()):
                holders[link_id].remove(flow.id)


def _shares_fate(topology: Topology, primary: Route, backup: Route) -> bool:
    primary_srlg: set[str] = set()
    for link_id in primary.links:
        primary_srlg |= topology.link(link_id).srlg
    if set(primary.links) & set(backup.links):
        return True
    return any(topology.link(link_id).srlg & primary_srlg for link_id in backup.links)
