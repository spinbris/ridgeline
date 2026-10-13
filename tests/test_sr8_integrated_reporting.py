"""SR8 - integrated_reporting tests."""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

from pathlib import Path

import pandas as pd
import pytest

from src.integrated.integrated_reporting import (
    get_calibration_panel_data,
    get_diversification_panel_data,
    get_disclaimer_text,
    get_joint_percentile_table,
)
from src.integrated.integrated_simulation import IntegratedConfig
from src.sra.methodology_defaults_reader import build_test_methodology_defaults
from tests._fixture_values import FIXTURE_DAY_RATE


def _make_cfg() -> IntegratedConfig:
    return IntegratedConfig(
        register_path=Path("/tmp/r"),
        p6_path=Path("/tmp/p"),
        strawman_path=Path("/tmp/s"),
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
    **TEST_CALIBRATION_TOLERANCES)


def test_get_calibration_panel_data_returns_required_keys():
    fake = {
        "cost_integrated_mean": 11_531_000.0,
        "cost_standalone_l2only_mean": 11_560_000.0,
        "cost_absolute_gap_dollars": 29_000.0,
        "cost_relative_gap_pct": 0.0025,
        "cost_passes_calibration": True,
        "schedule_integrated_mean_days": 1.74,
        "schedule_standalone_mean_days": 1.76,
        "schedule_absolute_gap_days": 0.02,
        "schedule_passes_calibration": True,
        "both_pass": True,
        "interpretation": "ok",
    }
    out = get_calibration_panel_data(fake)
    expected_keys = {
        "cost_status_label", "schedule_status_label", "both_pass",
        "cost_integrated_mean", "cost_standalone_l2only_mean",
        "cost_absolute_gap_dollars", "cost_relative_gap_pct",
        "schedule_integrated_mean_days", "schedule_standalone_mean_days",
        "schedule_absolute_gap_days", "interpretation",
    }
    assert expected_keys.issubset(set(out.keys()))
    assert out["cost_status_label"] == "PASS"
    assert out["schedule_status_label"] == "PASS"


def test_get_diversification_panel_data_three_scenarios():
    fake = {
        "scenarios": {
            "DP_Review": {"diversification_dollars": -100.0, "diversification_pct": -0.001},
            "All_Series": {"diversification_dollars": 500_000.0, "diversification_pct": 0.02},
            "Dummy_Realistic": {"diversification_dollars": 200_000.0, "diversification_pct": 0.01},
        },
        "all_series_passes_gate": True,
        "interpretation": "ok",
    }
    out = get_diversification_panel_data(fake)
    assert "scenarios" in out
    assert {"DP_Review", "All_Series", "Dummy_Realistic"}.issubset(out["scenarios"].keys())
    assert out["all_series_passes_gate"] is True


def test_get_joint_percentile_table_columns():
    df = pd.DataFrame([
        {"p_level": 50, "cost_dollars": 1, "schedule_days": 0,
         "schedule_dollars": 0, "integrated_total_dollars": 1},
        {"p_level": 80, "cost_dollars": 2, "schedule_days": 0,
         "schedule_dollars": 0, "integrated_total_dollars": 2},
    ])
    out = get_joint_percentile_table(df)
    assert "p_level" in out.columns
    assert "integrated_total_dollars" in out.columns


def test_get_disclaimer_text_includes_joint_sampling_explanation():
    cfg = _make_cfg()
    text = get_disclaimer_text(cfg, run_config={})
    assert "joint sampling" in text.lower() or "shared uniform" in text.lower()
    assert "8 dual-coded" in text or "dual-coded" in text.lower()
    assert "$100,000" in text
