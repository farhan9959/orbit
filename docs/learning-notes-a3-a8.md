# Learning notes — phases A3 to A8

Companion to `docs/learning-notes.md`, which covers A1 and A2. Same form: WHAT / WHY / HOW /
TRADEOFFS / HOW I EXPLAIN IT.

---

## A3 — Detector, GraphView, and the SPF baselines

**WHAT.** `FailureDetector` decides when a topology change becomes visible to the control
plane; `GraphView` is what algorithms are handed instead of ground truth; `StaticShortestPath`
(B1) and `ReconvergingShortestPath` (B2).

**WHY.** This is the component that decides whether the whole comparison is honest. If ORBIT
were given instant global knowledge while the baselines waited for flooding and hold-down
timers, ORBIT would "win" on recovery time purely because of *architecture*, and the result
would be worthless. So every algorithm receives the same detector object with the same
parameters, and the architectural advantage is isolated by running the baselines in both
control modes rather than by pretending it does not exist.

The `GraphView` / ground-truth split is the other half. Routing reads the view; physics reads
the truth. Between a failure and its detection the controller is routing over a graph that no
longer exists, and traffic is genuinely lost. That is modelled behaviour and it bounds how
good time-to-restore can possibly be.

**HOW.** The detector diffs ground truth against what it last saw, schedules each change to
become believed at `tick + delay`, and rebuilds a believed `Topology` when changes fall due.
Delay is `detection_interval + jitter`, plus a control-channel delay (centralised) or
hop-proportional flooding plus an SPF hold-down (distributed).

**TRADEOFFS.** Distributed flooding is measured to one reference vantage point rather than
per-router. A per-router model would need a distributed forwarding plane, which
`01-requirements.md` §5 explicitly excludes. Stated as a threat to validity rather than
hidden.

**HOW I EXPLAIN IT.** "The sharpest question anyone can ask about a 'my algorithm beats X'
project is whether X was given a fair chance. My answer is a single shared detector object
plus dual control modes: every baseline runs both against realistic IGP timing and against
the same instant global view my controller gets. The first comparison answers 'better than
what networks actually do', the second answers 'better *algorithm*'. Reporting only the first
would be the strawman."

---

## A4 — Failure injection

**WHAT.** Node, link, SRLG, bandwidth-degrade, latency-spike, loss-spike, congestion-surge,
restore, and a stateful cascade rule. Targeted selection by betweenness, seeded random by
fraction.

**WHY.** Cascading failure is the scenario worth the most, because it is where capacity-blind
recovery is actively harmful: reconvergence dumps rerouted traffic onto surviving links,
those links exceed the threshold, and they fail too. If capacity-aware placement reduces
cascade depth, that is a measured claim with a metric behind it.

**HOW.** The schedule is a pure function of `(base topology, tick)`. It never mutates the base
topology; it materialises a new one. That is what makes I-NOCREATE checkable and runs
replayable. `CONGESTION_SURGE` scales demand rather than the topology, because it is a
traffic event, not a hardware one.

**TRADEOFFS.** Restore returns an element to its *initial* state rather than its
previous one, so a degrade-then-restore recovers full capacity without the caller tracking
history. Simpler, and there is no scenario that needs the alternative.

---

## A5 — ECMP and CSPF, and the multipath problem

**WHAT.** B3 ECMP splits a demand across equal-cost paths; B4 CSPF prunes links without
enough residual capacity.

**WHY CSPF matters most.** It is capacity-aware but *priority-blind*. Without it the project
could only claim "capacity-awareness helps", which is already well known. The ORBIT-vs-CSPF
difference is the one that isolates the contribution of priority awareness specifically.

