# SR9 v3.1 amendment - 2026-04-26 - executive summary clarity patch.
"""Tests for SR9 v3.1 Deliverable 11 - Page 2 confidence curve table.

Verifies _build_confidence_curve and _compute_component_breakdown produce
consistent values for the interim scenario, that the recommended
P-level is flagged correctly, that ordered P-levels yield monotonically
non-decreasing integrated contingency and schedule slip days, and that
the page 2 confidence curve P80 row reconciles with the page 5
_waterfall_components naive_sum (single source of truth lock).
"""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.final.composer import (
    _build_confidence_curve,
    _compute_component_breakdown,
    _waterfall_components,
    compose_final_report_data,
)
from src.integrated.integrated_simulation import IntegratedConfig
from src.sra.methodology_defaults_reader import build_test_methodology_defaults
from tests._fixture_values import FIXTURE_DAY_RATE


def _fixture_integrated_by_scenario(seed: int = 42, n_iter: int = 5000):
    """Build a small fake integrated_results_by_scenario for unit tests.

    The indicative scenario (DP_Review, SR9 v3.3 Path A) has correlated cost+schedule so the
    joint sampling adjustment is non-zero by construction; this exercises the diversification
    arithmetic. PRESENT-01 (D-4): the correlated arrays sat under Dummy_Realistic while the
    resolver's dev default named it; with one answer they sit under the one it names.
    """
    rng = np.random.default_rng(seed)

    # Indicative: positively correlate cost and schedule via a shared latent.
    latent = rng.exponential(scale=1.0, size=n_iter)
    cost = 5_000_000.0 + latent * 1_000_000.0 + rng.normal(0, 200_000.0, n_iter)
    sched = latent * 2.0 + rng.normal(0, 0.3, n_iter)
    sched = np.clip(sched, 0.0, None)

    indicative = {
        "cost_dollars_array": cost,
        "schedule_days_array": sched,
        "per_risk_cost_array": np.zeros((n_iter, 1)),
        "per_risk_schedule_array": np.zeros((n_iter, 1)),
        "risk_ids_all": ["R000"],
        "risk_ids_dual": ["R000"],
        "iterations": n_iter,
    }

    # Alternate Mode scenario: lower mean schedule (Parallel-heavy assumption).
    dr = dict(indicative)
    dr["schedule_days_array"] = sched * 0.2

    # All Series: higher mean schedule.
    as_sched = sched * 1.5
    as_ = dict(indicative)
    as_["schedule_days_array"] = as_sched

    return {
        "DP_Review": indicative,
        "Dummy_Realistic": dr,
        "All_Series": as_,
    }


# ---------------------------------------------------------------------------
# Direct unit tests on _build_confidence_curve
# ---------------------------------------------------------------------------


def test_confidence_curve_returns_five_p_levels():
    """v3.1 contract: five P-level rows. Under SR9 v3.5 a Mean row is also
    inserted (at its natural sort position by integrated_contingency_m); the
    five P-level rows persist in the same order.
    """
    by_scenario = _fixture_integrated_by_scenario()
    curve = _build_confidence_curve(by_scenario, day_rate=100_000.0)

    p_rows = [r for r in curve if r.get("confidence_level", "").startswith("P")]
    assert len(p_rows) == 5
    assert [r["confidence_level"] for r in p_rows] == ["P50", "P70", "P80", "P90", "P95"]


def test_confidence_curve_p80_is_marked_recommended():
    by_scenario = _fixture_integrated_by_scenario()
    curve = _build_confidence_curve(
        by_scenario, day_rate=100_000.0, recommended_p_level=80,
    )

    p80_rows = [r for r in curve if r["is_recommended"]]
    assert len(p80_rows) == 1
    assert p80_rows[0]["confidence_level"] == "P80"

    other_rows = [r for r in curve if not r["is_recommended"]]
    assert all(r["confidence_level"] != "P80" for r in other_rows)


