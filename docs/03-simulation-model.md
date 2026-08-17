# 03 — Simulation, Routing, Failure & Recovery Design

Status: Phase 1 design. Not implemented. This is the document to read before writing any engine code.

This is the technical heart of ORBIT. If you can explain this document, you can defend the project.

---

## 1. The modelling decision: flow-level, not packet-level

**Choice:** fixed-timestep, flow-level (fluid) simulation. Each tick, every active flow has a
*rate*; links have *capacity*; contention is resolved by an allocation policy; loss and latency
are derived from utilisation.

**The alternative** is packet-level discrete-event simulation (what ns-3 does): every packet is
an event. It is more faithful and it is the wrong tool here.

| | Packet-level | Flow-level (chosen) |
|---|---|---|
| Fidelity | per-packet queueing, reordering, TCP dynamics | aggregate rate, loss, delay |
| Cost at 100 nodes, 60 s, 200 flows | ~10⁸ events | ~10⁵ tick-flow updates |
| Trials in a benchmark grid | tens, maybe | thousands |
| Determinism | achievable but fragile | straightforward |

The project's deliverable is a **statistically meaningful comparison across thousands of runs**.
Thirty seeds × eight failure scenarios × six sizes × five algorithms is ~7,200 runs. Packet-level
makes that infeasible on a laptop; flow-level makes it a coffee break. Flow-level is also the
standard abstraction in the traffic-engineering literature (B4, SWAN, FFC all reason about flow
rates, not packets).

**The cost, stated honestly in Threats to Validity:** sub-tick dynamics are invisible.
Microbursts, TCP slow-start and congestion-avoidance behaviour, per-packet reordering during
reroute, and transient queue buildup shorter than one tick are not modelled. ORBIT's "packet
delivery ratio" is a *rate-based* delivery ratio, and the paper must call it that.

**Interview answer:** "I chose fidelity that matches the question. The question is 'does
priority-aware recovery restore critical traffic faster,' which is answered by rates and
timing, not by individual packets. Packet-level fidelity would have bought me realism I don't
use and cost me three orders of magnitude of runs — which would have cost me statistical power,
which is the thing the claim actually rests on."

---

## 2. Core model

### Elements
```python
Node(id, kind: ROUTER|HOST, state: UP|DOWN, processing_delay_ms, srlg: set[str])
Link(id, src, dst, capacity_mbps, prop_delay_ms, loss_rate, state: UP|DOWN|DEGRADED,
     degrade_factor, srlg: set[str])          # directed; a bidirectional link is two Links
Flow(id, src, dst, demand_mbps, priority, start_s, duration_s)
Priority = CRITICAL > HIGH > NORMAL > LOW     # integer weights, configurable
```
Links are **directed** because failures are frequently unidirectional in practice and because
asymmetric capacity is common. A "cable" is modelled as two Links sharing an SRLG, so cutting
the cable takes both.

**SRLG (shared risk link group)** is how regional failure is expressed: elements tagged
`"region:west"` or `"conduit:A12"` fail together. Without SRLGs, a "backup path" can be computed
that shares physical fate with the primary — which is exactly the failure mode that makes real
protection schemes fail, and it is worth demonstrating.

### Time
- Fixed tick `Δt` (default **100 ms** of simulated time; configurable).
- Simulation time is `tick_index × Δt`, an integer count — **never a float accumulator**, which
  would drift and break determinism.
- Wall-clock is decoupled: headless runs go as fast as they can; live sessions sleep to a
  configurable speed multiplier.

---

## 3. The tick loop

```
for tick in range(n_ticks):
    1. apply scheduled events        (failures, restorations, traffic changes)
    2. detector.update(tick)         (which failures are now KNOWN to the control plane)
    3. if detector has news or control plane is dirty:
           t0 = perf_counter()
           routing_state = algorithm.recompute(graph_view, flows, routing_state)
           record control_computation_seconds
    4. place flows on routes → offered load per link
    5. allocate link capacity  (strict priority, then max-min within class)
    6. derive per-flow delivered rate, loss, latency
    7. record samples + events
```

Steps are strictly ordered and single-threaded. That ordering is the determinism guarantee: no
concurrency, no dict-iteration dependence (all iteration is over sorted IDs), no global RNG.

