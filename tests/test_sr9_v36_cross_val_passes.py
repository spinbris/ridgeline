"""SR9-v3.6 — Cross-validation gate passes on canonical inputs.

Regression tests for the iteration-aware tolerance scaling introduced in
SR9-v3.6. Six tests per brief §5 plus three PM directives (canonical-margin
regression, scaled-tolerance smoke, deliberate-oversize-gap fail) plus the
WARN-path coverage and a couple of scaling-factor sanity checks.

All tests use synthetic engine result dicts with controlled means and
top-3 ordering so the suite stays fast and deterministic. The synthetic
fixtures mirror the cached PROD pickle from 2026-04-29 (cost int $11.777M
/ std $11.822M, gap $45.3k; schedule int 19.582 d / std 19.500 d, gap
0.082 d; top-3 cost ['R028', 'R051', 'R029']; top-3 schedule
['R090', 'R067', 'R026.1']).

The goal is to lock the gate at canonical iter and to exercise the v3.6
scaling code path at smoke iter without paying for live engine runs.
"""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

import logging
from pathlib import Path

import numpy as np
import pytest

from src.final.cross_validator import (
    CANONICAL_ITERATIONS,
    TOLERANCE_SCALING_CAP,
    compute_iteration_scaling_factor,
    cross_validate_reports,
)
from src.integrated.integrated_simulation import IntegratedConfig
from src.sra.methodology_defaults_reader import build_test_methodology_defaults
from tests._fixture_values import FIXTURE_DAY_RATE


# Cached PROD reference values (2026-04-29 100k canonical run; sr9_state_cache
# pickle PROD_2026-04-29.pkl). Pinned here so a future code change that drifts
# the synthetic baseline surfaces as a test failure, not a silent shift.
REF_COST_INT_MEAN = 11_776_719.557
REF_COST_STD_MEAN = 11_822_021.328
REF_SCHED_INT_MEAN_DAYS = 19.582
REF_SCHED_STD_MEAN_DAYS = 19.500
REF_COST_GAP = abs(REF_COST_INT_MEAN - REF_COST_STD_MEAN)  # ≈ $45,302
REF_SCHED_GAP = abs(REF_SCHED_INT_MEAN_DAYS - REF_SCHED_STD_MEAN_DAYS)  # ≈ 0.082 d
REF_TOP_3_COST = ["R028", "R051", "R029"]
REF_TOP_3_SCHED = ["R090", "R067", "R026.1"]
REF_OTHER_COST_IDS = [f"X{i:03d}" for i in range(30)]  # 30 padding ids
REF_OTHER_SCHED_IDS = ["X101", "X102", "X103", "X104", "X105"]  # 5 padding


