"""The simulation engine: allocation, the tick loop, failures, and derived metrics."""

from orbit.engine.allocator import Allocation, allocate
from orbit.engine.failures import (
    CascadeRule,
    FailureEvent,
    FailureKind,
    FailureSchedule,
    highest_betweenness_links,
    highest_betweenness_nodes,
    link_betweenness,
    node_betweenness,
    random_links,
    random_nodes,
)
from orbit.engine.metrics import (
    ClassMetrics,
    FlowSample,
    MetricsAccumulator,
    RunSummary,
    TickResult,
    path_intrinsic_loss,
    peak_restore_fraction,
    queue_delay_ms,
    time_to_converge,
    time_to_restore,
)
from orbit.engine.simulation import Simulation, SimulationConfig, summarise

__all__ = [
    "Allocation",
    "CascadeRule",
    "ClassMetrics",
    "FailureEvent",
    "FailureKind",
    "FailureSchedule",
    "FlowSample",
    "MetricsAccumulator",
    "RunSummary",
    "Simulation",
    "SimulationConfig",
    "TickResult",
    "allocate",
    "highest_betweenness_links",
    "highest_betweenness_nodes",
    "link_betweenness",
    "node_betweenness",
    "path_intrinsic_loss",
    "peak_restore_fraction",
    "queue_delay_ms",
    "random_links",
    "random_nodes",
    "summarise",
    "time_to_converge",
    "time_to_restore",
]
