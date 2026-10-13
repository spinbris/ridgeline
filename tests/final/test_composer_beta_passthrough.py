"""SR-S3-Beta-08 tests for the composer's stage3_beta_result passthrough.

Covers:
  - backward-compat (Stage 2.5 production): when stage3_beta_result is
    None, the composer's output dict is bit-identical (key set + values
    for the canonical Stage 2.5 keys) to a snapshot taken with the
    kwarg absent. This is the brief's BLOCKER-class regression test
  - key population when stage3_beta_result is supplied: all six new
    keys present with correct types
  - path-crossover delta sign convention
  - WARN threshold edge case (delta == 30 → False; > 30 → True)
  - audit table row count == len(risk_drivers)
"""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.final.composer import (
    PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS,
    _compute_path_crossover_delta,
    _render_auto_mapper_audit_table,
    compose_final_report_data,
)
from src.integrated.integrated_simulation import IntegratedConfig
from src.sra.methodology_defaults_reader import build_test_methodology_defaults
from tests._fixture_values import FIXTURE_DAY_RATE


def _config_for_tmp(tmp_path) -> IntegratedConfig:
    """SR19 §6.2: compose_final_report_data only reads register_path itself
    (via read_methodology_defaults) when config is None. Passing an
    explicit config with a test-factory methodology_defaults avoids that
    fallback needing a real register file at the tmp fixture path."""
    return IntegratedConfig(
        register_path=tmp_path / "register.xlsx",
        p6_path=tmp_path / "register.xlsx",
        strawman_path=tmp_path / "strawman.xlsx",
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
    **TEST_CALIBRATION_TOLERANCES)


# ----------------------------------------------------------------------------
# Composer fixture (mirrors tests/test_sr9_composer.py shape)
# ----------------------------------------------------------------------------

def _build_inputs(seed=21):
    rng = np.random.default_rng(seed)
    n_iter = 1500
    risk_ids = ["R001", "R002", "R003", "R004", "R005"]
    sched_ids = ["R001", "R002", "R003"]

    def _per_risk_cost(means):
        a = rng.normal(0.0, 1.0, size=(n_iter, len(means)))
        return a - a.mean(axis=0) + np.array(means)

    def _per_risk_sched(means):
        a = rng.normal(0.0, 0.3, size=(n_iter, len(means)))
        return a - a.mean(axis=0) + np.array(means)

    cost_per = _per_risk_cost([5e6, 4e6, 3e6, 2e6, 1e6])
    cost_results = {
        "cost_dollars_array": cost_per.sum(axis=1),
        "per_risk_cost_array": cost_per,
        "risk_ids": list(risk_ids),
    }
    sched_dp_per = _per_risk_sched([0.4, 0.05, 0.05])
    schedule_results = {
        "finish_delay_days_array": sched_dp_per.sum(axis=1),
        "contribution_array": sched_dp_per,
        "risk_ids": list(sched_ids),
        "mode_used": {"R001": "Series", "R002": "Parallel", "R003": "Parallel"},
    }

    def _build_integrated(cost_means, sched_means, mode_used):
        c = _per_risk_cost(cost_means)
        s = _per_risk_sched(sched_means)
        return {
            "iterations": n_iter,
            "cost_dollars_array": c.sum(axis=1),
            "schedule_days_array": s.sum(axis=1),
            "per_risk_cost_array": c,
            "per_risk_schedule_array": s,
            "risk_ids_all": list(risk_ids),
            "risk_ids_dual": list(sched_ids),
            "_mode_used": mode_used,
        }

    integrated_by = {
        "DP_Review": _build_integrated(
            [5e6, 4e6, 3e6, 2e6, 1e6], [0.4, 0.05, 0.05],
            {"R001": "Series", "R002": "Parallel", "R003": "Parallel"},
        ),
        "Dummy_Realistic": _build_integrated(
            [5e6, 4e6, 3e6, 2e6, 1e6], [3.0, 1.5, 0.5],
            {"R001": "Series", "R002": "Hybrid", "R003": "Hybrid"},
        ),
        "All_Series": _build_integrated(
            [5e6, 4e6, 3e6, 2e6, 1e6], [10.0, 6.0, 3.0],
            {"R001": "Series", "R002": "Series", "R003": "Series"},
        ),
    }
    sched_by = {
        "DP_Review": schedule_results,
        "Dummy_Realistic": {
            "finish_delay_days_array": rng.normal(5.0, 0.5, n_iter),
            "contribution_array": _per_risk_sched([3.0, 1.5, 0.5]),
            "risk_ids": list(sched_ids),
            "mode_used": {"R001": "Series", "R002": "Hybrid", "R003": "Hybrid"},
        },
        "All_Series": {
            "finish_delay_days_array": rng.normal(19.0, 1.0, n_iter),
            "contribution_array": _per_risk_sched([10.0, 6.0, 3.0]),
            "risk_ids": list(sched_ids),
            "mode_used": {rid: "Series" for rid in sched_ids},
        },
    }
    cv = {
        "cost_passes_calibration": True,
        "schedule_passes_calibration": True,
        "top_3_cost_contributors_consistent": True,
        "top_3_schedule_contributors_consistent": True,
        "all_pass": True,
        "interpretation": "All checks pass.",
    }
    risk_titles = {rid: f"Risk title {rid}" for rid in risk_ids}
    return cost_results, schedule_results, integrated_by, sched_by, cv, risk_titles


