# Literature Review — starter

Status: **skeleton with a reading list. No claims may be made from this file until the papers are
actually read.**

## How to use this file

Every reference below is a real, well-known work that I am confident exists. **You must still
verify each one** (venue, year, page numbers, DOI) via Google Scholar, the ACM/IEEE Digital
Library, or the IETF datatracker before it appears in a citation. Add nothing you have not read
at least the abstract, introduction, and conclusion of.

For each paper, fill in: **What problem it solves → What it assumes → What it measures → How
ORBIT differs.** A literature review that only summarises is padding; one that positions your
work is the point.

---

## 1. Why this review must exist before any novelty claim

ORBIT's mechanisms are compositions of established techniques. The review's job is to establish
precisely **which combination has and has not been studied**, so that the paper's contribution
claim is calibrated. Three possible honest outcomes:

- **(a)** The combination is well studied → contribution becomes "an open, reproducible
  implementation and a controlled comparison on a public harness." Still worthwhile.
- **(b)** The combination is studied only in a different setting (e.g. optical, MPLS-TE, datacentre)
  → contribution becomes "evaluation of a known approach in an unstudied regime." Good.
- **(c)** The specific composition + evaluation regime is genuinely unstudied → a stronger claim,
  and only then.

Write down which outcome you land on. Do not decide in advance.

---

## 2. Reading list

### Foundations — shortest path and IP routing
- Dijkstra, E. W. (1959). *A note on two problems in connexion with graphs.* Numerische
  Mathematik 1, 269–271.
- Moy, J. (1998). *OSPF Version 2.* RFC 2328, IETF.
- Hopps, C. (2000). *Analysis of an Equal-Cost Multi-Path Algorithm.* RFC 2992, IETF.
- Bertsekas, D. & Gallager, R. *Data Networks* (2nd ed., 1992) — the max-min fairness chapter is
  the reference for ORBIT's allocator.

### Fast reroute and protection (this is where M1 comes from)
- Shand, M. & Bryant, S. (2010). *IP Fast Reroute Framework.* RFC 5714, IETF.
- Atlas, A. & Zinin, A. (2008). *Basic Specification for IP Fast Reroute: Loop-Free Alternates.*
  RFC 5286, IETF.
- Awduche, D. et al. (2001). *RSVP-TE: Extensions to RSVP for LSP Tunnels.* RFC 3209, IETF —
  source of the setup/holding priority preemption model (M3).
- Filsfils, C. et al. (2018). *Segment Routing Architecture.* RFC 8402, IETF.

### Failure detection and stability
- Katz, D. & Ward, D. (2010). *Bidirectional Forwarding Detection (BFD).* RFC 5880, IETF —
  the basis for the detection-interval model.
- Villamizar, C., Chandra, R. & Govindan, R. (1998). *BGP Route Flap Damping.* RFC 2439, IETF —
  prior art for M4.

### Traffic engineering and capacity-aware routing (this is where M2 and the B4 baseline come from)
- Fortz, B. & Thorup, M. (2000). *Internet Traffic Engineering by Optimizing OSPF Weights.*
  IEEE INFOCOM.
- Kodialam, M. & Lakshman, T. V. (2000). *Minimum Interference Routing with Applications to MPLS
  Traffic Engineering.* IEEE INFOCOM. (MIRA — the closest classical relative of ORBIT's M2.)
- Jain, S. et al. (2013). *B4: Experience with a Globally-Deployed Software Defined WAN.*
  ACM SIGCOMM.
- Hong, C.-Y. et al. (2013). *Achieving High Utilization with Software-Driven WAN.* ACM SIGCOMM
  (SWAN). **Read this one carefully — it uses priority classes and is the most important
  positioning reference for ORBIT.**
- Liu, H. H. et al. (2014). *Traffic Engineering with Forward Fault Correction.* ACM SIGCOMM
  (FFC) — proactive protection against multiple simultaneous failures; directly adjacent to
  ORBIT's problem statement.

### Topology models and datasets
- Waxman, B. M. (1988). *Routing of Multipoint Connections.* IEEE JSAC 6(9).
- Barabási, A.-L. & Albert, R. (1999). *Emergence of Scaling in Random Networks.* Science 286.
- Knight, S. et al. (2011). *The Internet Topology Zoo.* IEEE JSAC 29(9). (Real ISP topologies;
  check the licence terms before redistributing any topology file in the repo.)

### Simulation and emulation methodology
- Riley, G. F. & Henderson, T. R. (2010). *The ns-3 Network Simulator.* In *Modeling and Tools for
  Network Simulation*, Springer.
- Lantz, B., Heller, B. & McKeown, N. (2010). *A Network in a Laptop: Rapid Prototyping for
  Software-Defined Networks.* ACM HotNets. (Mininet — relevant to the optional cross-validation.)

### Search terms for finding the gap
`priority-aware fast reroute` · `differentiated restoration multi-failure` ·
`preemption traffic engineering QoS restoration` · `SRLG-disjoint backup path computation` ·
`network resilience benchmark reproducible` · `flow-level network simulator evaluation`

---

## 3. Positioning table (fill this in as you read)

| Work | Capacity-aware? | Priority-aware? | Multi-failure? | Reproducible artifact? | How ORBIT differs |
|---|---|---|---|---|---|
| OSPF/IS-IS reconvergence | no | no | yes | n/a | ORBIT is both |
| LFA / IP-FRR | no | no | single, mostly | n/a | ORBIT adds capacity + priority |
| MIRA | yes | no | no | no | |
| SWAN | yes | yes | limited | no | |
| FFC | yes | partly | yes | no | |
| **ORBIT** | yes | yes | yes | **yes — this is likely the real differentiator** | |

Note where that last column is heading: **the reproducible open harness may be ORBIT's most
honest and most defensible contribution.** Most of the systems above were evaluated on proprietary
production networks with unreleased code. A laptop-runnable, seeded, fully reproducible
comparison harness for priority-aware recovery has genuine value even if every mechanism inside
it is known — and that claim is one the project can actually substantiate.
