# Literature review and contribution positioning

Status: **written from the primary sources.** Every work in §2 was retrieved and read at least
to the depth stated in its entry; the depth is recorded per entry so a reader can tell a
close reading from a metadata check. Nothing is cited that was not retrieved.

Retrieved August 2026. PDF sources are the authors' own copies where the publisher's is
paywalled; the venue and year were cross-checked against the ACM DL or the RFC Editor.

---

## 1. What this review had to decide

`03-simulation-model.md` §6 describes ORBIT as an integration of four mechanisms and the
project's working agreement (CLAUDE.md, rule 4) forbids a novelty claim until the literature
is read. The skeleton version of this file set out three possible honest outcomes:

- **(a)** the combination is well studied → the contribution is an open, reproducible
  implementation and a controlled comparison;
- **(b)** the combination is studied only in a different setting → the contribution is
  evaluation in an unstudied regime;
- **(c)** the specific composition and evaluation regime is unstudied → a stronger claim.

**The answer is (a), and more strongly than the skeleton anticipated.** Not only is the
combination studied, ORBIT's one surviving mechanism is named in the literature as existing
practice. §5 states what is left.

---

## 2. The works

### 2.1 MIRA — Kar, Kodialam & Lakshman, *Minimum Interference Routing of Bandwidth Guaranteed Tunnels with MPLS Traffic Engineering Applications*, IEEE JSAC 18(12):2566–2579, December 2000

*Read: abstract, §I–§III, §VIII (performance studies).*

**Problem.** Online routing of bandwidth-guaranteed MPLS tunnels: requests arrive one at a
time with no knowledge of future requests, and the algorithm must place each on a path with
sufficient residual capacity while keeping as much future demand routable as possible. The
paper proves the problem NP-hard and gives a heuristic.

**Mechanism.** A link is *critical* for an ingress–egress pair if loading it reduces that
pair's maxflow. MIRA computes maxflows between distinguished ingress–egress pairs, derives
critical-link weights from them, and then runs an ordinary shortest-path computation on those
weights — deferring load on links that future demands will need.

**Assumptions.** The set of potential ingress–egress pairs is known in advance; only residual
capacities are dynamic; no traffic splitting; a single traffic class.

**What it measures.** Rejection ratio, primarily. §VIII.F additionally measures rerouting
after a link cut: LSPs are routed on a 15-node sample network, one link is cut, and the same
algorithm reroutes the affected LSPs; 20 trials. MIRA reroutes more successfully than min-hop
and widest-shortest-path because it has left capacity open between ingress–egress pairs.

**Priorities.** None. §II.10 lists "preemption and setup priorities" as a *requirement the
algorithm must eventually accommodate*, deferred to a cited requirements document. MIRA
itself is priority-blind.

**How ORBIT relates.** ORBIT's B4 baseline (`orbit/algorithms/cspf.py`) is CSPF on residual
capacity, which is the family MIRA improves on, not MIRA itself. ORBIT does **not** implement
minimum-interference weights, so MIRA is not a baseline ORBIT beats — it is a stronger
capacity-aware baseline that ORBIT has not been compared against. That is a gap in this
project, and §5 records it as one.

### 2.2 B4 — Jain et al., *B4: Experience with a Globally-Deployed Software Defined WAN*, ACM SIGCOMM 2013

*Read: abstract, §1–§2, TE sections.*

**Problem.** Google's private inter-datacenter WAN. Links provisioned at 30–40% average
utilisation to survive failures are prohibitively expensive at their scale.

**What it does.** Centralised traffic engineering over OpenFlow switches: three traffic
classes ordered by priority (user data highest and lowest-volume, remote storage, large-scale
data copy), multipath forwarding, edge rate limiting, and **dynamic bandwidth reallocation in
the face of link and switch failures according to application priority**. Reported result:
many links at near 100% utilisation, all links averaging 70%.

**Directly relevant sentence.** B4's introduction states that WANs typically treat all bits
the same, so when the inevitable failure occurs all applications are treated equally "despite
their highly variable sensitivity to available capacity." That is ORBIT's motivating premise,
stated in a production paper thirteen years before this project.

**Artifact.** None. Production network, unreleased code and traces.

### 2.3 SWAN — Hong et al., *Achieving High Utilization with Software-Driven WAN*, ACM SIGCOMM 2013

*Read: abstract, §1–§2, §4.2 (allocation), §4.4 (failures), §5–§6 (evaluation).*

**Problem.** Inter-DC WAN utilisation is 40–60% on even the busy links. SWAN raises it by
centrally deciding how much each service may send and reconfiguring the data plane frequently.

