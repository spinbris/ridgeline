"""SR9 Pass A tests for executive_summary helpers."""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

import numpy as np

from src.final.executive_summary import (
    DP_REVIEW_SCENARIO_DISPLAY,
    INDICATIVE_SCENARIO_DISPLAY,
    get_diversification_summary,
    get_headline_contingency_range,
    get_top_n_risk_drivers,
)
from src.integrated.integrated_simulation import IntegratedConfig
from src.sra.methodology_defaults_reader import build_test_methodology_defaults
from tests._fixture_values import FIXTURE_DAY_RATE


def _make_integrated(n_iter=2000, n_risks=5, n_dual=3,
                     cost_means=None, sched_means=None, seed=7):
    rng = np.random.default_rng(seed)
    cost_means = cost_means or [5.0, 4.0, 3.0, 2.0, 1.0]
    sched_means = sched_means or [10.0, 5.0, 2.0]
    cost_per = rng.normal(0.0, 1.0, size=(n_iter, n_risks))
    cost_per = cost_per - cost_per.mean(axis=0) + np.array(cost_means)
    sched_per = rng.normal(0.0, 0.5, size=(n_iter, n_dual))
    sched_per = sched_per - sched_per.mean(axis=0) + np.array(sched_means)
    return {
        "iterations": n_iter,
        "cost_dollars_array": cost_per.sum(axis=1),
        "schedule_days_array": sched_per.sum(axis=1),
        "per_risk_cost_array": cost_per,
        "per_risk_schedule_array": sched_per,
        "risk_ids_all": [f"R00{i+1}" for i in range(n_risks)],
        "risk_ids_dual": [f"R00{i+1}" for i in range(n_dual)],
    }


def test_get_top_n_risk_drivers_cost_returns_three():
    integ = _make_integrated()
    drivers = get_top_n_risk_drivers(integ, n=3, metric="cost", p_level=80)
    assert len(drivers) == 3
    assert drivers[0]["risk_id"] == "R001"  # highest mean -> highest P80
    assert drivers[0]["units"] == "dollars"
    assert drivers[0]["metric_value"] >= drivers[1]["metric_value"]
    assert drivers[1]["metric_value"] >= drivers[2]["metric_value"]


def test_get_top_n_risk_drivers_schedule_returns_three():
    integ = _make_integrated()
    drivers = get_top_n_risk_drivers(
        integ, n=3, metric="schedule", p_level=80, day_rate=100000.0,
    )
    assert len(drivers) == 3
    assert drivers[0]["units"] == "days"
    assert "p_level_dollars" in drivers[0]
    assert drivers[0]["risk_id"] == "R001"


def test_get_headline_contingency_range_labels_bounds_by_scenario():
    """Construct three scenarios with known P80s in non-default order;
    assert lower/upper labels follow data, not position."""
    # Construct so DP_Review has highest P80 and All_Series has lowest
    # (opposite of typical assumption) - validates that labels follow data.
    rng = np.random.default_rng(11)

    def _make(cost_mean, sched_mean):
        n = 1500
        cost_arr = rng.normal(cost_mean, cost_mean * 0.05, n)
        sched_arr = rng.normal(sched_mean, sched_mean * 0.05 + 0.1, n)
        return {
            "cost_dollars_array": cost_arr,
            "schedule_days_array": sched_arr,
        }

    scenarios = {
        # Lowest -> highest by scenario name to prove labels follow data:
        "All_Series": _make(10_000_000, 1.0),       # lowest P80
        "DP_Review": _make(11_000_000, 2.0),        # middle - this is the indicative
        "Dummy_Realistic": _make(15_000_000, 3.0),  # highest P80
    }
    result = get_headline_contingency_range(
        integrated_results_by_scenario=scenarios,
        p_level=80,
        day_rate=100000.0,
    )
    # Bound labels follow the data, not the scenario name's typical role
    assert "All Series" in result["lower_bound_scenario"]
    assert result["upper_bound_scenario"] == INDICATIVE_SCENARIO_DISPLAY
    # The indicative slot is the DP Review baseline (SR9 v3.3 Path A); PRESENT-01 (D-4) left
    # that the only answer, so this fixture puts the middle P80 under that key.
    assert result["indicative_scenario"] == DP_REVIEW_SCENARIO_DISPLAY
    # Sanity: lower < indicative < upper
    assert result["lower_bound_dollars"] < result["upper_bound_dollars"]
    assert (
        result["lower_bound_dollars"]
        <= result["indicative_dollars"]
        <= result["upper_bound_dollars"]
    )
    # All three labels appear in the all_three_scenarios dict
    assert len(result["all_three_scenarios"]) == 3


def test_get_diversification_summary_returns_dollars_and_pct(tmp_path):
    rng = np.random.default_rng(13)

    def _make(cost_mean, sched_mean):
        n = 2000
        cost_arr = rng.normal(cost_mean, cost_mean * 0.05, n)
        sched_arr = rng.normal(sched_mean, max(sched_mean * 0.05, 0.1), n)
        return {
            "cost_dollars_array": cost_arr,
            "schedule_days_array": sched_arr,
        }

    integrated_by_scenario = {
        "DP_Review": _make(11_000_000, 0.5),
        "All_Series": _make(12_000_000, 30.0),
        "Dummy_Realistic": _make(11_500_000, 15.0),
    }
    sched_by_scenario = {
        "DP_Review": {"finish_delay_days_array": rng.normal(0.5, 0.1, 2000)},
        "All_Series": {"finish_delay_days_array": rng.normal(30.0, 1.5, 2000)},
        "Dummy_Realistic": {"finish_delay_days_array": rng.normal(15.0, 1.0, 2000)},
    }
    cost_only = {"cost_dollars_array": rng.normal(11_000_000, 500_000, 2000)}
    cfg = IntegratedConfig(
        register_path=tmp_path / "x", p6_path=tmp_path / "x",
        strawman_path=tmp_path / "x",
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
    **TEST_CALIBRATION_TOLERANCES)

    result = get_diversification_summary(
        integrated_results_by_scenario=integrated_by_scenario,
        schedule_results_by_scenario=sched_by_scenario,
        cost_only_l2_results=cost_only,
        config=cfg,
    )
    assert "all_series_dollars" in result
    assert "all_series_pct" in result
    assert isinstance(result["interpretation"], str)
    assert len(result["interpretation"]) > 30
