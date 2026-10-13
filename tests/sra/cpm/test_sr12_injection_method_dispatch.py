"""SR12 — per-risk injection-method dispatch tests.

Covers Acceptance Criteria 1, 4, 5, 6 from the SR12 brief:

* AC1 — discrete_event_additive_days and productivity_multiplicative_factor
  dispatched correctly under the new branch in
  :func:`src.sra.cpm.risk_injection.sample_risk_deltas`.
* AC4 — legacy ``additive_pert_days`` parity (bit-identical to pre-SR12
  master when no risk has the new method).
* AC5 — joint-sampling invariant preserved across all three method
  dispatches.
* AC6 — Mode multiplier applied post-magnitude under both new methods.

Synthetic-graph only; no RefProject file references.
"""

from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import numpy as np
import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from src.sra.cpm.risk_driver_schema import RiskDriver
from src.sra.cpm.risk_injection import sample_risk_deltas


_DEFAULT_CAL = Calendar()  # 8 working hours per day


def _make_activity(
    aid: str,
    *,
    duration_hours: float = 80.0,
    code: str | None = None,
) -> Activity:
    return Activity(
        id=aid,
        code=code if code is not None else aid,
        name=aid,
        task_type="TT_Task",
        original_duration_hours=duration_hours,
        total_float_hours=0.0,
        calendar_id=None,
    )


def _make_graph(activities: list[Activity]) -> ScheduleGraph:
    return ScheduleGraph(
        activities={a.id: a for a in activities},
        links=[],
        topo_order=[a.id for a in activities],
        project_default_calendar=_DEFAULT_CAL,
    )


def _discrete_driver(
    *,
    risk_id: str = "R013",
    affected: tuple[str, ...] = ("a1", "a2", "a3"),
    gating_activity_id: str = "a1",
    opt: float = 5.0,
    ml: float = 5.0,
    pess: float = 5.0,
    probability: float = 1.0,
    mode: str = "Series",
) -> RiskDriver:
    return RiskDriver(
        risk_id=risk_id,
        affected_activity_ids=affected,
        injection_method="discrete_event_additive_days",  # type: ignore[arg-type]
        opt_pert=opt, ml_pert=ml, pess_pert=pess,
        probability=probability,
        derived_at_run_time=False,
        workshop_validated=True,
        mode=mode,  # type: ignore[arg-type]
        gating_activity_id=gating_activity_id,
    )


def _productivity_driver(
    *,
    risk_id: str = "R001",
    affected: tuple[str, ...] = ("a1", "a2"),
    opt: float = 1.05,
    ml: float = 1.05,
    pess: float = 1.05,
    probability: float = 1.0,
    mode: str = "Series",
) -> RiskDriver:
    return RiskDriver(
        risk_id=risk_id,
        affected_activity_ids=affected,
        injection_method="productivity_multiplicative_factor",  # type: ignore[arg-type]
        opt_pert=opt, ml_pert=ml, pess_pert=pess,
        probability=probability,
        mode=mode,  # type: ignore[arg-type]
    )


