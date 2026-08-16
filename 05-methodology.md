# 05 — Testing Strategy & Benchmark Methodology

Status: Phase 1 design. No results exist yet. Every number in this project's README, paper, and
CV bullet must trace back to a run produced by this pipeline.

---

# Part A — Testing strategy

## A1. Test layers, and what each is actually for

| Layer | Tool | What it catches | Runs |
|---|---|---|---|
| Unit | pytest | logic errors in a single function | every commit |
| **Differential** | pytest + NetworkX | our Dijkstra/ECMP disagreeing with a mature implementation | every commit |
| **Property** | Hypothesis | invariant violations in states nobody thought to write down | every commit |
| **Determinism** | pytest | non-reproducibility — hash of output vs stored hash | every commit |
| Integration | pytest + Postgres service | API ↔ DB ↔ worker wiring | every PR |
| Security | pytest | authz bypass, rate limits, injection, CSRF, error leakage | every PR |
| E2E | Playwright | the demo path a human will follow | every PR |
| Performance | pytest-benchmark | regressions past a documented ceiling | every PR (relative), documented machine (absolute) |

**Differential and property testing carry the most weight here**, and this is the thing to say in
an interview. Example-based unit tests confirm what you already believed. In a simulator, the
bugs are in the states you didn't imagine — a link that fails during the same tick as a reroute,
a flow whose source and destination are the same node, a topology with a self-loop. Hypothesis
finds those; a hand-written test suite does not.

## A2. The oracle tests

NetworkX is a mature, widely used graph library. It is a **test-only dependency** and never
imported by `orbit/`.

- `test_dijkstra_matches_networkx`: for 200 Hypothesis-generated weighted graphs, our SPF path
  cost equals `nx.shortest_path_length`. (Path *identity* is not asserted — ties are broken
  differently; cost equality is the real property.)
- `test_ecmp_path_set_matches_networkx`: our equal-cost path set equals
  `nx.all_shortest_paths` as a set.
- `test_cspf_matches_bruteforce`: on graphs with ≤ 8 nodes, exhaustive enumeration of simple
  paths confirms CSPF finds a feasible path whenever one exists.
- `test_orbit_gap_vs_lp`: on ≤ 15-node topologies, the LP relaxation (via `scipy.optimize.linprog`)
  bounds the achievable weighted-served-demand; ORBIT's allocation is asserted to be feasible and
  its gap is **recorded**, not asserted to be zero. A heuristic that matched the optimum every
  time would mean the test is wrong.

## A3. Property tests (mapping to the invariants in `03-simulation-model.md` §9)

```
given: arbitrary seeded topology (3–40 nodes), arbitrary flows, arbitrary failure schedule
assert after every tick:
    I-CAP     per-link allocation ≤ capacity
    I-DOWN    no allocation over DOWN elements
    I-PATH    every route is a simple path over known-UP elements
    I-DEMAND  delivered ≤ demand
    I-PRIO    no LOW flow served at a bottleneck where a CRITICAL flow is unserved
    I-NOCREATE the algorithm did not mutate the ground-truth topology
```
Failing examples are **committed** to a regression corpus (`tests/regressions/`) so a bug found
once is tested forever.

## A4. Required edge cases (each gets a named test)

| Case | Expected behaviour |
|---|---|
| Disconnected graph | flows across the partition → BLACKHOLED; run marked censored for recovery metrics |
| No route exists for one flow | that flow BLACKHOLED, all others unaffected |
| Source node fails | its flows terminate, no crash, no phantom allocation |
| Destination node fails | same |
| Simultaneous node + link failures in one tick | both applied atomically before any recompute |
| Repeated fail → restore → fail of the same element | no state leakage; damping counters behave |
| Zero-capacity link | never selected by any algorithm; not a division-by-zero |
| 100% loss rate link | delivered = 0 through it; not a NaN |
| Extreme latency (10⁶ ms) | no overflow; path costs remain ordered correctly |
| Invalid topology (dangling link endpoint, duplicate ID) | rejected at validation with a specific error |
| Duplicate link between same pair | permitted (parallel links are real), capacities are independent |
| Self-loop link | rejected at validation |
| Flow with src == dst | rejected at validation |
| Zero-demand flow | permitted, contributes nothing, doesn't divide by zero in PDR |
| Empty flow set | run completes with zero-valued metrics, not a crash |
| Single-node topology | run completes |
| Unauthorized API operation | 403/404 as specified in the threat model |
| Oversized spec | 422 before any work is enqueued |

