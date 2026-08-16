# Learning notes

One entry per major component, written the day it was built, in the form the project
constitution requires: WHAT / WHY / HOW / TRADEOFFS / HOW I EXPLAIN IT IN AN INTERVIEW.

The rule from `CLAUDE.md` is that no code merges without its entry. The point is not
documentation for its own sake — it is that a component you cannot explain in five short
sections is a component you do not understand, and an interviewer will find that out
faster than you will.

Status legend: **VERIFIED** = there is a test that fails if the claim is false.
**UNVERIFIED** = not yet measured.

---

## A1 — Core model types (`orbit/model/`)

**WHAT.** The immutable, self-validating vocabulary the whole simulator is written in:
`Node`, `Link`, `Topology`, `Flow`, `Priority`, `Route`, and `RoutingState`, plus the two
boundary validators `validate_flows` and `validate_routing`.

**WHY.**

* *Why validate in the constructor rather than at an API layer.* Topologies and scenarios
  are user-supplied structured data (`04-threat-model.md` T4). Every path into the
  system — CLI, YAML loader, future HTTP API, property test — goes through these
  constructors, so validating here means an invalid model object cannot exist anywhere.
  A check at the HTTP layer would protect exactly one of those four paths.
* *Why links are directed.* Real failures are frequently unidirectional and real capacity
  is frequently asymmetric. A bidirectional cable is two `Link`s sharing an SRLG tag, so
  cutting the conduit takes both — which is precisely the shared-fate case that defeats
  naive backup-path computation, and one of the things ORBIT is built to demonstrate.
* *Why immutability.* Failure injection (A4) will build a new `Topology` rather than mutate
  the current one. That makes invariant I-NOCREATE checkable by comparing objects, stops a
  stale reference from silently observing a future state, and removes an entire class of
  aliasing bug at tick 8000. The cost is an O(V+E) rebuild per failure event, which at a
  handful of events per run is nothing.
* *Why sorted iteration everywhere.* Determinism is an invariant, not an aspiration
  (`CLAUDE.md` rule 5). Sorting ids once at construction means no downstream code can
  accidentally depend on dict insertion order.
* *Why `Priority` is an `IntEnum` with CRITICAL = 3.* The allocator's class order is then
  literally `sorted(Priority, reverse=True)`, and the controller's flow order is
  `sorted(..., key=lambda f: (-f.priority, ...))`. Encoding precedence the other way round
  would put a negation at every use site, and the one place it was forgotten would be a
  silent, plausible-looking wrong result.

**HOW.** Frozen `@dataclass(slots=True)` types whose `__post_init__` validates and coerces
through `object.__setattr__`. `Topology` builds three read-only mappings at construction:
nodes by id, links by id, and sorted out-link adjacency lists. Adjacency lists rather than
a matrix because these graphs are sparse — a 500-node Waxman topology has ~2000 edges, so a
matrix would be 250,000 mostly-empty cells and every neighbour scan would cost O(V) instead
of O(deg).

The one subtle split: **`Route` validates structure, not liveness.** Link existence,
contiguity, and simplicity (no repeated node, therefore no forwarding loop) are checked at
construction. Whether the elements are UP is checked at *use* time by the allocator,
because operational state changes every tick while an installed route persists across
ticks — a route cannot become retroactively invalid by raising from a constructor that
already returned.

**TRADEOFFS.**

| Decision | Gained | Given up |
|---|---|---|
| Validate in constructors | Invalid objects cannot exist; one place to audit | Construction is slower; matters only if topologies are rebuilt in a hot loop |
| Immutable model | I-NOCREATE checkable, no aliasing bugs | O(V+E) copy per failure event |
| `RoutingState = Mapping[FlowId, Route]` | No class with one field | Becomes a real class in A6, when backups and damping counters need a home |
| Structural-only `Route` validation | Routes survive state changes honestly | Liveness must be re-checked by every consumer; currently exactly one |
| `GraphView` deferred to A3 | No speculative abstraction | The "controller never sees ground truth" guarantee is not yet enforced by construction |

