"""A1 — validation and structural behaviour of the core model types."""

from __future__ import annotations

import math

import pytest

from orbit.errors import ValidationError
from orbit.model import (
    Flow,
    Link,
    LinkState,
    Node,
    NodeKind,
    NodeState,
    Priority,
    Route,
    Topology,
    validate_flows,
    validate_routing,
)


def line_topology(capacities: list[float], **link_kwargs: object) -> Topology:
    """`n0 -> n1 -> ... -> nN` with `e{i}` carrying `capacities[i]`."""
    nodes = [Node(f"n{i}") for i in range(len(capacities) + 1)]
    links = [
        Link(f"e{i}", f"n{i}", f"n{i + 1}", capacity_mbps=capacity, **link_kwargs)  # type: ignore[arg-type]
        for i, capacity in enumerate(capacities)
    ]
    return Topology(nodes, links)


# --------------------------------------------------------------------------- Node


def test_node_defaults_are_a_healthy_router() -> None:
    node = Node("n0")
    assert node.kind is NodeKind.ROUTER
    assert node.state is NodeState.UP
    assert node.is_up
    assert node.srlg == frozenset()


def test_node_srlg_is_coerced_to_a_frozenset_so_the_node_stays_hashable() -> None:
    node = Node("n0", srlg={"region:west", "conduit:A12"})
    assert node.srlg == frozenset({"region:west", "conduit:A12"})
    assert hash(node) == hash(Node("n0", srlg={"conduit:A12", "region:west"}))


def test_node_is_immutable() -> None:
    node = Node("n0")
    with pytest.raises(Exception):  # noqa: B017 - dataclasses raise FrozenInstanceError
        node.state = NodeState.DOWN  # type: ignore[misc]


@pytest.mark.parametrize("bad_id", ["", None, 7])
def test_node_rejects_an_unusable_id(bad_id: object) -> None:
    with pytest.raises(ValidationError, match="id"):
        Node(bad_id)  # type: ignore[arg-type]


def test_node_rejects_negative_processing_delay() -> None:
    with pytest.raises(ValidationError, match="processing_delay_ms"):
        Node("n0", processing_delay_ms=-1.0)


def test_node_rejects_a_non_string_srlg_tag() -> None:
    with pytest.raises(ValidationError, match="srlg"):
        Node("n0", srlg=[1, 2])  # type: ignore[list-item]


# --------------------------------------------------------------------------- Link


def test_link_rejects_a_self_loop() -> None:
    with pytest.raises(ValidationError, match="self-loop"):
        Link("e0", "n0", "n0", capacity_mbps=10.0)


def test_link_permits_zero_capacity() -> None:
    assert Link("e0", "n0", "n1", capacity_mbps=0.0).effective_capacity_mbps == 0.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capacity_mbps", -1.0),
        ("capacity_mbps", math.nan),
        ("capacity_mbps", math.inf),
        ("capacity_mbps", True),
        ("prop_delay_ms", -0.5),
        ("loss_rate", -0.1),
        ("loss_rate", 1.5),
        ("degrade_factor", -0.1),
        ("degrade_factor", 1.5),
    ],
)
def test_link_rejects_out_of_range_fields(field: str, value: object) -> None:
    kwargs: dict[str, object] = {"capacity_mbps": 10.0, field: value}
    with pytest.raises(ValidationError, match=field):
        Link("e0", "n0", "n1", **kwargs)  # type: ignore[arg-type]


def test_effective_capacity_follows_operational_state() -> None:
    assert Link("e0", "n0", "n1", capacity_mbps=100.0).effective_capacity_mbps == 100.0
    down = Link("e0", "n0", "n1", capacity_mbps=100.0, state=LinkState.DOWN)
    assert down.effective_capacity_mbps == 0.0
    degraded = Link(
        "e0", "n0", "n1", capacity_mbps=100.0, state=LinkState.DEGRADED, degrade_factor=0.25
    )
    assert degraded.effective_capacity_mbps == 25.0


def test_degrade_factor_is_ignored_while_the_link_is_up() -> None:
    """So restoring a link does not require the injector to reset the factor."""
    link = Link("e0", "n0", "n1", capacity_mbps=100.0, degrade_factor=0.25)
    assert link.effective_capacity_mbps == 100.0


# ----------------------------------------------------------------------- Topology


def test_topology_rejects_duplicate_node_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate node id"):
        Topology([Node("n0"), Node("n0")], [])


def test_topology_rejects_duplicate_link_ids() -> None:
    nodes = [Node("n0"), Node("n1")]
    links = [
        Link("e0", "n0", "n1", capacity_mbps=1.0),
        Link("e0", "n1", "n0", capacity_mbps=1.0),
    ]
    with pytest.raises(ValidationError, match="duplicate link id"):
        Topology(nodes, links)


