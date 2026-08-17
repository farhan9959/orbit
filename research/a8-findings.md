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

* **Preemption never fires in this grid** — median 0 per run. **Corrected by A11:** the median
  is 0 but the mechanism fires in 19 of these 120 runs, and in 47% of runs once ring
  topologies and higher loads are included. "Never" was the wrong word; "fires and achieves
  nothing" is the measured claim. See the A11 section.
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
  situation preemption exists for essentially does not arise. **Superseded by A11:** in
  conditions this grid did not contain (ring topologies, loads to 2.0, cascading) preemption
  fires in 47% of runs and 2,024 times in total — and still produces 0 wins in 36 cells.
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

### The cost outside cascade - measured, and it does not pay

`a9-ceiling-cost`, **3,360 runs**, manifest `dirty: false`. The full headline grid (4 families
x 7 failure scenarios) at offered load 0.7, 30 paired trials, with and without the ceiling.

Pooled medians look favourable to the ceiling:

| Algorithm | CRITICAL | HIGH | overall | LOW |
|---|---|---|---|---|
| cspf | 0.790 | 0.705 | 0.593 | **0.426** |
| orbit | 0.827 | 0.743 | 0.583 | 0.321 |
| orbit-ceiling-0.9 | **0.897** | 0.805 | 0.570 | 0.226 |
| orbit-ceiling-0.95 | **0.897** | **0.818** | **0.604** | 0.250 |

**The paired per-scenario test says the opposite, and it is the correct test.** Against plain
ORBIT across the 28 scenarios:

| Comparison | overall PDR | CRITICAL PDR |
|---|---|---|
| ceiling-0.95 vs orbit | **5 wins / 20 losses**, median -0.018 | 4 wins / 6 losses, median **0.000** |
| ceiling-0.9 vs orbit | **4 wins / 23 losses**, median -0.025 | 4 wins / 7 losses, median **0.000** |

The ceiling **loses aggregate delivery in the large majority of scenarios and produces no
reliable CRITICAL benefit at all** - the median paired difference on CRITICAL is exactly zero,
with wins and losses roughly balanced. It also drives LOW-class delivery down further than
plain ORBIT already does, from 0.321 to 0.250.

The discrepancy between the pooled and paired views is itself worth recording. Pooling medians
across scenarios of differing difficulty lets a gain in a few easy scenarios mask losses in
many harder ones. The design is paired precisely so that this cannot happen, and here the
pairing changes the conclusion. **A pooled table would have reported a benefit that the paired
test shows is not there.**

### Verdict on the ceiling

The utilisation ceiling is a **cascade-specific mechanism, not a general improvement**. It is
decisive under cascading overload - depth 0, +0.325 PDR over static SPF - and it is a net
negative everywhere else. It stays **off by default**, and it is not claimed as a fifth ORBIT
mechanism.

What it does establish generally is the finding underneath it: under cascading overload,
forcing unplaceable flows onto loaded paths is harmful, and admission control beats forced
placement. That is a statement about a regime, not about a controller.

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

1. ~~**The contribution claim must be rewritten.**~~ **Done, and it went further than
   expected.** A11 (6,480 runs) put M1, M3 and M4 into conditions built to make them fire;
   they fired, and returned 0 wins in 36 cells. All three are out of the claim. The
   utilisation ceiling was tested as a fifth candidate and rejected. And the literature review
   then found that the one surviving mechanism is not novel either: FFC §5.1 calls
   priority-ordered computation on residual capacity existing practice, citing B4 and SWAN.
   The contribution is the harness and the measurements — see `research/literature-review.md`
   §5.
2. **The cascade result is robust to its parameters but rests on one model form.** The sweep
   (25,200 runs, 168 cells) rules out threshold and dwell sensitivity. It does not rule out
   sensitivity to the shape of the cascade rule itself, and no real-network claim may be made
   from it.
3. ~~**The LP gap is implemented but not swept.**~~ **Done.** `a10-optimality`, 13,200
   placements: ORBIT's median gap is 1.40%, the best of the five algorithms, and no algorithm
   exceeds the bound anywhere.
