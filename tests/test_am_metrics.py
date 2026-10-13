"""Tests for src.am.metrics.

Layered like the module:

1. Unit tests for the pure-data functions (lognormal_p_band,
   compute_per_activity_p_bands, compute_ssi_per_risk,
   compute_tornado_proxy_per_risk, build_methodology_notes).
2. Integration tests for the leave-one-out and counterfactual
   layers against the live template.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.input_skips import skip_missing


from src.sra.cpm.risk_driver_schema import RiskDriver

from src.am.metrics import (
    ActivityPBand,
    DEFAULT_COUNTERFACTUAL_ITERATIONS,
    DEFAULT_DAYS_AT_RISK_ITERATIONS,
    build_methodology_notes,
    compute_counterfactual_sweep,
    compute_days_at_risk_per_risk,
    compute_leave_one_out_metrics,
    compute_per_activity_p_bands,
    compute_per_risk_criticality,
    compute_ssi_per_risk,
    compute_tornado_proxy_per_risk,
    divergence_flag,
    lognormal_p_band,
)


AM_REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = AM_REPO_ROOT / "status_periods" / "wind_am_template.xlsx"
REGISTER_V9 = AM_REPO_ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"
XER_PATH = AM_REPO_ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_schedule.xer"
STRAWMAN_PATH = AM_REPO_ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"  # the wind tier is its own strawman


# ---------------------------------------------------------------------------
# Lognormal moment-fit unit tests
# ---------------------------------------------------------------------------

class TestLognormalPBand:
    pytestmark = pytest.mark.unit

    def test_standard_case_monotonic(self) -> None:
        p10, p50, p90 = lognormal_p_band(100.0, 10.0)
        assert 0.0 < p10 < p50 < p90
        # Median of lognormal == exp(mu) when fit to (mean, std);
        # for low CV this is very close to the mean.
        assert abs(p50 - 100.0) < 1.0

    def test_zero_std_collapses_to_point(self) -> None:
        """Degenerate case: zero variance -> all percentiles == mean."""
        assert lognormal_p_band(100.0, 0.0) == (100.0, 100.0, 100.0)

    def test_zero_mean_collapses_to_zero(self) -> None:
        assert lognormal_p_band(0.0, 5.0) == (0.0, 0.0, 0.0)

    def test_negative_mean_collapses(self) -> None:
        """Engineering sanity: a non-physical negative mean returns the
        mean at every percentile (degenerate branch)."""
        assert lognormal_p_band(-5.0, 2.0) == (-5.0, -5.0, -5.0)

    def test_high_cv_still_monotonic_and_finite(self) -> None:
        p10, p50, p90 = lognormal_p_band(100.0, 200.0)  # CV=2.0
        assert all(np.isfinite([p10, p50, p90]))
        assert p10 < p50 < p90
        assert p10 > 0.0  # lognormal is non-negative

    def test_custom_percentiles(self) -> None:
        """Caller can request other percentiles."""
        vals = lognormal_p_band(100.0, 10.0, percentiles=(0.05, 0.95))
        assert len(vals) == 2
        assert vals[0] < vals[1]


# ---------------------------------------------------------------------------
# Synthetic ScheduleMCResult builder for downstream unit tests
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _StubScheduleMCResult:
    """Minimal stub that satisfies the metrics-module interface."""
    activity_ids: tuple[str, ...]
    finish_mean_hours: np.ndarray
    finish_std_hours: np.ndarray
    criticality_index: dict[str, float]
    project_finish_hours: np.ndarray
    n_act: int
    n_iter: int


def _stub_result() -> _StubScheduleMCResult:
    return _StubScheduleMCResult(
        activity_ids=("a1", "a2", "a3"),
        finish_mean_hours=np.array([80.0, 160.0, 240.0], dtype=np.float64),
        finish_std_hours=np.array([0.0, 10.0, 20.0], dtype=np.float64),
        criticality_index={"a1": 1.0, "a2": 0.8, "a3": 0.4},
        project_finish_hours=np.array(
            [240.0, 250.0, 230.0, 260.0, 245.0], dtype=np.float32
        ),
        n_act=3,
        n_iter=5,
    )


# ---------------------------------------------------------------------------
# Per-activity P-band derivation unit tests
# ---------------------------------------------------------------------------

class TestPerActivityPBands:
    pytestmark = pytest.mark.unit

    def test_top_n_truncation_excludes_zero_variance(self) -> None:
        """AM02.1 §4.B.2: top_n truncation operates AFTER the non-zero
        variance filter. a1 has finish_std=0 so is excluded by the
        filter; a2 (CI=0.8) and a3 (CI=0.4) survive."""
        r = _stub_result()
        rows = compute_per_activity_p_bands(
            schedule_result=r,
            activity_durations_hours={"a1": 80.0, "a2": 80.0, "a3": 80.0},
            activity_names={"a1": "Task A1", "a2": "Task A2", "a3": "Task A3"},
            deterministic_ef_hours={"a1": 80.0, "a2": 160.0, "a3": 240.0},
            hours_per_day=8.0,
            top_n=2,
            ci_threshold=0.0,
        )
        ids = [row.activity_id for row in rows]
        assert "a1" not in ids  # zero variance, excluded
        assert ids == ["a2", "a3"]

    def test_ci_threshold_filters_compound_with_variance_filter(self) -> None:
        """CI threshold and variance filter compound: a1 excluded by
        variance, a3 excluded by CI < threshold, only a2 survives."""
        r = _stub_result()
        rows = compute_per_activity_p_bands(
            schedule_result=r,
            activity_durations_hours={"a1": 80.0, "a2": 80.0, "a3": 80.0},
            activity_names={"a1": "A1", "a2": "A2", "a3": "A3"},
            deterministic_ef_hours=None,
            hours_per_day=8.0,
            top_n=10,
            ci_threshold=0.5,  # excludes a3 (CI=0.4)
        )
        ids = [row.activity_id for row in rows]
        assert ids == ["a2"]  # a1 by variance, a3 by CI; a2 survives

    def test_zero_variance_activities_excluded_by_filter(self) -> None:
        """AM02.1 §4.B.2: activities with finish_std == 0 are filtered
        out of the top-N table because their lognormal P-band
        collapses to a point and is uninformative on the analyst
        stochastic Gantt."""
        r = _stub_result()
        rows = compute_per_activity_p_bands(
            schedule_result=r,
            activity_durations_hours={"a1": 80.0, "a2": 80.0, "a3": 80.0},
            activity_names={"a1": "A1", "a2": "A2", "a3": "A3"},
            deterministic_ef_hours=None,
            hours_per_day=8.0,
            top_n=10,
            ci_threshold=0.0,
        )
        for row in rows:
            assert row.activity_id != "a1"  # a1 had zero variance

    def test_p_band_monotonic_and_non_negative(self) -> None:
        r = _stub_result()
        rows = compute_per_activity_p_bands(
            schedule_result=r,
            activity_durations_hours={"a1": 80.0, "a2": 80.0, "a3": 80.0},
            activity_names={"a1": "A1", "a2": "A2", "a3": "A3"},
            deterministic_ef_hours=None,
            hours_per_day=8.0,
            top_n=10,
            ci_threshold=0.0,
        )
        for row in rows:
            assert row.p10_finish_days <= row.p50_finish_days <= row.p90_finish_days
            assert row.p10_start_days <= row.p50_start_days <= row.p90_start_days
            for v in (
                row.p10_finish_days, row.p50_finish_days, row.p90_finish_days,
                row.p10_start_days, row.p50_start_days, row.p90_start_days,
            ):
                assert v >= 0.0

    def test_start_equals_finish_minus_duration(self) -> None:
        r = _stub_result()
        rows = compute_per_activity_p_bands(
            schedule_result=r,
            activity_durations_hours={"a1": 80.0, "a2": 80.0, "a3": 80.0},
            activity_names={"a1": "A1", "a2": "A2", "a3": "A3"},
            deterministic_ef_hours=None,
            hours_per_day=8.0,
            top_n=10,
            ci_threshold=0.0,
        )
        for row in rows:
            # duration = 80h = 10 days
            assert row.p50_start_days == pytest.approx(row.p50_finish_days - 10.0)

    def test_det_es_ef_populated_when_passed(self) -> None:
        r = _stub_result()
        rows = compute_per_activity_p_bands(
            schedule_result=r,
            activity_durations_hours={"a1": 80.0, "a2": 80.0, "a3": 80.0},
            activity_names={"a1": "A1", "a2": "A2", "a3": "A3"},
            deterministic_ef_hours={"a1": 80.0, "a2": 160.0, "a3": 240.0},
            hours_per_day=8.0,
            top_n=10,
            ci_threshold=0.0,
        )
        for row in rows:
            assert row.det_ef_days is not None
            assert row.det_es_days is not None

    def test_all_zero_variance_returns_empty_list(self) -> None:
        """AM02.1 §4.B.2 degenerate case: every activity has finish_std
        == 0 -> filter removes all -> empty list returned. No error."""
        r = _StubScheduleMCResult(
            activity_ids=("a1", "a2", "a3"),
            finish_mean_hours=np.array([80.0, 160.0, 240.0], dtype=np.float64),
            finish_std_hours=np.zeros(3, dtype=np.float64),  # all zero
            criticality_index={"a1": 1.0, "a2": 0.8, "a3": 0.4},
            project_finish_hours=np.array([240.0] * 5, dtype=np.float32),
            n_act=3,
            n_iter=5,
        )
        rows = compute_per_activity_p_bands(
            schedule_result=r,
            activity_durations_hours={"a1": 80.0, "a2": 80.0, "a3": 80.0},
            activity_names={"a1": "A1", "a2": "A2", "a3": "A3"},
            deterministic_ef_hours=None,
            hours_per_day=8.0,
            top_n=10,
            ci_threshold=0.0,
        )
        assert rows == []

    def test_all_non_zero_variance_filter_is_noop(self) -> None:
        """AM02.1 §4.B.2 sanity: every activity has finish_std > 0 ->
        filter is a no-op, top-N selection by CI works unchanged."""
        r = _StubScheduleMCResult(
            activity_ids=("a1", "a2", "a3"),
            finish_mean_hours=np.array([80.0, 160.0, 240.0], dtype=np.float64),
            finish_std_hours=np.array([5.0, 10.0, 20.0], dtype=np.float64),
            criticality_index={"a1": 1.0, "a2": 0.8, "a3": 0.4},
            project_finish_hours=np.array([240.0] * 5, dtype=np.float32),
            n_act=3,
            n_iter=5,
        )
        rows = compute_per_activity_p_bands(
            schedule_result=r,
            activity_durations_hours={"a1": 80.0, "a2": 80.0, "a3": 80.0},
            activity_names={"a1": "A1", "a2": "A2", "a3": "A3"},
            deterministic_ef_hours=None,
            hours_per_day=8.0,
            top_n=2,
            ci_threshold=0.0,
        )
        # Sorted by CI desc, top 2 = [a1, a2]
        assert [row.activity_id for row in rows] == ["a1", "a2"]


def test_top_n_activity_filter_methodology_note_present() -> None:
    """AM02.1 §4.B.2: build_methodology_notes emits a
    top_n_activity_filter note disclosing the non-zero variance
    filter."""
    notes = build_methodology_notes(p_band_method="B")
    topics = {n["topic"] for n in notes}
    assert "top_n_activity_filter" in topics
    note = next(n for n in notes if n["topic"] == "top_n_activity_filter")
    assert note["method"] == "non_zero_variance"
    assert "finish_std_hours > 0" in note["text"]
    assert "queued_for_v1_1" in note


# ---------------------------------------------------------------------------
# SSI / tornado / methodology unit tests
# ---------------------------------------------------------------------------

class TestSSIAndTornado:
    pytestmark = pytest.mark.unit

    def test_ssi_per_risk_finite_and_signed(self) -> None:
        r = _stub_result()
        drivers = {
            "R001": RiskDriver(
                risk_id="R001",
                affected_activity_ids=("a1", "a2"),
                injection_method="additive_pert_days",
                opt_pert=0.0, ml_pert=5.0, pess_pert=20.0,
                probability=0.3,
            ),
        }
        ssi = compute_ssi_per_risk(r, drivers)
        # R001 affects a1 (finish_std=0 contributes 0) and a2 (finish_std=10,
        # CI=0.8); project_std = std(project_finish_hours).
        assert "R001" in ssi
        assert ssi["R001"] >= 0.0
        assert np.isfinite(ssi["R001"])

    def test_ssi_degenerate_zero_project_std(self) -> None:
        """No project-level variance -> all SSI = 0."""
        @dataclass(frozen=True)
        class _Stub:
            activity_ids: tuple[str, ...] = ("a1",)
            finish_std_hours: Any = None
            criticality_index: Any = None
            project_finish_hours: Any = None
            n_act: int = 1
        s = _Stub(
            finish_std_hours=np.array([5.0]),
            criticality_index={"a1": 1.0},
            project_finish_hours=np.array([100.0, 100.0, 100.0]),
        )
        drivers = {
            "R001": RiskDriver(
                risk_id="R001",
                affected_activity_ids=("a1",),
                injection_method="additive_pert_days",
                opt_pert=0.0, ml_pert=5.0, pess_pert=10.0,
                probability=0.1,
            ),
        }
        ssi = compute_ssi_per_risk(s, drivers)
        assert ssi["R001"] == 0.0

    def test_tornado_proxy_pert_formula(self) -> None:
        drivers = {
            "R001": RiskDriver(
                risk_id="R001",
                affected_activity_ids=("a1",),
                injection_method="additive_pert_days",
                opt_pert=2.0, ml_pert=8.0, pess_pert=20.0,
                probability=0.5,
            ),
        }
        proxy = compute_tornado_proxy_per_risk(drivers, hours_per_day=8.0)
        # sigma_days = (20 - 2) / 6 = 3.0; weighted by prob 0.5 = 1.5
        assert proxy["R001"] == pytest.approx(1.5)

    def test_tornado_proxy_zero_for_multiplicative_methods(self) -> None:
        """Multiplicative injection methods don't have day-scale PERT
        params; proxy returns 0 to flag that a sample-based sigma is
        unavailable in v1."""
        drivers = {
            "R001": RiskDriver(
                risk_id="R001",
                affected_activity_ids=("a1",),
                injection_method="multiplicative_pert_factor",
                opt_pert=0.9, ml_pert=1.0, pess_pert=1.2,
                probability=0.5,
            ),
        }
        proxy = compute_tornado_proxy_per_risk(drivers, hours_per_day=8.0)
        assert proxy["R001"] == 0.0


# ---------------------------------------------------------------------------
# AM02.1 §3.A.3 — per-risk criticality and divergence_flag
# ---------------------------------------------------------------------------

class TestPerRiskCriticalityAM02_1:
    """Per-risk Mode-conditioned + Mode-independent CI aggregation."""

    pytestmark = pytest.mark.unit

    def _stub_with_independent(
        self,
        cond_ci: dict[str, float],
        indep_ci: dict[str, float] | None,
    ):
        """Synthetic schedule result with both CI dicts."""
        from dataclasses import dataclass as _dc

        @_dc(frozen=True)
        class _S:
            activity_ids: tuple[str, ...]
            criticality_index: dict[str, float]
            mode_independent_criticality_index: dict[str, float] | None
        return _S(
            activity_ids=tuple(cond_ci.keys()),
            criticality_index=cond_ci,
            mode_independent_criticality_index=indep_ci,
        )

    def test_max_aggregation_over_affected_activities(self) -> None:
        """Risk affecting 3 activities with CI [0.2, 0.5, 0.9] -> 0.9."""
        s = self._stub_with_independent(
            cond_ci={"a1": 0.2, "a2": 0.5, "a3": 0.9, "a4": 0.0},
            indep_ci={"a1": 0.3, "a2": 0.6, "a3": 0.95, "a4": 0.0},
        )
        d = {"R001": RiskDriver(
            risk_id="R001",
            affected_activity_ids=("a1", "a2", "a3"),
            injection_method="additive_pert_days",
            opt_pert=0.0, ml_pert=5.0, pess_pert=20.0,
            probability=0.3, mode="Series",
        )}
        out = compute_per_risk_criticality(s, d)
        assert out["R001"]["criticality_conditioned"] == pytest.approx(0.9)
        assert out["R001"]["criticality_independent"] == pytest.approx(0.95)

    def test_empty_affected_activity_ids_returns_none(self) -> None:
        s = self._stub_with_independent(cond_ci={"a1": 0.5}, indep_ci=None)
        d = {"R001": RiskDriver(
            risk_id="R001",
            affected_activity_ids=(),
            injection_method="additive_pert_days",
            opt_pert=0.0, ml_pert=5.0, pess_pert=20.0,
            probability=0.3,
        )}
        out = compute_per_risk_criticality(s, d)
        assert out["R001"]["criticality_conditioned"] is None
        assert out["R001"]["criticality_independent"] is None

    def test_independent_ci_unavailable_returns_none_for_independent(
        self,
    ) -> None:
        """When mode_independent_criticality_index is None, conditioned
        is still populated, independent is None."""
        s = self._stub_with_independent(
            cond_ci={"a1": 0.7}, indep_ci=None,
        )
        d = {"R001": RiskDriver(
            risk_id="R001",
            affected_activity_ids=("a1",),
            injection_method="additive_pert_days",
            opt_pert=0.0, ml_pert=5.0, pess_pert=20.0,
            probability=0.3,
        )}
        out = compute_per_risk_criticality(s, d)
        assert out["R001"]["criticality_conditioned"] == pytest.approx(0.7)
        assert out["R001"]["criticality_independent"] is None

    def test_independent_ci_empty_dict_treated_as_unavailable(self) -> None:
        """An empty dict (rather than None) on the engine still means
        the Mode-independent measurement wasn't computed."""
        s = self._stub_with_independent(
            cond_ci={"a1": 0.7}, indep_ci={},
        )
        d = {"R001": RiskDriver(
            risk_id="R001",
            affected_activity_ids=("a1",),
            injection_method="additive_pert_days",
            opt_pert=0.0, ml_pert=5.0, pess_pert=20.0,
            probability=0.3,
        )}
        out = compute_per_risk_criticality(s, d)
        assert out["R001"]["criticality_independent"] is None

    def test_unmapped_activity_ids_silently_skipped(self) -> None:
        """A risk affecting an activity not in the engine output -> the
        unmapped activity is skipped, max is taken over the remaining
        mapped activities."""
        s = self._stub_with_independent(
            cond_ci={"a1": 0.5, "a2": 0.8}, indep_ci=None,
        )
        d = {"R001": RiskDriver(
            risk_id="R001",
            affected_activity_ids=("a1", "a2", "a99"),  # a99 not in engine
            injection_method="additive_pert_days",
            opt_pert=0.0, ml_pert=5.0, pess_pert=20.0,
            probability=0.3,
        )}
        out = compute_per_risk_criticality(s, d)
        assert out["R001"]["criticality_conditioned"] == pytest.approx(0.8)


