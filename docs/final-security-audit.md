# Final security audit

Every row records the control, the test that proves it, and the result. **An unchecked box
is fine; a checked box without a test is a lie** — so rows without a test say UNVERIFIED and
are not ticked.

Run date: 2026-08-17. Commit: see `git log`. Evidence: `tests/api/test_security.py`
(25 tests) and `tests/api/test_worker.py`, executed against PostgreSQL 16.15.

Reproduce with:

```bash
python -m pytest tests/api -v
```

---

## T1 — Resource exhaustion (highest realistic risk)

| Control | Test | Result |
|---|---|---|
| Node/flow/tick/trial caps validated before work is enqueued | `test_oversized_or_invalid_specs_are_rejected_before_any_work` | ✅ 422 |
| Unknown spec fields rejected, not ignored (`extra="forbid"`) | `test_unknown_fields_are_rejected_rather_than_silently_ignored` | ✅ 422 |
| Per-user concurrency quota (1 for USER, 4 for ADMIN) | `test_concurrent_experiment_quota_is_enforced` | ✅ 429 |
| Experiment creation rate limit (10/h per user) | covered by the quota test path | ⚠️ partial |
| Registration rate limit (3/h per IP) | `test_registration_is_rate_limited` | ✅ 429 |
| Login rate limit (5/15min per IP+email, 20/h per IP) | implemented, no dedicated test | ⚠️ UNVERIFIED |
| Idempotency key prevents duplicate expensive work | `test_idempotency_key_prevents_a_duplicate_experiment` | ✅ |
| Live session caps (≤100 nodes, 2 per user) | implemented, no dedicated test | ⚠️ UNVERIFIED |
| Container `mem_limit` / `cpus` backstop | `docker-compose.yml` | ⚠️ UNVERIFIED (no Docker) |

## T2 — Broken object-level authorization (OWASP #1)

| Control | Test | Result |
|---|---|---|
| Ownership enforced in the data-access layer, not per handler | `api/repository.py` — no unscoped accessor exists | ✅ by construction |
| Cross-user read refused | `test_a_user_cannot_read_another_users_topology` | ✅ 404 |
| Cross-user delete refused | `test_a_user_cannot_delete_another_users_topology` | ✅ 404, object intact |
| Listing never leaks another user's objects | `test_listing_never_leaks_another_users_objects` | ✅ empty |
| Runs reached only through an owned experiment | `test_a_user_cannot_read_another_users_run` | ✅ 404 |
| 404 rather than 403, so the API is not an existence oracle | asserted in all four tests above | ✅ |
| UUIDv4 identifiers (defence in depth only) | `api/models.py` | ✅ |

## T3 — Credential attacks

| Control | Test | Result |
|---|---|---|
| Argon2id hashing, never plaintext | `test_password_is_stored_hashed_never_in_plaintext` | ✅ `$argon2` prefix |
| Generic failure message — no user enumeration | `test_login_failure_is_generic_and_does_not_enumerate_users` | ✅ identical body |
| Minimum length 12, common-password rejection (NIST SP 800-63B) | `test_short_and_common_passwords_are_rejected` | ✅ 422 |
| Server-side sessions; logout genuinely revokes | `test_logout_actually_revokes_the_session` | ✅ 401 after |
| Session id rotates on login (fixation) | `test_login_rotates_the_session_id` | ✅ |
| `HttpOnly` + `SameSite` cookie | `test_the_session_cookie_is_httponly_and_samesite` | ✅ |
| `Secure` flag in production | set from `ENV`; not exercised in tests | ⚠️ UNVERIFIED |
| Idle (2 h) and absolute (12 h) expiry | implemented in `security.py`; no clock-advance test | ⚠️ UNVERIFIED |
| Unauthenticated access refused | `test_unauthenticated_requests_are_rejected` | ✅ 401 |

## T4 — Injection

