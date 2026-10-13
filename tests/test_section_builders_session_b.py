"""Unit tests for the SR14a.2 session-B section-builder modules.

Per the SR14a.2 brief AC6 / AC7 — each section-builder is independently
testable from its inputs without invoking the full composer, and the
returned dict-shape is asserted against the docstring contract.

Covers the two sections lifted in session B:

- ``s_curves`` (build_s_curves_section)
- ``criticality`` (build_criticality_section + composer re-exports of
  the eighteen criticality helpers)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.final.sections.criticality import (
    PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS,
    _apply_criticality_keys,
    _apply_stage3_beta_keys,
    _ci_band,
    _compute_path_crossover_delta,
    build_criticality_section,
    build_risk_to_activity_bridge,
    compute_ci_distribution_summary,
    compute_criticality_table,
    pick_near_critical_activities,
)
from src.final.sections.s_curves import (
    _build_confidence_curve,
    build_s_curves_section,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_integrated_arrays(n_iter: int = 500) -> dict:
    rng = np.random.default_rng(0)
    return {
        "cost_dollars_array": rng.uniform(0, 10_000_000, size=n_iter),
        "schedule_days_array": rng.uniform(0, 30, size=n_iter),
    }


# ---------------------------------------------------------------------------
# s_curves
# ---------------------------------------------------------------------------


def test_s_curves_section_contract() -> None:
    """build_s_curves_section returns the documented three keys with
    nested dict shapes matching the composer's expectations."""
    integ = _make_integrated_arrays(n_iter=500)
    by_scenario = {
        "DP_Review": integ, "Dummy_Realistic": integ, "All_Series": integ,
    }
    out = build_s_curves_section(
        integrated_results_by_scenario=by_scenario,
        day_rate=100_000.0,
        p_level=80,
        s_curve_path="/tmp/s_curve.png",
        density_path="/tmp/density.png",
        waterfall_path="/tmp/waterfall.png",
        cost_s_curve_path="/tmp/cost_s.png",
        cost_density_path="/tmp/cost_d.png",
    )
    assert set(out) == {
        "page2_confidence_curve",
        "page2_distribution",
        "page2_cost_distribution",
    }
    # Confidence curve is a list of dicts with the documented keys.
    cc = out["page2_confidence_curve"]
    assert isinstance(cc, list) and len(cc) >= 5
    assert {"confidence_level", "integrated_contingency_m",
            "schedule_slip_days", "above_naive_sum_m"}.issubset(set(cc[0]))
    # P80 row is flagged.
    assert any(row.get("is_p80") for row in cc)
    # Mean row inserted.
    assert any(row.get("is_mean") for row in cc)
    # page2_distribution carries paths + caption.
    assert out["page2_distribution"]["s_curve_path"] == "/tmp/s_curve.png"
    assert out["page2_distribution"]["density_path"] == "/tmp/density.png"
    assert out["page2_distribution"]["waterfall_path"] == "/tmp/waterfall.png"
    assert "$100,000/wd" in out["page2_distribution"]["waterfall_caption"]
    # cost_distribution carries paths only.
    assert out["page2_cost_distribution"]["s_curve_path"] == "/tmp/cost_s.png"
    assert out["page2_cost_distribution"]["density_path"] == "/tmp/cost_d.png"


def test_s_curves_section_empty_arrays_returns_empty_curve() -> None:
    """Empty arrays give an empty confidence curve but the dict shape
    remains stable so downstream renderers' if-guards still fire."""
    empty = {
        "cost_dollars_array": np.array([]),
        "schedule_days_array": np.array([]),
    }
    out = build_s_curves_section(
        integrated_results_by_scenario={
            "DP_Review": empty, "Dummy_Realistic": empty, "All_Series": empty,
        },
        day_rate=100_000.0,
        p_level=80,
    )
    assert out["page2_confidence_curve"] == []
    assert out["page2_distribution"]["s_curve_path"] == ""
    assert out["page2_cost_distribution"]["s_curve_path"] == ""


def test_build_confidence_curve_legacy_helper_parity() -> None:
    """The legacy private helper is preserved; the section-builder wraps
    it without altering its return."""
    integ = _make_integrated_arrays(n_iter=400)
    by_scenario = {"Dummy_Realistic": integ}
    direct = _build_confidence_curve(
        integrated_results_by_scenario=by_scenario,
        day_rate=100_000.0,
        recommended_p_level=80,
    )
    wrapped = build_s_curves_section(
        integrated_results_by_scenario=by_scenario,
        day_rate=100_000.0,
        p_level=80,
    )["page2_confidence_curve"]
    assert direct == wrapped


