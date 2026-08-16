"""A2 — worked examples for the max-min allocator, with hand-computed expected values.

Every expected number here is derived by hand from the definition in
docs/03-simulation-model.md §4, not copied from the implementation's output. A test that
records what the code currently does proves only that the code has not changed.
"""

from __future__ import annotations

import pytest

from orbit.engine import Allocation, allocate
from orbit.errors import ValidationError
from orbit.model import (
    Flow,
    Link,
    LinkState,
    Node,
    NodeState,
    Priority,
    Route,
    RoutingState,
    Topology,
)
from tests import invariants

APPROX = pytest.approx


def line_topology(capacities: list[float], **link_kwargs: object) -> Topology:
    """`n0 -> n1 -> ... -> nN` with `e{i}` carrying `capacities[i]`."""
    nodes = [Node(f"n{i}") for i in range(len(capacities) + 1)]
    links = [
        Link(f"e{i}", f"n{i}", f"n{i + 1}", capacity_mbps=capacity, **link_kwargs)  # type: ignore[arg-type]
        for i, capacity in enumerate(capacities)
    ]
    return Topology(nodes, links)


def run(topology: Topology, flows: list[Flow], routing: RoutingState) -> Allocation:
    """Allocate, then assert every invariant. Invariants are not optional in any test."""
    allocation = allocate(topology, flows, routing)
    invariants.check_all(topology, flows, routing, allocation)
    return allocation


# ------------------------------------------------------------------ single flow


def test_a_lone_flow_receives_its_full_demand_when_capacity_allows() -> None:
    topology = line_topology([10.0, 10.0])
    flow = Flow("f0", "n0", "n2", demand_mbps=4.0)
    routing = {"f0": Route.build(topology, ["e0", "e1"])}

    allocation = run(topology, [flow], routing)

    assert allocation.rates["f0"] == APPROX(4.0)
    assert allocation.load_on("e0") == APPROX(4.0)
    assert allocation.load_on("e1") == APPROX(4.0)
    assert allocation.blackholed == frozenset()


def test_a_lone_flow_is_capped_by_the_tightest_link_on_its_path() -> None:
    """The bottleneck is the minimum capacity along the route, not the first link."""
    topology = line_topology([10.0, 4.0, 10.0])
    flow = Flow("f0", "n0", "n3", demand_mbps=8.0)
    routing = {"f0": Route.build(topology, ["e0", "e1", "e2"])}

    allocation = run(topology, [flow], routing)

    assert allocation.rates["f0"] == APPROX(4.0)


def test_demand_exactly_equal_to_capacity_is_fully_served() -> None:
    topology = line_topology([10.0])
    flow = Flow("f0", "n0", "n1", demand_mbps=10.0)
    routing = {"f0": Route.build(topology, ["e0"])}

    allocation = run(topology, [flow], routing)

    assert allocation.rates["f0"] == APPROX(10.0)
    assert allocation.load_on("e0") == APPROX(10.0)


# ------------------------------------------------------- competing flows, one class


def test_two_flows_split_a_shared_bottleneck_equally() -> None:
    """e1 has 6 Mbps and two flows want 10 each, so max-min gives 3 each."""
    topology = line_topology([10.0, 6.0, 10.0])
    flows = [
        Flow("fa", "n0", "n3", demand_mbps=10.0),
        Flow("fb", "n1", "n2", demand_mbps=10.0),
    ]
    routing = {
        "fa": Route.build(topology, ["e0", "e1", "e2"]),
        "fb": Route.build(topology, ["e1"]),
    }

    allocation = run(topology, flows, routing)

    assert allocation.rates["fa"] == APPROX(3.0)
    assert allocation.rates["fb"] == APPROX(3.0)
    assert allocation.load_on("e1") == APPROX(6.0)


