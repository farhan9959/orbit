"""Experiment specification: the declarative description of a benchmark cell.

Assumptions and failure modes:
* A spec is data. Nothing in it is ever executed, interpreted as a path, or deserialised
  with anything other than `yaml.safe_load` equivalents (docs/04-threat-model.md T4).
* Bounds are enforced here because a spec is user-supplied even in Tier A, where the CLI is
  the only caller.
* `seed_for` is the pairing discipline: every algorithm in a cell gets the identical seed,
  so all of them face a bit-identical world (docs/05-methodology.md B2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from orbit.detect import ControlMode, DetectorConfig
from orbit.engine import CascadeRule, FailureEvent, FailureKind, FailureSchedule
from orbit.errors import ValidationError
from orbit.generators import barabasi_albert, grid, ring, waxman
from orbit.model import Flow, FlowId, Priority, Topology
from orbit.rng import derive_seed, rng_for

MAX_NODES = 500
MAX_FLOWS = 2000
MAX_TICKS = 20000
MAX_TRIALS = 50


class TopologyFamily(StrEnum):
    GRID = "grid"
    RING = "ring"
    WAXMAN = "waxman"
    SCALE_FREE = "scale_free"


class FailureScenario(StrEnum):
    NONE = "none"
    RANDOM_NODE_10 = "random_node_10"
    RANDOM_NODE_30 = "random_node_30"
    RANDOM_NODE_50 = "random_node_50"
    CRITICAL_LINK = "critical_link"
    REGIONAL_SRLG = "regional_srlg"
    CONGESTION_SURGE = "congestion_surge"
    CASCADING = "cascading"


PRIORITY_MIX: tuple[tuple[Priority, float], ...] = (
    (Priority.CRITICAL, 0.15),
    (Priority.HIGH, 0.25),
    (Priority.NORMAL, 0.35),
    (Priority.LOW, 0.25),
)


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    family: TopologyFamily = TopologyFamily.WAXMAN
    nodes: int = 100
    offered_load: float = 0.7
    flows: int = 200
    failure: FailureScenario = FailureScenario.CRITICAL_LINK
    failure_at_s: float = 2.0
    ticks: int = 200
    control_mode: ControlMode = ControlMode.CENTRALISED
    link_capacity_mbps: float = 100.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", TopologyFamily(self.family))
        object.__setattr__(self, "failure", FailureScenario(self.failure))
        object.__setattr__(self, "control_mode", ControlMode(self.control_mode))
        if not 2 <= self.nodes <= MAX_NODES:
            raise ValidationError(f"ScenarioSpec: nodes must be in [2, {MAX_NODES}]")
        if not 0 < self.flows <= MAX_FLOWS:
            raise ValidationError(f"ScenarioSpec: flows must be in (0, {MAX_FLOWS}]")
        if not 0 < self.ticks <= MAX_TICKS:
            raise ValidationError(f"ScenarioSpec: ticks must be in (0, {MAX_TICKS}]")
        if not 0.0 < self.offered_load <= 5.0:
            raise ValidationError("ScenarioSpec: offered_load must be in (0, 5]")

    @property
    def id(self) -> str:
        return (
            f"{self.family.value}-n{self.nodes}-load{self.offered_load}"
            f"-{self.failure.value}-{self.control_mode.value.lower()}"
        )

    def seed_for(self, trial: int) -> int:
        return derive_seed(trial, self.id)


def build_topology(spec: ScenarioSpec, seed: int) -> Topology:
    capacity = spec.link_capacity_mbps
    if spec.family is TopologyFamily.GRID:
        side = max(2, round(spec.nodes**0.5))
        return grid(side, side, capacity_mbps=capacity)
    if spec.family is TopologyFamily.RING:
        return ring(spec.nodes, capacity_mbps=capacity)
    if spec.family is TopologyFamily.SCALE_FREE:
        return barabasi_albert(spec.nodes, seed=seed, capacity_mbps=capacity)
    return waxman(spec.nodes, seed=seed, capacity_mbps=capacity)


def mean_path_hops(topology: Topology, samples: int = 8) -> float:
    from orbit.algorithms import hop_distances

    ids = sorted(topology.nodes)
    if len(ids) < 2:
        return 1.0
    step = max(1, len(ids) // samples)
    totals: list[int] = []
    for source in ids[::step][:samples]:
        distances = hop_distances(topology, source)
        totals.extend(value for node, value in distances.items() if node != source)
    return max(1.0, sum(totals) / len(totals)) if totals else 1.0


def build_traffic(spec: ScenarioSpec, topology: Topology, seed: int) -> tuple[Flow, ...]:
    """Traffic sized so that `offered_load` is the fraction of network capacity requested.

    A flow of rate r crossing h hops consumes r*h of link capacity, so the feasible total
    demand is (total capacity / mean hops). Sizing against that makes offered_load 0.7 mean
    "ask for 70% of what the network can carry" rather than an arbitrary constant.
    """
    rng = rng_for(seed, "traffic")
    ids = sorted(topology.nodes)
    if len(ids) < 2:
        return ()

    total_capacity = sum(
        topology.link(link_id).effective_capacity_mbps for link_id in topology.links
    )
    hops = mean_path_hops(topology)
    total_demand = spec.offered_load * total_capacity / hops
    per_flow = total_demand / max(1, spec.flows)

    classes: list[Priority] = []
    for priority, share in PRIORITY_MIX:
        classes.extend([priority] * max(1, round(spec.flows * share)))
    while len(classes) < spec.flows:
        classes.append(Priority.NORMAL)

    flows: list[Flow] = []
    for index in range(spec.flows):
        src, dst = rng.sample(ids, 2)
        flows.append(
            Flow(
                FlowId(f"f{index:05d}"),
                src,
                dst,
                demand_mbps=per_flow * rng.uniform(0.5, 1.5),
                priority=classes[index],
            )
        )
    return tuple(flows)


def build_schedule(spec: ScenarioSpec, topology: Topology, seed: int) -> FailureSchedule:
    from orbit.engine import highest_betweenness_links, random_nodes

    events: list[FailureEvent] = []
    cascade = CascadeRule()
    at = spec.failure_at_s

    if spec.failure is FailureScenario.CRITICAL_LINK:
        events.append(
            FailureEvent(at, FailureKind.LINK_DOWN, highest_betweenness_links(topology, 1))
        )
    elif spec.failure in (
        FailureScenario.RANDOM_NODE_10,
        FailureScenario.RANDOM_NODE_30,
        FailureScenario.RANDOM_NODE_50,
    ):
        fraction = {"random_node_10": 0.1, "random_node_30": 0.3, "random_node_50": 0.5}[
            spec.failure.value
        ]
        targets = random_nodes(topology, fraction, seed)
        if targets:
            events.append(FailureEvent(at, FailureKind.NODE_DOWN, targets))
    elif spec.failure is FailureScenario.REGIONAL_SRLG:
        tags = sorted({tag for link in topology.links.values() for tag in link.srlg})
        chosen = tags[: max(1, len(tags) // 5)]
        if chosen:
            events.append(FailureEvent(at, FailureKind.SRLG_DOWN, tuple(chosen)))
    elif spec.failure is FailureScenario.CONGESTION_SURGE:
        events.append(FailureEvent(at, FailureKind.CONGESTION_SURGE, factor=2.5))
    elif spec.failure is FailureScenario.CASCADING:
        events.append(
            FailureEvent(at, FailureKind.LINK_DOWN, highest_betweenness_links(topology, 2))
        )
        cascade = CascadeRule(utilisation_threshold=0.98, dwell_ticks=3, enabled=True)

    return FailureSchedule(topology, events, cascade)


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    name: str
    scenarios: tuple[ScenarioSpec, ...]
    algorithms: tuple[str, ...] = ("spf-static", "spf-reconverge", "ecmp", "cspf", "orbit")
    trials: int = 30
    detector: DetectorConfig = field(default_factory=DetectorConfig)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValidationError("ExperimentSpec: name must not be empty")
        if not self.scenarios:
            raise ValidationError("ExperimentSpec: at least one scenario is required")
        if not 0 < self.trials <= MAX_TRIALS:
            raise ValidationError(f"ExperimentSpec: trials must be in (0, {MAX_TRIALS}]")
        if not self.algorithms:
            raise ValidationError("ExperimentSpec: at least one algorithm is required")


def scenario_grid(
    families: Sequence[TopologyFamily],
    failures: Sequence[FailureScenario],
    **common: object,
) -> tuple[ScenarioSpec, ...]:
    return tuple(
        ScenarioSpec(family=family, failure=failure, **common)  # type: ignore[arg-type]
        for family in families
        for failure in failures
    )