# ---------------------------------------------------------------------------
# criticality
# ---------------------------------------------------------------------------


def test_criticality_section_none_input_returns_empty_dict() -> None:
    """Stage 2.5 production path passes stage3_beta_result=None and
    must produce no criticality keys (Beta-00 §5 invariant)."""
    out = build_criticality_section(
        integrated_results_by_scenario={},
        stage3_beta_result=None,
    )
    assert out == {}


def test_ci_band_labels_match_definitions() -> None:
    """_ci_band returns the Beta-12 §3.2 band labels for the documented
    CI ranges (never / rarely / near / often / always)."""
    assert _ci_band(0.05) == "never (<10%)"
    assert _ci_band(0.20) == "rarely (10-30%)"
    assert _ci_band(0.50) == "near (30-70%)"
    assert _ci_band(0.80) == "often (70-90%)"
    assert _ci_band(0.95) == "always (90%+)"
    # Edge: exactly 1.0 falls into the "always (90%+)" band by the
    # 1 + 1e-9 upper bound in CI_BAND_DEFINITIONS.
    assert _ci_band(1.0) == "always (90%+)"


def test_path_crossover_default_threshold_constant() -> None:
    """The Stage 3 Beta path-crossover warn threshold default is 30 days
    (PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS)."""
    assert PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS == 30.0


def test_compute_path_crossover_delta_warn_threshold_behaviour() -> None:
    """_compute_path_crossover_delta emits a warn flag when the absolute
    delta exceeds the configured threshold. Stage-2.5 P80 read from
    integrated_results['schedule_days_array']; Stage-3 P80 read from
    stage3_beta_result['schedule_days_array'] - a delay, since STAGE3HEADLINE-01
    D-5 (F-40); before that it read an absolute finish."""
    integ = {"schedule_days_array": np.array([10.0, 12.0, 14.0, 16.0, 18.0])}
    s3_delay = {"schedule_days_array": np.array([100.0, 102.0, 104.0, 106.0, 108.0])}

    s25, s3, delta, warn = _compute_path_crossover_delta(
        integ, s3_delay, threshold_days=10.0,
    )
    # Stage 2.5 P80 ~ 17.6, Stage 3 P80 ~ 107.6 → delta ~ -90, |delta| > 10.
    assert abs(delta) > 10.0
    assert warn is True


def test_composer_reexports_criticality_helpers() -> None:
    """All eighteen criticality helpers + the two constants are
    re-exported from composer.py so legacy test imports still resolve."""
    from src.final import composer

    expected_names = [
        "PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS",
        "_compute_path_crossover_delta",
        "_render_auto_mapper_audit_table",
        "_read_zero_expansion_risk_ids",
        "_build_auto_mapper_zero_expansion_notice",
        "_stage3_beta_unmapped_top_drivers",
        "_apply_stage3_beta_keys",
        "_ci_band",
        "compute_criticality_table",
        "pick_near_critical_activities",
        "build_risk_to_activity_bridge",
        "compute_ci_distribution_summary",
        "compute_extended_ci_table",
        "build_risk_to_cp_linkage_table",
        "_build_activity_dates_from_xer",
        "_build_phase_map_from_xer",
        "_resolve_schedule_window",
        "_render_risk_linkage_table_png",
        "_apply_criticality_keys",
    ]
    for name in expected_names:
        assert hasattr(composer, name), f"composer missing re-export: {name}"


def test_compute_ci_distribution_summary_empty_table() -> None:
    """Empty CI table produces a documented empty summary."""
    out = compute_ci_distribution_summary(pd.DataFrame())
    assert isinstance(out, dict)
    # Empty input still emits a stable dict shape (zero counts).
    assert out.get("n_activities", 0) == 0


def test_pick_near_critical_activities_returns_dataframe() -> None:
    """pick_near_critical_activities filters the CI table by the
    documented [low, high] band on the ``ci`` column, returning a
    DataFrame (possibly empty)."""
    df = pd.DataFrame({
        "activity_id": ["A1", "A2", "A3"],
        "ci": [0.95, 0.80, 0.30],
        "activity_title": ["A1 title", "A2 title", "A3 title"],
    })
    out = pick_near_critical_activities(df)
    assert isinstance(out, pd.DataFrame)
    # Empty input → empty output (preserves DataFrame shape).
    assert isinstance(pick_near_critical_activities(pd.DataFrame()), pd.DataFrame)
