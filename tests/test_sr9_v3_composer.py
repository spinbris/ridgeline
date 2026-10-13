# SR9 v3 amendment - 2026-04-26 - presentation-layer reframe.
"""Tests for SR9 v3 composer extension.

Verifies that when v3 inputs (risks, chart_output_dir) are supplied,
compose_final_report_data extends the returned dict with the v3
page1..page8_audit_trail keys and that the headline is formatted with
runtime values (no leftover format placeholders).
"""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.final.composer import compose_final_report_data
from src.integrated.integrated_simulation import IntegratedConfig
from src.sra.methodology_defaults_reader import build_test_methodology_defaults
from tests._fixture_values import FIXTURE_DAY_RATE


def _fake_risk(risk_id: str, probability: float, ml_cost: float, ml_days: float, pess_cost: float, pess_days: float) -> SimpleNamespace:
    return SimpleNamespace(
        risk_id=risk_id,
        description=f"Test risk {risk_id}",
        probability=probability,
        ml_cost=ml_cost,
        opt_cost=ml_cost * 0.8,
        pess_cost=pess_cost,
        ml_days=ml_days,
        opt_schedule_days=ml_days * 0.8,
        pess_schedule_days=pess_days,
    )


def _fixture_inputs(tmp_path: Path):
    rng = np.random.default_rng(42)
    n_iter = 1000
    n_risks_all = 5
    n_risks_dual = 4

    per_risk_cost = rng.exponential(scale=200000.0, size=(n_iter, n_risks_all))
    per_risk_sched = rng.exponential(scale=1.0, size=(n_iter, n_risks_dual))
    cost_total = per_risk_cost.sum(axis=1)
    sched_total = per_risk_sched.sum(axis=1)
    risk_ids_all = [f"R{i:03d}" for i in range(n_risks_all)]
    risk_ids_dual = [f"R{i:03d}" for i in range(n_risks_dual)]

    integrated_results = {
        "cost_dollars_array": cost_total,
        "schedule_days_array": sched_total,
        "per_risk_cost_array": per_risk_cost,
        "per_risk_schedule_array": per_risk_sched,
        "risk_ids_all": risk_ids_all,
        "risk_ids_dual": risk_ids_dual,
        "iterations": n_iter,
    }
    integrated_by_scenario = {
        "DP_Review": integrated_results,
        "Dummy_Realistic": integrated_results,
        "All_Series": integrated_results,
    }

    schedule_results = {
        "finish_delay_days_array": sched_total,
        "contribution_array": per_risk_sched,
        "risk_ids": risk_ids_dual,
        "mode_used": {rid: "Series" for rid in risk_ids_dual},
    }
    schedule_by_scenario = {
        "DP_Review": schedule_results,
        "Dummy_Realistic": schedule_results,
        "All_Series": schedule_results,
    }

    cost_results = {
        "cost_dollars_array": cost_total,
        "per_risk_cost_array": per_risk_cost,
        "risk_ids": risk_ids_all,
    }

    risks = [
        _fake_risk(rid, 0.1 + 0.1 * (i % 4), 100000 * (i + 1), 2.0 * (i + 1), 500000 * (i + 1), 10.0 * (i + 1))
        for i, rid in enumerate(risk_ids_all)
    ]

    cv_result = {
        "all_pass": True,
        "cost_passes_calibration": True,
        "schedule_passes_calibration": True,
        "top_3_cost_match": True,
        "top_3_schedule_match": True,
        "cost_absolute_gap_dollars": 19500.0,
        "schedule_absolute_gap_days": 0.007,
        "cost_relative_gap_pct": 0.00169,
        "top_3_cost_contributors_consistent": True,
        "top_3_schedule_contributors_consistent": True,
        "top_3_cost_contributors_cost_only": ["R000", "R001", "R002"],
        "top_3_cost_contributors_integrated": ["R000", "R001", "R002"],
        "top_3_schedule_contributors_sr5": ["R000", "R001", "R002"],
        "top_3_schedule_contributors_integrated": ["R000", "R001", "R002"],
    }

    register_path = tmp_path / "register.xlsx"
    register_path.write_text("dummy")  # so hash works
    strawman_path = tmp_path / "strawman.xlsx"
    strawman_path.write_text("dummy")

    # SR19 §6.2: compose_final_report_data reads register_path itself (via
    # read_methodology_defaults, openpyxl.load_workbook) only when config
    # is None - the register fixture above is a text stub, not a real
    # xlsx, so that fallback would raise BadZipFile. Explicit config with
    # a test-factory methodology_defaults bypasses it (same fix as the
    # cg_descriptions bypass below, one SR-series layer later).
    config = IntegratedConfig(
        register_path=register_path,
        p6_path=register_path,
        strawman_path=strawman_path,
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
        random_seed=42,  # the page-7 chart's seed; no default (SEEDZERO-01)
    **TEST_CALIBRATION_TOLERANCES)

    return {
        "cost_results": cost_results,
        "schedule_results": schedule_results,
        "integrated_by_scenario": integrated_by_scenario,
        "schedule_by_scenario": schedule_by_scenario,
        "cv_result": cv_result,
        "risks": risks,
        "risk_titles": {r.risk_id: r.description for r in risks},
        "register_path": register_path,
        "strawman_path": strawman_path,
        "config": config,
    }