**HOW I EXPLAIN IT IN AN INTERVIEW.** "The model types validate themselves in their
constructors, so an invalid topology is unrepresentable rather than merely rejected
somewhere. The interesting design decision is what `Route` deliberately does *not* check.
It validates that the path is structurally real — the links exist, they join up, no node
repeats, so no forwarding loop can be installed. It does not validate that the elements are
UP, because a route outlives the state it was computed under: the control plane installs a
route, a link fails three ticks later, and the route object is still a true statement about
the graph's shape. Liveness is a per-tick question, so it is answered per tick, by the
allocator, which is also where the invariant that no traffic crosses failed hardware is
enforced."

---

## A2 — Max-min allocator (`orbit/engine/allocator.py`)

**WHAT.** Given a topology, the active flows, and their installed routes, decide how much
each flow actually delivers this instant. Strict priority between traffic classes, max-min
fairness within a class.

**WHY.** This is the physics of the simulator. Every metric the project reports — packet
delivery ratio, throughput, time-to-restore — is derived from these numbers, so if the
allocator is wrong, the study is worthless regardless of how good the controller is. It is
also where "priority" stops being a label on a dataclass and becomes a mechanism with a
measurable consequence.

**HOW.** Progressive filling (water-filling), one priority class at a time.

The mental model: every competing flow's rate rises together at the same speed, like water
filling a tank. A flow stops rising the moment it is satisfied, or the moment one of its
links fills up. So each round raises the water level by

```
t = min( min over links  residual(e) / (unfixed flows on e),      # a link fills
         min over flows  (demand_f - rate_f) )                    # a flow is satisfied
```

then removes every flow that hit either condition, and repeats. Classes run
CRITICAL → HIGH → NORMAL → LOW, each seeing only the capacity its seniors left behind,
which is what makes precedence strict.

*Why it terminates:* each round removes at least one flow — either the flow achieving
`t_demand`, or the ≥1 flows crossing the link achieving `t_link`. So a class of `n` flows
takes at most `n` rounds. (Worth noting: `03-simulation-model.md` §4 states a bound of
`|E|` rounds. That is the bound for the textbook version with no demand caps; once flows
can also be removed by being *satisfied*, `n` is the bound that actually holds. Both are
finite.)

*Why residuals are recomputed rather than decremented:* keeping a running residual and
subtracting `t × n_e` each round accumulates floating-point error in the exact quantity
I-CAP is stated over. Recomputing `residual = capacity - load` from the authoritative load
costs nothing asymptotically — every round already touches every unfixed flow's links — and
keeps the error at a couple of ULPs.

**Complexity.** With `n` flows in a class and `P = Σ|route|` total path length over that
class: one round is O(P), at most `n` rounds, so O(n·P) worst case, plus O(|F| log |F|) for
the determinism sort. Memory O(|F| + |E|). The worst case needs every round to fix exactly
one flow; typical rounds fix several. **UNVERIFIED** — no benchmark has been run, and
`02-architecture.md` §8 already names NumPy vectorisation as the mitigation if a profile
ever says the allocator dominates.

**TRADEOFFS.**

| Decision | Gained | Given up |
|---|---|---|
| Strict priority, not weighted fair queueing | Priority is measurable; H1 has a mechanism | LOW traffic can starve to zero — a finding to report, not a bug to hide. The WFQ variant is deferred until the experiment runner can compare them |
| Progressive filling, not an LP solver | Deterministic, no dependency, fast enough for thousands of runs | Not an optimum. The optimality gap is measured separately against an LP on ≤ 15-node topologies (A6) |
| Relative tolerance of 1e-9 | Saturation and satisfaction are decidable in floating point | I-CAP holds to `capacity × (1 + 1e-9)`, not exactly. Stated in the docstring and used by the invariant checkers |
| Sparse `link_load` | No zero written for every idle link every tick | Callers need `load_on()` rather than direct indexing |
| Starvation reported separately from blackholing | "Did recovery find a route?" stays answerable from the metrics | One more field to carry |

**Testing strategy, and what it caught.** Three layers, and the second and third both found
real weaknesses in the first:

1. *Worked examples* with hand-computed answers — the parking-lot topology, unequal
   bottlenecks, the four-class precedence ladder. Every expected number is derived from the
   definition, never copied from the implementation's output.
2. *Property tests* asserting the invariants on generated topologies, including the
   bottleneck characterisation of max-min fairness — which is checkable directly from the
   output, without re-running the algorithm, so it cannot agree with a bug by sharing it.
3. *Mutation checks*: five deliberate breakages, each required to turn the suite red.

Two things worth remembering from this:

* Reversing the class order, dropping the demand cap, dropping the liveness check and
  disabling redistribution were all caught. **Deleting the determinism sort was not** — the
  rates come out order-independent anyway, because every flow in a round is raised by the
  same `step` and adding one identical value n times is order-independent in floating
  point. What the sort actually fixes is the *iteration order of the result*, which is what
  the CI determinism gate will hash. The test now asserts key order, not just values.
* The property generator was measured, not assumed. Its first version reached a genuinely
  contended link — real capacity, saturated, two or more competing flows — in only a few
  percent of examples, so I-PRIO and I-MAXMIN were barely exercised while the suite
  reported 300 passing examples. After fixing the generator (ring-connected base topology,
  demands above capacities, traffic concentrated on hot pairs) it reaches 41.5% contended
  and 37.0% cross-class contention, and a test now asserts floors under both.

**HOW I EXPLAIN IT IN AN INTERVIEW.** "A flow's rate is set by its most constrained link,
but how constrained a link is depends on what every other flow through it gets — which
depends on *their* bottlenecks. That circularity is the max-min fair allocation problem,
and progressive filling resolves it: raise everybody's rate together until either somebody
is satisfied or some link fills, freeze whoever just stopped, repeat. It terminates because
each round freezes at least one flow.

The thing I would actually want to talk about is testing it. The strong test is not an
example with a number I worked out — it is the bottleneck characterisation of max-min
fairness: an allocation is fair if and only if every unsatisfied flow has a saturated link
on its path where its own share is maximal. That is checkable straight from the output
without re-running the algorithm, so it cannot pass by sharing a bug with the
implementation.

And I measured whether the property tests were reaching interesting states, rather than
assuming it. They were not — a genuinely contended link showed up in a few percent of
generated examples, so the two fairness invariants were nearly untested while the suite
looked green. I instrumented the generator, fixed the bias, and added a test that asserts
the contention rate, so it cannot quietly regress. A property suite that cannot fail is
worse than none, because it reports confidence it has not earned."

---

## A1 (cont.) — Seed derivation and topology generators (`orbit/rng.py`, `orbit/generators/`)

**WHAT.** `derive_seed(base_seed, name)` / `rng_for(base_seed, name)`, giving each
stochastic subsystem its own independent reproducible stream; and the four synthetic
topology families from requirement F2 — `grid`, `ring`, `waxman`, `barabasi_albert`.

**WHY.**

* *Why named streams instead of one global RNG.* Two reasons, and the second is the one
  that matters. **Independence:** with a shared stream, adding one extra random draw to
  the topology generator silently changes the traffic matrix and the failure times of
  every subsequent run, so a refactor that should be invisible instead invalidates a
  benchmark. **Pairing:** `05-methodology.md` B2 requires every algorithm in a cell to
  face a bit-identical world, which is only true if the topology, traffic and failure
  schedule are reproducible regardless of which algorithm is running and how many draws
  that algorithm happens to make.
* *Why BLAKE2b and not `hash()`.* Python salts `str` and `bytes` hashes with a per-process
  random value unless `PYTHONHASHSEED` is set. `random.Random(hash(name))` is a
  plausible-looking one-liner that silently produces a different stream on every
  invocation, and nothing in the code's appearance reveals it. BLAKE2b is stdlib, stable
  across processes and platforms, and the test suite proves both halves: one test asserts
  `derive_seed` is identical across two subprocesses run with different `PYTHONHASHSEED`
  values, and another asserts that raw `hash()` *differs* under the same conditions — so
  the hazard is documented executably rather than as a comment nobody rechecks.
