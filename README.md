# ORBIT

**A flow-level network resilience simulator and evaluation harness.** It measures whether a
priority-aware, centrally-computed recovery controller restores traffic faster and preserves
critical traffic better than conventional routing, under injected failures.

It is a research prototype and a measurement study. It is **not** certified emergency
infrastructure, not a packet-level simulator, and not a replacement for ns-3 or Mininet.
Nothing in it is validated for real emergency or medical use.

---

## The result, in one paragraph

On 60-node synthetic topologies at offered loads from 0.3 to 1.2, priority-ordered
constrained restoration preserves more CRITICAL and HIGH traffic than a capacity-aware but
priority-blind controller (CSPF), and never less. The advantage is negligible when capacity
is adequate and grows monotonically with overload, reaching **+0.14 CRITICAL delivery ratio
at 1.2 offered load**. It costs 1–3 points of aggregate delivery, borne almost entirely by
the LOW class, at *lower* control-plane cost than the baseline it beats.

Two of the project's own hypotheses were **not** supported, and one of its four mechanisms
does all the work. Both are reported in full in [`research/a8-findings.md`](research/a8-findings.md).

| Median, pooled over 28 scenarios × 30 paired trials | CRITICAL | HIGH | NORMAL | LOW | overall |
|---|---|---|---|---|---|
| **orbit** | **0.907** | **0.819** | **0.612** | 0.352 | 0.645 |
| cspf | 0.874 | 0.760 | 0.607 | **0.472** | **0.655** |
| ecmp | 0.861 | 0.699 | 0.465 | 0.350 | 0.558 |
| spf-reconverge | 0.843 | 0.650 | 0.441 | 0.330 | 0.532 |
| spf-static | 0.685 | 0.582 | 0.440 | 0.343 | 0.509 |

Every number here traces to a committed results file with a reproducibility manifest
recording the git SHA, interpreter, platform and a clean-tree flag.

---

## Architecture

```
                    ┌────────────────────────────────────────┐
                    │  orbit/   pure Python, no I/O, no web   │
   ┌────────────┐   │                                        │
   │ CLI        │──▶│  model/       graph, links, flows, SRLG │
   │ experiments│   │  generators/  grid ring waxman BA       │
   └─────┬──────┘   │  engine/      tick loop, allocator,     │
         │          │               metrics, failure injector │
         │          │  algorithms/  spf ecmp cspf orbit       │
         │          │  detect/      failure detector model    │
         ▼          └────────────────────────────────────────┘
   experiments/results/            ▲                ▲
   *.parquet + manifest            │                │
         │                    ┌────┴─────┐   ┌──────┴─────┐
         ▼                    │ worker   │   │ FastAPI    │
   experiments/figures/       │ (jobs)   │   │ app        │
                              └────┬─────┘   └──────┬─────┘
                                   │                │ REST + SSE
                                   └──▶ PostgreSQL ◀┘
                                                    │
                                           ┌────────┴────────┐
                                           │ React dashboard │
                                           └─────────────────┘
```

**The engine is a library, not a service.** Everything else — CLI, benchmark harness, API,
dashboard — is a caller. That is what makes a figure reproducible from one Python process
with no database and no HTTP server running.

---

