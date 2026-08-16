"""Executes an experiment grid and writes results plus a reproducibility manifest.

Assumptions and failure modes:
* Every algorithm in a cell receives the identical topology, traffic, failure schedule and
  seed, which is what makes the design paired and the statistics Wilcoxon signed-rank
  rather than Mann-Whitney (docs/05-methodology.md B2).
* Runs are independent, so parallelism is across runs, never inside the engine.
* A run whose recovery is never observed is recorded with a null time-to-restore and a
  censored flag. It is never recorded as instant or infinite recovery.
* Wall-clock control-plane timings are only meaningful on one documented machine; the
  manifest records the host so a mismatch is visible.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from orbit.algorithms import (
    ConstrainedShortestPath,
    EqualCostMultiPath,
    OrbitConfig,
    OrbitController,
    ReconvergingShortestPath,
    RoutingAlgorithm,
    StaticShortestPath,
)
from orbit.detect import DetectorConfig
from orbit.engine import RunSummary, Simulation, SimulationConfig
from orbit.errors import ValidationError
from orbit.model import Priority
from orbit.scenarios import (
    ExperimentSpec,
    ScenarioSpec,
    build_schedule,
    build_topology,
    build_traffic,
)

RESULTS_ROOT = Path(__file__).resolve().parent / "results"


def make_algorithm(name: str, orbit_config: OrbitConfig | None = None) -> RoutingAlgorithm:
    if name == "spf-static":
        return StaticShortestPath()
    if name == "spf-reconverge":
        return ReconvergingShortestPath()
    if name == "ecmp":
        return EqualCostMultiPath()
    if name == "cspf":
        return ConstrainedShortestPath()
    if name == "orbit":
        return OrbitController(orbit_config)
    raise ValidationError(f"make_algorithm: unknown algorithm {name!r}")


@dataclass(frozen=True, slots=True)
class Job:
    scenario: ScenarioSpec
    algorithm: str
    trial: int
    experiment: str
    detector: DetectorConfig


@dataclass(frozen=True, slots=True)
class RunRecord:
    experiment: str
    scenario: str
    family: str
    nodes: int
    offered_load: float
    failure: str
    control_mode: str
    algorithm: str
    trial: int
    seed: int
    pdr: float | None
    pdr_critical: float | None
    pdr_high: float | None
    pdr_normal: float | None
    pdr_low: float | None
    throughput_mbps: float
    mean_latency_ms: float | None
    p95_latency_ms: float | None
    time_to_restore_critical_s: float | None
    time_to_restore_overall_s: float | None
    censored: bool
    reroutes: int
    preemptions: int
    cascade_depth: int
    control_seconds: float
    control_calls: int
    blackholed_flow_ticks: int
    wall_clock_s: float


def _pdr(summary: RunSummary, priority: Priority) -> float | None:
    metrics = summary.by_priority.get(priority)
    return metrics.pdr if metrics is not None else None


def run_one(
    spec: ScenarioSpec,
    algorithm_name: str,
    trial: int,
    experiment: str,
    detector_config: DetectorConfig,
    orbit_config: OrbitConfig | None = None,
) -> RunRecord:
    seed = spec.seed_for(trial)
    topology = build_topology(spec, seed)
    flows = build_traffic(spec, topology, seed)
    schedule = build_schedule(spec, topology, seed)
    detector = DetectorConfig(
        **{**asdict(detector_config), "mode": spec.control_mode, "seed": seed}
    )

    started = time.perf_counter()
    simulation = Simulation(
        topology,
        flows,
        make_algorithm(algorithm_name, orbit_config),
        SimulationConfig(validate_each_recompute=False),
        schedule=schedule,
        detector=detector,
    )
    summary = simulation.measure(spec.ticks)
    elapsed = time.perf_counter() - started

    restore = summary.time_to_restore_s
    overall = [value for value in restore.values() if value is not None]
    return RunRecord(
        experiment=experiment,
        scenario=spec.id,
        family=spec.family.value,
        nodes=spec.nodes,
        offered_load=spec.offered_load,
        failure=spec.failure.value,
        control_mode=spec.control_mode.value,
        algorithm=algorithm_name,
        trial=trial,
        seed=seed,
        pdr=summary.overall.pdr,
        pdr_critical=_pdr(summary, Priority.CRITICAL),
        pdr_high=_pdr(summary, Priority.HIGH),
        pdr_normal=_pdr(summary, Priority.NORMAL),
        pdr_low=_pdr(summary, Priority.LOW),
        throughput_mbps=summary.overall.throughput_mbps,
        mean_latency_ms=summary.overall.mean_latency_ms,
        p95_latency_ms=summary.overall.p95_latency_ms,
        time_to_restore_critical_s=restore.get(Priority.CRITICAL),
        time_to_restore_overall_s=max(overall) if overall else None,
        censored=summary.censored,
        reroutes=summary.reroutes,
        preemptions=summary.preemptions,
        cascade_depth=summary.cascade_depth,
        control_seconds=summary.control_seconds,
        control_calls=summary.control_calls,
        blackholed_flow_ticks=summary.overall.blackholed_flow_ticks,
        wall_clock_s=elapsed,
    )


def run_job(job: Job) -> RunRecord:
    return run_one(job.scenario, job.algorithm, job.trial, job.experiment, job.detector)


def _jobs(spec: ExperimentSpec) -> Iterator[Job]:
    for scenario in spec.scenarios:
        for trial in range(spec.trials):
            for algorithm in spec.algorithms:
                yield Job(scenario, algorithm, trial, spec.name, spec.detector)


def run_experiment(
    spec: ExperimentSpec, workers: int = 1, progress: bool = False
) -> list[RunRecord]:
    jobs = list(_jobs(spec))
    records: list[RunRecord] = []
    if workers <= 1:
        for index, job in enumerate(jobs, 1):
            records.append(run_job(job))
            if progress and index % 25 == 0:
                print(f"  {index}/{len(jobs)}", file=sys.stderr)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run_job, job) for job in jobs]
            for index, future in enumerate(futures, 1):
                records.append(future.result())
                if progress and index % 25 == 0:
                    print(f"  {index}/{len(jobs)}", file=sys.stderr)
    return sorted(records, key=lambda r: (r.scenario, r.trial, r.algorithm))


def git_sha() -> tuple[str, bool]:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        )
        return sha, dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True


def manifest(spec: ExperimentSpec, wall_clock_s: float) -> dict[str, object]:
    sha, dirty = git_sha()
    import numpy
    import scipy

    return {
        "git_sha": sha,
        "dirty": dirty,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "packages": {"numpy": numpy.__version__, "scipy": scipy.__version__},
        "experiment": spec.name,
        "trials": spec.trials,
        "algorithms": list(spec.algorithms),
        "scenarios": [scenario.id for scenario in spec.scenarios],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "wall_clock_s": wall_clock_s,
    }


def write_results(
    spec: ExperimentSpec,
    records: Sequence[RunRecord],
    wall_clock_s: float,
    root: Path = RESULTS_ROOT,
) -> Path:
    import pandas as pd

    root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([asdict(record) for record in records])
    frame.to_parquet(root / f"{spec.name}.parquet", index=False)
    frame.to_csv(root / f"{spec.name}.csv", index=False)
    payload = manifest(spec, wall_clock_s)
    (root / f"{spec.name}-manifest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    if payload["dirty"]:
        print(
            "WARNING: working tree is dirty; this result must not be reported.",
            file=sys.stderr,
        )
    return root / f"{spec.name}.parquet"


def execute(spec: ExperimentSpec, workers: int = 1, progress: bool = False) -> Path:
    started = time.perf_counter()
    records = run_experiment(spec, workers=workers, progress=progress)
    return write_results(spec, records, time.perf_counter() - started)