### Determinism rules (these are tested, see §9)
- Every stochastic subsystem owns its own `random.Random(seed_derived_from(base_seed, name))`.
  Never `random.random()` at module level.
- All iteration over collections is over sorted ID sequences.
- Single-threaded engine. Parallelism happens **across runs** (separate processes, separate
  seeds), never inside one.
- Floating point is deterministic under these conditions on a fixed platform. Cross-platform
  bit-identity is *not* claimed; the determinism test asserts identity on the same machine and
  the manifest records the platform.

---

## 4. Capacity allocation: strict priority + max-min fairness

This is where "traffic priority" stops being a label and becomes mechanism.

**The problem.** A flow crosses several links. Its achievable rate is limited by its most
constrained link. But how constrained a link is depends on what other flows get, which depends on
*their* bottlenecks. This is the classic max-min fair allocation problem (Bertsekas & Gallager).

**Algorithm — progressive filling with priority classes:**

```
for class in [CRITICAL, HIGH, NORMAL, LOW]:          # strict priority
    residual[link] = capacity[link] - already_allocated[link]
    unsaturated = flows in this class with a valid route
    repeat:
        for each link: fair_share[link] = residual[link] / (#unfixed flows on link)
        bottleneck = the link with the smallest fair_share
        fix every unfixed flow crossing bottleneck at that share (capped at its demand)
        subtract, remove them, remove saturated links
    until no unfixed flows remain
```

Properties (all of which become tests):
- Terminates in at most `|E|` outer iterations — each iteration fixes at least one link.
- Never allocates more than a link's capacity. **Invariant I-CAP.**
- Within a class, no flow can increase without decreasing an equally-or-less-favoured flow at
  its own bottleneck — the definition of max-min fairness. **Invariant I-MAXMIN.**
- A flow never receives more than its demand.

**Strict priority means:** LOW gets only what CRITICAL/HIGH/NORMAL leave behind. Under heavy
overload, LOW can be starved to zero. That is intentional and it is the mechanism H1 depends on —
and also the mechanism that will make ORBIT look bad on aggregate fairness metrics, which we
report.

**Configurable alternative:** weighted fair queueing (each class gets a weight, not absolute
precedence) as a policy option. Worth having because "strict priority starves low traffic" is a
real critique, and being able to show the WFQ variant answers it with data instead of opinion.

### Derived metrics per flow, per tick

> **AMENDED during implementation (A2).** As originally written, this section and
> `05-methodology.md` A4 contradicted each other: delivered rate was defined as the
> allocation result with intrinsic loss listed separately, but A4 requires a 100%-loss link
> to yield `delivered = 0`. Both cannot hold. Resolved toward the methodology:
>
> ```
> allocated_mbps = what the allocator granted   (this is what consumes link capacity)
> delivered_mbps = allocated_mbps * (1 - intrinsic_loss)   (PDR is computed from this)
> ```
>
> Both numbers are recorded so congestion and medium loss stay distinguishable. Note the
> asymmetry: capacity is charged against the *allocated* rate, because traffic dropped by a
> lossy link partway along a path has already occupied the links before it.

- **delivered rate** `a_f` = allocation result (0 if no valid route → `BLACKHOLED`),
  **reduced by intrinsic path loss — see the amendment above**.
- **congestive loss** = `(demand - delivered) / demand`.
- **intrinsic loss** along the path = `1 - Π(1 - loss_rate_e)`.
- **latency** = `Σ_path (prop_delay_e + queue_delay_e) + Σ_path node processing_delay`.
  Queue delay uses a bounded M/M/1-style approximation
  `q_e = min(q_max, k / (C_e − L_e))` for `L_e < C_e`, and `q_max` when saturated.
  **This is an approximation and must be labelled as one** — it is a monotone, well-behaved
  stand-in for "delay grows sharply as a link approaches capacity," not a queueing-theory result.
  It is applied identically to every algorithm, so it cannot bias the comparison; it can only
  affect the absolute latency numbers, which is a Threat to Validity.

---

## 5. Failure model and detection

