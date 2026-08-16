"""Seeded topology generators: grid, ring, Waxman, and Barabasi-Albert.

Implements requirement F2 (docs/01-requirements.md §3) for the four synthetic families.
Loading hand-written topologies from a spec file is the other half of F2 and belongs with
the scenario schema, which does not exist yet.

Shared conventions
------------------
**A cable is two directed links sharing an SRLG.** `Link` is directed
(docs/03-simulation-model.md §2), so every undirected adjacency produced here becomes a
forward and a reverse link tagged `cable:<a>-<b>`. A regional or conduit failure that
takes the SRLG therefore takes both directions, which is the realistic behaviour and the
thing that defeats a backup path sharing physical fate with its primary.

**Node ids are zero-padded** (`n000`, `n001`, ...). All iteration in this project is over
sorted ids, and unpadded ids would sort `n10` before `n2` — harmless for determinism, but
it makes every debugging session and every event log harder to read than it needs to be.

**Link ids name their endpoints** (`n000>n001`). A generated topology is something a human
reads while debugging a route; an opaque `e0417` would mean cross-referencing on every
lookup. Parallel links are impossible in these families, so endpoint-derived ids are
unique by construction.

Assumptions and limitations
---------------------------
* Capacity and propagation delay are uniform across links, except that Waxman scales delay
  by Euclidean distance. Heterogeneous capacity is a scenario concern, not a topology one,
  and there is no consumer for it yet.
* Waxman node coordinates are used to compute edge probability and are then discarded.
  Requirement F5 (persist coordinates so visualisations are stable) is a Tier-B concern
  and is satisfiable without storing them here, because regenerating with the same seed
  reproduces the same coordinates exactly.
* Every returned topology is connected as an undirected graph. See `_repair_connectivity`.
* These are synthetic families. They are not claimed to resemble any real ISP; the
  Internet Topology Zoo is listed as a stretch item in docs/05-methodology.md B1.
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable, Iterable, Sequence

from orbit.errors import ValidationError
from orbit.model import Link, LinkId, Node, NodeId, Topology
from orbit.rng import rng_for

Edge = tuple[int, int]
"""An undirected adjacency between two node indices, always stored with `a < b`."""

DEFAULT_CAPACITY_MBPS = 100.0
DEFAULT_PROP_DELAY_MS = 1.0


def _node_id(index: int, width: int) -> NodeId:
    return NodeId(f"n{index:0{width}d}")


def _id_width(node_count: int) -> int:
    """Digits needed so that lexicographic id order matches numeric node order."""
    return max(3, len(str(node_count - 1)))


def _require_size(node_count: int, minimum: int, family: str) -> None:
    if isinstance(node_count, bool) or not isinstance(node_count, int):
        raise ValidationError(f"{family}: node count must be an int, got {node_count!r}")
    if node_count < minimum:
        raise ValidationError(f"{family}: needs at least {minimum} nodes, got {node_count}")


def _build(
    node_count: int,
    edges: Iterable[Edge],
    *,
    capacity_mbps: float,
    delay_for: Callable[[Edge], float] | None = None,
    prop_delay_ms: float = DEFAULT_PROP_DELAY_MS,
) -> Topology:
    """Assemble a `Topology` from node indices and undirected adjacencies.

    `delay_for`, when given, is called with an edge and returns that cable's one-way
    propagation delay; otherwise every link gets `prop_delay_ms`.
    """
    width = _id_width(node_count)
    nodes = [Node(_node_id(index, width)) for index in range(node_count)]

    links: list[Link] = []
    for a, b in sorted(set(edges)):
        src, dst = _node_id(a, width), _node_id(b, width)
        delay = prop_delay_ms if delay_for is None else delay_for((a, b))
        cable = frozenset({f"cable:{src}-{dst}"})
        for tail, head in ((src, dst), (dst, src)):
            links.append(
                Link(
                    LinkId(f"{tail}>{head}"),
                    tail,
                    head,
                    capacity_mbps=capacity_mbps,
                    prop_delay_ms=delay,
                    srlg=cable,
                )
            )
    return Topology(nodes, links)


def _components(node_count: int, edges: Iterable[Edge]) -> list[list[int]]:
    """Undirected connected components, each sorted, ordered by smallest member.

    Union-find with path halving. Deterministic: the output depends only on the node count
    and the edge set, never on iteration order of a set or dict.
    """
    parent = list(range(node_count))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    grouped: dict[int, list[int]] = {}
    for node in range(node_count):
        grouped.setdefault(find(node), []).append(node)
    return [grouped[root] for root in sorted(grouped)]


def _repair_connectivity(node_count: int, edges: set[Edge]) -> set[Edge]:
    """Add the fewest edges needed to make the graph connected, deterministically.

    A disconnected topology is legal (the model permits it, and partitioned flows must be
    BLACKHOLED and censored rather than rejected), but it is a poor *benchmark* input: a
    generator that silently returns two islands produces runs where most traffic is
    unroutable before any failure is injected, which would flatter or punish algorithms for
    reasons unrelated to what is being measured.

    Components are chained in ascending order by their smallest member, joining each
    component's smallest node to the next component's smallest node. The choice is
    arbitrary but fixed, which is what matters — it must not depend on the RNG, or the
    repair would consume draws and shift every subsequent random decision.
    """
    components = _components(node_count, edges)
    repaired = set(edges)
    for left, right in itertools.pairwise(components):
        a, b = left[0], right[0]
        repaired.add((min(a, b), max(a, b)))
    return repaired


def grid(
    rows: int,
    cols: int,
    *,
    capacity_mbps: float = DEFAULT_CAPACITY_MBPS,
    prop_delay_ms: float = DEFAULT_PROP_DELAY_MS,
) -> Topology:
    """A `rows` x `cols` rectangular lattice, nodes numbered row-major.

    Deterministic with no seed: there is nothing random about a lattice. Its value as a
    benchmark family is that it is regular and highly connected, so a single link failure
    has an obvious alternative and shortest-path reconvergence looks its best.
    """
    if min(rows, cols) < 1:
        raise ValidationError(f"grid: rows and cols must be >= 1, got {rows}x{cols}")
    node_count = rows * cols
    _require_size(node_count, 1, "grid")

    edges: set[Edge] = set()
    for row in range(rows):
        for col in range(cols):
            index = row * cols + col
            if col + 1 < cols:
                edges.add((index, index + 1))
            if row + 1 < rows:
                edges.add((index, index + cols))
    return _build(node_count, edges, capacity_mbps=capacity_mbps, prop_delay_ms=prop_delay_ms)


def ring(
    node_count: int,
    *,
    capacity_mbps: float = DEFAULT_CAPACITY_MBPS,
    prop_delay_ms: float = DEFAULT_PROP_DELAY_MS,
) -> Topology:
    """A single cycle of `node_count` nodes.

    The pessimistic family: every node has degree two, so any single cable cut leaves
    exactly one path between the separated halves and any two cuts partition the network.
    Deterministic with no seed.
    """
    _require_size(node_count, 2, "ring")
    if node_count == 2:
        # Two nodes joined by one cable. Adding the "wrap-around" edge as well would be a
        # second edge between the same pair, which _build would deduplicate anyway.
        edges = {(0, 1)}
    else:
        edges = {(index, (index + 1) % node_count) for index in range(node_count)}
        edges = {(min(a, b), max(a, b)) for a, b in edges}
    return _build(node_count, edges, capacity_mbps=capacity_mbps, prop_delay_ms=prop_delay_ms)


def waxman(
    node_count: int,
    *,
    seed: int,
    alpha: float = 0.4,
    beta: float = 0.2,
    capacity_mbps: float = DEFAULT_CAPACITY_MBPS,
    prop_delay_ms: float = DEFAULT_PROP_DELAY_MS,
) -> Topology:
    """Waxman (1988) random geometric graph on the unit square.

    Nodes are placed uniformly at random; each pair is joined with probability

        P(u, v) = alpha * exp(-d(u, v) / (beta * L))

    where `d` is Euclidean distance and `L` is the largest distance between any two nodes.
    `alpha` raises the overall edge density; `beta` raises the share of long edges.

    Propagation delay is `prop_delay_ms * d(u, v)`, so distance is visible to any
    latency-aware algorithm. This is the only family here with non-uniform delay, and it is
    the reason Waxman is used for the scale and load sweeps in docs/05-methodology.md B1.

    The result is always connected; see `_repair_connectivity` for how and why.
    """
    _require_size(node_count, 2, "waxman")
    if not 0.0 < alpha <= 1.0:
        raise ValidationError(f"waxman: alpha must be in (0, 1], got {alpha!r}")
    if beta <= 0.0:
        raise ValidationError(f"waxman: beta must be > 0, got {beta!r}")

    rng = rng_for(seed, "topology.waxman")
    points = [(rng.random(), rng.random()) for _ in range(node_count)]

    def distance(a: int, b: int) -> float:
        return math.hypot(points[a][0] - points[b][0], points[a][1] - points[b][1])

    pairs = [(a, b) for a in range(node_count) for b in range(a + 1, node_count)]
    longest = max((distance(a, b) for a, b in pairs), default=0.0)
    if longest == 0.0:
        # Every node landed on the same point. Astronomically unlikely, but the alternative
        # is a division by zero in a benchmark that has already been running for an hour.
        longest = 1.0

    edges = {
        (a, b)
        for a, b in pairs
        if rng.random() < alpha * math.exp(-distance(a, b) / (beta * longest))
    }
    edges = _repair_connectivity(node_count, edges)
    return _build(
        node_count,
        edges,
        capacity_mbps=capacity_mbps,
        delay_for=lambda edge: prop_delay_ms * distance(*edge),
    )


def barabasi_albert(
    node_count: int,
    *,
    seed: int,
    attachments: int = 2,
    capacity_mbps: float = DEFAULT_CAPACITY_MBPS,
    prop_delay_ms: float = DEFAULT_PROP_DELAY_MS,
) -> Topology:
    """Barabasi-Albert (1999) preferential-attachment scale-free graph.

    Starts with `attachments` isolated nodes; every subsequent node joins to `attachments`
    existing nodes chosen with probability proportional to their degree. The resulting
    degree distribution is heavy-tailed, so the topology has hubs.

    Hubs are the point of this family. A targeted failure of the highest-betweenness node
    is devastating here and unremarkable on a grid, which is exactly the contrast the
    failure-scenario sweep in docs/05-methodology.md B1 is designed to expose.

    Connected by construction: every node added after the seed set attaches to at least one
    existing node, and the first such node attaches to all of the seed set.
    """
    _require_size(node_count, 2, "barabasi_albert")
    if isinstance(attachments, bool) or not isinstance(attachments, int) or attachments < 1:
        raise ValidationError(
            f"barabasi_albert: attachments must be an int >= 1, got {attachments!r}"
        )
    if attachments >= node_count:
        raise ValidationError(
            f"barabasi_albert: attachments ({attachments}) must be < node count "
            f"({node_count}); there would be nothing left to attach to"
        )

    rng = rng_for(seed, "topology.barabasi_albert")
    edges: set[Edge] = set()
    # One entry per edge endpoint, so sampling uniformly from it samples nodes in
    # proportion to their degree. This is the standard trick and it is why preferential
    # attachment costs O(1) per draw instead of a scan over the degree table.
    endpoint_pool: list[int] = []
    targets = list(range(attachments))

    for source in range(attachments, node_count):
        for target in targets:
            edges.add((min(source, target), max(source, target)))
        endpoint_pool.extend(targets)
        endpoint_pool.extend([source] * attachments)
        targets = _weighted_sample(endpoint_pool, attachments, rng)

    return _build(node_count, edges, capacity_mbps=capacity_mbps, prop_delay_ms=prop_delay_ms)


def _weighted_sample(pool: Sequence[int], count: int, rng: random.Random) -> list[int]:
    """Draw `count` distinct values from `pool`, each draw uniform over the pool.

    Because `pool` holds a node once per incident edge endpoint, uniform draws from it are
    degree-proportional draws over nodes. Returned sorted so that the caller's subsequent
    edge insertion order does not depend on draw order.
    """
    chosen: set[int] = set()
    while len(chosen) < count:
        chosen.add(rng.choice(pool))
    return sorted(chosen)
