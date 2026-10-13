"""Tests for src.sra.cpm.risk_injection (SR-S3-Beta-04).

Covers:

* Sampling shape, dtype, reproducibility (5).
* Probability-gate (3).
* Additive PERT-days conversion (3).
* Multiplicative PERT-factor conversion (3).
* Severity-uniform sharing (3).
* Multi-risk superposition (2).
* apply_to_durations broadcast / floor / dtype (3).
* Edge cases (3).
* Full pipeline smoke (1) → 26 tests.

All tests construct synthetic ScheduleGraphs and RiskDrivers directly
— no RefProject file references.
"""

from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import logging

import numpy as np
import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.cpm_kernel import run_batch
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from src.sra.cpm.risk_driver_schema import RiskDriver
from src.sra.cpm.risk_injection import (
    apply_to_durations,
    build_duration_array,
    sample_risk_deltas,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_CAL = Calendar()  # 8 working hours per day


def _make_activity(
    aid: str,
    *,
    duration_hours: float = 80.0,
    task_type: str = "TT_Task",
    code: str | None = None,
    total_float_hours: float | None = 0.0,
) -> Activity:
    return Activity(
        id=aid,
        code=code if code is not None else aid,
        name=aid,
        task_type=task_type,
        original_duration_hours=duration_hours,
        total_float_hours=total_float_hours,
        calendar_id=None,
    )


def _make_graph(
    activities: list[Activity],
    *,
    links: list[Link] | None = None,
    topo_order: list[str] | None = None,
    calendar: Calendar | None = None,
) -> ScheduleGraph:
    acts = {a.id: a for a in activities}
    return ScheduleGraph(
        activities=acts,
        links=links or [],
        topo_order=topo_order if topo_order is not None else [a.id for a in activities],
        project_default_calendar=calendar or _DEFAULT_CAL,
    )


def _driver(
    risk_id: str = "R001",
    *,
    affected: tuple[str, ...] = ("a1",),
    injection_method: str = "additive_pert_days",
    opt: float = 1.0,
    ml: float = 2.0,
    pess: float = 4.0,
    probability: float = 1.0,
) -> RiskDriver:
    return RiskDriver(
        risk_id=risk_id,
        affected_activity_ids=affected,
        injection_method=injection_method,  # type: ignore[arg-type]
        opt_pert=opt,
        ml_pert=ml,
        pess_pert=pess,
        probability=probability,
        derived_at_run_time=True,
        workshop_validated=False,
    )


# ---------------------------------------------------------------------------
# Sampling shape, dtype, reproducibility
# ---------------------------------------------------------------------------

class TestSamplingShapeDtype:

    def test_sample_risk_deltas_shape(self) -> None:
        graph = _make_graph(
            [_make_activity(f"a{i}") for i in range(10)]
        )
        drivers = {"R001": _driver(affected=("a1", "a2"))}
        rng = np.random.default_rng(42)
        deltas = sample_risk_deltas(drivers, graph, n_iter=100, rng=rng, mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert deltas.shape == (100, 10)

    def test_sample_risk_deltas_default_dtype_float32(self) -> None:
        graph = _make_graph([_make_activity("a1")])
        drivers = {"R001": _driver(affected=("a1",))}
        rng = np.random.default_rng(42)
        deltas = sample_risk_deltas(drivers, graph, n_iter=10, rng=rng, mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert deltas.dtype == np.float32

    def test_sample_risk_deltas_explicit_float64(self) -> None:
        graph = _make_graph([_make_activity("a1")])
        drivers = {"R001": _driver(affected=("a1",))}
        rng = np.random.default_rng(42)
        deltas = sample_risk_deltas(
            drivers, graph, n_iter=10, rng=rng, precision="float64",
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert deltas.dtype == np.float64

    def test_sample_risk_deltas_reproducible_with_seeded_rng(self) -> None:
        graph = _make_graph([_make_activity("a1"), _make_activity("a2")])
        drivers = {
            "R001": _driver(affected=("a1",), probability=0.5),
            "R002": _driver(affected=("a2",), probability=0.7),
        }
        d1 = sample_risk_deltas(drivers, graph, 1_000, np.random.default_rng(42), mode_multipliers=TEST_MODE_MULTIPLIERS)
        d2 = sample_risk_deltas(drivers, graph, 1_000, np.random.default_rng(42), mode_multipliers=TEST_MODE_MULTIPLIERS)
        np.testing.assert_array_equal(d1, d2)

    def test_sample_risk_deltas_reproducible_with_severity_uniform(self) -> None:
        """Same severity_uniform → bit-identical deltas across runs."""
        graph = _make_graph([_make_activity("a1"), _make_activity("a2")])
        drivers = {
            "R001": _driver(affected=("a1",), probability=1.0),
            "R002": _driver(affected=("a2",), probability=1.0),
        }
        n_iter = 500
        seed_uniform = np.random.default_rng(123).random((n_iter, 2))
        d1 = sample_risk_deltas(
            drivers, graph, n_iter, np.random.default_rng(42),
            severity_uniform=seed_uniform,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        d2 = sample_risk_deltas(
            drivers, graph, n_iter, np.random.default_rng(42),
            severity_uniform=seed_uniform,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        np.testing.assert_array_equal(d1, d2)


# ---------------------------------------------------------------------------
# Probability gate
# ---------------------------------------------------------------------------

class TestProbabilityGate:

    def test_zero_probability_zero_delta(self) -> None:
        graph = _make_graph([_make_activity("a1")])
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=10.0, ml=10.0, pess=10.0,
                probability=0.0,
            ),
        }
        rng = np.random.default_rng(42)
        deltas = sample_risk_deltas(drivers, graph, n_iter=500, rng=rng, mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert np.all(deltas == 0.0)

    def test_one_probability_always_fires(self) -> None:
        """Constant PERT (opt=ml=pess=10) days × 8 h/day = 80 h every iter."""
        graph = _make_graph([_make_activity("a1")])
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=10.0, ml=10.0, pess=10.0,
                probability=1.0,
            ),
        }
        rng = np.random.default_rng(42)
        deltas = sample_risk_deltas(drivers, graph, n_iter=500, rng=rng, mode_multipliers=TEST_MODE_MULTIPLIERS)
        # 10 days × 8 working hours = 80 working hours.
        np.testing.assert_allclose(deltas[:, 0], 80.0, atol=1e-3)

    # TESTLANE-01 A sweep: unmarked - measured 0.00s in the lane-1 durations, no
    # subprocess, no notebook, no engine run. It was in the slow class by habit.
    def test_probability_intermediate_approximate_fire_rate(self) -> None:
        """Mean fire-rate within tolerance of probability over 10k iter."""
        graph = _make_graph([_make_activity("a1")])
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=10.0, ml=10.0, pess=10.0,
                probability=0.3,
            ),
        }
        rng = np.random.default_rng(42)
        deltas = sample_risk_deltas(drivers, graph, n_iter=10_000, rng=rng, mode_multipliers=TEST_MODE_MULTIPLIERS)
        fired = deltas[:, 0] > 0.0
        observed_rate = float(fired.mean())
        # Within 2% of 0.3 — seeded rng makes this deterministic.
        assert abs(observed_rate - 0.3) < 0.02


# ---------------------------------------------------------------------------
# Additive PERT-days conversion
# ---------------------------------------------------------------------------

class TestAdditivePertDays:

    def test_additive_pert_days_converts_to_hours(self) -> None:
        """ml_pert=10 days × 8 h/day fires every iter → 80 h delta."""
        graph = _make_graph([_make_activity("a1")])
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=10.0, ml=10.0, pess=10.0,
                probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 100, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert np.all(np.isclose(deltas[:, 0], 80.0, atol=1e-3))

    def test_additive_pert_zero_when_opt_eq_pess(self) -> None:
        """Constant PERT collapses to deterministic ml × hours_per_day."""
        graph = _make_graph([_make_activity("a1")])
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=5.0, ml=5.0, pess=5.0,
                probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 100, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # 5 days × 8 h/day = 40 h.
        np.testing.assert_allclose(deltas[:, 0], 40.0, atol=1e-3)

    def test_additive_pert_days_broadcasts_to_all_affected_activities(self) -> None:
        graph = _make_graph([
            _make_activity("a1"), _make_activity("a2"), _make_activity("a3"),
        ])
        drivers = {
            "R001": _driver(
                affected=("a1", "a2", "a3"),
                opt=5.0, ml=5.0, pess=5.0,
                probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # Same delta across the three affected columns per iteration.
        np.testing.assert_allclose(deltas[:, 0], deltas[:, 1], atol=1e-3)
        np.testing.assert_allclose(deltas[:, 1], deltas[:, 2], atol=1e-3)
        np.testing.assert_allclose(deltas[:, 0], 40.0, atol=1e-3)


# ---------------------------------------------------------------------------
# Multiplicative PERT-factor conversion
# ---------------------------------------------------------------------------

class TestMultiplicativePertFactor:

    def test_multiplicative_factor_one_zero_delta(self) -> None:
        """factor=1 → (1-1)*base = 0 delta."""
        graph = _make_graph([_make_activity("a1", duration_hours=80.0)])
        drivers = {
            "R001": _driver(
                affected=("a1",),
                injection_method="multiplicative_pert_factor",
                opt=1.0, ml=1.0, pess=1.0,
                probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        np.testing.assert_allclose(deltas[:, 0], 0.0, atol=1e-3)

    def test_multiplicative_factor_two_doubles_duration(self) -> None:
        """factor=2 on base 80 h → (2-1)*80 = 80 h delta."""
        graph = _make_graph([_make_activity("a1", duration_hours=80.0)])
        drivers = {
            "R001": _driver(
                affected=("a1",),
                injection_method="multiplicative_pert_factor",
                opt=2.0, ml=2.0, pess=2.0,
                probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        np.testing.assert_allclose(deltas[:, 0], 80.0, atol=1e-3)

    def test_multiplicative_factor_uses_per_activity_base_duration(self) -> None:
        """Two activities w/ different bases → different deltas under same factor."""
        graph = _make_graph([
            _make_activity("a1", duration_hours=40.0),
            _make_activity("a2", duration_hours=80.0),
        ])
        drivers = {
            "R001": _driver(
                affected=("a1", "a2"),
                injection_method="multiplicative_pert_factor",
                opt=2.0, ml=2.0, pess=2.0,
                probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # (2-1) × 40 = 40, (2-1) × 80 = 80.
        np.testing.assert_allclose(deltas[:, 0], 40.0, atol=1e-3)
        np.testing.assert_allclose(deltas[:, 1], 80.0, atol=1e-3)


# ---------------------------------------------------------------------------
# Severity-uniform sharing
# ---------------------------------------------------------------------------

class TestSeverityUniform:

    def test_severity_uniform_consumed_for_pert_draw(self) -> None:
        """severity_uniform=0.5 → median PERT value (opt=ml=pess sanity check
        with a non-degenerate triangle)."""
        graph = _make_graph([_make_activity("a1")])
        # PERT (1, 2, 4) has CDF^-1(0.5) ≈ 2.13 days for default lambda=4.
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=1.0, ml=2.0, pess=4.0,
                probability=1.0,
            ),
        }
        n_iter = 50
        u = np.full((n_iter, 1), 0.5, dtype=np.float64)
        deltas = sample_risk_deltas(
            drivers, graph, n_iter, np.random.default_rng(42),
            severity_uniform=u,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # All iterations identical (same uniform → same PERT). And
        # within a sensible band — the median PERT(1,2,4) should be
        # between opt and pess.
        assert np.allclose(deltas[:, 0], deltas[0, 0], atol=1e-3)
        # In days: 1.0 ≤ median ≤ 4.0; in working hours: 8.0 ≤ ≤ 32.0.
        assert 8.0 <= float(deltas[0, 0]) <= 32.0

    def test_severity_uniform_alignment_to_driver_order(self) -> None:
        """Permuting drivers + matching severity_uniform columns → same result."""
        graph = _make_graph([_make_activity("a1"), _make_activity("a2")])
        n_iter = 100

        # Two drivers with very different PERT params so a column swap
        # would visibly change the per-activity delta.
        d_R001 = _driver(
            risk_id="R001", affected=("a1",),
            opt=10.0, ml=10.0, pess=10.0, probability=1.0,
        )
        d_R002 = _driver(
            risk_id="R002", affected=("a2",),
            opt=20.0, ml=20.0, pess=20.0, probability=1.0,
        )

        drivers_v1 = {"R001": d_R001, "R002": d_R002}
        drivers_v2 = {"R002": d_R002, "R001": d_R001}

        u_v1 = np.random.default_rng(7).random((n_iter, 2))
        # Permute u columns to match the v2 driver insertion order.
        u_v2 = u_v1[:, [1, 0]]

        d1 = sample_risk_deltas(
            drivers_v1, graph, n_iter, np.random.default_rng(42),
            severity_uniform=u_v1,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        d2 = sample_risk_deltas(
            drivers_v2, graph, n_iter, np.random.default_rng(42),
            severity_uniform=u_v2,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # The fire mask draws from rng.random(n_iter) per driver in
        # iteration order, so the permuted-driver run will draw the
        # fire mask in the opposite order. With probability=1.0
        # everywhere, fires are all True regardless, so the deltas
        # should match cell-for-cell.
        np.testing.assert_allclose(d1, d2, rtol=1e-5, atol=1e-3)

    def test_severity_uniform_none_falls_back_to_rng(self) -> None:
        graph = _make_graph([_make_activity("a1")])
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=1.0, ml=2.0, pess=4.0,
                probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 50, np.random.default_rng(42),
            severity_uniform=None,
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # Shape + dtype check; reproducibility is covered elsewhere.
        assert deltas.shape == (50, 1)
        assert deltas.dtype == np.float32

    def test_severity_uniform_shape_mismatch_raises(self) -> None:
        graph = _make_graph([_make_activity("a1")])
        drivers = {"R001": _driver(affected=("a1",))}
        # Shape is (n_iter, n_risks); pass wrong shape.
        u = np.full((50, 2), 0.5)
        with pytest.raises(ValueError, match="severity_uniform"):
            sample_risk_deltas(
                drivers, graph, 50, np.random.default_rng(42),
                severity_uniform=u,
            mode_multipliers=TEST_MODE_MULTIPLIERS)


# ---------------------------------------------------------------------------
# Multi-risk superposition
# ---------------------------------------------------------------------------

class TestMultiRiskSuperposition:

    def test_multiple_risks_same_activity_sum(self) -> None:
        """Two drivers each adding 5 days → 5×8 + 5×8 = 80 h on shared activity."""
        graph = _make_graph([_make_activity("a1")])
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=5.0, ml=5.0, pess=5.0, probability=1.0,
            ),
            "R002": _driver(
                affected=("a1",),
                opt=5.0, ml=5.0, pess=5.0, probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # Each contributes 5 × 8 = 40; sum = 80.
        np.testing.assert_allclose(deltas[:, 0], 80.0, atol=1e-3)

    def test_disjoint_risks_independent(self) -> None:
        """Disjoint affected sets → non-overlapping delta columns."""
        graph = _make_graph([
            _make_activity("a1"), _make_activity("a2"), _make_activity("a3"),
        ])
        drivers = {
            "R001": _driver(
                affected=("a1",),
                opt=5.0, ml=5.0, pess=5.0, probability=1.0,
            ),
            "R002": _driver(
                affected=("a3",),
                opt=10.0, ml=10.0, pess=10.0, probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        np.testing.assert_allclose(deltas[:, 0], 40.0, atol=1e-3)
        np.testing.assert_allclose(deltas[:, 1], 0.0, atol=1e-3)
        np.testing.assert_allclose(deltas[:, 2], 80.0, atol=1e-3)


# ---------------------------------------------------------------------------
# apply_to_durations
# ---------------------------------------------------------------------------

class TestApplyToDurations:

    def test_apply_to_durations_broadcasts_base(self) -> None:
        base = np.asarray([10.0, 20.0, 30.0], dtype=np.float64)
        deltas = np.zeros((5, 3), dtype=np.float32)
        durations = apply_to_durations(base, deltas)
        assert durations.shape == (5, 3)
        np.testing.assert_allclose(durations[0], [10.0, 20.0, 30.0])
        np.testing.assert_allclose(durations[4], [10.0, 20.0, 30.0])

    def test_apply_to_durations_zero_floor(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Negative delta exceeding base clips at 0 with WARNING."""
        base = np.asarray([10.0, 10.0], dtype=np.float64)
        deltas = np.asarray([[-20.0, 5.0], [-15.0, 0.0]], dtype=np.float32)
        with caplog.at_level(logging.WARNING):
            durations = apply_to_durations(base, deltas)
        # Two negative cells in the result before clipping; both clipped.
        assert durations[0, 0] == 0.0
        assert durations[1, 0] == 0.0
        # Non-clipped cells unchanged.
        assert durations[0, 1] == 15.0
        assert durations[1, 1] == 10.0
        msgs = [r.getMessage() for r in caplog.records]
        assert any("clipped" in m and "2" in m for m in msgs)

    def test_apply_to_durations_dtype_float32_default(self) -> None:
        """float64 inputs → float32 output (precision plumbing)."""
        base = np.asarray([10.0, 20.0], dtype=np.float64)
        deltas = np.zeros((3, 2), dtype=np.float64)
        durations = apply_to_durations(base, deltas)
        assert durations.dtype == np.float32

    def test_apply_to_durations_explicit_float64(self) -> None:
        base = np.asarray([10.0, 20.0], dtype=np.float32)
        deltas = np.zeros((3, 2), dtype=np.float32)
        durations = apply_to_durations(base, deltas, precision="float64")
        assert durations.dtype == np.float64


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_n_iter_zero_returns_empty_shape(self) -> None:
        """``n_iter=0`` returns a (0, n_act) array — last-batch edge case
        from the chunked-iteration orchestrator (Beta-05).
        """
        graph = _make_graph([_make_activity("a1"), _make_activity("a2")])
        drivers = {"R001": _driver(affected=("a1",), probability=0.5)}
        deltas = sample_risk_deltas(
            drivers, graph, n_iter=0, rng=np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert deltas.shape == (0, 2)
        assert deltas.dtype == np.float32

    def test_no_drivers_zero_delta_array(self) -> None:
        graph = _make_graph(
            [_make_activity(f"a{i}") for i in range(5)]
        )
        deltas = sample_risk_deltas(
            {}, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert deltas.shape == (50, 5)
        assert np.all(deltas == 0.0)

    def test_driver_with_zero_expansion_skipped(self) -> None:
        """Driver with empty affected_activity_ids contributes no delta."""
        graph = _make_graph([_make_activity("a1")])
        drivers = {
            "R001": _driver(
                affected=(),
                opt=10.0, ml=10.0, pess=10.0, probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert np.all(deltas == 0.0)

    def test_zero_expansion_driver_advances_rng_stream(self) -> None:
        """Zero-expansion drivers consume their fire-mask RNG slot.

        Consumer-side robustness: if a rule's expansion changes from
        non-empty to empty between runs (e.g. schedule revision), the
        rng stream for the surviving drivers must still be reproducible.
        That's only true if the zero-expansion driver advances the rng
        in the same place it would have advanced when non-empty.
        """
        graph = _make_graph([_make_activity("a1"), _make_activity("a2")])

        # Two configurations of two drivers in the same iteration order;
        # only difference is whether R001 has a non-empty expansion.
        drivers_with_expansion = {
            "R001": _driver(risk_id="R001", affected=("a1",), probability=0.5),
            "R002": _driver(
                risk_id="R002",
                affected=("a2",),
                opt=10.0, ml=10.0, pess=10.0,
                probability=0.5,
            ),
        }
        drivers_zero_expansion_R001 = {
            "R001": _driver(risk_id="R001", affected=(), probability=0.5),
            "R002": _driver(
                risk_id="R002",
                affected=("a2",),
                opt=10.0, ml=10.0, pess=10.0,
                probability=0.5,
            ),
        }

        d1 = sample_risk_deltas(
            drivers_with_expansion, graph, 200, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        d2 = sample_risk_deltas(
            drivers_zero_expansion_R001, graph, 200, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)

        # Column for a2 must match between the two runs — the surviving
        # driver R002 sees the same fire-mask stream because R001's
        # zero-expansion still consumed its rng slot.
        np.testing.assert_array_equal(d1[:, 1], d2[:, 1])

    def test_driver_with_unknown_activity_id_silently_skipped(self) -> None:
        """An affected_activity_id absent from the graph contributes no delta.

        Defensive — the orchestrator is expected to filter, but
        sample_risk_deltas must not raise on a stale audit-trail row
        referencing a renamed activity.
        """
        graph = _make_graph([_make_activity("a1")])
        drivers = {
            "R001": _driver(
                affected=("a1", "missing_id"),
                opt=5.0, ml=5.0, pess=5.0, probability=1.0,
            ),
        }
        deltas = sample_risk_deltas(
            drivers, graph, 50, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        # a1 still gets the delta; the unknown id is silently skipped.
        np.testing.assert_allclose(deltas[:, 0], 40.0, atol=1e-3)


# ---------------------------------------------------------------------------
# Full-pipeline smoke
# ---------------------------------------------------------------------------

class TestBuildDurationArray:

    def test_build_duration_array_full_pipeline(self) -> None:
        """End-to-end: drivers + graph + n_iter → durations ready for run_batch.

        Constructs a 4-activity chain (root → A → B → sink) with FS
        links, builds durations through risk_injection, runs the kernel,
        and asserts that with probability>0 risks the project_finish
        distribution is non-degenerate.
        """
        a_root = _make_activity("root", duration_hours=0.0)
        a_a = _make_activity("A", duration_hours=80.0)
        a_b = _make_activity("B", duration_hours=80.0)
        a_sink = _make_activity("sink", duration_hours=0.0)
        links = [
            Link(pred_id="root", succ_id="A", link_type="FS", lag_hours=0.0),
            Link(pred_id="A", succ_id="B", link_type="FS", lag_hours=0.0),
            Link(pred_id="B", succ_id="sink", link_type="FS", lag_hours=0.0),
        ]
        # Wire predecessor / successor link lists onto the activities.
        a_root.successor_links.append(links[0])
        a_a.predecessor_links.append(links[0])
        a_a.successor_links.append(links[1])
        a_b.predecessor_links.append(links[1])
        a_b.successor_links.append(links[2])
        a_sink.predecessor_links.append(links[2])

        graph = _make_graph(
            [a_root, a_a, a_b, a_sink],
            links=links,
            topo_order=["root", "A", "B", "sink"],
        )

        drivers = {
            "R001": _driver(
                risk_id="R001",
                affected=("A",),
                opt=10.0, ml=10.0, pess=10.0,
                probability=0.5,
            ),
        }
        n_iter = 1_000
        durations = build_duration_array(
            drivers, graph, n_iter, np.random.default_rng(42),
        mode_multipliers=TEST_MODE_MULTIPLIERS)
        assert durations.shape == (n_iter, 4)
        assert durations.dtype == np.float32

        # Project finish must vary across iterations.
        out = run_batch(durations, graph, calendar=_DEFAULT_CAL)
        finish = out["project_finish"]
        assert finish.shape == (n_iter,)
        # With probability=0.5, some iterations don't fire (delta=0,
        # finish=160 h) and others fire (delta=80, finish=240 h). At
        # least two distinct values must appear.
        unique = np.unique(np.round(finish, 3))
        assert len(unique) >= 2
        # Both 160 and 240 should be present.
        assert any(np.isclose(unique, 160.0, atol=1e-1))
        assert any(np.isclose(unique, 240.0, atol=1e-1))
