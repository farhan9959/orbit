# 02 — Architecture

Status: Phase 1 draft. Nothing here is implemented yet.

## 1. Shape of the system

The central decision: **the engine is a library, not a service.** Everything else — CLI,
benchmark harness, API, dashboard — is a caller.

```
                    ┌──────────────────────────────────────┐
                    │  orbit/  (pure Python, no I/O, no web) │
                    │                                        │
   ┌────────────┐   │  model/     graph, links, flows, SRLG  │
   │ CLI        │──▶│  engine/    tick loop, allocator,      │
   │ (Tier A)   │   │             metrics, failure injector  │
   └────────────┘   │  algorithms/ spf, ecmp, cspf, orbit    │
                    │  detect/    failure detector model     │
   ┌────────────┐   └──────────────────────────────────────┘
   │ bench      │──▶            ▲                ▲
   │ runner     │               │                │
   └─────┬──────┘               │                │
         │                 ┌────┴─────┐    ┌─────┴──────┐
         ▼                 │ worker   │    │ FastAPI    │
   experiments/results/    │ (runs    │    │ app        │
   *.parquet + *.json      │  jobs)   │    │ (Tier B)   │
         │                 └────┬─────┘    └─────┬──────┘
         ▼                      │                │ REST + SSE
   analysis/ → figures/         └──▶ PostgreSQL ◀┘
                                                 │
                                        ┌────────┴────────┐
                                        │ React dashboard │
                                        └─────────────────┘
```

**Why this way.** The research result is produced by the CLI + benchmark runner. If the engine
depended on the web layer, every experiment would need a database and an HTTP server running,
CI would be slow, and reproducing a figure would require the whole stack. Keeping `orbit/` free
of I/O also makes it trivially testable and makes determinism achievable.

**Interview answer:** "The simulation core has no knowledge of HTTP, the database, or the UI.
That's what makes the experiments reproducible from a single Python process and makes the
property tests possible — I can construct a topology in memory, run 10,000 ticks, and assert
invariants without any infrastructure."

## 2. Technology stack, with the argument for each

| Layer | Choice | Why this, and what was rejected |
|-------|--------|--------------------------------|
| Engine + algorithms | **Python 3.12**, stdlib `heapq`/`dataclasses`, NumPy for the allocator | The engine is graph algorithms plus a numerical allocator. Python gets it written and tested fastest, and the analysis half of the project (pandas, scipy stats, matplotlib) lives in the same language. Rejected Go/Rust: 2–10× faster engine, but a second language, a second toolchain, and no scientific stack — the bottleneck in this project is correctness of the *methodology*, not CPU. **Named risk + escape hatch in §8.** |
| Reference oracle | **NetworkX** (tests only) | Differential-testing our Dijkstra/ECMP against a mature implementation is worth one dev dependency. Not imported by production code. |
| Experiment storage | **Parquet** (per-tick samples) + **JSON** (run summary + manifest) | A 500-node run produces millions of rows. Parquet is columnar, compressed, and reads straight into pandas. Rejected: putting samples in Postgres (slow writes, no analytical benefit); CSV (10× the size, no types). |
| API | **FastAPI + Pydantic v2 + Uvicorn** | The API's main job is validating user-supplied simulation specs. Pydantic gives schema validation with bounds at the trust boundary and generates the OpenAPI doc for free — that is exactly the requirement, not a framework preference. |
| Live updates | **SSE** (`text/event-stream`) | Traffic is one-directional: server → browser. Controls are ordinary POSTs. SSE is HTTP, reconnects automatically, and needs no extra protocol handling or sticky-session concerns. Rejected WebSockets: bidirectional capability we don't need, plus its own auth story. Documented tradeoff: SSE can't push binary and is capped per-domain on HTTP/1.1 — irrelevant here. |
| Job execution | **Postgres-backed job table + a single worker process** (`SELECT ... FOR UPDATE SKIP LOCKED`) | Benchmarks take minutes; they cannot run inside a request. Rejected Celery/Redis/RabbitMQ: a broker, a result backend, and a new failure mode, for a queue that will hold tens of jobs. This is a ~60-line worker. |
| Database | **PostgreSQL 16** + SQLAlchemy 2 + Alembic | Genuinely relational data (ownership, foreign keys, audit trail) plus `jsonb` for specs. Rejected SQLite: fine for local single-user, but the multi-user/deployment story and concurrent worker+API access is cleaner in Postgres, and supporting both doubles the migration and testing surface for no gain. |
| Frontend | **React 18 + TypeScript (strict) + Vite + Tailwind** | Mainstream, hireable, fast build. Rejected a heavier meta-framework: no SSR requirement, no routing complexity, no SEO. |
| Topology rendering | **HTML Canvas 2D**, custom renderer; layout precomputed once with `d3-force` and stored in the topology spec | SVG with 500 nodes + 1500 edges re-rendering 4×/s will drop frames. Canvas draws thousands of primitives cheaply. Storing coordinates means the same topology looks identical in every run, which is what makes side-by-side baseline-vs-ORBIT comparison legible. Rejected Cytoscape/vis.js: heavy, and the interesting part (health/route/utilisation encoding) would be fought against, not helped. |
| Charts | **Recharts** or **uPlot** | Decide at Phase 11 based on point counts. uPlot if time-series get long. |
| Metrics | **prometheus-client** | Writing the exposition format by hand would be pointless. Grafana is **optional** — see §6. |
| Password hashing | **argon2-cffi** (Argon2id) | Memory-hard, current OWASP recommendation. |
| Containers | **Docker Compose**, multi-stage builds, non-root | Reproducible local setup. **No Kubernetes** — there is no requirement it would satisfy. |
| CI | **GitHub Actions** | Where the repo is. |

