"""SR10.B Chart 3 — risk-to-CP linkage table composer tests.

Locks the contract from brief §4.3:
- One row per Time=Yes risk (zero-bound risks kept with NaN means)
- Columns per spec
- divergence_summary is the median signed divergence
- top_3_activities_by_MI_CI is semicolon-separated, sorted by MI-CI desc
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.final.composer import (
    build_risk_to_cp_linkage_table,
    compute_extended_ci_table,
)


@dataclass
class _FakeScheduleResult:
    """Minimal duck-type matching ScheduleMCResult for unit tests."""

    activity_ids: tuple[str, ...]
    criticality_index: dict[str, float]
    on_critical_path_count: dict[str, int]
    total_float_mean_hours: np.ndarray
    total_float_std_hours: np.ndarray
    deterministic_critical_path: tuple[str, ...]
    mode_independent_criticality_index: dict[str, float] | None
    n_iter: int = 1000


@dataclass(frozen=True)
class _FakeDriver:
    """Minimal duck-type matching RiskDriver for unit tests."""

    affected_activity_ids: tuple[str, ...]
    mode: str = "Series"


def _make_extended_table_two_risks() -> tuple[
    pd.DataFrame, dict[str, _FakeDriver], dict[str, str]
]:
    """Two risks: R013 binds to two activities (one high-MI, one low),
    R067 binds to one zero-divergence activity.

    Activity MI/MC table:
        A1: MC=0.99, MI=0.45 (amplified-by-Mode)
        A2: MC=0.40, MI=0.40 (consistent)
        A3: MC=0.10, MI=0.60 (suppressed-by-Mode)
    """
    activity_ids = ("A1", "A2", "A3")
    mc = {"A1": 0.99, "A2": 0.40, "A3": 0.10}
    mi = {"A1": 0.45, "A2": 0.40, "A3": 0.60}
    fake = _FakeScheduleResult(
        activity_ids=activity_ids,
        criticality_index=mc,
        on_critical_path_count={a: int(c * 1000) for a, c in mc.items()},
        total_float_mean_hours=np.array([0.0, 80.0, 800.0], dtype=np.float32),
        total_float_std_hours=np.array([0.0, 8.0, 16.0], dtype=np.float32),
        deterministic_critical_path=("A1",),
        mode_independent_criticality_index=mi,
    )
    extended = compute_extended_ci_table(
        fake,
        activity_titles={"A1": "GTU Earthing", "A2": "Civil Phase 2",
                          "A3": "Commissioning"},
    )
    drivers = {
        "R013": _FakeDriver(affected_activity_ids=("A1", "A2"), mode="Hybrid"),
        "R067": _FakeDriver(affected_activity_ids=("A2",), mode="Parallel"),
    }
    titles = {"R013": "Civil delay", "R067": "Commissioning rework"}
    return extended, drivers, titles


def test_one_row_per_time_yes_risk() -> None:
    """build_risk_to_cp_linkage_table emits one row per risk passed."""
    extended, drivers, titles = _make_extended_table_two_risks()
    table = build_risk_to_cp_linkage_table(
        drivers, extended, risk_titles=titles,
    )
    assert len(table) == 2
    assert set(table["risk_id"]) == {"R013", "R067"}


def test_columns_per_spec() -> None:
    """All columns from brief §4.3 plus Beta-19b item 3's prob_weighted column."""
    extended, drivers, _ = _make_extended_table_two_risks()
    table = build_risk_to_cp_linkage_table(drivers, extended)
    expected = {
        "risk_id", "risk_title", "mode", "n_activities_bound",
        "top_3_activities_by_MI_CI", "mean_MC_CI_across_bound",
        "mean_MI_CI_across_bound", "divergence_summary",
        # Beta-19b item 3: probability-weighted mean impact column joined
        # from page4_schedule_drivers so Chart 3 and the §10.5 prose rank
        # consistently with §10.4.
        "prob_weighted_mean_days",
        # SR12: per-risk injection-method dispatch surfaced in the §10.5
        # linkage table so a reviewer reads the dispatch choice alongside
        # the Mode-conditioned / Mode-independent CI bands.
        "injection_method",
    }
    assert set(table.columns) == expected


def test_risk_impact_lookup_orders_rows_descending() -> None:
    """When risk_impact_lookup is supplied, rows emit in desc impact order."""
    extended, drivers, titles = _make_extended_table_two_risks()
    # R067 has the higher impact; should appear first when lookup is supplied.
    impact_lookup = {"R013": 1.5, "R067": 12.0}
    table = build_risk_to_cp_linkage_table(
        drivers, extended,
        risk_titles=titles,
        risk_impact_lookup=impact_lookup,
    )
    assert list(table["risk_id"]) == ["R067", "R013"]
    # Column populated.
    by_id = table.set_index("risk_id")
    assert math.isclose(
        float(by_id.loc["R067"]["prob_weighted_mean_days"]), 12.0,
    )
    assert math.isclose(
        float(by_id.loc["R013"]["prob_weighted_mean_days"]), 1.5,
    )


def test_risk_title_falls_back_when_lookup_missing() -> None:
    """risk_title falls back to risk_id when titles dict has no entry."""
    extended, drivers, _ = _make_extended_table_two_risks()
    # No titles passed.
    table = build_risk_to_cp_linkage_table(drivers, extended)
    titles_seen = set(table["risk_title"])
    # Both risks fall back to risk_id.
    assert "R013" in titles_seen
    assert "R067" in titles_seen


