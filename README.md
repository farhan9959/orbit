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

**The advantage holds and widens with size.** Over 50 to 500 nodes with mean degree held
constant, ORBIT's CRITICAL delivery stays at 0.98–1.00 while CSPF falls from 0.998 to 0.966:
**13 wins, 0 losses across 16 cells**. Against a splittable LP relaxation on small topologies
its median optimality gap is **1.40%**, the best of the five algorithms over 13,200 placements
in which no algorithm exceeds the bound.

Two of the project's own hypotheses were **not** supported, three of its four mechanisms do
nothing, and the one that works is not novel — FFC (SIGCOMM 2014) calls it existing practice,
citing B4 and SWAN. All of it is reported in full in
[`research/a8-findings.md`](research/a8-findings.md) and
[`research/literature-review.md`](research/literature-review.md).

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
* **Three of ORBIT's four mechanisms do nothing**, measured in the conditions built to make
  them act. See below.
* **The surviving mechanism is not novel.** Priority-ordered computation on residual capacity
  is described as existing practice by FFC (SIGCOMM 2014), citing B4 and SWAN. The
  contribution is the harness and the measurements, not the algorithm.
* **Synthetic topologies only.** Benchmarked to 500 nodes, but no Internet Topology Zoo
  instance was used. The Waxman family needed a density correction to be scalable at all — its
  mean degree runs 1.8 at 10 nodes to 44 at 500 — so scale results describe a sparse graph.
* **The optimality bound is small-topology only**, 9 to 15 nodes. Nothing bounds optimality at
  100 nodes or above.
* **Distributed convergence is modelled from one vantage point**, not per-router.
* **Docker has never been built.** The development machine has no Docker. Base image digests
  are verified against the registry and CI has a job that builds and starts the images, but
  that job has not run. Marked UNVERIFIED rather than implied to work.
* **CI has never executed.** Every step was run locally with the same arguments except the
  container job and gitleaks; the workflow itself has not run, because there is no remote.

---

## Findings that went against the project's own predictions

Reporting these is the point, not an embarrassment.

1. **Three of four mechanisms fire and change nothing.** A 6,480-run grid put protection,
   preemption and damping into the conditions designed to make them act — ring topologies,
   loads to 2.0, cascading failures. They acted: preemption fired in 47% of runs, protection
   in 16%. The paired test returns **0 wins and 0 losses across all 36 conditions** on every
   delivery metric, median difference exactly zero. All three are removed from the
   contribution claim; the code stays so the negative result remains reproducible.
2. **The one surviving mechanism is not novel either.** The literature review, done from the
   primary sources, found FFC §5.1 describing priority-ordered computation on residual
   capacity as practice already established by B4 and SWAN. The rejected utilisation ceiling
   is SWAN's scratch capacity under another name. No mechanism claim is available; the
   contribution is the harness and the measurements.
3. **The scale sweep could not be run as pre-registered.** Waxman's mean degree grows from 1.8
   at 10 nodes to 44 at 500 at fixed parameters, and per-flow demand then reaches 605 Mbps
   against 100 Mbps links, collapsing every algorithm onto the same floor at PDR 0.10. Size
   and density had to be separated before the sweep measured anything.
4. **A contention artefact nearly produced a false requirement failure.** The parallel grid's
   own control timings imply 460 ms per recompute at 100 nodes, which would miss N4 fivefold.
   Measured single-threaded it is 66 ms. Absolute timings now come from a dedicated
   single-threaded driver.
5. **The accessibility claim was wrong.** N10 asserted keyboard navigability on the strength
   of glyph and dash encoding. The first axe run found a real WCAG 2.1 AA failure: the event
   log was a scrollable region with no keyboard access. Fixed, and now enforced in CI.
6. **Time-to-restore could not be evaluated.** CRITICAL traffic recovers to ~80% of its
   pre-failure rate and stops, so the 95% criterion is unreachable and ~70% of runs censor.
   The capacity is genuinely gone; the hypothesis was measuring an incomplete recovery, not
   a slow one.
7. **Under cascading overload, recovery is harmful.** Static SPF suffers less than half the
   cascade depth of every recovering algorithm and delivers the most traffic, because it never
   displaces traffic onto surviving links. A 25,200-run sweep over the cascade threshold and
   dwell time confirms this in **168 of 168 parameter cells** with zero reversals.
8. **The cascade is avoidable, but not for the reason it appears.** A controller reserving ~5%
   link headroom eliminates it entirely and delivers 3.7x static SPF's traffic — yet controls
   show roughly 60% of that gain comes from *declining unplaceable flows*, not from the
   headroom. The best-effort fallback added to fix an unfair asymmetry turns out to be
   actively harmful in this regime.
9. **Two bugs in ORBIT's placement path were found after the first benchmark run**, both by
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
research/       literature review, methodology as executed, findings, paper
deploy/         Dockerfiles, nginx, compose  (digests verified; never built)
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
| [research/paper.md](research/paper.md) | the study written up as a paper draft |
| [research/methodology.md](research/methodology.md) | methodology as executed |
| [docs/final-audit.md](docs/final-audit.md) | requirement-by-requirement status |
| [docs/final-security-audit.md](docs/final-security-audit.md) | every control mapped to its test |

## Licence

MIT. See [LICENSE](LICENSE).