def test_a_modest_demand_leaves_its_surplus_to_the_greedier_flow() -> None:
    """The defining behaviour of max-min: fa needs only 2 of its 3-Mbps share, so the
    spare 1 Mbps is redistributed and fb ends on 4, not 3."""
    topology = line_topology([10.0, 6.0, 10.0])
    flows = [
        Flow("fa", "n0", "n3", demand_mbps=2.0),
        Flow("fb", "n1", "n2", demand_mbps=10.0),
    ]
    routing = {
        "fa": Route.build(topology, ["e0", "e1", "e2"]),
        "fb": Route.build(topology, ["e1"]),
    }

    allocation = run(topology, flows, routing)

    assert allocation.rates["fa"] == APPROX(2.0)
    assert allocation.rates["fb"] == APPROX(4.0)


def test_parking_lot_topology_gives_every_flow_the_same_fair_share() -> None:
    """The textbook case: one long flow crossing three 10-Mbps links, each also carrying
    one short flow. Every link is shared by exactly two flows, so all four get 5."""
    topology = line_topology([10.0, 10.0, 10.0])
    flows = [
        Flow("f_long", "n0", "n3", demand_mbps=10.0),
        Flow("f_a", "n0", "n1", demand_mbps=10.0),
        Flow("f_b", "n1", "n2", demand_mbps=10.0),
        Flow("f_c", "n2", "n3", demand_mbps=10.0),
    ]
    routing = {
        "f_long": Route.build(topology, ["e0", "e1", "e2"]),
        "f_a": Route.build(topology, ["e0"]),
        "f_b": Route.build(topology, ["e1"]),
        "f_c": Route.build(topology, ["e2"]),
    }

    allocation = run(topology, flows, routing)

    for flow_id in ("f_long", "f_a", "f_b", "f_c"):
        assert allocation.rates[flow_id] == APPROX(5.0)


def test_the_tightest_link_decides_and_nobody_grows_past_it() -> None:
    """e0 offers 3 Mbps to three flows and e1 offers 9 Mbps to two of them.

    The water level rises to min(3/3, 9/2) = 1.0, at which point e0 is saturated. All
    three flows cross e0, so all three stop at 1.0 and e1 is left holding only 2 of its 9
    — the correct outcome, and a case where a naive per-link split would over-allocate.
    """
    nodes = [Node("n0"), Node("n1"), Node("n2")]
    links = [
        Link("e0", "n0", "n1", capacity_mbps=3.0),
        Link("e1", "n1", "n2", capacity_mbps=9.0),
    ]
    topology = Topology(nodes, links)
    flows = [
        Flow("fa", "n0", "n1", demand_mbps=100.0),
        Flow("fb", "n0", "n2", demand_mbps=100.0),
        Flow("fc", "n0", "n2", demand_mbps=100.0),
    ]
    routing = {
        "fa": Route.build(topology, ["e0"]),
        "fb": Route.build(topology, ["e0", "e1"]),
        "fc": Route.build(topology, ["e0", "e1"]),
    }

    allocation = run(topology, flows, routing)

    assert allocation.rates["fa"] == APPROX(1.0)
    assert allocation.rates["fb"] == APPROX(1.0)
    assert allocation.rates["fc"] == APPROX(1.0)
    assert allocation.load_on("e0") == APPROX(3.0)


def test_parallel_links_are_independent_resources() -> None:
    nodes = [Node("n0"), Node("n1")]
    links = [
        Link("e0", "n0", "n1", capacity_mbps=2.0),
        Link("e1", "n0", "n1", capacity_mbps=8.0),
    ]
    topology = Topology(nodes, links)
    flows = [
        Flow("fa", "n0", "n1", demand_mbps=100.0),
        Flow("fb", "n0", "n1", demand_mbps=100.0),
    ]
    routing = {
        "fa": Route.build(topology, ["e0"]),
        "fb": Route.build(topology, ["e1"]),
    }

    allocation = run(topology, flows, routing)

    assert allocation.rates["fa"] == APPROX(2.0)
    assert allocation.rates["fb"] == APPROX(8.0)


# ------------------------------------------------------------------ strict priority