### Injectable failures (F12)
| Type | Effect |
|------|--------|
| `NODE_DOWN` | node state DOWN; all incident links unusable |
| `LINK_DOWN` | link state DOWN |
| `SRLG_DOWN` | every element tagged with the SRLG goes DOWN (regional failure) |
| `BANDWIDTH_DEGRADE` | capacity × factor (e.g. 0.25) |
| `LATENCY_SPIKE` | prop_delay + Δ, optionally time-varying |
| `LOSS_SPIKE` | loss_rate := p |
| `CONGESTION_SURGE` | inject additional demand (scenario traffic, not a topology change) |
| `CASCADE` | a rule: *if link utilisation > θ for > d ticks, fail it* — models overload-induced failure |

Selection is either **targeted** (highest betweenness centrality, highest utilisation, an
articulation point) or **seeded random** (`k`% of nodes/links). Targeted failures are the
interesting ones: a random 10% failure on a well-connected topology often changes nothing.

**Cascading failure is the scenario worth the most.** It is where capacity-blind recovery is
actively harmful: shortest-path reconvergence dumps rerouted traffic onto surviving links, those
links exceed θ, and they fail too. If ORBIT's capacity-aware placement demonstrably reduces
cascade depth, that is the project's strongest single result — and it will be a *measured* claim
with a cascade-depth metric, not an assertion.

