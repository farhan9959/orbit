"""LP optimality bound and the new recovery metrics."""

from __future__ import annotations

import pytest

from orbit.algorithms import BASELINES, OrbitController
from orbit.engine import allocate, peak_restore_fraction, time_to_converge
from orbit.errors import ValidationError
from orbit.model import Flow, GraphView, Link, Node, Topology
from orbit.optimal import MAX_LP_NODES, lp_upper_bound, optimality_gap, weighted_served
from orbit.scenarios import (
    FailureScenario,
    ScenarioSpec,
    TopologyFamily,
    build_topology,
    build_traffic,
)


def test_the_bound_is_never_below_what_an_algorithm_achieves() -> None:
    spec = ScenarioSpec(
        family=TopologyFamily.WAXMAN,
        nodes=12,
        flows=25,
        offered_load=0.9,
        ticks=10,
        failure=FailureScenario.NONE,
    )
    seed = spec.seed_for(0)
    topology = build_topology(spec, seed)
    flows = build_traffic(spec, topology, seed)
    bound = lp_upper_bound(topology, flows)
    assert bound is not None and bound > 0.0

    view = GraphView(topology, 0, changed=True)
    for name in (*sorted(BASELINES), "orbit"):
        algorithm = OrbitController() if name == "orbit" else BASELINES[name]()
        allocation = allocate(topology, flows, algorithm.recompute(view, flows, {}))
        achieved = weighted_served(flows, dict(allocation.rates))
        gap = optimality_gap(bound, achieved)
        assert achieved <= bound + 1e-6, f"{name} beat the upper bound"
        assert gap is not None and gap >= 0.0


def test_a_single_link_bound_is_exactly_the_capacity_times_the_weight() -> None:
    topology = Topology([Node("n0"), Node("n1")], [Link("e0", "n0", "n1", capacity_mbps=10.0)])
    flows = [Flow("f0", "n0", "n1", demand_mbps=100.0)]
    from orbit.algorithms.orbit_controller import PRIORITY_WEIGHTS

    assert lp_upper_bound(topology, flows) == pytest.approx(
        10.0 * PRIORITY_WEIGHTS[flows[0].priority]
    )


def test_the_bound_respects_failures() -> None:
    topology = Topology(
        [Node("n0"), Node("n1")],
        [Link("e0", "n0", "n1", capacity_mbps=10.0, state="DOWN")],
    )
    flows = [Flow("f0", "n0", "n1", demand_mbps=100.0)]
    assert lp_upper_bound(topology, flows) == 0.0


def test_the_bound_refuses_topologies_it_was_not_intended_for() -> None:
    spec = ScenarioSpec(family=TopologyFamily.WAXMAN, nodes=40, flows=5, ticks=5)
    topology = build_topology(spec, spec.seed_for(0))
    with pytest.raises(ValidationError, match=f"at most {MAX_LP_NODES}"):
        lp_upper_bound(topology, [])


def test_gap_is_none_rather_than_fabricated_when_the_bound_is_unusable() -> None:
    assert optimality_gap(None, 5.0) is None
    assert optimality_gap(0.0, 5.0) is None


def test_time_to_converge_measures_the_quiet_period_after_the_last_change() -> None:
    assert time_to_converge([10, 11, 12], failure_tick=10, last_tick=20, tick_seconds=0.1) == (
        pytest.approx(0.3)
    )


def test_time_to_converge_is_zero_when_nothing_changed_after_the_failure() -> None:
    assert time_to_converge([], failure_tick=5, last_tick=20, tick_seconds=0.1) == 0.0


def test_time_to_converge_is_none_when_the_run_ends_before_it_settles() -> None:
    assert time_to_converge([19], failure_tick=5, last_tick=20, tick_seconds=0.1) is None


def test_peak_restore_fraction_explains_a_censored_run() -> None:
    series = [10.0] * 5 + [4.0] * 5
    assert peak_restore_fraction(series, failure_tick=5) == pytest.approx(0.4)


def test_peak_restore_fraction_can_exceed_one_when_delivery_improves() -> None:
    series = [10.0] * 5 + [12.0] * 5
    assert peak_restore_fraction(series, failure_tick=5) == pytest.approx(1.2)
