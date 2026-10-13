# SR9 v3.1 amendment - 2026-04-26 - executive summary clarity patch.
"""Tests for SR9 v3.1 Page 1 helpers (Deliverables 2, 3, 4, 10).

Covers:
  - _filter_cost_drivers_for_table (Deliverable 2)
  - _build_specific_recommendations (Deliverable 3)
  - page1_top_schedule_driver dominance text composition (Deliverable 4)
  - _compute_component_breakdown / _build_component_breakdown_table (D10)

Word generator key-name fix (Deliverable 1) is exercised by the full
RUN_FINAL.bat smoke check rather than a unit test - the typo's behaviour
was wrong cv-panel rendering in a generated .docx, which the existing
test_sr9_v3_word_generator.py harness already exercises.
"""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.final import commentary_text
from src.final.composer import (
    _build_component_breakdown_table,
    _build_specific_recommendations,
    _compute_component_breakdown,
    _filter_cost_drivers_for_table,
    compose_final_report_data,
)
from src.integrated.integrated_simulation import IntegratedConfig
from src.sra.methodology_defaults_reader import build_test_methodology_defaults
from tests._fixture_values import FIXTURE_DAY_RATE


# ---------------------------------------------------------------------------
# Deliverable 2 - cost drivers table filter
# ---------------------------------------------------------------------------


def _make_driver(rid: str, value_m: float) -> dict:
    return {
        "risk_id": rid,
        "title": f"Test risk {rid}",
        "value": value_m,
        "value_dollars": value_m * 1e6,
        "pct_of_total": 0.0,
    }


def test_filter_cost_drivers_keeps_top_three_unconditionally():
    drivers = [
        _make_driver("R001", 1.65),
        _make_driver("R002", 1.38),
        _make_driver("R003", 0.79),
        _make_driver("R004", 0.05),  # below threshold
        _make_driver("R005", 0.00),
        _make_driver("R006", 0.00),
    ]
    out = _filter_cost_drivers_for_table(drivers, threshold_m=0.10, cap=5)
    assert [d["risk_id"] for d in out] == ["R001", "R002", "R003"]


def test_filter_cost_drivers_admits_position_4_5_when_above_threshold():
    drivers = [
        _make_driver("R001", 2.0),
        _make_driver("R002", 1.5),
        _make_driver("R003", 1.0),
        _make_driver("R004", 0.50),  # above threshold
        _make_driver("R005", 0.20),  # above threshold
        _make_driver("R006", 0.00),
    ]
    out = _filter_cost_drivers_for_table(drivers, threshold_m=0.10, cap=5)
    assert [d["risk_id"] for d in out] == ["R001", "R002", "R003", "R004", "R005"]


def test_filter_cost_drivers_caps_at_five():
    drivers = [_make_driver(f"R{i:03d}", 1.0) for i in range(8)]
    out = _filter_cost_drivers_for_table(drivers, threshold_m=0.10, cap=5)
    assert len(out) == 5


def test_filter_cost_drivers_handles_short_list():
    drivers = [_make_driver("R001", 1.0)]
    out = _filter_cost_drivers_for_table(drivers, threshold_m=0.10, cap=5)
    assert [d["risk_id"] for d in out] == ["R001"]


def test_filter_cost_drivers_empty():
    assert _filter_cost_drivers_for_table([], threshold_m=0.10, cap=5) == []


# ---------------------------------------------------------------------------
# Deliverable 3 - recommendation #1 with explicit risk IDs
# ---------------------------------------------------------------------------


def _counterfactual_df():
    """Mirror the SR5 run_counterfactual_table output schema."""
    rows = [
        {"scenario_id": 1, "scenario_name": "Baseline (DP Review)",
         "mc_mean_days": 1.78, "delta_from_baseline_days": 0.0},
        {"scenario_id": 2, "scenario_name": "All Series",
         "mc_mean_days": 19.64, "delta_from_baseline_days": 17.86},
        {"scenario_id": 3, "scenario_name": "All Hybrid",
         "mc_mean_days": 9.75, "delta_from_baseline_days": 7.97},
        {"scenario_id": 4, "scenario_name": "Dummy realistic (" + "S" + "JP)",
         "mc_mean_days": 15.47, "delta_from_baseline_days": 13.69},
        {"scenario_id": 9, "scenario_name": "R017.1 -> Series",
         "mc_mean_days": 11.88, "delta_from_baseline_days": 10.10},
        {"scenario_id": 10, "scenario_name": "R026.1 -> Series",
         "mc_mean_days": 5.44, "delta_from_baseline_days": 3.66},
        {"scenario_id": 11, "scenario_name": "R067 -> Series",
         "mc_mean_days": 3.27, "delta_from_baseline_days": 1.49},
        {"scenario_id": 12, "scenario_name": "R090 -> Series",
         "mc_mean_days": 1.74, "delta_from_baseline_days": -0.03},
    ]
    return pd.DataFrame(rows)


