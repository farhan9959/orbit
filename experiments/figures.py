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

    print(f"figures and tables written to {FIGURES_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(reproduce())
