"""SR10.E — engine tests for the Mode-independent finish/total-float
distribution fields.

Six new ``ScheduleMCResult`` fields under
``criticality_measurement_mode="both"``:
``mode_independent_project_finish_hours`` / ``_days``,
``mode_independent_finish_mean_hours`` / ``_std_hours``,
``mode_independent_total_float_mean_hours`` / ``_std_hours``. All six
come from the second (Mode-independent) CPM-replay pass's return tuple,
previously discarded past ``cp_count_mi`` (SR10.D); SR10.E captures the
rest of it. See ``cpm_simulation.py`` SR10.E for the derivation.

Covers:

(a) ``None`` on the default ``"mode_conditioned"`` mode.
(b) ``None`` on ``"mode_independent"`` alone (only ``"both"`` populates —
    a plausible confusion point since ``"mode_independent"`` alone does
    run the same forward pass, but there is no primary pass to pair it
    with for a Mode-conditioned baseline).
(c) Shapes / dtypes under ``"both"``.
(d) Days-hours unit-conversion sanity.
(e) P50/P80/P90 percentile sanity on the newly-exposed project-finish
    trace.
(f) **Capture-assertion regression guard** — on a Mode-mixed fixture
    (Series + Hybrid + Parallel all present), all six fields are
    non-``None`` under ``"both"`` and diverge from their Mode-conditioned
    counterparts (not silently a copy). Guards against a future refactor
    re-discarding the tuple positions at the
    ``cpm_simulation.py`` "both"-pass unpack site the way SR10.D
    originally left them.

**Deliberately NOT covered: pairing.** An earlier draft of this file
included a test asserting the "both" run's Mode-independent pass
reproduces a standalone ``"mode_independent"`` run bit-for-bit (i.e. that
the ``rng.bit_generator.state`` snapshot/restore around the second
``_run_batch_loop`` call actually pairs the two passes' Bernoulli fires
and PERT magnitudes, per the claim in ``cpm_simulation.py``'s own
comments). That assertion is FALSE against the current implementation —
verified directly: even an all-Series-mode risk set (multiplier 1.0 in
both passes, so a truly paired second pass would reproduce pass one
exactly) produces a materially different finish distribution on the
second pass. Root cause: ``Generator.spawn()`` draws from
``SeedSequence.n_children_spawned``, a counter NOT included in
``bit_generator.state`` — restoring ``.state`` does not reset it, so the
second ``.spawn(n_batches)`` call in a "both" run draws different
children than the first, regardless of the state restore. This is a
pre-existing SR10.A defect, out of SR10.E's scope (SR10.E only persists
already-computed values and does not touch RNG handling) — tracked as
its own brief (SR10.F). The capture-assertion test below (f) checks
"populated and diverges from Mode-conditioned", which holds regardless
of whether pairing works, and deliberately stops short of asserting
anything about pairing.

Synthetic graphs constructed in-test — no register / strawman / .xer
dependency. Helper functions duplicated from
``test_cpm_mode_independent_criticality.py`` per this repo's existing
per-file self-containment convention (no shared conftest for these
synthetic-graph builders).
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
    topo_order: list[str] | None = None,
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
        topo_order=topo_order if topo_order is not None else [a.id for a in activities],
        project_default_calendar=_DEFAULT_CAL,
    )


def _driver(
    risk_id: str,
    *,
    affected: tuple[str, ...],
    opt: float = 1.0,
    ml: float = 5.0,
    pess: float = 10.0,
    probability: float = 1.0,
    mode: RiskMode = "Series",
) -> RiskDriver:
    return RiskDriver(
        risk_id=risk_id,
        affected_activity_ids=affected,
        injection_method="additive_pert_days",
        opt_pert=opt,
        ml_pert=ml,
        pess_pert=pess,
        probability=probability,
        derived_at_run_time=False,
        workshop_validated=True,
        mode=mode,
    )


def _linear_chain(n: int = 5) -> ScheduleGraph:
    acts = [_activity(f"a{i}", duration_hours=80.0) for i in range(1, n + 1)]
    links = [
        Link(pred_id=f"a{i}", succ_id=f"a{i + 1}", link_type="FS", lag_hours=0.0)
        for i in range(1, n)
    ]
    return _make_graph(acts, links)


def _two_path_graph() -> ScheduleGraph:
    """Two equal-length parallel chains meeting at a single milestone.
    Duplicated from test_cpm_mode_independent_criticality.py — see that
    file's docstring for the full topology rationale."""
    acts = [
        _activity("start", duration_hours=0.0),
        _activity("p1a", duration_hours=80.0),
        _activity("p1b", duration_hours=80.0),
        _activity("p2a", duration_hours=80.0),
        _activity("p2b", duration_hours=80.0),
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


# ---------------------------------------------------------------------------
# (a) None on default "mode_conditioned"
# ---------------------------------------------------------------------------

def test_none_on_mode_conditioned_default() -> None:
    graph = _linear_chain(n=4)
    drivers = {
        "R001": _driver(risk_id="R001", affected=("a2",), mode="Hybrid"),
    }
    cfg = ScheduleMCConfig(n_iter=500, batch_size=250, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)

    result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)

    assert result.mode_independent_project_finish_hours is None
    assert result.mode_independent_project_finish_days is None
    assert result.mode_independent_finish_mean_hours is None
    assert result.mode_independent_finish_std_hours is None
    assert result.mode_independent_total_float_mean_hours is None
    assert result.mode_independent_total_float_std_hours is None