def test_topology_rejects_a_dangling_link_endpoint() -> None:
    with pytest.raises(ValidationError, match="dangling dst"):
        Topology([Node("n0")], [Link("e0", "n0", "ghost", capacity_mbps=1.0)])


def test_topology_permits_parallel_links_with_independent_capacities() -> None:
    nodes = [Node("n0"), Node("n1")]
    links = [
        Link("e0", "n0", "n1", capacity_mbps=10.0),
        Link("e1", "n0", "n1", capacity_mbps=40.0),
    ]
    topology = Topology(nodes, links)
    assert [link.id for link in topology.links_from("n0")] == ["e0", "e1"]
    assert topology.link("e1").capacity_mbps == 40.0


def test_topology_iteration_order_is_sorted_regardless_of_input_order() -> None:
    nodes = [Node("n2"), Node("n0"), Node("n1")]
    links = [
        Link("e1", "n1", "n2", capacity_mbps=1.0),
        Link("e0", "n0", "n1", capacity_mbps=1.0),
    ]
    forwards = Topology(nodes, links)
    backwards = Topology(list(reversed(nodes)), list(reversed(links)))
    assert list(forwards.nodes) == list(backwards.nodes) == ["n0", "n1", "n2"]
    assert list(forwards.links) == list(backwards.links) == ["e0", "e1"]


def test_topology_lookups_reject_unknown_ids_with_a_specific_message() -> None:
    topology = line_topology([1.0])
    with pytest.raises(ValidationError, match="unknown link id 'ghost'"):
        topology.link("ghost")
    with pytest.raises(ValidationError, match="unknown node id 'ghost'"):
        topology.node("ghost")
    with pytest.raises(ValidationError, match="unknown node id 'ghost'"):
        topology.links_from("ghost")


def test_a_node_with_no_out_links_reports_an_empty_tuple() -> None:
    assert line_topology([1.0]).links_from("n1") == ()


def test_link_usability_requires_the_link_and_both_endpoints() -> None:
    assert line_topology([1.0]).is_usable("e0")

    down_link = Topology(
        [Node("n0"), Node("n1")],
        [Link("e0", "n0", "n1", capacity_mbps=1.0, state=LinkState.DOWN)],
    )
    assert not down_link.is_usable("e0")

    down_node = Topology(
        [Node("n0"), Node("n1", state=NodeState.DOWN)],
        [Link("e0", "n0", "n1", capacity_mbps=1.0)],
    )
    assert not down_node.is_usable("e0")


def test_a_degraded_link_is_still_usable_but_may_carry_nothing() -> None:
    topology = Topology(
        [Node("n0"), Node("n1")],
        [Link("e0", "n0", "n1", capacity_mbps=10.0, state=LinkState.DEGRADED, degrade_factor=0.0)],
    )
    assert topology.is_usable("e0")
    assert topology.link("e0").effective_capacity_mbps == 0.0


# --------------------------------------------------------------------- Flow/Priority


def test_priority_orders_critical_highest() -> None:
    assert Priority.CRITICAL > Priority.HIGH > Priority.NORMAL > Priority.LOW
    assert sorted(Priority, reverse=True) == [
        Priority.CRITICAL,
        Priority.HIGH,
        Priority.NORMAL,
        Priority.LOW,
    ]


def test_flow_rejects_src_equal_to_dst() -> None:
    with pytest.raises(ValidationError, match="src and dst must differ"):
        Flow("f0", "n0", "n0", demand_mbps=1.0)


def test_flow_permits_zero_demand() -> None:
    assert Flow("f0", "n0", "n1", demand_mbps=0.0).demand_mbps == 0.0


def test_flow_defaults_to_running_for_the_whole_simulation() -> None:
    assert Flow("f0", "n0", "n1", demand_mbps=1.0).duration_s == math.inf


def test_flow_rejects_zero_duration() -> None:
    with pytest.raises(ValidationError, match="duration_s must be > 0"):
        Flow("f0", "n0", "n1", demand_mbps=1.0, duration_s=0.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [("demand_mbps", -1.0), ("demand_mbps", math.nan), ("start_s", -1.0), ("start_s", math.inf)],
)
def test_flow_rejects_out_of_range_fields(field: str, value: float) -> None:
    kwargs: dict[str, object] = {"demand_mbps": 1.0, field: value}
    with pytest.raises(ValidationError, match=field):
        Flow("f0", "n0", "n1", **kwargs)  # type: ignore[arg-type]


def test_validate_flows_rejects_endpoints_that_are_not_in_the_topology() -> None:
    topology = line_topology([1.0])
    with pytest.raises(ValidationError, match="src 'ghost' is not a node"):
        validate_flows(topology, [Flow("f0", "ghost", "n1", demand_mbps=1.0)])
    with pytest.raises(ValidationError, match="dst 'ghost' is not a node"):
        validate_flows(topology, [Flow("f0", "n0", "ghost", demand_mbps=1.0)])


