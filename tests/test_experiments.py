"""A7 - scenario specs, the experiment runner, and the paired statistics."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from experiments.analysis import (
    censoring_report,
    cliffs_delta,
    compare_all,
    effect_label,
    holm_bonferroni,
    paired_comparison,
    summary_table,
)
from experiments.runner import make_algorithm, run_experiment, run_one, write_results
from orbit.detect import ControlMode, DetectorConfig
from orbit.errors import ValidationError
from orbit.scenarios import (
    ExperimentSpec,
    FailureScenario,
    ScenarioSpec,
    TopologyFamily,
    build_schedule,
    build_topology,
    build_traffic,
)

SMALL = ScenarioSpec(family=TopologyFamily.WAXMAN, nodes=12, flows=20, ticks=25)


def test_paired_seeds_give_every_algorithm_an_identical_world() -> None:
    """The rule the whole comparison rests on (docs/05-methodology.md B2)."""
    seed = SMALL.seed_for(3)
    assert SMALL.seed_for(3) == seed

    first = build_topology(SMALL, seed)
    second = build_topology(SMALL, seed)
    assert list(first.links) == list(second.links)
    assert [f.demand_mbps for f in build_traffic(SMALL, first, seed)] == [
        f.demand_mbps for f in build_traffic(SMALL, second, seed)
    ]


def test_different_trials_give_different_worlds() -> None:
    assert SMALL.seed_for(0) != SMALL.seed_for(1)


def test_scenario_id_distinguishes_control_mode() -> None:
    distributed = ScenarioSpec(control_mode=ControlMode.DISTRIBUTED)
    centralised = ScenarioSpec(control_mode=ControlMode.CENTRALISED)
    assert distributed.id != centralised.id


@pytest.mark.parametrize(
    "kwargs",
    [{"nodes": 1}, {"nodes": 10_000}, {"flows": 0}, {"ticks": 0}, {"offered_load": 0.0}],
)
def test_scenario_spec_enforces_bounds(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        ScenarioSpec(**kwargs)


def test_experiment_spec_enforces_bounds() -> None:
    with pytest.raises(ValidationError, match="trials"):
        ExperimentSpec(name="x", scenarios=(SMALL,), trials=0)
    with pytest.raises(ValidationError, match="scenario"):
        ExperimentSpec(name="x", scenarios=())


@pytest.mark.parametrize("family", list(TopologyFamily))
def test_every_family_builds(family: TopologyFamily) -> None:
    spec = ScenarioSpec(family=family, nodes=16, flows=10, ticks=10)
    topology = build_topology(spec, spec.seed_for(0))
    assert len(topology.nodes) >= 2


@pytest.mark.parametrize("failure", list(FailureScenario))
def test_every_failure_scenario_builds_a_schedule(failure: FailureScenario) -> None:
    spec = ScenarioSpec(family=TopologyFamily.WAXMAN, nodes=12, flows=10, ticks=10, failure=failure)
    seed = spec.seed_for(0)
    topology = build_topology(spec, seed)
    schedule = build_schedule(spec, topology, seed)
    schedule.apply(0, 0.0)
    schedule.apply(30, 3.0)


def test_make_algorithm_rejects_an_unknown_name() -> None:
    with pytest.raises(ValidationError, match="unknown algorithm"):
        make_algorithm("nope")


def test_a_run_is_reproducible_from_its_seed() -> None:
    first = run_one(SMALL, "orbit", 0, "t", DetectorConfig())
    second = run_one(SMALL, "orbit", 0, "t", DetectorConfig())
    assert first.pdr == second.pdr
    assert first.seed == second.seed
    assert first.reroutes == second.reroutes


def test_every_algorithm_completes_a_run() -> None:
    for name in ("spf-static", "spf-reconverge", "ecmp", "cspf", "orbit"):
        record = run_one(SMALL, name, 0, "t", DetectorConfig())
        assert record.algorithm == name
        assert record.pdr is None or 0.0 <= record.pdr <= 1.0


def test_run_experiment_covers_the_whole_grid() -> None:
    spec = ExperimentSpec(name="grid", scenarios=(SMALL,), algorithms=("cspf", "orbit"), trials=3)
    records = run_experiment(spec)
    assert len(records) == 6
    assert {r.algorithm for r in records} == {"cspf", "orbit"}


def test_results_and_manifest_are_written(tmp_path) -> None:
    spec = ExperimentSpec(name="io", scenarios=(SMALL,), algorithms=("cspf",), trials=2)
    records = run_experiment(spec)
    path = write_results(spec, records, 1.0, root=tmp_path)

    assert path.exists()
    assert (tmp_path / "io.csv").exists()
    manifest = (tmp_path / "io-manifest.json").read_text(encoding="utf-8")
    for field in ("git_sha", "dirty", "python", "platform", "wall_clock_s"):
        assert field in manifest


def test_cliffs_delta_spans_the_full_range() -> None:
    assert cliffs_delta([3, 4, 5], [0, 1, 2]) == pytest.approx(1.0)
    assert cliffs_delta([0, 1, 2], [3, 4, 5]) == pytest.approx(-1.0)
    assert cliffs_delta([1, 2, 3], [1, 2, 3]) == pytest.approx(0.0)


def test_effect_labels_follow_the_documented_thresholds() -> None:
    assert effect_label(0.10) == "negligible"
    assert effect_label(0.20) == "small"
    assert effect_label(0.40) == "medium"
    assert effect_label(0.90) == "large"


def test_holm_bonferroni_is_monotone_and_never_shrinks_a_p_value() -> None:
    raw = [0.01, 0.04, 0.03]
    adjusted = holm_bonferroni(raw)
    assert all(a >= r for a, r in zip(adjusted, raw, strict=True))
    assert max(adjusted) <= 1.0


def frame_for(metric_values: dict[str, list[float]], scenario: str = "s") -> pd.DataFrame:
    rows = []
    for algorithm, values in metric_values.items():
        for trial, value in enumerate(values):
            rows.append(
                {
                    "scenario": scenario,
                    "algorithm": algorithm,
                    "trial": trial,
                    "pdr_critical": value,
                    "censored": False,
                }
            )
    return pd.DataFrame(rows)


def test_paired_comparison_detects_a_real_difference() -> None:
    frame = frame_for(
        {"cspf": [0.5 + 0.01 * i for i in range(20)], "orbit": [0.7 + 0.01 * i for i in range(20)]}
    )
    result = paired_comparison(frame, "pdr_critical", "cspf", "orbit", "s")

    assert result is not None
    assert result.n_pairs == 20
    assert result.median_difference == pytest.approx(0.2)
    assert result.p_value < 0.05
    assert result.effect == "large"
    assert result.ci_low <= result.median_difference <= result.ci_high


def test_paired_comparison_reports_no_difference_when_there_is_none() -> None:
    values = [0.5 + 0.01 * i for i in range(15)]
    frame = frame_for({"cspf": values, "orbit": list(values)})
    result = paired_comparison(frame, "pdr_critical", "cspf", "orbit", "s")

    assert result is not None
    assert result.p_value == pytest.approx(1.0)
    assert result.effect == "negligible"


def test_censored_pairs_are_excluded_and_counted() -> None:
    """They must never be recorded as instant or infinite recovery."""
    frame = frame_for({"cspf": [1.0, 2.0, 3.0], "orbit": [1.0, math.nan, 3.0]})
    result = paired_comparison(frame, "pdr_critical", "cspf", "orbit", "s")

    assert result is not None
    assert result.n_pairs == 2
    assert result.n_censored == 1


def test_compare_all_applies_a_family_wide_correction() -> None:
    frame = pd.concat(
        [
            frame_for(
                {
                    "cspf": [0.5] * 10,
                    "ecmp": [0.4] * 10,
                    "orbit": [0.6 + 0.001 * i for i in range(10)],
                },
                scenario="s1",
            ),
            frame_for(
                {
                    "cspf": [0.55] * 10,
                    "ecmp": [0.45] * 10,
                    "orbit": [0.65 + 0.001 * i for i in range(10)],
                },
                scenario="s2",
            ),
        ]
    )
    table = compare_all(frame, "pdr_critical")

    assert not table.empty
    assert (table["p_holm"] >= table["p_value"]).all()


def test_summary_table_reports_median_and_iqr_not_mean() -> None:
    frame = frame_for({"orbit": [1.0, 2.0, 3.0, 100.0]})
    table = summary_table(frame, ["pdr_critical"])

    assert table.loc[0, "pdr_critical_median"] == pytest.approx(2.5)
    assert table.loc[0, "pdr_critical_median"] != np.mean([1.0, 2.0, 3.0, 100.0])


def test_censoring_report_counts_partitioned_runs() -> None:
    frame = pd.DataFrame(
        [
            {"scenario": "s", "algorithm": "orbit", "trial": 0, "censored": True},
            {"scenario": "s", "algorithm": "orbit", "trial": 1, "censored": False},
        ]
    )
    report = censoring_report(frame)
    assert report.loc[0, "censored"] == 1
    assert report.loc[0, "partitioned_fraction"] == pytest.approx(0.5)
