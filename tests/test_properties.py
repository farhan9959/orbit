"""A2 — property-based tests: the invariants must hold on states nobody wrote down.

docs/05-methodology.md A1 argues that property and differential tests carry the most
weight in a simulator, because the interesting bugs live in the states you did not think
to imagine. These tests generate small random topologies — including failed nodes and
links, links degraded to zero effective capacity, parallel links, and unrouted flows — and
assert the invariants from docs/03-simulation-model.md §9 after every allocation.

The strictly degenerate inputs (zero capacity, zero demand, no flows at all) are covered
by named unit tests in `test_allocator.py` rather than here; see the note on `_CAPACITIES`
for why spending property-test budget on them is counterproductive.

Sizes are kept small (≤ 5 nodes, ≤ 9 links, ≤ 8 flows) on purpose. Invariant violations
are almost always reproducible on a tiny graph, and small examples shrink to something a
human can read.

**The generator is deliberately biased towards congestion, and the bias is measured.**
An unbiased random topology almost never contends. The first version of this generator
reached a genuinely contended link — one with real capacity, saturated, with two or more
competing flows on it — in only a few percent of examples, which meant I-PRIO and I-MAXMIN,
the two invariants that encode the entire point of the allocator, were effectively
untested while the suite cheerfully reported 300 passing examples. Four changes fixed it:

1. every topology starts from a directed ring, so a path exists between every ordered node
   pair (with purely random links, 59% of flows had no path at all and were blackholed
   before the allocator did anything interesting);
2. demands are drawn larger than capacities, and both are kept away from zero;
3. flows are concentrated on a few "hot" source/destination pairs so their routes overlap;
4. element failure rates are high enough to exercise I-DOWN but not so high that most
   traffic is blackholed.

Together these took the contended-scenario rate from a few percent to **41.5%**, and
cross-class contention to **37.0%** (400 derandomised examples).
`test_the_generator_actually_produces_contention` asserts floors under both, so this
cannot silently rot back.
"""

from __future__ import annotations

import random

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from orbit.engine import allocate
from orbit.model import (
    Flow,
    Link,
    LinkId,
    LinkState,
    Node,
    NodeId,
    NodeState,
    Priority,
    Route,
    RoutingState,
    Topology,
)
from tests import invariants

Scenario = tuple[Topology, list[Flow], RoutingState]


def _rates(low: float, high: float) -> st.SearchStrategy[float]:
    """Mbps values in [low, high].

    Subnormal floats are excluded: a capacity of 5e-324 Mbps is not a network, and
    admitting them would make the tolerance argument in the allocator docstring
    meaningless.
    """
    return st.floats(
        min_value=low, max_value=high, allow_nan=False, allow_infinity=False, allow_subnormal=False
    )


# Both are kept strictly away from zero. Hypothesis strongly favours boundary values, so
# an unrestricted [0, high] range spends most of its budget on empty links and idle flows —
# states that satisfy every invariant trivially. Zero capacity and zero demand have
# dedicated unit tests in test_allocator.py and do not need the property budget as well;
# near-zero effective capacity still occurs here, via degraded links.
_CAPACITIES = _rates(1.0, 50.0)
_DEMANDS = _rates(1.0, 60.0)
"""Demands run above capacities on purpose, so links actually fill up. See module docstring."""


def _simple_paths(
    topology: Topology, src: NodeId, dst: NodeId, limit: int = 6
) -> list[tuple[LinkId, ...]]:
    """Enumerate up to `limit` simple paths, ignoring operational state.

    State is ignored because routes are structural: a control plane may legitimately hold
    a route whose links have since failed, and the allocator must handle exactly that.
    """
    found: list[tuple[LinkId, ...]] = []

    def walk(node: NodeId, visited: frozenset[NodeId], links: tuple[LinkId, ...]) -> None:
        if len(found) >= limit:
            return
        if node == dst:
            found.append(links)
            return
        for link in topology.links_from(node):
            if link.dst in visited:
                continue
            walk(link.dst, visited | {link.dst}, (*links, link.id))

    walk(src, frozenset({src}), ())
    return found


