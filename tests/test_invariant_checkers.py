"""Tests for the invariant checkers themselves.

A property suite that cannot fail is worse than no property suite, because it reports
confidence it has not earned. `check_strict_priority` and `check_max_min_fair_within_class`
in particular have guard clauses that skip cases where the invariant says nothing — a typo
in one of those would silently turn the checker into a no-op that passes forever.

So each checker is handed a hand-built allocation that violates exactly the property it
owns, and is required to reject it. The allocations here are fabricated, not produced by
`allocate`; the point is to exercise the checker, not the allocator.
"""

from __future__ import annotations

import pytest

from orbit.engine.allocator import Allocation
from orbit.model import Flow, Link, Node, Priority, Route, Topology
from tests import invariants


def one_link(capacity: float) -> Topology:
    return Topology([Node("n0"), Node("n1")], [Link("e0", "n0", "n1", capacity_mbps=capacity)])


def fabricate(rates: dict[str, float], link_load: dict[str, float]) -> Allocation:
    return Allocation(rates=rates, link_load=link_load, blackholed=frozenset())


def test_check_capacity_rejects_an_overloaded_link() -> None:
    with pytest.raises(AssertionError, match="I-CAP violated"):
        invariants.check_capacity(one_link(10.0), fabricate({}, {"e0": 20.0}))


def test_check_demand_rejects_a_flow_given_more_than_it_asked_for() -> None:
    flow = Flow("f0", "n0", "n1", demand_mbps=5.0)
    with pytest.raises(AssertionError, match="I-DEMAND violated"):
        invariants.check_demand([flow], fabricate({"f0": 7.0}, {"e0": 7.0}))


def test_check_no_traffic_over_failed_elements_rejects_delivery_over_a_down_link() -> None:
    topology = Topology(
        [Node("n0"), Node("n1")],
        [Link("e0", "n0", "n1", capacity_mbps=10.0, state="DOWN")],
    )
    flow = Flow("f0", "n0", "n1", demand_mbps=5.0)
    routing = {"f0": Route.build(topology, ["e0"])}

    with pytest.raises(AssertionError, match="I-DOWN violated"):
        invariants.check_no_traffic_over_failed_elements(
            topology, [flow], routing, fabricate({"f0": 5.0}, {"e0": 5.0})
        )


def test_check_no_silent_loss_rejects_a_shortfall_with_no_saturated_link() -> None:
    topology = one_link(10.0)
    flow = Flow("f0", "n0", "n1", demand_mbps=10.0)
    routing = {"f0": Route.build(topology, ["e0"])}

    with pytest.raises(AssertionError, match="demand was lost with no cause"):
        invariants.check_no_silent_loss(
            topology, [flow], routing, fabricate({"f0": 4.0}, {"e0": 4.0})
        )


def test_check_strict_priority_rejects_a_low_flow_holding_a_criticals_bottleneck() -> None:
    """The 10 Mbps link is full, but 6 of it went to LOW while CRITICAL went short."""
    topology = one_link(10.0)
    flows = [
        Flow("f_crit", "n0", "n1", demand_mbps=10.0, priority=Priority.CRITICAL),
        Flow("f_low", "n0", "n1", demand_mbps=6.0, priority=Priority.LOW),
    ]
    routing = {flow.id: Route.build(topology, ["e0"]) for flow in flows}

    with pytest.raises(AssertionError, match="I-PRIO violated"):
        invariants.check_strict_priority(
            topology, flows, routing, fabricate({"f_crit": 4.0, "f_low": 6.0}, {"e0": 10.0})
        )


def test_check_strict_priority_accepts_the_correct_split() -> None:
    """Guards against a checker that rejects everything, which would be equally useless."""
    topology = one_link(10.0)
    flows = [
        Flow("f_crit", "n0", "n1", demand_mbps=10.0, priority=Priority.CRITICAL),
        Flow("f_low", "n0", "n1", demand_mbps=6.0, priority=Priority.LOW),
    ]
    routing = {flow.id: Route.build(topology, ["e0"]) for flow in flows}

    invariants.check_strict_priority(
        topology, flows, routing, fabricate({"f_crit": 10.0, "f_low": 0.0}, {"e0": 10.0})
    )


def test_check_max_min_rejects_an_unfair_split_within_one_class() -> None:
    """Both flows want 10 of a full 10 Mbps link; 2/8 is feasible but not max-min fair."""
    topology = one_link(10.0)
    flows = [
        Flow("f0", "n0", "n1", demand_mbps=10.0),
        Flow("f1", "n0", "n1", demand_mbps=10.0),
    ]
    routing = {flow.id: Route.build(topology, ["e0"]) for flow in flows}

    with pytest.raises(AssertionError, match="I-MAXMIN violated"):
        invariants.check_max_min_fair_within_class(
            topology, flows, routing, fabricate({"f0": 2.0, "f1": 8.0}, {"e0": 10.0})
        )


def test_check_max_min_accepts_the_equal_split() -> None:
    topology = one_link(10.0)
    flows = [
        Flow("f0", "n0", "n1", demand_mbps=10.0),
        Flow("f1", "n0", "n1", demand_mbps=10.0),
    ]
    routing = {flow.id: Route.build(topology, ["e0"]) for flow in flows}

    invariants.check_max_min_fair_within_class(
        topology, flows, routing, fabricate({"f0": 5.0, "f1": 5.0}, {"e0": 10.0})
    )


def test_check_blackholing_rejects_a_mislabelled_flow() -> None:
    topology = one_link(10.0)
    flow = Flow("f0", "n0", "n1", demand_mbps=10.0)
    routing = {"f0": Route.build(topology, ["e0"])}
    mislabelled = Allocation(rates={"f0": 0.0}, link_load={}, blackholed=frozenset({"f0"}))

    with pytest.raises(AssertionError, match="blackholed=True"):
        invariants.check_blackholing_is_accurate(topology, [flow], routing, mislabelled)
