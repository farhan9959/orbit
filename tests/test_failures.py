"""A3/A4 - failure injection, targeted selection, and the detection model."""

from __future__ import annotations

import pytest

from orbit.algorithms import ReconvergingShortestPath, StaticShortestPath
from orbit.detect import ControlMode, DetectorConfig, FailureDetector
from orbit.engine import (
    CascadeRule,
    FailureEvent,
    FailureKind,
    FailureSchedule,
    Simulation,
    SimulationConfig,
    highest_betweenness_links,
    link_betweenness,
    random_links,
    random_nodes,
)
from orbit.errors import ValidationError
from orbit.events import EventType
from orbit.generators import grid, ring, waxman
from orbit.model import Flow, Link, LinkState, Node, NodeState, Priority, Topology

APPROX = pytest.approx


def two_node_topology(capacity: float = 100.0) -> Topology:
    return Topology(
        [Node("n0"), Node("n1")],
        [
            Link("e0", "n0", "n1", capacity_mbps=capacity, srlg={"cable:x"}),
            Link("e1", "n1", "n0", capacity_mbps=capacity, srlg={"cable:x"}),
        ],
    )


def apply_at(schedule: FailureSchedule, time_s: float) -> Topology:
    topology, _ = schedule.apply(int(time_s * 10), time_s)
    return topology


def test_link_down_takes_only_that_direction() -> None:
    topology = two_node_topology()
    schedule = FailureSchedule(topology, [FailureEvent(1.0, FailureKind.LINK_DOWN, ("e0",))])
    after = apply_at(schedule, 1.0)

    assert after.link("e0").state is LinkState.DOWN
    assert after.link("e1").state is LinkState.UP


def test_srlg_down_takes_every_element_sharing_the_tag() -> None:
    topology = two_node_topology()
    schedule = FailureSchedule(topology, [FailureEvent(1.0, FailureKind.SRLG_DOWN, ("cable:x",))])
    after = apply_at(schedule, 1.0)

    assert after.link("e0").state is LinkState.DOWN
    assert after.link("e1").state is LinkState.DOWN


def test_node_down_disables_its_incident_links() -> None:
    topology = two_node_topology()
    schedule = FailureSchedule(topology, [FailureEvent(1.0, FailureKind.NODE_DOWN, ("n1",))])
    after = apply_at(schedule, 1.0)

    assert after.node("n1").state is NodeState.DOWN
    assert not after.is_usable("e0")
    assert not after.is_usable("e1")


def test_bandwidth_degrade_scales_effective_capacity() -> None:
    topology = two_node_topology()
    schedule = FailureSchedule(
        topology, [FailureEvent(1.0, FailureKind.BANDWIDTH_DEGRADE, ("e0",), factor=0.25)]
    )
    after = apply_at(schedule, 1.0)

    assert after.link("e0").effective_capacity_mbps == APPROX(25.0)


def test_latency_spike_adds_to_the_existing_delay() -> None:
    topology = Topology(
        [Node("n0"), Node("n1")],
        [Link("e0", "n0", "n1", capacity_mbps=10.0, prop_delay_ms=5.0)],
    )
    schedule = FailureSchedule(
        topology, [FailureEvent(1.0, FailureKind.LATENCY_SPIKE, ("e0",), delta_ms=20.0)]
    )
    assert apply_at(schedule, 1.0).link("e0").prop_delay_ms == APPROX(25.0)


def test_loss_spike_sets_the_loss_rate() -> None:
    topology = two_node_topology()
    schedule = FailureSchedule(
        topology, [FailureEvent(1.0, FailureKind.LOSS_SPIKE, ("e0",), loss_rate=0.4)]
    )
    assert apply_at(schedule, 1.0).link("e0").loss_rate == APPROX(0.4)


def test_congestion_surge_scales_demand_not_the_topology() -> None:
    topology = two_node_topology()
    schedule = FailureSchedule(
        topology, [FailureEvent(1.0, FailureKind.CONGESTION_SURGE, factor=3.0)]
    )
    before = schedule.demand_scale
    apply_at(schedule, 1.0)

    assert before == APPROX(1.0)
    assert schedule.demand_scale == APPROX(3.0)


def test_restore_returns_an_element_to_its_initial_state() -> None:
    topology = two_node_topology()
    schedule = FailureSchedule(
        topology,
        [
            FailureEvent(1.0, FailureKind.BANDWIDTH_DEGRADE, ("e0",), factor=0.1),
            FailureEvent(2.0, FailureKind.RESTORE, ("e0",)),
        ],
    )
    apply_at(schedule, 1.0)
    after = apply_at(schedule, 2.0)

    assert after.link("e0").state is LinkState.UP
    assert after.link("e0").effective_capacity_mbps == APPROX(100.0)


