# Final project audit

Requirement-by-requirement status. The status words are used strictly:

* **Verified** — there is code, a test or a measurement, and it has been executed on this
  machine with the output recorded.
* **Implemented** — there is code and a test, but the claim rests on the test rather than on a
  measurement.
* **UNVERIFIED** — the code exists and nothing has run it.
* **Not done** — exactly that.

Measured at the final commit: **378 Python tests, 30 TypeScript tests, 8 Playwright browser
tests including two axe scans, 93.18% coverage on the engine and algorithms.**

---

## Tier A — the science

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| F1 | Directed graph of nodes and links with capacity, delay, loss, state | Verified | `orbit/model/network.py`, `tests/test_model.py` |
| F2 | Seeded grid / ring / Waxman / Barabási–Albert generators | Verified | `orbit/generators/`, 39 tests |
| F2b | Load topologies from a spec file | **Verified** | `orbit/topospec.py`, 20 tests; `orbit topology --file` and `orbit run --topology-file` both exercised end to end on `experiments/topologies/abilene.yaml` |
| F3 | Sizes 10–500 | **Verified** | `a10-scale`, 2,400 runs at 50/100/250/500. Required a Waxman density correction first — see below |
| F4 | Flows with src, dst, demand, start, duration, priority | Verified | `orbit/model/traffic.py` |
| F5 | Persist node coordinates for stable visualisation | Implemented differently | coordinates regenerate from the seed; live view lays out on a circle |
| F6 | Shared-risk link groups | Verified | `srlg` on nodes and links, SRLG_DOWN failure, `tests/test_failures.py` |
| F7 | Fixed timestep; per-step allocation, loss, latency | Verified | `orbit/engine/simulation.py`, 46 tests |
| F8 | Strict priority between classes, max-min within | Verified | `orbit/engine/allocator.py`; I-MAXMIN property test |
| F9 | Identical output for identical seed | Verified | `tests/test_determinism.py`, SHA-256 over a serialised run |
| F10 | Per-tick metrics to disk in a columnar format plus a run summary | Verified | Parquet + CSV + manifest, 11 result sets |
| F11 | Step, pause, reset, run headless | Verified | `Simulation.step/run/reset/measure` |
| F12 | Inject node / link / SRLG / degrade / latency / loss / surge / cascade | Verified | `orbit/engine/failures.py`, 27 tests |
| F13 | Scripted and interactive injection | **Verified** | `FailureSchedule.inject`; `POST /sessions/{id}/inject` with 13 API tests |
| F14 | Targeted and seeded-random selection | Verified | betweenness, `random_nodes`, `random_links` |
| F15 | Explicit detection latency applied identically to every algorithm | Verified | `orbit/detect/detector.py` |
| F16–F19 | B1 static SPF, B2 reconverging SPF, B3 ECMP, B4 CSPF | Verified | `orbit/algorithms/`, all four in every grid |
| F20 | ORBIT controller, M1–M4 | **Verified, and three mechanisms rejected** | `a11-mechanisms`, 6,480 runs: M1/M3/M4 fire (16% and 47% of runs) and win 0 of 36 cells. Removed from the claim; code retained so the result stays reproducible |
| F21 | Every control decision recorded as a structured event | Verified | `orbit/events.py`; `backup_activations` added to separate M1 firing from M2 |
| F22 | Optimality gap against an LP on small topologies | **Verified** | `a10-optimality`, 13,200 placements; ORBIT median gap 1.40%, no algorithm exceeds the bound |
| F23 | Declare an experiment as a spec and run it headless | Verified | `orbit/scenarios.py`, `orbit/cli.py`, `experiments/specs/` |
| F24 | Paired seeds: identical world for every algorithm | Verified | `seed_key`; asserted by test |
| F25 | PDR per class, throughput, latency, recovery, churn, preemption, control time | Verified | `RunRecord` carries all of them |
| F26 | Plots and tables from raw data in one command | Verified | `make reproduce`, now including the scale, mechanism and optimality figures |
| F27 | Reproducibility manifest in every results artifact | Verified | git SHA, dirty flag, platform, packages; **all 11 result sets record `dirty: false`** |

