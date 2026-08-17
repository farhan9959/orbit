# Priority-aware constrained recovery: what it buys, what it costs, and what it does not do

**Status: draft. Every number traces to a committed results file. The literature review is
now done from the primary sources (`research/literature-review.md`), and it establishes that
no mechanism claim is available: the one mechanism that survives ablation is described in the
prior work as existing practice. The contribution claimed here is the artefact and the
measurements, including four negative results.**

---

## Abstract

We build a flow-level network resilience simulator and use it to ask whether a priority-aware,
capacity-constrained recovery controller preserves critical traffic better than conventional
routing under failure. Across 60-node synthetic topologies, four topology families, seven
failure scenarios and 30 paired trials per cell, priority-ordered constrained restoration
delivers more CRITICAL and HIGH traffic than a capacity-aware but priority-blind controller
and never less, with the advantage growing monotonically with offered load to +0.14 delivery
ratio at 1.2. It costs one point of aggregate delivery and twelve points of LOW-class
delivery, at *lower* control-plane cost than the baseline it beats.

The advantage holds and widens with network size: over 50 to 500 nodes with mean degree held
constant, CRITICAL delivery stays at 0.98-1.00 while the strongest baseline falls from 0.998 to
0.966, giving 13 wins and no losses across 16 cells. Against a splittable LP relaxation on
small topologies, the controller's median optimality gap is 1.40%, the best of the five
algorithms compared, over 13,200 placements in which no algorithm exceeds the bound.

Four results run against our own predictions and we report them as the main contribution of
the study rather than as caveats. First, an ablation shows that three of the controller's four
mechanisms do nothing. Placed deliberately in conditions built to make them act, they act -
preemption fires in 47% of runs, protection in 16% - and produce zero significant wins across
36 conditions and three delivery metrics, with a median paired difference of exactly zero.
Second, under cascading overload every algorithm that
recovers propagates a deeper cascade and delivers less traffic than one that does not; static
shortest path, which never reroutes, suffers less than half the cascade depth. A 25,200-run
sweep over the cascade rule's threshold and dwell time shows this holds in 168 of 168
parameter cells with no reversals. Third, the cascade is nonetheless avoidable: a controller
that reserves ~5% link headroom eliminates it entirely and delivers 3.7x static shortest
path's traffic — but controls show roughly 60% of that gain comes from declining unplaceable
flows rather than from the headroom itself, and a further 3,360-run test shows the ceiling is
a net negative outside cascade. We therefore report it as a regime-specific result and reject
it as a general mechanism. Fourth, the literature review finds that the surviving mechanism
is not novel: FFC (SIGCOMM 2014) describes computing higher-priority traffic first and lower
priorities on residual capacity as practice already established by B4 and SWAN. What is not
present in that literature is a released, seeded artefact that measures recovery *per priority
class*; the closest open harness, YATES, models a single traffic aggregate.

---

## 1. Problem

When links or routers fail, conventional IP routing reconverges to a new shortest path. Two
things go wrong. Recovery is **capacity-blind**: shortest-path recomputation ignores residual
bandwidth, so surviving links become congested and traffic that "recovered" still suffers loss.
And recovery is **priority-blind**: a bulk transfer and an emergency telemetry stream are
treated identically, when the correct behaviour under a capacity shortfall is to protect the
critical one.

We ask whether a controller aware of both residual capacity and traffic priority restores
critical traffic more completely than conventional routing, and what that costs.

## 2. What we built

A fixed-timestep, flow-level simulator. Each tick, active flows have a rate, links have
capacity, contention is resolved by strict priority between traffic classes and max-min
fairness within a class, and loss and latency are derived from utilisation. Flow-level rather
than packet-level because the question is about rates and timing, and because a statistically
meaningful comparison needs thousands of runs rather than tens.

Five algorithms share one interface and one failure detector:

| | capacity-aware | priority-aware |
|---|---|---|
| static shortest path | no | no |
| shortest path with reconvergence | no | no |
| ECMP | partly | no |
| **CSPF** | **yes** | **no** |
| **ORBIT** | **yes** | **yes** |