# ---------------------------------------------------------------------------
# (b) None on "mode_independent" alone (only "both" populates)
# ---------------------------------------------------------------------------

def test_none_on_mode_independent_alone() -> None:
    """``criticality_measurement_mode="mode_independent"`` runs the
    forward pass at multiplier 1.0 as the PRIMARY (only) pass — it does
    not run a paired second pass, so there is nothing to diverge against
    and the SR10.E fields (which describe the second-pass capture under
    "both") stay None. The Mode-independent distribution IS available in
    this mode, just via the ordinary primary-pass fields
    (project_finish_hours, finish_mean_hours, etc.) — not the
    mode_independent_* ones."""
    graph = _linear_chain(n=4)
    drivers = {
        "R001": _driver(risk_id="R001", affected=("a2",), mode="Parallel"),
    }
    cfg = ScheduleMCConfig(n_iter=500, batch_size=250, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)

    result = run_schedule_mc(
        graph=graph, risk_drivers=drivers, config=cfg,
        criticality_measurement_mode="mode_independent",
    )

    assert result.mode_independent_project_finish_hours is None
    assert result.mode_independent_finish_mean_hours is None
    assert result.mode_independent_total_float_mean_hours is None


# ---------------------------------------------------------------------------
# (c) Shapes / dtypes under "both"
# ---------------------------------------------------------------------------

def test_shapes_and_dtypes_under_both() -> None:
    graph = _linear_chain(n=5)
    drivers = {
        "R001": _driver(risk_id="R001", affected=("a2",), mode="Hybrid"),
        "R002": _driver(risk_id="R002", affected=("a4",), mode="Parallel"),
    }
    cfg = ScheduleMCConfig(n_iter=800, batch_size=300, seed=7, mode_multipliers=TEST_MODE_MULTIPLIERS)

    result = run_schedule_mc(
        graph=graph, risk_drivers=drivers, config=cfg,
        criticality_measurement_mode="both",
    )

    n_act = result.n_act
    n_iter = result.n_iter

    assert result.mode_independent_project_finish_hours.shape == (n_iter,)
    assert result.mode_independent_project_finish_days.shape == (n_iter,)
    assert (
        result.mode_independent_project_finish_hours.dtype
        == result.project_finish_hours.dtype
    )
    assert (
        result.mode_independent_project_finish_days.dtype
        == result.project_finish_days.dtype
    )

    assert result.mode_independent_finish_mean_hours.shape == (n_act,)
    assert result.mode_independent_finish_std_hours.shape == (n_act,)
    assert result.mode_independent_finish_mean_hours.dtype == np.float64
    assert result.mode_independent_finish_std_hours.dtype == np.float64

    assert result.mode_independent_total_float_mean_hours.shape == (n_act,)
    assert result.mode_independent_total_float_std_hours.shape == (n_act,)
    assert (
        result.mode_independent_total_float_mean_hours.dtype
        == result.total_float_mean_hours.dtype
    )
    assert (
        result.mode_independent_total_float_std_hours.dtype
        == result.total_float_std_hours.dtype
    )

    assert np.all(np.isfinite(result.mode_independent_project_finish_hours))
    assert np.all(np.isfinite(result.mode_independent_finish_mean_hours))
    assert np.all(result.mode_independent_finish_std_hours >= 0.0)
    assert np.all(result.mode_independent_total_float_std_hours >= 0.0)


# ---------------------------------------------------------------------------
# (d) Days-hours unit conversion sanity
# ---------------------------------------------------------------------------

def test_project_finish_days_matches_hours_conversion() -> None:
    graph = _linear_chain(n=4)
    drivers = {"R001": _driver(risk_id="R001", affected=("a2",), mode="Series")}
    cfg = ScheduleMCConfig(n_iter=500, batch_size=250, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)

    result = run_schedule_mc(
        graph=graph, risk_drivers=drivers, config=cfg,
        criticality_measurement_mode="both",
    )

    hours_per_day = float(_DEFAULT_CAL.working_hours_per_day)
    expected_days = (
        result.mode_independent_project_finish_hours.astype(np.float64)
        / hours_per_day
    )
    np.testing.assert_allclose(
        result.mode_independent_project_finish_days.astype(np.float64),
        expected_days,
        rtol=1e-5,
    )


# ---------------------------------------------------------------------------
# (e) P50/P80/P90 percentile sanity
# ---------------------------------------------------------------------------