def _make_synthetic_results(
    *,
    cost_int_mean: float = REF_COST_INT_MEAN,
    cost_std_mean: float = REF_COST_STD_MEAN,
    sched_int_mean: float = REF_SCHED_INT_MEAN_DAYS,
    sched_std_mean: float = REF_SCHED_STD_MEAN_DAYS,
    n_iter: int = CANONICAL_ITERATIONS,
    top_3_cost: list[str] | tuple[str, ...] = tuple(REF_TOP_3_COST),
    top_3_sched: list[str] | tuple[str, ...] = tuple(REF_TOP_3_SCHED),
    other_cost_ids: list[str] | tuple[str, ...] = tuple(REF_OTHER_COST_IDS),
    other_sched_ids: list[str] | tuple[str, ...] = tuple(REF_OTHER_SCHED_IDS),
) -> tuple[dict, dict, dict, dict, dict]:
    """Build (cost_results, schedule_results, integrated_results,
    schedule_dr, integrated_dr) with deterministic synthetic arrays.

    Cost / schedule total arrays are constants with the requested means
    (variance zero — gap is exactly cost_int_mean − cost_std_mean). Per-risk
    arrays place top_3_* at the leading columns with descending magnitudes
    so P-percentile-ranked top-3 lookups return the expected lists.
    """
    risk_ids_all = list(top_3_cost) + list(other_cost_ids)
    risk_ids_dual = list(top_3_sched) + list(other_sched_ids)

    cost_int_arr = np.full(n_iter, float(cost_int_mean))
    cost_std_arr = np.full(n_iter, float(cost_std_mean))
    sched_int_arr = np.full(n_iter, float(sched_int_mean))
    sched_std_arr = np.full(n_iter, float(sched_std_mean))

    n_cost = len(risk_ids_all)
    cost_per_risk = np.array(
        [1_000_000.0, 800_000.0, 600_000.0] + [1_000.0] * (n_cost - 3),
        dtype=np.float64,
    )
    per_risk_cost = np.tile(cost_per_risk, (n_iter, 1))

    n_sched = len(risk_ids_dual)
    sched_per_risk = np.array(
        [10.0, 8.0, 6.0] + [0.01] * (n_sched - 3),
        dtype=np.float64,
    )
    per_risk_sched = np.tile(sched_per_risk, (n_iter, 1))

    integrated_results = {
        "cost_dollars_array": cost_int_arr,
        "schedule_days_array": sched_int_arr,
        "per_risk_cost_array": per_risk_cost,
        "per_risk_schedule_array": per_risk_sched,
        "risk_ids_all": risk_ids_all,
        "risk_ids_dual": risk_ids_dual,
    }
    cost_results = {
        "cost_dollars_array": cost_std_arr,
        "per_risk_cost_array": per_risk_cost,
        "risk_ids": risk_ids_all,
    }
    schedule_results = {
        "finish_delay_days_array": sched_std_arr,
        "contribution_array": per_risk_sched,
        "risk_ids": risk_ids_dual,
    }
    # Dummy_Realistic shadow runs — same shape; used by top-3 schedule check.
    integrated_dr = {
        "cost_dollars_array": cost_int_arr,
        "schedule_days_array": sched_int_arr,
        "per_risk_cost_array": per_risk_cost,
        "per_risk_schedule_array": per_risk_sched,
        "risk_ids_all": risk_ids_all,
        "risk_ids_dual": risk_ids_dual,
    }
    schedule_dr = {
        "finish_delay_days_array": sched_std_arr,
        "contribution_array": per_risk_sched,
        "risk_ids": risk_ids_dual,
    }
    return cost_results, schedule_results, integrated_results, schedule_dr, integrated_dr


def _config(tmp_path: Path, n_iter: int = CANONICAL_ITERATIONS) -> IntegratedConfig:
    """Build an IntegratedConfig pointing at a tmp strawman path.

    The path does not need to exist — assert_strawman_unlocked only checks
    for a sibling lock file (`~$<name>.xlsx`), which is absent here.
    """
    fake = tmp_path / "fake_strawman.xlsx"
    return IntegratedConfig(
        register_path=fake,
        p6_path=fake,
        strawman_path=fake,
        iterations=n_iter,
        random_seed=42,
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
    **TEST_CALIBRATION_TOLERANCES)


# ---------------------------------------------------------------------------
# Brief §5 tests (six)
# ---------------------------------------------------------------------------

def test_cost_marginal_passes_on_canonical_inputs(tmp_path):
    """Cost-only L2 standalone vs integrated cost marginal at canonical iter
    passes within the absolute clause ($50k tolerance, factor 1.0)."""
    cost_r, sched_r, int_r, sched_dr, int_dr = _make_synthetic_results()
    cfg = _config(tmp_path, n_iter=CANONICAL_ITERATIONS)
    cv = cross_validate_reports(
        cost_results=cost_r,
        schedule_results=sched_r,
        integrated_results=int_r,
        strawman_path=cfg.strawman_path,
        config=cfg,
        integrated_results_dummy_realistic=int_dr,
        schedule_results_dummy_realistic=sched_dr,
    )
    assert cv["cost_passes_calibration"] is True
    assert cv["cost_absolute_gap_dollars"] == pytest.approx(REF_COST_GAP, abs=1.0)
    assert cv["cost_tolerance_dollars_effective"] == pytest.approx(50_000.0, rel=1e-9)


