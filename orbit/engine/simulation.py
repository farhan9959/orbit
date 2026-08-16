"""The fixed-timestep tick loop.

Implements requirements F7 (advance in fixed steps; per step allocate capacity and compute
delivered rate, loss and latency) and F11 (step, reset, run headless to completion), and
the tick-loop structure in docs/03-simulation-model.md §3.

What this loop does *not* do yet
--------------------------------
docs/03-simulation-model.md §3 lists seven steps per tick. Steps 4-7 are here. Steps 1-3
are not, because the things they call do not exist:

    1. apply scheduled events   -> failure injection, phase A4
    2. detector.update(tick)    -> failure detector, phase A3
    3. algorithm.recompute(...) -> routing algorithms, phase A3

So routing is currently **static**: the `RoutingState` handed to the constructor is used
for every tick. That is exactly baseline B1 (static shortest path, computed once, never
recomputed), so the loop is already capable of running one real algorithm — it simply has
no others to choose between yet. When A3 lands, steps 1-3 become a hook here rather than a
rewrite, because nothing below depends on the routes being fixed.

Time
----
Simulation time is `tick_index * tick_ms`, an integer count of milliseconds converted to
seconds only for display and for comparing against flow schedules. It is **never** a float
accumulator: repeatedly adding 0.1 drifts, and drift breaks determinism (I-DET) in a way
that shows up thousands of ticks into a run and is miserable to diagnose.

Determinism
-----------
There is no clock, no randomness and no mutable state in the loop beyond the tick counter,
so `reset()` is genuinely just "set the counter to zero" — the topology, the flows and the
routing are all immutable. That is a property worth noticing rather than a coincidence: it
is what makes I-DET hold, and it is why `run()` can be replayed and get identical output.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass

from orbit.engine.allocator import Allocation, allocate
from orbit.engine.metrics import (
    FlowSample,
    MetricsAccumulator,
    RunSummary,
    TickResult,
    path_intrinsic_loss,
    queue_delay_ms,
)
from orbit.errors import ValidationError
from orbit.model import (
    Flow,
    LinkId,
    Route,
    RoutingState,
    Topology,
    validate_flows,
    validate_routing,
)

_MS_PER_SECOND = 1000.0


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Tunables for the tick loop and the latency model.

    `queue_delay_coefficient` and `max_queue_delay_ms` parameterise an approximation, not a
    measurement (see `orbit.engine.metrics.queue_delay_ms`). Their defaults are arbitrary
    but fixed, and because the same values are applied to every algorithm they cannot bias
    a comparison — only the absolute latency numbers, which is a Threat to Validity and is
    written down as one.
    """

    tick_ms: int = 100
    queue_delay_coefficient: float = 1.0
    """`k`, in Mbps·ms. Larger values make delay climb sooner as a link fills."""
    max_queue_delay_ms: float = 50.0
    """`q_max`. The delay reported for a saturated link, and the ceiling everywhere else."""

    def __post_init__(self) -> None:
        if isinstance(self.tick_ms, bool) or not isinstance(self.tick_ms, int):
            raise ValidationError(f"SimulationConfig: tick_ms must be an int, got {self.tick_ms!r}")
        if self.tick_ms <= 0:
            raise ValidationError(f"SimulationConfig: tick_ms must be > 0, got {self.tick_ms!r}")
        for name in ("queue_delay_coefficient", "max_queue_delay_ms"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValidationError(f"SimulationConfig: {name} must be a number, got {value!r}")
            if not value >= 0.0:
                raise ValidationError(f"SimulationConfig: {name} must be >= 0, got {value!r}")

    @property
    def tick_seconds(self) -> float:
        return self.tick_ms / _MS_PER_SECOND


class Simulation:
    """A replayable fixed-timestep run over a fixed topology, traffic set and routing."""

    __slots__ = ("_config", "_flows", "_routing", "_tick", "_topology")

    def __init__(
        self,
        topology: Topology,
        flows: Iterable[Flow],
        routing: RoutingState,
        config: SimulationConfig | None = None,
    ) -> None:
        # Validated once, here, rather than on every tick. This is the boundary a routing
        # algorithm's output crosses; the per-tick path spends its budget on liveness and
        # capacity instead, which are the things that actually change between ticks.
        self._flows: tuple[Flow, ...] = validate_flows(topology, flows)
        validate_routing(topology, self._flows, routing)
        self._topology = topology
        self._routing = routing
        self._config = config if config is not None else SimulationConfig()
        self._tick = 0

    def __repr__(self) -> str:
        return (
            f"Simulation(nodes={len(self._topology.nodes)}, flows={len(self._flows)}, "
            f"tick={self._tick})"
        )

    @property
    def config(self) -> SimulationConfig:
        return self._config

    @property
    def tick(self) -> int:
        """Index of the tick that `step()` will produce next."""
        return self._tick

    @property
    def time_s(self) -> float:
        """Simulation time at the start of the next tick."""
        return self._tick * self._config.tick_ms / _MS_PER_SECOND

    def reset(self) -> None:
        """Rewind to tick 0 (requirement F11).

        Nothing else needs undoing: the topology, flows and routing are immutable, and the
        loop keeps no other state. A `reset` that had more to do would be a sign the engine
        had grown hidden state, which is the thing determinism cannot survive.
        """
        self._tick = 0

    def step(self) -> TickResult:
        """Advance exactly one tick and return what happened during it."""
        tick = self._tick
        time_s = tick * self._config.tick_ms / _MS_PER_SECOND

        active = [flow for flow in self._flows if flow.is_active_at(time_s)]
        allocation = allocate(self._topology, active, self._routing)
        samples = tuple(self._sample(tick, flow, allocation) for flow in active)

        self._tick += 1
        return TickResult(tick=tick, time_s=time_s, samples=samples, link_load=allocation.link_load)

    def run(self, ticks: int) -> Iterator[TickResult]:
        """Yield `ticks` consecutive results, lazily.

        A generator rather than a list because a 500-node, 20,000-tick run produces
        millions of samples; materialising them all before the caller can fold them into a
        summary or stream them to Parquet is how a laptop-scale tool runs out of memory
        (non-functional requirement N1). Callers that genuinely want them all can call
        `list()`, having decided to.
        """
        if isinstance(ticks, bool) or not isinstance(ticks, int):
            raise ValidationError(f"Simulation.run: ticks must be an int, got {ticks!r}")
        if ticks < 0:
            raise ValidationError(f"Simulation.run: ticks must be >= 0, got {ticks}")
        for _ in range(ticks):
            yield self.step()

    def measure(self, ticks: int) -> RunSummary:
        """Run `ticks` ticks headless and return the run summary (requirements F10, F11)."""
        accumulator = MetricsAccumulator(self._config.tick_seconds)
        accumulator.add_all(self.run(ticks))
        return accumulator.summary()

    def _sample(self, tick: int, flow: Flow, allocation: Allocation) -> FlowSample:
        allocated = allocation.rates[flow.id]
        blackholed = flow.id in allocation.blackholed
        route = None if blackholed else self._routing.get(flow.id)

        intrinsic = 0.0 if route is None else path_intrinsic_loss(self._topology, route)
        delivered = allocated * (1.0 - intrinsic)
        congestive = (
            (flow.demand_mbps - allocated) / flow.demand_mbps if flow.demand_mbps > 0.0 else 0.0
        )
        latency = (
            self._latency_ms(route, allocation.link_load)
            if route is not None and delivered > 0.0
            else None
        )

        return FlowSample(
            tick=tick,
            flow_id=flow.id,
            priority=flow.priority,
            demand_mbps=flow.demand_mbps,
            allocated_mbps=allocated,
            delivered_mbps=delivered,
            congestive_loss=congestive,
            intrinsic_loss=intrinsic,
            latency_ms=latency,
            blackholed=blackholed,
        )

    def _latency_ms(self, route: Route, link_load: Mapping[LinkId, float]) -> float:
        """`Σ_path (prop_delay + queue_delay) + Σ_path node processing_delay`."""
        total = 0.0
        for link_id in route.links:
            link = self._topology.link(link_id)
            total += link.prop_delay_ms + queue_delay_ms(
                link.effective_capacity_mbps,
                link_load.get(link_id, 0.0),
                coefficient=self._config.queue_delay_coefficient,
                maximum_ms=self._config.max_queue_delay_ms,
            )
        for node_id in route.nodes:
            total += self._topology.node(node_id).processing_delay_ms
        return total


def summarise(results: Sequence[TickResult], tick_seconds: float) -> RunSummary:
    """Fold already-collected results into a summary, for callers that kept them."""
    accumulator = MetricsAccumulator(tick_seconds)
    accumulator.add_all(results)
    return accumulator.summary()