def test_recommendations_name_the_top_schedule_drivers():
    """The first recommendation names the drivers, not a Mode review.

    PRESENT-01 (D-4) retired the dev form of this recommendation, which read explicit risk ids
    and Mode-shift deltas out of the counterfactual table. The three tests of that form went
    with it: it was never in a shipped report, and the builder no longer takes a counterfactual.
    """
    recs = _build_specific_recommendations(
        cost_drivers=[_make_driver("R028", 1.65)],
        schedule_drivers=[{"risk_id": "R067"}, {"risk_id": "R013"}, {"risk_id": "R090"}],
    )
    assert "R067, R013, R090" in recs[0]
    assert "Mode" not in recs[0]


def test_the_tail_recommendation_selects_on_shape_not_on_a_risk_id():
    """PRESENT-01 (P-4): the tail watch names the rarely-fired, large-when-fired driver.

    It used to fire on ``risk_id == "R067"``, which is a fact about one project's register. The
    driver here is called R001 and has no special name; it earns the recommendation because it
    fires in 2.5% of iterations and contributes 300 days when it does.
    """
    drivers = [
        {"risk_id": "R900", "probability": 0.60, "mean_impact_when_fired_days": 4.0,
         "pct_of_total_mean": 0.55},
        {"risk_id": "R001", "probability": 0.025, "mean_impact_when_fired_days": 300.0,
         "pct_of_total_mean": 0.30},
    ]
    recs = _build_specific_recommendations(cost_drivers=[], schedule_drivers=drivers)
    tail_rec = next(r for r in recs if "dominates upper-percentile contingency" in r)
    assert "R001" in tail_rec
    assert "R900" not in tail_rec
    # The figures are the run's, not literals.
    assert "2.5%" in tail_rec
    assert "300 days" in tail_rec


def test_no_tail_recommendation_when_no_driver_has_a_tail():
    """Every driver fires often, so none is a tail risk and the watch is not printed."""
    drivers = [
        {"risk_id": "R900", "probability": 0.60, "mean_impact_when_fired_days": 4.0,
         "pct_of_total_mean": 0.55},
        {"risk_id": "R901", "probability": 0.40, "mean_impact_when_fired_days": 9.0,
         "pct_of_total_mean": 0.45},
    ]
    recs = _build_specific_recommendations(cost_drivers=[], schedule_drivers=drivers)
    assert not any("dominates upper-percentile contingency" in r for r in recs)


def test_recommendations_without_drivers_still_return_the_standing_ones():
    recs = _build_specific_recommendations(cost_drivers=[], schedule_drivers=[])
    assert recs


# ---------------------------------------------------------------------------
# Deliverable 4 - top schedule driver and dominance text
# ---------------------------------------------------------------------------


def _fake_risk(risk_id: str, prob: float, ml_days: float, pess_days: float) -> SimpleNamespace:
    return SimpleNamespace(
        risk_id=risk_id,
        description=f"Test risk {risk_id}",
        probability=prob,
        ml_cost=100_000.0,
        opt_cost=80_000.0,
        pess_cost=500_000.0,
        ml_days=ml_days,
        opt_schedule_days=ml_days * 0.8,
        pess_schedule_days=pess_days,
    )


