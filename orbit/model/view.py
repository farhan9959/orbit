"""Control-plane view of the network: what the algorithms are allowed to see."""

from __future__ import annotations

from dataclasses import dataclass

from orbit.model.network import Topology


@dataclass(frozen=True, slots=True)
class GraphView:
    topology: Topology
    observed_at_tick: int
    changed: bool = False
