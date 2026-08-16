"""Routing algorithms: the four baselines and the ORBIT controller."""

from orbit.algorithms.base import BaseAlgorithm, RoutingAlgorithm, StaticRouting
from orbit.algorithms.cspf import ConstrainedShortestPath
from orbit.algorithms.ecmp import EqualCostMultiPath
from orbit.algorithms.orbit_controller import PRIORITY_WEIGHTS, OrbitConfig, OrbitController
from orbit.algorithms.paths import (
    equal_cost_routes,
    hop_cost,
    hop_distances,
    latency_cost,
    route_from_tree,
    shortest_path_tree,
    shortest_route,
)
from orbit.algorithms.spf import ReconvergingShortestPath, StaticShortestPath

BASELINES = {
    "spf-static": StaticShortestPath,
    "spf-reconverge": ReconvergingShortestPath,
    "ecmp": EqualCostMultiPath,
    "cspf": ConstrainedShortestPath,
}

__all__ = [
    "BASELINES",
    "PRIORITY_WEIGHTS",
    "BaseAlgorithm",
    "ConstrainedShortestPath",
    "EqualCostMultiPath",
    "OrbitConfig",
    "OrbitController",
    "ReconvergingShortestPath",
    "RoutingAlgorithm",
    "StaticRouting",
    "StaticShortestPath",
    "equal_cost_routes",
    "hop_cost",
    "hop_distances",
    "latency_cost",
    "route_from_tree",
    "shortest_path_tree",
    "shortest_route",
]