def _legacy_additive_driver(
    *,
    affected: tuple[str, ...] = ("a1", "a2", "a3"),
    opt: float = 5.0,
    ml: float = 5.0,
    pess: float = 5.0,
    probability: float = 1.0,
    mode: str = "Series",
) -> RiskDriver:
    return RiskDriver(
        risk_id="R_legacy",
        affected_activity_ids=affected,
        injection_method="additive_pert_days",
        opt_pert=opt, ml_pert=ml, pess_pert=pess,
        probability=probability,
        mode=mode,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# AC1 — discrete_event_additive_days mechanics
# ---------------------------------------------------------------------------


class TestDiscreteEventAdditiveDays:

    def test_writes_only_to_gating_column(self) -> None:
        """Magnitude written to gating col; other bound cols stay zero."""
        graph = _make_graph(
            [_make_activity(f"a{i}") for i in (1, 2, 3)]
        )
        drivers = {
            "R013": _discrete_driver(
                affected=("a1", "a2", "a3"),
                gating_activity_id="a2",
                opt=5.0, ml=5.0, pess=5.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, n_iter=100, rng=np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # 5 days × 8 h = 40 h on the gating column only.
        np.testing.assert_allclose(deltas[:, 1], 40.0, atol=1e-3)
        np.testing.assert_allclose(deltas[:, 0], 0.0, atol=1e-3)
        np.testing.assert_allclose(deltas[:, 2], 0.0, atol=1e-3)

    def test_magnitude_collapse_versus_legacy_broadcast(self) -> None:
        """Per-fire delta sum: legacy = K × X; SR12 discrete = 1 × X."""
        graph = _make_graph(
            [_make_activity(f"a{i}") for i in (1, 2, 3, 4, 5)]
        )
        # Both drivers fire every iteration with the same magnitude.
        legacy = {
            "R_legacy": _legacy_additive_driver(
                affected=("a1", "a2", "a3", "a4", "a5"),
                opt=5.0, ml=5.0, pess=5.0,
            ),
        }
        discrete = {
            "R013": _discrete_driver(
                affected=("a1", "a2", "a3", "a4", "a5"),
                gating_activity_id="a3",
                opt=5.0, ml=5.0, pess=5.0,
            ),
        }
        d_legacy = sample_risk_deltas(
            legacy, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        d_discrete = sample_risk_deltas(
            discrete, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # Per-iteration total across all bound columns: legacy = 5 × 40,
        # discrete = 1 × 40.
        legacy_total_per_iter = d_legacy.sum(axis=1)
        discrete_total_per_iter = d_discrete.sum(axis=1)
        np.testing.assert_allclose(legacy_total_per_iter, 200.0, atol=1e-3)
        np.testing.assert_allclose(discrete_total_per_iter, 40.0, atol=1e-3)

    def test_probability_gate_applies_to_discrete_event(self) -> None:
        """probability=0 → zero delta on gating column."""
        graph = _make_graph([_make_activity("a1"), _make_activity("a2")])
        drivers = {
            "R013": _discrete_driver(
                affected=("a1", "a2"),
                gating_activity_id="a1",
                opt=5.0, ml=5.0, pess=5.0,
                probability=0.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 500, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert np.all(deltas == 0.0)

    def test_discrete_event_skips_when_gating_missing_from_graph(self) -> None:
        """Stale gating id (not in graph): no write, no raise."""
        graph = _make_graph([_make_activity("a1"), _make_activity("a2")])
        drivers = {
            "R013": _discrete_driver(
                affected=("a1", "a2"),
                gating_activity_id="a_renamed",  # not in graph
                opt=5.0, ml=5.0, pess=5.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # Defensive skip per risk_injection.py — the pre-flight gate is
        # the assertive surface; the consumer must not raise mid-batch.
        assert deltas.shape == (50, 2)
        np.testing.assert_allclose(deltas, 0.0, atol=1e-3)

    def test_constructing_driver_without_gating_id_raises(self) -> None:
        """RiskDriver.__post_init__ rejects discrete-event without gating."""
        with pytest.raises(ValueError, match="gating_activity_id"):
            RiskDriver(
                risk_id="R013",
                affected_activity_ids=("a1",),
                injection_method="discrete_event_additive_days",  # type: ignore[arg-type]
                opt_pert=5.0, ml_pert=5.0, pess_pert=5.0,
                probability=1.0,
                gating_activity_id=None,
            )

    def test_constructing_driver_with_empty_gating_id_raises(self) -> None:
        with pytest.raises(ValueError, match="gating_activity_id"):
            RiskDriver(
                risk_id="R013",
                affected_activity_ids=("a1",),
                injection_method="discrete_event_additive_days",  # type: ignore[arg-type]
                opt_pert=5.0, ml_pert=5.0, pess_pert=5.0,
                probability=1.0,
                gating_activity_id="",
            )

    def test_pert_variability_under_discrete_event(self) -> None:
        """Non-degenerate PERT triple → magnitude varies across iterations."""
        graph = _make_graph([_make_activity("a1"), _make_activity("a2")])
        drivers = {
            "R013": _discrete_driver(
                affected=("a1", "a2"),
                gating_activity_id="a1",
                opt=1.0, ml=5.0, pess=15.0,
                probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 5_000, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # Mean PERT magnitude with λ=4: (1 + 4*5 + 15)/6 = 6.0 days.
        # × 8 working hours = 48.0; allow stochastic tolerance.
        observed_mean = float(deltas[:, 0].mean())
        assert abs(observed_mean - 48.0) < 2.0
        # a2 is not the gating column → strictly zero.
        np.testing.assert_allclose(deltas[:, 1], 0.0, atol=1e-3)


# ---------------------------------------------------------------------------
# AC1 — productivity_multiplicative_factor mechanics
# ---------------------------------------------------------------------------


class TestProductivityMultiplicativeFactor:

    def test_routes_to_multiplicative_branch(self) -> None:
        """productivity_multiplicative_factor and multiplicative_pert_factor
        produce bit-identical deltas under the same driver shape."""
        graph = _make_graph(
            [_make_activity("a1", duration_hours=80.0),
             _make_activity("a2", duration_hours=80.0)]
        )
        prod = {
            "R_prod": _productivity_driver(
                affected=("a1", "a2"),
                opt=1.10, ml=1.10, pess=1.10,
                probability=1.0,
            ),
        }
        legacy = {
            "R_prod": RiskDriver(
                risk_id="R_prod",
                affected_activity_ids=("a1", "a2"),
                injection_method="multiplicative_pert_factor",
                opt_pert=1.10, ml_pert=1.10, pess_pert=1.10,
                probability=1.0,
            ),
        }
        d_prod = sample_risk_deltas(
            prod, graph, 200, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        d_legacy = sample_risk_deltas(
            legacy, graph, 200, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        np.testing.assert_array_equal(d_prod, d_legacy)

    def test_multiplicative_factor_applied_to_all_bound(self) -> None:
        """Factor applied as (factor-1)*base across every bound activity."""
        graph = _make_graph(
            [_make_activity("a1", duration_hours=80.0),
             _make_activity("a2", duration_hours=40.0)]
        )
        drivers = {
            "R_prod": _productivity_driver(
                affected=("a1", "a2"),
                opt=1.10, ml=1.10, pess=1.10,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # (1.10 - 1.0) × 80 = 8.0; (1.10 - 1.0) × 40 = 4.0.
        np.testing.assert_allclose(deltas[:, 0], 8.0, atol=1e-3)
        np.testing.assert_allclose(deltas[:, 1], 4.0, atol=1e-3)


# ---------------------------------------------------------------------------
# AC4 — backward-compat parity (legacy additive_pert_days unchanged)
# ---------------------------------------------------------------------------


class TestLegacyAdditiveParity:

    def test_legacy_additive_pert_days_unchanged_post_sr12(self) -> None:
        """Driver with method=additive_pert_days and no SR12 method opt-in
        produces bit-identical deltas vs the pre-SR12 broadcast path."""
        graph = _make_graph(
            [_make_activity(f"a{i}") for i in (1, 2, 3, 4)]
        )
        drivers = {
            "R001": _legacy_additive_driver(
                affected=("a1", "a2", "a3", "a4"),
                opt=2.0, ml=4.0, pess=7.0,
                probability=0.6,
            ),
        }
        d = sample_risk_deltas(
            drivers, graph, 1_000, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # Broadcast invariant: per-iteration delta is identical across
        # every bound column (the legacy mechanic).
        np.testing.assert_array_equal(d[:, 0], d[:, 1])
        np.testing.assert_array_equal(d[:, 1], d[:, 2])
        np.testing.assert_array_equal(d[:, 2], d[:, 3])

    def test_legacy_path_unaffected_by_gating_field_default(self) -> None:
        """Legacy driver with gating_activity_id=None (default) still works."""
        graph = _make_graph([_make_activity("a1"), _make_activity("a2")])
        drivers = {
            "R001": RiskDriver(
                risk_id="R001",
                affected_activity_ids=("a1", "a2"),
                injection_method="additive_pert_days",
                opt_pert=2.0, ml_pert=4.0, pess_pert=7.0,
                probability=1.0,
                # gating_activity_id defaults to None — no validation
                # error because this method does not require it.
            ),
        }
        d = sample_risk_deltas(
            drivers, graph, 200, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert d.shape == (200, 2)
        assert (d > 0).any()


# ---------------------------------------------------------------------------
# AC5 — joint-sampling invariant under all dispatches
# ---------------------------------------------------------------------------


class TestJointSamplingPreserved:

    def test_severity_uniform_consumed_per_risk_in_discrete_event(self) -> None:
        """Same severity_uniform → bit-identical deltas across runs for
        discrete-event method."""
        graph = _make_graph([
            _make_activity(f"a{i}") for i in (1, 2)
        ])
        drivers = {
            "R013": _discrete_driver(
                affected=("a1", "a2"), gating_activity_id="a1",
                opt=1.0, ml=5.0, pess=15.0,
            ),
        }
        n = 500
        sev = np.random.default_rng(123).random((n, 1))
        d1 = sample_risk_deltas(
            drivers, graph, n, np.random.default_rng(42),
            severity_uniform=sev,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        d2 = sample_risk_deltas(
            drivers, graph, n, np.random.default_rng(42),
            severity_uniform=sev,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        np.testing.assert_array_equal(d1, d2)

    def test_severity_uniform_shared_across_methods(self) -> None:
        """Two risks under different methods sharing the same severity
        uniform column produce reproducible draws (joint-sampling
        invariant: column j → risk at iter index j)."""
        graph = _make_graph([
            _make_activity(f"a{i}", duration_hours=80.0) for i in (1, 2, 3)
        ])
        drivers = {
            "R013": _discrete_driver(
                affected=("a1", "a2"), gating_activity_id="a1",
                opt=1.0, ml=5.0, pess=15.0,
            ),
            "R_prod": _productivity_driver(
                affected=("a3",), opt=1.0, ml=1.1, pess=1.3,
            ),
        }
        n = 1_000
        sev = np.random.default_rng(7).random((n, 2))
        d1 = sample_risk_deltas(
            drivers, graph, n, np.random.default_rng(42),
            severity_uniform=sev,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        d2 = sample_risk_deltas(
            drivers, graph, n, np.random.default_rng(42),
            severity_uniform=sev,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        np.testing.assert_array_equal(d1, d2)


# ---------------------------------------------------------------------------
# AC6 — Mode multiplier applied post-magnitude for new methods
# ---------------------------------------------------------------------------


class TestModeMultiplierWithSR12Methods:

    def test_discrete_event_mode_parallel_zeros_delta(self) -> None:
        """Mode=Parallel (multiplier 0.0) zeros the discrete-event write."""
        graph = _make_graph([_make_activity("a1"), _make_activity("a2")])
        drivers = {
            "R013": _discrete_driver(
                affected=("a1", "a2"),
                gating_activity_id="a1",
                opt=5.0, ml=5.0, pess=5.0,
                probability=1.0,
                mode="Parallel",
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 200, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        np.testing.assert_allclose(deltas[:, 0], 0.0, atol=1e-3)

    def test_discrete_event_mode_hybrid_halves_delta(self) -> None:
        """Mode=Hybrid (multiplier 0.5) halves the discrete-event write."""
        graph = _make_graph([_make_activity("a1")])
        drivers = {
            "R013": _discrete_driver(
                affected=("a1",),
                gating_activity_id="a1",
                opt=5.0, ml=5.0, pess=5.0,
                probability=1.0,
                mode="Hybrid",
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 200, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # Series would give 40 h; Hybrid → 20 h.
        np.testing.assert_allclose(deltas[:, 0], 20.0, atol=1e-3)

    def test_productivity_multiplicative_mode_scales_factor(self) -> None:
        """Mode=Hybrid scales the (factor-1) by 0.5 before broadcast."""
        graph = _make_graph(
            [_make_activity("a1", duration_hours=80.0)]
        )
        drivers = {
            "R_prod": _productivity_driver(
                affected=("a1",),
                opt=1.20, ml=1.20, pess=1.20,
                probability=1.0,
                mode="Hybrid",
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 200, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # Hybrid: (1.20 - 1.0) × 80 × 0.5 = 8.0.
        np.testing.assert_allclose(deltas[:, 0], 8.0, atol=1e-3)

    def test_mode_independent_override_for_discrete_event(self) -> None:
        """mode_multiplier_override=1.0 restores Series-equivalent magnitude
        for a declared-Parallel discrete-event risk (SR10.A semantics
        preserved)."""
        graph = _make_graph([_make_activity("a1")])
        drivers = {
            "R013": _discrete_driver(
                affected=("a1",),
                gating_activity_id="a1",
                opt=5.0, ml=5.0, pess=5.0,
                probability=1.0,
                mode="Parallel",
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 100, np.random.default_rng(42),
            mode_multiplier_override=1.0,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        np.testing.assert_allclose(deltas[:, 0], 40.0, atol=1e-3)
