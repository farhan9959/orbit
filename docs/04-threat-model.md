# 04 — Threat Model & Security Design

Status: Phase 1 design. Controls are specified, not implemented. Nothing here may be ticked off
in `docs/final-security-audit.md` until a test demonstrates it.

## 0. First, the honest question: does ORBIT need auth at all?

For a single user running experiments from a CLI on a laptop: **no.** Adding authentication to a
local research tool would be security theatre, and this document would be padding.

Auth and authorization are in scope because of two real properties of the system:

1. **The API exposes an arbitrarily expensive compute primitive to a network client.** A single
   POST can request a 500-node, 10,000-tick, 30-trial experiment. Any instance reachable by
   anyone but the owner needs identity, quotas, and rate limits, or it is a free compute farm.
2. **Experiments and topologies are the user's research artifacts.** Multi-tenancy means
   object-level authorization, which is the OWASP #1 category and the one most commonly got wrong.

If you later decide the API tier isn't worth building, **delete the auth chapter too** — don't
keep it as decoration. Security controls without an asset to protect are exactly the "checklist
security" the project brief prohibits.

## 1. Assets, actors, trust boundaries

**Assets**
| Asset | Why it matters |
|---|---|
| Compute (CPU/RAM of the host) | The most attractive target: expensive by design |
| User credentials / sessions | Account takeover → access to others' work |
| Topologies, scenarios, experiments, results | The user's research output |
| Audit log integrity | Needed to explain what happened |
| Host filesystem | Artifact paths and any import feature touch it |

**Actors**
- Anonymous internet client (if deployed publicly)
- Authenticated USER (low privilege, owns their objects)
- Authenticated ADMIN
- A malicious or compromised dependency
- The operator (trusted, but should not need to see plaintext secrets)

**Trust boundaries**
1. Browser → API (all input hostile)
2. API → worker (a job spec crosses it; it is validated on the way in, and again by the worker)
3. API/worker → Postgres
4. Any package install → the build

## 2. Threats and controls

Ordered by realistic risk for *this* system, not by textbook order.

### T1 — Resource exhaustion through legitimate-looking requests **(highest risk)**
The most likely way to take this system down is to use it exactly as intended, at scale.

Controls:
- **Hard server-side caps**, validated by Pydantic before anything is enqueued:
  `nodes ≤ 500`, `links ≤ 5000`, `flows ≤ 2000`, `ticks ≤ 20000`, `trials ≤ 50`,
  `algorithms ≤ 5`. Request body size ≤ 256 KB.
- **Per-user concurrency quota** (default 1 running experiment; ADMIN 4).
- **Bounded worker pool** with a global cap, and a queue depth limit — reject with 429 beyond it.
- **Per-run wall-clock timeout** and **memory ceiling**; the worker kills and marks `FAILED`.
- **Container `mem_limit` and `cpus`** as the backstop when the in-process limits are wrong.
- Live sessions are separately capped (`nodes ≤ 100`) and expire after inactivity.

*Why:* validation caps are cheap and stop the attack at the boundary; the container limits exist
because the first two layers will eventually have a bug.

### T2 — Broken object-level authorization (IDOR)
`GET /runs/{id}` returning another user's run is the classic failure.

Controls:
- Ownership is enforced in the **data-access layer**, not in each route handler: every query is
  built from a scoped repository (`repo.for_user(current_user)`) that applies the owner filter.
  A handler that forgets cannot accidentally succeed, because there is no unscoped accessor to
  call. *This is the control worth explaining in an interview* — per-handler checks are how IDOR
  happens, because eventually someone adds a handler and forgets.
- UUIDv4 identifiers, so IDs are not enumerable (defence in depth only — never the control).
- Automated test per resource type: user B requests user A's object → 403/404, for every verb.
- 404 rather than 403 for objects the user may not even know exist, to avoid confirming existence.

### T3 — Credential attacks
Controls: **Argon2id** (argon2-cffi, tuned to ~50–100 ms on the target hardware, parameters
recorded in the audit doc); constant-time verification; a *generic* failure message
("invalid email or password") so the endpoint isn't a user-enumeration oracle; per-account and
per-IP login rate limiting with exponential backoff; **session ID rotation on login and on
privilege change** (session fixation); server-side session store so logout genuinely revokes;
`HttpOnly`, `Secure`, `SameSite=Lax` cookies; absolute (12 h) and idle (2 h) expiry; password
minimum length 12 with no composition rules (per NIST SP 800-63B) and a check against a small
common-password list.

Explicitly **not** used: MD5, SHA-1, unsalted hashes, reversible encryption of passwords, JWTs
in `localStorage`.

*Why cookies rather than bearer tokens:* the dashboard is same-origin and uses `EventSource` for
SSE, which cannot set an `Authorization` header. Cookie sessions make SSE auth work without a
token-in-querystring hack (which would land tokens in access logs). The cost of cookies is CSRF,
which is handled below — an explicit, defensible trade.

### T4 — Injection, including one specific to this application
- **SQL:** SQLAlchemy parameterised queries only. No f-string SQL anywhere, enforced by a
  `bandit`/grep check in CI. A test fires classic payloads at every free-text field.
- **Spec injection (application-specific):** topology and scenario specs are user-supplied
  structured data that drives a simulator. Therefore: **never `eval`, never `exec`, never
  `pickle.loads`, never `yaml.load`** — `yaml.safe_load` only, then a strict Pydantic model with
  `extra="forbid"` and numeric bounds on every field. A spec is data; nothing in it is ever
  interpreted as code or as a filesystem path.