def test_confidence_curve_p_levels_monotonic_in_contingency_and_days():
    """Integrated contingency and schedule slip days are monotonic in P-level
    by construction (percentiles of a fixed array). above_naive_sum_m is NOT
    asserted monotonic - it can vary non-monotonically across P-levels.
    """
    by_scenario = _fixture_integrated_by_scenario()
    curve = _build_confidence_curve(by_scenario, day_rate=100_000.0)

    contingencies = [r["integrated_contingency_m"] for r in curve]
    sched_days = [r["schedule_slip_days"] for r in curve]

    assert contingencies == sorted(contingencies), (
        f"integrated_contingency_m not monotonic: {contingencies}"
    )
    assert sched_days == sorted(sched_days), (
        f"schedule_slip_days not monotonic: {sched_days}"
    )


def test_confidence_curve_above_naive_sum_calculation():
    """The above_naive_sum_m column equals integrated minus naive sum.

    naive_sum at each P-level = cost_p + schedule_p_dollarised at that P-level
    (using integrated marginals). integrated_contingency_m at the same P-level
    is the percentile of (cost + schedule * day_rate). above_naive_sum_m =
    integrated - naive_sum. Verify the relationship row-by-row by computing
    naive_sum independently and checking the published delta.
    """
    by_scenario = _fixture_integrated_by_scenario()
    day_rate = 100_000.0
    curve = _build_confidence_curve(by_scenario, day_rate=day_rate)

    indicative = by_scenario["DP_Review"]
    cost_arr = np.asarray(indicative["cost_dollars_array"])
    sched_arr = np.asarray(indicative["schedule_days_array"])

    for row in curve:
        p_label = row["confidence_level"]
        if not p_label.startswith("P"):
            # SR9 v3.5: Mean row uses arithmetic means rather than percentiles.
            continue
        p = int(p_label[1:])  # "P80" -> 80
        cost_p = float(np.percentile(cost_arr, p))
        sched_p_dollars = float(np.percentile(sched_arr * day_rate, p))
        naive_sum = cost_p + sched_p_dollars
        integrated_p = row["integrated_contingency_m"] * 1e6

        expected_above_naive = (integrated_p - naive_sum) / 1e6
        assert row["above_naive_sum_m"] == pytest.approx(expected_above_naive, abs=1e-6), (
            f"{p_label}: above_naive_sum_m={row['above_naive_sum_m']:.6f} "
            f"does not equal integrated - naive_sum={expected_above_naive:.6f}"
        )


def test_confidence_curve_p80_reconciles_with_waterfall_naive_sum():
    """Single-source-of-truth lock: page 2 confidence curve P80 row's
    naive_sum (cost_p80 + sched_p80*day_rate from integrated marginals) must
    equal the v3 page 5 _waterfall_components naive_sum within numerical
    tolerance. Catches any future regression where one path drifts from the
    other - e.g. someone switching D11 to standalone arrays.
    """
    by_scenario = _fixture_integrated_by_scenario()
    day_rate = 100_000.0

    curve = _build_confidence_curve(by_scenario, day_rate=day_rate)
    waterfall = _waterfall_components(by_scenario, day_rate=day_rate)
    breakdown = _compute_component_breakdown(by_scenario, day_rate=day_rate, p_level=80)

    p80_row = next(r for r in curve if r["confidence_level"] == "P80")
    cc_naive_sum_m = (
        p80_row["integrated_contingency_m"] - p80_row["above_naive_sum_m"]
    )

    # _waterfall_components returns a list of dicts with label/value/category.
    cost_only_p80 = next(d["value"] for d in waterfall if d["label"] == "Cost-only P80")
    sched_p80 = next(
        d["value"] for d in waterfall
        if d["label"] == "Schedule slip P80 dollarised"
    )
    waterfall_naive_sum_m = cost_only_p80 + sched_p80

    breakdown_naive_sum_m = breakdown["naive_sum_m"]

    # All three sources should agree to numerical precision.
    assert cc_naive_sum_m == pytest.approx(waterfall_naive_sum_m, rel=1e-9, abs=1e-6)
    assert cc_naive_sum_m == pytest.approx(breakdown_naive_sum_m, rel=1e-9, abs=1e-6)
    assert (
        p80_row["integrated_contingency_m"]
        == pytest.approx(breakdown["integrated_p80_m"], rel=1e-9, abs=1e-6)
    )