## Quick start

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
```

Run one simulation:

```bash
python -m orbit.cli run --nodes 50 --flows 100 --algorithm orbit --failure critical_link
```

Run the committed benchmark grid and regenerate every figure and table:

```bash
make bench
make reproduce
```

Run the tests:

```bash
make check
```

The API and dashboard need PostgreSQL:

```bash
make migrate && make api        # http://127.0.0.1:8000/api/docs
make worker                     # separate terminal
npm --prefix web run dev        # http://127.0.0.1:5173
```

---

## Algorithms

| Name | What it is | Role |
|---|---|---|
| `spf-static` | Dijkstra once at t=0, never again | the floor — shows what no recovery looks like |
| `spf-reconverge` | recomputes on detected change, with flooding delay and SPF hold-down | what OSPF/IS-IS actually does |
| `ecmp` | splits demand over equal-cost paths (RFC 2992) | how much comes from plain load spreading |
| `cspf` | Dijkstra on links pruned by residual capacity | **the strong baseline**: capacity-aware, priority-blind |
| `orbit` | priority-ordered constrained restoration, plus protection, preemption and damping | the proposal |

`cspf` is the important one. It is capacity-aware but priority-blind, so the ORBIT-vs-CSPF
difference isolates the contribution of *priority awareness* specifically. Without it the
project could only claim "capacity-awareness helps", which is already well known.

---

## What makes the comparison credible

* **Paired seeds.** Every algorithm in a benchmark cell faces a bit-identical topology,
  traffic matrix and failure sequence, because the seed is derived before the algorithm is
  chosen. The design is therefore paired, and the statistics are Wilcoxon signed-rank.
* **One shared detector.** Failures are not instantly known. Every algorithm gets the same
  detector object with the same parameters, so recovery is never measured from an instant a
  baseline could not have known.
* **Both control modes.** Every baseline runs *distributed* (realistic IGP timing) and
  *centralised* (the same global view ORBIT gets). The first answers "better than practice",
  the second "better *algorithm*". Reporting only the first would be a strawman.
* **Effect size beside every p-value.** With 30 paired trials, trivial differences become
  "significant"; Cliff's delta is what says whether anyone should care.
* **Censoring is explicit.** A run that never recovers has no recovery time. It is reported
  as null and counted, never as zero or infinite.
* **Determinism is tested, not asserted.** Same seed ⇒ byte-identical output, checked by
  SHA-256 over a serialised run for all five algorithms.

---

## Limitations, stated plainly

* **Flow-level, not packet-level.** Sub-tick dynamics, TCP congestion control, microbursts
  and per-packet reordering are invisible. "Delivery ratio" here is rate-based.
* **Queueing delay is an approximation**, not a queueing-theory result. Applied identically
  to every algorithm, so it cannot bias a comparison — only absolute latency numbers.
* **Three of ORBIT's four mechanisms are inert** under the conditions tested. See below.
* **Only 60-node topologies are benchmarked.** Sizes 250 and 500 are supported by the code
  and are **not** claimed.
* **Synthetic topologies only.** No Internet Topology Zoo instance was used.
* **Distributed convergence is modelled from one vantage point**, not per-router.
* **The container and CI configuration is unverified** — no Docker on the development
  machine. Marked UNVERIFIED rather than implied to work.

---

## Findings that went against the project's own predictions

Reporting these is the point, not an embarrassment.

1. **Three of four mechanisms do nothing.** Disabling protection, preemption and damping
   together changes no measured outcome to four decimal places. Preemption never fires at
   all. The design document described ORBIT as "an integration of four mechanisms"; the
   measurement says it is one mechanism plus three that are currently unsupported.
2. **Recovery makes cascades worse.** Static SPF suffers less than half the cascade depth of
   every recovering algorithm and delivers the most traffic under cascade, because it never
   displaces traffic onto surviving links. Whether that is a real property or an artefact of
   the overload threshold is unknown and is the most interesting open question here.
3. **Time-to-restore could not be evaluated.** CRITICAL traffic recovers to ~80% of its
   pre-failure rate and stops, so the 95% criterion is unreachable and ~70% of runs censor.
   The capacity is genuinely gone; the hypothesis was measuring an incomplete recovery, not
   a slow one.
4. **Two bugs in ORBIT's placement path were found after the first benchmark run**, both by
   the dashboard and by a precondition guard rather than by the test suite. Both penalised
   ORBIT, and correcting them reversed one published conclusion. The results were retracted
   and regenerated. Regression tests now cover both.

---

## Repository layout

```
orbit/          the library: model, generators, engine, algorithms, detector, LP bound
experiments/    scenario specs, runner, statistics, figures, results
api/            FastAPI app, models, scoped repository, auth, worker
web/            React + TypeScript dashboard
tests/          unit, property, differential, determinism, security
docs/           requirements, architecture, simulation model, threat model, methodology
research/       literature review, methodology as executed, findings
deploy/         Dockerfiles, nginx, compose  (UNVERIFIED)
```

---

## Documentation

| Document | What it covers |
|---|---|
| [docs/01-requirements.md](docs/01-requirements.md) | requirements and non-goals |
| [docs/02-architecture.md](docs/02-architecture.md) | stack decisions, each with its argument |
| [docs/03-simulation-model.md](docs/03-simulation-model.md) | the simulation, routing and recovery design |
| [docs/04-threat-model.md](docs/04-threat-model.md) | assets, threats, controls |
| [docs/05-methodology.md](docs/05-methodology.md) | testing strategy and benchmark methodology |
| [docs/06-roadmap.md](docs/06-roadmap.md) | phases, risks, tradeoff log |
| [docs/learning-notes.md](docs/learning-notes.md) | WHAT/WHY/HOW/TRADEOFFS per component |
| [research/a8-findings.md](research/a8-findings.md) | **the results and hypothesis verdicts** |

## Licence

MIT. See [LICENSE](LICENSE).