## Tier B — the platform

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| F28 | HTTP API for topologies, scenarios, experiments, runs | Verified | 21 endpoints |
| F29 | Live session API: start/pause/step/reset, inject, switch algorithm | **Verified** | all six; `Simulation.switch_algorithm` carries topology, traffic, failures and tick across the switch |
| F30 | Server→client stream of state deltas | Verified | SSE with coalescing; deltas are positional against the snapshot so the replay canvas is reused |
| F31 | Dashboard: topology, health, routes, metrics, event log, controls, side-by-side | **Verified** | replay and live modes; 8 Playwright tests |
| F32 | Persist users, topologies, scenarios, experiments, runs, events, audit logs | Verified | 9 tables, Alembic migration |
| F33 | Authentication and server-side role/ownership authorization | Verified | 25 security tests plus 4 new authz/CSRF tests on the live routes |
| F34 | Health, readiness, metrics endpoints; structured logs with correlation IDs | Verified | `/healthz` deliberately checks nothing but the process |
| F35 | Learning notes for every major component | Implemented | `docs/learning-notes.md`, `learning-notes-a3-a8.md` |
| F36 | `research/{literature-review,methodology,results,paper}.md` | **Verified** | literature review written from the primary sources; paper §6 rewritten from it |
| F37 | README with architecture, quick start, algorithms, real results, limitations | Verified | `README.md` |
| F38 | Security audit and project audit with evidence per item | Verified | this file and `docs/final-security-audit.md` |

## Non-functional

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| N1 | Runs on a laptop, ≤ 8 GB, no GPU | Verified | 6,480-run grid on 16 workers; peak ~50 MB per worker |
| N2 | 100-node / 200-flow / 60 s run under 30 s | **Verified** | measured 5.1 s (CSPF) and 6.0 s (ORBIT) |
| N3 | Identical seed ⇒ identical metrics | Verified | hash test; confirmed across independent process pools |
| N4 | Control recomputation < 100 ms at 100 nodes | **Verified** | 65.7 ms Waxman, 72.7 ms scale-free, single-threaded. Stops holding between 100 and 250 nodes, and the curve says so |
| N5 | No secret material in the repository | Implemented | `.env` ignored from the first commit; gitleaks configured but never executed |
| N6 | Every state-changing endpoint enforces authn + authz server-side | Verified | scoped repository, 29 tests |
| N7 | Expensive operations bounded server-side | Verified | Pydantic caps, quotas, rate limits |
| N8 | ≥ 80% coverage on engine and algorithms | Verified | **93.18%**, enforced by `--cov-fail-under=80` |
| N9 | `docker compose up` works on a clean machine | **Verified** | both images built; `docker compose up` on a wiped volume reaches a serving stack in ~20 s, Alembic migrations run, registration returns 201, `/healthz` answers through nginx. Three defects found and fixed in the process — see below |
| N10 | Dashboard keyboard-navigable, non-colour-only status, WCAG AA | **Verified** | axe found and we fixed a real `scrollable-region-focusable` failure; two axe scans and a keyboard-traversal test now run in CI |

---

## What changed in this pass, and what it cost

**Five gaps were listed as outstanding. All five are closed, and closing them changed
conclusions rather than confirming them.**

1. **The literature review.** Done from the primary sources — MIRA, B4, SWAN, FFC, YATES and
   the RFCs. It **removed** the last available mechanism claim: FFC §5.1 describes ORBIT's
   surviving mechanism as practice already established by B4 and SWAN. It also found YATES, an
   open TE harness the skeleton reading list had missed, which is the closest existing artefact
   and the reason the contribution is stated as narrowly as it now is.