def test_the_higher_class_is_served_before_the_lower_one() -> None:
    topology = line_topology([10.0])
    flows = [
        Flow("f_crit", "n0", "n1", demand_mbps=8.0, priority=Priority.CRITICAL),
        Flow("f_norm", "n0", "n1", demand_mbps=8.0, priority=Priority.NORMAL),
    ]
    routing = {
        "f_crit": Route.build(topology, ["e0"]),
        "f_norm": Route.build(topology, ["e0"]),
    }

    allocation = run(topology, flows, routing)

    assert allocation.rates["f_crit"] == APPROX(8.0)
    assert allocation.rates["f_norm"] == APPROX(2.0)


def test_a_saturating_higher_class_starves_the_lower_class_to_zero() -> None:
    """Intended behaviour, and the mechanism H1 depends on. Not a bug to soften."""
    topology = line_topology([10.0])
    flows = [
        Flow("f_crit", "n0", "n1", demand_mbps=12.0, priority=Priority.CRITICAL),
        Flow("f_low", "n0", "n1", demand_mbps=8.0, priority=Priority.LOW),
    ]
    routing = {
        "f_crit": Route.build(topology, ["e0"]),
        "f_low": Route.build(topology, ["e0"]),
    }

    allocation = run(topology, flows, routing)

    assert allocation.rates["f_crit"] == APPROX(10.0)
    assert allocation.rates["f_low"] == APPROX(0.0)
    assert "f_low" not in allocation.blackholed, "starvation is not blackholing"


def test_all_four_classes_are_served_in_precedence_order() -> None:
    """20 Mbps, four flows of 8 each: 8 / 8 / 4 / 0 down the precedence ladder."""
    topology = line_topology([20.0])
    flows = [
        Flow("f_crit", "n0", "n1", demand_mbps=8.0, priority=Priority.CRITICAL),
        Flow("f_high", "n0", "n1", demand_mbps=8.0, priority=Priority.HIGH),
        Flow("f_norm", "n0", "n1", demand_mbps=8.0, priority=Priority.NORMAL),
        Flow("f_low", "n0", "n1", demand_mbps=8.0, priority=Priority.LOW),
    ]
    routing = {flow.id: Route.build(topology, ["e0"]) for flow in flows}

    allocation = run(topology, flows, routing)

    assert allocation.rates["f_crit"] == APPROX(8.0)
    assert allocation.rates["f_high"] == APPROX(8.0)
    assert allocation.rates["f_norm"] == APPROX(4.0)
    assert allocation.rates["f_low"] == APPROX(0.0)


def test_max_min_fairness_applies_within_a_class_after_priority_between_classes() -> None:
    """CRITICAL takes 4 of the 10 Mbps link, and the two NORMAL flows split the rest."""
    topology = line_topology([10.0])
    flows = [
        Flow("f_crit", "n0", "n1", demand_mbps=4.0, priority=Priority.CRITICAL),
        Flow("f_n1", "n0", "n1", demand_mbps=100.0, priority=Priority.NORMAL),
        Flow("f_n2", "n0", "n1", demand_mbps=100.0, priority=Priority.NORMAL),
    ]
    routing = {flow.id: Route.build(topology, ["e0"]) for flow in flows}

    allocation = run(topology, flows, routing)

    assert allocation.rates["f_crit"] == APPROX(4.0)
    assert allocation.rates["f_n1"] == APPROX(3.0)
    assert allocation.rates["f_n2"] == APPROX(3.0)


def test_a_low_flow_avoiding_the_congested_link_is_still_served() -> None:
    """Priority is enforced per bottleneck, not globally: starving a LOW flow that does
    not compete for the contended link would be wrong."""
    nodes = [Node("n0"), Node("n1"), Node("n2")]
    links = [
        Link("e0", "n0", "n1", capacity_mbps=5.0),
        Link("e1", "n0", "n2", capacity_mbps=5.0),
    ]
    topology = Topology(nodes, links)
    flows = [
        Flow("f_crit", "n0", "n1", demand_mbps=100.0, priority=Priority.CRITICAL),
        Flow("f_low", "n0", "n2", demand_mbps=3.0, priority=Priority.LOW),
    ]
    routing = {
        "f_crit": Route.build(topology, ["e0"]),
        "f_low": Route.build(topology, ["e1"]),
    }

    allocation = run(topology, flows, routing)

    assert allocation.rates["f_crit"] == APPROX(5.0)
    assert allocation.rates["f_low"] == APPROX(3.0)