CSPF is the load-bearing comparison. It is capacity-aware and priority-blind, so the
ORBIT-vs-CSPF difference isolates priority awareness specifically. Without it the study could
only conclude that capacity-awareness helps, which is already known.

## 3. Method

The credibility of the comparison rests on four choices, all enforced in code:

**Paired seeds.** The seed is derived from the scenario identity before the algorithm is
chosen, so every algorithm in a cell faces a bit-identical topology, traffic matrix and failure
sequence. The design is paired, so the statistics are Wilcoxon signed-rank rather than
Mann-Whitney.

**One shared detector.** Failures are not instantly known to the control plane. Every algorithm
receives the same detector object with the same parameters, so recovery is never measured from
an instant a baseline could not have known.

**Both control modes.** Every baseline runs with realistic IGP timing (flooding delay, SPF
hold-down) and with the same instant global view ORBIT has. The first comparison answers "better
than what networks do", the second "better *algorithm*". Reporting only the first would be a
strawman, and the strawman is the most common flaw in this kind of study.

**Effect size and censoring.** Cliff's delta accompanies every p-value, because with 30 paired
trials trivial differences become significant. A run whose traffic never recovers has no
recovery time; it is reported as null and counted, never as zero or infinite.

Determinism is tested, not asserted: the same seed produces byte-identical output, checked by
SHA-256 over a serialised run for all five algorithms.

## 4. Results

### 4.1 Priority awareness helps, under capacity shortage

Pooled medians over 28 scenarios, 30 paired trials each:

| | CRITICAL | HIGH | NORMAL | LOW | overall |
|---|---|---|---|---|---|
| ORBIT | **0.907** | **0.819** | **0.612** | 0.352 | 0.645 |
| CSPF | 0.874 | 0.760 | 0.607 | **0.472** | **0.655** |
| ECMP | 0.861 | 0.699 | 0.465 | 0.350 | 0.558 |
| SPF-reconverge | 0.843 | 0.650 | 0.441 | 0.330 | 0.532 |
| SPF-static | 0.685 | 0.582 | 0.440 | 0.343 | 0.509 |

Against CSPF, ORBIT wins CRITICAL in 11 of 28 scenarios and HIGH in 15, losing neither. Every
large-effect win is a congestion scenario, not a topology failure: +0.169 on Waxman, +0.143 on
scale-free, +0.081 on grid, all Holm-adjusted p < 0.001 with Cliff's delta above 0.90.

The mechanism earns its keep when the shortage is **capacity**, not connectivity. Once a
capacity-aware algorithm has found a feasible path, priority ordering has little left to decide.

### 4.2 The cost, precisely located

ORBIT trails CSPF on aggregate delivery in 7 of 28 scenarios and wins none, by about one point
(0.645 against 0.655). It is worst of five on LOW, losing 17 of 28 scenarios there. One point
of aggregate and twelve of LOW-class delivery buy three points of CRITICAL and six of HIGH.
Whether that trade is worthwhile is a policy question; the measurement states both sides.

Control-plane cost was predicted to be higher and is not: 0.058 s median against CSPF's 0.068 s
and ECMP's 0.092 s. Keeping surviving routes in place means fewer flows are recomputed per
event than CSPF, which re-places every flow from scratch.

### 4.3 The advantage grows with load

Waxman, critical-link failure, median CRITICAL delivery ratio:

| offered load | 0.3 | 0.5 | 0.7 | 0.9 | 1.2 |
|---|---|---|---|---|---|
| CSPF | 1.000 | 1.000 | 0.981 | 0.930 | 0.809 |
| ORBIT | 0.999 | 0.999 | **0.999** | **0.992** | **0.950** |

The margin is +0.018, +0.062 and +0.141 at loads 0.7, 0.9 and 1.2 while the aggregate cost
stays flat at 1–3 points. The exchange rate improves as the network becomes more overloaded,
which is the regime the mechanism is for.

### 4.4 Three of four mechanisms do nothing

ORBIT was designed as four composed mechanisms: protection (precomputed disjoint backups),
restoration (priority-ordered constrained placement), preemption (bounded, strictly
lower-priority victims) and damping (reroute budget). An ablation with each disabled in turn,
840 runs:

