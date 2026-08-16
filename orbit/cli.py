"""Headless CLI: run one simulation or one experiment (requirement F23)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from orbit.detect import ControlMode, DetectorConfig
from orbit.scenarios import ExperimentSpec, FailureScenario, ScenarioSpec, TopologyFamily


def _run(args: argparse.Namespace) -> int:
    from dataclasses import asdict

    from experiments.runner import run_one

    spec = ScenarioSpec(
        family=TopologyFamily(args.family),
        nodes=args.nodes,
        offered_load=args.load,
        flows=args.flows,
        failure=FailureScenario(args.failure),
        ticks=args.ticks,
        control_mode=ControlMode(args.control_mode),
    )
    record = run_one(spec, args.algorithm, args.trial, "cli", DetectorConfig())
    print(json.dumps(asdict(record), indent=2, default=str))
    return 0


def _bench(args: argparse.Namespace) -> int:
    from experiments.runner import execute

    scenarios = tuple(
        ScenarioSpec(
            family=TopologyFamily(args.family),
            nodes=args.nodes,
            offered_load=args.load,
            flows=args.flows,
            failure=FailureScenario(failure),
            ticks=args.ticks,
            control_mode=ControlMode(args.control_mode),
        )
        for failure in args.failures
    )
    spec = ExperimentSpec(name=args.name, scenarios=scenarios, trials=args.trials)
    path = execute(spec, workers=args.workers, progress=True)
    print(f"wrote {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orbit")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--family", default="waxman", choices=[f.value for f in TopologyFamily])
    common.add_argument("--nodes", type=int, default=50)
    common.add_argument("--flows", type=int, default=100)
    common.add_argument("--load", type=float, default=0.7)
    common.add_argument("--ticks", type=int, default=150)
    common.add_argument(
        "--control-mode", default="CENTRALISED", choices=[m.value for m in ControlMode]
    )

    run = sub.add_parser("run", parents=[common], help="run a single simulation")
    run.add_argument("--algorithm", default="orbit")
    run.add_argument(
        "--failure", default="critical_link", choices=[f.value for f in FailureScenario]
    )
    run.add_argument("--trial", type=int, default=0)
    run.set_defaults(func=_run)

    bench = sub.add_parser("bench", parents=[common], help="run an experiment grid")
    bench.add_argument("--name", default="adhoc")
    bench.add_argument("--trials", type=int, default=10)
    bench.add_argument("--workers", type=int, default=1)
    bench.add_argument(
        "--failures",
        nargs="+",
        default=["critical_link"],
        choices=[f.value for f in FailureScenario],
    )
    bench.set_defaults(func=_bench)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