# ------------------------------------------------------------------- failed elements


def test_a_route_over_a_down_link_is_blackholed() -> None:
    topology = line_topology([10.0, 10.0], state=LinkState.DOWN)
    flow = Flow("f0", "n0", "n2", demand_mbps=5.0)
    routing = {"f0": Route.build(topology, ["e0", "e1"])}

    allocation = run(topology, [flow], routing)

    assert allocation.rates["f0"] == 0.0
    assert allocation.blackholed == frozenset({"f0"})
    assert allocation.link_load == {}


def test_a_route_through_a_down_node_is_blackholed() -> None:
    nodes = [Node("n0"), Node("n1", state=NodeState.DOWN), Node("n2")]
    links = [
        Link("e0", "n0", "n1", capacity_mbps=10.0),
        Link("e1", "n1", "n2", capacity_mbps=10.0),
    ]
    topology = Topology(nodes, links)
    flow = Flow("f0", "n0", "n2", demand_mbps=5.0)
    routing = {"f0": Route.build(topology, ["e0", "e1"])}

    allocation = run(topology, [flow], routing)

    assert allocation.rates["f0"] == 0.0
    assert allocation.blackholed == frozenset({"f0"})


def test_an_unrouted_flow_is_blackholed_and_does_not_disturb_the_others() -> None:
    topology = line_topology([10.0])
    flows = [
        Flow("f_routed", "n0", "n1", demand_mbps=4.0),
        Flow("f_orphan", "n1", "n0", demand_mbps=4.0),
    ]
    routing = {"f_routed": Route.build(topology, ["e0"])}

    allocation = run(topology, flows, routing)

    assert allocation.rates["f_routed"] == APPROX(4.0)
    assert allocation.rates["f_orphan"] == 0.0
    assert allocation.blackholed == frozenset({"f_orphan"})


def test_a_degraded_link_allocates_only_its_degraded_capacity() -> None:
    topology = line_topology([100.0], state=LinkState.DEGRADED, degrade_factor=0.25)
    flow = Flow("f0", "n0", "n1", demand_mbps=100.0)
    routing = {"f0": Route.build(topology, ["e0"])}

    allocation = run(topology, [flow], routing)

    assert allocation.rates["f0"] == APPROX(25.0)


def test_only_the_flows_crossing_the_failure_are_blackholed() -> None:
    nodes = [Node("n0"), Node("n1"), Node("n2")]
    links = [
        Link("e0", "n0", "n1", capacity_mbps=10.0, state=LinkState.DOWN),
        Link("e1", "n0", "n2", capacity_mbps=10.0),
    ]
    topology = Topology(nodes, links)
    flows = [
        Flow("f_dead", "n0", "n1", demand_mbps=5.0),
        Flow("f_live", "n0", "n2", demand_mbps=5.0),
    ]
    routing = {
        "f_dead": Route.build(topology, ["e0"]),
        "f_live": Route.build(topology, ["e1"]),
    }

    allocation = run(topology, flows, routing)

    assert allocation.blackholed == frozenset({"f_dead"})
    assert allocation.rates["f_live"] == APPROX(5.0)


# ---------------------------------------------------------------- degenerate inputs


def test_a_zero_capacity_link_yields_zero_rate_without_dividing_by_zero() -> None:
    topology = line_topology([0.0])
    flow = Flow("f0", "n0", "n1", demand_mbps=5.0)
    routing = {"f0": Route.build(topology, ["e0"])}

    allocation = run(topology, [flow], routing)

    assert allocation.rates["f0"] == 0.0
    assert allocation.blackholed == frozenset(), "the path exists; there is just no room"


