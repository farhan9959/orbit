# Learning notes — A10 to A11, and the platform work that closed Tier B

Same shape as the earlier notes: WHAT it is, WHY it exists, HOW it works, what it TRADES
AWAY, and how I would explain it out loud. These cover the components added after A9, which
`CLAUDE.md`'s definition of done requires and which were missing until now.

---

## A10a — The Waxman density correction

**WHAT.** An optional `target_degree` on the Waxman generator, plumbed through
`ScenarioSpec.waxman_target_degree`, that rescales `alpha` so mean degree is held constant as
node count grows.

**WHY.** This is the entry I most want to be asked about, because the bug it fixes was
invisible and would have invalidated a headline claim. The pre-registered scale sweep was
"run Waxman at 50, 100, 250 and 500 nodes and report how the algorithms behave with size".
Waxman's edge probability between two nodes depends on the distance between them and on
`alpha`/`beta` — but *not* on how many nodes there are. Every pair still rolls the dice, so
the edge count grows as O(n²) and mean out-degree went **1.8 at 10 nodes, 3.8 at 60, 7.6 at
100, 21.3 at 250, 44.0 at 500**.

So the "size sweep" was sweeping size and density simultaneously, and no result from it could
be attributed to either. Worse, `offered_load` sets *total* demand as a fraction of network
capacity, so with capacity growing quadratically and a fixed flow count, mean per-flow demand
hit **605 Mbps against 100 Mbps links**. Past one link's capacity no single-path algorithm can
serve any flow in full, so every algorithm collapsed to the same floor: PDR 0.10 for
spf-static, cspf and orbit alike, identical to three decimals. The sweep would have produced a
clean-looking table proving nothing.

**HOW.** Compute the expected edge count at the current parameters, then scale `alpha` by the
ratio needed to hit `target_degree × n / 2` edges, clamped to 1.0. Flow counts are then chosen
per (family, size) so mean per-flow demand stays at 0.353 × link capacity — the value the
60-node headline grid happens to have.

**TRADEOFFS.** Two real ones. Results at 500 nodes describe a *sparse* graph with mean degree
4, not the textbook Waxman at those parameters, and the paper says so. And the correction had
to leave every existing result untouched: the new code path consumes the RNG in the identical
order when `target_degree is None`, and a test asserts the byte-identical stream, because
silently reseeding would have invalidated nine committed result sets.

**HOW I EXPLAIN IT.** "A benchmark that looks fine and measures the wrong thing is more
dangerous than one that crashes. My scale sweep was going to vary size and density together
and then attribute the outcome to size. I caught it by printing mean degree per size before
trusting the numbers — 1.8 to 44 across the range — and I fixed it by pinning the thing that
was supposed to be constant. The lesson I took is to sanity-check the *independent variable*
is actually independent before reading the dependent one."

---

## A10b — Uncontended control cost, and the artefact that nearly became a finding

**WHAT.** `experiments/control_cost.py`, a deliberately single-threaded driver that times one
full recompute at each size, separate from the parallel benchmark grid.

**WHY.** N4 requires control recomputation under 100 ms at 100 nodes. Reading
`control_seconds` straight out of `a10-scale` implied **460 ms** — a fivefold miss. Writing
that up as "ORBIT fails its own performance requirement" would have been rigorous-looking and
wrong. The grid ran 18 worker processes on 20 cores; wall-clock timings under that contention
are inflated roughly tenfold. Measured on an idle machine the same recompute is **66 ms** and
N4 passes.

The subtlety worth keeping: the contention does *not* invalidate the grid's comparison between
algorithms, because every algorithm paid it equally. It only invalidates absolute claims. So
the grid keeps its comparative numbers and absolute claims come from here.

**HOW.** Build the topology once per (family, size), warm each algorithm with a discarded
call, then take the median of five timed recomputes. Same pinned degree and demand-matched
flow counts as the grid, so the curve measures size.

**TRADEOFFS.** Wall-clock, so the numbers belong to the machine in the manifest and nowhere
else. Median of five is thin, but the spread between min and max was small enough that more
repeats would buy precision nobody needs.

**HOW I EXPLAIN IT.** "I nearly reported that my own system missed its performance budget by
5x. The number came from a benchmark harness running 18 processes on 20 cores, and it was
measuring scheduler contention, not my algorithm. The tell was that *every* algorithm looked
10x slower than it had at 60 nodes, including the trivial baseline that does almost no work.
When a measurement moves everything uniformly, suspect the instrument."

---

## A11 — Measuring that a mechanism fires, separately from whether it helps

**WHAT.** The `a11-mechanisms` grid, plus a `backup_activations` counter separating M1's
precomputed-backup path from M2's recomputation.

**WHY.** The earlier ablation found M1, M3 and M4 inert and I had written "preemption never
fires". That was wrong, and it was wrong in an instructive way: the median was zero, and I had
read "median zero" as "never". It fires in 19 of those 120 runs, and in 47% of runs once ring
topologies are in the grid.

