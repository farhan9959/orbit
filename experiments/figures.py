"""Regenerates every figure and table from raw results (`make reproduce`).

Assumptions and failure modes:
* Input is the committed Parquet; nothing here re-runs a simulation, so a figure can never
  silently disagree with the results file it claims to plot.
* Status is encoded by marker and by position as well as colour, because red/green alone is
  unreadable for roughly one man in twelve (non-functional requirement N10).
* Every figure states n, the topology family, the load and the failure scenario in its
  caption text, per docs/05-methodology.md B6.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from experiments.analysis import censoring_report, compare_all, summary_table

RESULTS_ROOT = Path(__file__).resolve().parent / "results"
FIGURES_ROOT = Path(__file__).resolve().parent / "figures"

ALGORITHM_ORDER = ["spf-static", "spf-reconverge", "ecmp", "cspf", "orbit"]
MARKERS = {"spf-static": "o", "spf-reconverge": "s", "ecmp": "^", "cspf": "D", "orbit": "*"}
HEADLINE_METRICS = [
    "pdr_critical",
    "pdr",
    "throughput_mbps",
    "time_to_restore_critical_s",
    "control_seconds",
    "p95_latency_ms",
]


def load(name: str) -> pd.DataFrame:
    return pd.read_parquet(RESULTS_ROOT / f"{name}.parquet")


def _ordered(frame: pd.DataFrame) -> list[str]:
    present = set(frame["algorithm"].unique())
    return [name for name in ALGORITHM_ORDER if name in present]


def plot_pdr_by_class(frame: pd.DataFrame, out: Path) -> None:
    classes = ["pdr_critical", "pdr_high", "pdr_normal", "pdr_low"]
    algorithms = _ordered(frame)
    figure, axis = plt.subplots(figsize=(9, 5))
    width = 0.8 / len(algorithms)

    for index, algorithm in enumerate(algorithms):
        block = frame[frame["algorithm"] == algorithm]
        medians = [block[metric].median() for metric in classes]
        positions = [pos + index * width for pos in range(len(classes))]
        axis.bar(positions, medians, width=width, label=algorithm, edgecolor="black")

    axis.set_xticks([pos + 0.4 - width / 2 for pos in range(len(classes))])
    axis.set_xticklabels(["CRITICAL", "HIGH", "NORMAL", "LOW"])
    axis.set_ylabel("median packet delivery ratio")
    axis.set_ylim(0.0, 1.05)
    axis.legend(fontsize=8, ncol=len(algorithms))
    axis.set_title(
        f"Delivery ratio by priority class (n={frame['trial'].nunique()} paired trials, "
        f"pooled over {frame['scenario'].nunique()} scenarios)"
    )
    figure.tight_layout()
    figure.savefig(out, dpi=150)
    plt.close(figure)


def plot_load_sweep(frame: pd.DataFrame, out: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for algorithm in _ordered(frame):
        block = frame[frame["algorithm"] == algorithm]
        grouped = block.groupby("offered_load")
        loads = sorted(grouped.groups)
        for axis, metric, label in (
            (axes[0], "pdr_critical", "CRITICAL delivery ratio"),
            (axes[1], "pdr", "overall delivery ratio"),
        ):
            axis.plot(
                loads,
                [grouped.get_group(load)[metric].median() for load in loads],
                marker=MARKERS.get(algorithm, "o"),
                label=algorithm,
            )
            axis.set_xlabel("offered load")
            axis.set_ylabel(label)
            axis.set_ylim(0.0, 1.05)
    axes[0].legend(fontsize=8)
    figure.suptitle(
        "Load sweep: Waxman, 60 nodes, critical-link failure "
        f"(n={frame['trial'].nunique()} paired trials)"
    )
    figure.tight_layout()
    figure.savefig(out, dpi=150)
    plt.close(figure)


def plot_by_failure(frame: pd.DataFrame, metric: str, out: Path) -> None:
    failures = sorted(frame["failure"].unique())
    figure, axis = plt.subplots(figsize=(11, 5))
    for algorithm in _ordered(frame):
        block = frame[frame["algorithm"] == algorithm]
        medians = [block[block["failure"] == failure][metric].median() for failure in failures]
        axis.plot(
            range(len(failures)),
            medians,
            marker=MARKERS.get(algorithm, "o"),
            linestyle="--",
            label=algorithm,
        )
    axis.set_xticks(range(len(failures)))
    axis.set_xticklabels(failures, rotation=20, ha="right")
    axis.set_ylabel(f"median {metric}")
    axis.legend(fontsize=8)
    axis.set_title(
        f"{metric} by failure scenario (n={frame['trial'].nunique()} paired trials, "
        f"pooled over {frame['family'].nunique()} topology families)"
    )
    figure.tight_layout()
    figure.savefig(out, dpi=150)
    plt.close(figure)


def plot_control_overhead(frame: pd.DataFrame, out: Path) -> None:
    algorithms = _ordered(frame)
    figure, axis = plt.subplots(figsize=(7, 4.5))
    data = [frame[frame["algorithm"] == name]["control_seconds"].dropna() for name in algorithms]
    axis.boxplot(data, tick_labels=algorithms, showfliers=False)
    axis.set_ylabel("control-plane seconds per run")
    axis.set_title("Control-plane computation cost (median and IQR)")
    figure.tight_layout()
    figure.savefig(out, dpi=150)
    plt.close(figure)


def plot_scale(frame: pd.DataFrame, cost: pd.DataFrame | None, out: Path) -> None:
    """Delivery and control cost against size.

    Control cost is taken from `a10-control-cost`, not from this grid's `control_seconds`:
    the grid ran 18 workers on 20 cores and its wall-clock timings are inflated roughly
    tenfold. The inflation is common to every algorithm, so the grid can still be compared
    within itself, but it cannot carry an absolute claim.
    """
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    critical = frame[frame["failure"] == "critical_link"]
    for algorithm in _ordered(critical):
        grouped = critical[critical["algorithm"] == algorithm].groupby("nodes")
        sizes = sorted(grouped.groups)
        axes[0].plot(
            sizes,
            [grouped.get_group(size)["pdr_critical"].median() for size in sizes],
            marker=MARKERS.get(algorithm, "o"),
            label=algorithm,
        )
    axes[0].set_xlabel("nodes")
    axes[0].set_ylabel("median CRITICAL delivery ratio")
    axes[0].set_xscale("log")
    axes[0].set_ylim(0.8, 1.01)
    axes[0].legend(fontsize=8)
    axes[0].set_title("Delivery under a critical-link failure")

    if cost is not None and not cost.empty:
        for algorithm in _ordered(cost):
            grouped = cost[cost["algorithm"] == algorithm].groupby("nodes")
            sizes = sorted(grouped.groups)
            medians = [grouped.get_group(size)["median_ms"].median() for size in sizes]
            if max(medians) <= 0.0:
                continue
            axes[1].plot(sizes, medians, marker=MARKERS.get(algorithm, "o"), label=algorithm)
        axes[1].axhline(100.0, linestyle=":", color="grey")
        axes[1].annotate("N4 budget, 100 ms", (0.02, 0.06), xycoords="axes fraction", fontsize=8)
        axes[1].set_xscale("log")
        axes[1].set_yscale("log")
        axes[1].set_xlabel("nodes")
        axes[1].set_ylabel("median ms per recompute (single-threaded)")
        axes[1].set_title("Control-plane cost")
        axes[1].legend(fontsize=8)

    figure.suptitle(
        "Scale sweep: mean degree pinned at 4, demand-matched flows, offered load 0.7 "
        f"(n={frame['trial'].nunique()} paired trials)"
    )
    figure.tight_layout()
    figure.savefig(out, dpi=150)
    plt.close(figure)


def plot_mechanisms(frame: pd.DataFrame, out: Path) -> None:
    """How often each mechanism fires, against how much it changes.

    The point of the figure is the gap between the two bars: the mechanisms are reached and
    do work, and the work makes no difference to delivery.
    """
    variants = {
        "orbit-no-protection": "M1 protection",
        "orbit-no-preemption": "M3 preemption",
        "orbit-no-damping": "M4 damping",
        "orbit-restoration-only": "M1+M3+M4",
    }
    keys = ["scenario", "trial"]
    metrics = ["pdr", "pdr_critical", "pdr_high", "pdr_low"]
    base = frame[frame["algorithm"] == "orbit"].set_index(keys)[metrics].sort_index()

    labels, changed = [], []
    for variant, label in variants.items():
        other = frame[frame["algorithm"] == variant].set_index(keys)[metrics].sort_index()
        if other.empty:
            continue
        labels.append(label)
        changed.append(100.0 * float((~(base == other).all(axis=1)).mean()))

    orbit = frame[frame["algorithm"] == "orbit"]
    fired = [
        100.0 * float((orbit["backup_activations"] > 0).mean()),
        100.0 * float((orbit["preemptions"] > 0).mean()),
        float("nan"),
        float("nan"),
    ][: len(labels)]

    figure, axis = plt.subplots(figsize=(8, 4.5))
    positions = range(len(labels))
    axis.bar(
        [p - 0.2 for p in positions],
        fired,
        width=0.4,
        label="runs where it fired (%)",
        edgecolor="black",
    )
    axis.bar(
        [p + 0.2 for p in positions],
        changed,
        width=0.4,
        label="runs whose outcome differed (%)",
        edgecolor="black",
        hatch="//",
    )
    axis.set_xticks(list(positions))
    axis.set_xticklabels(labels)
    axis.set_ylabel("% of runs")
    axis.legend(fontsize=8)
    axis.set_title(
        "A11: mechanisms fire but no cell shows a significant benefit "
        f"(0 wins / 0 losses over {frame['scenario'].nunique()} cells)"
    )
    figure.tight_layout()
    figure.savefig(out, dpi=150)
    plt.close(figure)


def plot_optimality(frame: pd.DataFrame, out: Path) -> None:
    figure, axis = plt.subplots(figsize=(8, 4.5))
    for algorithm in _ordered(frame):
        grouped = frame[frame["algorithm"] == algorithm].groupby("offered_load")
        loads = sorted(grouped.groups)
        axis.plot(
            loads,
            [100.0 * grouped.get_group(load)["optimality_gap"].median() for load in loads],
            marker=MARKERS.get(algorithm, "o"),
            label=algorithm,
        )
    axis.set_xlabel("offered load")
    axis.set_ylabel("median optimality gap (%)")
    axis.legend(fontsize=8)
    axis.set_title(
        "Gap to a splittable LP upper bound, 9-15 nodes "
        f"({len(frame)} placements; the bound is conservative, so this is an over-estimate)"
    )
    figure.tight_layout()
    figure.savefig(out, dpi=150)
    plt.close(figure)


def write_tables(frame: pd.DataFrame, prefix: str, root: Path) -> None:
    summary_table(frame, HEADLINE_METRICS).to_csv(root / f"{prefix}-summary.csv", index=False)
    censoring_report(frame).to_csv(root / f"{prefix}-censoring.csv", index=False)
    for metric in ("pdr_critical", "pdr", "time_to_restore_critical_s", "throughput_mbps"):
        table = compare_all(frame, metric)
        if not table.empty:
            table.to_csv(root / f"{prefix}-compare-{metric}.csv", index=False)


def reproduce() -> int:
    FIGURES_ROOT.mkdir(parents=True, exist_ok=True)
    if not (RESULTS_ROOT / "a8-headline.parquet").exists():
        print("no results found; run the A8 experiments first", file=sys.stderr)
        return 1

    headline = load("a8-headline")
    plot_pdr_by_class(headline, FIGURES_ROOT / "pdr-by-class.png")
    plot_by_failure(headline, "pdr_critical", FIGURES_ROOT / "critical-pdr-by-failure.png")
    plot_by_failure(headline, "pdr", FIGURES_ROOT / "overall-pdr-by-failure.png")
    plot_control_overhead(headline, FIGURES_ROOT / "control-overhead.png")
    write_tables(headline, "a8-headline", FIGURES_ROOT)

    for name, plotter in (("a8-load-sweep", plot_load_sweep),):
        path = RESULTS_ROOT / f"{name}.parquet"
        if path.exists():
            frame = load(name)
            plotter(frame, FIGURES_ROOT / f"{name}.png")
            write_tables(frame, name, FIGURES_ROOT)

    dual = RESULTS_ROOT / "a8-dual-control.parquet"
    if dual.exists():
        frame = load("a8-dual-control")
        write_tables(frame, "a8-dual-control", FIGURES_ROOT)

    if (RESULTS_ROOT / "a10-scale.parquet").exists():
        scale = load("a10-scale")
        cost_path = RESULTS_ROOT / "a10-control-cost.parquet"
        plot_scale(
            scale,
            load("a10-control-cost") if cost_path.exists() else None,
            FIGURES_ROOT / "a10-scale.png",
        )
        write_tables(scale, "a10-scale", FIGURES_ROOT)

    if (RESULTS_ROOT / "a11-mechanisms.parquet").exists():
        mechanisms = load("a11-mechanisms")
        plot_mechanisms(mechanisms, FIGURES_ROOT / "a11-mechanisms.png")
        for metric in ("pdr_critical", "pdr"):
            table = compare_all(
                mechanisms,
                metric,
                challenger="orbit",
                baselines=[
                    "orbit-no-protection",
                    "orbit-no-preemption",
                    "orbit-no-damping",
                    "orbit-restoration-only",
                ],
            )
            if not table.empty:
                table.to_csv(FIGURES_ROOT / f"a11-mechanisms-{metric}.csv", index=False)

    if (RESULTS_ROOT / "a10-optimality.parquet").exists():
        optimality = load("a10-optimality")
        plot_optimality(optimality, FIGURES_ROOT / "a10-optimality.png")
        optimality.groupby(["algorithm", "family", "offered_load"])[
            "optimality_gap"
        ].median().round(5).reset_index().to_csv(
            FIGURES_ROOT / "a10-optimality-summary.csv", index=False
        )

    print(f"figures and tables written to {FIGURES_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(reproduce())
