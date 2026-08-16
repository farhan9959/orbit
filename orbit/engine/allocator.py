"""Link-capacity allocation: strict priority between classes, max-min fairness within one.

Implements docs/03-simulation-model.md §4 (requirement F8) and enforces invariants I-CAP,
I-DEMAND, I-DOWN and I-PRIO.

This module is the physics of the simulator. If it is wrong, every number the project
reports is wrong, so the algorithm is written out in the open rather than hidden behind an
abstraction, and every step below is testable on its own.


1. Objective
------------
Let `F` be the active flows, `E` the links, `d_f > 0` the demand of flow `f`, `c_e` the
effective capacity of link `e`, and `R_f ⊆ E` the links on `f`'s installed route. We choose
rates `x_f ≥ 0` subject to

    (C1)  x_f ≤ d_f                              for every flow f          [I-DEMAND]
    (C2)  Σ_{f : e ∈ R_f} x_f ≤ c_e              for every link e          [I-CAP]
    (C3)  x_f = 0                                if f has no live route    [I-DOWN]

Among the vectors satisfying those constraints we want the one that is, in order:

    (O1)  lexicographically optimal by priority class — no rate in class k can be raised
          without lowering some rate in a class ranked k or higher;
    (O2)  max-min fair within each class.

(O1) is *strict priority*: LOW receives only what CRITICAL, HIGH and NORMAL leave behind,
and under heavy overload LOW can be driven to zero. That starvation is intended — it is
the mechanism hypothesis H1 depends on — and it is reported, not hidden
(docs/01-requirements.md §2).

(O2) is *max-min fairness* in the sense of Bertsekas & Gallager: a feasible allocation `x`
is max-min fair within a class iff for every flow `f` of that class with `x_f < d_f` there
is a saturated link `e ∈ R_f` on which `x_f ≥ x_g` for every flow `g` of that class
crossing `e`. In words: you cannot increase anybody without decreasing somebody who
already has no more than you. That link `e` is `f`'s *bottleneck*, and this characterisation
is exactly what `tests/test_properties.py` asserts — it is checkable directly from the
output, without re-running the algorithm.


2. Inputs
---------
* `topology`  — nodes and links with their current operational state. Supplies effective
                capacity and liveness. Never mutated (I-NOCREATE).
* `flows`     — the demands offered this tick. Flow ids must be unique.
* `routing`   — installed routes by flow id. A missing entry means "no route".

Time is not an input. The allocator resolves contention for one instant; deciding which
flows are active at that instant belongs to the tick loop.


3. Outputs
----------
An `Allocation` giving each flow's delivered rate, the resulting load on each link, and
the set of flows that were BLACKHOLED. Starvation and blackholing are reported separately
on purpose: a flow starved to 0 by strict priority had a working path, a blackholed flow
had none, and conflating them would make "did the recovery mechanism find a route?"
unanswerable from the metrics.


4. Algorithm — progressive filling, per class
---------------------------------------------
Classes are processed CRITICAL → HIGH → NORMAL → LOW, each seeing only the capacity its
seniors left. Within one class:

    all rates start at 0 and all flows are "unfixed"
    while unfixed flows remain:
        t_link   = min over links e carrying n_e ≥ 1 unfixed flows of  residual(e) / n_e
        t_demand = min over unfixed flows f of  (d_f - x_f)
        t        = min(t_link, t_demand)
        raise every unfixed flow's rate by t                    # the water level rises
        fix (remove) every unfixed flow that reached its demand
        fix (remove) every unfixed flow crossing a now-saturated link

This is the water-filling picture made literal: every competing flow's rate rises together
at the same speed, and a flow stops rising the moment it is satisfied or the moment one of
its links fills up. The two stopping conditions are why `t` is a minimum over both.

*Why it terminates.* Each iteration removes at least one flow. If `t = t_demand` the flow
achieving that minimum is satisfied; if `t = t_link` the link achieving that minimum
becomes saturated and the `n_e ≥ 1` flows crossing it can rise no further. So a class of
`n` flows takes at most `n` iterations. (docs/03-simulation-model.md §4 states a bound of
`|E|` outer iterations, which is the bound for the textbook variant with no demand caps;
with demand caps a flow can also be removed by being satisfied, so `n` is the bound that
actually holds. Both are finite; `min(n, |E| + n)` is tight.)

*Why residuals are recomputed rather than decremented.* Keeping a running `residual[e]`
and subtracting `t * n_e` each round accumulates floating-point error in the one quantity
I-CAP is stated over. Recomputing `residual(e) = c_e - load[e]` from the authoritative
load costs the same asymptotically — every round already touches every unfixed flow's
links — and keeps the error at a couple of ULPs instead of letting it drift.


5. Complexity
-------------
Let `n` be the flows in a class and `P = Σ_f |R_f|` the total path length over that class.
One iteration costs `O(P)`: one pass to count unfixed flows per link, one to raise rates,
one to test the removal conditions. With at most `n` iterations the worst case is `O(n·P)`,
plus `O(|F| log |F|)` for the initial sort. Memory is `O(|F| + |E|)`.

The worst case needs every round to fix exactly one flow. Typical rounds fix many at once,
and the observed number of rounds is small. If profiling later shows this is the hot loop,
docs/02-architecture.md §8 already names the mitigation.

# ponytail: O(n·P) worst case in pure Python; vectorise the inner passes with NumPy only
# when a profile of a real benchmark cell says the allocator dominates (architecture §8
# mitigation 3). Do not pre-optimise a loop that has never been measured.


6. Edge cases, and what each does
---------------------------------
| Case                              | Behaviour                                          |
|-----------------------------------|----------------------------------------------------|
| flow with no route                | rate 0, reported BLACKHOLED                        |
| route crossing a DOWN link        | rate 0, reported BLACKHOLED (I-DOWN)               |
| route crossing a DOWN node        | rate 0, reported BLACKHOLED (endpoint check)       |
| zero-capacity link on the route   | rate 0, routed, **not** blackholed; no division    |
| fully degraded link (factor 0)    | as above                                           |
| zero-demand flow                  | rate 0, routed, not blackholed; never enters fill  |
| no flows / no routes              | empty allocation, not an error                     |
| demand exactly equals capacity    | fully served; the link ends exactly saturated      |
| duplicate flow ids                | rejected — silently merging them would lose demand |
| route naming an unknown link      | rejected by `Topology.link`                        |


7. Determinism
--------------
Same input, same output, bit for bit (I-DET). Flows are sorted by id before anything else,
so every floating-point summation happens in the same order regardless of the order the
caller supplied. There is no randomness, no clock, and no dependence on dict insertion
order. This holds for a fixed platform and interpreter; cross-platform bit-identity is not
claimed (docs/03-simulation-model.md §3).


8. Known limitations
--------------------
* **Single-path only.** A flow's demand traverses one route. ECMP (baseline B3) splits a
  demand across equal-cost paths and will therefore be modelled as several sub-flows, one
  per path, rather than by changing this allocator.
* **No oversubscription mode.** I-CAP allows scenarios that explicitly permit exceeding
  capacity; none exist, so none is implemented.
* **Tolerance, not exactness.** Saturation and satisfaction are decided with a relative
  tolerance of 1e-9 (see `_EPS`). Sums of floats cannot be compared exactly, so I-CAP
  holds to `capacity·(1 + 1e-9)`, and the invariant tests assert it with that same
  tolerance. At the capacities used here (Mbps, ≤ 1e6) that is several orders of magnitude
  above the ULP and far below any physically meaningful rate.
* **Weighted fair queueing is not implemented.** docs/03-simulation-model.md §4 proposes it
  as a configurable alternative to strict priority so the "strict priority starves LOW"
  critique can be answered with data. It has no consumer until the experiment runner
  exists, so it is deferred rather than guessed at.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from orbit.errors import ValidationError
from orbit.model import Flow, FlowId, LinkId, Priority, RoutingState, Topology

_EPS = 1e-9
"""Relative tolerance for 'is this link full' and 'is this flow satisfied'.

