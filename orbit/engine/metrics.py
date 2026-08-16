"""Per-flow derived quantities and run-level aggregation.

Implements the derived metrics in docs/03-simulation-model.md §4 and the metric
definitions in §7. Requirement F7 (compute delivered rate, loss and latency per step) and
the run-summary half of F10.

Nothing here performs I/O. The engine *produces* samples; writing them to Parquet is the
experiment runner's job (docs/02-architecture.md §1 keeps `orbit/` free of I/O), so a
`RunSummary` is an in-memory object and A7 is what puts it on disk.


One ambiguity in the specification, and how it is resolved
----------------------------------------------------------
docs/03-simulation-model.md §4 defines delivered rate as "the allocation result" and lists
intrinsic loss as a *separate* derived metric, which reads as though the two are never
composed. But docs/05-methodology.md A4 requires that a link with a 100% loss rate yields
`delivered = 0`. Both cannot hold: under the literal reading, a flow crossing a totally
lossy link would report its full allocation as delivered.

**Resolution: intrinsic loss reduces delivered rate.**

    allocated_mbps  = what the allocator granted (this is what consumes link capacity)
    delivered_mbps  = allocated_mbps * (1 - intrinsic_loss)

Both numbers are recorded, so the two loss causes stay distinguishable — congestion is the
network being oversubscribed, intrinsic loss is the medium being lossy, and a recovery
controller can do something about the first but not the second. PDR is computed from
`delivered_mbps`, which is what makes the A4 edge case come out right.

Note that `allocated_mbps`, not `delivered_mbps`, is what occupies link capacity. Traffic
dropped by a lossy link partway along a path has already consumed capacity on the links
before it. Modelling it otherwise would quietly hand a lossy path extra effective capacity.


Latency is recorded only when something was delivered
-----------------------------------------------------
docs/03-simulation-model.md §7 requires latency to be "demand-weighted over delivered
traffic only (undelivered traffic has no latency; averaging it in as zero would flatter
congested runs)". So `FlowSample.latency_ms` is `None` when a flow delivered nothing, not
`0.0`. This is deliberate and it is the difference between an honest latency number and one
that improves as the network gets worse.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from orbit.errors import ValidationError
from orbit.model import FlowId, LinkId, Priority, Route, Topology


@dataclass(frozen=True, slots=True)
class FlowSample:
    """One flow's outcome for one tick."""

    tick: int
    flow_id: FlowId
    priority: Priority
    demand_mbps: float
    allocated_mbps: float
    """What the allocator granted. This is the quantity that consumed link capacity."""
    delivered_mbps: float
    """`allocated * (1 - intrinsic_loss)`. This is what PDR is computed from."""
    congestive_loss: float
    """Fraction of demand the allocator could not grant. 0.0 when demand is 0."""
    intrinsic_loss: float
    """Fraction lost to the medium along the path, independent of congestion."""
    latency_ms: float | None
    """`None` when nothing was delivered — see the module docstring."""
    blackholed: bool
    """True when the flow had no live route at all, as opposed to being starved to 0."""


@dataclass(frozen=True, slots=True)
class TickResult:
    """Everything the engine produced for one tick."""

    tick: int
    time_s: float
    samples: tuple[FlowSample, ...]
    link_load: Mapping[LinkId, float]


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    """Aggregates for one priority class, or for the run as a whole."""

    demanded_mbit: float
    delivered_mbit: float
    pdr: float | None
    """Delivered ÷ demanded. `None` when nothing was demanded — see `_ratio`."""
    mean_latency_ms: float | None
    p95_latency_ms: float | None
    throughput_mbps: float
    """Mean delivered rate over the measurement window."""
    blackholed_flow_ticks: int
    flow_ticks: int


@dataclass(frozen=True, slots=True)
class RunSummary:
    ticks: int
    duration_s: float
    overall: ClassMetrics
    by_priority: Mapping[Priority, ClassMetrics]
    """Only classes that actually appeared in the run. A run with no CRITICAL traffic does
    not report a CRITICAL row, because a PDR over zero demand is not a measurement."""


def path_intrinsic_loss(topology: Topology, route: Route) -> float:
    """`1 - Π(1 - loss_rate_e)` over the route's links.

    Losses compose multiplicatively because each link drops an independent fraction of what
    reaches it. A single link with `loss_rate = 1.0` therefore gives exactly 1.0, which is
    the docs/05-methodology.md A4 requirement that a 100%-loss link delivers nothing.
    """
    survival = 1.0
    for link_id in route.links:
        survival *= 1.0 - topology.link(link_id).loss_rate
    return 1.0 - survival