4. ~~**Sizes 250 and 500 were not benchmarked.**~~ **Done.** `a10-scale`, 2,400 runs to 500
   nodes: 13 wins / 0 losses against CSPF on CRITICAL delivery, and the advantage grows with
   size. Two methodology defects had to be fixed first; see the A10 section.
6. **Two defects were found in ORBIT's placement path after the first grid run**, both by the
   dashboard and by a precondition guard rather than by the test suite. Regression tests now
   cover both, but the episode is a reason to treat these numbers as provisional until an
   independent check exists.

---

# A10 / A11 — scale, mechanisms and the optimality gap

Four experiments run after the A9 series, all with clean manifests. They close the last three
research gaps: the scale claim, the M1/M3/M4 verdict, and the LP sweep.

## Scale: 50 to 500 nodes

`a10-scale`, **2,400 runs**, 91 minutes, manifest `dirty: false`. Waxman and scale-free x
{50, 100, 250, 500} nodes x {critical_link, random_node_30} x 5 algorithms x 30 paired trials.

### The sweep could not be run as pre-registered, and why

`docs/05-methodology.md` B1 specifies a Waxman scale sweep across all sizes. Run literally, it
measures the wrong thing twice over:

1. **Waxman's density is not scale-invariant.** At fixed alpha and beta the per-pair edge
   probability does not fall with n, so the edge count grows as O(n^2). Measured mean
   out-degree: **1.8 at 10 nodes, 3.8 at 60, 7.6 at 100, 21.3 at 250, 44.0 at 500.** A sweep on
   that parameterisation varies density and size together and can attribute a result to
   neither.
2. **`offered_load` does not fix per-flow demand.** It fixes total demand as a fraction of
   network capacity. With capacity growing quadratically and the flow count fixed, mean
   per-flow demand reaches **605 Mbps against 100 Mbps links** at Waxman-500. No single-path
   algorithm can serve any flow in full, and every algorithm collapses onto the same
   capacity-limited floor - measured PDR 0.10 for spf-static, cspf and orbit alike, identical
   to three decimals.

Both were fixed by holding constant what a size sweep has to hold constant: mean degree pinned
at 4.0 via `waxman_target_degree`, and flow counts chosen per (family, size) so mean per-flow
demand is 0.353 x link capacity, the 60-node headline value. The generator change consumes the
RNG in the identical order, so every earlier result is untouched; a test asserts it.

### ORBIT's advantage grows with size

Median CRITICAL delivery, critical-link failure, Waxman:

| nodes | spf-static | spf-reconverge | ecmp | cspf | **orbit** |
|---|---|---|---|---|---|
| 50 | 0.925 | 0.966 | 0.994 | 0.998 | **0.999** |
| 100 | 0.879 | 0.921 | 0.960 | 0.981 | **0.999** |
| 250 | 0.882 | 0.896 | 0.943 | 0.982 | **0.996** |
| 500 | 0.859 | 0.870 | 0.934 | 0.966 | **0.981** |

Scale-free behaves the same way, ORBIT reaching 1.000 at 500 nodes against CSPF's 0.992.

**ORBIT stays flat while every baseline degrades.** Paired against CSPF over all 16 cells:
**13 wins, 0 losses** on `pdr_critical`. The two non-wins are the 50-node critical-link cells
where both algorithms already sit at 0.999 and there is nothing left to win. The median paired
difference rises with size - +0.000 at 50 nodes, +0.010 at 100, +0.006 at 250, +0.011 at 500
on Waxman - and the effect size reaches *medium* to *large* at 100 nodes and above.

On overall PDR the result is **3 wins / 3 losses**, and the split is informative: every loss is
a Waxman critical-link cell (-0.010 to -0.013, small effect) and every win is a
`random_node_30` cell at 250 or 500 nodes (+0.004 to +0.010). **At scale, under node failures,
ORBIT stops paying the aggregate-delivery cost it pays at 60 nodes.**

