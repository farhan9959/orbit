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
