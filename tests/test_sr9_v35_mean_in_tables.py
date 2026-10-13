"""SR9 v3.5 - Mean column/row in PROD summary tables; alt PROD with Mean as headline.

Tests cover:
  - compute_mean_metrics correctness (synthetic and consistency with diversification)
  - Headline-metric resolver
  - the footnote constants

SNAPSHOTCUT-01 (Director, 11/10/2026): the twelve composer, docx and regression-lock tests, which
read the frozen v3.1 state-cache pickle and could only ever skip (SKIPDEAD-01), are retired.
"""
from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

import numpy as np
import pytest

from src.final import commentary_text
from src.final.executive_summary import (
    get_headline_contingency_range,
    resolve_headline_metric,
)
from src.integrated.integrated_analysis import compute_mean_metrics
from src.integrated.integrated_simulation import IntegratedConfig
from src.sra.methodology_defaults_reader import build_test_methodology_defaults
from tests._fixture_values import FIXTURE_DAY_RATE


# ---------------------------------------------------------------------------
# Synthetic-payload helpers (no MC engines required)
# ---------------------------------------------------------------------------

def _make_integrated_payload(rng, n=500, cost_lo=1e7, cost_hi=2e7,
                              sched_lo=0.0, sched_hi=10.0):
    cost = rng.uniform(cost_lo, cost_hi, size=n)
    sched = rng.uniform(sched_lo, sched_hi, size=n)
    return {
        "cost_dollars_array": cost,
        "schedule_days_array": sched,
        "per_risk_cost_array": rng.uniform(0, 1e6, size=(n, 2)),
        "per_risk_schedule_array": rng.uniform(0, 1, size=(n, 1)),
        "per_risk_schedule_pre_mode_array": rng.uniform(0, 1, size=(n, 1)),
        "risk_ids_all": ["R001", "R002"],
        "risk_ids_dual": ["R001"],
        "iterations": int(n),
    }


def _config_for_tests() -> IntegratedConfig:
    """An IntegratedConfig instance with sane defaults for synthetic tests.

    Uses placeholder paths since these tests do not load any files; the
    config is only consumed for day_rate / p_level / tolerances.
    """
    return IntegratedConfig(
        register_path="",
        p6_path="",
        strawman_path="",
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
    **TEST_CALIBRATION_TOLERANCES)


# ---------------------------------------------------------------------------
# compute_mean_metrics tests
# ---------------------------------------------------------------------------

def test_compute_mean_metrics_synthetic():
    """Mean values match np.mean of the underlying arrays."""
    rng = np.random.default_rng(7)
    integrated = _make_integrated_payload(rng, n=400)
    standalone_cost = {"cost_dollars_array": integrated["cost_dollars_array"].copy()}
    standalone_schedule = {
        "finish_delay_days_array": integrated["schedule_days_array"].copy(),
    }
    config = _config_for_tests()

    out = compute_mean_metrics(
        integrated_results=integrated,
        standalone_cost_l2only_results=standalone_cost,
        standalone_schedule_results=standalone_schedule,
        config=config,
    )

    expected_cost_mean = float(np.mean(standalone_cost["cost_dollars_array"]))
    expected_sched_mean_days = float(np.mean(standalone_schedule["finish_delay_days_array"]))
    expected_sched_mean_dollars = expected_sched_mean_days * config.day_rate
    expected_naive_sum = expected_cost_mean + expected_sched_mean_dollars
    expected_integrated_mean = float(np.mean(
        integrated["cost_dollars_array"]
        + integrated["schedule_days_array"] * config.day_rate
    ))

    assert out["cost_mean_dollars"] == pytest.approx(expected_cost_mean, rel=1e-9)
    assert out["schedule_mean_days"] == pytest.approx(expected_sched_mean_days, rel=1e-9)
    assert out["schedule_mean_dollars"] == pytest.approx(expected_sched_mean_dollars, rel=1e-9)
    assert out["naive_sum_mean_dollars"] == pytest.approx(expected_naive_sum, rel=1e-9)
    assert out["integrated_mean_dollars"] == pytest.approx(expected_integrated_mean, rel=1e-9)


def test_compute_mean_metrics_diversification_consistency():
    """diversification_at_mean = naive_sum_mean - integrated_mean (fp-tolerant)."""
    rng = np.random.default_rng(11)
    integrated = _make_integrated_payload(rng, n=600)
    standalone_cost = {"cost_dollars_array": integrated["cost_dollars_array"].copy()}
    standalone_schedule = {
        "finish_delay_days_array": integrated["schedule_days_array"].copy(),
    }
    config = _config_for_tests()

    out = compute_mean_metrics(
        integrated_results=integrated,
        standalone_cost_l2only_results=standalone_cost,
        standalone_schedule_results=standalone_schedule,
        config=config,
    )

    expected_div = out["naive_sum_mean_dollars"] - out["integrated_mean_dollars"]
    assert out["diversification_at_mean_dollars"] == pytest.approx(
        expected_div, abs=1e-6,
    )


# ---------------------------------------------------------------------------
# Headline-metric resolver
# ---------------------------------------------------------------------------

def test_resolve_headline_metric_canonical_forms():
    assert resolve_headline_metric("P80") == "P80"
    assert resolve_headline_metric("Mean") == "Mean"
    assert resolve_headline_metric("p80") == "P80"
    assert resolve_headline_metric("MEAN") == "Mean"


def test_resolve_headline_metric_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown headline_metric"):
        resolve_headline_metric("median")
    with pytest.raises(ValueError):
        resolve_headline_metric("P95")


def test_get_headline_contingency_range_p80_vs_mean():
    """P80 and Mean produce different headline figures on the same payload."""
    rng = np.random.default_rng(3)
    integrated = {
        "DP_Review": _make_integrated_payload(rng, n=400),
        "Dummy_Realistic": _make_integrated_payload(rng, n=400, sched_lo=10, sched_hi=30),
        "All_Series": _make_integrated_payload(rng, n=400, sched_lo=20, sched_hi=50),
    }
    p80_range = get_headline_contingency_range(
        integrated, p_level=80, day_rate=100000.0,
        headline_metric="P80",
    )
    mean_range = get_headline_contingency_range(
        integrated, p_level=80, day_rate=100000.0,
        headline_metric="Mean",
    )
    assert p80_range["headline_metric"] == "P80"
    assert mean_range["headline_metric"] == "Mean"
    # Mean of right-skewed-ish uniform ~< P80 (sampling); they must differ.
    assert p80_range["indicative_dollars"] != mean_range["indicative_dollars"]


# ---------------------------------------------------------------------------
# Footnotes
# ---------------------------------------------------------------------------

def test_footnote_constants_exist():
    assert hasattr(commentary_text, "MEAN_FOOTNOTE_TEXT")
    assert hasattr(commentary_text, "DIVERSIFICATION_TAIL_FOOTNOTE_TEXT")
    assert "P80" in commentary_text.MEAN_FOOTNOTE_TEXT
    assert "AU" in commentary_text.MEAN_FOOTNOTE_TEXT or "GN3A" in commentary_text.MEAN_FOOTNOTE_TEXT
    assert "AACE" in commentary_text.MEAN_FOOTNOTE_TEXT
    assert "diversification" in commentary_text.DIVERSIFICATION_TAIL_FOOTNOTE_TEXT.lower()