**HOW, and the model change it forced.** The allocator was single-path. Making ECMP a
first-class baseline meant `RoutingState` had to carry either a `Route` or a `PathSet`, and
the allocator had to expand a placement into per-path entries so that max-min fairness
operates at the sub-path level. That is what per-flow-hashed ECMP actually does, so it is the
faithful model rather than a convenience. `Allocation` now also reports per-path rates, so
ECMP's latency and loss are computed exactly rather than approximated from the nominal split.

**TRADEOFFS.** CSPF falls back to a best-effort shortest path when nothing fits, rather than
blackholing at the ingress. Real deployments forward best-effort; without the fallback CSPF
would look artificially bad on delivery and artificially good on latency, which would be a
rigged baseline in the opposite direction.

---

## A6 — The ORBIT controller

**WHAT.** M1 protection (SRLG-disjoint CRITICAL backups), M2 priority-ordered constrained
restoration, M3 bounded preemption, M4 damping. Each with an ablation switch.

**WHY ablation switches.** Without them the claim is "this bundle of four things helps".
With them the claim is specific: *which* mechanism produces the benefit. That is cheap to
build and it is the difference between a result and an anecdote.

**HOW.** Surviving routes are kept where they still fit, so stability is preserved. CRITICAL
flows fail over to a precomputed backup first. The rest are restored in
`(-priority, -demand, id)` order against a running residual-capacity table. When a flow of
HIGH or above cannot fit, victims are drawn *only* from strictly lower priorities, taken
cheapest-first until the shortfall is covered, displaced, and re-queued once. Damping blocks
a reroute that exceeds the budget or fails to improve cost by the threshold.

**TRADEOFFS.** Every one of these is a documented failure mode, written before measuring:
partition (correctly blackholed, censored), SRLG-shared backup (coverage reported), preemption
cascade (single-pass, bounded), damping under-reaction (parameter sweep), greedy ordering
suboptimality (needs the LP gap, not yet built), stale view (bounds recovery time).

**HOW I EXPLAIN IT.** "None of the four mechanisms is novel — they are IP-FRR, CSPF,
RSVP-TE preemption and BGP flap damping. The contribution is the integration plus a
reproducible measurement of what it buys and what it costs. Preemption is the interesting
part: victims come strictly from lower priorities and are re-queued exactly once, which is
what bounds the cascade. And the ablation switches mean I can say which mechanism did the
work rather than waving at the bundle."

---

## A7 — Experiment runner and statistics

**WHAT.** Declarative specs, a paired-seed runner, Parquet plus manifest output, and paired
non-parametric statistics.

**WHY the pairing.** Every algorithm in a cell faces a bit-identical world because the seed
is derived before the algorithm is chosen. That removes between-run variance from the
comparison, which is a large power gain, and it makes the statistics paired — Wilcoxon
signed-rank rather than Mann-Whitney.

**WHY effect size next to every p-value.** With 30 paired trials a trivial difference becomes
"significant". Cliff's delta is what says whether anyone should care. Reporting p alone is a
common and avoidable error.

**WHY censoring is explicit.** A run that never recovers has no recovery time. Recording it as
zero flatters the algorithm; recording it as infinite punishes it; dropping it silently biases
the result upward. It is reported as null, counted, and excluded with the count stated.

**The bug worth remembering.** The first traffic calibration was an arbitrary constant and
produced PDR 1.000 at nominal load 0.7 — the load axis meant nothing, and every load-dependent
claim would have been vacuous. The fix is dimensional: a flow of rate r over h hops consumes
r*h of capacity, so feasible demand is total_capacity/mean_hops. Sanity-checking that a
parameter actually moves the outcome is worth more than another unit test.

---

## A8 — The comparison

**WHAT.** 5,550 runs across the headline grid, the dual-control comparison and the load sweep.

**HOW I EXPLAIN IT.** See `research/a8-findings.md` for the verdicts. The thing to say about
A8 is that the hypotheses were written down before the code existed, including H3, which
predicted ORBIT would *lose* on aggregate throughput. A result that contradicts a
pre-registered hypothesis is reported as a result, not reframed.
