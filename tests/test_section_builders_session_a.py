"""Unit tests for the SR14a.2 session-A section-builder modules.

Per the SR14a.2 brief AC6 / AC7 — each section-builder is independently
testable from its inputs without invoking the full composer, and the
returned dict-shape is asserted against the docstring contract.

Covers the four sections lifted in session A:

- ``page1_table`` (build_page1_table_section, build_page5_reconciliation_section)
- ``action_implications`` (build_action_implications_section)
- ``cost_drivers`` (build_cost_drivers_section)
- ``schedule_drivers`` (build_schedule_drivers_section)

s_curves + criticality are queued for session B and are exercised by
the existing scaffolding-stub parametrised test in
``tests/test_section_builders.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.final.sections.action_implications import (
    _build_specific_recommendations,
    _build_treatment_roi_table,
    build_action_implications_section,
)
from src.final.sections.cost_drivers import (
    _build_cost_tornado_data,
    _filter_cost_drivers_for_table,
    build_cost_drivers_section,
)
from src.final.sections.page1_table import (
    _build_comparison_table,
    _compute_component_breakdown,
    build_page1_table_section,
    build_page5_reconciliation_section,
    build_six_approach_reconciliation_table,
)
from src.final.sections.schedule_drivers import (
    _build_probability_weighted_schedule_drivers,
    build_schedule_drivers_section,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_risk(rid: str, **kwargs) -> SimpleNamespace:
    """Minimal RiskInput-like fixture for section-builder tests."""
    defaults = {
        "probability": 0.1,
        "ml_cost": 100_000.0,
        "ml_days": 5.0,
        "opt_schedule_days": 1.0,
        "pess_schedule_days": 15.0,
        "pess_cost": 500_000.0,
        "rbs_l1": "10.Civil",
        "correlation_group": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(risk_id=rid, **defaults)


def _make_synthetic_integrated_results(n_iter: int = 500, n_risks: int = 5) -> dict:
    """Build a minimal integrated_results dict matching the engine output."""
    rng = np.random.default_rng(0)
    return {
        "cost_dollars_array": rng.uniform(0, 10_000_000, size=n_iter),
        "schedule_days_array": rng.uniform(0, 30, size=n_iter),
        "per_risk_cost_array": rng.uniform(0, 2_000_000, size=(n_iter, n_risks)),
        "per_risk_schedule_array": rng.uniform(0, 5, size=(n_iter, n_risks)),
        "risk_ids_all": [f"R{i:03d}" for i in range(n_risks)],
        "risk_ids_dual": [f"R{i:03d}" for i in range(n_risks)],
    }


# ---------------------------------------------------------------------------
# page1_table
# ---------------------------------------------------------------------------


def test_page1_table_section_contract() -> None:
    """build_page1_table_section returns the documented keys."""
    integ_dp = _make_synthetic_integrated_results(n_iter=300)
    integ_dr = _make_synthetic_integrated_results(n_iter=300)
    by_scenario = {"DP_Review": integ_dp, "Dummy_Realistic": integ_dr, "All_Series": integ_dp}
    risks = [_make_risk(f"R{i:03d}") for i in range(5)]
    out = build_page1_table_section(
        integrated_results_by_scenario=by_scenario,
        integrated_dp=integ_dp,
        integrated_dr=integ_dr,
        risks_list=risks,
        programme_duration_days=502.0,
        day_rate=100_000.0,
        p_level=80,
        headline_metric="P80",
        scenario_display_lookup={"DP_Review": "DP Review", "All_Series": "All Series"},
        indicative_scenario_name="DP_Review",
        indicative_display_short="DP Review",
    )
    expected = {
        "breakdown", "page1_component_breakdown", "page1_range_table",
        "page1_range_table_dedup_footnote", "page1_six_approach_reconciliation",
        "mean_days_indicative", "mean_cost_indicative_m",
        "lower_days", "upper_days", "p80_days_indicative",
        "dp_review_p80_m", "all_series_p80_m",
    }
    assert set(out) == expected
    assert isinstance(out["breakdown"], dict)
    assert isinstance(out["page1_component_breakdown"], list)
    assert isinstance(out["page1_range_table"], list)
    assert isinstance(out["page1_six_approach_reconciliation"], dict)
    assert "table" in out["page1_six_approach_reconciliation"]


def test_page1_table_section_empty_arrays_returns_zeros() -> None:
    """Empty arrays produce zero-valued scalars and empty tables."""
    empty = {"cost_dollars_array": np.array([]), "schedule_days_array": np.array([])}
    out = build_page1_table_section(
        integrated_results_by_scenario={
            "DP_Review": empty, "Dummy_Realistic": empty, "All_Series": empty,
        },
        integrated_dp=empty,
        integrated_dr=empty,
        risks_list=[],
        programme_duration_days=None,
        day_rate=100_000.0,
        p_level=80,
        headline_metric="P80",
        scenario_display_lookup={},
        indicative_scenario_name="DP_Review",
        indicative_display_short="",
    )
    assert out["mean_days_indicative"] == 0.0
    assert out["page1_range_table"] == []
    assert out["page1_range_table_dedup_footnote"] is None
    assert out["breakdown"] == {}


def test_page5_reconciliation_section_contract() -> None:
    """build_page5_reconciliation_section returns the documented keys."""
    integ = _make_synthetic_integrated_results(n_iter=300)
    risks = [_make_risk(f"R{i:03d}") for i in range(5)]
    out = build_page5_reconciliation_section(
        risks_list=risks,
        integrated_dr=integ,
        schedule_results_indicative=integ,
        programme_duration_days=502.0,
        day_rate=100_000.0,
        cross_validation={"all_pass": True},
        waterfall_path="/tmp/waterfall.png",
    )
    assert set(out) == {"comparison_table", "waterfall_path", "cross_validation_panel"}
    assert isinstance(out["comparison_table"], pd.DataFrame)
    assert out["waterfall_path"] == "/tmp/waterfall.png"
    assert out["cross_validation_panel"] == {"all_pass": True}


# ---------------------------------------------------------------------------
# action_implications
# ---------------------------------------------------------------------------


def test_action_implications_section_contract(tmp_path: Path) -> None:
    """build_action_implications_section returns treatment_roi_table +
    recommendations, even when the strawman doesn't exist (graceful
    fallback to empty Treatments DataFrame)."""
    cost_drivers = [
        {"risk_id": "R001", "value": 5.0, "metric_name": "P80",
         "title": "Cost driver R001"},
        {"risk_id": "R002", "value": 3.0, "metric_name": "P80",
         "title": "Cost driver R002"},
    ]
    schedule_drivers = [
        {"risk_id": "R003", "prob_weighted_mean_days": 2.0,
         "probability": 0.3, "title": "Schedule driver R003"},
    ]
    out = build_action_implications_section(
        cost_drivers=cost_drivers,
        schedule_drivers=schedule_drivers,
        strawman_path=tmp_path / "nonexistent.xlsx",
        headline_metric="P80",
    )
    assert set(out) == {"treatment_roi_table", "recommendations"}
    assert isinstance(out["treatment_roi_table"], pd.DataFrame)
    assert isinstance(out["recommendations"], list)
    # Six-driver roll-up: 2 cost + 1 schedule = 3 rows total in this fixture.
    assert len(out["treatment_roi_table"]) == 3
    assert len(out["recommendations"]) >= 2


def test_action_implications_section_recommendation_phrasing() -> None:
    """The first recommendation names the top schedule drivers.

    It once had a second form, the PM Mode-review framing dev used; PRESENT-01 (D-4) retired it.
    """
    schedule_drivers = [
        {"risk_id": "R090", "prob_weighted_mean_days": 1.0, "probability": 0.2, "title": "x"},
        {"risk_id": "R067", "prob_weighted_mean_days": 0.5, "probability": 0.05, "title": "y"},
    ]
    out = build_action_implications_section(
        cost_drivers=[],
        schedule_drivers=schedule_drivers,
        strawman_path=Path("/nonexistent.xlsx"),
        headline_metric="P80",
    )
    recs = out["recommendations"]
    assert any("R090" in r and "R067" in r for r in recs)
    # No "Mode" wording leaks into the prod first recommendation.
    assert not any("Mode classification" in r for r in recs[:1])


# ---------------------------------------------------------------------------
# cost_drivers
# ---------------------------------------------------------------------------


def test_cost_drivers_section_contract() -> None:
    """build_cost_drivers_section returns cost_drivers_full plus the
    rendered page3_cost_drivers dict with the metric-aware value column
    header (Beta-16 Item 1)."""
    integ = _make_synthetic_integrated_results(n_iter=300, n_risks=8)
    risks = [_make_risk(f"R{i:03d}") for i in range(8)]
    out = build_cost_drivers_section(
        integrated_dp=integ,
        risks_list=risks,
        risk_titles={f"R{i:03d}": f"Title {i}" for i in range(8)},
        p_level=80,
        headline_metric="P80",
    )
    assert set(out) == {"cost_drivers_full", "page3_cost_drivers"}
    p3 = out["page3_cost_drivers"]
    assert p3["metric_name"] == "P80"
    assert p3["value_column_header"] == "P80 contribution ($M)"
    assert isinstance(p3["drivers_table"], list)
    assert isinstance(p3["rbs_l1_breakdown_table"], list)
    # cost_drivers_full carries metric_name on every entry for downstream consumers.
    assert all(d.get("metric_name") == "P80" for d in out["cost_drivers_full"])


def test_cost_drivers_section_mean_variant_relabels_column() -> None:
    """Headline metric Mean re-labels the column header."""
    integ = _make_synthetic_integrated_results(n_iter=300, n_risks=5)
    risks = [_make_risk(f"R{i:03d}") for i in range(5)]
    out = build_cost_drivers_section(
        integrated_dp=integ,
        risks_list=risks,
        risk_titles=None,
        p_level=80,
        headline_metric="Mean",
    )
    p3 = out["page3_cost_drivers"]
    assert p3["metric_name"] == "Mean"
    assert p3["value_column_header"] == "Mean contribution ($M)"


def test_cost_drivers_section_empty_arrays_returns_empties() -> None:
    """Empty arrays produce empty tables but preserve the dict shape."""
    empty = {
        "per_risk_cost_array": np.array([]),
        "risk_ids_all": [],
    }
    out = build_cost_drivers_section(
        integrated_dp=empty,
        risks_list=[],
        risk_titles=None,
        p_level=80,
        headline_metric="P80",
    )
    assert out["cost_drivers_full"] == []
    assert out["page3_cost_drivers"]["drivers_table"] == []
    assert out["page3_cost_drivers"]["rbs_l1_breakdown_table"] == []


# ---------------------------------------------------------------------------
# schedule_drivers
# ---------------------------------------------------------------------------


def test_schedule_drivers_section_contract() -> None:
    """build_schedule_drivers_section returns prob_weighted_sched_drivers
    + rendered page4_schedule_drivers dict."""
    integ = _make_synthetic_integrated_results(n_iter=300, n_risks=8)
    risks = [_make_risk(f"R{i:03d}", probability=0.2) for i in range(8)]
    out = build_schedule_drivers_section(
        integrated_dr=integ,
        risks_list=risks,
        risk_titles={f"R{i:03d}": f"Title {i}" for i in range(8)},
        indicative_scenario_display="DP Review baseline",
        mode_used={f"R{i:03d}": "Series" for i in range(8)},
        appendix_counterfactual=None,
        schedule_tornado_path="/tmp/tornado.png",
    )
    assert set(out) == {"prob_weighted_sched_drivers", "page4_schedule_drivers"}
    p4 = out["page4_schedule_drivers"]
    assert p4["tornado_path"] == "/tmp/tornado.png"
    assert isinstance(p4["drivers_table"], list)
    assert isinstance(p4["mode_sensitivity_table"], pd.DataFrame)
    assert isinstance(p4["rbs_l1_breakdown_table"], list)
    # Prod label is just "Mode"; dev label includes the indicative scenario.
    column_names = set(p4["drivers_table"][0]) if p4["drivers_table"] else set()
    assert "Mode" in column_names


def test_schedule_drivers_section_passes_through_counterfactual() -> None:
    """When an appendix_counterfactual is supplied the section's
    mode_sensitivity_table copies it (so downstream renderers can mutate
    a working copy without affecting the input)."""
    integ = _make_synthetic_integrated_results(n_iter=200, n_risks=3)
    risks = [_make_risk(f"R{i:03d}") for i in range(3)]
    cf = pd.DataFrame({
        "scenario_name": ["Baseline (DP Review)", "All Series"],
        "mc_mean_days": [1.0, 5.0],
        "mc_p50_days": [0.5, 4.5],
        "mc_p80_days": [2.0, 7.0],
    })
    out = build_schedule_drivers_section(
        integrated_dr=integ,
        risks_list=risks,
        risk_titles=None,
        indicative_scenario_display="DP Review",
        mode_used={},
        appendix_counterfactual=cf,
    )
    cf_out = out["page4_schedule_drivers"]["mode_sensitivity_table"]
    assert isinstance(cf_out, pd.DataFrame)
    assert len(cf_out) == 2
    assert cf_out is not cf  # copy, not the same object


# ---------------------------------------------------------------------------
# Composer re-exports (regression on backward-compat imports)
# ---------------------------------------------------------------------------


def test_composer_reexports_session_a_helpers() -> None:
    """Composer re-exports every helper moved in SR14a.2 session A so
    pre-existing test imports keep working without churn."""
    from src.final import composer

    assert composer._build_comparison_table is _build_comparison_table
    assert composer._compute_component_breakdown is _compute_component_breakdown
    assert composer.build_six_approach_reconciliation_table is build_six_approach_reconciliation_table
    assert composer._build_treatment_roi_table is _build_treatment_roi_table
    assert composer._build_specific_recommendations is _build_specific_recommendations
    assert composer._build_cost_tornado_data is _build_cost_tornado_data
    assert composer._filter_cost_drivers_for_table is _filter_cost_drivers_for_table
    assert (
        composer._build_probability_weighted_schedule_drivers
        is _build_probability_weighted_schedule_drivers
    )
