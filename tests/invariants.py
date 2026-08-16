"""Executable statements of the allocator invariants from docs/03-simulation-model.md §9.

These are checkers, not tests. They are called by the example-based tests in
`test_allocator.py` and by the Hypothesis tests in `test_properties.py`, so an invariant is
stated exactly once and every test benefits when one is tightened.

Each checker asserts a *mathematical* property of the output, computed independently of
how the allocator arrived at it. None of them re-runs the algorithm, so none of them can
agree with a bug by sharing it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from orbit.engine.allocator import Allocation
from orbit.model import Flow, LinkId, Priority, RoutingState, Topology

TOL = 1e-9
"""Same relative tolerance the allocator uses; see `orbit.engine.allocator._EPS`."""


def _capacity(topology: Topology, link_id: LinkId) -> float:
    return topology.link(link_id).effective_capacity_mbps


def _is_saturated(topology: Topology, allocation: Allocation, link_id: LinkId) -> bool:
    capacity = _capacity(topology, link_id)
    return capacity - allocation.load_on(link_id) <= TOL * max(1.0, capacity)


def _routed_flows_on(flows: Sequence[Flow], routing: RoutingState, link_id: LinkId) -> list[Flow]:
    return [flow for flow in flows if flow.id in routing and link_id in routing[flow.id].links]


def _is_satisfied(flow: Flow, allocation: Allocation) -> bool:
    shortfall = flow.demand_mbps - allocation.rates[flow.id]
    return shortfall <= TOL * max(1.0, flow.demand_mbps)


def check_capacity(topology: Topology, allocation: Allocation) -> None:
    """I-CAP — no link carries more than its effective capacity."""
    for link_id, load in allocation.link_load.items():
        capacity = _capacity(topology, link_id)
        assert load <= capacity + TOL * max(
            1.0, capacity
        ), f"I-CAP violated on link {link_id!r}: load {load!r} > capacity {capacity!r}"
        assert load >= 0.0, f"I-CAP violated on link {link_id!r}: negative load {load!r}"


def check_demand(flows: Iterable[Flow], allocation: Allocation) -> None:
    """I-DEMAND — no flow receives more than it asked for, or a negative rate."""
    for flow in flows:
        rate = allocation.rates[flow.id]
        assert rate >= 0.0, f"I-DEMAND violated: flow {flow.id!r} has negative rate {rate!r}"
        assert rate <= flow.demand_mbps + TOL * max(
            1.0, flow.demand_mbps
        ), f"I-DEMAND violated: flow {flow.id!r} got {rate!r} > demand {flow.demand_mbps!r}"


def check_no_traffic_over_failed_elements(
    topology: Topology, flows: Sequence[Flow], routing: RoutingState, allocation: Allocation
) -> None:
    """I-DOWN — nothing is delivered across a DOWN link or through a DOWN node."""
    for link_id in topology.links:
        if not topology.is_usable(link_id):
            assert allocation.load_on(link_id) == 0.0, (
                f"I-DOWN violated: unusable link {link_id!r} carries "
                f"{allocation.load_on(link_id)!r}"
            )
    for flow in flows:
        if allocation.rates[flow.id] <= 0.0:
            continue
        route = routing.get(flow.id)
        assert route is not None, (
            f"I-DOWN violated: unrouted flow {flow.id!r} was allocated "
            f"{allocation.rates[flow.id]!r}"
        )
        for link_id in route.links:
            assert topology.is_usable(
                link_id
            ), f"I-DOWN violated: flow {flow.id!r} is served over unusable link {link_id!r}"
        assert flow.id not in allocation.blackholed, (
            f"flow {flow.id!r} is reported BLACKHOLED but was allocated "
            f"{allocation.rates[flow.id]!r}"
        )


def check_blackholing_is_accurate(
    topology: Topology, flows: Sequence[Flow], routing: RoutingState, allocation: Allocation
) -> None:
    """A flow is BLACKHOLED exactly when it has no live route.

    Starvation by strict priority is *not* blackholing; the two must stay distinguishable
    or the metrics cannot answer "did recovery find a route?".
    """
    for flow in flows:
        route = routing.get(flow.id)
        has_live_route = route is not None and all(
            topology.is_usable(link_id) for link_id in route.links
        )
        assert (flow.id in allocation.blackholed) is not has_live_route, (
            f"flow {flow.id!r}: blackholed={flow.id in allocation.blackholed} but "
            f"has_live_route={has_live_route}"
        )


def check_no_silent_loss(
    topology: Topology, flows: Sequence[Flow], routing: RoutingState, allocation: Allocation
) -> None:
    """Every shortfall has a cause: no route, no demand, or a saturated link on the path.

    This is the check that would catch an allocator that quietly drops demand — the one
    failure mode that produces plausible-looking numbers and invalidates the study.
    """
    for flow in flows:
        if _is_satisfied(flow, allocation) or flow.demand_mbps == 0.0:
            continue
        if flow.id in allocation.blackholed:
            continue
        route = routing[flow.id]
        assert any(_is_saturated(topology, allocation, link_id) for link_id in route.links), (
            f"flow {flow.id!r} got {allocation.rates[flow.id]!r} of {flow.demand_mbps!r} "
            "but no link on its route is saturated — demand was lost with no cause"
        )


def check_strict_priority(
    topology: Topology, flows: Sequence[Flow], routing: RoutingState, allocation: Allocation
) -> None:
    """I-PRIO — a lower class never takes capacity a higher class still needs.

    Stated over the bottleneck, which is the only place precedence is observable: if a
    flow is unsatisfied and link `e` is its *only* saturated link, then every
    lower-priority flow crossing `e` must have received nothing.
    """
    for link_id in topology.links:
        on_link = _routed_flows_on(flows, routing, link_id)
        for senior in on_link:
            if _is_satisfied(senior, allocation) or senior.id in allocation.blackholed:
                continue
            saturated = {
                other
                for other in routing[senior.id].links
                if _is_saturated(topology, allocation, other)
            }
            if saturated != {link_id}:
                continue  # constrained elsewhere too; this link proves nothing
            for junior in on_link:
                if junior.priority >= senior.priority:
                    continue
                assert allocation.rates[junior.id] <= TOL, (
                    f"I-PRIO violated on link {link_id!r}: {junior.priority.name} flow "
                    f"{junior.id!r} holds {allocation.rates[junior.id]!r} while "
                    f"{senior.priority.name} flow {senior.id!r} is unsatisfied there"
                )


def check_max_min_fair_within_class(
    topology: Topology, flows: Sequence[Flow], routing: RoutingState, allocation: Allocation
) -> None:
    """I-MAXMIN — the bottleneck characterisation of max-min fairness, per class.

    An allocation is max-min fair within a class iff every unsatisfied flow of that class
    has a saturated link on its route where its own rate is at least as large as that of
    every same-class flow crossing that link. If some same-class flow there had more, we
    could move capacity from it to us and improve the lexicographically-sorted rate
    vector — so the allocation would not be max-min fair.
    """
    for priority in Priority:
        peers = [flow for flow in flows if flow.priority is priority]
        for flow in peers:
            if flow.id in allocation.blackholed or _is_satisfied(flow, allocation):
                continue
            rate = allocation.rates[flow.id]
            has_bottleneck = False
            for link_id in routing[flow.id].links:
                if not _is_saturated(topology, allocation, link_id):
                    continue
                competitors = [
                    peer
                    for peer in _routed_flows_on(peers, routing, link_id)
                    if peer.id not in allocation.blackholed
                ]
                if all(
                    allocation.rates[peer.id] <= rate + TOL * max(1.0, rate) for peer in competitors
                ):
                    has_bottleneck = True
                    break
            assert has_bottleneck, (
                f"I-MAXMIN violated: {priority.name} flow {flow.id!r} got {rate!r} of "
                f"{flow.demand_mbps!r} with no saturated link on its route where it holds "
                "a maximal share"
            )


def check_all(
    topology: Topology, flows: Sequence[Flow], routing: RoutingState, allocation: Allocation
) -> None:
    """Run every invariant checker. Used by the property tests."""
    check_capacity(topology, allocation)
    check_demand(flows, allocation)
    check_no_traffic_over_failed_elements(topology, flows, routing, allocation)
    check_blackholing_is_accurate(topology, flows, routing, allocation)
    check_no_silent_loss(topology, flows, routing, allocation)
    check_strict_priority(topology, flows, routing, allocation)
    check_max_min_fair_within_class(topology, flows, routing, allocation)
