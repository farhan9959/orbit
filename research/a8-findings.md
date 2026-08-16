# A8 — the go/no-go gate: findings

Source: `experiments/results/a8-headline.parquet` (4,200 runs), `a8-dual-control.parquet`
(600 runs). 60-node topologies, 150 flows, offered load 0.7, failure injected at t = 2 s,
30 paired trials per cell, 28 scenarios (4 topology families x 7 failure scenarios).
Wilcoxon signed-rank on paired differences, Holm-Bonferroni within each metric family,
Cliff's delta reported with every comparison.

"win" below means Holm-adjusted p < 0.05 with a positive median difference; "loss" the same
with a negative one; "ns" means not significant after correction.

---

## Verdict on the pre-registered hypotheses

### H1 — "ORBIT achieves higher PDR for CRITICAL and HIGH than all baselines" — **partially supported**

ORBIT wins on CRITICAL and HIGH against every baseline, and never loses to the strong
baseline. But against CSPF the win is confined to a minority of scenarios:

| ORBIT vs | CRITICAL win / loss / ns | HIGH win / loss / ns |
|---|---|---|
| spf-static | 22 / 1 / 5 | 24 / 1 / 3 |
| spf-reconverge | 12 / 0 / 16 | 21 / 0 / 7 |
| ecmp | 9 / 4 / 15 | 14 / 0 / 14 |
| **cspf** | **4 / 0 / 24** | **8 / 0 / 20** |

Against CSPF — the capacity-aware, priority-blind control — ORBIT is significantly better on
CRITICAL in 4 of 28 scenarios and significantly worse in none. The claim that survives is
narrow and specific, not "ORBIT wins".

**Where the win actually lives: congestion surge.** Every large-effect CRITICAL win is a
congestion scenario, not a topology failure:

| Scenario | CSPF median | ORBIT median | difference | 95% CI | Holm p | Cliff's delta |
|---|---|---|---|---|---|---|
| waxman, congestion_surge | 0.620 | 0.790 | **+0.169** | [0.147, 0.181] | < 0.001 | 0.90 (large) |
| scale_free, congestion_surge | 0.710 | 0.857 | **+0.143** | [0.131, 0.166] | < 0.001 | 0.97 (large) |
| scale_free, none | 0.987 | 1.000 | +0.011 | [0.000, 0.021] | 0.011 | 0.59 (large) |

That is the honest headline: **priority-aware recovery helps when the shortage is capacity,
not when it is connectivity.** Under a topology failure, once a capacity-aware algorithm has
found a feasible path there is little left for priority ordering to do. Under a demand surge
there is no feasible assignment for everyone, and deciding *who* goes short is exactly what
priority awareness is for.

### H2 — "ORBIT achieves lower time-to-restore for CRITICAL flows" — **not supported; not measurable at this resolution**

Median time-to-restore for CRITICAL is **0.0 s for every algorithm including static SPF**.
At a 100 ms tick with a 150 ms detection interval, recovery completes inside the 3-tick
dwell window used by the definition, so the metric cannot separate the algorithms. This is a
measurement-resolution failure, not evidence of equality. Testing H2 requires a finer tick,
a longer detection interval, or a restore criterion with sub-tick resolution.

### H3 — "ORBIT achieves lower or equal aggregate throughput and higher control overhead" — **half confirmed, half refuted**

**Aggregate delivery: confirmed, and the cost is large.** Against CSPF, ORBIT loses overall
PDR in 18 of 28 scenarios and wins in none. Pooled medians: CSPF 0.655, ORBIT 0.603. Throughput
shows the same pattern, 0 wins and 18 losses, with large effect sizes on Waxman and scale-free.

This is the mechanism working as designed. Pooled median PDR by class:

| Algorithm | CRITICAL | HIGH | NORMAL | LOW | overall |
|---|---|---|---|---|---|
| orbit | **0.895** | **0.803** | 0.564 | **0.278** | 0.603 |
| cspf | 0.874 | 0.760 | 0.607 | 0.472 | **0.655** |
| ecmp | 0.861 | 0.699 | 0.465 | 0.350 | 0.558 |
| spf-reconverge | 0.843 | 0.650 | 0.441 | 0.330 | 0.532 |
| spf-static | 0.685 | 0.582 | 0.440 | 0.343 | 0.509 |

