# A8 — the go/no-go gate: findings

Source: `experiments/results/a8-*.parquet`, ~9,000 runs across five grids (headline,
dual-control, load-sweep, ablation, cascade) generated at commit `0d0ebf9` on a clean tree (all three manifests record `dirty: false`).
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

### H2 — "lower time-to-restore for CRITICAL" — **not supported; the traffic never fully returns**

Median time-to-restore is 0.0 s for every algorithm and 69–75% of runs censor. The added
`peak_restore_fraction` metric now explains why, and it is not a metric bug — see the H2
section further down. CRITICAL traffic recovers to roughly 80% of its pre-failure rate and
stops, so the 95% criterion is unreachable and censoring is the correct answer. Time-to-
converge, which *is* measurable, shows no separation either: 0.3 s for every recovering
algorithm.

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

* **Preemption never fires** — median 0 per run. The ablation below confirms M2 carries the
  entire result.
* **Static SPF is a genuine floor**, not a strawman: 0.685 CRITICAL against 0.843 for the
  same algorithm with reconvergence enabled.

---

## Ablation — M2 does all the work (negative result for M1, M3, M4)

`a8-ablation`, 840 runs: Waxman and scale-free, congestion-surge and critical-link, offered
load 0.9, 30 paired trials, each ORBIT mechanism disabled in turn.

| Variant | CRITICAL | HIGH | overall | preemptions | reroutes |
|---|---|---|---|---|---|
| cspf | 0.7515 | 0.5067 | 0.4240 | 0 | 2.5 |
| **orbit (all four)** | **0.8866** | **0.6948** | 0.4154 | 0 | 156 |
| orbit-no-protection (M1 off) | 0.8866 | 0.6948 | 0.4154 | 0 | 156 |
| orbit-no-preemption (M3 off) | 0.8866 | 0.6948 | 0.4154 | 0 | 155 |
| orbit-no-damping (M4 off) | 0.8866 | 0.6948 | 0.4154 | 0 | 156 |
| **orbit-restoration-only (M1, M3, M4 all off)** | **0.8866** | **0.6948** | 0.4154 | 0 | 155 |
| orbit-no-fallback | 0.8373 | 0.6147 | 0.3565 | 0 | 82 |

**Disabling M1, M3 and M4 together changes nothing, to four decimal places.** Restoration-only
ORBIT is indistinguishable from full ORBIT on every metric. The entire measured advantage
over CSPF (+0.135 CRITICAL, +0.188 HIGH at load 0.9) comes from **M2 alone** —
priority-ordered constrained restoration.

This is a negative result for three quarters of the design:

* **M1 protection** never helps because M2 finds an equivalent path anyway, within the same
  tick. Precomputed backups buy nothing when recomputation is not the bottleneck.
* **M3 preemption never fires** — median 0 preemptions per run, across every scenario. The
  restriction to strictly-lower-priority victims plus the best-effort fallback means the
  situation preemption exists for essentially does not arise.
* **M4 damping** changes no outcome, though it is also not costing anything.

The only non-M2 mechanism that matters is the **best-effort fallback**, which is not one of
the four documented mechanisms — it is the fix from `fc415d9`. Removing it costs 0.049
CRITICAL and 0.080 HIGH.

**Consequence for the contribution claim.** `03-simulation-model.md` §6 describes ORBIT as an
integration of four mechanisms. The measurement says it is one mechanism plus three that are
inert under these conditions. The honest claim is now "priority-ordered constrained
restoration outperforms priority-blind constrained restoration", which is narrower and does
not need the word "integration". M1/M3/M4 should either be shown to matter under conditions
not yet tested (tighter capacity, faster failure arrival, no fallback) or dropped.

---

## Cascading failure — the hypothesis is refuted

With the cap raised from 10 to 200, cascade depth is measurable for the first time.
`a8-cascade`, 600 runs, all four families, offered load 0.9:

