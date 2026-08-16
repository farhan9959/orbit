# Results — phase A8

Status: generated from `experiments/results/a8-*.parquet` by `make reproduce`. Every number
in this file traces to a committed results file. Nothing here is hand-written.

See `research/methodology.md` for what was run and `research/a8-findings.md` for the
interpretation and hypothesis verdicts.

## Files

| Artifact | Contents |
|---|---|
| `experiments/results/a8-headline.csv` | per-run records, 4 families x 7 failures x 5 algorithms x 30 trials |
| `experiments/results/a8-dual-control.csv` | centralised vs distributed baselines |
| `experiments/results/a8-load-sweep.csv` | offered load 0.3 to 1.2 |
| `experiments/results/*-manifest.json` | git SHA, dirty flag, interpreter, platform, wall clock |
| `experiments/figures/*-summary.csv` | median and IQR per scenario and algorithm |
| `experiments/figures/*-compare-*.csv` | paired Wilcoxon, Holm-adjusted p, Cliff's delta, bootstrap CI |
| `experiments/figures/*-censoring.csv` | censored-run counts per cell |
| `experiments/figures/*.png` | figures |

## Reproducing

```
make bench
make reproduce
```

Both are deterministic given the committed specs: same seeds, same topologies, same traffic,
same failures. Wall-clock control-plane timings are the only non-reproducible column and are
valid only on the machine recorded in the manifest.
