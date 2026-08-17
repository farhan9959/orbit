# Final project audit

Requirement-by-requirement status. **Implemented** means there is code and a test. **UNVERIFIED**
means the code exists but nothing proves it works. **Not done** means exactly that.

Measured at the final commit. 341 Python tests, 18 TypeScript tests, 92% coverage on `orbit/`.

---

## Tier A — the science

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| F1 | Directed graph of nodes and links with capacity, delay, loss, state | Implemented | `orbit/model/network.py`, `tests/test_model.py` |
| F2 | Seeded grid / ring / Waxman / Barabási–Albert generators | Implemented | `orbit/generators/`, 37 tests |
| F2b | Load topologies from a spec file | **Not done** | needs the YAML/Pydantic scenario loader |
| F3 | Sizes 10–500 | Partial | 10–100 tested; **250 and 500 not benchmarked and not claimed** |
| F4 | Flows with src, dst, demand, start, duration, priority | Implemented | `orbit/model/traffic.py` |
| F5 | Persist node coordinates for stable visualisation | Implemented differently | coordinates regenerate from the seed; `experiments/export_web.py` |
| F6 | Shared-risk link groups | Implemented | `srlg` on nodes and links, SRLG_DOWN failure, `tests/test_failures.py` |
| F7 | Fixed timestep; per-step allocation, loss, latency | Implemented | `orbit/engine/simulation.py`, 46 tests |
| F8 | Strict priority between classes, max-min within | Implemented | `orbit/engine/allocator.py`; I-MAXMIN property test |
| F9 | Identical output for identical seed | Implemented | `tests/test_determinism.py`, SHA-256 over a serialised run |
| F10 | Per-tick metrics to disk in a columnar format plus a run summary | Implemented | Parquet + CSV + manifest via `experiments/runner.py` |
| F11 | Step, pause, reset, run headless | Implemented | `Simulation.step/run/reset/measure` |
| F12 | Inject node / link / SRLG / degrade / latency / loss / surge / cascade | Implemented | `orbit/engine/failures.py`, 27 tests |
| F13 | Scripted and interactive injection | Implemented | `FailureSchedule`; interactive via the live-session API |
| F14 | Targeted and seeded-random selection | Implemented | link/node betweenness, `random_nodes`, `random_links` |
| F15 | Explicit detection latency applied identically to every algorithm | Implemented | `orbit/detect/detector.py` |
| F16 | B1 static SPF | Implemented | `orbit/algorithms/spf.py` |
| F17 | B2 SPF with reconvergence, flooding delay, hold-down | Implemented | detector models the timing |
| F18 | B3 ECMP | Implemented | required real multipath in the allocator |
| F19 | B4 CSPF on residual capacity | Implemented | `orbit/algorithms/cspf.py` |
| F20 | ORBIT controller, M1–M4 | Implemented | **ablation shows M1, M3, M4 are inert** |
| F21 | Every control decision recorded as a structured event | Implemented | `orbit/events.py`, emitted by every algorithm |
| F22 | Optimality gap against an LP on small topologies | Partial | `orbit/optimal.py` implemented and validated; **not swept** |
| F23 | Declare an experiment as a spec and run it headless | Implemented | `orbit/scenarios.py`, `orbit/cli.py`, `experiments/specs/` |
| F24 | Paired seeds: identical world for every algorithm | Implemented | `seed_key`; asserted by test |
| F25 | PDR per class, throughput, latency, recovery, churn, preemption, control time | Implemented | `RunRecord` carries all of them |
| F26 | Plots and tables from raw data in one command | Implemented | `make reproduce` |
| F27 | Reproducibility manifest in every results artifact | Implemented | git SHA, dirty flag, platform, packages |

## Tier B — the platform

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| F28 | HTTP API for topologies, scenarios, experiments, runs | Implemented | 19 endpoints |
| F29 | Live session API: start/pause/step/reset, inject, switch algorithm | Partial | start/pause/step/reset implemented; **inject and switch-algorithm not exposed** |
| F30 | Server→client stream of state deltas | Implemented | SSE with coalescing |
| F31 | Dashboard: topology, health, routes, metrics, event log, controls, side-by-side | Partial | all present except failure controls and algorithm switching; **reads static data, not the live API** |
| F32 | Persist users, topologies, scenarios, experiments, runs, events, audit logs | Implemented | 9 tables, Alembic migration |
| F33 | Authentication and server-side role/ownership authorization | Implemented | 25 security tests |
| F34 | Health, readiness, metrics endpoints; structured logs with correlation IDs | Implemented | `/healthz` deliberately checks nothing but the process |
| F35 | Learning notes for every major component | Implemented | `docs/learning-notes.md`, `learning-notes-a3-a8.md` |
| F36 | `research/{literature-review,methodology,results,paper}.md` | Partial | methodology, results, findings and paper written; **literature review is a skeleton** |
| F37 | README with architecture, quick start, algorithms, real results, limitations | Implemented | `README.md` |
| F38 | Security audit and project audit with evidence per item | Implemented | this file and `docs/final-security-audit.md` |

## Non-functional

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| N1 | Runs on a laptop, ≤ 8 GB, no GPU | Implemented | ~9,000-run grids complete in minutes on 10 workers |
| N2 | 100-node / 200-flow / 60 s run under 30 s | Implemented | measured ~4 s at that size |
| N3 | Identical seed ⇒ identical metrics | Implemented | hash test; also confirmed across independent process pools |
| N4 | Control recomputation < 100 ms at 100 nodes | Implemented | median 0.058 s per **run**, not per event; per-event is well below |
| N5 | No secret material in the repository | Implemented | `.env` ignored from the first commit; gitleaks configured |
| N6 | Every state-changing endpoint enforces authn + authz server-side | Implemented | scoped repository, 25 tests |
| N7 | Expensive operations bounded server-side | Implemented | Pydantic caps, quotas, rate limits |
| N8 | ≥ 80% coverage on engine and algorithms | Implemented | **92%** on `orbit/` |
| N9 | `docker compose up` works on a clean machine | **UNVERIFIED** | no Docker available; `Dockerfile.web` digest is a placeholder that will fail |
| N10 | Dashboard keyboard-navigable, non-colour-only status, WCAG AA | Partial | glyph/dash/text encoding implemented; **no axe run, no keyboard audit** |

---

## Honest summary

**Complete and verified:** the engine, the four baselines, the controller, failure injection,
the experiment harness, the statistics, the API, auth, the worker, observability, and the
dashboard as a static viewer.

**The five real gaps**, in the order they matter:

1. **The literature review is not done.** It gates every positioning and novelty claim. The
   paper says so explicitly rather than working around it.
2. **Docker and CI have never executed.** Everything in `deploy/` and `.github/` is written
   and unverified, and one pinned digest is known-bad.
3. **The dashboard and the live API do not meet.** B4 reads committed JSON; B5's SSE endpoint
   has no consumer. Two working halves, unconnected.
4. **Three of ORBIT's four mechanisms are unsupported** by measurement and should either be
   shown to matter or removed.
5. **Sizes 250 and 500 are unbenchmarked**, so the scale claim in the requirements is not made.

**What went wrong and was caught:** two defects in the controller's placement path survived
300 passing tests and were found by the dashboard and by a Dijkstra precondition guard. Both
penalised ORBIT; correcting them reversed one published conclusion and forced a retraction and
regeneration of the results. The suite now has regression tests for both. The episode is the
strongest argument in this project for validating preconditions and for looking at your data,
and it is recorded rather than smoothed over.