@st.composite
def scenarios(draw: st.DrawFn) -> Scenario:
    """A random topology, traffic matrix and routing, biased towards contention."""
    node_count = draw(st.integers(min_value=2, max_value=5))
    node_ids = [NodeId(f"n{i}") for i in range(node_count)]
    # Weighted towards UP: a graph where most nodes are down exercises little.
    node_states = st.sampled_from([NodeState.UP] * 14 + [NodeState.DOWN])
    nodes = [Node(node_id, state=draw(node_states)) for node_id in node_ids]

    pairs = [(a, b) for a in node_ids for b in node_ids if a != b]
    # Every topology starts as a directed ring, then gains random extra links. Purely
    # random endpoints leave most node pairs unreachable — measured, 59% of flows ended up
    # with no path at all — which wastes the property budget on flows that are blackholed
    # before the allocator does any interesting work. The ring guarantees a path between
    # every ordered pair, and because ring paths are long they overlap, which is what
    # produces contention. Parallel links still appear via the extra links.
    ring = [(node_ids[i], node_ids[(i + 1) % node_count]) for i in range(node_count)]
    endpoints = ring + draw(st.lists(st.sampled_from(pairs), min_size=0, max_size=4))
    # Failures stay in the mix — I-DOWN needs them — but at a rate that leaves most
    # scenarios with live traffic to allocate. Ring paths are several hops long, so a 10%
    # per-link failure rate blackholed roughly 60% of all routed flows.
    link_states = st.sampled_from([LinkState.UP] * 14 + [LinkState.DOWN, LinkState.DEGRADED])
    links = [
        Link(
            LinkId(f"e{index}"),
            src,
            dst,
            capacity_mbps=draw(_CAPACITIES),
            state=draw(link_states),
            degrade_factor=draw(_rates(0.0, 1.0)),
        )
        for index, (src, dst) in enumerate(endpoints)
    ]
    topology = Topology(nodes, links)

    # Concentrating traffic on a few pairs is what makes routes overlap and links fill.
    hot_pairs = draw(st.lists(st.sampled_from(pairs), min_size=1, max_size=3, unique=True))
    endpoint_choice = st.one_of(
        st.sampled_from(hot_pairs), st.sampled_from(hot_pairs), st.sampled_from(pairs)
    )

    flows: list[Flow] = []
    routing: dict[str, Route] = {}
    # At least one flow: the empty-input case has its own unit test and would otherwise
    # consume property-test budget on a scenario with nothing to check.
    for index in range(draw(st.integers(min_value=1, max_value=8))):
        src, dst = draw(endpoint_choice)
        flow = Flow(
            f"f{index}",
            src,
            dst,
            demand_mbps=draw(_DEMANDS),
            priority=draw(st.sampled_from(list(Priority))),
        )
        flows.append(flow)
        paths = _simple_paths(topology, src, dst)
        # Roughly one flow in five is left unrouted, which is what a partitioned or
        # unrecovered flow looks like to the allocator.
        if paths and draw(st.integers(min_value=0, max_value=4)) > 0:
            routing[flow.id] = Route.build(topology, draw(st.sampled_from(paths)))
    return topology, flows, routing


PROPERTY_SETTINGS = settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


def _contention(scenario: Scenario) -> tuple[bool, bool]:
    """Return (a link is genuinely contended, that contention crosses priority classes).

    "Genuinely contended" means a link with real capacity is full while two or more flows
    that could have used it are competing. A zero-capacity link is full by definition and
    proves nothing about fairness, so it does not count.
    """
    topology, flows, routing = scenario
    allocation = allocate(topology, flows, routing)
    contended = cross_class = False
    for link_id in topology.links:
        if topology.link(link_id).effective_capacity_mbps <= 0.0:
            continue
        competing = [
            flow
            for flow in flows
            if flow.id in routing
            and link_id in routing[flow.id].links
            and flow.id not in allocation.blackholed
            and flow.demand_mbps > 0.0
        ]
        if len(competing) >= 2 and invariants._is_saturated(topology, allocation, link_id):
            contended = True
            cross_class |= len({flow.priority for flow in competing}) >= 2
    return contended, cross_class