- Named separately because it is the injection vector a generic checklist would miss and the one
  this system actually has.

### T5 — XSS
User-controlled strings (topology names, experiment names, event messages) render in the
dashboard. Controls: React's default escaping; **zero uses of `dangerouslySetInnerHTML`**,
enforced by an eslint rule; a Content-Security-Policy with `default-src 'self'`, no
`unsafe-inline` (Vite build produces hashed assets, so this is achievable); length limits and
a character allowlist on names; JSON responses served with `application/json` and
`X-Content-Type-Options: nosniff`.

### T6 — CSRF
Cookie auth means a cross-site form can trigger a state change. Controls: `SameSite=Lax` (blocks
the common case), **plus** a double-submit CSRF token required on every non-GET request —
belt and braces, because `SameSite` behaviour varies by browser and by request type. GET
endpoints are side-effect free, which is what makes `SameSite=Lax` sufficient for them. Tested:
a non-GET without the token → 403.

### T7 — Path traversal via artifacts
Runs write Parquet files; the API serves them for download. Controls: the client **never**
supplies a path — it supplies a run UUID; the server looks up `artifact_path`, joins it under a
fixed `ARTIFACT_ROOT`, resolves it with `Path.resolve()`, and asserts the resolved path is still
inside `ARTIFACT_ROOT` before opening it. Filenames are generated server-side from the run UUID,
never from user text.

### T8 — SSRF
Only relevant if a "import topology from URL" feature is ever added. **Current decision: don't
add it.** No feature, no attack surface. If it is later required: allowlist scheme + host, resolve
DNS and reject private/link-local/loopback ranges *after* resolution, disable redirects, set a
timeout, cap the response size.

### T9 — Supply chain
Pinned lockfiles (`uv.lock`/`requirements.txt` with hashes, `package-lock.json`); pinned base
image digests; `pip-audit` and `npm audit` in CI; Dependabot; Trivy scan of the built image;
`gitleaks` in CI **and** as a pre-commit hook. Every new dependency must pass the stack rule in
`docs/02-architecture.md` §2.

### T10 — Secret leakage
`.env` in `.gitignore` from the first commit. `.env.example` holds **names and dummy values
only**. No default secret in code — the app **refuses to start** if `SESSION_SECRET` is missing or
is the example value. Secrets never appear in logs (redaction filter + a test that submits a
password and asserts it is absent from captured log output). No secrets in the docker-compose
file for anything but local development, and the local values are obviously non-production.

Variables that will actually exist (no invented ones):
```
DATABASE_URL=postgresql+psycopg://orbit:orbit@localhost:5432/orbit
SESSION_SECRET=            # required, ≥32 bytes, no default
ARTIFACT_ROOT=./experiments/results
LOG_LEVEL=INFO
ENV=development            # production ⇒ debug off, no stack traces, HTTPS-only cookies
CORS_ORIGINS=              # empty in prod; the frontend is same-origin
MAX_CONCURRENT_RUNS=2
```

### T11 — Information disclosure through errors
Production returns `{"error": {"code", "message", "request_id"}}` with a safe message; the stack
trace goes to the log keyed by `request_id`. Debug mode is off in production, verified by a test
that asserts a deliberately-triggered 500 contains no traceback. Database errors are never
surfaced verbatim.

### T12 — Container and host
Non-root `USER` in every image; `read_only: true` root filesystem with explicit `tmpfs` for
`/tmp`; `cap_drop: [ALL]`; `no-new-privileges`; only the web port published (Postgres and
`/metrics` stay on the internal network); resource limits per service; healthchecks; minimal
base images with pinned digests. No Docker socket is mounted anywhere.

## 3. Rate limits (concrete, and documented for the audit)

| Endpoint | Limit | Rationale |
|---|---|---|
| `POST /auth/login` | 5 / 15 min per (IP, email); 20 / h per IP | Credential stuffing |
| `POST /auth/register` | 3 / h per IP | Account spam |
| `POST /experiments` | 10 / h per user, plus concurrency quota 1 | The expensive operation |
| `POST /sessions` | 5 / h per user; max 2 live sessions | Live sessions hold memory |
| `POST /sessions/{id}/inject` | 30 / min per session | UI-driven; prevents event flooding |
| All other API | 300 / min per user, 60 / min per IP unauthenticated | General abuse ceiling |

Implementation: a fixed-window counter in Postgres or an in-process token bucket — **not** a new
Redis container for a single-node deployment. Limits return `429` with `Retry-After`.

## 4. What is deliberately NOT implemented, and why

Naming these prevents the audit from becoming a list of controls nobody needs, and each is a
good interview answer:

- **MFA** — no. Single-user research tool; the account protects experiment data, not money or PII.
- **Field-level encryption at rest** — no. Nothing stored is sensitive beyond an email address;
  disk-level encryption on the host is the appropriate layer.
- **WAF / bot detection** — no. Rate limits and input caps address the actual threat (T1) directly.
- **OAuth / SSO** — no. No organisational identity provider to integrate with.
- **HSTS preload, certificate pinning** — no. TLS terminates at the reverse proxy; HSTS header
  yes, preload submission no (it's irreversible and this is a demo host).
- **Audit-log tamper-evidence (hash chaining)** — no. The threat model has no adversary with DB
  write access but not application-level access.

## 5. Verification plan

Every control above maps to at least one automated test in `tests/security/`. The final security
audit document records, for each item: the control, the test that proves it, the date it was run,
and the result. **An unchecked box is fine; a checked box without a test is a lie.**