2. **Docker and CI.** The web image's node digest returned **404** from the registry — a
   placeholder that could never have built. Replaced with a verified digest, nginx pinned too.
   CI had two defects that would have failed on first run (`npm run test` with no such script;
   `eslint web` from a directory with no config). Docker then became available and the images
   were actually built, which found **three more defects that digest-checking could not have**:

   * **No `.dockerignore` existed.** The build context was the entire repository — a 643 MB
     `.venv`, `node_modules`, `.git` and the results Parquet — all uploaded to the daemon
     before it read a Dockerfile.
   * **The web container exited 1 on every start.** `cap_drop: [ALL]` removes `CHOWN`, and
     nginx's entrypoint chowns its cache directories before dropping to uid 101. The
     container never served a byte. Fixed by adding back the four capabilities the startup
     sequence needs and no more.
   * **The worker was permanently unhealthy.** It shares the API's Dockerfile and inherits its
     `HEALTHCHECK`, which curls `/healthz` — but the worker runs `python -m api.worker` and
     serves no HTTP, so the probe could never pass.

   This is the clearest vindication in the project of the rule that verified means executed.
   Every one of the three was invisible to static inspection, and the digest fix — the one
   thing that *was* caught statically — was necessary but nowhere near sufficient.
3. **Dashboard and live API.** Connected. The delta format changed to positional arrays so the
   live view reuses the replay canvas; `inject` and `switch-algorithm` are exposed with
   server-side target selection.
4. **M1, M3, M4.** Not merely unsupported — measured firing, and measured making no
   difference, across 36 conditions chosen to favour them. Removed from the claim.
5. **Sizes 250 and 500.** Benchmarked, after fixing two methodology defects that would have
   made the sweep meaningless.

**Three mistakes this pass caught in the project's own prior claims:**

* `research/a8-findings.md` said preemption "never fires". It fires in 47% of runs once ring
  topologies are included. The median was zero; that is a different statement.
* N4 looked like a fivefold failure when read off the parallel grid's `control_seconds`. It is
  a contention artefact: 18 workers on 20 cores inflate wall-clock control timings roughly
  tenfold. Measured properly, N4 passes. **The temptation here was to report the failure and
  look rigorous; measuring first was the correct move and it went the other way.**
* N10 claimed keyboard navigability with no audit behind it. The first axe run found a real
  WCAG 2.1 AA violation.

## Remaining honest gaps

1. **CI has never run.** No git remote. Every job's commands have now been executed locally,
   including the container job, which was the last one that could not be.
2. **No real ISP topology.** The loader (F2b) now makes one loadable, and
   `experiments/topologies/abilene.yaml` is a shaped example with invented capacities, clearly
   labelled as such. The Internet Topology Zoo remains unused.
3. **No optimality bound above 15 nodes.** The LP has |F| × |E| columns.
4. **The cascade result rests on one rule form.** 168 parameter cells rule out sensitivity to
   its threshold and dwell time, not to its shape.
5. **Waxman at scale is a corrected family, not the textbook one.** Its mean degree is pinned
   at 4; results at 500 nodes describe a sparse graph.
5. **gitleaks has never run**, so N5 rests on `.gitignore` and inspection.
6. **The compose stack was verified on Docker Desktop for Windows**, not on the
   `ubuntu-latest` runner the CI job targets. The images are `linux/amd64` either way, but
   the runner path itself is still unexercised.

## Honest summary

The engine, baselines, controller, failure injection, harness, statistics, API, auth, worker,
observability and dashboard are complete and verified. The contribution claim is smaller than
when this pass began: three of four mechanisms are gone, and the survivor is prior art. What
is left is an artefact nobody else in this literature published, and a set of measurements —
four of them negative — that a production evaluation had no incentive to produce.

The episode worth remembering is still the one from A8: two defects in the placement path
survived 300 passing tests and were found by looking at a dashboard and by a precondition
guard. This pass added two more of the same kind — a benchmark that measured density instead
of size, and a timing artefact that would have manufactured a requirement failure. Both were
caught by measuring the thing directly instead of reading it off a table.