def test_compose_v3_keys_present(tmp_path: Path):
    f = _fixture_inputs(tmp_path)
    chart_dir = tmp_path / "charts"

    composed = compose_final_report_data(
        cost_results=f["cost_results"],
        schedule_results=f["schedule_results"],
        integrated_results_by_scenario=f["integrated_by_scenario"],
        schedule_results_by_scenario=f["schedule_by_scenario"],
        strawman_path=f["strawman_path"],
        register_path=f["register_path"],
        cross_validation=f["cv_result"],
        risk_titles=f["risk_titles"],
        risks=f["risks"],
        chart_output_dir=chart_dir,
        programme_duration_days=300.0,
        # Beta-17 SSoT: bypass register read - fixture register file is a
        # text stub, not a real xlsx; pass empty cg_descriptions so the
        # CG drivers table renders "(not in register)" placeholders.
        cg_descriptions={},
        config=f["config"],
    )
    expected_v3_keys = {
        "page1_headline", "page1_range_table", "callouts",
        "page2_distribution", "page3_cost_drivers",
        "page4_schedule_drivers", "page5_reconciliation",
        "page6_action_implications", "page7_methodology",
        "page8_audit_trail",
    }
    missing = expected_v3_keys - set(composed.keys())
    assert not missing, f"missing v3 keys: {missing}"
    assert "executive_summary" in composed  # v2 keys preserved


def test_compose_v3_headline_formatted_with_runtime_values(tmp_path: Path):
    f = _fixture_inputs(tmp_path)
    chart_dir = tmp_path / "charts"

    composed = compose_final_report_data(
        cost_results=f["cost_results"],
        schedule_results=f["schedule_results"],
        integrated_results_by_scenario=f["integrated_by_scenario"],
        schedule_results_by_scenario=f["schedule_by_scenario"],
        strawman_path=f["strawman_path"],
        register_path=f["register_path"],
        cross_validation=f["cv_result"],
        risk_titles=f["risk_titles"],
        risks=f["risks"],
        chart_output_dir=chart_dir,
        programme_duration_days=300.0,
        # Beta-17 SSoT: bypass register read - fixture register file is a
        # text stub, not a real xlsx; pass empty cg_descriptions so the
        # CG drivers table renders "(not in register)" placeholders.
        cg_descriptions={},
        config=f["config"],
    )
    headline = composed["page1_headline"]
    # No leftover format placeholders
    assert "{" not in headline and "}" not in headline
    # Headline contains runtime values, not hardcoded literals like "$4.4M"
    assert "days" in headline.lower()
    assert "$" in headline
    assert isinstance(composed["page1_range_table"], list)
    # PRESENT-01 (D-4): the "why MC matters" callout body is one of the keys the composer drops
    # - it belonged to the dev report, and no shipped deliverable carried it.
    assert composed["callouts"]["why_mc_matters"] == ""