def _build_synthetic_stage3_beta_result(
    *,
    n_iter: int = 1500,
    project_finish_p80: float = 1200.0,
    n_risks: int = 8,
) -> dict:
    """Build a synthetic stage3_beta_result with the documented shape."""
    rng = np.random.default_rng(7)
    # PERT-ish array centred so its P80 is approximately project_finish_p80.
    arr = rng.normal(project_finish_p80 - 50.0, 25.0, n_iter).astype("float32")
    # Calibrate so np.percentile(arr, 80) is close to project_finish_p80
    arr = arr + (project_finish_p80 - float(np.percentile(arr, 80)))
    sched_result = SimpleNamespace(
        project_finish_days=arr,
        n_iter=n_iter,
        beta_flag=True,
        auto_mapper_audit_path=Path("/tmp/audit.parquet"),
    )

    risk_drivers = {}
    for i in range(n_risks):
        rid = f"R{100 + i:03d}"
        risk_drivers[rid] = SimpleNamespace(
            risk_id=rid,
            affected_activity_ids=tuple(f"A{i}_{j}" for j in range(5)),
            injection_method="additive_pert_days",
            opt_pert=0.0,
            ml_pert=10.0,
            pess_pert=30.0,
            probability=0.5,
            pattern_id=f"P{i+1:02d}",
            derived_at_run_time=True,
            workshop_validated=False,
        )

    # STAGE3HEADLINE-01: the Beta-06 dict also carries the integrated-results shape
    # (deliverable._stage3_beta_dict), which the composer reads for the Stage 3 headline
    # and for the schedule contributors; schedule_days_array is a DELAY, not a finish.
    baseline_days = 1000.0
    delay = np.maximum(arr.astype("float64") - baseline_days, 0.0)
    per_risk_sched = rng.gamma(2.0, 3.0, size=(n_iter, n_risks))
    per_risk_cost = rng.gamma(2.0, 20_000.0, size=(n_iter, n_risks))
    risk_ids = list(risk_drivers)
    return {
        "schedule_result": sched_result,
        # PRESENT-01 (D-5): the over-bind denominator is the run's own activity count;
        # this synthetic result has no graph, so it states the count.
        "activity_count": 120,
        "risk_drivers": risk_drivers,
        "auto_mapper_audit_path": Path("/tmp/audit.parquet"),
        "beta_flag": True,
        "schedule_days_array": delay,
        "cost_dollars_array": per_risk_cost.sum(axis=1),
        "per_risk_cost_array": per_risk_cost,
        "per_risk_schedule_array": per_risk_sched,
        "risk_ids_all": risk_ids,
        "risk_ids_dual": risk_ids,
        "iterations": n_iter,
    }


# ----------------------------------------------------------------------------
# Backward-compat: bit-identical when stage3_beta_result=None
# ----------------------------------------------------------------------------

