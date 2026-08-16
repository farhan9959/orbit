"""Shortest-path primitives shared by every routing algorithm.

Assumptions and failure modes:
* Costs must be non-negative; Dijkstra is invalid otherwise and negative costs are rejected.
* Iteration is over sorted link ids and the heap breaks ties on node id, so path selection
  is deterministic (I-DET).
* `allowed` decides which links the control plane may use. It is supplied by the caller so
  that liveness, residual capacity and pruning policies stay out of this module.
* A target unreachable under `allowed` yields `None`, never an exception.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable, Mapping, Sequence

from orbit.errors import ValidationError
from orbit.model import Link, LinkId, NodeId, Route, Topology

LinkCost = Callable[[Link], float]
LinkFilter = Callable[[Link], bool]

_MAX_EQUAL_COST_PATHS = 16


def latency_cost(link: Link) -> float:
    return link.prop_delay_ms


def hop_cost(link: Link) -> float:
    return 1.0


def usable_links(topology: Topology) -> LinkFilter:
    return lambda link: topology.is_usable(link.id)


def shortest_path_tree(
    topology: Topology,
    source: NodeId,
    *,
    cost: LinkCost = latency_cost,
    allowed: LinkFilter | None = None,
) -> tuple[dict[NodeId, float], dict[NodeId, LinkId]]:
    distance: dict[NodeId, float] = {source: 0.0}
    predecessor: dict[NodeId, LinkId] = {}
    settled: set[NodeId] = set()
    queue: list[tuple[float, NodeId]] = [(0.0, source)]

    while queue:
        current_distance, node = heapq.heappop(queue)
        if node in settled:
            continue
        settled.add(node)
        for link in topology.links_from(node):
            if allowed is not None and not allowed(link):
                continue
            weight = cost(link)
            if weight < 0.0 or math.isnan(weight):
                raise ValidationError(
                    f"shortest_path_tree: link {link.id!r} has invalid cost {weight!r}"
                )
            candidate = current_distance + weight
            known = distance.get(link.dst)
            if known is None or candidate < known:
                distance[link.dst] = candidate
                predecessor[link.dst] = link.id
                heapq.heappush(queue, (candidate, link.dst))
    return distance, predecessor


def route_from_tree(
    topology: Topology,
    predecessor: Mapping[NodeId, LinkId],
    source: NodeId,
    target: NodeId,
) -> Route | None:
    if source == target:
        return None
    links: list[LinkId] = []
    node = target
    seen: set[NodeId] = set()
    while node != source:
        link_id = predecessor.get(node)
        if link_id is None or node in seen:
            return None
        seen.add(node)
        links.append(link_id)
        node = topology.link(link_id).src
    links.reverse()
    return Route.build(topology, links)


def shortest_route(
    topology: Topology,
    source: NodeId,
    target: NodeId,
    *,
    cost: LinkCost = latency_cost,
    allowed: LinkFilter | None = None,
) -> Route | None:
    _, predecessor = shortest_path_tree(topology, source, cost=cost, allowed=allowed)
    return route_from_tree(topology, predecessor, source, target)


def equal_cost_routes(
    topology: Topology,
    source: NodeId,
    target: NodeId,
    *,
    cost: LinkCost = latency_cost,
    allowed: LinkFilter | None = None,
    limit: int = _MAX_EQUAL_COST_PATHS,
    tolerance: float = 1e-9,
) -> tuple[Route, ...]:
    if source == target:
        return ()
    distance, _ = shortest_path_tree(topology, source, cost=cost, allowed=allowed)
    if target not in distance:
        return ()

    incoming: dict[NodeId, list[LinkId]] = {}
    for link_id in topology.links:
        link = topology.link(link_id)
        if allowed is not None and not allowed(link):
            continue
        if link.src not in distance or link.dst not in distance:
            continue
        scale = max(1.0, abs(distance[link.dst]))
        if abs(distance[link.src] + cost(link) - distance[link.dst]) <= tolerance * scale:
            incoming.setdefault(link.dst, []).append(link_id)

    routes: list[Route] = []

    def walk(node: NodeId, suffix: tuple[LinkId, ...], visited: frozenset[NodeId]) -> None:
        if len(routes) >= limit:
            return
        if node == source:
            routes.append(Route.build(topology, list(suffix)))
            return
        for link_id in sorted(incoming.get(node, ())):
            predecessor_node = topology.link(link_id).src
            if predecessor_node in visited:
                continue
            walk(predecessor_node, (link_id, *suffix), visited | {predecessor_node})

    walk(target, (), frozenset({target}))
    return tuple(sorted(routes, key=lambda route: route.links))


def hop_distances(topology: Topology, source: NodeId) -> dict[NodeId, int]:
    distance = {source: 0}
    frontier: Sequence[NodeId] = [source]
    while frontier:
        nxt: list[NodeId] = []
        for node in frontier:
            for link in topology.links_from(node):
                for neighbour in (link.dst,):
                    if neighbour not in distance:
                        distance[neighbour] = distance[node] + 1
                        nxt.append(neighbour)
        frontier = nxt
    return distance
