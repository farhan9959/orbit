"""A2 — the tick loop, derived metrics, and the run summary.

Expected values are computed by hand from docs/03-simulation-model.md §4 and §7.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given

from orbit.engine import (
    MetricsAccumulator,
    Simulation,
    SimulationConfig,
    path_intrinsic_loss,
    queue_delay_ms,
)
from orbit.errors import ValidationError
from orbit.model import Flow, Link, LinkState, Node, Priority, Route, Topology
from tests import invariants
from tests.test_properties import PROPERTY_SETTINGS, Scenario, scenarios

APPROX = pytest.approx

# A generous coefficient and a huge ceiling, so queue delay is a rounding error in tests
# that are about something else. Tests that care about queueing set their own.
NEGLIGIBLE_QUEUEING = SimulationConfig(queue_delay_coefficient=0.0)


def line_topology(capacities: list[float], **link_kwargs: object) -> Topology:
    nodes = [Node(f"n{i}") for i in range(len(capacities) + 1)]
    links = [
        Link(f"e{i}", f"n{i}", f"n{i + 1}", capacity_mbps=capacity, **link_kwargs)  # type: ignore[arg-type]
        for i, capacity in enumerate(capacities)
    ]
    return Topology(nodes, links)


def single_flow_sim(
    topology: Topology,
    demand: float,
    links: list[str],
    *,
    config: SimulationConfig = NEGLIGIBLE_QUEUEING,
    **flow_kwargs: object,
) -> Simulation:
    src = topology.link(links[0]).src
    dst = topology.link(links[-1]).dst
    flow = Flow("f0", src, dst, demand_mbps=demand, **flow_kwargs)  # type: ignore[arg-type]
    return Simulation(topology, [flow], {"f0": Route.build(topology, links)}, config)


# ------------------------------------------------------------------------ tick loop


def test_a_tick_delivers_the_full_demand_when_capacity_allows() -> None:
    result = single_flow_sim(line_topology([10.0]), 4.0, ["e0"]).step()

    assert result.tick == 0
    assert result.time_s == 0.0
    assert len(result.samples) == 1
    assert result.samples[0].delivered_mbps == APPROX(4.0)
    assert result.samples[0].congestive_loss == APPROX(0.0)


def test_time_advances_in_exact_integer_milliseconds() -> None:
    """Never a float accumulator: repeatedly adding 0.1 drifts and breaks I-DET."""
    sim = single_flow_sim(line_topology([10.0]), 1.0, ["e0"])
    times = [result.time_s for result in sim.run(11)]

    assert times[10] == APPROX(1.0)
    assert times[3] == APPROX(0.3)
    # The exact check the float accumulator would fail after enough ticks.
    assert times[10] == 10 * 100 / 1000


def test_run_yields_the_requested_number_of_ticks() -> None:
    sim = single_flow_sim(line_topology([10.0]), 1.0, ["e0"])
    assert [result.tick for result in sim.run(5)] == [0, 1, 2, 3, 4]
    assert sim.tick == 5


def test_run_is_lazy_so_a_long_run_does_not_materialise_first() -> None:
    sim = single_flow_sim(line_topology([10.0]), 1.0, ["e0"])
    stream = sim.run(1_000_000)
    next(stream)
    assert sim.tick == 1, "run() must not have executed a million ticks eagerly"


def test_step_advances_exactly_one_tick() -> None:
    sim = single_flow_sim(line_topology([10.0]), 1.0, ["e0"])
    sim.step()
    assert sim.tick == 1
    assert sim.time_s == APPROX(0.1)


def test_reset_rewinds_and_reproduces_identical_output() -> None:
    sim = single_flow_sim(line_topology([10.0]), 7.0, ["e0"])
    first = [result.samples[0].delivered_mbps for result in sim.run(4)]
    sim.reset()
    assert sim.tick == 0
    second = [result.samples[0].delivered_mbps for result in sim.run(4)]
    assert first == second


def test_two_simulations_with_the_same_inputs_agree_tick_for_tick() -> None:
    """I-DET at the loop level."""

    def build() -> Simulation:
        topology = line_topology([10.0, 6.0])
        flows = [
            Flow("fa", "n0", "n2", demand_mbps=9.0, priority=Priority.CRITICAL),
            Flow("fb", "n0", "n2", demand_mbps=9.0),
        ]
        routing = {flow.id: Route.build(topology, ["e0", "e1"]) for flow in flows}
        return Simulation(topology, flows, routing)

    left = [(s.flow_id, s.delivered_mbps, s.latency_ms) for r in build().run(6) for s in r.samples]
    right = [(s.flow_id, s.delivered_mbps, s.latency_ms) for r in build().run(6) for s in r.samples]
    assert left == right


@pytest.mark.parametrize("bad", [-1, 1.5, True, "3"])
def test_run_rejects_an_unusable_tick_count(bad: object) -> None:
    sim = single_flow_sim(line_topology([10.0]), 1.0, ["e0"])
    with pytest.raises(ValidationError, match="ticks"):
        list(sim.run(bad))  # type: ignore[arg-type]


# ------------------------------------------------------------------ flow scheduling


def test_a_flow_offers_traffic_only_inside_its_window() -> None:
    topology = line_topology([10.0])
    sim = single_flow_sim(topology, 5.0, ["e0"], start_s=0.2, duration_s=0.2)

    active_ticks = [result.tick for result in sim.run(6) if result.samples]

    # tick_ms is 100, so ticks 2 and 3 cover [0.2, 0.4).
    assert active_ticks == [2, 3]


def test_the_activity_window_is_half_open_so_a_handover_never_double_counts() -> None:
    topology = line_topology([10.0])
    first = Flow("f0", "n0", "n1", demand_mbps=5.0, start_s=0.0, duration_s=0.2)
    second = Flow("f1", "n0", "n1", demand_mbps=5.0, start_s=0.2, duration_s=0.2)
    routing = {flow.id: Route.build(topology, ["e0"]) for flow in (first, second)}
    sim = Simulation(topology, [first, second], routing)

    per_tick = [{sample.flow_id for sample in result.samples} for result in sim.run(4)]

    assert per_tick == [{"f0"}, {"f0"}, {"f1"}, {"f1"}]


def test_an_infinite_duration_flow_never_expires() -> None:
    sim = single_flow_sim(line_topology([10.0]), 5.0, ["e0"], duration_s=math.inf)
    assert all(result.samples for result in sim.run(50))


def test_a_run_with_no_active_flows_produces_empty_ticks_not_a_crash() -> None:
    sim = single_flow_sim(line_topology([10.0]), 5.0, ["e0"], start_s=10.0, duration_s=1.0)
    results = list(sim.run(3))
    assert all(result.samples == () for result in results)


def test_an_empty_flow_set_completes() -> None:
    topology = line_topology([10.0])
    summary = Simulation(topology, [], {}).measure(5)
    assert summary.ticks == 5
    assert summary.overall.pdr is None, "no demand means no delivery ratio to report"
    assert summary.by_priority == {}


# ----------------------------------------------------------------------------- loss


def test_a_hundred_percent_loss_link_delivers_nothing() -> None:
    """docs/05-methodology.md A4. This is the edge case that settles whether intrinsic
    loss reduces delivered rate; it does."""
    topology = line_topology([10.0], loss_rate=1.0)
    sample = single_flow_sim(topology, 4.0, ["e0"]).step().samples[0]

    assert sample.allocated_mbps == APPROX(4.0), "capacity was still consumed"
    assert sample.delivered_mbps == 0.0
    assert sample.intrinsic_loss == APPROX(1.0)
    assert not math.isnan(sample.delivered_mbps)


def test_intrinsic_loss_scales_the_delivered_rate() -> None:
    topology = line_topology([10.0], loss_rate=0.25)
    sample = single_flow_sim(topology, 4.0, ["e0"]).step().samples[0]

    assert sample.delivered_mbps == APPROX(3.0)


def test_losses_compose_multiplicatively_along_a_path() -> None:
    """1 - (1-0.1)(1-0.5) = 0.55, because each link drops a share of what reaches it."""
    topology = Topology(
        [Node("n0"), Node("n1"), Node("n2")],
        [
            Link("e0", "n0", "n1", capacity_mbps=10.0, loss_rate=0.1),
            Link("e1", "n1", "n2", capacity_mbps=10.0, loss_rate=0.5),
        ],
    )
    route = Route.build(topology, ["e0", "e1"])

    assert path_intrinsic_loss(topology, route) == APPROX(0.55)


def test_congestive_and_intrinsic_loss_are_reported_separately() -> None:
    """A controller can reroute around congestion but not around a lossy medium, so the
    two causes must stay distinguishable in the metrics."""
    topology = line_topology([4.0], loss_rate=0.5)
    sample = single_flow_sim(topology, 8.0, ["e0"]).step().samples[0]

    assert sample.allocated_mbps == APPROX(4.0)
    assert sample.congestive_loss == APPROX(0.5)
    assert sample.intrinsic_loss == APPROX(0.5)
    assert sample.delivered_mbps == APPROX(2.0)


def test_a_zero_demand_flow_reports_zero_congestive_loss_not_a_division_error() -> None:
    sample = single_flow_sim(line_topology([10.0]), 0.0, ["e0"]).step().samples[0]
    assert sample.congestive_loss == 0.0


# -------------------------------------------------------------------------- latency


def test_latency_sums_propagation_queueing_and_node_processing() -> None:
    nodes = [Node("n0", processing_delay_ms=2.0), Node("n1", processing_delay_ms=3.0)]
    topology = Topology(nodes, [Link("e0", "n0", "n1", capacity_mbps=10.0, prop_delay_ms=7.0)])
    flow = Flow("f0", "n0", "n1", demand_mbps=5.0)
    config = SimulationConfig(queue_delay_coefficient=5.0, max_queue_delay_ms=50.0)
    sim = Simulation(topology, [flow], {"f0": Route.build(topology, ["e0"])}, config)

    sample = sim.step().samples[0]

    # prop 7 + queue 5/(10-5)=1 + processing (2 + 3) = 13
    assert sample.latency_ms == APPROX(13.0)


def test_latency_is_none_when_nothing_was_delivered() -> None:
    """docs/03-simulation-model.md §7: averaging undelivered traffic in as zero latency
    would make a congested run look faster than a healthy one."""
    topology = line_topology([0.0])
    sample = single_flow_sim(topology, 5.0, ["e0"]).step().samples[0]

    assert sample.delivered_mbps == 0.0
    assert sample.latency_ms is None


def test_a_blackholed_flow_has_no_latency() -> None:
    topology = line_topology([10.0], state=LinkState.DOWN)
    sample = single_flow_sim(topology, 5.0, ["e0"]).step().samples[0]

    assert sample.blackholed
    assert sample.latency_ms is None
    assert sample.delivered_mbps == 0.0


def test_queue_delay_grows_as_a_link_fills_and_is_capped() -> None:
    delay = [
        queue_delay_ms(100.0, load, coefficient=1.0, maximum_ms=50.0)
        for load in (0.0, 50.0, 90.0, 99.0, 99.99)
    ]
    assert delay == sorted(delay), "delay must be monotone in load"
    assert delay[-1] == APPROX(50.0), "capped at q_max"


def test_a_saturated_link_reports_the_ceiling_rather_than_dividing_by_zero() -> None:
    assert queue_delay_ms(10.0, 10.0, coefficient=1.0, maximum_ms=50.0) == 50.0
    assert queue_delay_ms(0.0, 0.0, coefficient=1.0, maximum_ms=50.0) == 50.0


# ---------------------------------------------------------------------- run summary


def test_summary_reports_delivery_ratio_per_class_and_overall() -> None:
    """10 Mbps shared by a CRITICAL flow wanting 8 and a LOW flow wanting 8: strict
    priority gives 8 and 2, so the class PDRs are 1.0 and 0.25."""
    topology = line_topology([10.0])
    flows = [
        Flow("f_crit", "n0", "n1", demand_mbps=8.0, priority=Priority.CRITICAL),
        Flow("f_low", "n0", "n1", demand_mbps=8.0, priority=Priority.LOW),
    ]
    routing = {flow.id: Route.build(topology, ["e0"]) for flow in flows}

    summary = Simulation(topology, flows, routing, NEGLIGIBLE_QUEUEING).measure(10)

    assert summary.ticks == 10
    assert summary.duration_s == APPROX(1.0)
    assert summary.by_priority[Priority.CRITICAL].pdr == APPROX(1.0)
    assert summary.by_priority[Priority.LOW].pdr == APPROX(0.25)
    assert summary.overall.pdr == APPROX(10.0 / 16.0)


def test_summary_reports_only_the_classes_that_appeared() -> None:
    topology = line_topology([10.0])
    flow = Flow("f0", "n0", "n1", demand_mbps=1.0, priority=Priority.HIGH)
    summary = Simulation(topology, [flow], {"f0": Route.build(topology, ["e0"])}).measure(3)

    assert set(summary.by_priority) == {Priority.HIGH}


def test_summary_orders_classes_by_descending_precedence() -> None:
    topology = line_topology([10.0])
    flows = [
        Flow("f_low", "n0", "n1", demand_mbps=1.0, priority=Priority.LOW),
        Flow("f_crit", "n0", "n1", demand_mbps=1.0, priority=Priority.CRITICAL),
    ]
    routing = {flow.id: Route.build(topology, ["e0"]) for flow in flows}
    summary = Simulation(topology, flows, routing).measure(2)

    assert list(summary.by_priority) == [Priority.CRITICAL, Priority.LOW]


def test_throughput_is_the_mean_delivered_rate_over_the_window() -> None:
    sim = single_flow_sim(line_topology([10.0]), 4.0, ["e0"])
    summary = sim.measure(10)

    assert summary.overall.delivered_mbit == APPROX(4.0)  # 4 Mbps for 1.0 s
    assert summary.overall.throughput_mbps == APPROX(4.0)


def test_blackholed_flow_ticks_are_counted() -> None:
    topology = line_topology([10.0], state=LinkState.DOWN)
    summary = single_flow_sim(topology, 5.0, ["e0"]).measure(7)

    assert summary.overall.blackholed_flow_ticks == 7
    assert summary.overall.flow_ticks == 7
    assert summary.overall.pdr == APPROX(0.0), "demand existed and none of it arrived"


def test_a_class_that_demanded_nothing_reports_no_ratio_rather_than_a_fabricated_one() -> None:
    topology = line_topology([10.0])
    flow = Flow("f0", "n0", "n1", demand_mbps=0.0)
    summary = Simulation(topology, [flow], {"f0": Route.build(topology, ["e0"])}).measure(3)

    assert summary.overall.pdr is None
    assert summary.overall.mean_latency_ms is None


def test_latency_aggregates_are_weighted_by_delivered_traffic() -> None:
    """A flow carrying ten times the traffic must pull the mean ten times as hard."""
    nodes = [Node("n0"), Node("n1"), Node("n2")]
    links = [
        Link("slow", "n0", "n1", capacity_mbps=100.0, prop_delay_ms=100.0),
        Link("fast", "n0", "n2", capacity_mbps=100.0, prop_delay_ms=10.0),
    ]
    topology = Topology(nodes, links)
    flows = [
        Flow("f_small", "n0", "n1", demand_mbps=1.0),
        Flow("f_big", "n0", "n2", demand_mbps=9.0),
    ]
    routing = {
        "f_small": Route.build(topology, ["slow"]),
        "f_big": Route.build(topology, ["fast"]),
    }

    summary = Simulation(topology, flows, routing, NEGLIGIBLE_QUEUEING).measure(1)

    # (1*100 + 9*10) / 10 = 19, not the unweighted mean of 55.
    assert summary.overall.mean_latency_ms == APPROX(19.0)


def test_metrics_accumulator_rejects_a_nonpositive_tick_length() -> None:
    with pytest.raises(ValidationError, match="tick_seconds"):
        MetricsAccumulator(0.0)


# ---------------------------------------------------------------- config validation


@pytest.mark.parametrize("bad", [0, -1, 1.5, True])
def test_config_rejects_an_unusable_tick_length(bad: object) -> None:
    with pytest.raises(ValidationError, match="tick_ms"):
        SimulationConfig(tick_ms=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"), [("queue_delay_coefficient", -1.0), ("max_queue_delay_ms", -1.0)]
)
def test_config_rejects_negative_latency_parameters(field: str, value: float) -> None:
    with pytest.raises(ValidationError, match=field):
        SimulationConfig(**{field: value})  # type: ignore[arg-type]


def test_a_non_default_tick_length_changes_simulated_time_not_the_rates() -> None:
    topology = line_topology([10.0])
    flow = Flow("f0", "n0", "n1", demand_mbps=4.0)
    routing = {"f0": Route.build(topology, ["e0"])}

    coarse = Simulation(topology, [flow], routing, SimulationConfig(tick_ms=1000)).measure(1)
    fine = Simulation(topology, [flow], routing, SimulationConfig(tick_ms=100)).measure(10)

    assert coarse.duration_s == APPROX(fine.duration_s)
    assert coarse.overall.delivered_mbit == APPROX(fine.overall.delivered_mbit)


# ------------------------------------------------------------ construction validation


def test_the_simulation_validates_its_routing_once_at_construction() -> None:
    topology = line_topology([10.0, 10.0])
    flow = Flow("f0", "n0", "n2", demand_mbps=1.0)
    wrong_route = Route.build(topology, ["e0"])

    with pytest.raises(ValidationError, match="but the flow demands"):
        Simulation(topology, [flow], {"f0": wrong_route})


def test_the_simulation_rejects_a_flow_whose_endpoints_are_not_in_the_topology() -> None:
    topology = line_topology([10.0])
    with pytest.raises(ValidationError, match="not a node in this topology"):
        Simulation(topology, [Flow("f0", "ghost", "n1", demand_mbps=1.0)], {})


# ------------------------------------------------------------------ properties


@given(scenarios())
@PROPERTY_SETTINGS
def test_derived_metrics_stay_within_their_definitions(scenario: Scenario) -> None:
    """Bounds that follow from the definitions in docs/03-simulation-model.md §4.

    Reuses the congestion-biased generator from test_properties.py, so these run against
    the same contended, partially-failed topologies the allocator invariants do.
    """
    topology, flows, routing = scenario
    for result in Simulation(topology, flows, routing).run(3):
        for sample in result.samples:
            scale = max(1.0, sample.demand_mbps)
            assert 0.0 <= sample.allocated_mbps <= sample.demand_mbps + invariants.TOL * scale
            assert 0.0 <= sample.delivered_mbps <= sample.allocated_mbps + invariants.TOL * scale
            assert 0.0 <= sample.intrinsic_loss <= 1.0
            assert 0.0 <= sample.congestive_loss <= 1.0
            assert (sample.latency_ms is None) == (
                sample.delivered_mbps <= 0.0
            ), "latency must be recorded exactly when traffic was delivered"
            assert sample.latency_ms is None or sample.latency_ms >= 0.0
            if sample.blackholed:
                assert sample.delivered_mbps == 0.0


@given(scenarios())
@PROPERTY_SETTINGS
def test_delivery_ratios_are_proper_fractions(scenario: Scenario) -> None:
    topology, flows, routing = scenario
    summary = Simulation(topology, flows, routing).measure(3)
    for metrics in (summary.overall, *summary.by_priority.values()):
        assert metrics.delivered_mbit <= metrics.demanded_mbit + invariants.TOL
        assert metrics.pdr is None or 0.0 <= metrics.pdr <= 1.0 + invariants.TOL


@given(scenarios())
@PROPERTY_SETTINGS
def test_a_run_replays_identically_after_reset(scenario: Scenario) -> None:
    """I-DET over the whole loop, not just one allocation."""
    topology, flows, routing = scenario
    sim = Simulation(topology, flows, routing)

    def trace() -> list[tuple[object, ...]]:
        return [
            (s.flow_id, s.delivered_mbps, s.latency_ms, s.blackholed)
            for result in sim.run(4)
            for s in result.samples
        ]

    first = trace()
    sim.reset()
    assert trace() == first