ORBIT is best on CRITICAL and HIGH and **worst on LOW** — it loses LOW to CSPF in 17 of 28
scenarios. It buys the top two classes with the bottom one. That trade is the entire point of
strict priority, and it is a finding to report rather than a defect to fix.

**Control overhead: refuted.** ORBIT's median control-plane time is **0.163 s per run**,
*below* CSPF (0.201 s) and ECMP (0.310 s), though above the SPF baselines (0.043-0.056 s).
The prediction that a priority-aware controller must cost more than a capacity-aware one was
wrong: keeping surviving routes in place means ORBIT recomputes fewer flows per event than
CSPF, which re-places every flow from scratch.

---

## The strawman check (dual control mode)

Median CRITICAL PDR, Waxman, both control modes:

| Failure | Mode | spf-static | spf-reconverge | ecmp | cspf | orbit |
|---|---|---|---|---|---|---|
| critical_link | CENTRALISED | 0.876 | 0.939 | 0.939 | 0.981 | 0.999 |
| critical_link | DISTRIBUTED | 0.888 | 0.954 | 0.954 | 0.998 | 0.999 |
| random_node_30 | CENTRALISED | 0.273 | 0.483 | 0.483 | 0.515 | 0.513 |
| random_node_30 | DISTRIBUTED | 0.342 | 0.503 | 0.503 | 0.551 | 0.537 |

ORBIT's advantage does **not** come from having a better view of the network: the baselines
do not improve when given ORBIT's instant global knowledge, and under `random_node_30` CSPF
slightly exceeds ORBIT in both modes. Whatever ORBIT gains is algorithmic. The counter-
intuitive direction — distributed scoring marginally *higher* than centralised — is an
artefact of the failure landing at a fixed time while a slower control plane leaves stale but
still-working routes in place a little longer; it is small and it applies to every algorithm
equally.

---

## Other measured results

* **Cascade depth is 10.0 for every algorithm**, i.e. every cascading run hit the configured
  `max_failures` cap of 10. The cap is binding, so the metric is saturated and says nothing
  about whether capacity-aware placement reduces cascade depth. The cap must be raised (or
  the surge reduced) before that question can be answered. **Currently unmeasured.**
* **Preemption is rare**: ORBIT preempts a mean of 1.78 flows per run. The mechanism fires,
  but it is not doing most of the work — consistent with the win being concentrated in
  congestion scenarios.
* **Static SPF is a genuine floor**, not a strawman: 0.685 CRITICAL against 0.843 for the same
  algorithm with reconvergence enabled. The failure model is doing real damage.

---

## Answer to the gate question

**Proceed.** ORBIT does not beat the strong baseline across the board, and the pre-registered
H1 does not hold in the general form it was written. What survives is narrower and more
interesting: under demand surges, priority-aware recovery preserves substantially more
CRITICAL traffic than a capacity-aware but priority-blind controller (+0.14 to +0.17 PDR,
large effect, p < 0.001), and it pays for that with aggregate delivery and with LOW-class
starvation, both quantified.

The framing that the data supports is *"priority-aware recovery is a capacity-shortage
mechanism, not a connectivity-failure mechanism"* — which is a sharper claim than the one the
project set out to make, and it is falsifiable.

## What must change before any of this is published

1. **H2 is untestable as configured.** Time-to-restore needs sub-tick resolution or a longer
   detection interval.
2. **The cascade cap is binding.** Raise `max_failures` before claiming anything about cascade
   depth.
3. **No optimality bound exists.** The LP gap on <= 15-node topologies is specified in the
   methodology and not implemented, so "how far from optimal" is unanswered.
4. **Ablation has not been run.** The switches exist and are tested; the sweep that would say
   *which* of M1-M4 produces the congestion-surge win has not been executed.
5. **Sizes 250 and 500 were not benchmarked** and must not be claimed.