| variant | CRITICAL | HIGH | overall |
|---|---|---|---|
| CSPF | 0.752 | 0.507 | 0.424 |
| ORBIT, all four | **0.887** | **0.695** | 0.415 |
| ORBIT, restoration only | **0.887** | **0.695** | 0.415 |

Disabling protection, preemption and damping *together* changes no outcome to four decimal
places. The entire measured advantage comes from priority-ordered constrained restoration
alone.

That grid could not distinguish "does not help" from "was never reached", because it held
conditions under which none of the three can act: preemption is attempted only when no path
has residual capacity, which is routine on a ring and rare on a Waxman graph; damping binds
only after repeated reroutes, which a single failure does not produce. A second experiment
(`a11-mechanisms`, 6,480 runs) supplied those conditions — four families including ring, loads
to 2.0, and cascading failures — and instrumented how often each mechanism fires.

**They fire.** Preemption in 506 of 1,080 runs (2,024 preemptions, 1,023 of them on ring);
protection in 175 of 1,080 (248 backup activations). Disabling them changes the outcome of 8%
to 31% of individual runs.

**And it makes no difference.** Paired Wilcoxon with Holm correction, across all 36 cells:

| mechanism disabled | `pdr_critical` | `pdr` | `pdr_low` |
|---|---|---|---|
| protection (M1) | 0 wins / 0 losses | 0 / 0 | 0 / 0 |
| preemption (M3) | 0 wins / 0 losses | 0 / 0 | 0 / 0 |
| damping (M4) | 0 wins / 0 losses | 0 / 0 | 0 / 0 |
| all three | 0 wins / 0 losses | 0 / 0 | 0 / 0 |

Median paired difference is exactly zero in all twelve comparisons; the smallest Holm-adjusted
p is 0.87. Among the 506 runs where preemption fired, 424 are bit-identical to the same run
without it, and the remainder are symmetric about zero (worst -0.110, best +0.071). The
mechanism is noise, not signal.

Preemption cannot help in this model because CRITICAL is starved only by partition or by a
single flow's demand exceeding a link's capacity, and evicting a lower-priority victim fixes
neither; where it does fire, CRITICAL is already at 0.998–0.999. Protection cannot help
because the controller recomputes the entire routing state in the tick it learns of a failure,
so there is no interval in which a precomputed backup is available and recomputation is not.
That is not what IP-FRR is — RFC 5714's value is *local* repair before the control plane
knows anything — and this model has no local-repair actor. **M1 is less refuted than
inexpressible here**, which is a different and more useful statement.

Against criteria fixed before the run — keep a mechanism if it wins CRITICAL delivery in at
least a quarter of cells with no significant reversals — all three are removed from the
contribution claim. The code is retained behind its ablation switches so the negative result
stays reproducible, not because it is expected to pay off later.

The claim this study can defend is therefore narrower than the design intended: **priority-ordered
constrained restoration outperforms priority-blind constrained restoration under capacity
shortage**. It does not require the word "integration". And §6 records that even this
mechanism is not novel: it is what B4, SWAN and FFC already do.

### 4.5 Under cascading overload, recovery is harmful

We model cascading failure as: a link fails when its utilisation stays at or above a threshold
theta for `dwell` consecutive ticks. The design document predicted that capacity-aware placement
would reduce cascade depth and called that the strongest potential result.

It is refuted, and the direction is reversed. Median cascade depth of ~232 links:

| | cascade depth | overall delivery |
|---|---|---|
| **SPF-static** | **31.5** | **0.201** |
| ORBIT | 76 | 0.138 |
| ECMP | 77 | 0.121 |
| CSPF | 78.5 | 0.126 |
| SPF-reconverge | 88 | 0.103 |

Static shortest path suffers less than half the cascade depth of every recovering algorithm and
delivers the most traffic. It never reroutes, so it never displaces traffic onto surviving
links, so it never trips the threshold that propagates the cascade. Every algorithm that
recovers makes the cascade worse, and the better it recovers the worse it makes it.

A single parameter setting cannot separate a property of the mechanism from a property of that
setting, so we swept both cascade parameters: theta over seven values from 0.75 to 1.00, dwell
over six values from 1 to 40 ticks, two offered loads, two families, 30 paired trials —
**25,200 runs across 168 parameter cells**, with the cascade parameters excluded from the seed
so every cell faces a bit-identical world. Verdict criteria were fixed before inspecting the
data.

