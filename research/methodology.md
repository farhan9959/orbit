# Methodology (as executed)

This records what phase A8 actually ran. The design rules it follows are specified in
`05-methodology.md`; this file states how they were realised in code, so that a reader can
check the implementation against the intent.

## What was run

| Experiment | Scenarios | Algorithms | Trials | Runs |
|---|---|---|---|---|
| `a8-headline` | 4 topology families x 7 failure scenarios | 5 | 30 | 4,200 |
| `a8-dual-control` | Waxman x 2 failures x 2 control modes | 5 | 30 | 600 |
| `a8-load-sweep` | Waxman x 5 offered loads, critical-link failure | 5 | 30 | 750 |
| `a8-ablation` | 2 families x 2 failures, each ORBIT mechanism disabled | 7 | 30 | 840 |
| `a8-cascade` | 4 families, cascading failure | 5 | 30 | 600 |
| `a9-cascade-sweep` | 7 thresholds x 6 dwells x 2 loads x 2 families | 5 | 30 | 25,200 |

Size is fixed at 60 nodes and 150 flows, 150 ticks (15 s of simulated time) with a failure
injected at t = 2 s. **Only these sizes are claimed.** The requirements list 10-500 nodes;
250 and 500 were not benchmarked and no number is reported for them.

## Fair-comparison rules, and where each is enforced

| Rule | Enforcement |
|---|---|
| Identical world per cell | `ScenarioSpec.seed_for(trial)` derives one seed from `(trial, scenario id)`; topology, traffic and failure schedule are all built from it, before the algorithm is chosen. `tests/test_experiments.py::test_paired_seeds_give_every_algorithm_an_identical_world` |
| Identical detection | Every run constructs the same `DetectorConfig`; only `mode` varies, and it varies per *scenario*, not per algorithm. `orbit/detect/detector.py` |
| Both control modes | `a8-dual-control` runs every baseline in CENTRALISED and DISTRIBUTED |
| Tuned baselines | CSPF's cost blend and ORBIT's parameters have the same shape (`latency_weight`, `utilisation_weight`) and the same defaults |
| Same measurement window | All algorithms in a cell run the same tick count |
| No post-hoc scenarios | The scenario list is committed in `experiments/specs/main.py` and was fixed before results existed |

## Offered load

`offered_load` is the fraction of the network's carrying capacity that traffic requests. A
flow of rate `r` crossing `h` hops consumes `r*h` of link capacity, so feasible total demand
is `total_capacity / mean_hops`, and demand is sized against that.

This matters: the first calibration used an arbitrary constant and produced PDR 1.000 at a
nominal load of 0.7, which would have made every load-dependent claim meaningless. The
recalibration is in `orbit/scenarios.py::build_traffic`.

## Cascade parameter sweep

`ScenarioSpec.seed_key` excludes the cascade-rule parameters while `ScenarioSpec.id` includes
them. The seed therefore identifies the *world* - topology, traffic, injected failure - and the
id identifies the *cell*. All 168 cells of the sweep share four seed keys, so a difference
across the grid is attributable to the rule and to nothing else. Asserted by
`test_cascade_parameters_do_not_change_the_world_being_measured`.

Verdict criteria were written into `experiments/cascade_analysis.py` before the results were
inspected: *robust* requires the ordering to hold in at least 90% of cells with the paired test
significant in the majority and no significant reversals; *unsupported* if it fails in half or
more. This is the pre-registration discipline of B3 rule 6 applied to an analysis rather than
to a scenario list.

## Statistics

Paired by `(scenario, trial)`. Wilcoxon signed-rank on the paired differences;
Holm-Bonferroni across each comparison family; Cliff's delta with negligible/small/medium/
large thresholds at 0.147/0.33/0.474 reported next to every p-value; bootstrap 95% CI on
the median difference over 10,000 resamples. Medians and IQRs, not means.

## Censoring

A run where a class never regains 95% of its pre-failure delivered rate for 3 consecutive
ticks has **no** time-to-restore. It is recorded as null and flagged `censored`, excluded
from recovery aggregates with the exclusion count reported, and never recorded as instant or
infinite recovery. `experiments/analysis.py::paired_comparison` counts and reports the
excluded pairs.

## Threats to validity

* **Flow-level, not packet-level.** Sub-tick dynamics, TCP congestion control, microbursts
  and per-packet reordering during reroute are invisible. Delivery ratio here is rate-based.
* **Queueing delay is an approximation**, not a queueing-theory result. It is applied
  identically to every algorithm, so it cannot bias a comparison; it can shift absolute
  latency numbers.
* **Distributed convergence is modelled from a single vantage point**, not per-router.
* **Synthetic topologies only.** No Internet Topology Zoo instance was used.
* **Greedy heuristic, no optimality bound yet.** The LP gap analysis on <= 15-node
  topologies is specified but not implemented, so "how far from optimal" is unanswered.
* **Timings come from one machine** and are recorded in each manifest.