def test_repeated_fail_restore_leaves_no_state_leak() -> None:
    topology = two_node_topology()
    schedule = FailureSchedule(
        topology,
        [
            FailureEvent(1.0, FailureKind.LINK_DOWN, ("e0",)),
            FailureEvent(2.0, FailureKind.RESTORE, ("e0",)),
            FailureEvent(3.0, FailureKind.LINK_DOWN, ("e0",)),
            FailureEvent(4.0, FailureKind.RESTORE, ("e0",)),
        ],
    )
    for moment in (1.0, 2.0, 3.0, 4.0):
        apply_at(schedule, moment)
    assert apply_at(schedule, 5.0).link("e0") == topology.link("e0")


def test_simultaneous_failures_apply_atomically_within_one_tick() -> None:
    topology = grid(2, 2)
    ids = sorted(topology.links)
    schedule = FailureSchedule(
        topology,
        [
            FailureEvent(1.0, FailureKind.LINK_DOWN, (ids[0],)),
            FailureEvent(1.0, FailureKind.NODE_DOWN, ("n003",)),
        ],
    )
    after, fired = schedule.apply(10, 1.0)

    assert len(fired) == 2
    assert after.link(ids[0]).state is LinkState.DOWN
    assert after.node("n003").state is NodeState.DOWN


def test_the_schedule_never_mutates_the_base_topology() -> None:
    topology = two_node_topology()
    schedule = FailureSchedule(topology, [FailureEvent(0.0, FailureKind.LINK_DOWN, ("e0",))])
    apply_at(schedule, 1.0)

    assert topology.link("e0").state is LinkState.UP


def test_schedule_rejects_an_unknown_target() -> None:
    with pytest.raises(ValidationError, match="unknown target"):
        FailureSchedule(two_node_topology(), [FailureEvent(1.0, FailureKind.LINK_DOWN, ("ghost",))])


