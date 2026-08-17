"""Committed experiment specifications, fixed before results exist (B3 rule 6)."""

from __future__ import annotations

from orbit.detect import ControlMode
from orbit.scenarios import (
    ExperimentSpec,
    FailureScenario,
    ScenarioSpec,
    TopologyFamily,
    scenario_grid,
)

FAMILIES = (
    TopologyFamily.GRID,
    TopologyFamily.RING,
    TopologyFamily.WAXMAN,
    TopologyFamily.SCALE_FREE,
)

FAILURES = (
    FailureScenario.NONE,
    FailureScenario.RANDOM_NODE_10,
    FailureScenario.RANDOM_NODE_30,
    FailureScenario.CRITICAL_LINK,
    FailureScenario.REGIONAL_SRLG,
    FailureScenario.CONGESTION_SURGE,
    FailureScenario.CASCADING,
)

A8_HEADLINE = ExperimentSpec(
    name="a8-headline",
    scenarios=scenario_grid(FAMILIES, FAILURES, nodes=60, flows=150, offered_load=0.7, ticks=150),
    trials=30,
)

A8_DUAL_CONTROL = ExperimentSpec(
    name="a8-dual-control",
    scenarios=tuple(
        ScenarioSpec(
            family=TopologyFamily.WAXMAN,
            nodes=60,
            flows=150,
            offered_load=0.7,
            ticks=150,
            failure=failure,
            control_mode=mode,
        )
        for failure in (FailureScenario.CRITICAL_LINK, FailureScenario.RANDOM_NODE_30)
        for mode in (ControlMode.CENTRALISED, ControlMode.DISTRIBUTED)
    ),
    trials=30,
)

A8_LOAD_SWEEP = ExperimentSpec(
    name="a8-load-sweep",
    scenarios=tuple(
        ScenarioSpec(
            family=TopologyFamily.WAXMAN,
            nodes=60,
            flows=150,
            offered_load=load,
            ticks=150,
            failure=FailureScenario.CRITICAL_LINK,
        )
        for load in (0.3, 0.5, 0.7, 0.9, 1.2)
    ),
    trials=30,
)

SMOKE = ExperimentSpec(
    name="smoke",
    scenarios=(ScenarioSpec(nodes=25, flows=40, ticks=50),),
    trials=3,
)


A8_ABLATION = ExperimentSpec(
    name="a8-ablation",
    scenarios=tuple(
        ScenarioSpec(
            family=family,
            nodes=60,
            flows=150,
            offered_load=0.9,
            ticks=150,
            failure=failure,
        )
        for family in (TopologyFamily.WAXMAN, TopologyFamily.SCALE_FREE)
        for failure in (FailureScenario.CONGESTION_SURGE, FailureScenario.CRITICAL_LINK)
    ),
    algorithms=(
        "cspf",
        "orbit",
        "orbit-no-protection",
        "orbit-no-preemption",
        "orbit-no-damping",
        "orbit-no-fallback",
        "orbit-restoration-only",
    ),
    trials=30,
)

A8_CASCADE = ExperimentSpec(
    name="a8-cascade",
    scenarios=tuple(
        ScenarioSpec(
            family=family,
            nodes=60,
            flows=150,
            offered_load=0.9,
            ticks=150,
            failure=FailureScenario.CASCADING,
        )
        for family in FAMILIES
    ),
    trials=30,
)


CASCADE_THRESHOLDS = (0.75, 0.80, 0.85, 0.90, 0.95, 0.98, 1.00)
CASCADE_DWELLS = (1, 3, 5, 10, 20, 40)

A9_CASCADE_SWEEP = ExperimentSpec(
    name="a9-cascade-sweep",
    scenarios=tuple(
        ScenarioSpec(
            family=family,
            nodes=60,
            flows=150,
            offered_load=load,
            ticks=150,
            failure=FailureScenario.CASCADING,
            cascade_threshold=threshold,
            cascade_dwell_ticks=dwell,
        )
        for family in (TopologyFamily.WAXMAN, TopologyFamily.SCALE_FREE)
        for load in (0.7, 0.9)
        for threshold in CASCADE_THRESHOLDS
        for dwell in CASCADE_DWELLS
    ),
    trials=30,
)


A9_CEILING = ExperimentSpec(
    name="a9-ceiling",
    scenarios=tuple(
        ScenarioSpec(
            family=family,
            nodes=60,
            flows=150,
            offered_load=0.9,
            ticks=150,
            failure=FailureScenario.CASCADING,
            cascade_threshold=threshold,
            cascade_dwell_ticks=3,
        )
        for family in (TopologyFamily.WAXMAN, TopologyFamily.SCALE_FREE)
        for threshold in (0.90, 0.95, 0.98)
    ),
    algorithms=(
        "spf-static",
        "cspf",
        "orbit",
        "orbit-no-fallback",
        "orbit-ceiling-1.0",
        "orbit-ceiling-0.95",
        "orbit-ceiling-0.9",
        "orbit-ceiling-0.8",
        "orbit-ceiling-0.7",
        "orbit-ceiling-0.6",
    ),
    trials=30,
)
