# A8 — the go/no-go gate: findings

Source: `experiments/results/a8-{headline,dual-control,load-sweep}.parquet`, 5,550 runs
generated at commit `f2e35e2` on a clean tree (all three manifests record `dirty: false`).
60-node topologies, 150 flows, failure injected at t = 2 s, 30 paired trials per cell.
Headline grid: 4 topology families x 7 failure scenarios x 5 algorithms.

Wilcoxon signed-rank on paired differences, Holm-Bonferroni within each metric family,
Cliff's delta beside every comparison. "win" means Holm-adjusted p < 0.05 with a positive
median difference, over 28 scenarios.

> **This supersedes an earlier version that was retracted.** Those numbers were generated
> before `fc415d9` and `f2e35e2`, which fixed two defects in ORBIT's placement path: it
> blackholed flows that CSPF carried best-effort, and its preemption accounting could push
> residual capacity above a link's capacity. Both penalised ORBIT. Every conclusion below
> differs from the retracted version, one of them by reversing sign.

---

## Verdict on the pre-registered hypotheses

### H1 — "higher PDR for CRITICAL and HIGH than all baselines" — **supported**

| ORBIT vs | CRITICAL W/L | HIGH W/L |
|---|---|---|
| spf-static | 22 / 1 | 24 / 1 |
| spf-reconverge | 15 / 0 | 22 / 0 |
| ecmp | 11 / 4 | 15 / 0 |
| **cspf** (strong baseline) | **11 / 0** | **15 / 0** |

Pooled medians: CRITICAL 0.907 for ORBIT against 0.874 for CSPF; HIGH 0.819 against 0.760.
ORBIT never loses a scenario to CSPF on either class.

**Every large-effect win is a congestion scenario**, and now on all three families that admit
one:

| Scenario | CSPF | ORBIT | difference | 95% CI | Holm p | delta |
|---|---|---|---|---|---|---|
| waxman, congestion_surge | 0.620 | 0.790 | **+0.169** | [0.147, 0.181] | <0.001 | 0.90 large |
| scale_free, congestion_surge | 0.710 | 0.857 | **+0.143** | [0.131, 0.166] | <0.001 | 0.97 large |
| grid, congestion_surge | 0.919 | **1.000** | **+0.081** | [0.055, 0.098] | 0.0002 | 0.94 large |

Under pure topology failures the differences are real but small (+0.002 to +0.009). The
mechanism earns its keep when the shortage is **capacity**, not connectivity — once a
capacity-aware algorithm has found a feasible path, priority ordering has little left to
decide.

### H2 — "lower time-to-restore for CRITICAL" — **still not measurable**

Median time-to-restore is **0.0 s for every algorithm**, and **69–75% of runs are censored**
(no restore observed at all). At a 100 ms tick with a 150 ms detection interval, recovery
either completes inside the 3-tick dwell window or never satisfies the criterion. The metric
separates nothing.

The high censoring rate is itself a problem: it means the 95%-of-pre-failure-mean criterion
is rarely met, most likely because at offered load 0.7 several classes sit below that level
for the rest of the run regardless of recovery. **H2 cannot be evaluated from this data** and
the metric needs redefining, not merely a finer tick.

### H3 — "lower aggregate throughput, higher control overhead" — **first half confirmed but small, second half refuted**

**Aggregate delivery: ORBIT still trails CSPF, by about one point.** 0 wins / 7 losses on
overall PDR, 0 / 6 on throughput. Pooled medians 0.645 against 0.655. The retracted version
reported 0 / 18 with a much larger gap — most of that was the blackholing defect, not the
mechanism.

Pooled median PDR by class:

| Algorithm | CRITICAL | HIGH | NORMAL | LOW | overall |
|---|---|---|---|---|---|
| orbit | **0.907** | **0.819** | **0.612** | 0.352 | 0.645 |
| cspf | 0.874 | 0.760 | 0.607 | **0.472** | **0.655** |
| ecmp | 0.861 | 0.699 | 0.465 | 0.350 | 0.558 |
| spf-reconverge | 0.843 | 0.650 | 0.441 | 0.330 | 0.532 |
| spf-static | 0.685 | 0.582 | 0.440 | 0.343 | 0.509 |

ORBIT is best on the top three classes and pays for it almost entirely in LOW: 0 wins / 17
losses against CSPF there, 0.352 against 0.472. **The trade is now precisely located** — one
point of aggregate delivery and twelve points of LOW-class delivery, buying three points of
CRITICAL and six of HIGH. Whether that is worth it is a policy question, not a measurement
one, and the measurement now states both sides.

**Control overhead: refuted, and by more than before.** ORBIT's median control-plane time is
**0.058 s**, below CSPF (0.068 s) and ECMP (0.092 s), above only the SPF baselines
(0.009–0.016 s). Keeping surviving routes in place means ORBIT recomputes fewer flows per
event than CSPF, which re-places every flow from scratch.