def test_project_finish_mi_percentiles_monotonic_and_above_baseline() -> None:
    graph = _linear_chain(n=5)
    base_finish_hours = 5 * 80.0
    drivers = {
        "R_hybrid": _driver(
            risk_id="R_hybrid",
            affected=("a3",),
            opt=10.0, ml=20.0, pess=30.0,
            probability=1.0,
            mode="Hybrid",
        ),
    }
    cfg = ScheduleMCConfig(n_iter=2000, batch_size=500, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)

    result = run_schedule_mc(
        graph=graph, risk_drivers=drivers, config=cfg,
        criticality_measurement_mode="both",
    )

    p50, p80, p90 = np.percentile(
        result.mode_independent_project_finish_days, [50, 80, 90]
    )
    assert p50 <= p80 <= p90
    hours_per_day = float(_DEFAULT_CAL.working_hours_per_day)
    baseline_days = base_finish_hours / hours_per_day
    assert p50 >= baseline_days - 1e-6, (
        f"P50 ({p50:.2f}d) should not fall below the deterministic "
        f"zero-risk baseline ({baseline_days:.2f}d)"
    )


# ---------------------------------------------------------------------------
# (f) Capture-assertion regression guard
# ---------------------------------------------------------------------------

def test_capture_assertion_mode_mixed_fields_diverge_from_mode_conditioned() -> None:
    """Regression guard against a future refactor silently re-discarding
    the tuple positions at the "both"-pass unpack site the way SR10.D
    originally left them (``_, cp_count_mi, _, _, _, _ = ...``).

    Fixture is Mode-mixed (Series + Hybrid + Parallel all present, on
    distinct chain activities) so the Mode-conditioned and
    Mode-independent passes are expected to diverge materially — a
    Series-only fixture would make "field equals its Mode-conditioned
    counterpart" ambiguous between "correctly captured but coincidentally
    equal" (Series multiplier 1.0, and — once SR10.F fixes the "both"-mode
    RNG pairing defect noted in this module's docstring — genuinely
    paired-and-equal draws too) and "silently discarded and defaulted to
    a stale copy". With Hybrid/Parallel present the two passes cannot
    coincidentally agree under either the current unpaired behaviour or a
    future fixed/paired one, so any accidental revert back to discarding
    the tuple would either raise (None where a value is expected) or
    produce values equal to the Mode-conditioned side — both caught here.

    Deliberately does NOT assert anything about pairing (bit-identical
    Bernoulli fires / PERT magnitudes between the two passes) — see the
    module docstring for why that assertion would currently be false and
    is out of SR10.E's scope. This test only asserts "populated" and
    "diverges", both of which hold regardless of whether pairing works.
    """
    graph = _linear_chain(n=6)
    drivers = {
        "R_series": _driver(
            risk_id="R_series", affected=("a1",),
            opt=5.0, ml=10.0, pess=20.0, probability=1.0, mode="Series",
        ),
        "R_hybrid": _driver(
            risk_id="R_hybrid", affected=("a3",),
            opt=5.0, ml=10.0, pess=20.0, probability=1.0, mode="Hybrid",
        ),
        "R_parallel": _driver(
            risk_id="R_parallel", affected=("a5",),
            opt=5.0, ml=10.0, pess=20.0, probability=1.0, mode="Parallel",
        ),
    }
    cfg = ScheduleMCConfig(n_iter=3000, batch_size=1000, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)

    result = run_schedule_mc(
        graph=graph, risk_drivers=drivers, config=cfg,
        criticality_measurement_mode="both",
    )

    # All six fields present (not silently discarded back to None).
    assert result.mode_independent_project_finish_hours is not None
    assert result.mode_independent_project_finish_days is not None
    assert result.mode_independent_finish_mean_hours is not None
    assert result.mode_independent_finish_std_hours is not None
    assert result.mode_independent_total_float_mean_hours is not None
    assert result.mode_independent_total_float_std_hours is not None

    # Project-level finish trace materially diverges (Parallel risk on
    # a5 contributes its full impact under MI but is suppressed to zero
    # under MC; Hybrid risk on a3 contributes half under MC vs full
    # under MI) — means must differ, not just "not bit-identical".
    mc_finish_mean = float(result.project_finish_hours.mean())
    mi_finish_mean = float(result.mode_independent_project_finish_hours.mean())
    assert mi_finish_mean > mc_finish_mean + 1.0, (
        f"Mode-independent project-finish mean ({mi_finish_mean:.2f}h) "
        f"should exceed Mode-conditioned ({mc_finish_mean:.2f}h) by a "
        f"material margin on this Mode-mixed fixture — a value this "
        f"close suggests the MI capture silently fell back to the MC "
        f"array."
    )

    # Per-activity finish mean is not merely a copy of the
    # Mode-conditioned array.
    assert not np.array_equal(
        result.mode_independent_finish_mean_hours, result.finish_mean_hours
    ), (
        "mode_independent_finish_mean_hours is bit-identical to "
        "finish_mean_hours on a Mode-mixed fixture — capture likely "
        "silently fell back to the Mode-conditioned pass"
    )

    # Per-activity total-float mean is not merely a copy either.
    assert not np.array_equal(
        result.mode_independent_total_float_mean_hours,
        result.total_float_mean_hours,
    ), (
        "mode_independent_total_float_mean_hours is bit-identical to "
        "total_float_mean_hours on a Mode-mixed fixture — capture "
        "likely silently fell back to the Mode-conditioned pass"
    )
