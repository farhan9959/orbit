"""Exports committed results and a replayable demo run as JSON for the dashboard.

Assumptions and failure modes:
* The dashboard is a viewer over completed runs. It never simulates, so nothing it shows
  can disagree with the committed results.
* Node coordinates are computed once with a seeded spring layout and stored, so the same
  topology looks identical in every algorithm's panel and across reloads (requirement F5).
  Without stored coordinates, side-by-side comparison is illegible.
* Frames are downsampled per tick but the full event list is kept, because events are what
  the log panel needs and there are only hundreds of them.
* NetworkX is used here for layout only. It is a research-tooling dependency; `orbit/`
  still never imports it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from experiments.runner import RESULTS_ROOT, make_algorithm
from orbit.detect import DetectorConfig
from orbit.engine import Simulation, SimulationConfig
from orbit.model import Topology
from orbit.scenarios import (
    FailureScenario,
    ScenarioSpec,
    TopologyFamily,
    build_schedule,
    build_topology,
    build_traffic,
)

WEB_DATA = Path(__file__).resolve().parents[1] / "web" / "public" / "data"

DEMO = ScenarioSpec(
    family=TopologyFamily.WAXMAN,
    nodes=40,
    flows=100,
    offered_load=0.9,
    ticks=120,
    failure=FailureScenario.CRITICAL_LINK,
)
ALGORITHMS = ("spf-static", "spf-reconverge", "ecmp", "cspf", "orbit")


def layout(topology: Topology, seed: int) -> dict[str, tuple[float, float]]:
    graph = nx.Graph()
    graph.add_nodes_from(sorted(topology.nodes))
    for link in topology.links.values():
        graph.add_edge(link.src, link.dst)
    positions = nx.spring_layout(graph, seed=seed % (2**32 - 1), iterations=200)
    return {node: (round(float(x), 4), round(float(y), 4)) for node, (x, y) in positions.items()}


def export_demo() -> dict[str, Any]:
    seed = DEMO.seed_for(0)
    topology = build_topology(DEMO, seed)
    flows = build_traffic(DEMO, topology, seed)
    coordinates = layout(topology, seed)

    node_index = {node_id: index for index, node_id in enumerate(sorted(topology.nodes))}

    payload: dict[str, Any] = {
        "scenario": DEMO.id,
        "tick_ms": SimulationConfig().tick_ms,
        "nodes": [
            {"id": node_id, "x": coordinates[node_id][0], "y": coordinates[node_id][1]}
            for node_id in sorted(topology.nodes)
        ],
        "links": [
            {
                "id": link_id,
                "src": node_index[topology.link(link_id).src],
                "dst": node_index[topology.link(link_id).dst],
                "capacity": topology.link(link_id).capacity_mbps,
            }
            for link_id in sorted(topology.links)
        ],
        "flows": [
            {
                "id": flow.id,
                "src": node_index[flow.src],
                "dst": node_index[flow.dst],
                "demand": round(flow.demand_mbps, 3),
                "priority": flow.priority.name,
            }
            for flow in flows
        ],
        "runs": {},
    }

    for name in ALGORITHMS:
        schedule = build_schedule(DEMO, topology, seed)
        simulation = Simulation(
            topology,
            flows,
            make_algorithm(name),
            SimulationConfig(validate_each_recompute=False),
            schedule=schedule,
            detector=DetectorConfig(seed=seed),
        )
        frames: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        for result in simulation.run(DEMO.ticks):
            truth = result.topology or topology
            by_class: dict[str, list[float]] = {}
            for sample in result.samples:
                bucket = by_class.setdefault(sample.priority.name, [0.0, 0.0])
                bucket[0] += sample.delivered_mbps
                bucket[1] += sample.demand_mbps
            frames.append(
                {
                    "t": result.tick,
                    "util": [
                        (
                            round(
                                result.link_load.get(link_id, 0.0)
                                / truth.link(link_id).capacity_mbps,
                                4,
                            )
                            if truth.link(link_id).capacity_mbps > 0
                            else 0.0
                        )
                        for link_id in sorted(topology.links)
                    ],
                    "linkDown": [
                        0 if truth.is_usable(link_id) else 1 for link_id in sorted(topology.links)
                    ],
                    "nodeDown": [
                        0 if truth.node(node_id).is_up else 1 for node_id in sorted(topology.nodes)
                    ],
                    "delivered": {k: round(v[0], 2) for k, v in sorted(by_class.items())},
                    "demanded": {k: round(v[1], 2) for k, v in sorted(by_class.items())},
                    "blackholed": sum(1 for s in result.samples if s.blackholed),
                }
            )
            for event in result.events:
                events.append({"t": event.tick, "type": event.type.value, "payload": event.payload})

        accumulated = _accumulate(frames)
        payload["runs"][name] = {
            "frames": frames,
            "events": events[:400],
            "eventCount": len(events),
            "controlSeconds": round(simulation.control_seconds, 6),
            "controlCalls": simulation.control_calls,
            "pdr": accumulated,
        }
    return payload


def _accumulate(frames: list[dict[str, Any]]) -> dict[str, float]:
    delivered: dict[str, float] = {}
    demanded: dict[str, float] = {}
    for frame in frames:
        for name, value in frame["delivered"].items():
            delivered[name] = delivered.get(name, 0.0) + value
        for name, value in frame["demanded"].items():
            demanded[name] = demanded.get(name, 0.0) + value
    result = {
        name: round(delivered.get(name, 0.0) / demanded[name], 4)
        for name in demanded
        if demanded[name] > 0
    }
    total_delivered = sum(delivered.values())
    total_demanded = sum(demanded.values())
    if total_demanded > 0:
        result["OVERALL"] = round(total_delivered / total_demanded, 4)
    return result


def export_results() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in ("a8-headline", "a8-dual-control", "a8-load-sweep"):
        path = RESULTS_ROOT / f"{name}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        metrics = [
            "pdr_critical",
            "pdr_high",
            "pdr_normal",
            "pdr_low",
            "pdr",
            "throughput_mbps",
            "control_seconds",
        ]
        grouped = (
            frame.groupby(["scenario", "family", "failure", "offered_load", "algorithm"])[metrics]
            .median()
            .reset_index()
        )
        out[name] = {
            "rows": json.loads(grouped.to_json(orient="records")),
            "trials": int(frame["trial"].nunique()),
            "runs": len(frame),
        }
        manifest = RESULTS_ROOT / f"{name}-manifest.json"
        if manifest.exists():
            out[name]["manifest"] = json.loads(manifest.read_text(encoding="utf-8"))
    return out


def main() -> int:
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    (WEB_DATA / "demo.json").write_text(
        json.dumps(export_demo(), separators=(",", ":")), encoding="utf-8"
    )
    (WEB_DATA / "results.json").write_text(
        json.dumps(export_results(), separators=(",", ":")), encoding="utf-8"
    )
    for path in sorted(WEB_DATA.glob("*.json")):
        print(f"{path.name}: {path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