**Allocation.** Strict priority across three classes — interactive, elastic, background —
with **approximate max-min fairness within a class**. Exact max-min fairness needs a long
sequence of LPs, so SWAN invokes multi-commodity flow in T steps and proves an
α-approximation. Lower classes are allocated from the capacity the higher classes leave.

**Scratch capacity.** SWAN leaves scratch capacity s ∈ [0, 50%] on every link (10% in
practice) and proves this admits a congestion-free update plan in at most ⌈1/s⌉−1 steps; in
practice 1–3 steps. The scratch is not wasted — background traffic is allowed to use it under
a bounded-congestion guarantee.

**Failures.** §4.4: agents report link and switch failures to the controller, which
immediately recomputes allocations. Failure recovery *time* is measured in the companion
technical report, not the paper.

**Evaluation.** A 5-DC testbed spanning three continents, plus data-driven simulation of two
production inter-DC WANs (one with >40 DCs). Headline: 60% more traffic than MPLS TE, within
2% of an optimal method with infinite rule capacity. 16–25% more traffic than MPLS TE even
without controlling ingress rates.

**Artifact.** None released.

**How ORBIT relates — and a correction ORBIT owes.** ORBIT's allocator is strict priority
between classes with max-min within, which is SWAN's allocation policy. And ORBIT's
`utilisation_ceiling` — measured in `a9-ceiling` to eliminate the modelled cascade at a
5% reserve — **is SWAN's scratch capacity under a different name**. SWAN reserves it to make
*updates* congestion-free; ORBIT's experiment reserves it to stop overload propagating. The
purpose differs, the mechanism does not. The ceiling was already rejected as a fifth ORBIT
mechanism on measurement grounds (`research/a8-findings.md`); this review adds that it would
not have been novel had it worked.

### 2.4 FFC — Liu, Kandula, Mahajan, Zhang & Gelernter, *Traffic Engineering with Forward Fault Correction*, ACM SIGCOMM 2014

*Read: abstract, §1–§3, §5.1 (priorities), §8 (evaluation).*

**Problem.** Centralised TE cannot react quickly to faults. In the WAN the authors study, a
link fails every 30 minutes on average; a single link failure produces over 20% link
oversubscription a fifth of the time; switch configuration updates fail 0.1–1% of the time
and a single switch rule update takes a median 10 ms and worst case over 200 ms.

**Mechanism.** Proactive rather than reactive, by analogy with forward error correction:
spread traffic so that *no congestion occurs under any combination of up to k faults*.
Formulated as an LP whose combinatorial constraint set is reduced to a "bounded M-sum"
problem and encoded in O(kn) constraints with sorting networks. Protection level is
configurable per fault type (control-plane, link, switch).

**Priorities.** §5.1: FFC extends to multiple priorities by computing the TE solution for the
higher-priority traffic first at its own protection level, then computing lower-priority
traffic **on residual capacity**. The paper states plainly that "this cascading computation is
already done to support multiple priorities," citing B4 and SWAN.

**This is the sentence that settles ORBIT's contribution claim.** ORBIT's M2 — priority-
ordered constrained routing on residual capacity — is described by FFC as existing practice
in 2014, attributed to two 2013 production systems. It is not novel and cannot be claimed as
such.

**What it measures.** Throughput overhead and data loss, on L-Net (O(50) sites, O(100)
switches, O(1000) links, with real capacity, traffic and fault logs) and S-Net (B4's 12-site
topology with synthesised demand). Three provisioning regimes. Headline: in well-provisioned
networks FFC reduces data loss by 7–130x with negligible throughput cost; in well-utilised
multi-priority networks it protects high-priority traffic from almost all loss, again with
negligible total throughput loss. Recommended protection level (kc, ke, kv) = (2, 1, 0).

**How ORBIT relates.** FFC's multi-priority headline — protect the high-priority class at
negligible aggregate throughput cost — is the same *shape* of result as ORBIT's H1/H3
finding, obtained four years earlier by a proactive method with a formal guarantee, on
production data. ORBIT's result differs in being reactive, heuristic, guarantee-free and
synthetic. ORBIT's contribution cannot be the finding; it can only be the artifact and the
specific measurements FFC did not make (per-class delivery under a controlled failure sweep,
and the ablation).

### 2.5 YATES — Kumar, Yu, Yuan, Foster, Kleinberg & Soulé, *YATES: Rapid Prototyping for Traffic Engineering Systems*, ACM SOSR 2018

*Read: full paper (7 pages).*

**This is the closest existing artifact to ORBIT's harness and the skeleton review did not
list it.** It is the single most important addition here.