## A5. Coverage policy

Coverage gate of 80% on `orbit/engine/` and `orbit/algorithms/`; no gate elsewhere. Coverage is a
smoke detector, not a goal — 100% coverage with weak assertions is worse than 70% with property
tests. Never write a test purely to raise the number.

---

# Part B — Benchmark methodology

**This is what makes ORBIT a research project rather than an app.** Get it right and a weak
result is still publishable and defensible; get it wrong and a strong result is worthless.

## B1. Experimental design

**Factors:**

| Factor | Levels |
|---|---|
| Topology family | grid, ring-of-rings, Waxman random, Barabási–Albert scale-free, (stretch: a real ISP topology from the Internet Topology Zoo) |
| Size (nodes) | 10, 25, 50, 100, 250, 500 — *report only what is actually run* |
| Offered load | 0.3, 0.5, 0.7, 0.9 × network bottleneck capacity |
| Failure scenario | none (control), 10% random node, 30% random node, 50% random node, targeted critical link (max betweenness), regional SRLG, congestion surge, cascading |
| Algorithm | B1 static-SPF, B2 SPF-reconverge, B3 ECMP, B4 CSPF, ORBIT |
| Control mode | distributed, centralised (baselines run in both; see §B3) |
| Trials | ≥ 30 seeds per cell |

**Full factorial is too large.** 4 × 6 × 4 × 8 × 5 × 2 × 30 ≈ 230,000 runs. The design is
therefore **fractional**, and the reduction is stated up front rather than discovered later:

- **Main experiment** (the headline result): size fixed at 100, load fixed at 0.7, all 4 topology
  families × all 8 failure scenarios × 5 algorithms × 2 control modes × 30 seeds ≈ 9,600 runs.
- **Scale sweep:** Waxman only, load 0.7, failure = 30% random node, all sizes × 5 algorithms ×
  30 seeds ≈ 900 runs. Answers "does it hold as the network grows" and produces the control-
  overhead-vs-size curve.
- **Load sweep:** Waxman, size 100, failure = critical link, all 4 loads × 5 algorithms × 30
  seeds = 600 runs. Answers "does the advantage depend on how loaded the network already is" —
  likely yes, and that is an interesting finding either way.
- **Parameter sensitivity:** ORBIT only — sweep `R_max`, `δ`, preemption on/off, protection
  on/off. **Ablation matters**: running ORBIT with M1 disabled, M3 disabled, etc. shows *which
  mechanism produces the benefit*. Without ablation the claim is "this bundle helps"; with it,
  the claim is specific. This is high-value and cheap.

## B2. Seed and pairing discipline

```
seed(scenario, trial) = stable_hash(scenario_id, trial_index)
```
The **same seed** drives topology generation, traffic generation, and the failure schedule for
**every algorithm in that cell**. Consequently every algorithm faces a bit-identical world.

This makes the design **paired**, which matters twice:
1. It removes between-run variance from the comparison, which is a large power gain — far fewer
   trials are needed to detect the same effect.
2. It makes the statistics paired: **Wilcoxon signed-rank**, not Mann-Whitney U.

Seeds are recorded in every results row. Any single run can be re-executed exactly:
`make run SPEC=... SEED=...`.

## B3. Fair comparison rules (the credibility of the whole project rests here)

1. **Identical world:** same topology, traffic, failure sequence, and seed.
2. **Identical detection:** the same failure-detector object with the same parameters for every
   algorithm. Recovery time is never measured from an instant the baseline could not have known.
