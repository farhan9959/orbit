"""Traffic demands: priority classes and flows.

Implements the `Flow` and `Priority` definitions in docs/03-simulation-model.md §2.

Why `Priority` is an `IntEnum` with CRITICAL highest
----------------------------------------------------
The allocator serves classes in strict precedence order, and the ORBIT controller sorts
affected flows by `(-priority, -demand, id)` (docs/03-simulation-model.md §6). Both are
one-liners if precedence is the natural integer order and CRITICAL is the largest value:
`sorted(Priority, reverse=True)` *is* the service order. Encoding it the other way round
would put a `reverse=` or a negation at every use site, and the one place it was forgotten
would be a silent, plausible-looking wrong result.

The integer values are precedence ranks, not the objective-function weights `w(priority)`
from docs/03-simulation-model.md §6. Those weights are a separate, configurable mapping
and belong to phase A6, where they first have a consumer.

Assumptions and failure modes
-----------------------------
* `src == dst` is rejected (docs/05-methodology.md A4).
* Zero demand is permitted: it contributes nothing and must not divide by zero in PDR.
* `duration_s` may be `math.inf`, meaning "active for the whole run". It may not be zero;
  a flow that is never active is a spec bug, not a valid input.
* A `Flow` cannot check that its endpoints exist, because it does not know the topology.
  `validate_flows` is the function that closes that gap, and it is what a spec loader must
  call.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum
from typing import NewType

from orbit.errors import ValidationError
from orbit.model._validate import require_id, require_number
from orbit.model.network import NodeId, Topology

FlowId = NewType("FlowId", str)


class Priority(IntEnum):
    """Traffic class. Larger value == served first.

    `sorted(Priority, reverse=True)` yields CRITICAL, HIGH, NORMAL, LOW — the strict
    priority order used by the allocator.
    """

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass(frozen=True, slots=True)
class Flow:
    """A unidirectional traffic demand from `src` to `dst`.

    A flow is a *rate*, not a sequence of packets: this is a flow-level (fluid) simulator
    and `demand_mbps` is the rate the source offers while the flow is active
    (docs/03-simulation-model.md §1).
    """

    id: FlowId
    src: NodeId
    dst: NodeId
    demand_mbps: float
    priority: Priority = Priority.NORMAL
    start_s: float = 0.0
    duration_s: float = math.inf

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "id", require_id(self.id, field="id", owner="Flow"))
        owner = f"Flow({self.id!r})"
        set_(self, "src", require_id(self.src, field="src", owner=owner))
        set_(self, "dst", require_id(self.dst, field="dst", owner=owner))
        if self.src == self.dst:
            raise ValidationError(
                f"{owner}: src and dst must differ (both are {self.src!r}); a flow to "
                "itself never crosses a link and would distort delivery-ratio metrics"
            )
        set_(
            self,
            "demand_mbps",
            require_number(self.demand_mbps, field="demand_mbps", owner=owner, minimum=0.0),
        )
        set_(self, "priority", Priority(self.priority))
        set_(
            self, "start_s", require_number(self.start_s, field="start_s", owner=owner, minimum=0.0)
        )
        duration = require_number(
            self.duration_s, field="duration_s", owner=owner, minimum=0.0, allow_infinite=True
        )
        if duration == 0.0:
            raise ValidationError(f"{owner}: duration_s must be > 0, got {duration!r}")
        set_(self, "duration_s", duration)


def validate_flows(topology: Topology, flows: Iterable[Flow]) -> tuple[Flow, ...]:
    """Return `flows` sorted by id, after checking them against `topology`.

    Rejects duplicate flow ids and endpoints that name no node in the topology. Duplicate
    ids matter more than they look: the allocator keys its results by flow id, so two
    flows sharing an id would silently collapse into one and the run would under-report
    offered demand without any error.

    Sorting the result is deliberate. Callers that iterate the returned tuple inherit a
    deterministic order for free, which is one fewer place determinism can be lost.
    """
    ordered = sorted(flows, key=lambda f: f.id)
    seen: set[FlowId] = set()
    for flow in ordered:
        if not isinstance(flow, Flow):
            raise ValidationError(f"validate_flows: expected Flow objects, got {flow!r}")
        if flow.id in seen:
            raise ValidationError(f"validate_flows: duplicate flow id {flow.id!r}")
        seen.add(flow.id)
        for endpoint, field in ((flow.src, "src"), (flow.dst, "dst")):
            if endpoint not in topology.nodes:
                raise ValidationError(
                    f"Flow({flow.id!r}): {field} {endpoint!r} is not a node in this topology"
                )
    return tuple(ordered)
