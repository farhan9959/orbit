"""Load a hand-written topology from a YAML specification (requirement F2b).

This is the other half of F2: `orbit/generators/families.py` produces synthetic families from
a seed, and this module reads a topology someone wrote down. The two paths converge on the
same `Topology` constructor, so a loaded topology is validated by exactly the same rules as a
generated one (docs/04-threat-model.md T4 — the model constructor is the innermost trust
boundary and every path must cross it).

Why Pydantic on top of the model's own validation
-------------------------------------------------
`orbit/model/_validate.py` already rejects a negative capacity or a NaN delay, and it is the
authority. What it cannot do is say *where* in a 200-line YAML file the mistake is: it sees a
float, not a document. Pydantic reports `links.14.capacity_mbps`, which is the difference
between a usable error and a shrug. The two layers are not redundant — the schema layer
localises, the model layer decides.

Assumptions and failure modes:
* **No I/O here.** `orbit/` is a pure library (see the package docstring), so this module
  parses text and never opens a file. The CLI reads the file.
* `yaml.safe_load` only. A topology file is untrusted structured data; `yaml.load` would
  make it executable (T4).
* `extra="forbid"` everywhere. A misspelled key is a silent behaviour change otherwise —
  `capacity_mpbs` would leave the link on its default capacity and the run would look fine.
* A cable is two directed links sharing an SRLG, matching the generators. `bidirectional:
  false` emits one direction only, which is legal and occasionally what a spec means.
* Connectivity is *not* repaired. The generators repair it because a disconnected random
  graph is a bad benchmark input; a hand-written file that is disconnected is what the
  author asked for, and the engine handles partitions by blackholing and censoring.
"""

from __future__ import annotations

from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from orbit.errors import ValidationError
from orbit.model import Link, LinkId, Node, NodeId, Topology

MAX_SPEC_NODES = 5000
MAX_SPEC_LINKS = 50_000

Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")]


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Identifier
    srlg: tuple[Identifier, ...] = ()


class LinkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    src: Identifier
    dst: Identifier
    capacity_mbps: float = Field(default=100.0, gt=0.0, le=1e7)
    prop_delay_ms: float = Field(default=1.0, ge=0.0, le=1e5)
    srlg: tuple[Identifier, ...] = ()
    bidirectional: bool = True
    id: Identifier | None = None
    """Only meaningful for a unidirectional link; a cable derives both ids from its ends."""


class TopologySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="unnamed", min_length=1, max_length=128)
    nodes: tuple[NodeSpec, ...] = Field(min_length=2, max_length=MAX_SPEC_NODES)
    links: tuple[LinkSpec, ...] = Field(min_length=1, max_length=MAX_SPEC_LINKS)


def topology_from_yaml(text: str) -> Topology:
    """Parse a YAML topology specification and build the `Topology` it describes.

    Raises `orbit.errors.ValidationError` for every rejection — malformed YAML, a schema
    violation, or a model-level violation — so a caller has one exception type to handle.
    """
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValidationError(f"topology spec: not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ValidationError(
            f"topology spec: expected a mapping at the top level, got {type(document).__name__}"
        )

    try:
        spec = TopologySpec.model_validate(document)
    except PydanticValidationError as exc:
        raise ValidationError(f"topology spec: {_explain(exc)}") from exc

    return build_topology_spec(spec)


def build_topology_spec(spec: TopologySpec) -> Topology:
    known: set[str] = set()
    nodes: list[Node] = []
    for node in spec.nodes:
        if node.id in known:
            raise ValidationError(f"topology spec: duplicate node id {node.id!r}")
        known.add(node.id)
        nodes.append(Node(NodeId(node.id), srlg=frozenset(node.srlg)))

    links: list[Link] = []
    seen: set[str] = set()
    for position, link in enumerate(spec.links):
        for endpoint, role in ((link.src, "src"), (link.dst, "dst")):
            if endpoint not in known:
                raise ValidationError(
                    f"topology spec: links.{position}.{role} references unknown node {endpoint!r}"
                )
        if link.src == link.dst:
            raise ValidationError(f"topology spec: links.{position} is a self-loop on {link.src!r}")

        srlg = frozenset(link.srlg) or frozenset({f"cable:{link.src}-{link.dst}"})
        directions = (
            ((link.src, link.dst), (link.dst, link.src))
            if link.bidirectional
            else ((link.src, link.dst),)
        )
        for index, (tail, head) in enumerate(directions):
            link_id = link.id if link.id is not None and index == 0 else f"{tail}>{head}"
            if link_id in seen:
                raise ValidationError(f"topology spec: duplicate link id {link_id!r}")
            seen.add(link_id)
            links.append(
                Link(
                    LinkId(link_id),
                    NodeId(tail),
                    NodeId(head),
                    capacity_mbps=link.capacity_mbps,
                    prop_delay_ms=link.prop_delay_ms,
                    srlg=srlg,
                )
            )

    return Topology(nodes, links)


def _explain(exc: PydanticValidationError) -> str:
    """One line per problem, each naming the path into the document."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
        for error in exc.errors()
    )
