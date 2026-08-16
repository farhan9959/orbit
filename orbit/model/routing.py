"""Routes and routing state: where the control plane has decided each flow should go.

Implements invariant I-PATH from docs/03-simulation-model.md §9.

What a `Route` validates, and what it deliberately does not
-----------------------------------------------------------
`Route.build` validates *structure*: the links exist in the topology, they are contiguous
(each link starts where the previous one ended), and no node repeats — a simple path, so
no forwarding loop can be installed.

It does **not** validate *liveness*. Operational state changes every tick while an
installed route persists across ticks, so baking "all elements are UP" into the route
object would mean a route becomes retroactively invalid, and the natural way to express
that is to raise from a constructor that already returned. Liveness is therefore checked
where it is used: `orbit.engine.allocator` refuses to allocate over an unusable link,
which is the enforcement point for invariant I-DOWN.

`RoutingState` is a plain mapping
---------------------------------
A flow absent from the mapping has no route and is BLACKHOLED. That is the whole
semantics, so a mapping is the whole type.

# ponytail: RoutingState is a bare Mapping. It becomes a real class in A6, when the ORBIT
# controller needs to carry precomputed CRITICAL backup paths and per-flow damping
# counters alongside the primary routes.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from orbit.errors import ValidationError
from orbit.model.network import LinkId, NodeId, Topology
from orbit.model.traffic import Flow, FlowId


@dataclass(frozen=True, slots=True)
class Route:
    """A simple directed path, stored as its link sequence plus the nodes it visits.

    Both are kept because both are hot: the allocator iterates `links` to charge capacity,
    while latency accounting (phase A2 of the roadmap, tick loop) iterates `nodes` for
    per-node processing delay. Deriving one from the other on every tick would mean a
    topology lookup per hop per flow per tick.

    Construct with `Route.build`, which is the only entry point that can check the path
    against a topology.
    """

    links: tuple[LinkId, ...]
    nodes: tuple[NodeId, ...]

    def __post_init__(self) -> None:
        if not self.links:
            raise ValidationError(
                "Route: a route must contain at least one link; flows with src == dst are "
                "rejected at validation, so an empty path is always a bug"
            )
        if len(self.nodes) != len(self.links) + 1:
            raise ValidationError(
                f"Route: {len(self.links)} links imply {len(self.links) + 1} nodes, "
                f"got {len(self.nodes)}"
            )
        if len(set(self.nodes)) != len(self.nodes):
            raise ValidationError(f"Route: path is not simple, node repeats in {self.nodes!r}")

    @property
    def src(self) -> NodeId:
        return self.nodes[0]

    @property
    def dst(self) -> NodeId:
        return self.nodes[-1]

    @classmethod
    def build(cls, topology: Topology, link_ids: Sequence[LinkId]) -> Route:
        """Return the `Route` traversing `link_ids`, or raise if that is not a simple path."""
        if not link_ids:
            raise ValidationError("Route.build: link_ids must not be empty")
        links = [topology.link(link_id) for link_id in link_ids]
        nodes = [links[0].src]
        for previous, current in itertools.pairwise(links):
            if previous.dst != current.src:
                raise ValidationError(
                    f"Route.build: link {current.id!r} starts at {current.src!r} but the "
                    f"previous link {previous.id!r} ends at {previous.dst!r}"
                )
        nodes.extend(link.dst for link in links)
        return cls(links=tuple(link_ids), nodes=tuple(nodes))


@dataclass(frozen=True, slots=True)
class PathSet:
    """Several routes carrying one flow, with the share of demand each takes.

    ECMP splits a demand across equal-cost paths (RFC 2992). The shares are explicit rather
    than assumed equal so that a weighted variant needs no new type.
    """

    routes: tuple[Route, ...]
    shares: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.routes:
            raise ValidationError("PathSet: must contain at least one route")
        if len(self.routes) != len(self.shares):
            raise ValidationError(
                f"PathSet: {len(self.routes)} routes but {len(self.shares)} shares"
            )
        if any(share < 0.0 for share in self.shares):
            raise ValidationError(f"PathSet: shares must be non-negative, got {self.shares!r}")
        total = math.fsum(self.shares)
        if abs(total - 1.0) > 1e-9:
            raise ValidationError(f"PathSet: shares must sum to 1.0, got {total!r}")
        first, last = self.routes[0].src, self.routes[0].dst
        for route in self.routes:
            if route.src != first or route.dst != last:
                raise ValidationError(
                    f"PathSet: every route must run {first!r}->{last!r}, "
                    f"got {route.src!r}->{route.dst!r}"
                )

    @property
    def src(self) -> NodeId:
        return self.routes[0].src

    @property
    def dst(self) -> NodeId:
        return self.routes[0].dst

    @classmethod
    def equal_split(cls, routes: Sequence[Route]) -> PathSet:
        if not routes:
            raise ValidationError("PathSet.equal_split: routes must not be empty")
        share = 1.0 / len(routes)
        shares = [share] * len(routes)
        shares[-1] = 1.0 - share * (len(routes) - 1)
        return cls(tuple(routes), tuple(shares))


Placement = Route | PathSet
RoutingState = Mapping[FlowId, Placement]
"""Installed placement by flow id. A flow with no entry is unrouted, i.e. BLACKHOLED."""


def placement_paths(placement: Placement) -> tuple[tuple[Route, float], ...]:
    if isinstance(placement, Route):
        return ((placement, 1.0),)
    return tuple(zip(placement.routes, placement.shares, strict=True))


def placement_links(placement: Placement) -> tuple[LinkId, ...]:
    if isinstance(placement, Route):
        return placement.links
    return tuple(link for route in placement.routes for link in route.links)


def validate_routing(topology: Topology, flows: Iterable[Flow], routing: RoutingState) -> None:
    """Check that every installed route is structurally valid for its flow, or raise.

    This is a *boundary* check, meant to run when a routing algorithm hands over its
    result — not once per tick. The allocator deliberately trusts the routes it is given
    and spends its per-tick budget on liveness and capacity instead, which are the things
    that actually change between ticks.
    """
    by_id = {flow.id: flow for flow in flows}
    for flow_id in sorted(routing):
        flow = by_id.get(flow_id)
        if flow is None:
            raise ValidationError(f"validate_routing: route installed for unknown flow {flow_id!r}")
        placement = routing[flow_id]
        if not isinstance(placement, (Route, PathSet)):
            raise ValidationError(
                f"validate_routing: expected Route or PathSet for flow {flow_id!r}, "
                f"got {placement!r}"
            )
        for route, _ in placement_paths(placement):
            rebuilt = Route.build(topology, route.links)
            if rebuilt != route:
                raise ValidationError(
                    f"validate_routing: route for flow {flow_id!r} does not match this "
                    f"topology (expected nodes {rebuilt.nodes!r}, got {route.nodes!r})"
                )
            if route.src != flow.src or route.dst != flow.dst:
                raise ValidationError(
                    f"validate_routing: route for flow {flow_id!r} runs "
                    f"{route.src!r}->{route.dst!r} but the flow demands "
                    f"{flow.src!r}->{flow.dst!r}"
                )
