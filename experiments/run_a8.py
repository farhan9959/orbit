"""Phase A8: executes the committed experiment specifications."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence

from experiments.runner import execute
from experiments.specs.main import (
    A8_ABLATION,
    A8_CASCADE,
    A8_DUAL_CONTROL,
    A8_HEADLINE,
    A8_LOAD_SWEEP,
    A9_CASCADE_SWEEP,
    SMOKE,
)

SPECS = {
    "smoke": SMOKE,
    "headline": A8_HEADLINE,
    "dual-control": A8_DUAL_CONTROL,
    "load-sweep": A8_LOAD_SWEEP,
    "ablation": A8_ABLATION,
    "cascade": A8_CASCADE,
    "cascade-sweep": A9_CASCADE_SWEEP,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_a8")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--only", nargs="*", choices=sorted(SPECS), default=None)
    args = parser.parse_args(argv)

    chosen = args.only or ["headline", "dual-control", "load-sweep", "ablation", "cascade"]
    for name in chosen:
        spec = SPECS[name]
        total = len(spec.scenarios) * spec.trials * len(spec.algorithms)
        started = time.perf_counter()
        path = execute(spec, workers=args.workers, progress=True)
        print(
            f"{spec.name}: {total} runs in {time.perf_counter() - started:.1f}s -> {path}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
