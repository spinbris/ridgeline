"""SRA-02 S-C deliverable 1 - the falsifiable CPM joint test.

The property: ``run_integrated_simulation_stage3``'s **CPM schedule arm** consumes
the same per-risk severity uniform as the cost arm.

Why this file exists (brief Amendment 1 A1.3 / A1.5). The sharing is real but
*architectural*: the caller injects one ``severity_uniforms_by_risk_id`` dict, the
cost arm receives it whole (``integrated_simulation_stage3.py:468-472``) and the
schedule arm is column-projected off the same dict (``:476-479``). Two tests were
written to state that falsifiably and neither does:

* ``test_sr11_integrated_simulation_stage3.py:281`` correlates the injected uniform
  against the **cost** arm alone, despite a docstring promising cost-versus-schedule.
* ``:331`` asserts ``n_risks``, ``n_iter`` and ``risk_ids`` ordering - shape and order.
  A schedule arm fed independently drawn uniforms passes all three.

So the CPM arm has had no test capable of failing on the property that
JOINTSAMP-01 records as reading the integrated P80 low when it breaks.

Method, per A1.5: the extension test's technique
(``test_integrated_simulation_severity_uniform_extension.py:285``) applied to
stage3 rather than to ``run_integrated_simulation`` - inject an all-low and an
all-high uniform dict and require the CPM schedule output to move with them.

**Assert on ``schedule_result.project_finish_days``, not on
``schedule_days_array``.** The latter is baseline-subtracted at
``integrated_simulation_stage3.py:508-510``
(``project_finish_days - min(project_finish_days)``), so under a *constant*
injected uniform it is normalised against its own floor and collapses toward zero
for both the low and the high run. A test written against it would compare two
near-zero arrays and pass for the wrong reason - which is the shape this file was
created to stop shipping.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.integrated.integrated_simulation_stage3 import (
    run_integrated_simulation_stage3,
)
from tests.integrated.test_sr11_integrated_simulation_stage3 import _build_inputs

#: Far enough apart that a real response is unambiguous, and both strictly inside
#: (0, 1) so neither lands on a distribution endpoint.
_U_LOW = 0.05
_U_HIGH = 0.95


def _run_with_constant_uniform(u: float, *, iterations: int = 200, seed: int = 42):
    """Run stage3 with every risk's severity uniform pinned to ``u``.

    Firing uniforms are untouched, so the fire pattern is identical between two
    runs at the same seed and the only thing that differs is severity.
    """
    cfg, risks, scope_df, graph, drivers, severity, xer_tables = _build_inputs(
        iterations=iterations, seed=seed,
    )
    injected = {
        rid: np.full(iterations, u, dtype=np.float32) for rid in severity
    }
    return run_integrated_simulation_stage3(
        cfg,
        risks=risks,
        risk_scope_df=scope_df,
        schedule_graph=graph,
        risk_drivers=drivers,
        xer_tables=xer_tables,
        severity_uniforms_by_risk_id=injected,
    )


@pytest.fixture(scope="module")
def low_high():
    return (
        _run_with_constant_uniform(_U_LOW),
        _run_with_constant_uniform(_U_HIGH),
    )


def test_cpm_schedule_arm_moves_with_the_injected_severity_uniform(low_high):
    """THE gate. Raising the injected severity uniform must lengthen the CPM
    schedule arm's project finish.

    A schedule arm that drew its own uniforms instead of projecting the injected
    dict produces identical output for both runs (same seed, same rng stream), so
    this assertion fails. That is the decoupling the red-first proof performs at
    ``integrated_simulation_stage3.py:476-479``.
    """
    low, high = low_high
    lo = np.asarray(low.schedule_result.project_finish_days, dtype=np.float64)
    hi = np.asarray(high.schedule_result.project_finish_days, dtype=np.float64)

    assert hi.mean() > lo.mean(), (
        "CPM schedule arm did not respond to the injected severity uniform - "
        f"low mean {lo.mean():.6f} vs high mean {hi.mean():.6f}. Either the arm "
        "is drawing its own uniforms or the projection at "
        "integrated_simulation_stage3.py:476-479 is broken."
    )


def test_cost_arm_moves_too_so_the_injection_demonstrably_took_effect(low_high):
    """Control for the gate above.

    Without this, a run in which the injected dict was ignored *entirely* - by
    both arms - would leave the schedule assertion failing for an unrelated
    reason and the diagnosis pointing at the wrong module. This pins the
    injection itself as working, so a red on the schedule gate is attributable to
    the schedule arm.
    """
    low, high = low_high
    lo = np.asarray(low.cost_result["cost_dollars_array"], dtype=np.float64)
    hi = np.asarray(high.cost_result["cost_dollars_array"], dtype=np.float64)
    assert hi.mean() > lo.mean()


def test_both_arms_respond_on_the_same_iterations(low_high):
    """Sharing is a per-iteration property, not an aggregate one.

    The means moving together is necessary but not sufficient: two arms driven by
    different uniforms could both rise on average. This requires the *same*
    iterations to be the ones that changed, which an independently-drawn schedule
    arm does not satisfy - its per-iteration deltas would be identically zero
    while the cost arm's are not.
    """
    low, high = low_high
    sched_delta = (
        np.asarray(high.schedule_result.project_finish_days, dtype=np.float64)
        - np.asarray(low.schedule_result.project_finish_days, dtype=np.float64)
    )
    cost_delta = (
        np.asarray(high.cost_result["cost_dollars_array"], dtype=np.float64)
        - np.asarray(low.cost_result["cost_dollars_array"], dtype=np.float64)
    )
    moved_cost = cost_delta > 0
    assert moved_cost.any(), "no iteration moved on the cost arm - fixture is inert"
    # Every iteration whose cost moved is an iteration where a dual-coded risk
    # fired; the schedule arm shares that risk's uniform, so it must have moved
    # there too rather than somewhere else.
    assert (sched_delta[moved_cost] > 0).any(), (
        "no iteration moved on BOTH arms - the schedule arm is not sharing the "
        "cost arm's severity uniform"
    )
    assert not np.allclose(sched_delta, 0.0), (
        "schedule arm is completely inert to the injected uniform"
    )


def test_schedule_days_array_is_the_wrong_surface_for_this_property():
    """Guards the reasoning in this module's docstring rather than the engine.

    ``schedule_days_array`` is baseline-subtracted, so under a constant injected
    uniform it collapses toward zero for BOTH runs. Recorded as an executable
    statement so a later edit that "simplifies" the gate onto this array is
    caught by a test rather than by review - it would look like a passing gate.
    """
    low = _run_with_constant_uniform(_U_LOW, iterations=50)
    high = _run_with_constant_uniform(_U_HIGH, iterations=50)
    lo = np.asarray(low.schedule_days_array, dtype=np.float64)
    hi = np.asarray(high.schedule_days_array, dtype=np.float64)
    # Both floor at zero by construction, which is exactly why a mean comparison
    # on this array is not a statement about the shared uniform.
    assert lo.min() == 0.0 and hi.min() == 0.0
    # And the absolute surface the real gate uses does separate them.
    assert (
        np.asarray(high.schedule_result.project_finish_days).mean()
        > np.asarray(low.schedule_result.project_finish_days).mean()
    )