class TestDivergenceFlagAM02_1:
    """divergence_flag: consistent / mode_amplifies / mode_suppresses."""

    pytestmark = pytest.mark.unit

    def test_within_threshold_consistent(self) -> None:
        assert divergence_flag(0.80, 0.82) == "consistent"
        assert divergence_flag(0.80, 0.78) == "consistent"

    def test_conditioned_higher_amplifies(self) -> None:
        assert divergence_flag(0.90, 0.80) == "mode_amplifies"

    def test_conditioned_lower_suppresses(self) -> None:
        assert divergence_flag(0.70, 0.85) == "mode_suppresses"

    def test_none_inputs_default_to_consistent(self) -> None:
        """No signal -> no claim of divergence."""
        assert divergence_flag(None, 0.8) == "consistent"
        assert divergence_flag(0.8, None) == "consistent"
        assert divergence_flag(None, None) == "consistent"

    def test_threshold_boundary(self) -> None:
        """Exactly at threshold = consistent; just past = divergent."""
        assert divergence_flag(0.85, 0.80) == "consistent"  # diff = 0.05 (not >)
        assert divergence_flag(0.851, 0.80) == "mode_amplifies"


class TestMethodologyNotes:
    pytestmark = pytest.mark.unit

    def test_method_b_lognormal_note_present(self) -> None:
        notes = build_methodology_notes(p_band_method="B")
        topics = {n["topic"] for n in notes}
        assert "per_activity_p_bands" in topics
        per_act = next(n for n in notes if n["topic"] == "per_activity_p_bands")
        assert per_act["method"] == "B"
        # Verbatim text fragments per Doc 3 v2.2 §audit
        assert "lognormal moment-fit" in per_act["text"]
        assert "per-activity Mean and standard deviation of finish day" in per_act["text"]
        assert "AACE 132R-23" in per_act["text"]
        assert per_act["queued_for_v1_1"] == "Per-iteration ES/EF persistence"

    def test_subsampled_iteration_note_present(self) -> None:
        notes = build_methodology_notes()
        topics = {n["topic"] for n in notes}
        assert "counterfactual_iteration_budget" in topics

    def test_tornado_and_cruciality_proxy_notes_present(self) -> None:
        notes = build_methodology_notes()
        topics = {n["topic"] for n in notes}
        assert "per_risk_tornado_sigma" in topics
        assert "per_risk_cruciality_proxy" in topics


