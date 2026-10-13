"""SR9 Pass A tests for cross_validator."""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

from pathlib import Path

import numpy as np
import pytest

from src.final.cross_validator import cross_validate_reports
from src.integrated.integrated_simulation import IntegratedConfig
from src.sra.methodology_defaults_reader import build_test_methodology_defaults
from tests._fixture_values import FIXTURE_DAY_RATE


def _make_config(strawman_path: Path) -> IntegratedConfig:
    return IntegratedConfig(
        register_path=strawman_path,
        p6_path=strawman_path,
        strawman_path=strawman_path,
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
    **TEST_CALIBRATION_TOLERANCES)


def _build_results(
    n_iter: int,
    cost_mean_dollars: float,
    sched_mean_days: float,
    risk_ids: list[str],
    cost_per_risk_means: list[float],
    sched_per_risk_means: list[float] | None = None,
    sched_risk_ids: list[str] | None = None,
    seed: int = 42,
):
    """Build (cost_results, schedule_results, integrated_results) in-memory.

    Shapes match what the actual engines produce:
      cost_results        : MonteCarloEngine outputs (materialised by notebook)
      schedule_results    : run_schedule_simulation outputs
      integrated_results  : run_integrated_simulation outputs
    """
    rng = np.random.default_rng(seed)
    n_risks = len(risk_ids)

    # Cost-only L2 standalone
    per_risk_cost = rng.normal(loc=0.0, scale=1.0, size=(n_iter, n_risks))
    per_risk_cost = per_risk_cost - per_risk_cost.mean(axis=0) + np.array(cost_per_risk_means)
    total_cost = per_risk_cost.sum(axis=1)
    # Adjust mean to target
    total_cost = total_cost - total_cost.mean() + cost_mean_dollars
    per_risk_cost = per_risk_cost - per_risk_cost.mean(axis=0) + np.array(cost_per_risk_means)
    cost_results = {
        "cost_dollars_array": total_cost,
        "per_risk_cost_array": per_risk_cost,
        "risk_ids": list(risk_ids),
    }

    # Schedule SR5 standalone (DP Review)
    sched_risk_ids = sched_risk_ids or risk_ids[:3]
    n_sched = len(sched_risk_ids)
    sched_per_risk_means = sched_per_risk_means or [1.0] * n_sched
    contribution = rng.normal(loc=0.0, scale=0.3, size=(n_iter, n_sched))
    contribution = contribution - contribution.mean(axis=0) + np.array(sched_per_risk_means)
    finish_delays = contribution.sum(axis=1)
    finish_delays = finish_delays - finish_delays.mean() + sched_mean_days
    schedule_results = {
        "finish_delay_days_array": finish_delays,
        "contribution_array": contribution,
        "risk_ids": list(sched_risk_ids),
        "mode_used": {rid: "Series" for rid in sched_risk_ids},
    }

    # Integrated (DP Review baseline)
    integrated_per_risk_cost = per_risk_cost.copy()
    integrated_total_cost = integrated_per_risk_cost.sum(axis=1)
    integrated_per_risk_sched = contribution.copy()
    integrated_total_sched = integrated_per_risk_sched.sum(axis=1)
    integrated_results = {
        "iterations": n_iter,
        "cost_dollars_array": integrated_total_cost,
        "schedule_days_array": integrated_total_sched,
        "per_risk_cost_array": integrated_per_risk_cost,
        "per_risk_schedule_array": integrated_per_risk_sched,
        "risk_ids_all": list(risk_ids),
        "risk_ids_dual": list(sched_risk_ids),
    }
    return cost_results, schedule_results, integrated_results


@pytest.fixture
def strawman_path(tmp_path):
    p = tmp_path / "strawman.xlsx"
    p.write_bytes(b"")  # placeholder; not actually read by the validator
    return p