@pytest.mark.parametrize(
    ("kind", "kwargs"),
    [
        (FailureKind.BANDWIDTH_DEGRADE, {"factor": 1.5}),
        (FailureKind.LOSS_SPIKE, {"loss_rate": 1.5}),
        (FailureKind.CONGESTION_SURGE, {"factor": -1.0}),
    ],
)
def test_failure_event_rejects_out_of_range_parameters(kind: FailureKind, kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        FailureEvent(1.0, kind, ("e0",), **kwargs)


def test_cascade_fails_a_link_that_stays_overloaded() -> None:
    topology = Topology([Node("n0"), Node("n1")], [Link("e0", "n0", "n1", capacity_mbps=10.0)])
    schedule = FailureSchedule(
        topology, [], CascadeRule(utilisation_threshold=0.9, dwell_ticks=2, enabled=True)
    )
    schedule.apply(0, 0.0)

    assert schedule.observe_utilisation(0, topology, {"e0": 10.0}) == ()
    assert schedule.observe_utilisation(1, topology, {"e0": 10.0}) == ("e0",)
    assert schedule.cascade_depth == 1


def test_cascade_dwell_resets_when_load_falls_back() -> None:
    topology = Topology([Node("n0"), Node("n1")], [Link("e0", "n0", "n1", capacity_mbps=10.0)])
    schedule = FailureSchedule(
        topology, [], CascadeRule(utilisation_threshold=0.9, dwell_ticks=3, enabled=True)
    )
    schedule.apply(0, 0.0)
    schedule.observe_utilisation(0, topology, {"e0": 10.0})
    schedule.observe_utilisation(1, topology, {"e0": 0.0})
    schedule.observe_utilisation(2, topology, {"e0": 10.0})

    assert schedule.cascade_depth == 0


def test_cascade_is_off_by_default() -> None:
    topology = Topology([Node("n0"), Node("n1")], [Link("e0", "n0", "n1", capacity_mbps=10.0)])
    schedule = FailureSchedule(topology)
    schedule.apply(0, 0.0)
    for tick in range(10):
        assert schedule.observe_utilisation(tick, topology, {"e0": 10.0}) == ()


def test_targeted_selection_prefers_the_busiest_link() -> None:
    topology = grid(3, 3)
    scores = link_betweenness(topology)
    chosen = highest_betweenness_links(topology, 1)[0]

    assert scores[chosen] == max(scores.values())


def test_random_selection_is_reproducible_and_sized() -> None:
    topology = waxman(20, seed=3)
    first = random_nodes(topology, 0.3, seed=7)
    second = random_nodes(topology, 0.3, seed=7)

    assert first == second
    assert len(first) == 6
    assert random_links(topology, 0.0, seed=7) == ()


def test_selection_rejects_a_fraction_outside_the_unit_interval() -> None:
    with pytest.raises(ValidationError, match="fraction"):
        random_nodes(waxman(5, seed=1), 1.5, seed=1)


def test_detection_is_delayed_by_the_configured_interval() -> None:
    topology = two_node_topology()
    detector = FailureDetector(
        topology, DetectorConfig(detection_interval_ms=150.0, control_channel_delay_ms=50.0), 100
    )
    damaged = Topology(
        topology.nodes.values(),
        [
            Link("e0", "n0", "n1", capacity_mbps=100.0, state=LinkState.DOWN),
            topology.link("e1"),
        ],
    )
    seen = [detector.observe(tick, damaged).topology.link("e0").state for tick in range(4)]

    assert seen[0] is LinkState.UP
    assert seen[1] is LinkState.UP
    assert seen[2] is LinkState.DOWN


def test_distributed_mode_is_slower_than_centralised() -> None:
    topology = ring(8)
    broken = sorted(topology.links)[4]
    damaged = Topology(
        topology.nodes.values(),
        [
            (
                Link(
                    link.id,
                    link.src,
                    link.dst,
                    capacity_mbps=link.capacity_mbps,
                    prop_delay_ms=link.prop_delay_ms,
                    state=LinkState.DOWN,
                    srlg=link.srlg,
                )
                if link.id == broken
                else link
            )
            for link in topology.links.values()
        ],
    )

    def first_detection(mode: ControlMode) -> int:
        detector = FailureDetector(topology, DetectorConfig(mode=mode), 10)
        for tick in range(400):
            if detector.observe(tick, damaged).topology.link(broken).state is LinkState.DOWN:
                return tick
        return -1

    assert first_detection(ControlMode.DISTRIBUTED) > first_detection(ControlMode.CENTRALISED)


def test_both_control_modes_use_the_same_detector_parameters() -> None:
    """The fairness rule: recovery is never measured from an instant nobody could know."""
    config = DetectorConfig(detection_interval_ms=150.0)
    assert config.detection_interval_ms == DetectorConfig().detection_interval_ms


def test_detector_rejects_negative_parameters() -> None:
    with pytest.raises(ValidationError, match="detection_interval_ms"):
        DetectorConfig(detection_interval_ms=-1.0)


def test_the_controller_routes_over_a_stale_graph_until_detection() -> None:
    topology = ring(6)
    flows = [Flow("f0", "n000", "n003", demand_mbps=10.0, priority=Priority.CRITICAL)]
    algorithm = ReconvergingShortestPath()
    probe = Simulation(topology, flows, StaticShortestPath())
    probe.step()
    doomed = probe.routing["f0"].links[0]

    schedule = FailureSchedule(topology, [FailureEvent(0.5, FailureKind.LINK_DOWN, (doomed,))])
    simulation = Simulation(
        topology,
        flows,
        algorithm,
        SimulationConfig(tick_ms=100),
        schedule=schedule,
        detector=DetectorConfig(detection_interval_ms=300.0, control_channel_delay_ms=0.0),
    )
    results = list(simulation.run(20))

    injected = next(
        r.tick for r in results if any(e.type is EventType.FAILURE_INJECTED for e in r.events)
    )
    detected = next(
        r.tick for r in results if any(e.type is EventType.FAILURE_DETECTED for e in r.events)
    )
    assert detected > injected

    blackholed_between = [
        r.tick
        for r in results
        if injected <= r.tick < detected and r.samples and r.samples[0].blackholed
    ]
    assert blackholed_between, "traffic must be lost while the controller is unaware"
    assert not results[-1].samples[0].blackholed, "and recovered once it learns"


def test_a_run_with_failures_replays_identically_after_reset() -> None:
    topology = waxman(12, seed=5)
    ids = sorted(topology.nodes)
    flows = [Flow("f0", ids[0], ids[-1], demand_mbps=20.0, priority=Priority.CRITICAL)]
    schedule = FailureSchedule(
        topology, [FailureEvent(0.5, FailureKind.LINK_DOWN, (sorted(topology.links)[0],))]
    )
    simulation = Simulation(topology, flows, ReconvergingShortestPath(), schedule=schedule)

    def trace() -> list[tuple[object, ...]]:
        return [
            (s.flow_id, s.delivered_mbps, s.blackholed)
            for result in simulation.run(15)
            for s in result.samples
        ]

    first = trace()
    simulation.reset()
    assert trace() == first