# ---------------------------------------------------------------------------
# AM04 - sample-based per-risk tornado sigma (leave-one-out variance)
# ---------------------------------------------------------------------------

class TestSampleSigmaAM04:
    """compute_leave_one_out_metrics: the sample-sigma derivation.

    The expensive engine re-run is monkeypatched so the test is a fast,
    deterministic unit check of the std-delta arithmetic and the no-double-
    compute contract (both metrics fall out of ONE loop). The fake runner
    returns a controllable finish distribution per left-out risk, keyed by
    which risk the synthetic workbook marks Closed.
    """

    pytestmark = pytest.mark.unit

    @staticmethod
    def _build_inputs(responses: dict[str, np.ndarray]):
        """A ConditionalRunInputs whose workbook carries the named risks
        (all Open), plus a baseline schedule result. ``responses`` maps a
        left-out risk_id -> the finish-hours array its leave-one-out re-run
        should return."""
        from pathlib import Path as _P

        from src.am.conditional_runner import ConditionalRunInputs
        from src.am.workbook_reader import WorkbookData

        rows = [
            {"risk_id": rid, "risk_title": rid, "status_this_period": "Open",
             "probability_override": None, "mode_override": None,
             "owner": None, "notes_this_period": None}
            for rid in responses
        ]
        wb = WorkbookData(
            period_info={}, risk_status=rows,
            milestones=[], mitigations=[], am_risk_ids=list(responses),
        )
        inputs = ConditionalRunInputs(
            workbook_data=wb,
            register_path=_P("dummy"), xer_path=_P("dummy"),
            strawman_path=_P("dummy"), n_iter=1000, seed=42,
        )
        return inputs

    @staticmethod
    def _fake_runner(responses: dict[str, np.ndarray]):
        from types import SimpleNamespace

        def _run(loop_inputs):
            closed = [
                r["risk_id"] for r in loop_inputs.workbook_data.risk_status
                if r.get("status_this_period") == "Closed"
            ]
            assert len(closed) == 1, closed
            arr = responses[closed[0]]
            return SimpleNamespace(
                schedule_result=SimpleNamespace(project_finish_hours=arr)
            )

        return _run

    def test_wider_variance_risk_has_bigger_sample_sigma(
        self, monkeypatch
    ) -> None:
        """Removing the higher-variance risk reduces std more, so its
        sample_sigma is larger; both are non-negative within the floor."""
        import src.am.conditional_runner as cr

        pattern = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])  # zero-mean, std~1.414
        base = 100.0 + pattern * 10.0  # baseline std ~14.14 h
        responses = {
            "R_wide": 100.0 + pattern * 2.0,    # std ~2.83 -> big reduction
            "R_narrow": 100.0 + pattern * 9.0,  # std ~12.73 -> small reduction
        }
        inputs = self._build_inputs(responses)
        monkeypatch.setattr(cr, "run_conditional_mc", self._fake_runner(responses))

        baseline = SimpleNamespace_finish(base)
        out = compute_leave_one_out_metrics(
            baseline_inputs=inputs,
            baseline_schedule_result=baseline,
            risks_to_iterate=["R_wide", "R_narrow"],
            n_iter=1000,
            p_level=80,
        )
        sig_wide = out["R_wide"]["sample_sigma_days"]
        sig_narrow = out["R_narrow"]["sample_sigma_days"]
        assert sig_wide > sig_narrow
        assert sig_narrow >= 0.0
        # Both keys produced from the one loop (no double compute).
        assert set(out["R_wide"]) == {"days_at_risk_p80", "sample_sigma_days"}

    def test_resolved_risk_self_zeros(self, monkeypatch) -> None:
        """AM04 AC9 / self-zero property: a Closed or Fired risk's
        leave-one-out re-run reproduces the baseline finish distribution
        (the conditional runner already pinned it out), so its
        sample_sigma is within the noise floor of 0. Modelled here by the
        fake runner returning the baseline array verbatim for both."""
        import src.am.conditional_runner as cr

        pattern = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
        base = 100.0 + pattern * 10.0
        responses = {
            "R_closed": base.copy(),  # resolved -> re-run == baseline
            "R_fired": base.copy(),
        }
        inputs = self._build_inputs(responses)
        monkeypatch.setattr(cr, "run_conditional_mc", self._fake_runner(responses))

        out = compute_leave_one_out_metrics(
            baseline_inputs=inputs,
            baseline_schedule_result=SimpleNamespace_finish(base),
            risks_to_iterate=["R_closed", "R_fired"],
            n_iter=1000,
            p_level=80,
        )
        floor = 0.3  # 10k-iter precision floor language (days)
        for rid in ("R_closed", "R_fired"):
            assert out[rid]["sample_sigma_days"] == 0.0
            assert abs(out[rid]["sample_sigma_days"]) <= floor

    def test_days_at_risk_wrapper_matches_combined(self, monkeypatch) -> None:
        """The thin compute_days_at_risk_per_risk wrapper returns exactly
        the days_at_risk_p80 projection of the combined helper (back-compat
        of the single-loop refactor)."""
        import src.am.conditional_runner as cr

        pattern = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
        base = 100.0 + pattern * 10.0
        responses = {"R1": 100.0 + pattern * 4.0, "R2": 100.0 + pattern * 8.0}
        inputs = self._build_inputs(responses)
        monkeypatch.setattr(cr, "run_conditional_mc", self._fake_runner(responses))

        baseline = SimpleNamespace_finish(base)
        combined = compute_leave_one_out_metrics(
            baseline_inputs=inputs, baseline_schedule_result=baseline,
            risks_to_iterate=["R1", "R2"], n_iter=1000, p_level=80,
        )
        # Re-patch (the loop consumed nothing stateful, but keep it clean).
        monkeypatch.setattr(cr, "run_conditional_mc", self._fake_runner(responses))
        wrapped = compute_days_at_risk_per_risk(
            baseline_inputs=inputs, baseline_schedule_result=baseline,
            risks_to_iterate=["R1", "R2"], n_iter=1000, p_level=80,
        )
        assert wrapped == {
            rid: combined[rid]["days_at_risk_p80"] for rid in combined
        }