> **AMENDED after measurement (A9 cascade grid, `research/a8-findings.md`).** It was measured,
> and the prediction is refuted. ORBIT's median cascade depth is 76 against CSPF's 78.5 and
> ECMP's 77 — a rounding difference. Capacity-aware placement does **not** reduce cascade
> depth here.
>
> The result runs the other way, and more sharply than expected: **static SPF suffers 31.5,
> less than half of every recovering algorithm, and delivers the most traffic under cascade**
> (0.188 CRITICAL against ORBIT's 0.133). Because it never reroutes, it never displaces
> traffic onto surviving links, so it never trips θ. Every algorithm that recovers makes the
> cascade worse, and the better it recovers the worse it makes it.
>
> Whether this is a real property of cascading overload or an artefact of the θ/dwell model
> is **currently unknown** and is the most interesting open question in the project. It must
> not be reported as a finding about real networks until that is settled.

### Failure detection — the fairness-critical component

**Failures are not instantaneously known to the control plane.** Modelling this explicitly is
what separates a credible comparison from a rigged one.

```
detector: link-local liveness, detection_interval T_d (default 150 ms ≈ 3 × 50 ms, BFD-like)
          → a failure at time t is locally detected at t + T_d (+ jitter, seeded)

knowledge propagation:
  centralised control (ORBIT, and the centralised baseline variants):
      controller knows at t + T_d + control_channel_delay
  distributed control (realistic IGP baseline):
      knowledge spreads hop-by-hop: t + T_d + hops × per_hop_flood_delay
      then SPF runs after an spf_hold_time (models OSPF SPF back-off timers)
```

**Both ORBIT and the baselines use the identical detector object with identical parameters.**

**The strawman trap and how it is avoided.** If ORBIT is centralised (instant global knowledge)
and the baseline is distributed (flooding + hold-down timers), then ORBIT "wins" on recovery time
purely because of *architecture*, not because of its *algorithm* — and the result is worthless.

So every baseline is run in **two modes**:
- **`distributed`** — realistic IGP behaviour, flooding delay + SPF hold-down. Answers: *is ORBIT
  better than what networks actually do?*
- **`centralised`** — same instant global view ORBIT gets. Answers: *is ORBIT's decision logic
  better than shortest-path logic, holding information equal?*

Reporting both isolates the architectural advantage from the algorithmic one. This single
methodological choice is probably the most defensible thing in the project, and it is the answer
to the sharpest question an interviewer or reviewer can ask.

---

## 6. Routing algorithms

Every algorithm implements one interface:

```python
class RoutingAlgorithm(Protocol):
    def recompute(self, view: GraphView, flows: Sequence[Flow],
                  prev: RoutingState) -> RoutingState: ...
```
`GraphView` exposes only what the control plane *knows* (post-detector), never ground truth. This
is enforced by construction — the algorithm is never handed the real graph. That is both a
correctness property and a nice thing to point at in an interview.

### B1 — Static shortest path (Dijkstra)
Computes once at t=0 and never again. **Purpose:** the floor. Shows what happens with no
recovery at all. **Complexity:** O(E log V) per source. **Failure behaviour:** flows whose path
contains a failed element are blackholed permanently.
*Not an ORBIT contribution — Dijkstra, 1959.*

### B2 — Shortest path with reconvergence
Recomputes on detected topology change, subject to flooding delay and SPF hold-down.
**Purpose:** the realistic conventional baseline (what OSPF/IS-IS does).
**Limitation to document:** capacity-blind — it will happily move 800 Mbps onto a 100 Mbps link.

### B3 — ECMP
Splits a flow's demand equally over all equal-cost shortest paths (RFC 2992).
**Purpose:** shows how much of the benefit is available from plain load spreading.
**Limitation:** equal split regardless of residual capacity; only helps when equal-cost paths
exist, which depends heavily on topology family — worth reporting per topology family.

### B4 — CSPF (congestion-aware shortest path)
Dijkstra on a graph pruned of links with insufficient residual capacity for the flow, with a
cost that blends latency and utilisation. Flows are placed in arrival order.
**Purpose:** the *strong* baseline. This is important — B4 is capacity-aware but
**priority-blind**, so the ORBIT-vs-B4 difference isolates the contribution of *priority
awareness* specifically. Without B4 the project can only claim "capacity-awareness helps," which
is already well known.

### ORBIT — Priority-Aware Constrained Recovery

Four composed mechanisms. **None of them is individually novel, and the documentation says so.**

| Mechanism | Prior art it derives from |
|---|---|
| M1 Protection (precomputed disjoint backups for CRITICAL only) | IP Fast Reroute / LFA (RFC 5286), MPLS-TE fast reroute |
| M2 Restoration (priority-ordered CSPF on residual capacity) | CSPF, MIRA (Kodialam & Lakshman 2000) |
| M3 Bounded preemption | RSVP-TE setup/holding priority (RFC 3209) |
| M4 Damping (reroute budget + improvement threshold) | BGP route flap damping (RFC 2439) |

**The honest claim:** ORBIT is an *integration* of these into a single priority-differentiated
recovery controller, plus a reproducible measurement of what that integration buys and costs
under multi-failure and cascading conditions. The contribution is the system + the empirical
study, not a new algorithm. Any stronger claim requires the literature review to first establish
that the combination is unstudied — and if it turns out to be studied, the claim gets weakened,
not the literature ignored.

> **AMENDED after measurement (A9 ablation, `research/a8-findings.md`).** The claim above is
> no longer supported by this project's own data. Disabling M1, M3 and M4 together changes
> no measured outcome to four decimal places: restoration-only ORBIT scores 0.8866 CRITICAL,
> 0.6948 HIGH and 0.4154 overall, identical to the full controller. The entire measured
> advantage over CSPF comes from **M2 alone**.
>
> M1 never helps because M2 finds an equivalent path within the same tick, so precomputed
> backups buy nothing when recomputation is not the bottleneck. M3 never fires at all —
> median 0 preemptions per run across every scenario. M4 changes no outcome.
>
> The claim this project can actually defend is therefore narrower: **priority-ordered
> constrained restoration outperforms priority-blind constrained restoration**, under
> capacity shortage, at lower control-plane cost. It does not need the word "integration".
>
> M1, M3 and M4 are retained in the code behind ablation switches because they may matter
> under conditions not yet tested — tighter capacity, faster failure arrival, or without the
> best-effort fallback. Until that is measured they are unsupported, and the paper must say
> so rather than describing four mechanisms as though all four earn their place.

#### Objective function (explicit)

Minimise, in lexicographic order:
1. `Σ_f w(priority_f) × unserved_demand_f`   — primary
2. `Σ_f served_f × path_latency_f`           — secondary
3. `number_of_route_changes`                 — tertiary (stability)

subject to: per-link `Σ served ≤ capacity`; routes are simple paths over UP elements known to
the controller; per-flow reroutes within a window ≤ `R_max`.

**This is a heuristic for an NP-hard problem.** Unsplittable multi-commodity flow with priorities
is NP-hard; ORBIT is a greedy priority-ordered heuristic, not an optimiser. On topologies of
≤ 15 nodes we solve the LP/ILP relaxation with `scipy.optimize.linprog` and report the
**optimality gap** — how far ORBIT's allocation is from the achievable optimum. Reporting a gap
is enormously more credible than reporting only "better than baseline," and it makes the
limitations section write itself.

#### Decision procedure

```
on detected topology change:
    affected = union of flows whose current route touches a now-DOWN element
               (via reverse index link→flows; O(|affected|), not O(|flows|))

    # M1 — protected flows fail over immediately
    for f in affected where priority == CRITICAL and f.backup is valid:
        install backup; emit FLOW_REROUTED(via=BACKUP)

    # M2 — restore the rest, highest priority first
    for f in sorted(remaining affected, key=(-priority, -demand, id)):   # id → deterministic
        residual = graph minus links with residual_capacity < f.demand
        path = dijkstra(residual, cost = α·latency + β·utilisation_penalty)
        if path: install; reserve capacity
        else:
            # M3 — bounded preemption
            if priority(f) >= HIGH:
                victims = lowest-priority flows on the bottleneck link, ascending,
                          taken until f fits;  never preempt equal-or-higher priority
                if victims free enough capacity:
                    displace victims (emit FLOW_PREEMPTED); install f
                    re-queue victims at the end of the restoration order
                else: mark f BLACKHOLED
            else: mark f BLACKHOLED

    # M4 — damping
    a flow may not be rerouted more than R_max times per window W,
    and a voluntary (non-failure-driven) reroute requires cost improvement ≥ δ

    # backup recomputation, budget-capped
    recompute CRITICAL backup paths (link-disjoint w.r.t. primary and SRLG-disjoint
    where possible) — at most B per tick, amortised across ticks
```

**Complexity:** M2 dominates. With `K` affected flows and `S` distinct sources among them,
batching per source gives `O(S · E log V + K · path_length)`. The reverse index keeps `K` small
for localised failures; a regional failure makes `K` large, which is exactly the case §8 of the
architecture doc plans for.

#### Documented failure cases of ORBIT (write these before measuring, not after)
1. **Partition.** If the graph is disconnected, no algorithm can route — flows are correctly
   BLACKHOLED. This must not be counted as an ORBIT failure, and recovery-time observations in
   partitioned runs are **censored**, not dropped (dropping them biases results upward).
2. **SRLG-shared backup.** If the backup path shares an SRLG with the primary, a regional failure
   kills both and M1 provides nothing. Mitigated by SRLG-disjoint backup computation; when no
   disjoint backup exists, that is recorded (`backup_coverage` is a reported metric).
3. **Preemption cascade.** Preempting LOW flows re-queues them, which may preempt further flows.
   Bounded by: victims are only chosen from strictly lower priority, and the re-queue is
   single-pass. Cascade depth is capped and counted.
4. **Damping under-reaction.** `R_max` can prevent a genuinely necessary reroute. Sensitivity to
   `R_max` and `δ` is a reported parameter sweep, not a hidden constant.
5. **Greedy ordering suboptimality.** Serving flows in priority order can place an early flow
   such that two later flows both fail, where a different assignment would have served all three.
   This is what the LP optimality-gap analysis quantifies.
6. **Stale controller view.** Between failure and detection, ORBIT routes on a wrong graph. This
   is modelled, not hidden, and it bounds how good time-to-restore can possibly be.

---

## 7. Metric definitions (precise — ambiguity here invalidates results)

| Metric | Definition |
|---|---|
| **PDR** (per class, and overall) | Σ delivered bytes ÷ Σ demanded bytes, over the measurement window |
| **Throughput** | Σ delivered rate, averaged over the window |
| **Mean / p95 latency** | demand-weighted over delivered traffic only (undelivered traffic has no latency; averaging it in as zero would flatter congested runs) |
| **Time-to-restore (class c)** | time from the failure event until class-*c* delivered rate first reaches ≥ 95% of its pre-failure 1-second mean, **and stays there for 3 ticks**. If never reached: **censored** at run end, reported as censored |
| **Time-to-converge** | time from failure until the control plane makes no further route changes for 3 consecutive ticks |
| **Route churn** | count of route changes per flow per failure event |
| **Preemptions** | count of FLOW_PREEMPTED events, by victim priority |
| **Cascade depth** | number of secondary failures triggered by overload after the initial injection |
| **Control overhead** | wall-clock seconds in `algorithm.recompute()`, plus number of invocations |
| **Backup coverage** | fraction of CRITICAL flows holding a valid, SRLG-disjoint backup at failure time |

Time-to-restore and time-to-converge are **different numbers** and both are reported. The control
plane can converge on a route set that still doesn't deliver the traffic (because capacity is
gone). Conflating them is a common way to accidentally overstate a result.

