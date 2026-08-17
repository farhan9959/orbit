"""Does recovery worsen cascades, or was that an artefact of one threshold setting?

The A8 cascade grid used a single rule (theta = 0.98, dwell = 3 ticks) and found static SPF
suffering less than half the cascade depth of every recovering algorithm while delivering the
most traffic. One parameter setting cannot distinguish a property of the mechanism from a
property of that setting, so this sweeps both cascade parameters over the same worlds.

The seed excludes the cascade parameters, so every cell in the grid faces a bit-identical
topology, traffic matrix and initial failure. The only thing varying is the rule.

Verdict criteria, fixed before looking at the results:

* robust             - static SPF has strictly lower median cascade depth than every
                       recovering algorithm in at least 90% of cells, with the paired test
                       significant after Holm correction in the majority of them.
* parameter-sensitive - the ordering holds in some regions of the grid and reverses or
                       vanishes in others.
* unsupported        - the ordering fails to hold in most cells.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from experiments.analysis import cliffs_delta, effect_label, holm_bonferroni

RESULTS = Path(__file__).resolve().parent / "results" / "a9-cascade-sweep.parquet"
FIGURES = Path(__file__).resolve().parent / "figures"

RECOVERING = ["spf-reconverge", "ecmp", "cspf", "orbit"]
BASELINE = "spf-static"
ROBUST_FRACTION = 0.90


def load() -> pd.DataFrame:
    return pd.read_parquet(RESULTS)


def cell_comparison(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    keys = ["family", "offered_load", "cascade_threshold", "cascade_dwell_ticks"]
    for cell, block in frame.groupby(keys):
        static = block[block["algorithm"] == BASELINE].set_index("trial")
        for algorithm in RECOVERING:
            other = block[block["algorithm"] == algorithm].set_index("trial")
            joined = pd.concat(
                [static["cascade_depth"], other["cascade_depth"]],
                axis=1,
                join="inner",
                keys=["static", "other"],
            ).dropna()
            if len(joined) < 2:
                continue
            differences = (joined["other"] - joined["static"]).to_numpy(dtype=float)
            p_value = (
                1.0
                if np.allclose(differences, 0.0)
                else float(stats.wilcoxon(differences, zero_method="zsplit").pvalue)
            )
            rows.append(
                {
                    "family": cell[0],
                    "offered_load": cell[1],
                    "threshold": cell[2],
                    "dwell": cell[3],
                    "algorithm": algorithm,
                    "static_median": float(joined["static"].median()),
                    "other_median": float(joined["other"].median()),
                    "median_difference": float(np.median(differences)),
                    "p_value": p_value,
                    "cliffs_delta": cliffs_delta(
                        joined["other"].to_numpy(), joined["static"].to_numpy()
                    ),
                    "static_lower": bool(joined["static"].median() < joined["other"].median()),
                    "n_pairs": len(joined),
                }
            )
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["p_holm"] = holm_bonferroni(list(table["p_value"]))
    table["effect"] = table["cliffs_delta"].map(effect_label)
    table["significant"] = table["p_holm"] < 0.05
    return table


def verdict(table: pd.DataFrame) -> tuple[str, dict[str, float]]:
    cells = table.groupby(["family", "offered_load", "threshold", "dwell"])
    all_lower = cells["static_lower"].all()
    any_reversed = cells.apply(
        lambda block: bool(((~block["static_lower"]) & block["significant"]).any()),
        include_groups=False,
    )
    significant_share = cells["significant"].mean()

    fraction_lower = float(all_lower.mean())
    fraction_reversed = float(any_reversed.mean())
    fraction_sig = float((significant_share > 0.5).mean())

    stats_out = {
        "cells": float(len(all_lower)),
        "fraction_static_lower_in_all_comparisons": fraction_lower,
        "fraction_with_a_significant_reversal": fraction_reversed,
        "fraction_majority_significant": fraction_sig,
    }
    if fraction_lower >= ROBUST_FRACTION and fraction_sig >= 0.5 and fraction_reversed <= 0.05:
        return "robust", stats_out
    if fraction_lower <= 0.5:
        return "unsupported", stats_out
    return "parameter-sensitive", stats_out


def heatmap(frame: pd.DataFrame, out: Path) -> None:
    families = sorted(frame["family"].unique())
    loads = sorted(frame["offered_load"].unique())
    figure, axes = plt.subplots(
        len(families), len(loads), figsize=(6 * len(loads), 4.5 * len(families)), squeeze=False
    )
    for row, family in enumerate(families):
        for column, load in enumerate(loads):
            block = frame[(frame["family"] == family) & (frame["offered_load"] == load)]
            pivot_static = block[block["algorithm"] == BASELINE].pivot_table(
                index="cascade_threshold",
                columns="cascade_dwell_ticks",
                values="cascade_depth",
                aggfunc="median",
            )
            pivot_recovering = block[block["algorithm"].isin(RECOVERING)].pivot_table(
                index="cascade_threshold",
                columns="cascade_dwell_ticks",
                values="cascade_depth",
                aggfunc="median",
            )
            delta = pivot_recovering - pivot_static
            axis = axes[row][column]
            image = axis.imshow(
                delta.to_numpy(),
                cmap="RdBu_r",
                aspect="auto",
                vmin=-abs(delta.to_numpy()).max(),
                vmax=abs(delta.to_numpy()).max(),
            )
            axis.set_xticks(range(len(delta.columns)))
            axis.set_xticklabels(delta.columns)
            axis.set_yticks(range(len(delta.index)))
            axis.set_yticklabels(delta.index)
            axis.set_xlabel("dwell ticks")
            axis.set_ylabel("utilisation threshold")
            axis.set_title(f"{family}, load {load}")
            for i in range(delta.shape[0]):
                for j in range(delta.shape[1]):
                    axis.text(
                        j, i, f"{delta.to_numpy()[i, j]:+.0f}", ha="center", va="center", fontsize=7
                    )
            figure.colorbar(image, ax=axis, label="recovering minus static")
    figure.suptitle(
        "Extra cascade depth caused by recovering, vs static SPF "
        "(positive = recovery makes the cascade worse; n=30 paired trials per cell)"
    )
    figure.tight_layout()
    figure.savefig(out, dpi=150)
    plt.close(figure)


def pdr_curve(frame: pd.DataFrame, out: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    markers = {"spf-static": "o", "spf-reconverge": "s", "ecmp": "^", "cspf": "D", "orbit": "*"}
    for axis, metric, label in (
        (axes[0], "cascade_depth", "median cascade depth"),
        (axes[1], "pdr", "median overall delivery ratio"),
    ):
        for algorithm in [BASELINE, *RECOVERING]:
            block = frame[frame["algorithm"] == algorithm]
            grouped = block.groupby("cascade_threshold")[metric].median()
            axis.plot(grouped.index, grouped.to_numpy(), marker=markers[algorithm], label=algorithm)
        axis.set_xlabel("utilisation threshold")
        axis.set_ylabel(label)
    axes[0].legend(fontsize=8)
    figure.suptitle(
        "Cascade behaviour across the overload threshold (pooled over dwell, load, family)"
    )
    figure.tight_layout()
    figure.savefig(out, dpi=150)
    plt.close(figure)


def main() -> int:
    if not RESULTS.exists():
        print("run the cascade sweep first", file=sys.stderr)
        return 1
    FIGURES.mkdir(parents=True, exist_ok=True)
    frame = load()
    table = cell_comparison(frame)
    table.to_csv(FIGURES / "a9-cascade-sweep-comparison.csv", index=False)

    summary = (
        frame.groupby(
            ["family", "offered_load", "cascade_threshold", "cascade_dwell_ticks", "algorithm"]
        )[["cascade_depth", "pdr", "pdr_critical", "total_links"]]
        .median()
        .reset_index()
    )
    summary.to_csv(FIGURES / "a9-cascade-sweep-summary.csv", index=False)

    heatmap(frame, FIGURES / "a9-cascade-sweep-heatmap.png")
    pdr_curve(frame, FIGURES / "a9-cascade-sweep-threshold.png")

    label, numbers = verdict(table)
    print(f"VERDICT: {label}")
    for key, value in numbers.items():
        print(f"  {key}: {value:.4f}")
    print(f"\nsaturated runs: {int(frame['cascade_saturated'].sum())} of {len(frame)}")
    print("\nmedian cascade depth by algorithm (pooled):")
    print(frame.groupby("algorithm")["cascade_depth"].median().round(1).to_string())
    print("\nmedian overall PDR by algorithm (pooled):")
    print(frame.groupby("algorithm")["pdr"].median().round(4).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