def test_a_zero_demand_flow_takes_nothing_and_blocks_nobody() -> None:
    topology = line_topology([10.0])
    flows = [
        Flow("f_idle", "n0", "n1", demand_mbps=0.0),
        Flow("f_busy", "n0", "n1", demand_mbps=10.0),
    ]
    routing = {flow.id: Route.build(topology, ["e0"]) for flow in flows}

    allocation = run(topology, flows, routing)

    assert allocation.rates["f_idle"] == 0.0
    assert allocation.rates["f_busy"] == APPROX(10.0)
    assert "f_idle" not in allocation.blackholed


def test_no_flows_produces_an_empty_allocation_rather_than_an_error() -> None:
    allocation = run(line_topology([10.0]), [], {})

    assert allocation.rates == {}
    assert allocation.link_load == {}
    assert allocation.blackholed == frozenset()


def test_every_flow_appears_in_the_result_even_when_it_got_nothing() -> None:
    topology = line_topology([0.0])
    flows = [Flow("f0", "n0", "n1", demand_mbps=1.0), Flow("f1", "n0", "n1", demand_mbps=0.0)]
    routing = {flow.id: Route.build(topology, ["e0"]) for flow in flows}

    allocation = run(topology, flows, routing)

    assert set(allocation.rates) == {"f0", "f1"}


def test_duplicate_flow_ids_are_rejected_rather_than_silently_merged() -> None:
    topology = line_topology([10.0])
    flows = [
        Flow("f0", "n0", "n1", demand_mbps=1.0),
        Flow("f0", "n0", "n1", demand_mbps=2.0),
    ]
    routing = {"f0": Route.build(topology, ["e0"])}

    with pytest.raises(ValidationError, match="duplicate flow id"):
        allocate(topology, flows, routing)


def test_a_route_naming_a_link_outside_the_topology_is_rejected() -> None:
    topology = line_topology([10.0, 10.0])
    stale_route = Route.build(topology, ["e1"])
    smaller = line_topology([10.0])
    flow = Flow("f0", "n1", "n2", demand_mbps=1.0)

    with pytest.raises(ValidationError, match="unknown link id 'e1'"):
        allocate(smaller, [flow], {"f0": stale_route})


# --------------------------------------------------------------------- determinism


def test_repeated_execution_is_bit_identical() -> None:
    topology = line_topology([10.0, 6.0, 10.0])
    flows = [
        Flow("fa", "n0", "n3", demand_mbps=7.0),
        Flow("fb", "n1", "n2", demand_mbps=9.0),
        Flow("fc", "n1", "n2", demand_mbps=1.0, priority=Priority.CRITICAL),
    ]
    routing = {
        "fa": Route.build(topology, ["e0", "e1", "e2"]),
        "fb": Route.build(topology, ["e1"]),
        "fc": Route.build(topology, ["e1"]),
    }

    first = allocate(topology, flows, routing)
    second = allocate(topology, flows, routing)

    assert dict(first.rates) == dict(second.rates)
    assert dict(first.link_load) == dict(second.link_load)
    assert list(first.rates) == list(second.rates), "key order must be stable too"


def test_the_order_flows_are_supplied_in_does_not_change_the_result() -> None:
    """Guards the determinism invariant against the most likely way to lose it: a caller
    that builds its flow list in a different order (a set, a dict, a parallel merge)."""
    topology = line_topology([10.0, 6.0, 10.0])
    flows = [
        Flow("fa", "n0", "n3", demand_mbps=7.0),
        Flow("fb", "n1", "n2", demand_mbps=9.0),
        Flow("fc", "n1", "n2", demand_mbps=1.0),
    ]
    routing = {
        "fa": Route.build(topology, ["e0", "e1", "e2"]),
        "fb": Route.build(topology, ["e1"]),
        "fc": Route.build(topology, ["e1"]),
    }

    forwards = allocate(topology, flows, routing)
    backwards = allocate(topology, list(reversed(flows)), routing)

    assert dict(forwards.rates) == dict(backwards.rates)
    assert dict(forwards.link_load) == dict(backwards.link_load)
    # Iteration order matters as much as the values: the determinism gate in CI hashes a
    # serialised metrics file, and a reordered file is a different hash.
    assert list(forwards.rates) == list(backwards.rates)
    assert list(forwards.link_load) == list(backwards.link_load)