def test_schedule_marginal_passes_on_canonical_inputs(tmp_path):
    """SR5 standalone vs integrated schedule marginal at canonical iter
    passes within the 1-day tolerance (factor 1.0)."""
    cost_r, sched_r, int_r, sched_dr, int_dr = _make_synthetic_results()
    cfg = _config(tmp_path, n_iter=CANONICAL_ITERATIONS)
    cv = cross_validate_reports(
        cost_results=cost_r, schedule_results=sched_r,
        integrated_results=int_r, strawman_path=cfg.strawman_path, config=cfg,
        integrated_results_dummy_realistic=int_dr,
        schedule_results_dummy_realistic=sched_dr,
    )
    assert cv["schedule_passes_calibration"] is True
    assert cv["schedule_absolute_gap_days"] == pytest.approx(REF_SCHED_GAP, abs=1e-3)
    assert cv["schedule_tolerance_days_effective"] == pytest.approx(1.0, rel=1e-9)


def test_top_3_cost_contributors_consistent(tmp_path):
    """Top-3 cost contributors at P80 match across cost-only and integrated."""
    cost_r, sched_r, int_r, sched_dr, int_dr = _make_synthetic_results()
    cfg = _config(tmp_path)
    cv = cross_validate_reports(
        cost_results=cost_r, schedule_results=sched_r,
        integrated_results=int_r, strawman_path=cfg.strawman_path, config=cfg,
        integrated_results_dummy_realistic=int_dr,
        schedule_results_dummy_realistic=sched_dr,
    )
    assert cv["top_3_cost_contributors_consistent"] is True
    assert cv["top_3_cost_contributors_cost_only"] == REF_TOP_3_COST
    assert cv["top_3_cost_contributors_integrated"] == REF_TOP_3_COST


def test_top_3_schedule_contributors_consistent(tmp_path):
    """Top-3 schedule contributors at P80 match between SR5 and integrated
    under the Dummy_Realistic Mode override."""
    cost_r, sched_r, int_r, sched_dr, int_dr = _make_synthetic_results()
    cfg = _config(tmp_path)
    cv = cross_validate_reports(
        cost_results=cost_r, schedule_results=sched_r,
        integrated_results=int_r, strawman_path=cfg.strawman_path, config=cfg,
        integrated_results_dummy_realistic=int_dr,
        schedule_results_dummy_realistic=sched_dr,
    )
    assert cv["top_3_schedule_contributors_consistent"] is True
    assert cv["top_3_schedule_contributors_sr5"] == REF_TOP_3_SCHED
    assert cv["top_3_schedule_contributors_integrated"] == REF_TOP_3_SCHED


def test_cross_validate_reports_returns_all_pass_true(tmp_path):
    """End-to-end gate returns all_pass=True on canonical synthetic inputs."""
    cost_r, sched_r, int_r, sched_dr, int_dr = _make_synthetic_results()
    cfg = _config(tmp_path)
    cv = cross_validate_reports(
        cost_results=cost_r, schedule_results=sched_r,
        integrated_results=int_r, strawman_path=cfg.strawman_path, config=cfg,
        integrated_results_dummy_realistic=int_dr,
        schedule_results_dummy_realistic=sched_dr,
    )
    assert cv["all_pass"] is True