def test_composer_no_beta_kwarg_produces_pre_beta_output_bit_identical(tmp_path):
    """Stage 2.5 production output is unchanged when stage3_beta_result=None.

    Per Beta-00 §5: Stage 2.5 unchanged. The brief's BLOCKER class
    regression test - if the composer's existing output drifts under
    the kwarg addition, prod is broken. We compare two compositions:
    (a) without stage3_beta_result, (b) with stage3_beta_result=None
    explicit. Both must produce identical key sets and matching
    canonical-Stage-2.5 values, and neither must contain Stage 3
    beta keys.
    """
    cost, sched, integ_by, sched_by, cv, titles = _build_inputs()
    common_kwargs = dict(
        cost_results=cost,
        schedule_results=sched,
        integrated_results_by_scenario=integ_by,
        schedule_results_by_scenario=sched_by,
        strawman_path=tmp_path / "strawman.xlsx",
        register_path=tmp_path / "register.xlsx",
        cross_validation=cv,
        risk_titles=titles,
        appendix_counterfactual=pd.DataFrame({"scenario": [1, 2], "p80": [10, 20]}),
        config=_config_for_tmp(tmp_path),
    )
    a = compose_final_report_data(**common_kwargs)
    b = compose_final_report_data(**common_kwargs, stage3_beta_result=None)

    # Same keys, no Stage 3 beta keys leaked in.
    stage3_keys = {
        "beta_flag",
        "stage3_beta_p80_schedule_days",
        "stage25_p80_schedule_days",
        "path_crossover_delta_days",
        "path_crossover_warn",
        "path_crossover_warn_threshold_days",
        "auto_mapper_audit_path",
        "stage3_beta_audit_table",
    }
    assert set(a.keys()) == set(b.keys())
    assert stage3_keys.isdisjoint(set(a.keys())), (
        f"Stage 3 keys leaked into Stage 2.5 path: {stage3_keys & set(a.keys())}"
    )

    # Sanity: a few canonical Stage 2.5 fields are byte-identical between
    # the two calls (deterministic given identical inputs).
    assert a["cross_validation"] == b["cross_validation"]
    assert a["executive_summary"]["key_findings"] == b["executive_summary"]["key_findings"]
    assert a["executive_summary"]["recommendations"] == b["executive_summary"]["recommendations"]


# ----------------------------------------------------------------------------
# Key population when stage3_beta_result supplied
# ----------------------------------------------------------------------------

def test_composer_with_beta_kwarg_populates_keys(tmp_path):
    cost, sched, integ_by, sched_by, cv, titles = _build_inputs()
    stage3 = _build_synthetic_stage3_beta_result()
    composed = compose_final_report_data(
        cost_results=cost,
        schedule_results=sched,
        integrated_results_by_scenario=integ_by,
        schedule_results_by_scenario=sched_by,
        strawman_path=tmp_path / "strawman.xlsx",
        register_path=tmp_path / "register.xlsx",
        cross_validation=cv,
        risk_titles=titles,
        stage3_beta_result=stage3,
        config=_config_for_tmp(tmp_path),
    )

    assert composed["beta_flag"] is True
    assert isinstance(composed["stage3_beta_p80_schedule_days"], float)
    assert isinstance(composed["stage25_p80_schedule_days"], float)
    assert isinstance(composed["path_crossover_delta_days"], float)
    assert isinstance(composed["path_crossover_warn"], bool)
    assert isinstance(composed["path_crossover_warn_threshold_days"], float)
    assert composed["auto_mapper_audit_path"] == Path("/tmp/audit.parquet")
    assert isinstance(composed["stage3_beta_audit_table"], list)
    assert len(composed["stage3_beta_audit_table"]) == 8


# ----------------------------------------------------------------------------
# Path-crossover delta sign convention
# ----------------------------------------------------------------------------

