# CLAUDE.md — ORBIT working agreement

This file is read by Claude Code at the start of every session in this repo.
It is the project's constitution. Keep it short; keep it true.

## What ORBIT is

A **flow-level network resilience simulator and evaluation harness**. It measures whether a
priority-aware, centrally-computed recovery controller restores traffic faster and preserves
critical traffic better than conventional routing, under injected failures.

It is a research prototype and a measurement study. It is **not** certified emergency
infrastructure, not a packet-level simulator, and not a replacement for ns-3 or Mininet.

## Non-negotiable rules

1. **Never fabricate.** No invented benchmark numbers, no invented citations, no "implemented"
   claims for code that has not been run and tested. If something is untested, the doc says
   `UNVERIFIED`.
2. **Baselines get a fair fight.** Every baseline receives the same failure detection latency,
   the same topology, the same traffic, and the same seed as ORBIT. A strawman baseline
   invalidates the entire project. See `docs/05-methodology.md` §3.
3. **Report negative results.** If ORBIT loses on a metric, that goes in the results table and
   the paper. Losing on aggregate throughput while winning on critical-flow delivery is an
   expected, interesting finding — not a bug to hide.
4. **No novelty claims without the literature review.** ORBIT's mechanisms are compositions of
   known techniques (IP-FRR, CSPF, RSVP-TE priority preemption, route damping). The contribution
   is the integration + the reproducible measurement study. Say exactly that.
5. **Determinism is an invariant, not a nice-to-have.** Same seed ⇒ byte-identical output.
   Tested in CI. No global `random`, no unordered iteration, no threads in the engine.
6. **The author must be able to explain every file.** If a change cannot be explained in three
   sentences, it is too clever. Rewrite it.

## Ponytail applies, with named exceptions

Apply the ponytail ladder (does it need to exist → stdlib → native → existing dep → one line →
minimum code). Prefer deleting over adding. No interface with one implementation.

Ponytail does **not** apply to: input validation at trust boundaries, authz checks, password
hashing, rate limiting, the invariant test suite, benchmark statistics, structured logging,
or the research documentation. Those are the deliverable.

Mark deliberate corners with `# ponytail: <ceiling>, <upgrade path>`.

## Build order (do not reorder)

Tier A (the science) must be finished and producing real numbers before Tier B (the platform)
starts. See `docs/06-roadmap.md`. If ORBIT's mechanism does not beat the baselines, that must be
discovered in week 4 with a CLI, not in week 20 with a React dashboard already built on top.

## Definition of done for any component

- [ ] implemented
- [ ] has a test that fails if the logic breaks
- [ ] tested against a known-good oracle where one exists (e.g. Dijkstra vs `networkx`)
- [ ] its assumptions and failure modes are written down in the module docstring
- [ ] `docs/learning-notes.md` has a WHAT / WHY / HOW / TRADEOFFS / INTERVIEW entry for it

## Commands

```
make dev            # run api + frontend locally
make test           # unit + property + integration
make test-security  # authz, rate limit, injection, CSRF tests
make lint           # ruff, black --check, mypy, eslint, tsc
make bench SCENARIO=<name>   # one benchmark cell, writes to experiments/results/
make reproduce      # regenerate every figure in the paper from raw results
```

## Style

Python: 3.12, ruff + black, mypy strict on `orbit/` (not on tests).
TypeScript: strict, eslint, no `any` in `src/` without a comment justifying it.
Commits: `<area>: <imperative summary>` — e.g. `engine: add max-min allocator with strict priority`.