Static shortest path has strictly lower median cascade depth than **every** recovering
algorithm in **168 of 168 cells**, with zero significant reversals and all 672 pairwise effect
sizes large. The ordering is invariant to both parameters. The finding is robust to the rule's
parameters, though not necessarily to the rule's *form*.

### 4.6 The cascade is avoidable, and the cause decomposes

A controller that refuses to place a flow if doing so would leave a link above a utilisation
ceiling — declining traffic it could physically carry — eliminates the cascade. 1,800 runs:

| | cascade depth | overall delivery |
|---|---|---|
| SPF-static | 48 | 0.119 |
| ORBIT | 117 | 0.057 |
| ORBIT, no best-effort fallback | 65 | 0.295 |
| ORBIT, ceiling 1.0 | 49.5 | 0.331 |
| **ORBIT, ceiling 0.95** | **0** | **0.445** |
| ORBIT, ceiling 0.6 | 0 | 0.271 |

The controls are more informative than the headline. `no best-effort fallback` has no ceiling
at all and already reaches 0.295 against plain ORBIT's 0.057 — roughly **60% of the total gain
comes from declining unplaceable flows, not from headroom**. Headroom is nonetheless what takes
cascade depth to zero: ceiling 1.0 still suffers 49.5, ceiling 0.95 suffers none.

Two separable things are therefore true. Forcing unplaceable flows onto already-loaded paths is
actively harmful under cascading overload. And reserving headroom is what stops propagation.
The optimum is not the most conservative setting: delivery peaks near 0.95 and falls to 0.271
at 0.6, because excessive caution declines more traffic than the cascade would have destroyed.

We then tested whether the ceiling is a general improvement, over the full headline grid at
load 0.7 (3,360 runs). It is not. Against plain ORBIT it loses aggregate delivery in 20 of 28
scenarios and its median paired difference on CRITICAL delivery is exactly zero. Pooled
medians across scenarios suggested a benefit; the paired test, which the design exists to
support, shows there is none. The ceiling is a cascade-specific mechanism, is off by default,
and is **not** claimed as a contribution.

That the pooled and paired views disagree is worth stating on its own. Pooling across scenarios
of differing difficulty allowed gains in a few easy cells to mask losses in many hard ones.

## 5. Threats to validity

* **Flow-level, not packet-level.** Sub-tick dynamics, TCP congestion control, microbursts and
  per-packet reordering are invisible. Delivery ratio here is rate-based.
* **Queueing delay is a bounded approximation**, not a queueing-theory result. Applied
  identically to every algorithm, so it cannot bias a comparison; it can shift absolute latency.
* **The cascade rule is an assumption.** The sweep rules out sensitivity to its parameters, not
  to its form. A model where overload degrades capacity gradually might behave differently.
* **Synthetic topologies only.** Sizes to 500 nodes are benchmarked (`a10-scale`), but no real
  ISP topology from the Internet Topology Zoo has been used. The Waxman family also required a
  density correction to be scaled at all: at fixed alpha and beta its mean degree runs from 1.8
  at 10 nodes to 44 at 500, so the size sweep pins mean degree at 4 and matches per-flow demand
  to link capacity. Results at 500 nodes describe a sparse synthetic graph, not a dense one.
* **Time-to-restore could not be evaluated.** Critical traffic recovers to ~80% of its
  pre-failure rate and stops, so the 95% criterion is unreachable and ~70% of runs censor. The
  hypothesis was measuring an incomplete recovery, not a slow one.
* **Distributed convergence is modelled from a single vantage point**, not per-router.
* **No optimality bound at scale.** The LP relaxation is now swept over 13,200 placements, but
  only on 9- to 15-node topologies, because the model has |F| x |E| columns. ORBIT's median gap
  there is 1.40%, the smallest of the five algorithms, and no algorithm exceeds the bound
  anywhere. Nothing bounds optimality at 100 nodes or above. The relaxation is splittable, so
  the reported gap over-states the true distance from the unsplittable optimum.