def test_the_generator_actually_produces_contention() -> None:
    """The property suite is only as good as the states it reaches.

    An earlier version of `scenarios()` produced a genuinely contended link in only a few
    percent of examples, so I-PRIO and I-MAXMIN were almost never exercised while the
    suite reported hundreds of passing examples. This test measures the generator instead
    of trusting it.

    `derandomize=True` fixes the seed, so the measured rate is reproducible and this test
    cannot flake. The thresholds sit well below the rates measured at the time of writing
    (41.5% contended, 37.0% cross-class over 400 examples), so they fail on a real
    regression in the generator rather than on noise.
    """
    contended = cross_class = total = 0

    @settings(max_examples=200, deadline=None, derandomize=True, database=None)
    @given(scenarios())
    def sample(scenario: Scenario) -> None:
        nonlocal contended, cross_class, total
        total += 1
        one, two = _contention(scenario)
        contended += one
        cross_class += two

    sample()

    assert contended / total >= 0.25, f"only {contended}/{total} scenarios contend"
    assert cross_class / total >= 0.15, (
        f"only {cross_class}/{total} scenarios contend across priority classes, so I-PRIO "
        "is barely being tested"
    )


@given(scenarios())
@PROPERTY_SETTINGS
def test_every_allocator_invariant_holds(scenario: Scenario) -> None:
    """I-CAP, I-DEMAND, I-DOWN, I-PRIO, I-MAXMIN, and no silently lost demand."""
    topology, flows, routing = scenario
    invariants.check_all(topology, flows, routing, allocate(topology, flows, routing))


@given(scenarios())
@PROPERTY_SETTINGS
def test_allocation_is_deterministic_under_repetition(scenario: Scenario) -> None:
    """I-DET, the narrow form: the same call twice gives byte-identical output."""
    topology, flows, routing = scenario
    first = allocate(topology, flows, routing)
    second = allocate(topology, flows, routing)
    assert dict(first.rates) == dict(second.rates)
    assert dict(first.link_load) == dict(second.link_load)
    assert first.blackholed == second.blackholed


@given(scenarios(), st.randoms(use_true_random=False))
@PROPERTY_SETTINGS
def test_allocation_does_not_depend_on_the_order_flows_arrive_in(
    scenario: Scenario, rng: random.Random
) -> None:
    """I-DET, the form that actually breaks in practice.

    Determinism is lost when some caller iterates a set or merges results in a different
    order. Sorting by flow id inside the allocator is what prevents it.

    **Key order is asserted, not just the values.** The rates happen to come out
    order-independent anyway — every flow in a round is raised by the same `step`, and
    adding one identical value n times is order-independent in floating point — so
    comparing values alone passes even with the sort deleted. What the sort really fixes
    is the *iteration order of the result*, which is what the CI determinism gate hashes
    (docs/05-methodology.md A1, and N3). This assertion is the one that fails without it.
    """
    topology, flows, routing = scenario
    shuffled = list(flows)
    rng.shuffle(shuffled)

    original = allocate(topology, flows, routing)
    permuted = allocate(topology, shuffled, routing)

    assert dict(original.rates) == dict(permuted.rates)
    assert dict(original.link_load) == dict(permuted.link_load)
    assert list(original.rates) == list(permuted.rates)
    assert list(original.link_load) == list(permuted.link_load)


@given(scenarios())
@PROPERTY_SETTINGS
def test_removing_low_priority_flows_cannot_change_the_higher_classes(
    scenario: Scenario,
) -> None:
    """The operational meaning of strict priority, stated as an independent property.

    If deleting every LOW flow changed what a CRITICAL flow received, then LOW traffic had
    been taking capacity from CRITICAL — which is the exact failure I-PRIO exists to
    prevent, expressed without reference to bottlenecks.
    """
    topology, flows, routing = scenario
    senior = [flow for flow in flows if flow.priority is not Priority.LOW]

    with_low = allocate(topology, flows, routing)
    without_low = allocate(topology, senior, routing)

    for flow in senior:
        assert with_low.rates[flow.id] == without_low.rates[flow.id], (
            f"removing LOW traffic changed {flow.priority.name} flow {flow.id!r} from "
            f"{with_low.rates[flow.id]!r} to {without_low.rates[flow.id]!r}"
        )


@given(scenarios())
@PROPERTY_SETTINGS
def test_total_delivered_never_exceeds_total_demanded(scenario: Scenario) -> None:
    """Conservation at the aggregate level: no traffic is created out of nothing."""
    topology, flows, routing = scenario
    allocation = allocate(topology, flows, routing)
    delivered = sum(allocation.rates.values())
    demanded = sum(flow.demand_mbps for flow in flows)
    assert delivered <= demanded + invariants.TOL * max(1.0, demanded)