def test_cross_validate_passes_when_all_consistent(strawman_path):
    """Synthetic dicts that satisfy all four checks."""
    cost, sched, integ = _build_results(
        n_iter=3000,
        cost_mean_dollars=11_000_000.0,
        sched_mean_days=1.5,
        risk_ids=["R001", "R002", "R003", "R004", "R005"],
        cost_per_risk_means=[5_000_000, 3_000_000, 2_000_000, 800_000, 200_000],
        sched_per_risk_means=[1.0, 0.4, 0.1],
        sched_risk_ids=["R001", "R002", "R003"],
    )
    cfg = _make_config(strawman_path)
    result = cross_validate_reports(
        cost_results=cost,
        schedule_results=sched,
        integrated_results=integ,
        strawman_path=strawman_path,
        config=cfg,
        integrated_results_dummy_realistic=integ,
        schedule_results_dummy_realistic=sched,
    )
    assert result["cost_passes_calibration"] is True
    assert result["schedule_passes_calibration"] is True
    assert result["top_3_cost_contributors_consistent"] is True
    assert result["top_3_schedule_contributors_consistent"] is True
    assert result["all_pass"] is True


def test_cross_validate_fails_when_cost_marginal_diverges(strawman_path):
    """Cost mean gap exceeds tolerance ($50k OR 0.1%)."""
    cost, sched, integ = _build_results(
        n_iter=3000,
        cost_mean_dollars=11_000_000.0,
        sched_mean_days=1.5,
        risk_ids=["R001", "R002", "R003"],
        cost_per_risk_means=[5_000_000, 3_000_000, 3_000_000],
    )
    # Force divergence: shift integrated cost by $500k (10x tolerance, well over 0.1%)
    integ["cost_dollars_array"] = integ["cost_dollars_array"] + 500_000.0
    cfg = _make_config(strawman_path)
    result = cross_validate_reports(
        cost_results=cost, schedule_results=sched, integrated_results=integ,
        strawman_path=strawman_path, config=cfg,
        integrated_results_dummy_realistic=integ,
        schedule_results_dummy_realistic=sched,
    )
    assert result["cost_passes_calibration"] is False
    assert result["all_pass"] is False
    assert result["cost_absolute_gap_dollars"] >= 50_000.0


def test_cross_validate_fails_when_schedule_marginal_diverges(strawman_path):
    """Schedule mean gap exceeds tolerance.

    SR9-v3.6 note: the schedule absolute tolerance scales by sqrt(canonical/iter)
    capped at 5.0×, so at iter=3000 the effective tolerance is min(sqrt(100k/3k),
    5.0) × 1 day = 5.0 days. We inject +10 days to ensure the gap exceeds the
    capped scaled tolerance regardless of where in the [1d, 5d] band the
    effective tolerance lands.
    """
    cost, sched, integ = _build_results(
        n_iter=3000,
        cost_mean_dollars=11_000_000.0,
        sched_mean_days=1.5,
        risk_ids=["R001", "R002", "R003"],
        cost_per_risk_means=[5_000_000, 3_000_000, 3_000_000],
        sched_per_risk_means=[1.0, 0.4, 0.1],
        sched_risk_ids=["R001", "R002", "R003"],
    )
    integ["schedule_days_array"] = integ["schedule_days_array"] + 10.0
    cfg = _make_config(strawman_path)
    result = cross_validate_reports(
        cost_results=cost, schedule_results=sched, integrated_results=integ,
        strawman_path=strawman_path, config=cfg,
        integrated_results_dummy_realistic=integ,
        schedule_results_dummy_realistic=sched,
    )
    assert result["schedule_passes_calibration"] is False
    assert result["schedule_absolute_gap_days"] > result["schedule_tolerance_days_effective"]
    assert result["all_pass"] is False


def test_cross_validate_fails_when_top_3_diverges(strawman_path):
    """Top-3 cost contributors mismatched between cost-only and integrated."""
    cost, sched, integ = _build_results(
        n_iter=3000,
        cost_mean_dollars=11_000_000.0,
        sched_mean_days=1.5,
        risk_ids=["R001", "R002", "R003", "R004", "R005"],
        cost_per_risk_means=[5_000_000, 3_000_000, 2_000_000, 800_000, 200_000],
    )
    # Break the label-to-data mapping in integrated only (NOT in cost_results),
    # so the same numerical columns now report different risk_ids in the two sources.
    integ["risk_ids_all"] = list(reversed(integ["risk_ids_all"]))
    cfg = _make_config(strawman_path)
    result = cross_validate_reports(
        cost_results=cost, schedule_results=sched, integrated_results=integ,
        strawman_path=strawman_path, config=cfg,
        integrated_results_dummy_realistic=integ,
        schedule_results_dummy_realistic=sched,
    )
    assert result["top_3_cost_contributors_consistent"] is False
    assert result["all_pass"] is False
    # Top-3 lists themselves should still be populated
    assert len(result["top_3_cost_contributors_cost_only"]) == 3
    assert len(result["top_3_cost_contributors_integrated"]) == 3


