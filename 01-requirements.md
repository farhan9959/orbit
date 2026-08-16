# 01 — Requirements

Status: Phase 1 draft. Nothing here is implemented yet.

## 1. Problem statement

When links or routers fail, conventional IP routing reconverges to a new shortest path. Two
things go wrong during and after that reconvergence:

1. **Recovery is capacity-blind.** Shortest-path recomputation ignores residual bandwidth, so
   surviving links become congested and traffic that "recovered" still suffers loss.
2. **Recovery is priority-blind.** A bulk file transfer and an emergency telemetry stream are
   treated identically. Under a capacity shortfall, both degrade, when the correct behaviour is
   to protect the critical one.

ORBIT investigates whether a controller that is aware of residual capacity and traffic priority
can restore *critical* traffic faster and more completely than conventional routing — and what
that costs in aggregate throughput, latency, and control overhead.

## 2. Research question and hypotheses

**RQ.** Under single, multiple, and regional failures, does priority-aware capacity-constrained
recovery improve critical-traffic delivery ratio and time-to-restore relative to shortest-path
reconvergence, ECMP, and congestion-aware shortest path?

**H1.** ORBIT achieves higher packet delivery ratio for CRITICAL and HIGH classes than all
baselines at failure levels ≥ 10%.

**H2.** ORBIT achieves lower time-to-restore for CRITICAL flows, because protected flows fail
over from a precomputed backup rather than waiting for a full recomputation.

**H3 (expected cost).** ORBIT achieves *lower or equal* aggregate throughput and *higher*
control-plane computation time than static shortest path, because preemption sacrifices
low-priority flows and the controller does strictly more work.

H3 predicts a result unfavourable to ORBIT. It is stated up front deliberately: a system that
wins on every metric is usually a system with a rigged baseline.

## 3. Functional requirements

Priority: **M** = must (Tier A), **S** = should (Tier B), **C** = could (Tier C, only if time).

### Network & traffic model
| ID | Requirement | Pri |
|----|-------------|-----|
| F1 | Model a network as a directed graph of nodes (router/host) and links with capacity, propagation delay, intrinsic loss rate, and up/down/degraded state | M |
| F2 | Generate topologies from seeded families: grid, ring, Waxman random, Barabási–Albert scale-free; and load hand-written topologies from a spec file | M |
| F3 | Support sizes 10, 25, 50, 100, 250, 500 nodes — **claim only the sizes actually benchmarked** | M |
| F4 | Model traffic flows with source, destination, demand rate, start time, duration, and priority ∈ {CRITICAL, HIGH, NORMAL, LOW} | M |
| F5 | Persist a topology's node coordinates in its spec so visualisations are stable and visually comparable across runs | S |
| F6 | Model shared-risk link groups (SRLG) so a "regional failure" can take down a correlated set of elements | M |

### Simulation engine
| ID | Requirement | Pri |
|----|-------------|-----|
| F7 | Advance simulation in fixed time steps; per step, allocate link capacity to flows and compute delivered rate, loss, and latency per flow | M |
| F8 | Allocate contended link capacity by strict priority between classes and max-min fairness within a class | M |
| F9 | Produce identical output for identical seed, on the same code version | M |
| F10 | Record per-tick per-flow metrics to disk in a columnar format, plus a run summary | M |
| F11 | Support stepping, pausing, resetting, and running headless to completion | M |

### Failure model
| ID | Requirement | Pri |
|----|-------------|-----|
| F12 | Inject: single/multiple node failure, single/multiple link failure, regional (SRLG) failure, bandwidth degradation, latency spike, loss spike, congestion surge, and time-lagged cascading failure | M |
| F13 | Inject failures either from a scripted schedule (deterministic, for benchmarks) or interactively (for the demo) | M |
| F14 | Support targeted failure selection (e.g. highest-betweenness link) and seeded random selection | M |
| F15 | Model failure *detection* explicitly with a configurable detection interval, applied identically to every algorithm | M |

### Routing / control plane
| ID | Requirement | Pri |
|----|-------------|-----|
| F16 | Baseline B1: static shortest path (Dijkstra), no recomputation after failure | M |
| F17 | Baseline B2: shortest-path reconvergence with modelled LSA propagation and SPF hold-down | M |
| F18 | Baseline B3: ECMP over equal-cost shortest paths | M |
| F19 | Baseline B4: congestion-aware shortest path (CSPF on residual capacity) | M |
| F20 | ORBIT controller: protection + priority-ordered restoration + bounded preemption + damping (see `docs/03-simulation-model.md` §6) | M |
| F21 | Record every control-plane decision as a structured event (what failed, which flows were affected, which were rerouted/preempted/blackholed, and the computation time) | M |
| F22 | Report an optimality gap against an LP/ILP optimum on small topologies (≤ 15 nodes) | S |

