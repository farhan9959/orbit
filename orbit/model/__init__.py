"""ORBIT's core model types: the network, the traffic offered to it, and the routes.

Everything in this package is immutable and validated at construction, so an object that
exists is an object that satisfies its constraints. Nothing here performs I/O.
"""

from orbit.model.network import (
    Link,
    LinkId,
    LinkState,
    Node,
    NodeId,
    NodeKind,
    NodeState,
    Topology,
)
from orbit.model.routing import Route, RoutingState, validate_routing
from orbit.model.traffic import Flow, FlowId, Priority, validate_flows

__all__ = [
    "Flow",
    "FlowId",
    "Link",
    "LinkId",
    "LinkState",
    "Node",
    "NodeId",
    "NodeKind",
    "NodeState",
    "Priority",
    "Route",
    "RoutingState",
    "Topology",
    "validate_flows",
    "validate_routing",
]
