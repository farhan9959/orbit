"""A1 — topology generators: structural invariants, determinism, and exact shapes.

The roadmap's done-when for A1 is "property test: generated topologies satisfy structural
invariants". Those invariants are asserted by `check_structure` below and applied to every
family at every size the property test reaches, plus the fixed sizes named in requirement
F3.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from orbit.errors import ValidationError
from orbit.generators import barabasi_albert, grid, ring, waxman
from orbit.model import LinkId, NodeId, Topology

GENERATOR_SETTINGS = settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


def undirected_neighbours(topology: Topology) -> dict[NodeId, set[NodeId]]:
    neighbours: dict[NodeId, set[NodeId]] = {node_id: set() for node_id in topology.nodes}
    for link in topology.links.values():
        neighbours[link.src].add(link.dst)
        neighbours[link.dst].add(link.src)
    return neighbours


def is_connected(topology: Topology) -> bool:
    neighbours = undirected_neighbours(topology)
    start = next(iter(topology.nodes), None)
    if start is None:
        return True
    seen = {start}
    stack = [start]
    while stack:
        for neighbour in sorted(neighbours[stack.pop()]):
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return len(seen) == len(topology.nodes)


def check_structure(topology: Topology, expected_nodes: int) -> None:
    """Every structural property a generated topology must have.

    Self-loops, dangling endpoints and duplicate ids cannot occur — `Link` and `Topology`
    reject them at construction — so asserting them here would only re-test A1's
    validation. What is *not* guaranteed by construction, and is therefore worth asserting,
    is what the generators themselves promise.
    """
    assert len(topology.nodes) == expected_nodes

    for link in topology.links.values():
        reverse = LinkId(f"{link.dst}>{link.src}")
        assert (
            reverse in topology.links
        ), f"link {link.id!r} has no reverse: a cable must be two directed links"
        assert topology.links[reverse].srlg == link.srlg, (
            f"link {link.id!r} and its reverse do not share an SRLG, so a conduit cut "
            "would take only one direction"
        )
        assert len(link.srlg) == 1, f"link {link.id!r} should carry exactly one cable tag"
        assert link.capacity_mbps > 0.0
        assert link.prop_delay_ms >= 0.0

    assert len(topology.links) % 2 == 0, "directed links must come in pairs"
    assert is_connected(topology), "generated topologies must be connected"

    # Zero-padded ids exist so that lexicographic order matches numeric order.
    assert list(topology.nodes) == sorted(topology.nodes)
    if expected_nodes > 10:
        assert "n010" in topology.nodes


def topologies_equal(left: Topology, right: Topology) -> bool:
    return list(left.nodes.items()) == list(right.nodes.items()) and list(
        left.links.items()
    ) == list(right.links.items())


# ------------------------------------------------------------------------------ grid


def test_grid_has_the_exact_lattice_edge_count() -> None:
    """A rows x cols lattice has rows*(cols-1) horizontal and cols*(rows-1) vertical
    cables, each becoming two directed links."""
    rows, cols = 4, 5
    topology = grid(rows, cols)
    cables = rows * (cols - 1) + cols * (rows - 1)
    assert len(topology.links) == 2 * cables
    check_structure(topology, rows * cols)


def test_a_single_row_grid_is_a_line() -> None:
    topology = grid(1, 5)
    assert len(topology.links) == 2 * 4
    check_structure(topology, 5)


def test_a_one_by_one_grid_is_a_single_node_with_no_links() -> None:
    topology = grid(1, 1)
    assert len(topology.nodes) == 1
    assert topology.links == {}


def test_grid_corner_and_interior_degrees_differ() -> None:
    neighbours = undirected_neighbours(grid(3, 3))
    assert len(neighbours[NodeId("n000")]) == 2, "corner"
    assert len(neighbours[NodeId("n004")]) == 4, "centre"


@pytest.mark.parametrize(("rows", "cols"), [(0, 3), (3, 0), (-1, 2)])
def test_grid_rejects_a_degenerate_shape(rows: int, cols: int) -> None:
    with pytest.raises(ValidationError, match="rows and cols"):
        grid(rows, cols)


# ------------------------------------------------------------------------------ ring


def test_ring_is_a_single_cycle_with_every_node_at_degree_two() -> None:
    topology = ring(6)
    assert len(topology.links) == 2 * 6
    neighbours = undirected_neighbours(topology)
    assert all(len(peers) == 2 for peers in neighbours.values())
    check_structure(topology, 6)


def test_a_two_node_ring_is_one_cable_not_a_duplicated_pair() -> None:
    """The wrap-around edge coincides with the forward edge; it must not become a
    parallel link."""
    topology = ring(2)
    assert len(topology.links) == 2
    check_structure(topology, 2)


def test_ring_rejects_fewer_than_two_nodes() -> None:
    """A one-node ring would need a self-loop, which the model rejects."""
    with pytest.raises(ValidationError, match="at least 2 nodes"):
        ring(1)


# --------------------------------------------------------------------------- waxman


def test_waxman_is_deterministic_for_a_given_seed() -> None:
    assert topologies_equal(waxman(30, seed=7), waxman(30, seed=7))


def test_waxman_differs_between_seeds() -> None:
    assert not topologies_equal(waxman(30, seed=7), waxman(30, seed=8))


def test_waxman_scales_propagation_delay_with_distance() -> None:
    """The one family with non-uniform delay, which is why it carries the scale sweep."""
    delays = {link.prop_delay_ms for link in waxman(40, seed=3).links.values()}
    assert len(delays) > 1


def test_waxman_alpha_controls_edge_density() -> None:
    sparse = waxman(40, seed=5, alpha=0.1)
    dense = waxman(40, seed=5, alpha=0.9)
    assert len(dense.links) > len(sparse.links)


def test_waxman_is_connected_even_when_alpha_is_tiny() -> None:
    """With alpha this low the raw graph is almost certainly fragmented, so this exercises
    the connectivity repair rather than the generator's luck."""
    topology = waxman(40, seed=11, alpha=0.01, beta=0.01)
    check_structure(topology, 40)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"alpha": 0.0}, "alpha"),
        ({"alpha": 1.5}, "alpha"),
        ({"beta": 0.0}, "beta"),
        ({"beta": -1.0}, "beta"),
    ],
)
def test_waxman_rejects_out_of_range_parameters(kwargs: dict[str, float], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        waxman(10, seed=1, **kwargs)


def test_waxman_rejects_fewer_than_two_nodes() -> None:
    with pytest.raises(ValidationError, match="at least 2 nodes"):
        waxman(1, seed=1)


# ------------------------------------------------------------------ barabasi-albert


def test_barabasi_albert_adds_exactly_m_edges_per_new_node() -> None:
    """Each node after the seed set attaches to `attachments` distinct existing nodes, and
    the source is new every time, so no edge can repeat."""
    node_count, attachments = 30, 3
    topology = barabasi_albert(node_count, seed=2, attachments=attachments)
    expected_cables = attachments * (node_count - attachments)
    assert len(topology.links) == 2 * expected_cables
    check_structure(topology, node_count)


def test_barabasi_albert_is_deterministic_for_a_given_seed() -> None:
    assert topologies_equal(barabasi_albert(40, seed=4), barabasi_albert(40, seed=4))


def test_barabasi_albert_differs_between_seeds() -> None:
    assert not topologies_equal(barabasi_albert(40, seed=4), barabasi_albert(40, seed=5))


def test_barabasi_albert_produces_hubs() -> None:
    """The property that makes this family interesting: preferential attachment gives a
    heavy-tailed degree distribution, so a targeted failure has something to target."""
    neighbours = undirected_neighbours(barabasi_albert(60, seed=6, attachments=2))
    degrees = sorted(len(peers) for peers in neighbours.values())
    assert (
        degrees[-1] >= 3 * degrees[len(degrees) // 2]
    ), f"no hub emerged: max degree {degrees[-1]}, median {degrees[len(degrees) // 2]}"


def test_barabasi_albert_rejects_attachments_that_leave_nothing_to_attach_to() -> None:
    with pytest.raises(ValidationError, match="must be < node count"):
        barabasi_albert(5, seed=1, attachments=5)


@pytest.mark.parametrize("bad", [0, -1, True, 2.5])
def test_barabasi_albert_rejects_an_unusable_attachment_count(bad: object) -> None:
    with pytest.raises(ValidationError, match="attachments"):
        barabasi_albert(10, seed=1, attachments=bad)  # type: ignore[arg-type]


# ------------------------------------------------------------- across every family


SEEDED_FAMILIES: dict[str, Callable[[int, int], Topology]] = {
    "waxman": lambda n, seed: waxman(n, seed=seed),
    # `attachments` is clamped because it must stay below the node count — at n=2 the only
    # legal value is 1. That constraint is inherent to preferential attachment, not a
    # limitation to work around, so the caller respects it rather than the generator
    # silently adjusting it.
    "barabasi_albert": lambda n, seed: barabasi_albert(n, seed=seed, attachments=min(2, n - 1)),
}


@given(
    family=st.sampled_from(sorted(SEEDED_FAMILIES)),
    node_count=st.integers(min_value=2, max_value=40),
    seed=st.integers(min_value=-1000, max_value=1000),
)
@GENERATOR_SETTINGS
def test_seeded_families_satisfy_the_structural_invariants(
    family: str, node_count: int, seed: int
) -> None:
    check_structure(SEEDED_FAMILIES[family](node_count, seed), node_count)


@given(
    family=st.sampled_from(sorted(SEEDED_FAMILIES)),
    node_count=st.integers(min_value=2, max_value=30),
    seed=st.integers(min_value=-1000, max_value=1000),
)
@GENERATOR_SETTINGS
def test_seeded_families_are_reproducible(family: str, node_count: int, seed: int) -> None:
    """I-DET at the generator: same seed, same topology, byte for byte."""
    build = SEEDED_FAMILIES[family]
    assert topologies_equal(build(node_count, seed), build(node_count, seed))


@given(rows=st.integers(min_value=1, max_value=8), cols=st.integers(min_value=1, max_value=8))
@GENERATOR_SETTINGS
def test_grids_satisfy_the_structural_invariants(rows: int, cols: int) -> None:
    topology = grid(rows, cols)
    if rows * cols == 1:
        assert topology.links == {}
        return
    check_structure(topology, rows * cols)


@given(node_count=st.integers(min_value=2, max_value=40))
@GENERATOR_SETTINGS
def test_rings_satisfy_the_structural_invariants(node_count: int) -> None:
    check_structure(ring(node_count), node_count)


@pytest.mark.parametrize("size", [10, 25, 50, 100])
def test_every_family_builds_at_the_sizes_the_requirements_name(size: int) -> None:
    """Requirement F3 lists 10, 25, 50, 100, 250 and 500. The two largest are excluded
    here to keep the suite fast; nothing about them is special, and the claim in the paper
    will come from a benchmark run, not from this test."""
    check_structure(waxman(size, seed=size), size)
    check_structure(barabasi_albert(size, seed=size), size)
    check_structure(ring(size), size)
    check_structure(grid(size // 5, 5), (size // 5) * 5)