def test_cross_validator_gap_values_populated(tmp_path):
    """Result dict carries the diagnostic instrumentation keys for every
    check (regression protection on the v3.6 surface)."""
    cost_r, sched_r, int_r, sched_dr, int_dr = _make_synthetic_results()
    cfg = _config(tmp_path)
    cv = cross_validate_reports(
        cost_results=cost_r, schedule_results=sched_r,
        integrated_results=int_r, strawman_path=cfg.strawman_path, config=cfg,
        integrated_results_dummy_realistic=int_dr,
        schedule_results_dummy_realistic=sched_dr,
    )
    expected_keys = {
        # Calibration gap data
        "cost_absolute_gap_dollars", "cost_relative_gap_pct",
        "schedule_absolute_gap_days",
        "cost_integrated_mean", "cost_standalone_l2only_mean",
        "schedule_integrated_mean_days", "schedule_standalone_mean_days",
        # Top-3 lists for both arms
        "top_3_cost_contributors_cost_only", "top_3_cost_contributors_integrated",
        "top_3_schedule_contributors_sr5", "top_3_schedule_contributors_integrated",
        # SR9-v3.6 scaling instrumentation
        "n_iter_used_for_scaling", "tolerance_scaling_factor",
        "tolerance_scaling_canonical_iter", "tolerance_scaling_cap",
        "cost_tolerance_dollars_base", "cost_tolerance_dollars_effective",
        "schedule_tolerance_days_base", "schedule_tolerance_days_effective",
    }
    missing = expected_keys - set(cv.keys())
    assert not missing, f"cv_result missing keys: {sorted(missing)}"


# ---------------------------------------------------------------------------
# PM directive tests (three additional)
# ---------------------------------------------------------------------------

def test_canonical_iter_passes_with_margin(tmp_path):
    """At canonical 100k iter the cost gap sits at ~10% margin under
    the unscaled $50k tolerance (regression test for the production case)."""
    cost_r, sched_r, int_r, sched_dr, int_dr = _make_synthetic_results(
        n_iter=CANONICAL_ITERATIONS,
    )
    cfg = _config(tmp_path, n_iter=CANONICAL_ITERATIONS)
    cv = cross_validate_reports(
        cost_results=cost_r, schedule_results=sched_r,
        integrated_results=int_r, strawman_path=cfg.strawman_path, config=cfg,
        integrated_results_dummy_realistic=int_dr,
        schedule_results_dummy_realistic=sched_dr,
    )
    assert cv["tolerance_scaling_factor"] == pytest.approx(1.0, rel=1e-9)
    assert cv["cost_tolerance_dollars_effective"] == pytest.approx(50_000.0, rel=1e-9)
    margin = (
        cv["cost_tolerance_dollars_effective"]
        - cv["cost_absolute_gap_dollars"]
    ) / cv["cost_tolerance_dollars_effective"]
    # PM directive: ~10% margin at canonical case. Allow [5%, 20%] band so
    # small upstream shifts surface as failures rather than silent passes.
    assert 0.05 <= margin <= 0.20, (
        f"Canonical 100k margin {margin*100:.2f}% outside [5%, 20%] band — "
        f"upstream drift suspected; investigate before relaxing this assertion."
    )


def test_smoke_iter_25k_passes_under_scaled_tolerance(tmp_path):
    """At 25k iter the scaling factor is 2.0; tolerance widens to $100k
    and a synthetic gap of $85.8k (the realised diagnostic value) passes."""
    cost_r, sched_r, int_r, sched_dr, int_dr = _make_synthetic_results(
        cost_int_mean=11_803_000.0,
        cost_std_mean=11_717_200.0,  # gap $85.8k matches diagnostic at 25k iter
        n_iter=25_000,
    )
    cfg = _config(tmp_path, n_iter=25_000)
    cv = cross_validate_reports(
        cost_results=cost_r, schedule_results=sched_r,
        integrated_results=int_r, strawman_path=cfg.strawman_path, config=cfg,
        integrated_results_dummy_realistic=int_dr,
        schedule_results_dummy_realistic=sched_dr,
    )
    assert cv["n_iter_used_for_scaling"] == 25_000
    assert cv["tolerance_scaling_factor"] == pytest.approx(2.0, rel=1e-9)
    assert cv["cost_tolerance_dollars_effective"] == pytest.approx(100_000.0, rel=1e-9)
    assert cv["cost_passes_calibration"] is True
    assert cv["all_pass"] is True