def queue_delay_ms(
    capacity_mbps: float,
    load_mbps: float,
    *,
    coefficient: float,
    maximum_ms: float,
) -> float:
    """Bounded M/M/1-style queueing delay: `min(q_max, k / (C - L))`, or `q_max` if full.

    **This is an approximation and is labelled as one** (docs/03-simulation-model.md §4).
    It is a monotone, well-behaved stand-in for "delay grows sharply as a link approaches
    capacity", not a queueing-theory result. It is applied identically to every algorithm,
    so it cannot bias a comparison between them; it can only shift absolute latency
    numbers, which belongs in Threats to Validity.

    A zero-capacity link is saturated by definition and returns `q_max` rather than
    dividing by zero.
    """
    headroom = capacity_mbps - load_mbps
    if headroom <= 0.0:
        return maximum_ms
    return min(maximum_ms, coefficient / headroom)


def _ratio(numerator: float, denominator: float) -> float | None:
    """Delivered ÷ demanded, or `None` when nothing was demanded.

    Returning `None` rather than 0.0 or 1.0 is the honest answer: a run that asked for
    nothing did not achieve 0% delivery, and it did not achieve 100% either. Folding a
    fabricated value into an aggregate is exactly the kind of quiet bias
    docs/05-methodology.md B4 rules out for censored runs.
    """
    if denominator <= 0.0:
        return None
    return numerator / denominator


def _weighted_percentile(pairs: list[tuple[float, float]], quantile: float) -> float | None:
    """Lower weighted percentile of (value, weight) pairs.

    Weights are delivered rates, so a flow carrying 10x the traffic counts 10x toward the
    percentile. Sorting makes the result independent of insertion order, which keeps it
    deterministic under I-DET.
    """
    if not pairs:
        return None
    total = math.fsum(weight for _, weight in pairs)
    if total <= 0.0:
        return None
    threshold = quantile * total
    cumulative = 0.0
    for value, weight in sorted(pairs):
        cumulative += weight
        if cumulative >= threshold:
            return value
    return sorted(pairs)[-1][0]


@dataclass
class _Bucket:
    """Running totals for one class. Mutable by design; it is an accumulator."""

    demanded_mbit: float = 0.0
    delivered_mbit: float = 0.0
    flow_ticks: int = 0
    blackholed_flow_ticks: int = 0
    latencies: list[tuple[float, float]] = field(default_factory=list)

    def add(self, sample: FlowSample, tick_seconds: float) -> None:
        self.demanded_mbit += sample.demand_mbps * tick_seconds
        self.delivered_mbit += sample.delivered_mbps * tick_seconds
        self.flow_ticks += 1
        if sample.blackholed:
            self.blackholed_flow_ticks += 1
        if sample.latency_ms is not None and sample.delivered_mbps > 0.0:
            self.latencies.append((sample.latency_ms, sample.delivered_mbps))

    def finish(self, duration_s: float) -> ClassMetrics:
        weighted = math.fsum(value * weight for value, weight in self.latencies)
        total_weight = math.fsum(weight for _, weight in self.latencies)
        return ClassMetrics(
            demanded_mbit=self.demanded_mbit,
            delivered_mbit=self.delivered_mbit,
            pdr=_ratio(self.delivered_mbit, self.demanded_mbit),
            mean_latency_ms=(weighted / total_weight) if total_weight > 0.0 else None,
            p95_latency_ms=_weighted_percentile(self.latencies, 0.95),
            throughput_mbps=(self.delivered_mbit / duration_s) if duration_s > 0.0 else 0.0,
            blackholed_flow_ticks=self.blackholed_flow_ticks,
            flow_ticks=self.flow_ticks,
        )


class MetricsAccumulator:
    """Folds `TickResult`s into a `RunSummary` without retaining every sample.

    Totals are running sums, so a 20,000-tick run does not have to hold two million sample
    objects in memory to report a delivery ratio (non-functional requirement N1: the whole
    thing runs on a laptop).

    # ponytail: latency samples ARE retained, because an exact weighted p95 needs the
    # distribution. At Tier-A sizes that is acceptable; if a 500-node run runs out of
    # memory, replace the list with a fixed-bin histogram and report the percentile from
    # that. Do not do it before a run actually gets big enough to hurt.
    """

    def __init__(self, tick_seconds: float) -> None:
        if tick_seconds <= 0.0:
            raise ValidationError(
                f"MetricsAccumulator: tick_seconds must be > 0, got {tick_seconds!r}"
            )
        self._tick_seconds = tick_seconds
        self._overall = _Bucket()
        self._by_priority: dict[Priority, _Bucket] = {}
        self._ticks = 0

    def add(self, result: TickResult) -> None:
        self._ticks += 1
        for sample in result.samples:
            self._overall.add(sample, self._tick_seconds)
            self._by_priority.setdefault(sample.priority, _Bucket()).add(sample, self._tick_seconds)

    def add_all(self, results: Iterable[TickResult]) -> None:
        for result in results:
            self.add(result)

    def summary(self) -> RunSummary:
        duration_s = self._ticks * self._tick_seconds
        return RunSummary(
            ticks=self._ticks,
            duration_s=duration_s,
            overall=self._overall.finish(duration_s),
            by_priority=MappingProxyType(
                {
                    priority: self._by_priority[priority].finish(duration_s)
                    for priority in sorted(self._by_priority, reverse=True)
                }
            ),
        )
