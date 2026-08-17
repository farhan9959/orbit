"""YAML topology loader (requirement F2b)."""

from __future__ import annotations

import pytest

from orbit.errors import ValidationError
from orbit.model import LinkState
from orbit.topospec import topology_from_yaml

TRIANGLE = """
name: triangle
nodes:
  - id: a
  - id: b
  - id: c
links:
  - {src: a, dst: b, capacity_mbps: 40}
  - {src: b, dst: c, capacity_mbps: 40}
  - {src: c, dst: a, capacity_mbps: 40}
"""


def test_a_valid_spec_builds_the_topology_it_describes() -> None:
    topology = topology_from_yaml(TRIANGLE)
    assert sorted(topology.nodes) == ["a", "b", "c"]
    assert len(topology.links) == 6, "three cables, each two directed links"
    assert topology.link("a>b").capacity_mbps == 40.0
    assert topology.link("b>a").capacity_mbps == 40.0


def test_a_cable_shares_one_srlg_so_a_conduit_cut_takes_both_directions() -> None:
    topology = topology_from_yaml(TRIANGLE)
    assert topology.link("a>b").srlg == topology.link("b>a").srlg
    assert topology.link("a>b").srlg == frozenset({"cable:a-b"})


def test_a_unidirectional_link_emits_one_direction_only() -> None:
    topology = topology_from_yaml(
        "nodes: [{id: a}, {id: b}]\nlinks: [{src: a, dst: b, bidirectional: false}]\n"
    )
    assert sorted(topology.links) == ["a>b"]


def test_defaults_apply_when_a_link_omits_them() -> None:
    topology = topology_from_yaml("nodes: [{id: a}, {id: b}]\nlinks: [{src: a, dst: b}]\n")
    link = topology.link("a>b")
    assert (link.capacity_mbps, link.prop_delay_ms, link.state) == (100.0, 1.0, LinkState.UP)


def test_an_explicit_srlg_overrides_the_derived_cable_tag() -> None:
    topology = topology_from_yaml(
        "nodes: [{id: a}, {id: b}]\nlinks: [{src: a, dst: b, srlg: [conduit:A12]}]\n"
    )
    assert topology.link("a>b").srlg == frozenset({"conduit:A12"})


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("nodes: [{id: a}, {id: b}]\nlinks: [{src: a, dst: z}]\n", "unknown node 'z'"),
        ("nodes: [{id: a}, {id: b}]\nlinks: [{src: a, dst: a}]\n", "self-loop"),
        ("nodes: [{id: a}, {id: a}]\nlinks: [{src: a, dst: a}]\n", "duplicate node id 'a'"),
        (
            "nodes: [{id: a}, {id: b}]\nlinks: [{src: a, dst: b}, {src: b, dst: a}]\n",
            "duplicate link id",
        ),
        (
            "nodes: [{id: a}, {id: b}]\nlinks: [{src: a, dst: b, capacity_mpbs: 10}]\n",
            "capacity_mpbs",
        ),
        (
            "nodes: [{id: a}, {id: b}]\nlinks: [{src: a, dst: b, capacity_mbps: -5}]\n",
            "capacity_mbps",
        ),
        ("nodes: [{id: a}]\nlinks: [{src: a, dst: a}]\n", "nodes"),
        ("nodes: [{id: a}, {id: b}]\nlinks: []\n", "links"),
        ("- just\n- a\n- list\n", "expected a mapping"),
        ("nodes: [{id: a}, {id: b}]\nlinks: [{src: a, dst: b}\n", "not valid YAML"),
    ],
)
def test_an_invalid_spec_is_rejected_with_a_message_that_locates_the_problem(
    document: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        topology_from_yaml(document)


def test_the_error_names_the_offending_field_path() -> None:
    with pytest.raises(ValidationError, match=r"links\.1\.capacity_mbps"):
        topology_from_yaml(
            "nodes: [{id: a}, {id: b}, {id: c}]\n"
            "links:\n"
            "  - {src: a, dst: b}\n"
            "  - {src: b, dst: c, capacity_mbps: 0}\n"
        )


def test_a_loaded_topology_is_usable_by_the_engine() -> None:
    """The whole point of F2b: a hand-written file must run like a generated one."""
    from orbit.algorithms import StaticShortestPath
    from orbit.engine import Simulation, SimulationConfig
    from orbit.model import Flow, Priority

    topology = topology_from_yaml(TRIANGLE)
    flows = (Flow("f0", "a", "c", demand_mbps=10.0, priority=Priority.CRITICAL),)
    summary = Simulation(
        topology, flows, StaticShortestPath(), SimulationConfig(validate_each_recompute=False)
    ).measure(20)
    assert summary.overall.pdr == pytest.approx(1.0)


def test_the_cli_validates_a_spec_file_and_reports_it(tmp_path, capsys) -> None:
    import json

    from orbit.cli import main

    path = tmp_path / "t.yaml"
    path.write_text(TRIANGLE, encoding="utf-8")
    assert main(["topology", "--file", str(path)]) == 0
    reported = json.loads(capsys.readouterr().out)
    assert (reported["nodes"], reported["links"]) == (3, 6)


def test_the_cli_reports_a_missing_file_as_a_validation_error(tmp_path) -> None:
    from orbit.cli import main

    with pytest.raises(ValidationError, match="topology file"):
        main(["topology", "--file", str(tmp_path / "absent.yaml")])


def test_a_run_can_be_driven_from_a_spec_file(tmp_path, capsys) -> None:
    """F2b's actual purpose: the loaded topology reaches the experiment runner."""
    import json

    from orbit.cli import main

    path = tmp_path / "t.yaml"
    path.write_text(TRIANGLE, encoding="utf-8")
    assert main(["run", "--topology-file", str(path), "--flows", "6", "--ticks", "20"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["family"] == "file"
    assert record["nodes"] == 3
