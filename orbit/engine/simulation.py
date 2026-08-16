"""The fixed-timestep tick loop (docs/03-simulation-model.md §3).

Per tick: apply scheduled failures, update the detector, recompute routes if the control
plane has news, allocate capacity, derive metrics, record samples and events.

Assumptions and failure modes:
* Routing decisions use the detector's `GraphView`; physics uses the ground-truth topology.
  Between a failure and its detection the controller routes over a graph that no longer
  exists, and the resulting blackholing is a modelled behaviour, not a bug.
* Simulation time is `tick_index * tick_ms`, an integer count. A float accumulator drifts
  off 1.0 within ten ticks and silently shifts every flow's activity window.
* The loop is single-threaded and holds no randomness of its own; `reset()` restores the
  tick counter, the algorithm, the schedule and the detector, so a run replays exactly.
* Control-plane computation time is wall-clock and therefore the one non-deterministic
  output. It is reported as a measurement, never fed back into simulation state.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from time import perf_counter

from orbit.algorithms.base import RoutingAlgorithm, StaticRouting
from orbit.detect.detector import DetectorConfig, FailureDetector
from orbit.engine.allocator import Allocation, allocate
from orbit.engine.failures import FailureSchedule
from orbit.engine.metrics import (
    FlowSample,
    MetricsAccumulator,
    RunSummary,
    TickResult,
    path_intrinsic_loss,
    queue_delay_ms,
)
from orbit.errors import ValidationError
from orbit.events import Event, EventType
from orbit.model import (
    Flow,
    LinkId,
    Route,
    RoutingState,
    Topology,
    placement_links,
    placement_paths,
    validate_flows,
    validate_routing,
)

_MS_PER_SECOND = 1000.0


def _clamp_fraction(value: float) -> float:
    return min(1.0, max(0.0, value))


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    tick_ms: int = 100
    queue_delay_coefficient: float = 1.0
    max_queue_delay_ms: float = 50.0
    validate_each_recompute: bool = True

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
    __slots__ = (
        "_algorithm",
        "_config",
        "_control_calls",
        "_control_seconds",
        "_detector",
        "_detector_config",
        "_flows",
        "_routing",
        "_schedule",
        "_stable_ticks",
        "_tick",
        "_topology",
    )

    def __init__(
        self,
        topology: Topology,
        flows: Iterable[Flow],
        algorithm: RoutingAlgorithm | RoutingState,
        config: SimulationConfig | None = None,
        *,
        schedule: FailureSchedule | None = None,
        detector: DetectorConfig | None = None,
    ) -> None:
        self._flows = validate_flows(topology, flows)
        if isinstance(algorithm, Mapping):
            validate_routing(topology, self._flows, algorithm)
            self._algorithm: RoutingAlgorithm = StaticRouting(algorithm)
        else:
            self._algorithm = algorithm
        self._topology = topology
        self._config = config if config is not None else SimulationConfig()
        self._schedule = schedule
        self._detector_config = detector or DetectorConfig()
        self._detector = FailureDetector(topology, self._detector_config, self._config.tick_ms)
        self._tick = 0
        self._routing: RoutingState = {}
        self._control_seconds = 0.0
        self._control_calls = 0
        self._stable_ticks = 0

    def __repr__(self) -> str:
        return (
            f"Simulation(nodes={len(self._topology.nodes)}, flows={len(self._flows)}, "
            f"algorithm={self._algorithm.name!r}, tick={self._tick})"
        )

    @property
    def config(self) -> SimulationConfig:
        return self._config

    @property
    def algorithm(self) -> RoutingAlgorithm:
        return self._algorithm

    @property
    def tick(self) -> int:
        return self._tick

    @property
    def time_s(self) -> float:
        return self._tick * self._config.tick_ms / _MS_PER_SECOND

    @property
    def routing(self) -> RoutingState:
        return self._routing

    @property
    def control_seconds(self) -> float:
        return self._control_seconds

    @property
    def control_calls(self) -> int:
        return self._control_calls

    def reset(self) -> None:
        self._tick = 0
        self._routing = {}
        self._control_seconds = 0.0
        self._control_calls = 0
        self._stable_ticks = 0
        self._algorithm.reset()
        if self._schedule is not None:
            self._schedule.reset()
        self._detector = FailureDetector(
            self._topology, self._detector_config, self._config.tick_ms
        )

    def step(self) -> TickResult:
        tick = self._tick
        time_s = tick * self._config.tick_ms / _MS_PER_SECOND
        events: list[Event] = []

        truth = self._topology
        if self._schedule is not None:
            truth, fired = self._schedule.apply(tick, time_s)
            for event in fired:
                events.append(
                    Event(
                        tick,
                        EventType.FAILURE_INJECTED,
                        {"kind": str(event.kind), "targets": list(event.targets)},
                    )
                )

        view = self._detector.observe(tick, truth)
        for kind, element_id in self._detector.detected_this_tick:
            events.append(
                Event(tick, EventType.FAILURE_DETECTED, {"element": element_id, "kind": kind})
            )

        control_seconds: float | None = None
        if view.changed or not self._routing:
            started = perf_counter()
            routing = self._algorithm.recompute(view, self._flows, self._routing)
            control_seconds = perf_counter() - started
            self._control_seconds += control_seconds
            self._control_calls += 1
            if self._config.validate_each_recompute:
                validate_routing(view.topology, self._flows, routing)
            changed_routes = self._changed_routes(routing)
            self._routing = routing
            events.extend(self._algorithm.drain_events())
            self._stable_ticks = 0 if changed_routes else self._stable_ticks + 1
        else:
            self._stable_ticks += 1
            if self._stable_ticks == 3:
                events.append(Event(tick, EventType.RECONVERGED, {}))

        scale = self._schedule.demand_scale if self._schedule is not None else 1.0
        active = [
            replace(flow, demand_mbps=flow.demand_mbps * scale) if scale != 1.0 else flow
            for flow in self._flows
            if flow.is_active_at(time_s)
        ]
        allocation = allocate(truth, active, self._routing)
        samples = tuple(self._sample(tick, flow, allocation, truth) for flow in active)

        if self._schedule is not None:
            for link_id in self._schedule.observe_utilisation(tick, truth, allocation.link_load):
                events.append(Event(tick, EventType.CASCADE_FAILURE, {"link": link_id}))

        self._tick += 1
        return TickResult(
            tick=tick,
            time_s=time_s,
            samples=samples,
            link_load=allocation.link_load,
            events=tuple(events),
            control_seconds=control_seconds,
        )

    def _changed_routes(self, routing: RoutingState) -> bool:
        if set(routing) != set(self._routing):
            return True
        return any(
            placement_links(routing[flow_id]) != placement_links(self._routing[flow_id])
            for flow_id in routing
        )

    def run(self, ticks: int) -> Iterator[TickResult]:
        if isinstance(ticks, bool) or not isinstance(ticks, int):
            raise ValidationError(f"Simulation.run: ticks must be an int, got {ticks!r}")
        if ticks < 0:
            raise ValidationError(f"Simulation.run: ticks must be >= 0, got {ticks}")
        for _ in range(ticks):
            yield self.step()

    def measure(self, ticks: int) -> RunSummary:
        accumulator = MetricsAccumulator(self._config.tick_seconds)
        accumulator.add_all(self.run(ticks))
        return accumulator.summary(
            control_seconds=self._control_seconds,
            control_calls=self._control_calls,
            cascade_depth=self._schedule.cascade_depth if self._schedule is not None else 0,
        )

    def _sample(self, tick: int, flow: Flow, allocation: Allocation, truth: Topology) -> FlowSample:
        allocated = allocation.rates[flow.id]
        blackholed = flow.id in allocation.blackholed
        placement = None if blackholed else self._routing.get(flow.id)

        delivered = 0.0
        weighted_latency = 0.0
        if placement is not None:
            for index, (route, _) in enumerate(placement_paths(placement)):
                granted = allocation.path_rates.get((flow.id, index), 0.0)
                if granted <= 0.0:
                    continue
                survived = granted * (1.0 - path_intrinsic_loss(truth, route))
                delivered += survived
                weighted_latency += survived * self._latency_ms(route, allocation.link_load, truth)
        intrinsic = _clamp_fraction(1.0 - (delivered / allocated)) if allocated > 0.0 else 0.0
        congestive = (
            _clamp_fraction((flow.demand_mbps - allocated) / flow.demand_mbps)
            if flow.demand_mbps > 0.0
            else 0.0
        )
        latency = (weighted_latency / delivered) if delivered > 0.0 else None
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

    def _latency_ms(
        self, route: Route, link_load: Mapping[LinkId, float], truth: Topology
    ) -> float:
        total = 0.0
        for link_id in route.links:
            link = truth.link(link_id)
            total += link.prop_delay_ms + queue_delay_ms(
                link.effective_capacity_mbps,
                link_load.get(link_id, 0.0),
                coefficient=self._config.queue_delay_coefficient,
                maximum_ms=self._config.max_queue_delay_ms,
            )
        for node_id in route.nodes:
            total += truth.node(node_id).processing_delay_ms
        return total


def summarise(results: Sequence[TickResult], tick_seconds: float) -> RunSummary:
    accumulator = MetricsAccumulator(tick_seconds)
    accumulator.add_all(results)
    return accumulator.summary()
