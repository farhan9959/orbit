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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from orbit.errors import ValidationError
from orbit.events import Event, EventType
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
    events: tuple[Event, ...] = ()
    control_seconds: float | None = None
    topology: Topology | None = None
    routing: Mapping[FlowId, tuple[tuple[LinkId, ...], ...]] | None = None


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
    control_seconds: float = 0.0
    control_calls: int = 0
    cascade_depth: int = 0
    reroutes: int = 0
    preemptions: int = 0
    backup_activations: int = 0
    """Reroutes served from a precomputed M1 backup rather than recomputed by M2."""
    time_to_restore_s: Mapping[Priority, float | None] = field(default_factory=dict)
    censored: bool = False
    time_to_converge_s: float | None = None
    peak_restore_fraction: Mapping[Priority, float | None] = field(default_factory=dict)
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


_RESTORE_FRACTION = 0.95
_RESTORE_DWELL_TICKS = 3


def peak_restore_fraction(series: Sequence[float], failure_tick: int) -> float | None:
    """Best post-failure delivered rate as a fraction of the pre-failure mean.

    Reported alongside time-to-restore so a censored run is interpretable: a run that peaked
    at 0.93 was close to the 0.95 criterion, while one that peaked at 0.4 lost capacity it
    was never going to get back. Without this, censoring is a single opaque bit.
    """
    if failure_tick <= 0 or failure_tick >= len(series):
        return None
    baseline_slice = series[:failure_tick]
    if not baseline_slice:
        return None
    baseline = math.fsum(baseline_slice) / len(baseline_slice)
    if baseline <= 0.0:
        return None
    return max(series[failure_tick:], default=0.0) / baseline


def time_to_converge(
    route_change_ticks: Sequence[int], failure_tick: int, last_tick: int, tick_seconds: float
) -> float | None:
    """Time from failure until the control plane stops changing routes for 3 ticks.

    Distinct from time-to-restore, and both are reported: the control plane can converge on
    a route set that still does not deliver the traffic, because the capacity is gone.
    Conflating them is a common way to overstate a recovery result.
    """
    if failure_tick < 0 or last_tick < failure_tick:
        return None
    after = sorted(tick for tick in route_change_ticks if tick >= failure_tick)
    quiet_from = failure_tick
    for tick in after:
        quiet_from = tick + 1
    if last_tick - quiet_from + 1 < _RESTORE_DWELL_TICKS:
        return None
    return (quiet_from - failure_tick) * tick_seconds


def time_to_restore(
    series: Sequence[float], failure_tick: int, tick_seconds: float
) -> float | None:
    """First moment delivered rate regains 95% of its pre-failure mean and holds 3 ticks.

    Returns None when the level is never regained, which the caller must treat as censored
    rather than as an infinite or zero recovery (invariant I-CENSOR).
    """
    if failure_tick <= 0 or failure_tick >= len(series):
        return None
    window = max(1, round(1.0 / tick_seconds))
    baseline_slice = series[max(0, failure_tick - window) : failure_tick]
    if not baseline_slice:
        return None
    baseline = math.fsum(baseline_slice) / len(baseline_slice)
    if baseline <= 0.0:
        return None
    target = _RESTORE_FRACTION * baseline
    held = 0
    for index in range(failure_tick, len(series)):
        if series[index] >= target:
            held += 1
            if held >= _RESTORE_DWELL_TICKS:
                start = index - _RESTORE_DWELL_TICKS + 1
                return (start - failure_tick) * tick_seconds
        else:
            held = 0
    return None


class MetricsAccumulator:
    """Folds `TickResult`s into a `RunSummary` without retaining every sample.

    # ponytail: latency samples and the per-class rate series ARE retained, because an
    # exact weighted p95 and a time-to-restore both need the distribution. Replace with a
    # fixed-bin histogram only if a real run runs out of memory.
    """

    def __init__(self, tick_seconds: float) -> None:
        if tick_seconds <= 0.0:
            raise ValidationError(
                f"MetricsAccumulator: tick_seconds must be > 0, got {tick_seconds!r}"
            )
        self._tick_seconds = tick_seconds
        self._overall = _Bucket()
        self._by_priority: dict[Priority, _Bucket] = {}
        self._series: dict[Priority, list[float]] = {}
        self._ticks = 0
        self._first_failure_tick: int | None = None
        self._reroutes = 0
        self._preemptions = 0
        self._backup_activations = 0
        self._route_change_ticks: list[int] = []
        self._last_tick = -1

    def add(self, result: TickResult) -> None:
        self._ticks += 1
        per_class: dict[Priority, float] = {}
        for sample in result.samples:
            self._overall.add(sample, self._tick_seconds)
            self._by_priority.setdefault(sample.priority, _Bucket()).add(sample, self._tick_seconds)
            per_class[sample.priority] = per_class.get(sample.priority, 0.0) + sample.delivered_mbps
        for priority in self._by_priority:
            self._series.setdefault(priority, [0.0] * (self._ticks - 1)).append(
                per_class.get(priority, 0.0)
            )
        self._last_tick = result.tick
        for event in result.events:
            if event.type is EventType.FAILURE_INJECTED and self._first_failure_tick is None:
                self._first_failure_tick = result.tick
            elif event.type is EventType.FLOW_REROUTED:
                self._reroutes += 1
                self._route_change_ticks.append(result.tick)
                # Distinguishes M1 firing from M2 firing. Without it the ablation can only
                # say that disabling protection changed nothing, not whether protection was
                # ever reached in the first place.
                if event.payload.get("via") == "BACKUP":
                    self._backup_activations += 1
            elif event.type is EventType.FLOW_PREEMPTED:
                self._preemptions += 1
                self._route_change_ticks.append(result.tick)

    def add_all(self, results: Iterable[TickResult]) -> None:
        for result in results:
            self.add(result)

    def summary(
        self,
        *,
        control_seconds: float = 0.0,
        control_calls: int = 0,
        cascade_depth: int = 0,
    ) -> RunSummary:
        duration_s = self._ticks * self._tick_seconds
        restore: dict[Priority, float | None] = {}
        peak: dict[Priority, float | None] = {}
        converge: float | None = None
        if self._first_failure_tick is not None:
            for priority, series in self._series.items():
                restore[priority] = time_to_restore(
                    series, self._first_failure_tick, self._tick_seconds
                )
                peak[priority] = peak_restore_fraction(series, self._first_failure_tick)
            converge = time_to_converge(
                self._route_change_ticks,
                self._first_failure_tick,
                self._last_tick,
                self._tick_seconds,
            )
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
            control_seconds=control_seconds,
            control_calls=control_calls,
            cascade_depth=cascade_depth,
            reroutes=self._reroutes,
            preemptions=self._preemptions,
            backup_activations=self._backup_activations,
            time_to_restore_s=MappingProxyType(restore),
            censored=any(value is None for value in restore.values()),
            time_to_converge_s=converge,
            peak_restore_fraction=MappingProxyType(peak),
        )