| Algorithm | median cascade depth | max | CRITICAL PDR | overall PDR |
|---|---|---|---|---|
| spf-static | **31.5** | 63 | **0.188** | **0.201** |
| orbit | 76.0 | 178 | 0.133 | 0.138 |
| ecmp | 77.0 | 187 | 0.126 | 0.121 |
| cspf | 78.5 | 184 | 0.118 | 0.126 |
| spf-reconverge | 88.0 | 187 | 0.116 | 0.103 |

`03-simulation-model.md` §5 called this "the project's strongest single result" if
capacity-aware placement reduced cascade depth. **It does not.** ORBIT's 76 against CSPF's
78.5 is a rounding difference next to the spread.

The striking result is the opposite one: **static SPF suffers less than half the cascade
depth of every recovering algorithm, and delivers the most traffic under cascade.** Because
it never reroutes, it never dumps displaced traffic onto surviving links, so it never trips
the overload threshold that propagates the cascade.

That single grid used one cascade rule (theta = 0.98, dwell = 3), so it could not distinguish
a property of the mechanism from a property of that setting. The sweep below settles it.

---

## Cascade parameter sweep - the finding is robust, not an artefact

`a9-cascade-sweep`, **25,200 runs**, manifest `dirty: false`. Utilisation threshold in
{0.75, 0.80, 0.85, 0.90, 0.95, 0.98, 1.00} x dwell in {1, 3, 5, 10, 20, 40} ticks x offered
load in {0.7, 0.9} x {waxman, scale_free} x 5 algorithms x 30 paired trials.
**168 parameter cells.**

The cascade parameters are deliberately excluded from the seed, so all 168 cells face a
bit-identical topology, traffic matrix and initial failure - only the rule varies. Verified by
`test_cascade_parameters_do_not_change_the_world_being_measured`. No run hit the failure cap
(0 of 25,200 saturated), so the metric is unsaturated everywhere.

**Verdict criteria were fixed before looking at the data** (`experiments/cascade_analysis.py`):
robust required static SPF strictly lower in at least 90% of cells with the paired test
significant in the majority, and no significant reversals.

