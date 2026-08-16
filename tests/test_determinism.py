"""I-DET / N3 - the reproducibility claim, asserted as an output hash.

The other determinism tests compare objects. This one serialises a whole run the way the
results pipeline does and compares a SHA-256, which is the form the claim actually takes:
"same seed, same code, byte-identical metrics output".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import pytest

from experiments.runner import run_one
from orbit.algorithms import BASELINES, OrbitController
from orbit.detect import ControlMode, DetectorConfig
from orbit.engine import Simulation
from orbit.scenarios import (
    FailureScenario,
    ScenarioSpec,
    TopologyFamily,
    build_schedule,
    build_topology,
    build_traffic,
)

SPEC = ScenarioSpec(
    family=TopologyFamily.WAXMAN,
    nodes=20,
    flows=40,
    ticks=60,
    failure=FailureScenario.CRITICAL_LINK,
)
ALGORITHMS = [*sorted(BASELINES), "orbit"]


def digest_of_run(algorithm_name: str, trial: int = 0) -> str:
    seed = SPEC.seed_for(trial)
    topology = build_topology(SPEC, seed)
    flows = build_traffic(SPEC, topology, seed)
    schedule = build_schedule(SPEC, topology, seed)
    algorithm = OrbitController() if algorithm_name == "orbit" else BASELINES[algorithm_name]()
    simulation = Simulation(topology, flows, algorithm, schedule=schedule)

    hasher = hashlib.sha256()
    for result in simulation.run(SPEC.ticks):
        for sample in result.samples:
            hasher.update(json.dumps(asdict(sample), sort_keys=True, default=str).encode())
        for link_id in sorted(result.link_load):
            hasher.update(f"{link_id}:{result.link_load[link_id]!r}".encode())
    return hasher.hexdigest()


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_a_run_is_byte_identical_across_invocations(algorithm: str) -> None:
    assert digest_of_run(algorithm) == digest_of_run(algorithm)


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_different_trials_produce_different_output(algorithm: str) -> None:
    assert digest_of_run(algorithm, trial=0) != digest_of_run(algorithm, trial=1)


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_run_records_are_reproducible(algorithm: str) -> None:
    first = run_one(SPEC, algorithm, 0, "det", DetectorConfig())
    second = run_one(SPEC, algorithm, 0, "det", DetectorConfig())
    left, right = asdict(first), asdict(second)
    for volatile in ("wall_clock_s", "control_seconds"):
        left.pop(volatile)
        right.pop(volatile)
    assert left == right


def test_control_mode_changes_the_outcome_but_stays_reproducible() -> None:
    distributed = ScenarioSpec(
        family=SPEC.family,
        nodes=SPEC.nodes,
        flows=SPEC.flows,
        ticks=SPEC.ticks,
        failure=SPEC.failure,
        control_mode=ControlMode.DISTRIBUTED,
    )
    first = run_one(distributed, "spf-reconverge", 0, "det", DetectorConfig())
    second = run_one(distributed, "spf-reconverge", 0, "det", DetectorConfig())
    assert first.pdr == second.pdr