But the deeper problem was that the old grid **could not distinguish "does not help" from "was
never reached"**. Preemption is only attempted when no path has residual capacity for a flow —
routine on a degree-two ring, rare on Waxman, and the grid had no ring. Damping only binds
after repeated reroutes, which a single injected failure never produces. So I had been
concluding "these mechanisms do nothing" from conditions in which they could not act at all.

**HOW.** A11 varies only fields already in the scenario identity — family (adding ring), load
to 2.0, failure (adding cascading) — so no seed or scenario id changes and every earlier
result stays reproducible. The verdict criteria were written into the spec *before* the run:
keep a mechanism if it wins CRITICAL delivery in ≥25% of cells with no significant reversals.

The result: they fire (2,024 preemptions, 248 backup activations) and win **0 of 36 cells** on
every metric, median paired difference exactly zero. Among the 506 runs where preemption
fired, 424 are identical to the same run without it and the rest are symmetric about zero.
Noise, not signal.

**TRADEOFFS.** The code stays behind its flags rather than being deleted, which costs some
clarity. Deleting it would make a published negative result unreproducible, and that seemed
the worse trade. M1's verdict is also narrower than it looks: this model recomputes globally
in the tick it detects a failure, so there is no window where a precomputed backup beats
recomputation. IP-FRR's value is *local* repair before the control plane knows anything, and
there is no local-repair actor here. **M1 is inexpressible in this model, not refuted by it** —
a distinction I would rather state than quietly bank as a win.

**HOW I EXPLAIN IT.** "I removed three quarters of my own design based on measurement. The
part I am most pleased with is that the first ablation was not good enough to justify it — it
had tested the mechanisms in conditions where they physically could not activate, so 'no
effect' was unfalsifiable. I built a second grid specifically to give them their best shot,
instrumented how often they actually fired, and fixed the verdict criteria before looking.
They fired constantly and changed nothing. That is a much stronger claim than the one I
started with, and it is stronger *because* I tried to prove myself wrong first."

---

## A11b — The LP optimality sweep

**WHAT.** `experiments/optimality.py`, extending the LP bound from one validated 12-node case
to 13,200 placements across four families, three sizes, four loads and two failure states.

**WHY.** "Better than the baselines" is a weak claim if every algorithm is far from optimal —
it could mean the whole field of comparison is bad. The bound answers "how much is left on the
table". ORBIT's median gap is **1.40%**, the best of the five, and no algorithm exceeds the
bound in any of the 13,200 cells, which is the check that actually matters.

**HOW.** For each cell, apply the failure first so the algorithm and the LP face the identical
graph, run one recompute, allocate, and compare weighted served demand against the relaxation.
Comparing a whole *run* to a static LP would have been comparing unlike things — a run folds
in detection latency and per-tick dynamics the LP knows nothing about — so this measures one
placement decision.

**TRADEOFFS.** The relaxation is splittable, so it upper-bounds the unsplittable optimum and
the reported gap over-states the true distance. Sizes cap at 15 nodes because the LP has
|F| × |E| columns, so nothing bounds optimality at 100 nodes. And on Waxman at these sizes all
five algorithms return an identical 4.68% gap — at 9–15 nodes a Waxman graph often admits one
sensible path per pair, so the algorithms are not being distinguished there at all. The
separation comes from grid and scale-free, and saying so is more useful than quoting the
pooled median alone.

**HOW I EXPLAIN IT.** "A bound turns 'I beat the baseline' into 'I am within 1.4% of what is
achievable'. It also catches bugs no test would: if my algorithm ever *exceeded* a valid upper
bound, that proves the bound or the allocator is broken. Thirteen thousand placements, zero
violations, so both are behaving."

---

## F2b — The YAML topology loader

**WHAT.** `orbit/topospec.py`: parse a topology specification and build the same `Topology`
the generators build.

**WHY.** Generators cover synthetic families; a spec file covers "run it on *this* network".
The interesting design question was where validation lives. The model constructor already
rejects a negative capacity — it is the innermost trust boundary and every path crosses it.
What it cannot do is say *where* in a 200-line file the mistake is; it sees a float, not a
document. So Pydantic sits on top purely to localise: it reports `links.14.capacity_mbps`. The
two layers are not redundant — the schema localises, the model decides.

**HOW.** `yaml.safe_load` (never `load`, which would make an untrusted topology file
executable), a Pydantic schema with `extra="forbid"` so a misspelled `capacity_mpbs` is an
error rather than a silently-defaulted link, then the same `Node`/`Link` constructors the
generators use. A cable becomes two directed links sharing an SRLG.

**TRADEOFFS.** `orbit/` is a pure library with no I/O, so this module parses *text* and the
CLI owns the filesystem. Connectivity is deliberately not repaired: the generators repair it
because a disconnected random graph is a bad benchmark input, but a hand-written file that is
disconnected is what its author asked for.

