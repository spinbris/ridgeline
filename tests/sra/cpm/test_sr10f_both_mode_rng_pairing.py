"""SR10.F — lock test for "both"-mode pass-1-vs-pass-2 RNG pairing.

``run_schedule_mc(..., criticality_measurement_mode="both")`` runs the
Mode-conditioned and Mode-independent passes over ONE shared set of
per-batch sub-generators (spawned once, each restored to its
pre-first-pass state before the second pass — SR10.F). The methodological
claim SR10.A/B's divergence audit rests on is that the two passes draw
*identical* Bernoulli fires and PERT magnitudes, so any divergence between
them is attributable solely to the per-risk Mode multiplier, not to
independent Monte Carlo sampling noise.

The invariant this file locks: **when the Mode multiplier is identical in
both passes, the two passes must produce bit-identical output.** An
all-Series risk set gives multiplier 1.0 in both the Mode-conditioned pass
(``TEST_MODE_MULTIPLIERS["Series"] == 1.0``) and the Mode-independent pass
(override 1.0), so a correctly-paired engine must reproduce pass 1 exactly
in pass 2.

Why this test did not exist before SR10.F
-----------------------------------------
``test_cpm_mode_independent_criticality.test_both_mode_conditioned_half_matches_standalone``
compares "both" mode's *pass 1* against an *independent standalone*
``mode_conditioned`` run — both the first-ever ``.spawn()`` from a
freshly-seeded rng, so they matched regardless of the pairing bug. No test
compared "both" mode's pass 1 against its own pass 2. That is the gap the
bug (SR10.F §2/§4) slipped through; this file closes it.

Fixture-design guards (brief §4.1, Director 08/07/2026)
-------------------------------------------------------
1. **Non-degenerate topology.** Two equal-length parallel chains that
   genuinely compete for the critical path, NOT a linear chain. In a
   linear chain every driving activity has ``criticality_index == 1.0``
   regardless of the draws, so ``CI == mode_independent_CI`` would hold
   even on the unpaired (pre-fix) engine — a vacuous pass. Here the
   per-activity CI is fractional and draw-sensitive (asserted explicitly
   below), so the CI equality assertion actually witnesses the pairing.
2. **Finish-array equality is the PRIMARY assertion.** The per-iteration
   ``project_finish_hours`` diverges between an unpaired pass 1 and pass 2
   even when CI happens not to; it is the field that actually detects the
   unpaired state (the ~47% iteration difference in the brief's §2 smoke
   check was a finish-array difference). CI equality is secondary.

Fail-first evidence: this test was demonstrated RED on the pre-fix engine
(finish-array assertion) and GREEN post-fix — see the SR10.F close-out in
the stage log.
"""

from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import numpy as np
import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.cpm_simulation import ScheduleMCConfig, run_schedule_mc
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from src.sra.cpm.risk_driver_schema import RiskDriver, RiskMode


_DEFAULT_CAL = Calendar()


def _activity(aid: str, *, duration_hours: float = 80.0) -> Activity:
    return Activity(
        id=aid,
        code=aid,
        name=aid,
        task_type="TT_Task",
        original_duration_hours=duration_hours,
        total_float_hours=None,
        calendar_id=None,
    )


def _make_graph(
    activities: list[Activity],
    links: list[Link],
    *,
    topo_order: list[str],
) -> ScheduleGraph:
    acts = {a.id: a for a in activities}
    for link in links:
        if link.pred_id in acts:
            acts[link.pred_id].successor_links.append(link)
        if link.succ_id in acts:
            acts[link.succ_id].predecessor_links.append(link)
    return ScheduleGraph(
        activities=acts,
        links=list(links),
        topo_order=topo_order,
        project_default_calendar=_DEFAULT_CAL,
    )


def _competing_two_path_graph() -> ScheduleGraph:
    """Two equal-length parallel chains meeting at one milestone.

    start → p1a → p1b → end
    start → p2a → p2b → end

    All durations 80 working hours, so the two chains are tied without
    risk. With a firing risk on each chain, whichever chain draws the
    larger extension in a given iteration wins the critical path — the
    per-activity criticality index is genuinely fractional and sensitive
    to the underlying Bernoulli/PERT draws (the non-degeneracy §4.1
    requires).
    """
    acts = [
        _activity("start", duration_hours=0.0),
        _activity("p1a"),
        _activity("p1b"),
        _activity("p2a"),
        _activity("p2b"),
        _activity("end", duration_hours=0.0),
    ]
    links = [
        Link(pred_id="start", succ_id="p1a", link_type="FS", lag_hours=0.0),
        Link(pred_id="p1a", succ_id="p1b", link_type="FS", lag_hours=0.0),
        Link(pred_id="p1b", succ_id="end", link_type="FS", lag_hours=0.0),
        Link(pred_id="start", succ_id="p2a", link_type="FS", lag_hours=0.0),
        Link(pred_id="p2a", succ_id="p2b", link_type="FS", lag_hours=0.0),
        Link(pred_id="p2b", succ_id="end", link_type="FS", lag_hours=0.0),
    ]
    return _make_graph(
        acts, links,
        topo_order=["start", "p1a", "p1b", "p2a", "p2b", "end"],
    )


def _series_driver(
    risk_id: str, *, affected: tuple[str, ...], probability: float
) -> RiskDriver:
    """A Series-mode risk — multiplier 1.0 under BOTH measurement passes.

    ``mode="Series"`` gives ``TEST_MODE_MULTIPLIERS["Series"] == 1.0`` in the
    Mode-conditioned pass, and the Mode-independent pass overrides every
    multiplier to 1.0. Identical multiplier ⇒ paired draws ⇒ bit-identical
    output, which is exactly the invariant under test.
    """
    mode: RiskMode = "Series"
    return RiskDriver(
        risk_id=risk_id,
        affected_activity_ids=affected,
        injection_method="additive_pert_days",
        opt_pert=5.0,
        ml_pert=10.0,
        pess_pert=20.0,
        probability=probability,
        derived_at_run_time=False,
        workshop_validated=True,
        mode=mode,
    )


