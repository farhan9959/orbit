"""Network structure: identifiers, element state, nodes, links, and the topology graph.

Implements the element definitions in docs/03-simulation-model.md §2.

Design decisions and their reasons
----------------------------------
**Links are directed.** A bidirectional cable is *two* `Link` objects that normally share
an SRLG tag, so cutting the conduit takes both. Real failures are frequently
unidirectional and real capacity is frequently asymmetric; a single undirected edge
cannot express either.

**Model objects are immutable.** Failure injection (phase A4) will produce a *new*
`Topology` rather than mutating this one. That costs an O(V+E) rebuild per failure event
— negligible at a handful of events per run — and buys three things: invariant I-NOCREATE
becomes checkable by comparing objects, a stale reference cannot silently observe a future
state, and there is no aliasing bug class to debug at tick 8000.

**Iteration order is sorted, everywhere.** Determinism (CLAUDE.md rule 5) is an invariant.
Anything that iterates nodes or links here does so over identifiers sorted once at
construction, so no downstream code depends on dict insertion order.

Assumptions and failure modes
-----------------------------
* Parallel links between the same ordered node pair are permitted; their capacities are
  independent (docs/05-methodology.md A4).
* Self-loops are rejected at construction.
* Connectivity is **not** validated. A disconnected topology is legal input: flows across
  a partition must be BLACKHOLED and the run marked censored, not rejected (invariant
  I-CENSOR).
* `degrade_factor` is applied only in the `DEGRADED` state. In `UP` it is ignored, so a
  link restored from a degradation returns to full capacity without the failure injector
  having to remember and reset the factor.
* Units are not enforced by the type system. Capacity is Mbps and delay is ms, everywhere.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import NewType

from orbit.errors import ValidationError
from orbit.model._validate import require_id, require_number, require_tags

NodeId = NewType("NodeId", str)
LinkId = NewType("LinkId", str)


class NodeKind(StrEnum):
    ROUTER = "ROUTER"
    HOST = "HOST"


class NodeState(StrEnum):
    """Operational state of a node. Nodes have no degraded state; links do."""

    UP = "UP"
    DOWN = "DOWN"


class LinkState(StrEnum):
    """Operational state of a link.

    `DEGRADED` is a distinct state rather than "UP with a smaller capacity number" so that
    a bandwidth degradation is visible to the control plane and to the event log as an
    event, instead of appearing as an unexplained capacity value.
    """

    UP = "UP"
    DOWN = "DOWN"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class Node:
    """A router or host.

    `srlg` holds shared-risk group tags (e.g. `"region:west"`, `"conduit:A12"`). Elements
    sharing a tag fail together, which is how regional failure is expressed (F6).
    """

    id: NodeId
    kind: NodeKind = NodeKind.ROUTER
    state: NodeState = NodeState.UP
    processing_delay_ms: float = 0.0
    srlg: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "id", require_id(self.id, field="id", owner="Node"))
        owner = f"Node({self.id!r})"
        set_(self, "kind", NodeKind(self.kind))
        set_(self, "state", NodeState(self.state))
        set_(
            self,
            "processing_delay_ms",
            require_number(
                self.processing_delay_ms, field="processing_delay_ms", owner=owner, minimum=0.0
            ),
        )
        set_(self, "srlg", require_tags(self.srlg, field="srlg", owner=owner))

    @property
    def is_up(self) -> bool:
        return self.state is NodeState.UP


@dataclass(frozen=True, slots=True)
class Link:
    """A directed link between two distinct nodes.

    `loss_rate` is the *intrinsic* per-link loss of the medium, independent of congestion.
    Congestive loss is derived by the engine from the allocation shortfall
    (docs/03-simulation-model.md §4) and is deliberately not stored on the link.
    """

    id: LinkId
    src: NodeId
    dst: NodeId
    capacity_mbps: float
    prop_delay_ms: float = 0.0
    loss_rate: float = 0.0
    state: LinkState = LinkState.UP
    degrade_factor: float = 1.0
    srlg: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "id", require_id(self.id, field="id", owner="Link"))
        owner = f"Link({self.id!r})"
        set_(self, "src", require_id(self.src, field="src", owner=owner))
        set_(self, "dst", require_id(self.dst, field="dst", owner=owner))
        if self.src == self.dst:
            raise ValidationError(
                f"{owner}: self-loop is not permitted (src == dst == {self.src!r})"
            )
        # Zero capacity is permitted: a scenario may degrade a link to nothing, and the
        # allocator must then return 0 for flows crossing it rather than divide by zero.
        set_(
            self,
            "capacity_mbps",
            require_number(self.capacity_mbps, field="capacity_mbps", owner=owner, minimum=0.0),
        )
        set_(
            self,
            "prop_delay_ms",
            require_number(self.prop_delay_ms, field="prop_delay_ms", owner=owner, minimum=0.0),
        )
        set_(
            self,
            "loss_rate",
            require_number(
                self.loss_rate, field="loss_rate", owner=owner, minimum=0.0, maximum=1.0
            ),
        )
        set_(self, "state", LinkState(self.state))
        set_(
            self,
            "degrade_factor",
            require_number(
                self.degrade_factor, field="degrade_factor", owner=owner, minimum=0.0, maximum=1.0
            ),
        )
        set_(self, "srlg", require_tags(self.srlg, field="srlg", owner=owner))

    @property
    def effective_capacity_mbps(self) -> float:
        """Capacity actually available this tick, after operational state.

        DOWN links carry nothing. DEGRADED links carry `capacity x degrade_factor`. This
        is the only capacity number the allocator is allowed to read; reading
        `capacity_mbps` directly would let traffic flow over failed hardware (I-DOWN).
        """
        if self.state is LinkState.DOWN:
            return 0.0
        if self.state is LinkState.DEGRADED:
            return self.capacity_mbps * self.degrade_factor
        return self.capacity_mbps


class Topology:
    """An immutable directed multigraph of `Node`s and `Link`s.

    Adjacency is stored as sorted out-link lists rather than an adjacency matrix. The
    topologies of interest here are sparse — a 500-node Waxman graph has ~2000 edges, so a
    matrix would be 250,000 mostly-empty cells and every neighbour scan would cost O(V)
    instead of O(deg).
    """

    __slots__ = ("_links", "_nodes", "_out_links")

    def __init__(self, nodes: Iterable[Node], links: Iterable[Link]) -> None:
        by_node: dict[NodeId, Node] = {}
        for node in sorted(nodes, key=lambda n: n.id):
            if not isinstance(node, Node):
                raise ValidationError(f"Topology: expected Node objects, got {node!r}")
            if node.id in by_node:
                raise ValidationError(f"Topology: duplicate node id {node.id!r}")
            by_node[node.id] = node

        by_link: dict[LinkId, Link] = {}
        out_links: dict[NodeId, list[Link]] = {node_id: [] for node_id in by_node}
        for link in sorted(links, key=lambda e: e.id):
            if not isinstance(link, Link):
                raise ValidationError(f"Topology: expected Link objects, got {link!r}")
            if link.id in by_link:
                raise ValidationError(f"Topology: duplicate link id {link.id!r}")
            for endpoint, field in ((link.src, "src"), (link.dst, "dst")):
                if endpoint not in by_node:
                    raise ValidationError(
                        f"Topology: link {link.id!r} has dangling {field} {endpoint!r} "
                        "(no such node)"
                    )
            by_link[link.id] = link
            out_links[link.src].append(link)

        self._nodes: Mapping[NodeId, Node] = MappingProxyType(by_node)
        self._links: Mapping[LinkId, Link] = MappingProxyType(by_link)
        self._out_links: Mapping[NodeId, tuple[Link, ...]] = MappingProxyType(
            {node_id: tuple(incident) for node_id, incident in out_links.items()}
        )

    def __repr__(self) -> str:
        return f"Topology(nodes={len(self._nodes)}, links={len(self._links)})"

    @property
    def nodes(self) -> Mapping[NodeId, Node]:
        """Nodes by id, in ascending id order."""
        return self._nodes

    @property
    def links(self) -> Mapping[LinkId, Link]:
        """Links by id, in ascending id order."""
        return self._links

    def node(self, node_id: NodeId) -> Node:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise ValidationError(f"Topology: unknown node id {node_id!r}") from None

    def link(self, link_id: LinkId) -> Link:
        try:
            return self._links[link_id]
        except KeyError:
            raise ValidationError(f"Topology: unknown link id {link_id!r}") from None

    def links_from(self, node_id: NodeId) -> tuple[Link, ...]:
        """Out-links of `node_id`, in ascending link-id order."""
        try:
            return self._out_links[node_id]
        except KeyError:
            raise ValidationError(f"Topology: unknown node id {node_id!r}") from None

    def is_usable(self, link_id: LinkId) -> bool:
        """True if traffic may cross this link right now.

        A link is usable only if it is not DOWN *and* both endpoints are UP. Checking the
        endpoints here is what makes a node failure disable its incident links without the
        failure injector having to touch every link, and it is the enforcement point for
        invariant I-DOWN.

        A usable link may still have zero effective capacity (a fully degraded link).
        Usability is about reachability; capacity is about how much fits.
        """
        link = self.link(link_id)
        return (
            link.state is not LinkState.DOWN
            and self._nodes[link.src].is_up
            and self._nodes[link.dst].is_up
        )