---

## 8. Repository structure

```
ORBIT/
├── README.md  LICENSE  .gitignore  .env.example  CLAUDE.md  Makefile
├── docker-compose.yml  pyproject.toml
│
├── orbit/                      # the library — no I/O, no web, no DB
│   ├── model/                  # Node, Link, Flow, Topology, GraphView, SRLG
│   ├── generators/             # seeded grid / ring / waxman / barabasi_albert
│   ├── engine/                 # tick loop, allocator, metrics, failure injector, detector
│   ├── algorithms/             # spf.py ecmp.py cspf.py orbit_controller.py + base Protocol
│   ├── scenarios/              # spec schemas (pydantic) + loader
│   └── cli.py                  # run one simulation / one experiment headless
│
├── experiments/
│   ├── specs/                  # YAML experiment definitions (version-controlled)
│   ├── runner.py               # executes the grid, parallel across runs
│   ├── analysis/               # aggregation, statistics, plots
│   └── results/                # .gitignored raw parquet + committed summary CSVs
│
├── api/                        # FastAPI app: routes, auth, authz, persistence, worker
│   ├── migrations/             # alembic
│   └── tests/
├── web/                        # React + TS dashboard
├── tests/                      # unit, property, integration, security, invariants
├── deploy/                     # Dockerfiles, nginx conf, compose overrides
├── docs/                       # this folder + learning-notes.md + audits
└── research/                   # literature-review, methodology, results, paper
```