### Cost, and a wrong conclusion avoided

`a10-control-cost`, 40 single-threaded measurements, manifest `dirty: false`. Median
milliseconds for one full recompute:

| nodes | spf-reconverge | ecmp | cspf | orbit |
|---|---|---|---|---|
| 50 | 5.2 | 33.5 | 25.8 | 28.4 |
| 100 | 18.0 | 88.4 | 63.1 | 65.7 |
| 250 | 104.7 | 474.7 | 353.9 | 391.8 |
| 500 | 422.4 | 1806.4 | 1331.8 | 1394.5 |

Cost grows as roughly O(n^1.7) to O(n^2.0), consistent with one Dijkstra per flow while the
flow count grows linearly. **ORBIT costs within ~7% of CSPF and consistently less than ECMP**,
so the A8 finding that ORBIT is not the expensive option holds at every size tested.

**N4 ("recomputation under 100 ms at 100 nodes") is met: 65.7 ms on Waxman, 72.7 ms on
scale-free.** The curve also shows where it stops being met, between 100 and 250 nodes. A run
of 100 nodes, 200 flows and 60 s of simulated time completes in 6.0 s against N2's 30 s budget.

**A wrong conclusion was nearly published here.** `a10-scale`'s own `control_seconds` column
implies 460 ms per recompute at 100 nodes, which would fail N4 by fivefold. That number is an
artefact of running 18 workers on 20 cores: contention inflates wall-clock control timings
roughly tenfold. The inflation is common to every algorithm, so the grid's *comparison* between
algorithms is unaffected, but its absolute numbers cannot carry an absolute claim. Hence the
separate single-threaded driver, and a note in `experiments/runner.py`.

---

## A11 - M1, M3 and M4 fire, and change nothing

`a11-mechanisms`, **6,480 runs**, manifest `dirty: false`. Four families **including ring**,
offered load {0.9, 1.5, 2.0}, failures {critical_link, cascading, random_node_30}, six
algorithms, 30 paired trials. 36 cells.

### Why the earlier ablation could not settle this

`a8-ablation` reported all three inert, but it held conditions under which none of them *can*
act, so it could not distinguish "does not help" from "was never reached":

* **M3 preemption** is attempted only when no path has residual capacity for the flow. On
  Waxman and scale-free that is rare; on a **ring** - degree two, one path per pair - it is
  routine. The old grid contained neither ring nor grid.
* **M4 damping** binds only after a flow has rerouted three times inside a 50-tick window. A
  single injected failure reroutes most flows once. Churn requires **cascading**, which the old
  ablation grid did not include.
* **M1 protection** needs a case where the precomputed backup is live and the recomputed path
  is not equivalent.

A11 supplies all three conditions, and `backup_activations` was added to the metrics so that
firing and helping could be told apart.

### They fired

| mechanism | runs where it fired | total firings |
|---|---|---|
| M1 protection | 175 / 1080 (16.2%) | 248 backup activations |
| M3 preemption | 506 / 1080 (46.9%) | 2,024 preemptions |

Preemption concentrates exactly where predicted: 1,023 of the 2,024 on ring against 265 on
Waxman. This **corrects the A8 statement that "preemption never fires"** - it fires in nearly
half of all runs. The median was zero, which is a different claim.

Per trial, the mechanisms change real outcomes:

| variant | runs identical to full ORBIT |
|---|---|
| M1 off | 994 / 1080 (92.0%) |
| M3 off | 742 / 1080 (68.7%) |
| M4 off | 990 / 1080 (91.7%) |
| M1+M3+M4 off | 682 / 1080 (63.1%) |

### And none of it makes a difference

Paired Wilcoxon, Holm-adjusted, full ORBIT against each ablation, over all 36 cells:

| mechanism | `pdr_critical` | `pdr` | `pdr_low` |
|---|---|---|---|
| M1 protection | **0 wins / 0 losses** | 0 / 0 | 0 / 0 |
| M3 preemption | **0 wins / 0 losses** | 0 / 0 | 0 / 0 |
| M4 damping | **0 wins / 0 losses** | 0 / 0 | 0 / 0 |
| M1+M3+M4 together | **0 wins / 0 losses** | 0 / 0 | 0 / 0 |