### Experiments & analysis
| ID | Requirement | Pri |
|----|-------------|-----|
| F23 | Declare an experiment as a spec file (topology × traffic × failure schedule × algorithms × trials × seeds) and run it headless from the CLI | M |
| F24 | Use paired seeds: every algorithm in a cell faces the identical topology, traffic, and failure sequence | M |
| F25 | Compute per-run and aggregate metrics: PDR overall and per priority class, throughput, mean/p95 latency, time-to-restore, time-to-converge, route churn, preemption count, control computation time | M |
| F26 | Produce plots and result tables from raw data with a single command, with statistical tests and confidence intervals | M |
| F27 | Embed a reproducibility manifest (git SHA, seeds, package versions, host CPU/RAM, wall-clock) in every results artifact | M |

### Platform (Tier B)
| ID | Requirement | Pri |
|----|-------------|-----|
| F28 | HTTP API to create/read topologies, scenarios, experiments, and runs | S |
| F29 | Live session API: start/pause/step/reset, inject failure, switch algorithm | S |
| F30 | Server→client stream of simulation state deltas | S |
| F31 | Dashboard: topology with node/link health, active routes, per-class metrics, event log, failure controls, algorithm selector, and baseline-vs-ORBIT side-by-side | S |
| F32 | Persist users, topologies, scenarios, experiments, runs, events, and audit logs | S |
| F33 | Authentication (email + password) and server-side role-based + ownership-based authorization | S |
| F34 | Health, readiness, and metrics endpoints; structured JSON logs with request/run correlation IDs | S |

### Documentation
| ID | Requirement | Pri |
|----|-------------|-----|
| F35 | `docs/learning-notes.md` with WHAT/WHY/HOW/TRADEOFFS/INTERVIEW for every major component | M |
| F36 | `research/{literature-review,methodology,results,paper}.md` | M |
| F37 | README with architecture diagram, quick start, algorithms, real benchmark results, limitations | M |
| F38 | `docs/final-security-audit.md` and `docs/final-audit.md`, each with evidence of the test that verified each item | S |

## 4. Non-functional requirements

| ID | Requirement | How it will be verified |
|----|-------------|------------------------|
| N1 | Runs entirely on a laptop: ≤ 8 GB RAM, no GPU, no special hardware | Benchmarks record peak RSS; CI runs on a 2-core GitHub runner |
| N2 | A 100-node / 200-flow / 60 s-sim-time run completes in under 30 s wall clock | `pytest-benchmark` ceiling test; **target, not yet measured** |
| N3 | Determinism: identical seed ⇒ identical metrics file | Hash-comparison test in CI |
| N4 | Control-plane recomputation for a single link failure at 100 nodes completes in < 100 ms | Benchmark; **target, not yet measured** |
| N5 | No secret material in the repository, ever | `gitleaks` in CI and in a pre-commit hook |
| N6 | Every state-changing API endpoint enforces authn + authz server-side | Automated security tests, one per endpoint |
| N7 | Expensive operations are bounded server-side (nodes, ticks, flows, trials, concurrency) | Rate-limit and cap tests |
| N8 | Test coverage ≥ 80% on `orbit/engine/` and `orbit/algorithms/` | `pytest --cov` gate in CI |
| N9 | `docker compose up` gives a working system on a clean machine | Documented, and exercised by the CI e2e job |
| N10 | Dashboard is keyboard-navigable, has non-colour-only status encoding, and meets WCAG AA contrast | Manual checklist + axe in the e2e job |

**On N10:** network dashboards conventionally encode health as red/amber/green alone. Roughly
1 in 12 men has a red–green colour vision deficiency, so status is additionally encoded by
shape/icon and by text. This is a real correctness requirement for a status display, not a
checkbox.

## 5. Explicit non-goals

Writing these down is what stops scope creep, and each one is an honest answer to "why didn't
you do X?" in an interview.

- **Not packet-level.** No per-packet events, no TCP congestion-control dynamics, no queue
  modelling below the tick interval. Consequence: microbursts and TCP fairness effects are
  invisible. Listed in Threats to Validity.
- **Not a real control plane.** No OSPF/BGP wire protocol implementation. Reconvergence timing
  is *modelled*, not executed.
- **Not distributed.** ORBIT's controller is centralised (SDN-style). A distributed variant is
  future work; the centralised-baseline comparison in §3 of the methodology exists precisely so
  that ORBIT's architectural advantage is separated from its algorithmic one.
- **No machine learning in v1.** Per the project rules: build and benchmark the deterministic
  system first. ML is considered only if a measured problem exists that it can solve.
- **No Kubernetes, no microservices, no message broker.** One API process, one worker process,
  one database. Splitting further would add operational complexity with no requirement behind it.
- **No file uploads** unless topology import from a file turns out to be genuinely needed; if it
  is, it becomes a size-capped, schema-validated JSON/YAML paste-or-upload with no filesystem
  write of user-controlled names.
- **Not certified for operational use.** ORBIT models emergency-priority traffic as a research
  scenario. Nothing in it is validated for real emergency or medical infrastructure, and the
  README, UI, and paper all state this.