def test_validate_flows_rejects_duplicate_ids() -> None:
    topology = line_topology([1.0])
    flows = [Flow("f0", "n0", "n1", demand_mbps=1.0), Flow("f0", "n1", "n0", demand_mbps=1.0)]
    with pytest.raises(ValidationError, match="duplicate flow id"):
        validate_flows(topology, flows)


def test_validate_flows_returns_a_deterministic_order() -> None:
    topology = line_topology([1.0, 1.0])
    flows = [
        Flow("f2", "n0", "n1", demand_mbps=1.0),
        Flow("f0", "n1", "n2", demand_mbps=1.0),
        Flow("f1", "n0", "n2", demand_mbps=1.0),
    ]
    assert [f.id for f in validate_flows(topology, flows)] == ["f0", "f1", "f2"]
    assert [f.id for f in validate_flows(topology, reversed(flows))] == ["f0", "f1", "f2"]


# ---------------------------------------------------------------------------- Route


def test_route_build_derives_the_node_sequence() -> None:
    topology = line_topology([1.0, 1.0])
    route = Route.build(topology, ["e0", "e1"])
    assert route.links == ("e0", "e1")
    assert route.nodes == ("n0", "n1", "n2")
    assert route.src == "n0"
    assert route.dst == "n2"


def test_route_build_rejects_an_empty_path() -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        Route.build(line_topology([1.0]), [])


def test_route_build_rejects_an_unknown_link() -> None:
    with pytest.raises(ValidationError, match="unknown link id 'ghost'"):
        Route.build(line_topology([1.0]), ["ghost"])


def test_route_build_rejects_a_discontiguous_path() -> None:
    nodes = [Node("n0"), Node("n1"), Node("n2"), Node("n3")]
    links = [
        Link("e0", "n0", "n1", capacity_mbps=1.0),
        Link("e1", "n2", "n3", capacity_mbps=1.0),
    ]
    with pytest.raises(ValidationError, match="starts at 'n2' but the previous link"):
        Route.build(Topology(nodes, links), ["e0", "e1"])


def test_route_build_rejects_a_cycle_so_no_forwarding_loop_can_be_installed() -> None:
    nodes = [Node("n0"), Node("n1"), Node("n2")]
    links = [
        Link("e0", "n0", "n1", capacity_mbps=1.0),
        Link("e1", "n1", "n2", capacity_mbps=1.0),
        Link("e2", "n2", "n0", capacity_mbps=1.0),
    ]
    with pytest.raises(ValidationError, match="not simple"):
        Route.build(Topology(nodes, links), ["e0", "e1", "e2"])


def test_route_build_succeeds_on_a_down_link_because_liveness_is_checked_at_use_time() -> None:
    """A route outlives the operational state it was computed under; see routing.py."""
    topology = line_topology([1.0], state=LinkState.DOWN)
    assert Route.build(topology, ["e0"]).links == ("e0",)


# ------------------------------------------------------------------ validate_routing


def test_validate_routing_accepts_a_consistent_routing() -> None:
    topology = line_topology([1.0, 1.0])
    flow = Flow("f0", "n0", "n2", demand_mbps=1.0)
    validate_routing(topology, [flow], {"f0": Route.build(topology, ["e0", "e1"])})


def test_validate_routing_rejects_a_route_for_an_unknown_flow() -> None:
    topology = line_topology([1.0])
    with pytest.raises(ValidationError, match="unknown flow 'ghost'"):
        validate_routing(topology, [], {"ghost": Route.build(topology, ["e0"])})


def test_validate_routing_rejects_a_route_whose_endpoints_differ_from_the_flow() -> None:
    topology = line_topology([1.0, 1.0])
    flow = Flow("f0", "n0", "n2", demand_mbps=1.0)
    with pytest.raises(ValidationError, match="runs 'n0'->'n1' but the flow demands"):
        validate_routing(topology, [flow], {"f0": Route.build(topology, ["e0"])})


def test_validate_routing_rejects_a_route_computed_on_a_different_topology() -> None:
    original = line_topology([1.0, 1.0])
    route = Route.build(original, ["e0", "e1"])
    rewired = Topology(
        [Node("n0"), Node("n1"), Node("n2")],
        [
            Link("e0", "n0", "n1", capacity_mbps=1.0),
            Link("e1", "n2", "n1", capacity_mbps=1.0),
        ],
    )
    flow = Flow("f0", "n0", "n2", demand_mbps=1.0)
    with pytest.raises(ValidationError, match="previous link"):
        validate_routing(rewired, [flow], {"f0": route})
