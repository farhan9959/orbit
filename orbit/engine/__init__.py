"""The simulation engine: capacity allocation, the tick loop, and derived metrics."""

from orbit.engine.allocator import Allocation, allocate
from orbit.engine.metrics import (
    ClassMetrics,
    FlowSample,
    MetricsAccumulator,
    RunSummary,
    TickResult,
    path_intrinsic_loss,
    queue_delay_ms,
)
from orbit.engine.simulation import Simulation, SimulationConfig, summarise

__all__ = [
    "Allocation",
    "ClassMetrics",
    "FlowSample",
    "MetricsAccumulator",
    "RunSummary",
    "Simulation",
    "SimulationConfig",
    "TickResult",
    "allocate",
    "path_intrinsic_loss",
    "queue_delay_ms",
    "summarise",
]
