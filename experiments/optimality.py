"""Sweeps the LP optimality gap over small topologies (requirement F22).

`orbit/optimal.py` provides the bound and was validated on a single 12-node case. This turns
that into a measurement: for every (family, size, load, failure, algorithm, trial) cell, the
algorithm places the flows on the post-failure topology, the allocator says what each flow
actually got, and the weighted served demand is compared against the LP relaxation's optimum
for the identical graph.

Assumptions and failure modes:
* **One placement decision, not a whole run.** A run's delivery ratio folds in detection
  latency and per-tick dynamics the static LP knows nothing about; comparing the two would
  not be comparing like with like. The question here is "how good is the placement", which
  is the question the bound can answer.
* The failure is applied before the algorithm runs, so the algorithm and the bound face the
  identical graph. Anything else would measure detection rather than placement.
* The bound is the **splittable** relaxation, so the gap is conservative: a non-zero gap may
  be the relaxation being loose rather than the heuristic being poor, and a zero gap would be
  evidence the bound is broken. See `orbit/optimal.py`.
* Sizes are capped at `MAX_LP_NODES`; the LP has |F| x |E| columns. The grid generator
  rounds to a square, so `nodes=9` and `nodes=12` both build a 3x3 (differing in flow count,
  which is still a load variation) and `nodes=15` rounds to 16 and is skipped rather than
  silently solved above the cap. `nodes` in the output is the true count, not the requested
  one, so this is visible in the data.
* A cell whose LP is infeasible or whose bound is zero records a null gap. It is never
  recorded as a zero gap.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from experiments.runner import RESULTS_ROOT, git_sha, make_algorithm
from orbit.engine import allocate
from orbit.model import GraphView
from orbit.optimal import MAX_LP_NODES, lp_upper_bound, optimality_gap, weighted_served
from orbit.scenarios import (
    FailureScenario,
    ScenarioSpec,
    TopologyFamily,
    build_schedule,
    build_topology,
    build_traffic,
)

ALGORITHMS = ("spf-static", "spf-reconverge", "ecmp", "cspf", "orbit")
FAMILIES = (
    TopologyFamily.WAXMAN,
    TopologyFamily.GRID,
    TopologyFamily.RING,
    TopologyFamily.SCALE_FREE,
)
SIZES = (9, 12, 15)
LOADS = (0.5, 0.7, 0.9, 1.2)
FAILURES = (FailureScenario.NONE, FailureScenario.CRITICAL_LINK)
TRIALS = 30
FLOWS_PER_NODE = 2


@dataclass(frozen=True, slots=True)
class GapRecord:
    experiment: str
    scenario: str
    family: str
    nodes: int
    offered_load: float
    failure: str
    algorithm: str
    trial: int
    seed: int
    flows: int
    live_links: int
    bound: float | None
    achieved: float
    optimality_gap: float | None


@dataclass(frozen=True, slots=True)
class Cell:
    family: TopologyFamily
    nodes: int
    load: float
    failure: FailureScenario
    trial: int


def _cells() -> Iterator[Cell]:
    for family in FAMILIES:
        for nodes in SIZES:
            for load in LOADS:
                for failure in FAILURES:
                    for trial in range(TRIALS):
                        yield Cell(family, nodes, load, failure, trial)


def measure(cell: Cell) -> list[GapRecord]:
    spec = ScenarioSpec(
        family=cell.family,
        nodes=cell.nodes,
        flows=cell.nodes * FLOWS_PER_NODE,
        offered_load=cell.load,
        ticks=50,
        failure=cell.failure,
    )
    seed = spec.seed_for(cell.trial)
    topology = build_topology(spec, seed)
    if len(topology.nodes) > MAX_LP_NODES:
        return []
    flows = build_traffic(spec, topology, seed)

    # Apply the schedule at a time past the injection instant, so the algorithm and the LP
    # both see the post-failure graph rather than the pristine one.
    schedule = build_schedule(spec, topology, seed)
    failed, _ = schedule.apply(0, spec.failure_at_s + 1.0)

    bound = lp_upper_bound(failed, flows)
    view = GraphView(failed, 0, changed=True)
    records: list[GapRecord] = []
    for name in ALGORITHMS:
        routing = make_algorithm(name).recompute(view, flows, {})
        achieved = weighted_served(flows, dict(allocate(failed, flows, routing).rates))
        records.append(
            GapRecord(
                experiment="a10-optimality",
                scenario=spec.id,
                family=cell.family.value,
                nodes=len(topology.nodes),
                offered_load=cell.load,
                failure=cell.failure.value,
                algorithm=name,
                trial=cell.trial,
                seed=seed,
                flows=len(flows),
                live_links=sum(1 for link in failed.links if failed.is_usable(link)),
                bound=bound,
                achieved=achieved,
                optimality_gap=optimality_gap(bound, achieved),
            )
        )
    return records


def run(workers: int, progress: bool) -> list[GapRecord]:
    cells = list(_cells())
    records: list[GapRecord] = []
    if workers <= 1:
        for index, cell in enumerate(cells, 1):
            records.extend(measure(cell))
            if progress and index % 50 == 0:
                print(f"  {index}/{len(cells)}", file=sys.stderr)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for index, batch in enumerate(pool.map(measure, cells), 1):
                records.extend(batch)
                if progress and index % 50 == 0:
                    print(f"  {index}/{len(cells)}", file=sys.stderr)
    return sorted(records, key=lambda r: (r.scenario, r.trial, r.algorithm))


def write(records: Sequence[GapRecord], wall_clock_s: float, root: Path = RESULTS_ROOT) -> Path:
    import pandas as pd

    root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([asdict(record) for record in records])
    frame.to_parquet(root / "a10-optimality.parquet", index=False)
    frame.to_csv(root / "a10-optimality.csv", index=False)

    sha, dirty = git_sha()
    payload = {
        "git_sha": sha,
        "dirty": dirty,
        "experiment": "a10-optimality",
        "trials": TRIALS,
        "algorithms": list(ALGORITHMS),
        "families": [family.value for family in FAMILIES],
        "sizes": list(SIZES),
        "loads": list(LOADS),
        "failures": [failure.value for failure in FAILURES],
        "max_lp_nodes": MAX_LP_NODES,
        "relaxation": "splittable multi-commodity flow; the gap is a conservative bound",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "wall_clock_s": wall_clock_s,
    }
    (root / "a10-optimality-manifest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    if dirty:
        print("WARNING: working tree is dirty; this result must not be reported.", file=sys.stderr)
    return root / "a10-optimality.parquet"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="optimality")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)

    started = time.perf_counter()
    records = run(args.workers, progress=True)
    elapsed = time.perf_counter() - started
    path = write(records, elapsed)
    print(f"a10-optimality: {len(records)} placements in {elapsed:.1f}s -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
