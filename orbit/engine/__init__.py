"""The simulation engine: capacity allocation, and (later) the tick loop and metrics."""

from orbit.engine.allocator import Allocation, allocate

__all__ = ["Allocation", "allocate"]