### The stack rule
Every dependency added after this point must answer: *what requirement fails without it, and how
many lines does it save?* If the answer is "it looks good on a CV," it does not go in. A short,
justified dependency list is itself a signal of engineering judgment.

## 3. Data model (Tier B)

```sql
users        (id uuid pk, email citext unique, password_hash text, role text
              check (role in ('ADMIN','USER','VIEWER')), created_at, last_login_at)

topologies   (id uuid pk, owner_id uuid fk→users on delete cascade, name text,
              spec jsonb, node_count int, link_count int, seed bigint,
              created_at, updated_at)

scenarios    (id uuid pk, owner_id uuid fk→users, name text, spec jsonb, created_at)
             -- traffic matrix + failure schedule

experiments  (id uuid pk, owner_id uuid fk→users, topology_id fk, scenario_id fk,
              algorithms text[], trials int, base_seed bigint,
              status text check (status in ('QUEUED','RUNNING','DONE','FAILED','CANCELLED')),
              created_at, started_at, finished_at)

runs         (id uuid pk, experiment_id fk→experiments on delete cascade,
              algorithm text, trial int, seed bigint, status text,
              summary jsonb,          -- PDR, latency percentiles, recovery time, churn
              artifact_path text,     -- relative path under ARTIFACT_ROOT; never client-supplied
              manifest jsonb,         -- git sha, versions, host, wall clock
              started_at, finished_at)

events       (id bigserial pk, run_id uuid fk→runs on delete cascade, tick int,
              type text, payload jsonb, created_at)
             -- FAILURE_INJECTED, FAILURE_DETECTED, FLOW_REROUTED, FLOW_PREEMPTED,
             -- FLOW_BLACKHOLED, RECONVERGED

audit_logs   (id bigserial pk, actor_id uuid null, action text, object_type text,
              object_id uuid null, ip inet, user_agent text, metadata jsonb, at timestamptz)

jobs         (id uuid pk, experiment_id fk, state text, attempts int,
              locked_at, locked_by text, error text)
```

Indexes: `runs(experiment_id)`, `events(run_id, tick)`, `topologies(owner_id)`,
`experiments(owner_id, created_at desc)`, `audit_logs(actor_id, at desc)`,
partial index `jobs(state) where state = 'QUEUED'`.

**Decisions worth defending:**
- **UUIDv4 primary keys**, not sequential integers — sequential IDs make object-level
  authorization failures trivially exploitable by enumeration. (Defence in depth: the authz
  check is still mandatory, see `docs/04-threat-model.md`.)