* **Control-plane timings are contention-sensitive.** The grids run 18 workers on 20 cores,
  which inflates wall-clock control timings roughly tenfold. Absolute per-recompute figures
  come from a separate single-threaded driver; the grids are used only to compare algorithms
  against each other, where the inflation is common.
* **Two defects were found in the controller after the first benchmark run**, both by the
  dashboard and by a precondition guard rather than by the 300-test suite. Both penalised
  ORBIT, and correcting them reversed a published conclusion. Results were retracted and
  regenerated. This is a reason to treat the numbers as provisional pending independent check.

## 6. Positioning

The literature review (`research/literature-review.md`) was carried out from the primary
sources: MIRA (JSAC 2000), B4 and SWAN (SIGCOMM 2013), FFC (SIGCOMM 2014), YATES (SOSR 2018),
and the RFCs each mechanism derives from. It settles the contribution claim, and it settles it
downward.

**No mechanism claim is available.** ORBIT's surviving mechanism, after the ablation, is
priority-ordered constrained routing on residual capacity. FFC §5.1 describes exactly this —
compute the higher-priority traffic first, compute lower priorities on what is left — and
states that the "cascading computation is already done to support multiple priorities",
citing B4 and SWAN. It was production practice in 2013. Nor is the allocator novel: strict
priority between classes with max-min fairness within a class is SWAN's policy. Nor is the
utilisation ceiling this study tested and rejected: SWAN reserves 10% "scratch capacity" on
every link, arriving at the same order of magnitude for a different purpose (congestion-free
updates rather than cascade suppression).

**The prior work also anticipates two of our findings.** FFC's multi-priority headline —
protect high-priority traffic from almost all loss at negligible aggregate throughput cost —
has the same shape as our H1/H3 result, obtained four years earlier by a proactive method with
a formal guarantee, on production traffic and fault logs. And the IP Fast Reroute Framework
states that repair paths may push excessive traffic onto a link and cause congestion discard,
that this reduces the effectiveness of IPFRR, and that mechanisms to distribute repaired
traffic are therefore desirable — while placing that concern out of its own scope. Our cascade
result quantifies an effect the framework named and declined to address.

**What is not in this literature is a released artefact that measures recovery per priority
class.** MIRA, B4, SWAN and FFC published no code; each was evaluated on a proprietary network
against a single incumbent. YATES (SOSR 2018) is open, more mature as TE infrastructure, and
has a failure model including SRLGs — and it models a single traffic aggregate, with no
priority class anywhere in it. The intersection of "priority-aware" and "reproducible" is
empty in this set:

| | capacity-aware | priority-aware | multi-failure | public artefact |
|---|---|---|---|---|
| LFA / IP-FRR | no, out of scope | no | single | n/a |
| MIRA (2000) | yes | no | one link cut | no |
| B4 (2013) | yes | 3 classes | yes | no |
| SWAN (2013) | yes | 3 classes + max-min | yes | no |
| FFC (2014) | yes | per-class protection | guaranteed to k | no |
| YATES (2018) | yes | **no** | yes, incl. SRLG | **yes** |
| **this work** | yes | 4 classes | yes, incl. cascade | **yes** |

The contribution is therefore stated as: **an open, seeded, laptop-runnable harness for
comparing recovery algorithms per priority class under a swept failure catalogue, and the
measurements it produces — including four negative results that the prior work's evaluation
method could not have surfaced.** A production paper has no incentive to report that a quarter
of its own design does nothing; this one does, with the firing counts alongside.

## 7. Reproducing

```bash
make bench       # regenerates every results file
make reproduce   # regenerates every figure and table
```

Every results file embeds a manifest recording the git SHA, a clean-tree flag, interpreter,
platform and package versions. A result generated from a dirty tree is flagged and must not be
reported.

## 8. What would strengthen this

1. The literature review, which gates every positioning claim.
2. Whether the cascade result survives a different cascade *form*, not just different parameters.
3. Whether M1, M3 and M4 matter under any tested condition, or should be removed. The
   utilisation ceiling has already been through this and was rejected.
4. An optimality-gap sweep, so "how far from optimal" has an answer.
5. Cross-validation against Mininet on a small topology, comparing trends rather than absolutes.
