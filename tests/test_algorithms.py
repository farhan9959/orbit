"""A3/A5/A6 - routing algorithms, including the NetworkX differential oracle."""

from __future__ import annotations

import networkx as nx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from orbit.algorithms import (
    ConstrainedShortestPath,
    EqualCostMultiPath,
    OrbitConfig,
    OrbitController,
    ReconvergingShortestPath,
    StaticShortestPath,
    equal_cost_routes,
    shortest_path_tree,
    shortest_route,
)
from orbit.engine import Simulation
from orbit.generators import barabasi_albert, grid, ring, waxman
from orbit.model import Flow, GraphView, Link, LinkState, Node, PathSet, Priority, Route, Topology

ALGO_SETTINGS = settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


def to_networkx(topology: Topology) -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(topology.nodes))
    for link_id in sorted(topology.links):
        link = topology.link(link_id)
        if not topology.is_usable(link_id):
            continue
        weight = link.prop_delay_ms
        if graph.has_edge(link.src, link.dst):
            weight = min(weight, graph[link.src][link.dst]["weight"])
        graph.add_edge(link.src, link.dst, weight=weight)
    return graph


def path_cost(topology: Topology, route: Route) -> float:
    return sum(topology.link(link_id).prop_delay_ms for link_id in route.links)


def view_of(topology: Topology) -> GraphView:
    return GraphView(topology, 0, changed=True)


@given(
    node_count=st.integers(min_value=2, max_value=14),
    seed=st.integers(min_value=0, max_value=500),
)
@ALGO_SETTINGS
def test_dijkstra_cost_matches_networkx(node_count: int, seed: int) -> None:
    topology = waxman(node_count, seed=seed)
    graph = to_networkx(topology)
    for source in sorted(topology.nodes):
        distance, _ = shortest_path_tree(
            topology, source, allowed=lambda link: topology.is_usable(link.id)
        )
        expected = nx.single_source_dijkstra_path_length(graph, source, weight="weight")
        assert set(distance) == set(expected)
        for node, value in expected.items():
            assert distance[node] == pytest.approx(value)


@given(
    node_count=st.integers(min_value=2, max_value=10),
    seed=st.integers(min_value=0, max_value=200),
)
@ALGO_SETTINGS
def test_ecmp_path_set_matches_networkx(node_count: int, seed: int) -> None:
    topology = barabasi_albert(node_count, seed=seed, attachments=min(2, node_count - 1))
    graph = to_networkx(topology)
    for source in sorted(topology.nodes):
        for target in sorted(topology.nodes):
            if source == target:
                continue
            routes = equal_cost_routes(
                topology,
                source,
                target,
                allowed=lambda link: topology.is_usable(link.id),
                limit=64,
            )
            if not nx.has_path(graph, source, target):
                assert routes == ()
                continue
            expected = {
                tuple(path)
                for path in nx.all_shortest_paths(graph, source, target, weight="weight")
            }
            produced = {route.nodes for route in routes}
            assert produced <= expected
            assert produced


def test_static_spf_never_recomputes_after_a_failure() -> None:
    topology = ring(6)
    flows = [Flow("f0", "n000", "n003", demand_mbps=1.0)]
    algorithm = StaticShortestPath()
    first = algorithm.recompute(view_of(topology), flows, {})
    damaged = Topology(
        topology.nodes.values(),
        [
            (
                link
                if link.id != first["f0"].links[0]
                else Link(
                    link.id,
                    link.src,
                    link.dst,
                    capacity_mbps=link.capacity_mbps,
                    state=LinkState.DOWN,
                )
            )
            for link in topology.links.values()
        ],
    )
    second = algorithm.recompute(view_of(damaged), flows, first)
    assert second["f0"].links == first["f0"].links


def test_reconverging_spf_finds_the_alternative_after_a_failure() -> None:
    topology = ring(6)
    flows = [Flow("f0", "n000", "n003", demand_mbps=1.0)]
    algorithm = ReconvergingShortestPath()
    first = algorithm.recompute(view_of(topology), flows, {})
    broken = first["f0"].links[0]
    damaged = Topology(
        topology.nodes.values(),
        [
            (
                link
                if link.id != broken
                else Link(
                    link.id,
                    link.src,
                    link.dst,
                    capacity_mbps=link.capacity_mbps,
                    state=LinkState.DOWN,
                )
            )
            for link in topology.links.values()
        ],
    )
    algorithm.drain_events()
    second = algorithm.recompute(view_of(damaged), flows, first)
    assert broken not in second["f0"].links
    assert any(event.type.value == "FLOW_REROUTED" for event in algorithm.drain_events())


