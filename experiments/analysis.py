"""Paired statistics and result tables (docs/05-methodology.md B4).

Assumptions and failure modes:
* Comparisons are paired by (scenario, trial), because every algorithm in a cell faced a
  bit-identical world. Unpaired tests would throw away that power and overstate variance.
* Wilcoxon signed-rank, not a t-test: recovery-time and delivery-ratio distributions here
  are skewed and often bimodal, since a run either recovers or is partitioned.
* Cliff's delta accompanies every p-value. With 30+ paired trials a trivial difference
  becomes "significant", and the effect size is what says whether anyone should care.
* Censored runs are excluded from recovery-time aggregates and the exclusion count is
  reported. They are never counted as zero or infinite recovery.
* Medians and IQRs are reported rather than means, for the same skew reason.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy import stats

ALPHA = 0.05
BOOTSTRAP_RESAMPLES = 10_000


@dataclass(frozen=True, slots=True)
class Comparison:
    metric: str
    scenario: str
    baseline: str
    challenger: str
    n_pairs: int
    n_censored: int
    baseline_median: float
    challenger_median: float
    median_difference: float
    ci_low: float
    ci_high: float
    p_value: float
    p_holm: float
    cliffs_delta: float
    effect: str


def cliffs_delta(left: Sequence[float], right: Sequence[float]) -> float:
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    if a.size == 0 or b.size == 0:
        return 0.0
    greater = int((a[:, None] > b[None, :]).sum())
    lesser = int((a[:, None] < b[None, :]).sum())
    return (greater - lesser) / (a.size * b.size)


def effect_label(delta: float) -> str:
    magnitude = abs(delta)
    if magnitude < 0.147:
        return "negligible"
    if magnitude < 0.33:
        return "small"
    if magnitude < 0.474:
        return "medium"
    return "large"


def bootstrap_median_difference(
    differences: Sequence[float], resamples: int = BOOTSTRAP_RESAMPLES, seed: int = 12345
) -> tuple[float, float]:
    values = np.asarray(differences, dtype=float)
    if values.size < 2:
        return (math.nan, math.nan)
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(resamples, values.size), replace=True)
    medians = np.median(draws, axis=1)
    return float(np.percentile(medians, 2.5)), float(np.percentile(medians, 97.5))


def holm_bonferroni(p_values: Sequence[float]) -> list[float]:
    order = sorted(range(len(p_values)), key=lambda index: p_values[index])
    adjusted = [0.0] * len(p_values)
    running = 0.0
    for rank, index in enumerate(order):
        scaled = (len(p_values) - rank) * p_values[index]
        running = max(running, min(1.0, scaled))
        adjusted[index] = running
    return adjusted


def paired_comparison(
    frame: pd.DataFrame, metric: str, baseline: str, challenger: str, scenario: str
) -> Comparison | None:
    subset = frame[frame["scenario"] == scenario]
    left = subset[subset["algorithm"] == baseline].set_index("trial")[metric]
    right = subset[subset["algorithm"] == challenger].set_index("trial")[metric]
    joined = pd.concat([left, right], axis=1, join="inner", keys=["baseline", "challenger"])
    censored = int(joined.isna().any(axis=1).sum())
    joined = joined.dropna()
    if len(joined) < 2:
        return None

    differences = (joined["challenger"] - joined["baseline"]).to_numpy(dtype=float)
    if np.allclose(differences, 0.0):
        p_value = 1.0
    else:
        p_value = float(stats.wilcoxon(differences, zero_method="zsplit").pvalue)
    low, high = bootstrap_median_difference(differences)
    delta = cliffs_delta(joined["challenger"].to_numpy(), joined["baseline"].to_numpy())

    return Comparison(
        metric=metric,
        scenario=scenario,
        baseline=baseline,
        challenger=challenger,
        n_pairs=len(joined),
        n_censored=censored,
        baseline_median=float(joined["baseline"].median()),
        challenger_median=float(joined["challenger"].median()),
        median_difference=float(np.median(differences)),
        ci_low=low,
        ci_high=high,
        p_value=p_value,
        p_holm=p_value,
        cliffs_delta=delta,
        effect=effect_label(delta),
    )


def compare_all(
    frame: pd.DataFrame,
    metric: str,
    challenger: str = "orbit",
    baselines: Sequence[str] | None = None,
) -> pd.DataFrame:
    baselines = baselines or [
        name for name in sorted(frame["algorithm"].unique()) if name != challenger
    ]
    rows: list[Comparison] = []
    for scenario in sorted(frame["scenario"].unique()):
        for baseline in baselines:
            comparison = paired_comparison(frame, metric, baseline, challenger, scenario)
            if comparison is not None:
                rows.append(comparison)
    if not rows:
        return pd.DataFrame()
    adjusted = holm_bonferroni([row.p_value for row in rows])
    return pd.DataFrame(
        [{**asdict(row), "p_holm": p} for row, p in zip(rows, adjusted, strict=True)]
    )


def summary_table(frame: pd.DataFrame, metrics: Sequence[str]) -> pd.DataFrame:
    grouped = frame.groupby(["scenario", "algorithm"], dropna=False)
    rows = []
    for (scenario, algorithm), block in grouped:
        row: dict[str, object] = {"scenario": scenario, "algorithm": algorithm, "n": len(block)}
        for metric in metrics:
            values = block[metric].dropna()
            row[f"{metric}_median"] = float(values.median()) if len(values) else math.nan
            row[f"{metric}_iqr"] = (
                float(values.quantile(0.75) - values.quantile(0.25)) if len(values) else math.nan
            )
            row[f"{metric}_n"] = len(values)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["scenario", "algorithm"]).reset_index(drop=True)


def censoring_report(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = frame.groupby(["scenario", "algorithm"], dropna=False)
    return (
        grouped.agg(
            runs=("trial", "count"),
            censored=("censored", "sum"),
            partitioned_fraction=("censored", "mean"),
        )
        .reset_index()
        .sort_values(["scenario", "algorithm"])
    )