def test_deliberate_oversize_gap_fails(tmp_path):
    """A gap intentionally larger than even the capped scaled tolerance
    must surface as cost_passes_calibration=False and all_pass=False."""
    # At 1k iter, scaling factor caps at 5.0 → effective tol = $250k.
    # A gap of $500k exceeds that and also exceeds the relative clause
    # ($500k / $11.8M = 4.24% >> 0.1%).
    cost_r, sched_r, int_r, sched_dr, int_dr = _make_synthetic_results(
        cost_int_mean=11_822_021.328,
        cost_std_mean=11_322_021.328,  # $500k gap
        n_iter=1_000,
    )
    cfg = _config(tmp_path, n_iter=1_000)
    cv = cross_validate_reports(
        cost_results=cost_r, schedule_results=sched_r,
        integrated_results=int_r, strawman_path=cfg.strawman_path, config=cfg,
        integrated_results_dummy_realistic=int_dr,
        schedule_results_dummy_realistic=sched_dr,
    )
    assert cv["tolerance_scaling_factor"] == pytest.approx(
        TOLERANCE_SCALING_CAP, rel=1e-9
    )
    assert cv["cost_tolerance_dollars_effective"] == pytest.approx(
        50_000.0 * TOLERANCE_SCALING_CAP, rel=1e-9
    )
    assert cv["cost_absolute_gap_dollars"] == pytest.approx(500_000.0, abs=1.0)
    assert cv["cost_passes_calibration"] is False
    assert cv["all_pass"] is False


# ---------------------------------------------------------------------------
# Additional coverage — scaling helper sanity + WARN path
# ---------------------------------------------------------------------------

def test_scaling_factor_unity_at_canonical_iter():
    """Sanity: scaling factor = 1.0 at canonical iter; production unchanged."""
    assert compute_iteration_scaling_factor(CANONICAL_ITERATIONS) == pytest.approx(1.0)


def test_scaling_factor_capped_at_low_iter():
    """Sanity: scaling factor caps at TOLERANCE_SCALING_CAP for low iter."""
    # At iter=1, sqrt(100000/1) = 316.2; the cap kicks in.
    assert compute_iteration_scaling_factor(1) == pytest.approx(TOLERANCE_SCALING_CAP)
    # Above the cap-binding threshold (100_000 / cap^2 = 4_000), the cap
    # does not bind and the raw sqrt formula applies. n_iter=10,000 sits
    # comfortably above 4,000 so factor = sqrt(100_000 / 10_000) ≈ 3.162.
    assert compute_iteration_scaling_factor(10_000) == pytest.approx(
        (CANONICAL_ITERATIONS / 10_000) ** 0.5
    )


def test_relative_clause_warn_when_only_clause_passing(tmp_path, caplog):
    """If absolute clause fails but relative <= 0.1% saves the gate, emit WARN.

    Construct a deliberate gap that falls outside the scaled absolute tolerance
    but inside the relative clause: cost_int = $1B, cost_std = $1B + $300k →
    absolute gap $300k (over $50k); relative gap 0.03% (under 0.10%).
    """
    cost_r, sched_r, int_r, sched_dr, int_dr = _make_synthetic_results(
        cost_int_mean=1_000_000_000.0,
        cost_std_mean=1_000_300_000.0,
        n_iter=CANONICAL_ITERATIONS,
    )
    cfg = _config(tmp_path, n_iter=CANONICAL_ITERATIONS)
    with caplog.at_level(logging.WARNING, logger="src.final.cross_validator"):
        cv = cross_validate_reports(
            cost_results=cost_r, schedule_results=sched_r,
            integrated_results=int_r, strawman_path=cfg.strawman_path, config=cfg,
            integrated_results_dummy_realistic=int_dr,
            schedule_results_dummy_realistic=sched_dr,
        )
    assert cv["cost_passes_calibration"] is True  # passes via relative clause
    assert cv["cost_absolute_gap_dollars"] == pytest.approx(300_000.0, abs=1.0)
    assert cv["cost_relative_gap_pct"] < 0.001  # under 0.1%
    warn_messages = [
        rec.message for rec in caplog.records if rec.levelno == logging.WARNING
    ]
    assert any("relative-clause only" in msg for msg in warn_messages), (
        f"Expected WARN about relative-clause-only pass; got: {warn_messages}"
    )