def test_confidence_curve_empty_when_indicative_missing():
    """Defensive: empty array or missing scenario yields empty curve."""
    by_scenario = {
        "DP_Review": {
            "cost_dollars_array": np.array([]),
            "schedule_days_array": np.array([]),
        },
    }
    curve = _build_confidence_curve(by_scenario, day_rate=100_000.0)
    assert curve == []


# ---------------------------------------------------------------------------
# Integration test - confidence curve appears in compose_final_report_data
# ---------------------------------------------------------------------------


def _fake_risk(risk_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        risk_id=risk_id,
        description=f"Test risk {risk_id}",
        probability=0.2,
        ml_cost=100_000.0,
        opt_cost=80_000.0,
        pess_cost=500_000.0,
        ml_days=1.0,
        opt_schedule_days=0.8,
        pess_schedule_days=10.0,
    )


def test_compose_exposes_page2_confidence_curve_keys(tmp_path: Path):
    by_scenario = _fixture_integrated_by_scenario()

    register_path = tmp_path / "register.xlsx"
    register_path.write_text("dummy")
    strawman_path = tmp_path / "strawman.xlsx"
    strawman_path.write_text("dummy")
    chart_dir = tmp_path / "charts"

    indicative = by_scenario["DP_Review"]
    risk_ids = list(indicative["risk_ids_all"])
    risks = [_fake_risk(rid) for rid in risk_ids]

    schedule_results = {
        "finish_delay_days_array": indicative["schedule_days_array"],
        "contribution_array": indicative["per_risk_schedule_array"],
        "risk_ids": indicative["risk_ids_dual"],
        "mode_used": {rid: "Series" for rid in indicative["risk_ids_dual"]},
    }
    schedule_by_scenario = {
        "DP_Review": schedule_results,
        "Dummy_Realistic": schedule_results,
        "All_Series": schedule_results,
    }
    cost_results = {
        "cost_dollars_array": indicative["cost_dollars_array"],
        "per_risk_cost_array": indicative["per_risk_cost_array"],
        "risk_ids": indicative["risk_ids_all"],
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
        "top_3_cost_contributors_cost_only": list(risk_ids),
        "top_3_cost_contributors_integrated": list(risk_ids),
        "top_3_schedule_contributors_sr5": list(risk_ids),
        "top_3_schedule_contributors_integrated": list(risk_ids),
    }

    composed = compose_final_report_data(
        cost_results=cost_results,
        schedule_results=schedule_results,
        integrated_results_by_scenario=by_scenario,
        schedule_results_by_scenario=schedule_by_scenario,
        strawman_path=strawman_path,
        register_path=register_path,
        cross_validation=cv_result,
        risk_titles={r.risk_id: r.description for r in risks},
        risks=risks,
        chart_output_dir=chart_dir,
        programme_duration_days=300.0,
        # Beta-17 SSoT: bypass register read - fixture register file is a
        # text stub, not a real xlsx; pass empty cg_descriptions so the
        # CG drivers table renders "(not in register)" placeholders.
        cg_descriptions={},
        # SR19 §6.2: same text-stub problem for read_methodology_defaults
        # (openpyxl.load_workbook) - explicit config with a test-factory
        # methodology_defaults bypasses that fallback too.
        config=IntegratedConfig(
            register_path=register_path, p6_path=register_path,
            strawman_path=strawman_path,
            methodology_defaults=build_test_methodology_defaults(),
            day_rate=FIXTURE_DAY_RATE,
            random_seed=42,  # the page-7 chart's seed; no default (SEEDZERO-01)
        **TEST_CALIBRATION_TOLERANCES),
    )

    assert "page2_confidence_curve" in composed
    assert "page2_confidence_curve_preamble" in composed
    assert "page2_confidence_curve_footnote" in composed

    curve = composed["page2_confidence_curve"]
    p_rows = [r for r in curve if r.get("confidence_level", "").startswith("P")]
    assert len(p_rows) == 5
    p80 = next(r for r in curve if r["confidence_level"] == "P80")
    assert p80["is_recommended"] is True