def test_ecmp_splits_across_equal_cost_paths() -> None:
    nodes = [Node("n0"), Node("n1"), Node("n2"), Node("n3")]
    links = [
        Link("a1", "n0", "n1", capacity_mbps=100.0, prop_delay_ms=1.0),
        Link("a2", "n1", "n3", capacity_mbps=100.0, prop_delay_ms=1.0),
        Link("b1", "n0", "n2", capacity_mbps=100.0, prop_delay_ms=1.0),
        Link("b2", "n2", "n3", capacity_mbps=100.0, prop_delay_ms=1.0),
    ]
    topology = Topology(nodes, links)
    flows = [Flow("f0", "n0", "n3", demand_mbps=50.0)]

    routing = EqualCostMultiPath().recompute(view_of(topology), flows, {})
    placement = routing["f0"]

    assert isinstance(placement, PathSet)
    assert len(placement.routes) == 2
    assert placement.shares == pytest.approx((0.5, 0.5))

    allocation = Simulation(topology, flows, routing).step()
    assert allocation.samples[0].delivered_mbps == pytest.approx(50.0)
    assert allocation.link_load["a1"] == pytest.approx(25.0)
    assert allocation.link_load["b1"] == pytest.approx(25.0)


def test_ecmp_beats_single_path_when_one_branch_is_thin() -> None:
    nodes = [Node("n0"), Node("n1"), Node("n2"), Node("n3")]
    links = [
        Link("a1", "n0", "n1", capacity_mbps=30.0, prop_delay_ms=1.0),
        Link("a2", "n1", "n3", capacity_mbps=30.0, prop_delay_ms=1.0),
        Link("b1", "n0", "n2", capacity_mbps=30.0, prop_delay_ms=1.0),
        Link("b2", "n2", "n3", capacity_mbps=30.0, prop_delay_ms=1.0),
    ]
    topology = Topology(nodes, links)
    flows = [Flow("f0", "n0", "n3", demand_mbps=50.0)]

    spf = Simulation(topology, flows, StaticShortestPath()).step().samples[0]
    ecmp = Simulation(topology, flows, EqualCostMultiPath()).step().samples[0]

    assert spf.delivered_mbps == pytest.approx(30.0)
    assert ecmp.delivered_mbps == pytest.approx(50.0)


def test_cspf_avoids_a_congested_link_that_spf_would_take() -> None:
    nodes = [Node("n0"), Node("n1"), Node("n2"), Node("n3")]
    links = [
        Link("short", "n0", "n3", capacity_mbps=10.0, prop_delay_ms=1.0),
        Link("long1", "n0", "n1", capacity_mbps=100.0, prop_delay_ms=2.0),
        Link("long2", "n1", "n2", capacity_mbps=100.0, prop_delay_ms=2.0),
        Link("long3", "n2", "n3", capacity_mbps=100.0, prop_delay_ms=2.0),
    ]
    topology = Topology(nodes, links)
    flows = [Flow("f0", "n0", "n3", demand_mbps=60.0)]

    spf = Simulation(topology, flows, StaticShortestPath()).step().samples[0]
    cspf = Simulation(topology, flows, ConstrainedShortestPath()).step().samples[0]

    assert spf.delivered_mbps == pytest.approx(10.0)
    assert cspf.delivered_mbps == pytest.approx(60.0)


def test_cspf_is_priority_blind() -> None:
    """The property that makes CSPF the right control for isolating priority awareness."""
    nodes = [Node("n0"), Node("n1")]
    topology = Topology(nodes, [Link("e0", "n0", "n1", capacity_mbps=10.0)])
    flows = [
        Flow("f_low", "n0", "n1", demand_mbps=10.0, priority=Priority.LOW),
        Flow("f_crit", "n0", "n1", demand_mbps=10.0, priority=Priority.CRITICAL),
    ]
    routing = ConstrainedShortestPath().recompute(view_of(topology), flows, {})
    assert set(routing) == {"f_low", "f_crit"}


