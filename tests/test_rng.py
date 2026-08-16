"""Seed derivation: the determinism guarantee that every other seeded thing rests on."""

from __future__ import annotations

import os
import pathlib
import random
import subprocess
import sys

import pytest

from orbit.errors import ValidationError
from orbit.rng import derive_seed, rng_for

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _run_in_subprocess(code: str, hash_seed: str) -> str:
    """Evaluate `code` in a fresh interpreter with a given PYTHONHASHSEED."""
    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        check=True,
    )
    return result.stdout.strip()


def test_derive_seed_is_stable_within_a_process() -> None:
    assert derive_seed(42, "topology.waxman") == derive_seed(42, "topology.waxman")


def test_different_names_give_different_streams() -> None:
    """Subsystems must not perturb one another; identical seeds would couple them."""
    assert derive_seed(42, "topology.waxman") != derive_seed(42, "traffic")


def test_different_base_seeds_give_different_streams() -> None:
    assert derive_seed(1, "traffic") != derive_seed(2, "traffic")


def test_rng_for_reproduces_the_same_sequence() -> None:
    first = [rng_for(7, "failures").random() for _ in range(5)]
    second = [rng_for(7, "failures").random() for _ in range(5)]
    assert first == second


def test_rng_for_streams_are_independent_across_names() -> None:
    assert [rng_for(7, "a").random() for _ in range(3)] != [
        rng_for(7, "b").random() for _ in range(3)
    ]


def test_python_hash_randomisation_is_real_and_would_have_broken_this() -> None:
    """Documents the hazard `derive_seed` exists to avoid, executably.

    If this test ever fails, hash randomisation stopped being a threat and the rationale in
    `orbit/rng.py` needs revisiting. Until then it is proof that `random.Random(hash(name))`
    — the obvious one-liner — silently produces a different stream on every run.
    """
    code = "print(hash('topology.waxman'))"
    assert _run_in_subprocess(code, "1") != _run_in_subprocess(code, "2")


def test_derive_seed_is_stable_across_processes_and_hash_seeds() -> None:
    """The property the entire reproducibility claim (N3, I-DET) depends on."""
    code = "from orbit.rng import derive_seed; print(derive_seed(42, 'topology.waxman'))"
    first = _run_in_subprocess(code, "1")
    second = _run_in_subprocess(code, "2")
    assert first == second == str(derive_seed(42, "topology.waxman"))


def test_derive_seed_result_fits_the_documented_width() -> None:
    assert 0 <= derive_seed(0, "x") < 2**64


@pytest.mark.parametrize("bad_seed", [None, "42", 4.2, True])
def test_derive_seed_rejects_a_non_integer_base_seed(bad_seed: object) -> None:
    with pytest.raises(ValidationError, match="base_seed"):
        derive_seed(bad_seed, "traffic")  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_name", ["", None, 7])
def test_derive_seed_rejects_an_unusable_name(bad_name: object) -> None:
    with pytest.raises(ValidationError, match="name"):
        derive_seed(1, bad_name)  # type: ignore[arg-type]


def test_negative_base_seeds_are_accepted() -> None:
    """Seeds derive from hashes of scenario ids and may legitimately be negative."""
    assert isinstance(derive_seed(-5, "traffic"), int)


def test_rng_for_returns_an_independent_generator_not_the_global_one() -> None:
    """A module-level `random.seed()` must not be able to move a subsystem's stream."""
    random.seed(999)
    before = rng_for(3, "traffic").random()
    random.seed(1)
    assert rng_for(3, "traffic").random() == before