YATES is an open-source (LGPLv3) framework for prototyping and evaluating TE systems, roughly
12k lines of OCaml, with a flow-level ("fluid model") simulator backend and an SDN backend for
validating simulation against hardware. It ships over a dozen TE systems including ECMP,
CSPF, KSP+MCF, SMORE and a prototype of FFC; models topologies from the Internet Topology
Zoo; generates demands with a gravity model; and includes a **failure model with random link
failures, SRLG failures and empirically-measured failure probability distributions**. It
provides a generic composable recovery function and a built-in "normalization recovery"
method, and it was calibrated against a content provider's network.

**What YATES does not model: traffic priority classes.** The paper describes a single traffic
aggregate throughout; there is no QoS, class-of-service, or differentiated-delivery concept
anywhere in it. Its metrics are congestion, throughput, loss, latency and churn — all
aggregate.

**How ORBIT relates.** YATES is strictly more mature as TE infrastructure and has the
failure model, the real topologies and the hardware validation ORBIT lacks. The one axis
ORBIT's harness has that YATES's does not is the **priority class as a first-class object**:
per-class demand, strict-priority allocation, per-class delivery ratio, per-class recovery
time, and preemption accounting. That is a narrow difference and it is the only one this
project can defend.

### 2.6 The standards ORBIT's mechanisms come from

Verified against the RFC Editor.

| Mechanism | Source | Verified citation | What it actually specifies |
|---|---|---|---|
| M1 protection | IP-FRR / LFA | Shand & Bryant, *IP Fast Reroute Framework*, RFC 5714, January 2010; Atlas & Zinin (eds.), *Basic Specification for IP Fast Reroute: Loop-Free Alternates*, RFC 5286, September 2008 | **Local** repair at the node adjacent to the failure, on a tens-of-milliseconds timescale, without waiting for network-wide reconvergence. RFC 5286 does not address capacity or priority. |
| M3 preemption | RSVP-TE | Awduche, Berger, Gan, Li, Srinivasan & Swallow, *RSVP-TE: Extensions to RSVP for LSP Tunnels*, RFC 3209, December 2001 | Setup priority and holding priority, 0–7. The **mechanism** for preemption only; the policy for when to preempt is explicitly out of scope. |
| M4 damping | BGP route flap damping | Villamizar, Chandra & Govindan, *BGP Route Flap Damping*, RFC 2439, November 1998 | Suppressing prefixes that flap repeatedly. Known downsides: persistent loops if applied to IBGP, suppression of stable secondary paths, and a need for careful parameter tuning. |
| Detection model | BFD | Katz & Ward, *Bidirectional Forwarding Detection (BFD)*, RFC 5880, June 2010 | Sub-second, down to ~50 ms, detection between adjacent forwarding engines. |

**RFC 5714 is worth quoting against ORBIT's own cascade result.** The framework states that
repair paths may push excessive traffic onto a link and cause congestion discard, that this
reduces the effectiveness of IPFRR, and that mechanisms to distribute repaired traffic so as
to minimise the effect are therefore desirable — while placing the capacity characteristics
of backup paths out of its own scope. ORBIT's cascade finding (recovering algorithms suffer
deeper cascades than static SPF) is a measurement of exactly the effect RFC 5714 names and
declines to address. That is the most defensible framing available for that result: not a
new phenomenon, a quantification of a known and explicitly-deferred one, inside a stated
model.

---

## 3. Positioning table

Filled from the readings above. "Reproducible artifact" means code a third party can run.

| Work | Capacity-aware | Priority-aware | Multi-failure | Reactive / proactive | Evaluation | Public artifact |
|---|---|---|---|---|---|---|
| OSPF/IS-IS reconvergence | no | no | yes | reactive | n/a | n/a |
| LFA / IP-FRR (RFC 5286/5714) | **no — explicitly out of scope** | no | single failure | proactive backup, local repair | n/a | n/a |
| MIRA (2000) | yes | no | single link cut, 20 trials | reactive reroute | 15-node synthetic | no |
| B4 (2013) | yes | yes, 3 classes | yes, in production | reactive | production WAN, ~12 sites | no |
| SWAN (2013) | yes | yes, 3 classes + max-min within | yes | reactive + scratch capacity | 5-DC testbed; sim of two production WANs | no |
| FFC (2014) | yes | yes, per-class protection level | **yes, guaranteed up to k** | **proactive** | L-Net O(100) switches; S-Net (B4 topology) | no |
| YATES (2018) | yes | **no** | yes, incl. SRLG | both (composable recovery) | Topology Zoo + SDN testbed | **yes, LGPLv3** |
| **ORBIT** | yes | yes, 4 classes | yes, incl. SRLG and cascade | reactive | synthetic, 50–500 nodes, seeded | **yes** |