Changes from the structure in the original brief, and why:
- **`simulation/` + `algorithms/` merged into `orbit/`.** They share the model types and are
  imported together everywhere. Two top-level packages would mean a circular-import problem or a
  third shared package. One library, clear submodules.
- **`benchmarks/` folded into `experiments/`.** A benchmark *is* an experiment with a particular
  spec. Two directories would mean two runners and two result formats.
- **`monitoring/` dropped as a top-level directory.** Metrics live next to the code that emits
  them (`api/observability.py`); Prometheus/Grafana config lives in `deploy/`. A top-level
  `monitoring/` with two YAML files in it is a directory pretending to be a subsystem.
- **`scripts/` dropped** in favour of a `Makefile`. Anything worth scripting is worth a make
  target; anything else is a one-liner in the README.

---

## 9. Invariants (these become the property-test suite)

| ID | Invariant | Why it matters |
|----|-----------|----------------|
| I-CAP | For every link, Σ allocated ≤ capacity (unless the scenario explicitly permits oversubscription) | The allocator is the physics of the simulator; violating this makes every number meaningless |
| I-DOWN | No flow is allocated a non-zero rate over a DOWN node or link | The single most important correctness property; a violation means ORBIT is "recovering" through failed hardware |
| I-PATH | Every installed route is a simple path (no repeated nodes) whose elements all exist and are known-UP to the controller | Prevents forwarding loops and phantom routes |
| I-DEMAND | delivered_f ≤ demand_f for all f | No traffic created from nothing |
| I-DET | Same seed + same code ⇒ byte-identical metrics output | The entire reproducibility claim |
| I-PRIO | If a LOW flow is served on a link, no CRITICAL flow is unserved *at that same bottleneck* | The priority mechanism actually works |
| I-AUTHZ | A user can read/modify only objects they own, unless ADMIN | Server-side authorization holds |
| I-NOCREATE | Recovery never produces a topology different from the ground-truth one (the controller may only change routes, never links) | Catches a whole class of engine bugs where the control plane mutates the world |
| I-CENSOR | A run in which the source and destination are in different partitions is marked censored, never counted as a 0-second or infinite recovery | Prevents a subtle, results-flattering statistics bug |

Property-based tests (Hypothesis) generate random topologies/flows and assert I-CAP, I-DOWN,
I-PATH, I-DEMAND, I-PRIO. Differential tests compare our Dijkstra and ECMP path sets against
NetworkX on the same graphs. Both are far more valuable than more example-based unit tests,
because the interesting bugs in this system live in states nobody thought to write down.