def _compose_inputs(tmp_path: Path, dominant_pct: float = 0.66):
    """Build inputs where a single risk dominates the schedule mean.

    The integrated per_risk_schedule_array column means determine the
    prob-weighted mean ranking. We construct the array so that risk 0
    (R017.1) holds `dominant_pct` of the total mean.
    """
    rng = np.random.default_rng(7)
    n_iter = 1000
    n_risks_dual = 4

    # Indicative scenario - rig per_risk_schedule so R017.1 dominates.
    means_target = np.array([
        dominant_pct,
        (1 - dominant_pct) * 0.5,
        (1 - dominant_pct) * 0.3,
        (1 - dominant_pct) * 0.2,
    ])
    per_risk_sched = (
        rng.exponential(scale=1.0, size=(n_iter, n_risks_dual))
        * means_target[np.newaxis, :]
    )
    per_risk_cost = rng.exponential(scale=200_000.0, size=(n_iter, n_risks_dual))
    cost_total = per_risk_cost.sum(axis=1)
    sched_total = per_risk_sched.sum(axis=1)

    risk_ids = ["R017.1", "R026.1", "R067", "R090"]
    integrated = {
        "cost_dollars_array": cost_total,
        "schedule_days_array": sched_total,
        "per_risk_cost_array": per_risk_cost,
        "per_risk_schedule_array": per_risk_sched,
        "risk_ids_all": risk_ids,
        "risk_ids_dual": risk_ids,
        "iterations": n_iter,
    }
    by_scenario = {
        "DP_Review": integrated,
        "Dummy_Realistic": integrated,
        "All_Series": integrated,
    }

    schedule_results = {
        "finish_delay_days_array": sched_total,
        "contribution_array": per_risk_sched,
        "risk_ids": risk_ids,
        "mode_used": {rid: "Series" for rid in risk_ids},
    }
    schedule_by_scenario = {
        "DP_Review": schedule_results,
        "Dummy_Realistic": schedule_results,
        "All_Series": schedule_results,
    }
    cost_results = {
        "cost_dollars_array": cost_total,
        "per_risk_cost_array": per_risk_cost,
        "risk_ids": risk_ids,
    }

    cv_result = {
        "all_pass": True,
        "cost_passes_calibration": True,
        "schedule_passes_calibration": True,
        "top_3_cost_contributors_consistent": True,
        "top_3_schedule_contributors_consistent": True,
        "cost_absolute_gap_dollars": 0.0,
        "schedule_absolute_gap_days": 0.0,
        "cost_relative_gap_pct": 0.0,
        "top_3_cost_contributors_cost_only": risk_ids[:3],
        "top_3_cost_contributors_integrated": risk_ids[:3],
        "top_3_schedule_contributors_sr5": risk_ids[:3],
        "top_3_schedule_contributors_integrated": risk_ids[:3],
    }

    risks = [
        _fake_risk("R017.1", 0.5, 20.0, 50.0),
        _fake_risk("R026.1", 0.3, 5.0, 15.0),
        _fake_risk("R067", 0.025, 0.0, 365.0),
        _fake_risk("R090", 0.5, 1.0, 5.0),
    ]
    risk_titles = {
        "R017.1": "subcontract inefficiencies / late commencement - test description",
        "R026.1": "Contractor workforce productivity",
        "R067": "transformer lead time tail risk",
        "R090": "commissioning scope or time exceeds allowance",
    }

    register_path = tmp_path / "register.xlsx"
    register_path.write_text("dummy")
    strawman_path = tmp_path / "strawman.xlsx"
    strawman_path.write_text("dummy")
    chart_dir = tmp_path / "charts"

    # SR19 §6.2: compose_final_report_data reads register_path itself (via
    # read_methodology_defaults, openpyxl.load_workbook) only when config
    # is None - the register fixture above is a text stub, not a real
    # xlsx. Explicit config with a test-factory methodology_defaults
    # bypasses that fallback (same fix as the cg_descriptions bypass at
    # each call site, one SR-series layer later).
    config = IntegratedConfig(
        register_path=register_path, p6_path=register_path,
        strawman_path=strawman_path,
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
        random_seed=42,  # the page-7 chart's seed; no default (SEEDZERO-01)
    **TEST_CALIBRATION_TOLERANCES)

    return {
        "cost_results": cost_results,
        "schedule_results": schedule_results,
        "integrated_by_scenario": by_scenario,
        "schedule_by_scenario": schedule_by_scenario,
        "cv_result": cv_result,
        "risks": risks,
        "risk_titles": risk_titles,
        "register_path": register_path,
        "strawman_path": strawman_path,
        "chart_dir": chart_dir,
        "config": config,
    }