Reading the table honestly: ORBIT is the only row with a *yes* in both the priority column and
the artifact column, and that is the entire distance between it and the prior work.

---

## 4. What is genuinely unstudied, and what is not

**Not unstudied — do not claim:**

1. Priority-ordered routing on residual capacity (ORBIT's M2). FFC §5.1 calls it existing
   practice and attributes it to B4 and SWAN.
2. Strict priority across classes with max-min fairness within a class. That is SWAN's
   allocator.
3. Reserving link headroom to avoid congestion (ORBIT's tested-and-rejected utilisation
   ceiling). That is SWAN's scratch capacity.
4. Protecting a high-priority class at negligible aggregate throughput cost. That is FFC's
   multi-priority headline, with a guarantee ORBIT does not have.
5. An open flow-level TE simulator with a failure model. That is YATES.
6. Congestion caused by repair paths. Named in RFC 5714 in 2010.

**Not covered by any of the above:**

1. **A controlled, per-class, paired comparison of recovery algorithms under a swept failure
   catalogue, in a runnable artifact.** B4, SWAN and FFC each evaluate one system against
   MPLS TE on private data. YATES enables the controlled comparison but has no priority
   classes to compare *per class*. Nobody in this set publishes a seeded harness where a
   third party can re-derive per-class delivery for five algorithms across a failure sweep.
2. **Mechanism ablation.** None of these papers disables a component of its own system and
   reports that it made no difference. ORBIT's ablation result is a kind of evidence the
   prior work does not produce, because production papers have no incentive to.

---

## 5. The contribution claim, after the measurements

The ablation is what forces this section to be short. `a11-mechanisms` (6,480 runs) put M1,
M3 and M4 into the conditions designed to make them fire — they fired, in 16% and 47% of runs
respectively — and returned **0 wins and 0 losses across all 36 cells** on every delivery
metric. All three are out of the claim. What remains of ORBIT's mechanism is M2: priority-
ordered constrained restoration on residual capacity.

**And M2 is not novel.** FFC §5.1 describes computing higher-priority traffic first and lower
priorities on residual capacity, and states that this "cascading computation is already done
to support multiple priorities", citing B4 and SWAN. That sentence rules out any mechanism
claim this project could have made.

So the contribution is not an algorithm. Stated at the width the evidence supports:

> **An open, seeded, laptop-runnable harness for comparing recovery algorithms per priority
> class under a swept failure catalogue, and the measurements it produces — including four
> negative results that the prior work's evaluation methods could not have surfaced.**

Each half against the literature:

**The harness.** YATES is the closest existing artifact and is more mature as TE
infrastructure — real topologies, an SDN backend, hardware validation. It models a single
traffic aggregate. ORBIT's harness treats the priority class as a first-class object: per-class
demand, strict-priority allocation with max-min within, per-class delivery ratio, per-class
recovery time, preemption accounting. B4, SWAN and FFC all model priority classes and none
released an artifact. **The intersection of "priority-aware" and "reproducible" is empty in
this set, and that is the entire gap.** It is a narrow claim and it is defensible.

**The measurements.** Four results here are not in the prior work, and the reason is
structural rather than accidental — a paper evaluating a production system has no incentive to
publish that a quarter of its own design does nothing:

1. **Three of four mechanisms are inert**, under conditions built to favour them, with the
   ablation and the firing counts both published.
2. **Recovery deepens cascades.** Static SPF suffers less than half the cascade depth of every
   recovering algorithm, robust across 168 parameter cells. RFC 5714 names this effect —
   repair paths causing congestion discard — and explicitly places it out of scope. This
   quantifies what the framework declined to address, inside a stated model.
3. **A utilisation ceiling eliminates the modelled cascade but is a net negative elsewhere**,
   and roughly 60% of its benefit comes from declining unplaceable flows rather than from the
   headroom. The headroom itself is SWAN's scratch capacity arriving at the same 5-10% figure
   for an unrelated reason, which is at least corroborating.
4. **The advantage grows with network size.** Over 50-500 nodes with mean degree pinned,
   ORBIT's CRITICAL delivery stays at 0.98-1.00 while CSPF falls from 0.998 to 0.966 — 13 wins,
   0 losses across 16 cells. None of MIRA, SWAN or FFC reports a size sweep at all.

**What must not be claimed**, restating §4: not the mechanism, not the allocator, not the
headroom idea, not "protects high-priority traffic cheaply" as a discovery — FFC published
that in 2014 with a guarantee, on production data, four years before this project's harness
had an equivalent in YATES.