Scaled by the quantity being compared (with a floor of 1.0) so that it behaves sensibly
for both a 0.5 Mbps trickle and a 100 Gbps trunk.
"""


def _is_exhausted(remaining: float, scale: float) -> bool:
    """True if `remaining` is zero to within tolerance, relative to `scale`."""
    return remaining <= _EPS * max(1.0, scale)


@dataclass(frozen=True, slots=True)
class Allocation:
    """The result of one allocation: what each flow got, and what each link carries."""

    rates: Mapping[FlowId, float]
    """Delivered rate in Mbps for **every** flow passed in, 0.0 if it got nothing."""

    link_load: Mapping[LinkId, float]
    """Offered-and-accepted load in Mbps, for links carrying traffic only.

    Sparse on purpose: at 500 nodes and 20,000 ticks, materialising a zero for every idle
    link every tick is pure waste. Use `load_on` to read it without a `.get` dance.
    """

    blackholed: frozenset[FlowId]
    """Flows with no live route. Distinct from flows starved to 0 by strict priority."""

    def load_on(self, link_id: LinkId) -> float:
        return self.link_load.get(link_id, 0.0)


def allocate(topology: Topology, flows: Iterable[Flow], routing: RoutingState) -> Allocation:
    """Allocate link capacity to `flows` over their installed `routing`.

    See the module docstring for the objective, the algorithm, and the complexity. Routes
    are assumed to be structurally valid — call `orbit.model.validate_routing` once when a
    routing algorithm produces them, not once per tick.
    """
    ordered = sorted(flows, key=lambda f: f.id)
    rates: dict[FlowId, float] = {}
    for flow in ordered:
        if flow.id in rates:
            raise ValidationError(
                f"allocate: duplicate flow id {flow.id!r}; two flows sharing an id would "
                "collapse into one result and silently under-report offered demand"
            )
        rates[flow.id] = 0.0

    blackholed: set[FlowId] = set()
    by_class: dict[Priority, list[tuple[Flow, tuple[LinkId, ...]]]] = {}
    for flow in ordered:
        route = routing.get(flow.id)
        if route is None or not all(topology.is_usable(link_id) for link_id in route.links):
            blackholed.add(flow.id)
            continue
        by_class.setdefault(flow.priority, []).append((flow, route.links))

    link_load: dict[LinkId, float] = {}
    for priority in sorted(by_class, reverse=True):
        _progressive_fill(topology, by_class[priority], rates, link_load)

    return Allocation(
        rates=MappingProxyType(rates),
        link_load=MappingProxyType(link_load),
        blackholed=frozenset(blackholed),
    )


def _progressive_fill(
    topology: Topology,
    entries: Sequence[tuple[Flow, tuple[LinkId, ...]]],
    rates: dict[FlowId, float],
    link_load: dict[LinkId, float],
) -> None:
    """Max-min fair fill of one priority class, over the capacity left by higher classes.

    Mutates `rates` and `link_load` in place; `link_load` carries the higher classes'
    allocations in, which is exactly how strict priority is enforced — a junior class sees
    only the residual.
    """
    capacity = {
        link_id: topology.link(link_id).effective_capacity_mbps
        for _, links in entries
        for link_id in links
    }
    # Zero-demand flows are excluded rather than fixed at zero inside the loop: including
    # them would make t_demand zero on the first iteration and stall every other flow.
    unfixed = [(flow, links) for flow, links in entries if flow.demand_mbps > 0.0]

    while unfixed:
        crossings: dict[LinkId, int] = {}
        for _, links in unfixed:
            for link_id in links:
                crossings[link_id] = crossings.get(link_id, 0) + 1

        # The water level rises until either a link fills or a flow is satisfied.
        t_link = min(
            max(0.0, capacity[link_id] - link_load.get(link_id, 0.0)) / count
            for link_id, count in crossings.items()
        )
        t_demand = min(flow.demand_mbps - rates[flow.id] for flow, _ in unfixed)
        step = min(t_link, t_demand)

        if step > 0.0:
            for flow, links in unfixed:
                rates[flow.id] += step
                for link_id in links:
                    link_load[link_id] = link_load.get(link_id, 0.0) + step

        remaining: list[tuple[Flow, tuple[LinkId, ...]]] = []
        for flow, links in unfixed:
            satisfied = _is_exhausted(flow.demand_mbps - rates[flow.id], flow.demand_mbps)
            bottlenecked = any(
                _is_exhausted(capacity[link_id] - link_load.get(link_id, 0.0), capacity[link_id])
                for link_id in links
            )
            if not satisfied and not bottlenecked:
                remaining.append((flow, links))

        if len(remaining) == len(unfixed):
            # Unreachable: the termination argument in the module docstring shows that the
            # flow or the link achieving the minimum is always removed. Guarding anyway,
            # because the alternative to a wrong number here is an infinite loop.
            raise AssertionError(
                "allocator made no progress; this is a bug in the progressive-fill loop"
            )
        unfixed = remaining
