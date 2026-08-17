"""Failure injection (requirement F12-F14) and targeted element selection.

Assumptions and failure modes:
* The schedule is a pure function of (initial topology, tick): applying it twice gives the
  same result, so a run is replayable and I-NOCREATE holds — the controller never mutates
  the world, only this module does.
* Failures are cumulative until an explicit RESTORE. Restoring an element returns it to its
  state in the *initial* topology, so a degrade followed by a restore recovers full
  capacity without the caller tracking prior values.
* CONGESTION_SURGE scales demand rather than changing the topology; it returns a per-flow
  multiplier that the tick loop applies.
* CASCADE is stateful across ticks: it counts consecutive ticks above the utilisation
  threshold and fails the link once the dwell time is exceeded. Cascade depth is counted.
* Selection is deterministic. Random selection draws from a named seeded stream; targeted
  selection breaks ties on element id.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from orbit.algorithms.paths import shortest_path_tree
from orbit.errors import ValidationError
from orbit.model import Link, LinkId, LinkState, NodeId, NodeState, Topology
from orbit.rng import rng_for


class FailureKind(StrEnum):
    NODE_DOWN = "NODE_DOWN"
    LINK_DOWN = "LINK_DOWN"
    SRLG_DOWN = "SRLG_DOWN"
    BANDWIDTH_DEGRADE = "BANDWIDTH_DEGRADE"
    LATENCY_SPIKE = "LATENCY_SPIKE"
    LOSS_SPIKE = "LOSS_SPIKE"
    CONGESTION_SURGE = "CONGESTION_SURGE"
    RESTORE = "RESTORE"


@dataclass(frozen=True, slots=True)
class FailureEvent:
    at_s: float
    kind: FailureKind
    targets: tuple[str, ...] = ()
    factor: float = 1.0
    delta_ms: float = 0.0
    loss_rate: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", FailureKind(self.kind))
        object.__setattr__(self, "targets", tuple(self.targets))
        if self.at_s < 0.0:
            raise ValidationError(f"FailureEvent: at_s must be >= 0, got {self.at_s!r}")
        if self.kind is FailureKind.BANDWIDTH_DEGRADE and not 0.0 <= self.factor <= 1.0:
            raise ValidationError(
                f"FailureEvent: BANDWIDTH_DEGRADE factor must be in [0, 1], got {self.factor!r}"
            )
        if self.kind is FailureKind.LOSS_SPIKE and not 0.0 <= self.loss_rate <= 1.0:
            raise ValidationError(
                f"FailureEvent: LOSS_SPIKE loss_rate must be in [0, 1], got {self.loss_rate!r}"
            )
        if self.kind is FailureKind.CONGESTION_SURGE and self.factor < 0.0:
            raise ValidationError(
                f"FailureEvent: CONGESTION_SURGE factor must be >= 0, got {self.factor!r}"
            )


@dataclass(frozen=True, slots=True)
class CascadeRule:
    utilisation_threshold: float = 0.95
    dwell_ticks: int = 3
    max_failures: int = 200
    enabled: bool = False

    def __post_init__(self) -> None:
        if not 0.0 < self.utilisation_threshold <= 1.0:
            raise ValidationError(
                f"CascadeRule: utilisation_threshold must be in (0, 1], "
                f"got {self.utilisation_threshold!r}"
            )
        if self.dwell_ticks < 1:
            raise ValidationError(
                f"CascadeRule: dwell_ticks must be >= 1, got {self.dwell_ticks!r}"
            )


@dataclass
class _Mutation:
    nodes: dict[NodeId, NodeState] = field(default_factory=dict)
    link_state: dict[LinkId, LinkState] = field(default_factory=dict)
    degrade: dict[LinkId, float] = field(default_factory=dict)
    delay: dict[LinkId, float] = field(default_factory=dict)
    loss: dict[LinkId, float] = field(default_factory=dict)

    def clear_element(self, element_id: str) -> None:
        self.nodes.pop(NodeId(element_id), None)
        self.link_state.pop(LinkId(element_id), None)
        self.degrade.pop(LinkId(element_id), None)
        self.delay.pop(LinkId(element_id), None)
        self.loss.pop(LinkId(element_id), None)


class FailureSchedule:
    __slots__ = (
        "_applied",
        "_base",
        "_cascade",
        "_cascade_dwell",
        "_cascade_failed",
        "_events",
        "_last_tick",
        "_state",
        "_surge",
    )

    def __init__(
        self,
        topology: Topology,
        events: Iterable[FailureEvent] = (),
        cascade: CascadeRule | None = None,
    ) -> None:
        self._base = topology
        self._events = tuple(sorted(events, key=lambda e: (e.at_s, e.kind, e.targets)))
        for event in self._events:
            self._validate_targets(event)
        self._cascade = cascade or CascadeRule()
        self._state = _Mutation()
        self._applied: set[int] = set()
        self._cascade_dwell: dict[LinkId, int] = {}
        self._cascade_failed: list[LinkId] = []
        self._surge = 1.0
        self._last_tick = -1

    def _validate_targets(self, event: FailureEvent) -> None:
        if event.kind in (FailureKind.SRLG_DOWN, FailureKind.CONGESTION_SURGE):
            return
        for target in event.targets:
            if target in self._base.nodes or target in self._base.links:
                continue
            raise ValidationError(f"FailureEvent({event.kind}): unknown target {target!r}")

    @property
    def events(self) -> tuple[FailureEvent, ...]:
        return self._events

    @property
    def demand_scale(self) -> float:
        return self._surge

    @property
    def cascade_depth(self) -> int:
        return len(self._cascade_failed)

    def reset(self) -> None:
        self._state = _Mutation()
        self._applied.clear()
        self._cascade_dwell.clear()
        self._cascade_failed.clear()
        self._surge = 1.0
        self._last_tick = -1

    def _srlg_members(self, tag: str) -> tuple[list[NodeId], list[LinkId]]:
        nodes = [n for n in sorted(self._base.nodes) if tag in self._base.nodes[n].srlg]
        links = [e for e in sorted(self._base.links) if tag in self._base.links[e].srlg]
        return nodes, links

    def _apply_event(self, event: FailureEvent) -> None:
        state = self._state
        if event.kind is FailureKind.NODE_DOWN:
            for target in event.targets:
                state.nodes[NodeId(target)] = NodeState.DOWN
        elif event.kind is FailureKind.LINK_DOWN:
            for target in event.targets:
                state.link_state[LinkId(target)] = LinkState.DOWN
        elif event.kind is FailureKind.SRLG_DOWN:
            for tag in event.targets:
                nodes, links = self._srlg_members(tag)
                for node_id in nodes:
                    state.nodes[node_id] = NodeState.DOWN
                for link_id in links:
                    state.link_state[link_id] = LinkState.DOWN
        elif event.kind is FailureKind.BANDWIDTH_DEGRADE:
            for target in event.targets:
                state.link_state[LinkId(target)] = LinkState.DEGRADED
                state.degrade[LinkId(target)] = event.factor
        elif event.kind is FailureKind.LATENCY_SPIKE:
            for target in event.targets:
                state.delay[LinkId(target)] = event.delta_ms
        elif event.kind is FailureKind.LOSS_SPIKE:
            for target in event.targets:
                state.loss[LinkId(target)] = event.loss_rate
        elif event.kind is FailureKind.CONGESTION_SURGE:
            self._surge = event.factor
        elif event.kind is FailureKind.RESTORE:
            if not event.targets:
                self._state = _Mutation()
                self._surge = 1.0
            for target in event.targets:
                state.clear_element(target)

    def _materialise(self) -> Topology:
        state = self._state
        nodes = [
            replace(node, state=state.nodes[node_id]) if node_id in state.nodes else node
            for node_id, node in self._base.nodes.items()
        ]
        links: list[Link] = []
        for link_id, link in self._base.links.items():
            changes: dict[str, object] = {}
            if link_id in state.link_state:
                changes["state"] = state.link_state[link_id]
            if link_id in state.degrade:
                changes["degrade_factor"] = state.degrade[link_id]
            if link_id in state.delay:
                changes["prop_delay_ms"] = link.prop_delay_ms + state.delay[link_id]
            if link_id in state.loss:
                changes["loss_rate"] = state.loss[link_id]
            links.append(replace(link, **changes) if changes else link)  # type: ignore[arg-type]
        return Topology(nodes, links)

    def apply(self, tick: int, time_s: float) -> tuple[Topology, tuple[FailureEvent, ...]]:
        fired: list[FailureEvent] = []
        for index, event in enumerate(self._events):
            if index in self._applied or event.at_s > time_s:
                continue
            self._applied.add(index)
            self._apply_event(event)
            fired.append(event)
        self._last_tick = tick
        return self._materialise(), tuple(fired)

    def observe_utilisation(
        self, tick: int, topology: Topology, link_load: Mapping[LinkId, float]
    ) -> tuple[LinkId, ...]:
        rule = self._cascade
        if not rule.enabled or len(self._cascade_failed) >= rule.max_failures:
            return ()
        newly_failed: list[LinkId] = []
        for link_id in sorted(topology.links):
            if self._state.link_state.get(link_id) is LinkState.DOWN:
                continue
            capacity = topology.link(link_id).effective_capacity_mbps
            if capacity <= 0.0:
                continue
            utilisation = link_load.get(link_id, 0.0) / capacity
            if utilisation >= rule.utilisation_threshold:
                self._cascade_dwell[link_id] = self._cascade_dwell.get(link_id, 0) + 1
            else:
                self._cascade_dwell[link_id] = 0
            if self._cascade_dwell[link_id] >= rule.dwell_ticks:
                if len(self._cascade_failed) + len(newly_failed) >= rule.max_failures:
                    break
                self._state.link_state[link_id] = LinkState.DOWN
                self._cascade_dwell[link_id] = 0
                newly_failed.append(link_id)
        self._cascade_failed.extend(newly_failed)
        return tuple(newly_failed)


def link_betweenness(topology: Topology) -> dict[LinkId, float]:
    counts: dict[LinkId, float] = {link_id: 0.0 for link_id in topology.links}
    allowed = lambda link: topology.is_usable(link.id)  # noqa: E731
    for source in topology.nodes:
        _, predecessor = shortest_path_tree(topology, source, allowed=allowed)
        for target in topology.nodes:
            if target == source:
                continue
            node = target
            guard = 0
            while node != source and guard <= len(topology.nodes):
                link_id = predecessor.get(node)
                if link_id is None:
                    break
                counts[link_id] += 1.0
                node = topology.link(link_id).src
                guard += 1
    return counts


def node_betweenness(topology: Topology) -> dict[NodeId, float]:
    counts: dict[NodeId, float] = {node_id: 0.0 for node_id in topology.nodes}
    for link_id, score in link_betweenness(topology).items():
        counts[topology.link(link_id).src] += score
    return counts


def highest_betweenness_links(topology: Topology, count: int) -> tuple[LinkId, ...]:
    scores = link_betweenness(topology)
    ranked = sorted(scores, key=lambda link_id: (-scores[link_id], link_id))
    return tuple(ranked[:count])


def highest_betweenness_nodes(topology: Topology, count: int) -> tuple[NodeId, ...]:
    scores = node_betweenness(topology)
    ranked = sorted(scores, key=lambda node_id: (-scores[node_id], node_id))
    return tuple(ranked[:count])


def random_nodes(topology: Topology, fraction: float, seed: int) -> tuple[NodeId, ...]:
    return tuple(
        NodeId(item) for item in _sample(sorted(topology.nodes), fraction, seed, "failure.nodes")
    )


def random_links(topology: Topology, fraction: float, seed: int) -> tuple[LinkId, ...]:
    return tuple(
        LinkId(item) for item in _sample(sorted(topology.links), fraction, seed, "failure.links")
    )


def _sample(population: Sequence[str], fraction: float, seed: int, name: str) -> list[str]:
    if not 0.0 <= fraction <= 1.0:
        raise ValidationError(f"{name}: fraction must be in [0, 1], got {fraction!r}")
    count = round(len(population) * fraction)
    if count <= 0:
        return []
    return sorted(rng_for(seed, name).sample(list(population), min(count, len(population))))
