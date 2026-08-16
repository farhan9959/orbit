"""Failure detection: when a topology change becomes known to the control plane.

This is the fairness-critical component. Every algorithm receives the same detector with
the same parameters, so recovery time is never measured from an instant a baseline could
not have known (docs/05-methodology.md B3).

Assumptions and failure modes:
* Detection latency is modelled, not executed. There is no BFD packet exchange; a change at
  tick t becomes visible at t + delay, rounded up to whole ticks.
* CENTRALISED mode adds a single control-channel delay. DISTRIBUTED mode additionally adds
  flooding delay proportional to hop distance plus an SPF hold-down, which is how OSPF/IS-IS
  back-off is represented.
* Distributed flooding is measured from the changed element to one reference vantage point
  (the lexicographically smallest node), not per-router. The algorithms in this engine are
  centrally computed, so a single vantage is the honest abstraction; per-router convergence
  would require a distributed forwarding model, which docs/01-requirements.md §5 excludes.
* Jitter is drawn from the detector's own seeded stream, never a global RNG.
* The control plane learns any attribute change, not only UP/DOWN, because a bandwidth
  degradation must reach a capacity-aware algorithm the same way a failure does.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from orbit.algorithms.paths import hop_distances
from orbit.errors import ValidationError
from orbit.model import GraphView, Link, LinkId, Node, NodeId, Topology
from orbit.rng import rng_for


class ControlMode(StrEnum):
    CENTRALISED = "CENTRALISED"
    DISTRIBUTED = "DISTRIBUTED"


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    detection_interval_ms: float = 150.0
    jitter_ms: float = 0.0
    control_channel_delay_ms: float = 10.0
    per_hop_flood_delay_ms: float = 20.0
    spf_hold_time_ms: float = 100.0
    mode: ControlMode = ControlMode.CENTRALISED
    seed: int = 0

    def __post_init__(self) -> None:
        for name in (
            "detection_interval_ms",
            "jitter_ms",
            "control_channel_delay_ms",
            "per_hop_flood_delay_ms",
            "spf_hold_time_ms",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0.0:
                raise ValidationError(f"DetectorConfig: {name} must be >= 0, got {value!r}")
        object.__setattr__(self, "mode", ControlMode(self.mode))


class FailureDetector:
    __slots__ = (
        "_believed_links",
        "_believed_nodes",
        "_config",
        "_detected",
        "_hops",
        "_last_truth_links",
        "_last_truth_nodes",
        "_pending",
        "_rng",
        "_tick_ms",
        "_view",
    )

    def __init__(self, topology: Topology, config: DetectorConfig, tick_ms: int) -> None:
        if tick_ms <= 0:
            raise ValidationError(f"FailureDetector: tick_ms must be > 0, got {tick_ms!r}")
        self._config = config
        self._tick_ms = tick_ms
        self._believed_nodes = dict(topology.nodes)
        self._believed_links = dict(topology.links)
        self._last_truth_nodes = dict(topology.nodes)
        self._last_truth_links = dict(topology.links)
        self._pending: list[tuple[int, str, str, Node | Link]] = []
        self._view = GraphView(topology, 0, changed=True)
        self._rng = rng_for(config.seed, "detector")
        reference = next(iter(topology.nodes), None)
        self._hops = hop_distances(topology, reference) if reference is not None else {}
        self._detected: list[tuple[str, str]] = []

    @property
    def config(self) -> DetectorConfig:
        return self._config

    def _delay_ticks(self, origin: NodeId | None) -> int:
        config = self._config
        delay = config.detection_interval_ms
        if config.jitter_ms > 0.0:
            delay += self._rng.uniform(0.0, config.jitter_ms)
        if config.mode is ControlMode.CENTRALISED:
            delay += config.control_channel_delay_ms
        else:
            hops = self._hops.get(origin, 0) if origin is not None else 0
            delay += config.per_hop_flood_delay_ms * hops + config.spf_hold_time_ms
        return max(1, math.ceil(delay / self._tick_ms))

    def observe(self, tick: int, truth: Topology) -> GraphView:
        self._detected.clear()
        for node_id in sorted(truth.nodes):
            node = truth.nodes[node_id]
            if self._last_truth_nodes.get(node_id) != node:
                self._last_truth_nodes[node_id] = node
                self._pending.append((tick + self._delay_ticks(node_id), "node", node_id, node))
        for link_id in sorted(truth.links):
            link = truth.links[link_id]
            if self._last_truth_links.get(link_id) != link:
                self._last_truth_links[link_id] = link
                self._pending.append((tick + self._delay_ticks(link.src), "link", link_id, link))

        due = [entry for entry in self._pending if entry[0] <= tick]
        if due:
            self._pending = [entry for entry in self._pending if entry[0] > tick]
            for _, kind, element_id, element in sorted(due, key=lambda item: (item[0], item[2])):
                if kind == "node":
                    self._believed_nodes[NodeId(element_id)] = element  # type: ignore[assignment]
                else:
                    self._believed_links[LinkId(element_id)] = element  # type: ignore[assignment]
                self._detected.append((kind, element_id))
            believed = Topology(self._believed_nodes.values(), self._believed_links.values())
            self._view = GraphView(believed, tick, changed=True)
        elif self._view.changed or self._view.observed_at_tick != tick:
            self._view = GraphView(self._view.topology, tick, changed=False)
        return self._view

    @property
    def detected_this_tick(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._detected)

    def pending_count(self) -> int:
        return len(self._pending)


def detector_for(
    topology: Topology, config: DetectorConfig | None, tick_ms: int
) -> FailureDetector:
    return FailureDetector(topology, config or DetectorConfig(), tick_ms)


def elements_of(topology: Topology) -> Iterable[str]:
    yield from topology.nodes
    yield from topology.links