def SimpleNamespace_finish(arr: np.ndarray):
    """Minimal baseline schedule result exposing project_finish_hours."""
    from types import SimpleNamespace

    return SimpleNamespace(project_finish_hours=np.asarray(arr, dtype=np.float64))


# ---------------------------------------------------------------------------
# Integration: leave-one-out and counterfactual against live template
# ---------------------------------------------------------------------------

class TestLeaveOneOutIntegration:
    pytestmark = pytest.mark.integration

    @pytest.fixture(scope="class")
    def baseline_run(self):
        from src.am.workbook_reader import read_workbook
        from src.am.conditional_runner import (
            ConditionalRunInputs, run_conditional_mc,
        )
        for name, p in (
            ("template", TEMPLATE_PATH), ("V9", REGISTER_V9),
            ("xer", XER_PATH), ("strawman", STRAWMAN_PATH),
        ):
            if not p.is_file():
                skip_missing(p, label=name)
        workbook = read_workbook(TEMPLATE_PATH)
        inputs = ConditionalRunInputs(
            workbook_data=workbook,
            register_path=REGISTER_V9,
            xer_path=XER_PATH,
            strawman_path=STRAWMAN_PATH,
            n_iter=500,
            seed=42,
            criticality_measurement_mode="both",
        )
        result = run_conditional_mc(inputs)
        return inputs, result

    def test_days_at_risk_runs_to_completion(self, baseline_run) -> None:
        """Subset of the 8 the engagement risks at small iter count to keep
        the integration test under a few seconds. Returns dict mapping
        risk_id -> days_at_risk_p80 (float, may be negative due to MC
        noise at the small iter count)."""
        inputs, result = baseline_run
        days_at_risk = compute_days_at_risk_per_risk(
            baseline_inputs=inputs,
            baseline_schedule_result=result.schedule_result,
            risks_to_iterate=["R013", "R017.1"],
            n_iter=200,  # tiny for test speed
            p_level=80,
        )
        assert set(days_at_risk.keys()) == {"R013", "R017.1"}
        for v in days_at_risk.values():
            assert np.isfinite(v)

    def test_leave_one_out_metrics_both_keys_finite(self, baseline_run) -> None:
        """AM04: the combined helper returns BOTH days_at_risk_p80 and
        sample_sigma_days per risk from one re-run loop, against the real
        engine, both finite."""
        inputs, result = baseline_run
        out = compute_leave_one_out_metrics(
            baseline_inputs=inputs,
            baseline_schedule_result=result.schedule_result,
            risks_to_iterate=["R013", "R017.1"],
            n_iter=200,
            p_level=80,
        )
        assert set(out.keys()) == {"R013", "R017.1"}
        for rid, m in out.items():
            assert set(m) == {"days_at_risk_p80", "sample_sigma_days"}
            assert np.isfinite(m["days_at_risk_p80"])
            assert np.isfinite(m["sample_sigma_days"])

    def test_counterfactual_sweep_empty_template(self, baseline_run) -> None:
        """Template state: no Proposed mitigations. Sweep returns
        an empty dict."""
        inputs, result = baseline_run
        sweep = compute_counterfactual_sweep(
            baseline_inputs=inputs,
            baseline_schedule_result=result.schedule_result,
            proposed_mitigations=inputs.workbook_data.mitigations,
            n_iter=200,
            p_level=80,
        )
        assert sweep == {}

    def test_counterfactual_sweep_with_synthetic_proposal(self, baseline_run) -> None:
        """Inject a synthetic Proposed mitigation tied to R067; verify
        the sweep computes days_saved for it."""
        inputs, result = baseline_run
        proposals = [{
            "mitigation_id": "TEST_M01",
            "risk_id": "R067",
            "status": "Proposed",
        }]
        sweep = compute_counterfactual_sweep(
            baseline_inputs=inputs,
            baseline_schedule_result=result.schedule_result,
            proposed_mitigations=proposals,
            n_iter=200,
            p_level=80,
        )
        assert "TEST_M01" in sweep
        assert np.isfinite(sweep["TEST_M01"])
