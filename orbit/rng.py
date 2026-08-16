"""Seed derivation: one independent, reproducible random stream per subsystem.

Implements the determinism rules in docs/03-simulation-model.md §3.

The rule is that every stochastic subsystem owns its own `random.Random`, seeded from the
run's base seed plus a name, and that no code anywhere calls the module-level `random.*`
functions. Two reasons:

* **Independence.** Topology generation, traffic generation and the failure schedule must
  not perturb one another. With a single shared stream, adding one extra draw to the
  topology generator silently changes the traffic matrix and the failure times of every
  subsequent run — so a refactor that should be invisible instead invalidates a benchmark.
  Named streams mean a change to one subsystem cannot move another.
* **Pairing.** docs/05-methodology.md B2 requires every algorithm in a benchmark cell to
  face a bit-identical world. That is only true if `seed(scenario, trial)` reproduces the
  same topology, traffic and failures regardless of which algorithm is running, and
  regardless of how many random draws that algorithm happens to make.

**Why not `hash()`.** Python salts the hashes of `str` and `bytes` with a per-process
random value unless `PYTHONHASHSEED` is set, so `random.Random(hash(name))` produces a
different stream on every invocation. It is a plausible-looking one-liner that quietly
destroys reproducibility, and nothing about the code's appearance reveals it. BLAKE2b is
used instead: it is in the standard library, it is stable across processes, platforms and
Python versions, and `test_rng.py` asserts that stability by re-running under a different
`PYTHONHASHSEED` in a subprocess.
"""

from __future__ import annotations

import hashlib
import random

from orbit.errors import ValidationError

_DIGEST_BYTES = 8


def derive_seed(base_seed: int, name: str) -> int:
    """Return a stable 64-bit seed for the subsystem `name` under `base_seed`.

    The result depends only on the arguments — never on process state, wall-clock time, or
    the hash randomisation seed.
    """
    if isinstance(base_seed, bool) or not isinstance(base_seed, int):
        raise ValidationError(f"derive_seed: base_seed must be an int, got {base_seed!r}")
    if not isinstance(name, str) or not name:
        raise ValidationError(f"derive_seed: name must be a non-empty string, got {name!r}")
    payload = f"{base_seed}:{name}".encode()
    digest = hashlib.blake2b(payload, digest_size=_DIGEST_BYTES).digest()
    return int.from_bytes(digest, "big")


def rng_for(base_seed: int, name: str) -> random.Random:
    """Return the `random.Random` owned by subsystem `name` under `base_seed`."""
    return random.Random(derive_seed(base_seed, name))
