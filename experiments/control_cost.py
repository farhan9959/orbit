"""Uncontended control-plane cost against network size (requirement N4, methodology B1).

Why this exists separately from the scale grid
----------------------------------------------
`a10-scale` records `control_seconds`, but it was produced by 18 worker processes on 20
cores. Wall-clock timings under that much contention are inflated by roughly an order of
magnitude: the same 100-node recompute reads 460 ms inside the parallel grid and 65 ms on an
idle machine. The inflation is common to every algorithm, so the grid's *comparison* between
algorithms stands; its absolute numbers cannot support "under 100 ms at 100 nodes".

This driver is therefore deliberately single-threaded and measures one thing: the wall-clock
cost of a single full recompute, the operation N4 bounds.

Assumptions and failure modes:
* Wall-clock, so the numbers belong to the machine in the manifest and nowhere else.
* Each algorithm is warmed once before timing, so the first-call import and allocation costs
  do not land in the measurement.
* The median of `repeats` is reported, not the mean; a scheduler hiccup should not decide the
  answer.
* Mean degree is pinned and flow counts demand-matched exactly as in `a10-scale`, so the
  curve measures size rather than density.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from experiments.runner import RESULTS_ROOT, git_sha, make_algorithm
from experiments.specs.main import SCALE_FLOWS
from orbit.model import GraphView
from orbit.scenarios import ScenarioSpec, TopologyFamily, build_topology, build_traffic

ALGORITHMS = ("spf-static", "spf-reconverge", "ecmp", "cspf", "orbit")
SIZES = (50, 100, 250, 500)
TARGET_DEGREE = 4.0
REPEATS = 5


@dataclass(frozen=True, slots=True)
class CostRecord:
    experiment: str
    family: str
    nodes: int
    links: int
    flows: int
    algorithm: str
    repeats: int
    median_ms: float
    min_ms: float
    max_ms: float
    meets_n4: bool
    """N4 bounds one recompute at 100 nodes to 100 ms. Recorded at every size for the curve."""


def measure() -> list[CostRecord]:
    records: list[CostRecord] = []
    for family in (TopologyFamily.WAXMAN, TopologyFamily.SCALE_FREE):
        for nodes in SIZES:
            spec = ScenarioSpec(
                family=family,
                nodes=nodes,
                flows=SCALE_FLOWS[(family, nodes)],
                offered_load=0.7,
                ticks=150,
                waxman_target_degree=TARGET_DEGREE,
            )
            seed = spec.seed_for(0)
            topology = build_topology(spec, seed)
            flows = build_traffic(spec, topology, seed)
            view = GraphView(topology, 0, changed=True)

            for name in ALGORITHMS:
                algorithm = make_algorithm(name)
                algorithm.recompute(view, flows, {})
                samples: list[float] = []
                for _ in range(REPEATS):
                    started = time.perf_counter()
                    algorithm.recompute(view, flows, {})
                    samples.append((time.perf_counter() - started) * 1000.0)
                median = statistics.median(samples)
                records.append(
                    CostRecord(
                        experiment="a10-control-cost",
                        family=family.value,
                        nodes=nodes,
                        links=len(topology.links),
                        flows=len(flows),
                        algorithm=name,
                        repeats=REPEATS,
                        median_ms=round(median, 3),
                        min_ms=round(min(samples), 3),
                        max_ms=round(max(samples), 3),
                        meets_n4=nodes > 100 or median < 100.0,
                    )
                )
                print(f"  {family.value} n={nodes} {name}: {median:.1f} ms", file=sys.stderr)
    return records


def write(records: Sequence[CostRecord], wall_clock_s: float, root: Path = RESULTS_ROOT) -> Path:
    import pandas as pd

    root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([asdict(record) for record in records])
    frame.to_parquet(root / "a10-control-cost.parquet", index=False)
    frame.to_csv(root / "a10-control-cost.csv", index=False)

    sha, dirty = git_sha()
    (root / "a10-control-cost-manifest.json").write_text(
        json.dumps(
            {
                "git_sha": sha,
                "dirty": dirty,
                "experiment": "a10-control-cost",
                "python": platform.python_version(),
                "platform": platform.platform(),
                "processor": platform.processor(),
                "workers": 1,
                "note": "single-threaded on purpose; a10-scale's control_seconds is contended",
                "repeats": REPEATS,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "wall_clock_s": wall_clock_s,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if dirty:
        print("WARNING: working tree is dirty; this result must not be reported.", file=sys.stderr)
    return root / "a10-control-cost.parquet"


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(prog="control_cost").parse_args(argv)
    started = time.perf_counter()
    records = measure()
    elapsed = time.perf_counter() - started
    path = write(records, elapsed)
    print(f"a10-control-cost: {len(records)} measurements in {elapsed:.1f}s -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
