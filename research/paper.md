# Priority-aware constrained recovery: what it buys, what it costs, and what it does not do

**Status: draft. Every number traces to a committed results file. The positioning section is
incomplete because the literature review has not been done, and no novelty claim is made.**

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

Three results run against our own predictions and we report them as the main contribution of
the study rather than as caveats. First, an ablation shows that three of the controller's four
mechanisms are inert: disabling protection, preemption and damping together changes no measured
outcome, and preemption never fires. Second, under cascading overload every algorithm that
recovers propagates a deeper cascade and delivers less traffic than one that does not; static
shortest path, which never reroutes, suffers less than half the cascade depth. A 25,200-run
sweep over the cascade rule's threshold and dwell time shows this holds in 168 of 168
parameter cells with no reversals. Third, the cascade is nonetheless avoidable: a controller
that reserves ~5% link headroom eliminates it entirely and delivers 3.7x static shortest
path's traffic — but controls show roughly 60% of that gain comes from declining unplaceable
flows rather than from the headroom itself.

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
places. Preemption never fires: median zero per run across every scenario. The entire measured
advantage comes from priority-ordered constrained restoration alone.

The claim this study can defend is therefore narrower than the design intended: **priority-ordered
constrained restoration outperforms priority-blind constrained restoration under capacity
shortage**. It does not require the word "integration", and three quarters of the design are
currently unsupported. They are retained behind ablation switches because they may matter
under conditions not tested — tighter capacity, faster failure arrival — but that is a
hypothesis, not a result.

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

## 5. Threats to validity

* **Flow-level, not packet-level.** Sub-tick dynamics, TCP congestion control, microbursts and
  per-packet reordering are invisible. Delivery ratio here is rate-based.
* **Queueing delay is a bounded approximation**, not a queueing-theory result. Applied
  identically to every algorithm, so it cannot bias a comparison; it can shift absolute latency.
* **The cascade rule is an assumption.** The sweep rules out sensitivity to its parameters, not
  to its form. A model where overload degrades capacity gradually might behave differently.
* **Synthetic topologies only**, 60 nodes. Sizes 250 and 500 are supported by the code and are
  not claimed. No real ISP topology was used.
* **Time-to-restore could not be evaluated.** Critical traffic recovers to ~80% of its
  pre-failure rate and stops, so the 95% criterion is unreachable and ~70% of runs censor. The
  hypothesis was measuring an incomplete recovery, not a slow one.
* **Distributed convergence is modelled from a single vantage point**, not per-router.
* **No optimality bound at scale.** An LP relaxation is implemented and validated on small
  topologies (2.4% gap on one 12-node case) but not swept.
* **Two defects were found in the controller after the first benchmark run**, both by the
  dashboard and by a precondition guard rather than by the 300-test suite. Both penalised
  ORBIT, and correcting them reversed a published conclusion. Results were retracted and
  regenerated. This is a reason to treat the numbers as provisional pending independent check.

## 6. Positioning — NOT YET DONE

ORBIT's mechanisms derive from IP Fast Reroute (RFC 5286), CSPF and MIRA, RSVP-TE preemption
(RFC 3209) and BGP route flap damping (RFC 2439). **None is novel and we make no novelty
claim.** Establishing what is and is not already studied requires the literature review, which
has not been carried out. Until it is, this document claims only to be a measurement study with
a reproducible artefact, and the positioning table in `research/literature-review.md` is empty
by design rather than by oversight.

The most defensible contribution available is the harness itself: a laptop-runnable, seeded,
fully reproducible comparison in which every figure regenerates from committed raw data. The
systems it compares against were evaluated on proprietary production networks with unreleased
code.

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
3. Whether M1, M3 and M4 matter under any tested condition, or should be removed.
4. An optimality-gap sweep, so "how far from optimal" has an answer.
5. Cross-validation against Mininet on a small topology, comparing trends rather than absolutes.
