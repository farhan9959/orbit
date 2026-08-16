# 06 — Roadmap, Risks, Tradeoffs & Learning Plan

## 1. The single most important scheduling decision

**Finish the science before building the platform.**

The brief's phase list builds the engine, then the backend, then the database, then auth, then
the frontend, and benchmarks at Phase 15. That ordering has one fatal property: **you find out
in month five whether ORBIT actually beats the baselines.** If it doesn't, everything built on
top of it needs rethinking with no time left.

Reordered so the risky question is answered first:

| Tier | Contents | Why here |
|---|---|---|
| **A — the science** | model, engine, allocator, detector, 4 baselines, ORBIT controller, failure injection, CLI, experiment runner, analysis, tests, invariants | Produces the result the whole project rests on. Runs headless, needs no DB, no auth, no UI. |
| **B — the platform** | FastAPI, Postgres, worker, auth/authz, security, dashboard, live visualisation, observability, Docker, CI | Makes it demonstrable and shows web/systems/security engineering. Built *on top of* a validated engine. |
| **C — stretch** | Mininet cross-validation, ML congestion prediction, Grafana, public deployment | Only if A and B are genuinely done. |

If time runs out, **Tier A + a good README + the paper is still an excellent project.** Tier A
alone with real measured results beats Tier A+B half-finished with fabricated ones.

## 2. Phases (honest effort estimates at ~15 h/week)

### Tier A — weeks 1–10
| Phase | Deliverable | Done when | Est. |
|---|---|---|---|
| A0 | Repo, `pyproject.toml`, Makefile, CI skeleton, `.gitignore`, `.env.example`, LICENSE | `make lint test` passes on an empty suite | 2 days |
| A1 | `orbit/model` + validation + topology generators | Property test: generated topologies satisfy structural invariants | 4 days |
| A2 | Tick loop + **max-min allocator** + metrics recording | I-CAP, I-DEMAND, I-MAXMIN property tests green; determinism test green | 1.5 wk |
| A3 | B1 static SPF + B2 SPF-reconverge + **detector model** | Differential test vs NetworkX green; a link failure visibly blackholes then recovers in the metrics CSV | 1 wk |
| A4 | Failure injection (all types incl. SRLG + cascade) | Every failure type has a test; I-DOWN holds under all of them | 1 wk |
| A5 | B3 ECMP + B4 CSPF | Differential/brute-force tests green | 1 wk |
| A6 | **ORBIT controller** (M1–M4) | Ablation switches work; all invariants hold; events emitted | 2 wk |
| A7 | Experiment runner + analysis + statistics | `make bench` produces a results table with CIs and effect sizes | 1 wk |
| **A8** | **First real comparison: ORBIT vs 4 baselines, 100 nodes, 30 seeds** | **A committed results file and a plot** | 3 days |

> **A8 is the project's go/no-go gate.** After A8 you know whether the hypotheses hold. If ORBIT
> loses everywhere, you still have a real measurement study — the paper becomes "priority-aware
> recovery does not help under these conditions, and here is why," which is a legitimate and
> defensible outcome. Adjust the framing, not the data.

### Tier B — weeks 11–18
| Phase | Deliverable | Est. |
|---|---|---|
| B1 | FastAPI + Pydantic specs + Postgres + Alembic + repository layer with **scoped access** | 1.5 wk |
| B2 | Auth (Argon2id, sessions, CSRF) + RBAC + rate limits + the security test suite | 1.5 wk |
| B3 | Job table + worker + experiment execution via API | 1 wk |
| B4 | React dashboard: topology canvas, health encoding, controls, event log | 2 wk |
| B5 | SSE live sessions + delta/coalescing publisher | 1 wk |
| B6 | Observability: JSON logs, request IDs, `/healthz` `/readyz` `/metrics`, audit log | 4 days |
| B7 | Docker Compose, CI full pipeline, e2e tests | 1 wk |

### Finish — weeks 19–22
Literature review → methodology → full benchmark grid → results → paper → learning notes →
security audit → project audit → README + diagrams + demo video → resume bullets.

**Total ≈ 5 months at 15 h/week.** If that doesn't fit, cut Tier C entirely, then cut B4/B5 to a
static dashboard reading a completed run, then cut B1–B3 and ship Tier A + paper + CLI + a
matplotlib animation as the demo. Cut from the top down, never from the tests or the methodology.

## 3. Risk register

| # | Risk | Impact | Mitigation | Trigger to act |
|---|---|---|---|---|
| R1 | **ORBIT doesn't beat the baselines** | Project narrative collapses | Reframe as a measurement study; ablation identifies which mechanism (if any) helps; a null result honestly reported is defensible research | At A8 |
| R2 | **Strawman baseline** — the result is real but meaningless | Fatal to credibility; an interviewer will find it | Dual control modes (§B3 of methodology); baselines get equal tuning budget; document it prominently | Design-time; re-check at A8 |
| R3 | **Scope overrun** — the brief describes ~2 person-years | Nothing finishes | Tier A/B/C gates; cut top-down; Tier A alone is shippable | Week 10 checkpoint |
| R4 | Python too slow at 250–500 nodes | Can't claim the large sizes | Escape hatch ladder in `02-architecture.md` §8; worst case, claim only measured sizes | When a run exceeds 60 s |
| R5 | Non-determinism creeps in | Reproducibility claim fails | Determinism test in CI from day one, not retrofitted | Immediately |
| R6 | Simulator validity challenged ("it's not real") | Weakens the contribution | Threats to Validity written honestly; optional Mininet cross-validation; flow-level choice justified against the literature | Paper-writing |
| R7 | **Unconscious metric shopping** — trying metrics until one favours ORBIT | Invalidates the study | Metric list and scenario list committed *before* results exist; post-hoc additions labelled as such | Continuous |
| R8 | AI-generated code you can't explain | Fails the interview, which is the whole point | Definition-of-done in `CLAUDE.md` includes a learning-notes entry; never merge unexplained code | Every PR |
| R9 | Deployed demo abused as free compute | Cost, takedown | Public deploy is optional; caps + quotas + invite-only if deployed | Before any deploy |
| R10 | Time-to-restore has a subtle statistical bug (censoring) | Silently wrong headline number | I-CENSOR invariant + explicit censoring policy in the methodology | A7 |