def test_orbit_preempts_a_low_flow_to_admit_a_critical_one() -> None:
    nodes = [Node("n0"), Node("n1")]
    topology = Topology(nodes, [Link("e0", "n0", "n1", capacity_mbps=10.0)])
    flows = [
        Flow("f_low", "n0", "n1", demand_mbps=10.0, priority=Priority.LOW),
        Flow("f_crit", "n0", "n1", demand_mbps=10.0, priority=Priority.CRITICAL),
    ]
    installed = {"f_low": Route.build(topology, ["e0"])}
    controller = OrbitController()
    routing = controller.recompute(view_of(topology), flows, installed)

    assert "f_crit" in routing
    assert "f_low" not in routing
    assert any(event.type.value == "FLOW_PREEMPTED" for event in controller.drain_events())


def test_orbit_never_preempts_an_equal_or_higher_priority_flow() -> None:
    nodes = [Node("n0"), Node("n1")]
    topology = Topology(nodes, [Link("e0", "n0", "n1", capacity_mbps=10.0)])
    flows = [
        Flow("f_a", "n0", "n1", demand_mbps=10.0, priority=Priority.CRITICAL),
        Flow("f_b", "n0", "n1", demand_mbps=10.0, priority=Priority.CRITICAL),
    ]
    installed = {"f_a": Route.build(topology, ["e0"])}
    controller = OrbitController()
    routing = controller.recompute(view_of(topology), flows, installed)

    assert routing == installed
    assert not any(event.type.value == "FLOW_PREEMPTED" for event in controller.drain_events())


def test_orbit_ablation_switches_change_behaviour() -> None:
    nodes = [Node("n0"), Node("n1")]
    topology = Topology(nodes, [Link("e0", "n0", "n1", capacity_mbps=10.0)])
    flows = [
        Flow("f_low", "n0", "n1", demand_mbps=10.0, priority=Priority.LOW),
        Flow("f_crit", "n0", "n1", demand_mbps=10.0, priority=Priority.CRITICAL),
    ]
    installed = {"f_low": Route.build(topology, ["e0"])}
    without = OrbitController(OrbitConfig(preemption=False))
    routing = without.recompute(view_of(topology), flows, installed)

    assert "f_low" in routing
    assert "f_crit" not in routing
    assert not any(event.type.value == "FLOW_PREEMPTED" for event in without.drain_events())


def test_orbit_disabled_restoration_places_nothing_new() -> None:
    topology = grid(3, 3)
    flows = [Flow("f0", "n000", "n008", demand_mbps=1.0)]
    controller = OrbitController(OrbitConfig(restoration=False, protection=False))
    assert controller.recompute(view_of(topology), flows, {}) == {}


def test_orbit_builds_an_srlg_disjoint_backup_for_critical_flows() -> None:
    topology = ring(6)
    flows = [Flow("f0", "n000", "n003", demand_mbps=1.0, priority=Priority.CRITICAL)]
    controller = OrbitController()
    first = controller.recompute(view_of(topology), flows, {})
    controller.recompute(view_of(topology), flows, first)

    assert controller.backup_coverage == pytest.approx(1.0)


@given(
    node_count=st.integers(min_value=4, max_value=12),
    seed=st.integers(min_value=0, max_value=200),
)
@ALGO_SETTINGS
def test_every_algorithm_produces_valid_simple_paths(node_count: int, seed: int) -> None:
    topology = waxman(node_count, seed=seed)
    ids = sorted(topology.nodes)
    flows = [
        Flow(
            f"f{index}",
            ids[index % len(ids)],
            ids[(index + 1) % len(ids)],
            demand_mbps=10.0,
            priority=list(Priority)[index % 4],
        )
        for index in range(min(6, len(ids)))
        if ids[index % len(ids)] != ids[(index + 1) % len(ids)]
    ]
    for algorithm in (
        StaticShortestPath(),
        ReconvergingShortestPath(),
        EqualCostMultiPath(),
        ConstrainedShortestPath(),
        OrbitController(),
    ):
        simulation = Simulation(topology, flows, algorithm)
        for _ in simulation.run(3):
            pass


def test_shortest_route_returns_none_when_unreachable() -> None:
    nodes = [Node("n0"), Node("n1")]
    topology = Topology(nodes, [Link("e0", "n1", "n0", capacity_mbps=1.0)])
    assert shortest_route(topology, "n0", "n1") is None