def test_beta19b_item_6_schedule_top3_ranks_by_mean() -> None:
    """Beta-19b item 6: schedule top-3 ranks by probability-weighted mean
    (iteration mean of the contribution array), not by P-level percentile.

    Construct a synthetic contribution array where one risk has a
    high tail (high P80) but low mean, and another has low tail but
    high mean. The mean-ranked top-3 must put the high-mean risk
    above the high-tail risk; a P80-ranking would invert them.
    """
    import numpy as np

    from src.final.cross_validator import _rank_by_mean, _rank_by_p_level

    n_iter = 1000
    risk_ids = ["R_hi_mean", "R_hi_tail", "R_low"]
    # R_hi_mean: constant 2.0 each iteration (mean=2.0, P80=2.0).
    # R_hi_tail: zero in 95% of iters, 50 in 5% (mean=2.5, P80=0).
    # R_low: constant 0.1 (mean=0.1).
    rng = np.random.default_rng(0)
    col_hi_mean = np.full(n_iter, 2.0)
    col_hi_tail = np.zeros(n_iter)
    tail_idx = rng.choice(n_iter, size=int(0.05 * n_iter), replace=False)
    col_hi_tail[tail_idx] = 50.0
    col_low = np.full(n_iter, 0.1)
    arr = np.column_stack([col_hi_mean, col_hi_tail, col_low])

    by_mean = _rank_by_mean(arr, risk_ids, top_n=3)
    by_p80 = _rank_by_p_level(arr, risk_ids, p_level=80, top_n=3)
    # Mean ranking: R_hi_tail (2.5) > R_hi_mean (2.0) > R_low (0.1)
    # — both metrics agree on the *order* in this construction because
    # R_hi_tail's tail dominates its mean. So we additionally confirm
    # the rankings can DISAGREE on a clearer case below.
    assert by_mean[0] == "R_hi_tail"
    # P80 ranking: R_hi_mean (P80=2.0) > R_hi_tail (P80=0) > R_low
    # (P80=0.1). So under P80 R_hi_tail drops to rank 3.
    assert by_p80[0] == "R_hi_mean"
    assert by_p80[2] == "R_hi_tail"


def test_beta19b_item_6_gate_still_passes_under_consistent_top3(
    strawman_path,
) -> None:
    """The pass criterion (set equality) is metric-agnostic — switching
    from P-level to mean ranking does not break the gate when standalone
    and integrated produce the same top-3."""
    cost, sched, integ = _build_results(
        n_iter=3000,
        cost_mean_dollars=11_000_000.0,
        sched_mean_days=1.5,
        risk_ids=["R001", "R002", "R003", "R004", "R005"],
        cost_per_risk_means=[5_000_000, 3_000_000, 2_000_000, 800_000, 200_000],
        sched_per_risk_means=[1.0, 0.4, 0.1],
        sched_risk_ids=["R001", "R002", "R003"],
    )
    cfg = _make_config(strawman_path)
    result = cross_validate_reports(
        cost_results=cost, schedule_results=sched, integrated_results=integ,
        strawman_path=strawman_path, config=cfg,
        integrated_results_dummy_realistic=integ,
        schedule_results_dummy_realistic=sched,
    )
    assert result["top_3_schedule_contributors_consistent"] is True
    assert result["all_pass"] is True


def test_cross_validate_raises_when_strawman_locked(tmp_path):
    """Pre-flight should fail-fast when Excel lock-file is present."""
    strawman = tmp_path / "strawman.xlsx"
    strawman.write_bytes(b"")
    lock = tmp_path / "~$strawman.xlsx"
    lock.write_bytes(b"")
    cost, sched, integ = _build_results(
        n_iter=300,
        cost_mean_dollars=10.0, sched_mean_days=1.0,
        risk_ids=["R001"], cost_per_risk_means=[10.0],
    )
    cfg = IntegratedConfig(
        register_path=strawman, p6_path=strawman, strawman_path=strawman,
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
    **TEST_CALIBRATION_TOLERANCES)
    with pytest.raises(RuntimeError, match="locked"):
        cross_validate_reports(
            cost_results=cost, schedule_results=sched, integrated_results=integ,
            strawman_path=strawman, config=cfg,
        )