**HOW I EXPLAIN IT.** "`extra='forbid'` is the whole entry. If you typo a field name, the
permissive default is to ignore it and quietly use the default value — your 10 Gbps link is
silently 100 Mbps and your results are wrong with no error anywhere. Failing on unknown keys
turns a silent wrong answer into a loud one, and that trade is almost always worth it in
anything that feeds a measurement."

---

## F29/F30 — Live sessions: inject, switch algorithm, and the SSE wire format

**WHAT.** `POST /sessions/{id}/inject` and `/algorithm` in `api/routes/live.py`,
`Simulation.switch_algorithm`, positional SSE deltas, and the dashboard's live mode
(`web/src/lib/live.ts` for the pure wire logic, `web/src/components/LivePanel.tsx` for the
view, reusing `TopologyCanvas` and `MetricsPanel`).

**WHY.** Two halves existed and did not meet: the dashboard replayed committed JSON and the
SSE endpoint had no consumer. Three decisions are worth defending.

*Targets are chosen server-side.* `inject` takes a `kind`, not element ids. A client that
could name arbitrary link ids would be enumerating a topology it has not been shown, and could
send ids belonging to someone else's session.

*Deltas are positional.* Arrays indexed by the snapshot's ordering rather than id-keyed
objects, so the live view feeds the *same* canvas the replay view uses instead of needing its
own renderer. At the 100-node session cap that is a few hundred rounded floats at 4 Hz.

*Same-origin, not CORS.* nginx already proxies `/api/` in production, so a Vite dev proxy
mirrors it. Adding `CORSMiddleware` with credentials would have widened the CSRF surface the
threat model deliberately closes, for no benefit.

**HOW.** `switch_algorithm` swaps the controller and clears `_routing`, which is what forces a
recompute on the next step — topology, traffic, injected failures and the tick all carry over,
so the switch shows two controllers meeting the identical world. `FailureSchedule.inject`
appends to the event list, so the schedule stays a pure function of its events and a reset
replays the injection.

**TRADEOFFS.** One I want on the record: the SSE endpoint is deliberately endless, and reading
it to completion from an in-process `TestClient` deadlocks. So its HTTP path is unit-tested
through the publisher's own encoders plus an authz test, and the *wire* behaviour was verified
separately with curl against the real nginx — 25 frames in 6 s, snapshot then deltas, array
lengths matching the snapshot. Two different tools because neither alone covers it.

**HOW I EXPLAIN IT.** "The endpoint never closes, which is correct for a live stream and
awkward for a test client that wants to read to EOF. I split it: the encoders are unit-tested
because that is where the contract lives, and the transport is verified over a real socket
through the real proxy. Writing a test that hangs forever and calling it coverage would have
been worse than admitting the split."

---

## Containers — why "the digests are valid" was not verification

**WHAT.** Building both images, running `docker compose up`, and a `.dockerignore`.

**WHY.** This is the cleanest lesson in the project about what "verified" means. Before Docker
was available I checked both base-image digests against the registry API, found one returning
**404** (a fabricated placeholder that could never have built), fixed it, and recorded the
containers as UNVERIFIED. That was the right label, and the fix was necessary — but when the
images were actually built, three more defects appeared that no amount of static inspection
would have found:

* No `.dockerignore` existed, so the build context was the entire repository — a 643 MB
  `.venv`, `node_modules`, `.git` and the results Parquet — uploaded before the daemon read a
  Dockerfile.
* The web container **exited 1 on every start**. `cap_drop: [ALL]` removes `CHOWN`, and
  nginx's entrypoint chowns its cache directories before dropping to uid 101. It never served
  a byte.
* The worker was **permanently unhealthy**: it shares the API's Dockerfile and inherits a
  `HEALTHCHECK` that curls `/healthz`, but it runs `python -m api.worker` and serves no HTTP.

**HOW.** Capabilities were added back individually (`CHOWN`, `SETUID`, `SETGID`,
`NET_BIND_SERVICE`) rather than by dropping the hardening; the worker's inherited healthcheck
is disabled because it has no endpoint to probe and "the process is running" is what Docker's
status already reports.

**TRADEOFFS.** Verified on Docker Desktop for Windows, not the `ubuntu-latest` runner CI
targets. Same `linux/amd64` images, but the runner path is still unexercised, and the audit
says so rather than rounding up.

**HOW I EXPLAIN IT.** "I had a config I'd inspected carefully, whose one statically-checkable
error I'd already found and fixed. Running it found three more in about ninety seconds, and
one of them meant the web tier had never served a single byte. Static checks tell you a
reference resolves; they cannot tell you the process survives its own startup sequence. That
is why my audit distinguishes 'implemented' from 'executed' and refuses to call anything
verified until something has actually run it."