* *Why four families.* They differ in exactly the way the failure sweep needs. A grid is
  regular and richly connected, so reconvergence looks its best. A ring is the pessimistic
  case: every node has degree two, so any second cable cut partitions the network.
  Barabási–Albert has hubs, which is what makes a *targeted* failure devastating there and
  unremarkable on a grid. Waxman is geometric, and the only family with distance-dependent
  latency, which is why it carries the scale and load sweeps.
* *Why a cable is two directed links sharing an SRLG.* `Link` is directed, so an undirected
  adjacency becomes a forward and reverse pair tagged `cable:<a>-<b>`. A conduit cut takes
  the tag, therefore both directions. Without this, a "backup path" could be computed that
  shares physical fate with its primary — the exact failure mode that defeats real
  protection schemes, and one ORBIT is meant to demonstrate.

**HOW.** Each generator produces a set of undirected `(a, b)` index pairs, and one shared
`_build` turns them into nodes and directed link pairs. Waxman joins each pair with
probability `alpha·exp(-d/(beta·L))` over uniformly placed points; Barabási–Albert uses the
standard endpoint-pool trick, where a node appears in the pool once per incident edge
endpoint, so a uniform draw from the pool is a degree-proportional draw over nodes — O(1)
per attachment instead of a scan over the degree table.

Two decisions worth defending:

* **Node ids are zero-padded** (`n000`). Everything in this project iterates over sorted
  ids, and unpadded ids sort `n10` before `n2`. That is harmless for determinism but makes
  every event log and debugging session harder to read than it needs to be.
* **Connectivity is repaired deterministically, not by retrying with a new seed.** Waxman
  at low `alpha` routinely fragments. Components are chained in ascending order by their
  smallest member. The specific choice is arbitrary; what matters is that the repair
  consumes *no random draws*, because a repair that sampled would shift every subsequent
  random decision and make the topology depend on how fragmented it happened to be.

**TRADEOFFS.**

| Decision | Gained | Given up |
|---|---|---|
| Guaranteed-connected output | Benchmarks measure recovery, not pre-existing partitions | The generator can't produce a naturally-partitioned topology; a partition must be *injected*, which is where it belongs |
| Uniform capacity per topology | Load is a scenario parameter, not a topology one | No heterogeneous-capacity families yet |
| Waxman coordinates discarded | No speculative field on `Node` | F5 (stable visual layout) relies on regenerating from the seed, which reproduces the coordinates exactly |
| Deterministic connectivity repair | Repair can't perturb later draws | Repaired edges are slightly unnatural for the family |
| Spec-file loading not implemented | No premature YAML/Pydantic dependency | The other half of F2 is still open |

**HOW I EXPLAIN IT IN AN INTERVIEW.** "The generators are ordinary graph algorithms; the
part worth talking about is the seeding. Every stochastic subsystem gets its own stream
derived from the run's base seed and a name, rather than sharing one global generator. That
sounds fussy until you notice the failure mode it prevents: with a shared stream, adding a
single random draw to the topology generator changes the traffic and the failure schedule
of every run afterwards, so a refactor silently invalidates results you have already
published.

The derivation uses BLAKE2b rather than Python's `hash()`, because `hash()` on strings is
salted per process — `random.Random(hash(name))` looks completely reasonable and quietly
destroys reproducibility. I have a test that runs the derivation in two subprocesses with
different `PYTHONHASHSEED` values and asserts the seeds match, and a companion test
asserting that raw `hash()` does *not* match, so the reason the code is written that way is
executable rather than a comment somebody deletes in a year."

---

## A2 (cont.) — Tick loop and metrics (`orbit/engine/simulation.py`, `metrics.py`)

**WHAT.** The fixed-timestep loop (`Simulation.step` / `run` / `reset` / `measure`), the
per-flow derived quantities (delivered rate, congestive loss, intrinsic loss, latency), and
the run summary (PDR overall and per class, throughput, weighted mean and p95 latency).

**WHY.**