## 4. Tradeoff log (decisions and what they cost)

| Decision | Gained | Given up | Why the trade is right |
|---|---|---|---|
| Flow-level, not packet-level | 10³× more runs → statistical power; determinism | TCP dynamics, sub-tick effects, per-packet realism | The claim is about rates and timing, not packets |
| Python, not Go/Rust | Velocity; one language for engine + analysis | 2–10× runtime; large-topology headroom | Correctness of methodology is the bottleneck, not CPU |
| Centralised controller | Simple, matches SDN practice, easy to reason about | Not distributed — a real-world limitation | Made explicit and measured via the dual-control-mode design |
| SSE, not WebSockets | Simpler auth, automatic reconnect, plain HTTP | No client→server push | Controls are ordinary POSTs; no need for a duplex channel |
| Postgres + Parquet split | Fast analytics, sane transactional data | Two stores to reason about | Millions of samples/run make a single store bad at one job |
| Cookie sessions, not JWT | SSE auth works; real logout; no token in localStorage | CSRF must be handled | CSRF is a solved problem; token revocation is not |
| Job table, not Celery/Redis | One fewer service, no broker failure mode | No fan-out, no retries-with-backoff for free | Queue holds tens of jobs on one node |
| Strict priority allocation | Priority means something measurable | LOW traffic can starve | The starvation is a *finding* to report, plus a WFQ variant to compare |
| Fractional factorial design | Feasible compute budget | No full interaction analysis | Reductions are declared up front, not discovered post-hoc |
| Skipping Kubernetes, microservices, message brokers, ML | Time; a defensible dependency list | A longer buzzword list | Every one of them would be a question you can't answer with "because a requirement needed it" |

## 5. What you need to learn, and when

Learn each item **in the week you build it**, not up front. Write the `docs/learning-notes.md`
entry the same day — WHAT / WHY / HOW / TRADEOFFS / HOW-I-EXPLAIN-IT-IN-AN-INTERVIEW.

| When | Topic | The specific thing to be able to explain |
|---|---|---|
| A1 | Graph representations, adjacency structures | Why adjacency lists over a matrix at these densities |
| A2 | **Max-min fairness**, progressive filling | Why a flow's rate is set by its bottleneck, and why the algorithm terminates |
| A2 | Determinism, seeding, floating-point | Why `random.Random(seed)` per subsystem beats a global seed |
| A3 | **Dijkstra**, link-state routing, OSPF | Why O(E log V), why a heap, and what OSPF adds that Dijkstra doesn't |
| A3 | Convergence, LSA flooding, SPF hold-down, BFD | Why real reconvergence takes hundreds of milliseconds to seconds |
| A4 | Fault models, SRLG, cascading failure | Why shared fate defeats naive backup paths |
| A5 | ECMP, flow hashing, CSPF, traffic engineering | Why ECMP splits per-flow and not per-packet |
| A6 | Multi-commodity flow, NP-hardness, LP relaxation, greedy heuristics | Why you can't just "solve it optimally" and what the optimality gap means |
| A6 | IP-FRR / LFA, RSVP-TE preemption, route damping | Which parts of ORBIT are prior art (all of them) and what the composition adds |
| A7 | Non-parametric statistics, paired designs, effect size, censoring | Why Wilcoxon signed-rank, why Cliff's delta, why censored runs can't be dropped |
| B1 | REST design, Pydantic validation, SQLAlchemy, migrations, transactions, indexes | Why `jsonb` for specs but relational for ownership |
| B2 | Argon2id, sessions vs tokens, CSRF, OWASP Top 10, IDOR | Why the ownership check lives in the repository layer |
| B3 | Job queues, `FOR UPDATE SKIP LOCKED`, idempotency, timeouts | Why the expensive operation returns 202, not 200 |
| B4 | Canvas rendering, layout algorithms, React state | Why coordinates are stored in the topology spec |
| B5 | SSE, backpressure, delta encoding, coalescing | What happens when the client is slower than the producer |
| B6 | Structured logging, correlation IDs, RED/USE metrics, health vs readiness | Why `/healthz` must not check the database |
| B7 | Docker layers, non-root, least privilege, CI gating | Why benchmarks don't run in CI |

## 6. Immediate next steps

1. Create the repo on your laptop with the structure in `03-simulation-model.md` §8; commit these
   Phase 1 docs as the first commit. **Architecture-first is itself a signal in the commit history.**
2. Open it in Claude Code with `CLAUDE.md` at the root.
3. Build **A1 + A2** — the model and the allocator. That is the piece with the most subtle
   correctness content and the least glamour, and it is where the project earns its credibility.
4. Do not write a line of React until A8 has produced a committed results file.
