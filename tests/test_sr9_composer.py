"""SR9 Pass A tests for composer."""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

import numpy as np
import pandas as pd

from src.final.composer import compose_final_report_data
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


def _build_inputs(tmp_path, seed=21):
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


def test_compose_final_report_data_returns_required_top_level_keys(tmp_path):
    cost, sched, integ_by, sched_by, cv, titles = _build_inputs(tmp_path)
    composed = compose_final_report_data(
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
    expected_keys = {
        "cross_validation",
        "executive_summary",
        "cost_section",
        "schedule_section",
        "integrated_section",
        "appendix_counterfactual",
        "appendix_methodology",
        "appendix_audit_trail",
        "disclaimer_paragraphs",
    }
    assert expected_keys.issubset(composed.keys())


def test_compose_final_report_data_executive_summary_has_required_fields(tmp_path):
    cost, sched, integ_by, sched_by, cv, titles = _build_inputs(tmp_path)
    composed = compose_final_report_data(
        cost_results=cost,
        schedule_results=sched,
        integrated_results_by_scenario=integ_by,
        schedule_results_by_scenario=sched_by,
        strawman_path=tmp_path / "strawman.xlsx",
        register_path=tmp_path / "register.xlsx",
        cross_validation=cv,
        risk_titles=titles,
        config=_config_for_tmp(tmp_path),
    )
    es = composed["executive_summary"]
    expected = {
        "headline_contingency_range_p80",
        "top_3_cost_drivers",
        "top_3_schedule_drivers",
        "schedule_basis_note",
        "key_findings",
        "methodology_caveats",
        "recommendations",
        "diversification_summary",
    }
    assert expected.issubset(es.keys())
    assert len(es["top_3_cost_drivers"]) == 3
    assert len(es["top_3_schedule_drivers"]) == 3
    assert isinstance(es["schedule_basis_note"], str) and len(es["schedule_basis_note"]) > 50
    assert all(isinstance(x, str) for x in es["key_findings"])


def test_compose_final_report_data_passes_cross_validation_through(tmp_path):
    cost, sched, integ_by, sched_by, cv, titles = _build_inputs(tmp_path)
    composed = compose_final_report_data(
        cost_results=cost,
        schedule_results=sched,
        integrated_results_by_scenario=integ_by,
        schedule_results_by_scenario=sched_by,
        strawman_path=tmp_path / "strawman.xlsx",
        register_path=tmp_path / "register.xlsx",
        cross_validation=cv,
        risk_titles=titles,
        config=_config_for_tmp(tmp_path),
    )
    assert composed["cross_validation"] == cv