The median paired difference is exactly 0.00000 in every one of those twelve comparisons, and
the smallest Holm-adjusted p across all of them is 0.87.

The clearest single statement is about preemption. Restricting to the 506 runs where it
actually fired, against the identical run with preemption disabled: **424 are identical, the
median change in CRITICAL delivery is exactly zero, and the tails are symmetric - worst
-0.110, best +0.071.** Preemption moves individual runs in both directions and nothing on
average. It is noise, not signal.

**Why preemption cannot help here.** It exists so a high-priority flow can take capacity from
a lower-priority one. That needs CRITICAL to be starved *and* a path to exist once victims are
evicted. In this model CRITICAL is starved only when no path exists at all (partition) or when
a single flow's demand exceeds a link's capacity, and preemption fixes neither. Where it does
fire, CRITICAL is already at 0.998-0.999 and there is nothing to buy.

**Why protection cannot help here.** The controller recomputes the whole routing state in the
tick it learns of a failure, and the protection branch runs immediately before restoration
would find a path anyway. There is no interval in which a precomputed backup is available and
recomputation is not. That is not what IP-FRR is: RFC 5714's value comes from **local** repair
at the node adjacent to the failure, tens of milliseconds *before* the control plane knows
anything. This model has no local-repair actor - the detector gates all knowledge and the
central controller is the only thing that places routes. **M1 is not refuted here so much as
inexpressible here**, and that distinction is the honest one to record.

### Verdict, against criteria fixed before the run

The spec required a mechanism to win `pdr_critical` in at least a quarter of the cells with no
significant reversals. All three won zero cells. Per criterion C, **M1, M3 and M4 are removed
from the contribution claim.**

The code stays, behind its existing configuration flags. Deleting it would make this result
unreproducible, and a measured negative is worth being able to re-derive.

**ORBIT is one mechanism: priority-ordered constrained restoration (M2), plus a best-effort
fallback that is not one of the four documented mechanisms and is the only non-M2 component
the measurements support.** `research/literature-review.md` §5 records that M2 is itself
described as existing practice by FFC §5.1, citing B4 and SWAN.

---

## The LP optimality gap, swept

`a10-optimality`, **13,200 placements**, manifest `dirty: false`. Four families x
{9, 12, 15} nodes x four loads x {none, critical_link} x 5 algorithms x 30 trials. Each
algorithm places flows on the post-failure graph; the LP solves the splittable relaxation on
that same graph, so the two face an identical world.

**No algorithm exceeds the bound in any of the 13,200 cells.** That is the check that matters:
the relaxation is an upper bound on the unsplittable optimum, so exceeding it would mean the
bound is broken, not that the heuristic is good.

| algorithm | median gap | mean | at load 0.5 | at load 1.2 |
|---|---|---|---|---|
| spf-static | 3.65% | 9.75% | 0.46% | 9.35% |
| spf-reconverge | 3.65% | 9.75% | 0.46% | 9.35% |
| ecmp | 2.74% | 8.28% | 0.27% | 8.24% |
| cspf | 2.78% | 8.71% | 0.15% | 9.04% |
| **orbit** | **1.40%** | **6.87%** | **0.08%** | **6.71%** |

ORBIT is closest to the bound at every load and in every family, and the margin widens with
load. The gap is **conservative**: the relaxation permits arbitrary splitting, so part of the
1.4% is looseness in the bound rather than weakness in the heuristic. The earlier single
12-node case reported 2.4%; the swept figure is 1.40% over 2,640 ORBIT placements.

One caveat worth stating: on Waxman at these sizes all five algorithms return an identical
4.68% gap. At 9-15 nodes a Waxman graph often admits only one sensible path per pair, so the
algorithms are not being distinguished there at all. The separation comes from grid and
scale-free.