- **`events` is bounded, `samples` is not.** Control-plane events number in the hundreds per run
  and are queried transactionally with the run → Postgres. Per-tick per-flow samples number in
  the millions and are only ever scanned analytically → Parquet on disk. Mixing the two into one
  store would make one of the two access patterns bad.
- **`ON DELETE CASCADE` from experiments to runs to events**, so deleting an experiment cannot
  leave orphans; artifact files are deleted in the same transaction's `after-commit` hook.
- **`spec jsonb` rather than fully normalised nodes/links tables.** A topology is read and
  written as a whole, always; normalising it into `nodes`/`links` tables would mean hundreds of
  inserts per topology and joins on every read for zero query benefit. If per-node queries ever
  become a requirement, that's the trigger to normalise — not before.

## 4. API design (Tier B)

Base: `/api/v1`. JSON. Cookie session auth. CSRF token required on all non-GET.

```
POST   /auth/register                 201  (rate limited)
POST   /auth/login                    200  sets session cookie, rotates session id
POST   /auth/logout                   204
GET    /auth/me                       200

GET    /topologies                    200  owner-scoped list, paginated
POST   /topologies                    201  body: TopologySpec (validated, bounded)
GET    /topologies/{id}               200  403 if not owner and not ADMIN
PUT    /topologies/{id}               200
DELETE /topologies/{id}               204

GET    /scenarios  POST /scenarios  GET|PUT|DELETE /scenarios/{id}

POST   /experiments                   202  enqueues; body: topology, scenario, algorithms, trials
GET    /experiments                   200
GET    /experiments/{id}              200  includes run statuses
DELETE /experiments/{id}              204  cancels if running
GET    /experiments/{id}/results      200  aggregate table
GET    /experiments/{id}/results.csv  200  export

GET    /runs/{id}                     200
GET    /runs/{id}/events              200  paginated
GET    /runs/{id}/samples             200  downsampled series for charts

POST   /sessions                      201  interactive live simulation
POST   /sessions/{id}/control         200  {action: start|pause|step|reset, speed}
POST   /sessions/{id}/algorithm       200  {algorithm}
POST   /sessions/{id}/inject          200  {failure spec}
POST   /sessions/{id}/restore         200  {element ids}
GET    /sessions/{id}/stream          200  text/event-stream

GET    /healthz   /readyz   /metrics       unauthenticated, but /metrics bound to internal only
```

**Design notes:**
- `POST /experiments` returns **202 Accepted** with a resource to poll, not 200 with results.
  Benchmarks take minutes; holding an HTTP connection open for that is how you get gateway
  timeouts and no cancellation story.
- Live sessions are separate from experiments. A live session is for demonstration and is
  throttled and capped; an experiment is for measurement and is queued. Conflating them would
  mean the demo's interactive tick rate contaminates benchmark timing.
- **Idempotency:** `POST /experiments` accepts an optional `Idempotency-Key` header so a retried
  request doesn't launch a duplicate 20-minute benchmark.
- Errors use a single shape: `{"error": {"code": "...", "message": "...", "request_id": "..."}}`.
  Message text is safe for display; details go to the log, never to the client (see threat model).

## 5. Live update transport

Per tick the engine has state for up to 500 nodes, ~1500 links, and hundreds of flows. Streaming
all of it at the engine's tick rate would saturate the browser.

- The engine runs at its own tick rate; the session publisher **aggregates to ~4 updates/second**.
- Each SSE message is a **delta**: only elements whose state changed since the last publish,
  plus the current metric aggregates. A full snapshot is sent on connect and every 50 deltas
  (so a reconnecting client resynchronises without replaying history).
- If the client falls behind, deltas are **coalesced, not queued** — the publisher keeps one
  pending delta per session and merges into it. A slow client sees a lower frame rate, never a
  growing backlog. This is the backpressure story and it is a good interview topic.

## 6. Observability

- **Structured logging:** stdlib `logging` with a ~25-line JSON formatter. Fields: `ts`, `level`,
  `logger`, `msg`, `request_id`, `user_id`, `run_id`, `event`. Rejected `structlog`: the
  formatter is 25 lines. Correlation IDs propagate via `contextvars` (survives `await`).
- **Never logged:** passwords, session cookies, CSRF tokens, `Authorization` headers, full
  request bodies of auth endpoints. Enforced by a redaction filter *and* a test that posts a
  password and greps the captured log stream for it.