def test_risk_title_uses_lookup_when_provided() -> None:
    """Beta-19b item 7a: real risk titles flow through when supplied."""
    extended, drivers, titles = _make_extended_table_two_risks()
    table = build_risk_to_cp_linkage_table(
        drivers, extended, risk_titles=titles,
    )
    by_id = table.set_index("risk_id")
    assert by_id.loc["R013"]["risk_title"] == "Civil delay"
    assert by_id.loc["R067"]["risk_title"] == "Commissioning rework"


def test_divergence_summary_is_median_signed_divergence() -> None:
    """divergence_summary is the median across bound activities, signed."""
    extended, drivers, _ = _make_extended_table_two_risks()
    table = build_risk_to_cp_linkage_table(drivers, extended)
    r013 = table.set_index("risk_id").loc["R013"]
    # R013 binds A1 (div=0.45-0.99=-0.54) and A2 (div=0). Median = -0.27
    # under standard "average of two middle values" definition.
    assert math.isclose(
        float(r013["divergence_summary"]), -0.27, abs_tol=1e-6,
    )


def test_top_n_activities_by_MI_CI_sorted_desc() -> None:
    """Top-N string ranks activities by MI CI descending."""
    extended, drivers, _ = _make_extended_table_two_risks()
    table = build_risk_to_cp_linkage_table(drivers, extended)
    r013 = table.set_index("risk_id").loc["R013"]
    top = r013["top_3_activities_by_MI_CI"]
    # A1 (MI 0.45) > A2 (MI 0.40), so A1 must appear before A2 in the
    # semicolon-separated list.
    assert "A1" in top
    assert "A2" in top
    assert top.index("A1") < top.index("A2")


def test_top_n_string_format_includes_MI_CI_pct() -> None:
    """Format is ``activity_id|activity_name (MI-CI %)`` per piece."""
    extended, drivers, _ = _make_extended_table_two_risks()
    table = build_risk_to_cp_linkage_table(drivers, extended)
    r013 = table.set_index("risk_id").loc["R013"]
    top = r013["top_3_activities_by_MI_CI"]
    # MI for A1 = 0.45 → "MI-CI 45%"
    assert "MI-CI 45%" in top


def test_zero_bound_risk_kept_with_nan_means() -> None:
    """Zero-bound risk surfaces a row with NaN means + empty top-N."""
    extended, drivers, _ = _make_extended_table_two_risks()
    drivers["R999"] = _FakeDriver(affected_activity_ids=(), mode="Series")
    table = build_risk_to_cp_linkage_table(drivers, extended)
    r999 = table.set_index("risk_id").loc["R999"]
    assert int(r999["n_activities_bound"]) == 0
    assert r999["top_3_activities_by_MI_CI"] == ""
    assert math.isnan(float(r999["mean_MC_CI_across_bound"]))
    assert math.isnan(float(r999["mean_MI_CI_across_bound"]))
    assert math.isnan(float(r999["divergence_summary"]))


def test_mode_column_reflects_driver_mode() -> None:
    """The mode column comes from RiskDriver.mode."""
    extended, drivers, _ = _make_extended_table_two_risks()
    table = build_risk_to_cp_linkage_table(drivers, extended)
    table_by_id = table.set_index("risk_id")
    assert table_by_id.loc["R013"]["mode"] == "Hybrid"
    assert table_by_id.loc["R067"]["mode"] == "Parallel"


def test_extended_ci_table_carries_dual_ci_and_divergence() -> None:
    """compute_extended_ci_table joins MI CI + divergence + band columns."""
    extended, _, _ = _make_extended_table_two_risks()
    expected_cols = {
        "ci_mode_conditioned", "ci_mode_independent",
        "mode_conditioned_ci_band", "mode_independent_ci_band",
        "divergence", "divergence_band", "total_float_mean_days",
    }
    assert expected_cols.issubset(set(extended.columns))
    # A1: MC=0.99, MI=0.45 → divergence -0.54 → amplified by Mode.
    a1 = extended.set_index("activity_id").loc["A1"]
    assert math.isclose(float(a1["divergence"]), -0.54, abs_tol=1e-9)
    assert a1["divergence_band"] == "amplified by Mode"


def test_extended_table_total_float_mean_days_conversion() -> None:
    """total_float_mean_days = hours / 8 (RefProject default)."""
    extended, _, _ = _make_extended_table_two_risks()
    a2 = extended.set_index("activity_id").loc["A2"]
    assert math.isclose(float(a2["total_float_mean_days"]), 10.0, abs_tol=1e-6)


def test_extended_table_falls_back_when_MI_is_None() -> None:
    """Legacy mode_conditioned-only runs: MI mirrors MC (no divergence)."""
    activity_ids = ("X1",)
    mc = {"X1": 0.6}
    fake = _FakeScheduleResult(
        activity_ids=activity_ids,
        criticality_index=mc,
        on_critical_path_count={"X1": 600},
        total_float_mean_hours=np.array([16.0], dtype=np.float32),
        total_float_std_hours=np.array([0.0], dtype=np.float32),
        deterministic_critical_path=(),
        mode_independent_criticality_index=None,
    )
    extended = compute_extended_ci_table(fake)
    x1 = extended.set_index("activity_id").loc["X1"]
    assert float(x1["ci_mode_conditioned"]) == 0.6
    assert float(x1["ci_mode_independent"]) == 0.6
    assert float(x1["divergence"]) == 0.0
    assert x1["divergence_band"] == "consistent"