3. **Both control modes:** every baseline runs *distributed* (realistic IGP timing) and
   *centralised* (same global view ORBIT has). The distributed comparison answers "better than
   practice"; the centralised comparison answers "better *algorithm*". Reporting only the first
   would be the strawman.
4. **Tuned baselines:** B4/CSPF's cost-blend parameters are tuned by the same sweep budget given
   to ORBIT's parameters. An untuned baseline against a tuned proposal is a rigged comparison, and
   it is the single most common flaw in student "my algorithm beats X" projects.
5. **Same measurement window** and same warm-up discard for all algorithms.
6. **No post-hoc scenario selection.** The scenario list is fixed in `experiments/specs/` and
   committed *before* results are generated. If a scenario is added later, it is labelled as
   post-hoc in the paper.

## B4. Statistics

- **Report:** median and IQR (distributions here will be skewed and often bimodal — a run either
  recovers or is partitioned). Means alone would be misleading.
- **Test:** Wilcoxon signed-rank for paired algorithm comparisons; Holm–Bonferroni correction for
  the family of comparisons in each table. Significance level 0.05.
- **Effect size:** Cliff's delta, reported alongside every p-value. With 30+ paired trials,
  trivial differences become "significant"; the effect size is what says whether anyone should
  care. Reporting p without effect size is a common and avoidable error.
- **Confidence intervals:** BCa bootstrap (10,000 resamples) on the median difference.
- **Censoring:** runs where the source–destination pair is partitioned cannot recover. These are
  reported as a separate `partitioned_fraction` statistic and **excluded from recovery-time
  aggregates with the exclusion count stated**. They are *not* silently dropped and *not* recorded
  as instant recovery — both would bias the result in ORBIT's favour.
- **Timing measurements** (control-plane computation) are taken on one documented machine, with
  the process pinned where possible, `n ≥ 30` repetitions, reported as median with IQR. CI-runner
  timings are never reported as results.

## B5. Reproducibility manifest

Every results file embeds:
```json
{"git_sha": "...", "dirty": false, "python": "3.12.x", "platform": "...",
 "cpu": "...", "cores": n, "ram_gb": n, "packages": {...},
 "spec_path": "...", "spec_sha256": "...", "base_seed": n,
 "started_at": "...", "wall_clock_s": n}
```
A run with `dirty: true` (uncommitted changes) is **never** used for a reported result; the
runner warns loudly.

`make reproduce` regenerates every figure and table in `research/results.md` from
`experiments/results/`. A reader with the repo and the raw data gets byte-identical figures. That
capability — not the numbers themselves — is what makes this a reproducible study.

## B6. Result reporting rules

- **A negative result is a result.** H3 predicts ORBIT loses on aggregate throughput. If it does,
  that goes in the abstract, not a footnote. If ORBIT loses on a metric H1/H2 predicted it would
  win, the hypothesis was wrong and the paper says so.
- **No number goes in the README, the paper, or the CV that isn't in a committed results file.**
- **State the scope of every claim:** "on Waxman topologies of 100 nodes at 0.7 offered load,
  ORBIT preserved X% of CRITICAL demand vs Y% for CSPF (median over 30 paired trials, Wilcoxon
  p = …, Cliff's δ = …)" — not "ORBIT improves resilience by X%".
- Every figure states n, the topology family, the size, the load, and the failure scenario.

## B7. Optional external validation (stretch, Tier C)

The strongest available answer to "but your simulator isn't real" is a small cross-validation:
build a ~10-node topology in **Mininet** (Linux, laptop-feasible, no special hardware), run the
same traffic and the same link-failure event, and compare *trends* — not absolute numbers —
against the ORBIT simulator's prediction.

This will not validate the absolute latency model, and should not be claimed to. It would show
that the simulator's *ordering* of algorithms under failure matches an emulated network, which is
the claim being made. Even a single-topology cross-validation moves the Threats to Validity
section from "we acknowledge this limitation" to "we partially addressed it," and that is a
meaningful difference to a reviewer or admissions committee.

If time runs out, the limitation is stated plainly instead. That is an acceptable outcome; a
fabricated validation is not.