- **Audit log** (separate from application log, in Postgres): login, failed login, logout, role
  change, topology create/update/delete, experiment start/cancel, failure injection,
  admin actions. Records actor, object, IP, and timestamp.
- **Endpoints:** `/healthz` (process alive, no dependencies checked — used by the container
  healthcheck), `/readyz` (DB reachable, migrations current, worker heartbeat fresh — used by
  the load balancer), `/metrics` (Prometheus).
- **Metrics that will actually be read:**
  `http_request_duration_seconds{route,method,status}`,
  `http_requests_total`, `orbit_active_runs`, `orbit_run_duration_seconds{algorithm}`,
  `orbit_control_computation_seconds{algorithm,event_type}`,
  `orbit_reroutes_total{algorithm,priority}`, `orbit_preemptions_total`,
  `db_query_duration_seconds`, `process_resident_memory_bytes`.
- **Grafana: optional.** Prometheus earns its place because `orbit_control_computation_seconds`
  is a *result* — it is the control-plane overhead reported in the paper. Grafana adds a
  container and a dashboard JSON to look at data the app already charts. Decide at Phase 13; if
  it is added, it must be because a question was hard to answer without it.

## 7. Deployment & CI/CD

**Local / demo (primary):**
```
docker compose up   →   postgres | api | worker | web (nginx serving built frontend)
```
Multi-stage builds, `python:3.12-slim` and `node:22-alpine` builders, non-root `USER`,
`read_only: true` root filesystem with explicit tmpfs, dropped capabilities, healthchecks,
`mem_limit`/`cpus` on the worker, only the web port published.

**Public deployment: recommended as optional, not core.** A public instance that lets anonymous
users start 500-node simulations is a free CPU-mining target and an ongoing maintenance cost.
The primary demo artifact is `docker compose up` plus a recorded video. If a public instance is
wanted, it must ship with: registration disabled or invite-only, a read-only demo account, hard
caps on nodes/ticks/trials, per-user concurrency of 1, and a global worker cap.

**CI pipeline (GitHub Actions):**

| Job | Runs | Contents |
|-----|------|----------|
| `lint` | every PR | ruff, black --check, mypy (strict on `orbit/`), eslint, tsc --noEmit |
| `test` | every PR | pytest unit + property + integration (Postgres service container), coverage gate |
| `security` | every PR | gitleaks (secret scan), pip-audit + npm audit (dependency scan), bandit, Trivy on the built image |
| `build` | every PR | docker build for api and web; fails on non-pinned base images |
| `e2e` | every PR | compose up, Playwright happy path + failure-injection path, axe accessibility check |
| `bench-smoke` | every PR | one tiny benchmark cell — proves the harness runs, **not** a result |
| `bench-full` | nightly / manual | full factorial; uploads results as artifacts. Never gates a PR. |

Benchmarks do not run on PRs: CI runners are noisy shared VMs and their timings are not valid
measurements. Reported results come from a single documented machine. That distinction is itself
worth explaining in the paper's methodology section.

**Tests are never disabled to make CI green.** A failing test is either a real bug or a wrong
test; both get fixed.

## 8. Named performance risk and the escape hatch

Pure-Python Dijkstra on 500 nodes / ~2000 edges is roughly single-digit milliseconds. The danger
is the controller: if a regional failure affects K = 300 flows and each triggers its own
constrained shortest-path computation, the recomputation is K × SPF, which could reach seconds.

Planned mitigations, in the order they will be applied (and only when a profiler says so):
1. **Reverse index** `link → set(flows)`, so only affected flows are considered — O(K), not O(all).
2. **Batch by source:** flows sharing a source share one shortest-path tree. Compute per distinct
   source, not per flow.
3. **Vectorise the allocator** with NumPy (it is the other hot loop: progressive filling over links).
4. **Incremental SPF** — only recompute subtrees invalidated by the failed edge.
5. Only if all of the above are insufficient: port the inner loop to C via `cffi`, or drop the
   largest topology size from the claims.

Step 5 is the honest fallback: **claim only the sizes actually benchmarked.** Reporting results
for 10–250 nodes with a documented reason for excluding 500 is far better than a fabricated
500-node number.
