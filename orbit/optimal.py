"""LP upper bound on achievable weighted served demand, for the optimality gap.

ORBIT is a greedy heuristic for unsplittable multi-commodity flow with priorities, which is
NP-hard. Reporting "better than baseline" without any notion of how far from optimal that is
leaves the obvious question unanswered, so on small topologies we solve a relaxation and
report the gap (docs/03-simulation-model.md §6, docs/05-methodology.md A2).

What this bounds, and what it does not
--------------------------------------
The relaxation is the **splittable** multi-commodity flow problem: each demand may be split
arbitrarily across paths and served fractionally. Its optimum is an upper bound on the
unsplittable optimum, which is in turn an upper bound on what any single-path heuristic can
achieve. So `gap = 1 - achieved / bound` is a *conservative* measure: a non-zero gap may
reflect the relaxation being loose rather than the heuristic being poor.

That is the honest direction to be wrong in. A heuristic that matched this bound exactly
would be evidence the bound is broken, not that the heuristic is optimal.

Formulation, per link e and flow f:

    maximise    sum_f w(priority_f) * served_f
    subject to  sum_f  x[f, e]  <=  capacity_e            for every link e
                flow conservation at every node for every flow
                served_f <= demand_f

Variables are per-flow per-link rates, so the model is O(|F| * |E|) columns. Restricted to
15 nodes by default; beyond that the LP stops being cheap enough to be worth solving on
every run.

Assumptions and failure modes:
* Only links usable *right now* are included, so the bound respects failures.
* An infeasible or unbounded solve returns None rather than a fabricated number.
* Priority weights are the same `PRIORITY_WEIGHTS` the controller's objective uses.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.optimize import linprog

from orbit.algorithms.orbit_controller import PRIORITY_WEIGHTS
from orbit.errors import ValidationError
from orbit.model import Flow, Topology

MAX_LP_NODES = 15


def weighted_served(flows: Sequence[Flow], rates: dict[str, float]) -> float:
    return sum(PRIORITY_WEIGHTS[flow.priority] * rates.get(flow.id, 0.0) for flow in flows)


def lp_upper_bound(topology: Topology, flows: Sequence[Flow]) -> float | None:
    """Maximum achievable weighted served demand under a splittable relaxation."""
    if len(topology.nodes) > MAX_LP_NODES:
        raise ValidationError(
            f"lp_upper_bound: refusing to solve for {len(topology.nodes)} nodes; "
            f"the bound is intended for topologies of at most {MAX_LP_NODES}"
        )
    live_links = [link_id for link_id in topology.links if topology.is_usable(link_id)]
    if not live_links or not flows:
        return 0.0

    nodes = sorted(topology.nodes)
    node_index = {node_id: index for index, node_id in enumerate(nodes)}
    link_index = {link_id: index for index, link_id in enumerate(live_links)}
    n_flows, n_links, n_nodes = len(flows), len(live_links), len(nodes)
    columns = n_flows * n_links

    objective = np.zeros(columns)
    for flow_position, flow in enumerate(flows):
        weight = PRIORITY_WEIGHTS[flow.priority]
        for link_id in live_links:
            if topology.link(link_id).dst == flow.dst:
                objective[flow_position * n_links + link_index[link_id]] = -weight

    capacity_rows = np.zeros((n_links, columns))
    capacity_bounds = np.zeros(n_links)
    for link_id, position in link_index.items():
        capacity_bounds[position] = topology.link(link_id).effective_capacity_mbps
        for flow_position in range(n_flows):
            capacity_rows[position, flow_position * n_links + position] = 1.0

    demand_rows = np.zeros((n_flows, columns))
    demand_bounds = np.zeros(n_flows)
    for flow_position, flow in enumerate(flows):
        demand_bounds[flow_position] = flow.demand_mbps
        for link_id in live_links:
            if topology.link(link_id).dst == flow.dst:
                demand_rows[flow_position, flow_position * n_links + link_index[link_id]] = 1.0

    conservation = np.zeros((n_flows * n_nodes, columns))
    for flow_position, flow in enumerate(flows):
        for node_id in nodes:
            if node_id in (flow.src, flow.dst):
                continue
            row = flow_position * n_nodes + node_index[node_id]
            for link_id in live_links:
                link = topology.link(link_id)
                column = flow_position * n_links + link_index[link_id]
                if link.dst == node_id:
                    conservation[row, column] += 1.0
                if link.src == node_id:
                    conservation[row, column] -= 1.0

    result = linprog(
        c=objective,
        A_ub=np.vstack([capacity_rows, demand_rows]),
        b_ub=np.concatenate([capacity_bounds, demand_bounds]),
        A_eq=conservation,
        b_eq=np.zeros(n_flows * n_nodes),
        bounds=(0.0, None),
        method="highs",
    )
    if not result.success:
        return None
    return float(-result.fun)


def optimality_gap(bound: float | None, achieved: float) -> float | None:
    """`1 - achieved / bound`, or None when the bound is unavailable or zero."""
    if bound is None or bound <= 0.0:
        return None
    return max(0.0, 1.0 - achieved / bound)