def test_path_crossover_delta_sign_convention():
    """Positive delta = Stage 3 lower P80 (less risk surfacing).

    Synthetic: Stage 2.5 P80 = 1000 days, Stage 3 P80 = 950 days.
    Expected delta = +50 days; warn = True (>30 threshold).
    """
    n_iter = 5000
    rng = np.random.default_rng(0)
    s25 = rng.normal(900.0, 50.0, n_iter)
    s25 = s25 + (1000.0 - float(np.percentile(s25, 80)))
    s3 = rng.normal(850.0, 50.0, n_iter)
    s3 = s3 + (950.0 - float(np.percentile(s3, 80)))
    # STAGE3HEADLINE-01 D-5 (F-40): both sides are DELAYS. Until 10/09/2026 the Stage 3
    # side was schedule_result.project_finish_days, an absolute finish, so the delta
    # subtracted a delay from a finish and the WARN was never about path crossover.
    s3_result = {"schedule_days_array": s3}
    integrated_results = {"schedule_days_array": s25}
    s25_p80, s3_p80, delta, warn = _compute_path_crossover_delta(
        integrated_results, s3_result,
    )
    assert s25_p80 == pytest.approx(1000.0, abs=1e-6)
    assert s3_p80 == pytest.approx(950.0, abs=1e-6)
    assert delta == pytest.approx(50.0, abs=1e-6)
    assert warn is True


# ----------------------------------------------------------------------------
# WARN threshold edge case
# ----------------------------------------------------------------------------

def test_path_crossover_warn_threshold_at_exactly_30():
    """delta = 30 -> warn = False; delta = 30.1 -> warn = True."""

    def _result(p80_value: float) -> dict:
        # Build a degenerate distribution whose P80 is exactly p80_value.
        return {"schedule_days_array": np.array([p80_value] * 100)}

    # delta = 30
    integrated = {"schedule_days_array": np.array([1030.0] * 100)}
    _, _, delta_30, warn_30 = _compute_path_crossover_delta(
        integrated, _result(1000.0),
    )
    assert delta_30 == pytest.approx(30.0)
    assert warn_30 is False, "delta == 30 should NOT warn (strictly > threshold)"

    # delta = 30.1
    integrated_high = {"schedule_days_array": np.array([1030.1] * 100)}
    _, _, delta_31, warn_31 = _compute_path_crossover_delta(
        integrated_high, _result(1000.0),
    )
    assert delta_31 == pytest.approx(30.1)
    assert warn_31 is True


def test_path_crossover_warn_threshold_default_is_30():
    """Default threshold is 30 working days (Beta-00 §9)."""
    assert PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS == 30.0


# ----------------------------------------------------------------------------
# Audit table rendering
# ----------------------------------------------------------------------------

def test_audit_table_rendered_with_one_row_per_risk():
    """8 risk_drivers in -> 8 rows out, with the documented column set."""
    risk_drivers = {}
    for i in range(8):
        rid = f"R{i:03d}"
        risk_drivers[rid] = SimpleNamespace(
            risk_id=rid,
            affected_activity_ids=tuple(f"A{j}" for j in range(3 + i)),
            injection_method="additive_pert_days",
            opt_pert=0.0,
            ml_pert=float(i + 1),
            pess_pert=float((i + 1) * 5),
            probability=0.1 * (i + 1),
            pattern_id=f"P{i+1:02d}",
            derived_at_run_time=True,
            workshop_validated=False,
        )
    rows = _render_auto_mapper_audit_table(risk_drivers)
    assert len(rows) == 8
    for row, (i, rid) in zip(rows, enumerate(risk_drivers.keys())):
        assert row["risk_id"] == rid
        assert row["activity_count"] == 3 + i
        assert row["pattern_id"] == f"P{i+1:02d}"
        assert row["derived_at_run_time"] is True
        assert row["workshop_validated"] is False
    expected_columns = {
        "risk_id",
        "activity_count",
        "pattern_id",
        "injection_method",
        # SR12 — per-risk gating activity surfaced in the §10.5 audit
        # table; "" for legacy / multiplicative methods.
        "gating_activity_id",
        "probability",
        "opt_d",
        "ml_d",
        "pess_d",
        "derived_at_run_time",
        "workshop_validated",
    }
    assert set(rows[0].keys()) == expected_columns


def test_audit_table_empty_when_no_drivers():
    """Empty dict -> empty list (no exceptions)."""
    assert _render_auto_mapper_audit_table({}) == []
    assert _render_auto_mapper_audit_table(None) == []