def test_page1_top_schedule_driver_exposes_dominance_text(tmp_path: Path):
    f = _compose_inputs(tmp_path, dominant_pct=0.66)

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
        chart_output_dir=f["chart_dir"],
        programme_duration_days=300.0,
        # Beta-17 SSoT: bypass register read - fixture register file is a
        # text stub, not a real xlsx; pass empty cg_descriptions so the
        # CG drivers table renders "(not in register)" placeholders.
        cg_descriptions={},
        config=f["config"],
    )

    top = composed["page1_top_schedule_driver"]
    assert top, "page1_top_schedule_driver should be non-empty"
    # Snake-case keys with numeric percentage are required (downstream consumers
    # cannot use Title-case strings).
    assert "risk_id" in top
    assert "title" in top
    assert "pct_of_total_mean" in top
    pct = float(top["pct_of_total_mean"])
    assert 0.0 <= pct <= 1.0

    dominance_text = top["dominance_text"]
    assert dominance_text
    assert "{" not in dominance_text and "}" not in dominance_text
    assert top["risk_id"] in dominance_text
    # Top driver dominates - dominance phrasing kicks in when pct >= 0.5.
    assert "single risk" in dominance_text


def test_page1_top_schedule_driver_uses_fallback_when_share_below_50pct(tmp_path: Path):
    f = _compose_inputs(tmp_path, dominant_pct=0.30)

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
        chart_output_dir=f["chart_dir"],
        programme_duration_days=300.0,
        # Beta-17 SSoT: bypass register read - fixture register file is a
        # text stub, not a real xlsx; pass empty cg_descriptions so the
        # CG drivers table renders "(not in register)" placeholders.
        cg_descriptions={},
        config=f["config"],
    )
    top = composed["page1_top_schedule_driver"]
    assert top
    dominance_text = top["dominance_text"]
    # Fallback phrasing references "top three risks" rather than "single risk".
    assert "top three" in dominance_text
    assert "{" not in dominance_text and "}" not in dominance_text


# ---------------------------------------------------------------------------
# Deliverable 10 - component breakdown table
# ---------------------------------------------------------------------------


def test_compute_component_breakdown_round_trip():
    rng = np.random.default_rng(11)
    n_iter = 1000
    cost = rng.exponential(scale=2_000_000.0, size=n_iter)
    sched = rng.exponential(scale=2.0, size=n_iter)

    # DP_Review is the indicative scenario (SR9 v3.3 Path A; PRESENT-01 D-4 left it the only
    # answer), so the arrays under test belong under that key.
    by_scenario = {
        "DP_Review": {
            "cost_dollars_array": cost,
            "schedule_days_array": sched,
        },
    }
    breakdown = _compute_component_breakdown(by_scenario, day_rate=100_000.0, p_level=80)

    expected_cost_p80 = float(np.percentile(cost, 80))
    expected_sched_p80_days = float(np.percentile(sched, 80))
    expected_sched_p80_dollars = expected_sched_p80_days * 100_000.0
    expected_integrated_p80 = float(np.percentile(cost + sched * 100_000.0, 80))
    expected_naive = expected_cost_p80 + expected_sched_p80_dollars

    assert breakdown["cost_p80_dollars"] == pytest.approx(expected_cost_p80, rel=1e-9)
    assert breakdown["sched_p80_days"] == pytest.approx(expected_sched_p80_days, rel=1e-9)
    assert breakdown["sched_p80_dollars"] == pytest.approx(expected_sched_p80_dollars, rel=1e-9)
    assert breakdown["integrated_p80_dollars"] == pytest.approx(expected_integrated_p80, rel=1e-9)
    assert breakdown["naive_sum_dollars"] == pytest.approx(expected_naive, rel=1e-9)
    assert (
        breakdown["diversification_dollars"]
        == pytest.approx(expected_integrated_p80 - expected_naive, rel=1e-9, abs=1e-6)
    )


def test_compute_component_breakdown_empty_when_indicative_missing():
    by_scenario = {"Dummy_Realistic": {}}
    breakdown = _compute_component_breakdown(by_scenario, day_rate=100_000.0)
    assert breakdown == {}