| Measure | Result |
|---|---|
| Cells where static SPF is strictly lower than **every** recovering algorithm | **168 / 168 (100%)** |
| Cells with a significant reversal | **0** |
| Cells where the majority of comparisons are significant after Holm | **168 / 168** |
| Effect size, all 672 pairwise comparisons | **large** (Cliff's delta) |
| Extra cascade depth from recovering, median across cells | **+77 links** (range +31.5 to +104) |

**Verdict: robust.**

Median cascade depth by threshold (of ~232 links):

| Threshold | spf-static | spf-reconverge | ecmp | cspf | orbit |
|---|---|---|---|---|---|
| 0.75 | **59** | 141 | 134 | 141 | 142 |
| 0.80 | **54** | 134 | 128 | 132 | 134 |
| 0.85 | **49** | 129 | 120 | 126 | 126 |
| 0.90 | **46** | 125 | 116 | 118 | 118 |
| 0.95 | **42** | 120 | 111 | 111 | 108 |
| 0.98 | **39** | 117 | 107 | 106 | 102.5 |
| 1.00 | **38** | 111 | 102 | 103 | **99** |

The ordering never changes. Raising the threshold to 1.00 - where only a link at or beyond its
full capacity can fail - reduces cascade depth for everyone but does not close the gap: static
SPF still suffers 38 against 99-111.

Dwell time behaves similarly. Depths are flat from 1 to 20 ticks and fall for everyone at 40
ticks (4 s of sustained overload) without changing the ordering: static 43 against 95-103.

Delivery ratio tells the same story at every threshold. Static SPF's advantage over the best
recovering algorithm is +0.037 to +0.052 overall PDR, and it is largest at the *most*
permissive thresholds, not the tightest.

### What this does and does not license

**Supported:** in this model, across every cascade rule tested, an algorithm that reroutes
after a failure propagates a substantially deeper cascade and delivers less traffic than one
that does not. The effect is not a threshold artefact.

**Not supported, and not claimed:** that this holds in real networks. The result rests on the
project's own cascade abstraction - a link fails when utilisation stays above theta for
`dwell` consecutive ticks - which is a modelling assumption, not a measured property of
hardware. The sweep rules out sensitivity to that rule's *parameters*; it cannot rule out
sensitivity to the rule's *form*. A model where overload degrades capacity gradually, or where
failure probability rises smoothly with utilisation, might behave differently and has not been
tested.

**The mechanism is plausible and consistent with the data:** recovery relocates displaced
demand onto surviving links, which pushes them over the threshold, which fails them, which
displaces more demand. Static SPF blackholes the affected traffic instead, and blackholed
traffic loads nothing. That is why its advantage grows as the threshold becomes *more*
permissive - more headroom means more room for relocated traffic to do damage before anything
fails.

**What it implies for the design:** ORBIT already carries a utilisation term in its placement
cost and does not weight it aggressively enough to avoid this. The next section runs that
experiment.

---

## Utilisation ceiling - the cascade is avoidable, and two separate things cause it

`a9-ceiling`, **1,800 runs**, manifest `dirty: false`. Waxman and scale-free, offered load
0.9, cascade thresholds {0.90, 0.95, 0.98}, 30 paired trials, 10 algorithms.

`OrbitConfig.utilisation_ceiling` refuses to place a flow if doing so would leave a link
above the ceiling, and the best-effort fallback respects the ceiling too. The controller
therefore declines traffic it could physically carry.

Median over all cells:

| Algorithm | cascade depth | overall PDR | CRITICAL | HIGH | LOW |
|---|---|---|---|---|---|
| spf-static | 48 | 0.119 | 0.120 | 0.121 | **0.114** |
| cspf | 120 | 0.057 | 0.061 | 0.052 | 0.046 |
| orbit | 117 | 0.057 | 0.075 | 0.059 | 0.043 |
| orbit-no-fallback | 65 | 0.295 | 0.649 | 0.389 | 0.121 |
| orbit-ceiling-1.0 | 49.5 | 0.331 | 0.636 | 0.508 | **0.125** |
| **orbit-ceiling-0.95** | **0** | **0.445** | 0.903 | 0.725 | 0.124 |
| orbit-ceiling-0.9 | **0** | 0.434 | **0.932** | **0.747** | 0.096 |
| orbit-ceiling-0.8 | **0** | 0.386 | 0.907 | 0.684 | 0.071 |
| orbit-ceiling-0.7 | **0** | 0.332 | 0.727 | 0.586 | 0.087 |
| orbit-ceiling-0.6 | **0** | 0.271 | 0.501 | 0.447 | 0.068 |

A ceiling at or below 0.95 **eliminates the cascade entirely** - depth 0 in every cell at
every threshold tested - and delivers 3.7x static SPF's traffic and 7.8x plain ORBIT's.
Paired, `orbit-ceiling-0.95` wins overall PDR in 6 of 6 cells against every control, all
large effect, Holm-adjusted p < 0.05:

| vs | median difference |
|---|---|
| spf-static | **+0.325** |
| orbit | **+0.395** |
| orbit-no-fallback | +0.125 |
| orbit-ceiling-1.0 | +0.088 |

### The effect decomposes into two causes, and the smaller one is the ceiling

The controls matter more than the headline. `orbit-no-fallback` has **no ceiling at all** —
it is plain ORBIT with the best-effort fallback disabled — and it already reaches 0.295 PDR
against plain ORBIT's 0.057. That is roughly **two thirds of the total improvement, from
removing the fallback alone.**

| Step | overall PDR | share of the gain |
|---|---|---|
| orbit (baseline) | 0.057 | — |
| + disable best-effort fallback | 0.295 | **61%** |
| + ceiling at 1.0 (capacity constraint, no headroom) | 0.331 | 9% |
| + ceiling at 0.95 (genuine headroom) | 0.445 | 29% |

So the honest statement is **not** "a utilisation ceiling fixes cascades". It is:

1. **The best-effort fallback is actively harmful under cascading overload.** It places flows
   that fit nowhere onto already-loaded paths, pushing links over theta and propagating the
   cascade. This is the same fallback added in `fc415d9` to remove an unfair asymmetry
   against ORBIT — correct in the non-cascade case, harmful here. A mechanism can be right
   for one regime and wrong for another, and this project now has a measured example.
2. **Genuine headroom is what drives cascade depth to zero.** Ceiling 1.0 still suffers depth
   49.5; ceiling 0.95 suffers 0. Only refusing to fill a link *completely* stops the
   propagation.
3. **The optimum is not the most conservative setting.** Delivery peaks near 0.95 and falls
   monotonically below it — 0.271 at ceiling 0.6. Too much caution declines more traffic than
   the cascade would have destroyed.

### What this does and does not license

**Supported:** in this model, a controller that reserves ~5% headroom on every link avoids
the cascade entirely and delivers substantially more traffic than any algorithm tested,
including static SPF. The gain is attributable — roughly 60% to declining unplaceable flows
rather than forcing them, and 40% to the headroom itself.

**Not supported, and not claimed:** any real-network claim. This inherits every limitation of
the cascade rule it is tuned against, and a ceiling tuned to a threshold the operator does not
know is not a deployable design. The result is evidence that *the model's* cascade is
avoidable, and a demonstration that admission control beats forced placement under overload.

**Not tested:** whether the ceiling harms the non-cascade scenarios where ORBIT's original
advantage lives. It almost certainly costs delivery there, since it declines traffic the
network could carry, and it is not enabled by default for that reason. Measuring that
trade-off across the headline grid is the next experiment and has not been run.

---

## H2 resolved: the censoring is real, not a metric bug

`peak_restore_fraction` explains the 69–75% censoring directly. Median peak post-failure
delivery, as a fraction of the pre-failure mean:

| Algorithm | peak restore fraction | time-to-converge |
|---|---|---|
| cspf | 0.801 | 0.3 s |
| orbit | 0.800 | 0.3 s |
| spf-reconverge | 0.792 | 0.3 s |
| ecmp | 0.786 | 0.3 s |
| spf-static | 0.691 | 0.0 s |

CRITICAL traffic recovers to about **80%** of its pre-failure rate and stops there. The 95%
criterion is therefore unreachable, and censoring is the *correct* answer: the capacity is
genuinely gone, and no controller can route around a shortage that does not exist elsewhere.
H2 was not measuring a slow recovery, it was measuring an incomplete one.

**Time-to-converge is measurable and does separate the algorithms** — 0.3 s for every
recovering algorithm, 0.0 s for static SPF, which never changes a route. The control plane
settles long before delivery does, which is exactly the distinction §7 warned about.

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

1. **The contribution claim must be rewritten.** The ablation shows M1, M3 and M4 are inert.
   ORBIT is one mechanism, not four. The utilisation ceiling is a fifth candidate mechanism
   with a measured effect, but it is only measured under cascade and is off by default.
2. **The cascade result is robust to its parameters but rests on one model form.** The sweep
   (25,200 runs, 168 cells) rules out threshold and dwell sensitivity. It does not rule out
   sensitivity to the shape of the cascade rule itself, and no real-network claim may be made
   from it.
3. **The LP gap is implemented but not swept.** It is validated (no algorithm exceeds the
   bound) and measured at 2.4% on one 12-node case; a proper sweep over small topologies has
   not been run.
4. **Sizes 250 and 500 were not benchmarked** and are not claimed.
6. **Two defects were found in ORBIT's placement path after the first grid run**, both by the
   dashboard and by a precondition guard rather than by the test suite. Regression tests now
   cover both, but the episode is a reason to treat these numbers as provisional until an
   independent check exists.