* *Why integer time.* Simulation time is `tick_index * tick_ms`, never a float that
  accumulates. This is not theoretical fastidiousness: a mutation test that replaced the
  integer arithmetic with `time += 0.1` produced `0.9999999999999999` after **ten ticks**.
  Over a 20,000-tick run that drift silently shifts every flow's activity window, and it
  would be discovered — if at all — as an unreproducible benchmark months later.
* *Why latency is `None`, not `0.0`, when nothing was delivered.* §7 requires latency to be
  weighted over delivered traffic only. Recording zero for a flow that delivered nothing
  would make a congested run look *faster* than a healthy one, because the worst-off flows
  would contribute the best latencies. This is a statistics trap the methodology doc
  anticipates, and the type system now enforces it: `float | None` forces every consumer to
  decide what to do about it.
* *Why the summary refuses to report a PDR over zero demand.* `pdr` is `float | None`, and
  `None` when nothing was demanded. Neither 0.0 nor 1.0 is true, and folding a fabricated
  value into an aggregate is the same class of bias as counting a partitioned run as an
  instant recovery — which B4 explicitly forbids.
* *Why `run()` is a generator.* A 500-node, 20,000-tick run produces millions of samples.
  Returning a list would make the engine's memory ceiling the run length, against N1
  (8 GB laptop). Streaming lets `MetricsAccumulator` fold results into running totals.

**HOW.** Per tick: select active flows by their half-open `[start, start+duration)` window,
allocate, then derive. Half-open matters — a closed interval would double-count one tick at
every flow handover, inflating offered demand.

**A specification ambiguity I had to resolve.** §4 defines delivered rate as "the allocation
result" and lists intrinsic loss as a *separate* metric, implying they are never composed.
But `05-methodology.md` A4 requires a 100%-loss link to yield `delivered = 0`. Both cannot
hold. The resolution, documented in `metrics.py`:

```
allocated_mbps = what the allocator granted     <- this consumes link capacity
delivered_mbps = allocated * (1 - intrinsic_loss)  <- this is what PDR uses
```

Both are recorded, so congestion and medium loss stay distinguishable — a controller can
reroute around the first but not the second. Note the asymmetry: capacity is consumed by
the *allocated* rate, because traffic dropped by a lossy link partway along a path has
already occupied the links before it. Modelling it the other way would quietly hand lossy
paths extra effective capacity.

**TRADEOFFS.**

| Decision | Gained | Given up |
|---|---|---|
| Static routing for now | Loop works today, and it *is* baseline B1 | Steps 1–3 of the tick loop (events, detector, recompute) wait for A3/A4 |
| `run()` yields lazily | Memory bounded by the caller's choice, not run length | Callers must opt into `list()` |
| Summary in the engine, Parquet in A7 | `orbit/` stays I/O-free per architecture §1 | No file output yet |
| Exact weighted p95 | Correct percentile, not an approximation | Latency samples retained; marked `# ponytail:` with a histogram as the upgrade |
| Queue delay `min(q_max, k/(C-L))` | Monotone, bounded, no division by zero | An approximation, labelled as one; affects absolute latency only, identically for every algorithm |

**HOW I EXPLAIN IT IN AN INTERVIEW.** "Two decisions in the tick loop are worth more than
the loop itself. First, simulation time is an integer tick count multiplied by the tick
length, never a running float sum. I proved that mattered by breaking it deliberately — the
float version drifts off 1.0 after ten ticks, and in a twenty-thousand-tick benchmark that
silently moves every flow's schedule.

Second, latency is `None` rather than zero when a flow delivered nothing. That sounds
pedantic until you work out what averaging zeros does: the flows that were starved
contribute the *best* latencies, so the more congested the network gets, the faster it
looks. The methodology document flagged that trap, and encoding it as `float | None` means
every consumer has to make a decision about it rather than silently averaging in a lie.

I also hit a genuine contradiction between two of my own design documents about whether
link loss reduces delivered rate. Rather than pick one silently, I found the edge case that
settles it — a 100%-loss link has to deliver zero — wrote the resolution into the module
docstring, and made that edge case a named test."