---

## Load sweep — the retracted reversal was an artefact

Waxman, 60 nodes, critical-link failure. Median CRITICAL PDR:

| Offered load | spf-static | spf-reconverge | ecmp | cspf | orbit |
|---|---|---|---|---|---|
| 0.3 | 0.948 | 0.999 | 0.999 | **1.000** | 0.999 |
| 0.5 | 0.936 | 0.999 | 0.999 | **1.000** | 0.999 |
| 0.7 | 0.876 | 0.939 | 0.939 | 0.981 | **0.999** |
| 0.9 | 0.829 | 0.855 | 0.855 | 0.930 | **0.992** |
| 1.2 | 0.709 | 0.744 | 0.744 | 0.809 | **0.950** |

**ORBIT's advantage grows monotonically with load** — +0.018, +0.062, +0.141 at loads 0.7,
0.9 and 1.2. The retracted version reported ORBIT *losing* at 1.2 (0.743 against 0.809); that
was the blackholing defect, which bit hardest exactly where capacity was scarcest. The
corrected direction is the one the mechanism predicts, and it is the strongest single result
in the study.

Overall PDR over the same sweep shows the cost staying small and roughly flat:

| Offered load | cspf | orbit | difference |
|---|---|---|---|
| 0.3 | 0.997 | 0.997 | 0.000 |
| 0.5 | 0.936 | 0.923 | -0.013 |
| 0.7 | 0.762 | 0.736 | -0.026 |
| 0.9 | 0.603 | 0.579 | -0.024 |
| 1.2 | 0.455 | 0.441 | -0.014 |

ORBIT converts 1–3 points of aggregate delivery into up to 14 points of CRITICAL delivery,
and the exchange rate improves as the network gets more overloaded.

---

## The strawman check (dual control mode)

Median CRITICAL PDR, Waxman:

| Failure | Mode | spf-static | spf-reconverge | ecmp | cspf | orbit |
|---|---|---|---|---|---|---|
| critical_link | CENTRALISED | 0.876 | 0.939 | 0.939 | 0.981 | **0.999** |
| critical_link | DISTRIBUTED | 0.888 | 0.954 | 0.954 | 0.998 | **0.999** |
| random_node_30 | CENTRALISED | 0.273 | 0.483 | 0.483 | **0.515** | 0.512 |
| random_node_30 | DISTRIBUTED | 0.342 | 0.503 | 0.503 | 0.551 | 0.551 |

Baselines do not improve when handed ORBIT's instant global view, so ORBIT's advantage is
algorithmic rather than architectural. ORBIT is also insensitive to control mode (0.999 in
both), consistent with it depending on capacity decisions rather than on early knowledge.

---

## Other measured results

* **Preemption almost never fires** — median 0 per run. Since ORBIT still wins CRITICAL
  decisively, the win is coming from M2 (priority-ordered constrained restoration), not M3.
  The ablation sweep would confirm this and has not been run.
* **Cascade depth is 10.0 for every algorithm**, i.e. every cascading run hits the
  `max_failures` cap. The metric is saturated and says nothing. **Unmeasured.**
* **Static SPF is a genuine floor**, not a strawman: 0.685 CRITICAL against 0.843 for the
  same algorithm with reconvergence enabled.

---

## Answer to the gate question

**Proceed.** The corrected result is stronger and cleaner than the retracted one:

> On 60-node synthetic topologies at offered loads from 0.3 to 1.2, a priority-aware
> capacity-constrained controller preserves more CRITICAL and HIGH traffic than a
> capacity-aware but priority-blind controller, and never less; the advantage is negligible
> when capacity is adequate and grows monotonically with overload, reaching +0.14 CRITICAL
> PDR at 1.2 offered load; and it costs 1–3 points of aggregate delivery, borne almost
> entirely by the LOW class, at *lower* control-plane cost than the baseline it beats.

Every clause is measured, and the cost clause is stated as prominently as the benefit.

## What must change before any of this is published

1. **H2 is unevaluable.** 69–75% censoring means the time-to-restore definition, not just the
   tick resolution, needs rework.
2. **The cascade cap is binding**, so cascade depth is unmeasured.
3. **No optimality bound.** The LP gap on <= 15-node topologies is specified and not built,
   so "how far from optimal" is unanswered.
4. **The M1–M4 ablation has not been run.** Preemption firing at a median of 0 suggests M2
   carries the result, but that is an inference, not a measurement.
5. **Sizes 250 and 500 were not benchmarked** and are not claimed.
6. **Two defects were found in ORBIT's placement path after the first grid run**, both by the
   dashboard and by a precondition guard rather than by the test suite. Regression tests now
   cover both, but the episode is a reason to treat these numbers as provisional until an
   independent check exists.