def test_build_component_breakdown_table_renders_five_rows():
    """Five rows (Component / P80 / Mean / Notes; legacy "Value" alias).

    Component labels were shortened under SR9 v3.5 because the Mean column
    is now alongside the P80 column - the per-row "(P80)" suffix would be
    misleading. The v3.1 / v3.5 contract is the same five components in
    the same order.
    """
    rng = np.random.default_rng(22)
    n_iter = 500
    by_scenario = {
        "DP_Review": {
            "cost_dollars_array": rng.exponential(scale=2_000_000.0, size=n_iter),
            "schedule_days_array": rng.exponential(scale=2.0, size=n_iter),
        },
    }
    breakdown = _compute_component_breakdown(by_scenario, day_rate=100_000.0)
    table = _build_component_breakdown_table(breakdown)

    assert len(table) == 5
    components = [r["Component"] for r in table]
    assert components == [
        "Cost contingency",
        "Schedule contingency (dollarised)",
        "Naive sum",
        "Diversification effect",
        "Integrated total",
    ]
    # All values are pre-formatted strings; "Value" is the legacy alias for
    # the P80 column. P80 and Mean columns are also present per v3.5.
    for row in table:
        assert isinstance(row["Value"], str)
        assert "$" in row["Value"]
        assert "$" in row["P80"]
        assert "$" in row["Mean"]


def test_build_component_breakdown_table_handles_negative_diversification():
    """Diversification effect carries explicit sign; negative case rendered '-$X.XXM'."""
    breakdown = {
        "p_level": 80,
        "cost_p80_m": 5.0,
        "sched_p80_dollars_m": 3.0,
        "naive_sum_m": 8.0,
        "integrated_p80_m": 7.5,
        "diversification_m": -0.5,
        # SR9 v3.5: Mean-equivalents required by the table renderer.
        "cost_mean_m": 4.0,
        "sched_mean_days": 0.0,
        "sched_mean_dollars_m": 2.5,
        "naive_sum_mean_m": 6.5,
        "integrated_mean_m": 6.0,
        "diversification_at_mean_m": -0.5,
    }
    # Fill other dollar keys for completeness; not consumed by the renderer.
    breakdown.setdefault("cost_p80_dollars", 5e6)
    breakdown.setdefault("sched_p80_days", 0.0)
    breakdown.setdefault("sched_p80_dollars", 3e6)
    breakdown.setdefault("naive_sum_dollars", 8e6)
    breakdown.setdefault("integrated_p80_dollars", 7.5e6)
    breakdown.setdefault("diversification_dollars", -0.5e6)

    table = _build_component_breakdown_table(breakdown)
    div_row = next(r for r in table if r["Component"] == "Diversification effect")
    assert div_row["Value"].startswith("-$")
    assert "0.50" in div_row["Value"]


def test_build_component_breakdown_table_empty_when_breakdown_empty():
    assert _build_component_breakdown_table({}) == []


# ---------------------------------------------------------------------------
# Deliverable 5 / 6 / 9 - static text constants exposed
# ---------------------------------------------------------------------------


def test_v3_1_static_constants_present():
    """Verify v3.1 narrative constants exist in commentary_text and are
    non-empty. Templates should still contain placeholders; static
    paragraphs should not.

    SR9 v3.5 amendment: READING_CONVENTION moved from static to template
    (gained {indicative_mix}/{dp_review_mix}/{all_series_mix} placeholders
    so narrative reflects runtime data instead of baked literals).
    """
    # Templates retain placeholders.
    for template in (
        commentary_text.HEADLINE_INTEGRATED_P80,
        commentary_text.SCHEDULE_DAYS_CONTEXT,
        commentary_text.MODE_CAVEAT_HEADLINE,
        commentary_text.DOMINANT_RISK_TEMPLATE,
        commentary_text.DOMINANT_RISK_FALLBACK,
        commentary_text.READING_CONVENTION,  # SR9 v3.5: now a template
    ):
        assert "{" in template

    # Static paragraphs - no placeholders.
    for static in (
        commentary_text.READING_CONVENTION_TITLE,
        commentary_text.MEAN_COST_IDENTICAL_NOTE,
        commentary_text.COST_DRIVERS_MODE_INDEPENDENCE_NOTE,
        commentary_text.CONFIDENCE_CURVE_PREAMBLE,
        commentary_text.CONFIDENCE_CURVE_FOOTNOTE,
    ):
        assert "{" not in static
        assert "}" not in static
        assert static.strip()