def _multiplier_identical_drivers() -> dict[str, RiskDriver]:
    """One Series risk on each competing chain, both firing ~half the
    time so the two chains trade the critical path across iterations.
    """
    return {
        "R_p1": _series_driver("R_p1", affected=("p1a", "p1b"), probability=0.5),
        "R_p2": _series_driver("R_p2", affected=("p2a", "p2b"), probability=0.5),
    }


# ---------------------------------------------------------------------------
# The lock test — pass 1 vs pass 2 within a single "both" call
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [1, 42, 7])
def test_both_mode_pass1_pass2_paired_when_multiplier_identical(seed: int) -> None:
    """Within one ``criticality_measurement_mode="both"`` call, an
    all-Series (multiplier-identical) risk set on a competing two-path
    network must produce bit-identical Mode-conditioned and
    Mode-independent output.

    PRIMARY assertion: ``project_finish_hours ==
    mode_independent_project_finish_hours`` bit-for-bit — this is the
    field that diverges on the pre-fix (unpaired) engine.

    SECONDARY assertion: ``criticality_index ==
    mode_independent_criticality_index`` bit-for-bit — meaningful only
    because the fixture's CI is fractional (guarded below), not the
    always-1.0 of a linear chain.
    """
    graph = _competing_two_path_graph()
    drivers = _multiplier_identical_drivers()
    cfg = ScheduleMCConfig(n_iter=2000, batch_size=500, seed=seed, mode_multipliers=TEST_MODE_MULTIPLIERS)

    result = run_schedule_mc(
        graph=graph,
        risk_drivers=drivers,
        config=cfg,
        criticality_measurement_mode="both",
    )

    assert result.mode_independent_project_finish_hours is not None
    assert result.mode_independent_criticality_index is not None

    # --- Non-degeneracy guard (brief §4.1.1) --------------------------
    # At least one activity must have a genuinely fractional criticality
    # index (neither ≈0 nor ≈1). If every CI were 1.0 (linear-chain
    # degeneracy) the CI equality assertion would pass vacuously and
    # witness nothing. p1a/p1b/p2a/p2b compete, so their CI sits well
    # inside (0, 1).
    competing = ("p1a", "p1b", "p2a", "p2b")
    competing_cis = {a: result.criticality_index[a] for a in competing}
    fractional = [a for a, ci in competing_cis.items() if 0.05 < ci < 0.95]
    assert fractional, (
        "fixture is degenerate — no activity has a fractional criticality "
        "index, so the CI equality assertion would be vacuous. "
        f"CIs: {competing_cis!r}"
    )

    # --- PRIMARY: finish-array bit-identity ---------------------------
    assert np.array_equal(
        result.project_finish_hours,
        result.mode_independent_project_finish_hours,
    ), (
        f"[seed={seed}] project_finish_hours diverges from "
        "mode_independent_project_finish_hours — the two passes are NOT "
        "drawing paired randomness (SR10.F unpaired-state signature). "
        f"differing iterations: "
        f"{int((result.project_finish_hours != result.mode_independent_project_finish_hours).sum())}"
        f"/{result.n_iter}"
    )
    assert np.array_equal(
        result.project_finish_days,
        result.mode_independent_project_finish_days,
    )

    # --- SECONDARY: criticality-index bit-identity --------------------
    assert (
        result.criticality_index == result.mode_independent_criticality_index
    ), (
        f"[seed={seed}] criticality_index diverges from "
        "mode_independent_criticality_index under a multiplier-identical "
        "risk set — the passes are not paired."
    )

    # --- Companion SR10.E stat arrays must pair too --------------------
    # With paired draws and identical multiplier the streaming finish /
    # total-float sums are identical, so every derived stat matches.
    assert np.array_equal(
        result.finish_mean_hours, result.mode_independent_finish_mean_hours
    )
    assert np.array_equal(
        result.finish_std_hours, result.mode_independent_finish_std_hours
    )
    assert np.array_equal(
        result.total_float_mean_hours,
        result.mode_independent_total_float_mean_hours,
    )
    assert np.array_equal(
        result.total_float_std_hours,
        result.mode_independent_total_float_std_hours,
    )


def test_both_mode_pass1_unchanged_vs_standalone_mode_conditioned() -> None:
    """The SR10.F fix must not perturb pass 1. "both" mode's
    Mode-conditioned half must still match an independent standalone
    ``mode_conditioned`` run bit-for-bit (the property the pre-existing
    ``test_both_mode_conditioned_half_matches_standalone`` locks, re-checked
    here on the SR10.F competing-path fixture to guard against a
    regression in the shared-spawn refactor).
    """
    graph = _competing_two_path_graph()
    drivers = _multiplier_identical_drivers()
    cfg = ScheduleMCConfig(n_iter=2000, batch_size=500, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)

    result_both = run_schedule_mc(
        graph=graph, risk_drivers=drivers, config=cfg,
        criticality_measurement_mode="both",
    )
    result_mc = run_schedule_mc(
        graph=graph, risk_drivers=drivers, config=cfg,
        criticality_measurement_mode="mode_conditioned",
    )

    assert np.array_equal(
        result_both.project_finish_hours, result_mc.project_finish_hours
    )
    assert result_both.criticality_index == result_mc.criticality_index