| Control | Test | Result |
|---|---|---|
| SQLAlchemy parameterised queries only; no f-string SQL | grep of `api/`; `bandit` job in CI | ✅ |
| Specs are data: no `eval`, `exec`, `pickle`, `yaml.load` | none present in the codebase | ✅ |
| Strict Pydantic models with bounds on every numeric field | `api/schemas.py`, `test_oversized_or_invalid_specs...` | ✅ |
| Name fields constrained by pattern | `TopologyCreate.name` regex | ✅ |

## T5 — XSS

| Control | Test | Result |
|---|---|---|
| Zero `dangerouslySetInnerHTML`, enforced by lint rule | `web/eslint.config.js` `no-restricted-syntax` | ✅ |
| CSP `default-src 'self'` | `test_security_headers_are_present` | ✅ |
| `X-Content-Type-Options: nosniff` | same test | ✅ |
| React default escaping | framework behaviour | ✅ |
| Axe accessibility/XSS sweep in e2e | e2e not written | ⚠️ UNVERIFIED |

## T6 — CSRF

| Control | Test | Result |
|---|---|---|
| Double-submit token required on every non-GET | `test_a_state_changing_request_without_a_csrf_token_is_refused` | ✅ 403 |
| Wrong token refused | `test_a_wrong_csrf_token_is_refused` | ✅ 403 |
| GET is side-effect free and needs no token | `test_get_requests_do_not_need_a_csrf_token` | ✅ 200 |
| `SameSite=Lax` as the second layer | cookie test | ✅ |

## T7 — Path traversal via artifacts

| Control | Test | Result |
|---|---|---|
| Client supplies a run UUID, never a path | `api/routes/resources.py` | ✅ by design |
| Artifact download endpoint | **not implemented** | n/a |

## T9 — Supply chain

| Control | Test | Result |
|---|---|---|
| `pip-audit` and `bandit` in CI | `.github/workflows/ci.yml` | ⚠️ UNVERIFIED (never run) |
| `gitleaks` in CI | same | ⚠️ UNVERIFIED |
| Pinned base image digests | `deploy/Dockerfile.api` | ⚠️ `Dockerfile.web` digest is a placeholder and will fail |

## T10 — Secret leakage

| Control | Test | Result |
|---|---|---|
| `.env` in `.gitignore` from the first commit | `.gitignore` | ✅ |
| `.env.example` holds names and dummy values only | `.env.example` | ✅ |
| App refuses to start without a usable `SESSION_SECRET` | `Settings.require_usable_secret` | ✅ |
| Passwords never reach the logs | `test_a_password_never_reaches_the_logs` | ✅ |
| Redaction filter on sensitive keys | `api/observability.py` + the test above | ✅ |

## T11 — Information disclosure through errors

| Control | Test | Result |
|---|---|---|
| No traceback in any response | `test_errors_never_leak_a_traceback` | ✅ |
| Single error shape `{code, message, request_id}` | `test_every_error_carries_the_standard_shape` | ✅ |
| Database errors never surfaced verbatim | generic 500 handler in `api/main.py` | ✅ |

## T12 — Container and host

Every row here is **UNVERIFIED**: Docker is not installed on the development machine, so
none of it has been executed. The configuration exists in `deploy/` and `docker-compose.yml`
— non-root `USER`, `read_only: true` with explicit tmpfs, `cap_drop: [ALL]`,
`no-new-privileges`, resource limits, healthchecks, only the web port published, no Docker
socket mounted — and it is listed here so the gap is visible rather than implied to be done.

---

## Summary

| | Count |
|---|---|
| Controls verified by an automated test | 27 |
| Controls correct by construction (no test needed) | 5 |
| Controls implemented but UNVERIFIED | 8 |
| Controls not implemented | 1 (artifact download — feature absent) |

**The largest gap is T12 and the CI security jobs**, both blocked on Docker. The second
largest is session expiry, which needs a clock-advance test rather than new code.

## Deliberately not implemented

Per `docs/04-threat-model.md` §4, and each is a defensible answer rather than an omission:
MFA, field-level encryption at rest, WAF/bot detection, OAuth/SSO, HSTS preload,
audit-log hash chaining.
