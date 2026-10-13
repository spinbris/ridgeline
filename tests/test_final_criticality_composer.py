"""Tests for SR-S3-Beta-12 composer aggregation helpers.

Covers:

* :func:`src.final.composer.compute_criticality_table` — band assignment,
  schema, deterministic-CP membership flag.
* :func:`src.final.composer.pick_near_critical_activities` — band filter,
  sort order, top-N cap.
* :func:`src.final.composer.build_risk_to_activity_bridge` — join
  correctness, zero-expansion placeholder, top-N-per-risk cap.
* :func:`src.final.composer.compute_ci_distribution_summary` — band
  counts, percentages, shape classifier across the four named patterns.

All tests build a synthetic minimal "ScheduleMCResult-like" object so
they do not depend on an end-to-end run. The SimpleNamespace stand-in
has the same attribute surface the composer reads.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.final.composer import (
    build_risk_to_activity_bridge,
    compute_ci_distribution_summary,
    compute_criticality_table,
    pick_near_critical_activities,
)


def _make_schedule_result_stub(
    activity_ids: tuple[str, ...],
    ci_values: dict[str, float],
    *,
    tf_mean: list[float] | None = None,
    tf_std: list[float] | None = None,
    deterministic_cp: tuple[str, ...] = (),
    n_iter: int = 1000,
) -> SimpleNamespace:
    """Construct a minimal ScheduleMCResult-shaped stub for the composer."""
    n = len(activity_ids)
    if tf_mean is None:
        tf_mean = [0.0] * n
    if tf_std is None:
        tf_std = [0.0] * n
    return SimpleNamespace(
        activity_ids=activity_ids,
        criticality_index=ci_values,
        total_float_mean_hours=np.array(tf_mean, dtype=np.float32),
        total_float_std_hours=np.array(tf_std, dtype=np.float32),
        deterministic_critical_path=deterministic_cp,
        n_iter=n_iter,
    )


def _make_driver_stub(
    risk_id: str, affected: tuple[str, ...]
) -> SimpleNamespace:
    return SimpleNamespace(
        risk_id=risk_id,
        affected_activity_ids=affected,
    )


# ---------------------------------------------------------------------------
# compute_criticality_table
# ---------------------------------------------------------------------------

def test_compute_criticality_table_band_assignment() -> None:
    """Synthetic CIs covering all five bands map to the expected band labels."""
    activity_ids = ("a1", "a2", "a3", "a4", "a5")
    ci_values = {
        "a1": 0.05,   # never (<10%)
        "a2": 0.20,   # rarely (10-30%)
        "a3": 0.50,   # near (30-70%)
        "a4": 0.80,   # often (70-90%)
        "a5": 0.95,   # always (90%+)
    }
    sched = _make_schedule_result_stub(
        activity_ids,
        ci_values,
        tf_mean=[100.0, 50.0, 30.0, 10.0, 0.0],
        tf_std=[5.0, 4.0, 3.0, 2.0, 1.0],
        deterministic_cp=("a5",),
    )
    titles = {"a3": "Near-critical activity"}
    table = compute_criticality_table(sched, activity_titles=titles)

    assert list(table.columns) == [
        "activity_id", "activity_name", "ci", "ci_band",
        "total_float_mean_hours", "total_float_std_hours",
        "on_deterministic_cp",
    ]
    assert len(table) == 5

    band_lookup = dict(zip(table["activity_id"], table["ci_band"]))
    assert band_lookup["a1"] == "never (<10%)"
    assert band_lookup["a2"] == "rarely (10-30%)"
    assert band_lookup["a3"] == "near (30-70%)"
    assert band_lookup["a4"] == "often (70-90%)"
    assert band_lookup["a5"] == "always (90%+)"

    # Activity title applied where supplied; falls back to id otherwise.
    name_lookup = dict(zip(table["activity_id"], table["activity_name"]))
    assert name_lookup["a3"] == "Near-critical activity"
    assert name_lookup["a1"] == "a1"

    # Deterministic-CP membership flagged correctly.
    cp_lookup = dict(zip(table["activity_id"], table["on_deterministic_cp"]))
    assert cp_lookup["a5"] is True
    assert cp_lookup["a1"] is False


def test_compute_criticality_table_empty_result_returns_empty_frame() -> None:
    """Schedule result with zero activities returns an empty DataFrame
    with the correct column schema (downstream consumers index by name)."""
    sched = _make_schedule_result_stub((), {})
    table = compute_criticality_table(sched)
    assert table.empty
    assert list(table.columns) == [
        "activity_id", "activity_name", "ci", "ci_band",
        "total_float_mean_hours", "total_float_std_hours",
        "on_deterministic_cp",
    ]


# ---------------------------------------------------------------------------
# pick_near_critical_activities
# ---------------------------------------------------------------------------

def test_pick_near_critical_respects_top_n_and_band() -> None:
    """Picker returns only [low, high] band activities, sorted by ci desc,
    capped at top_n.

    Setup: 20 activities spread evenly across CI ∈ [0, 1). Default
    [0.20, 0.80] band catches 12 of them; default top_n=10 caps at 10.
    """
    activity_ids = tuple(f"a{i:02d}" for i in range(20))
    # CI = 0.0, 0.05, 0.10, ..., 0.95
    ci_values = {a: i * 0.05 for i, a in enumerate(activity_ids)}
    sched = _make_schedule_result_stub(activity_ids, ci_values)
    table = compute_criticality_table(sched)

    near = pick_near_critical_activities(table)
    # Default: low=0.20, high=0.80, top_n=10
    # Activities with CI in [0.20, 0.80] are i=4..16 (CI 0.20 to 0.80)
    assert len(near) == 10  # capped at top_n
    # Sorted descending by CI.
    assert list(near["ci"]) == sorted(near["ci"], reverse=True)
    # Highest CI in the picker output is at most 0.80.
    assert near["ci"].max() <= 0.80
    # Lowest CI in the picker output is at least 0.20.
    assert near["ci"].min() >= 0.20


def test_pick_near_critical_with_custom_band_and_no_results() -> None:
    """Custom band that excludes every activity returns an empty frame."""
    activity_ids = ("a1", "a2", "a3")
    ci_values = {"a1": 0.0, "a2": 0.0, "a3": 0.0}
    sched = _make_schedule_result_stub(activity_ids, ci_values)
    table = compute_criticality_table(sched)
    near = pick_near_critical_activities(table, low=0.50, high=0.95)
    assert near.empty


# ---------------------------------------------------------------------------
# build_risk_to_activity_bridge
# ---------------------------------------------------------------------------

def test_build_risk_to_activity_bridge_joins_correctly() -> None:
    """Bridge emits one row per (risk, affected activity); CI / CP-flag
    are joined from the CI table; rows sorted by CI desc within each
    risk group; capped at top_n_activities_per_risk.
    """
    activity_ids = ("a1", "a2", "a3", "a4", "a5", "a6")
    ci_values = {
        "a1": 0.95, "a2": 0.50, "a3": 0.10,
        "a4": 0.85, "a5": 0.30, "a6": 0.05,
    }
    sched = _make_schedule_result_stub(
        activity_ids, ci_values, deterministic_cp=("a1", "a4"),
    )
    table = compute_criticality_table(sched)

    risk_drivers = {
        "R001": _make_driver_stub("R001", ("a1", "a2", "a3", "a5")),
        "R002": _make_driver_stub("R002", ("a4",)),
        "R003": _make_driver_stub("R003", ()),  # zero expansion
    }
    bridge = build_risk_to_activity_bridge(
        risk_drivers,
        table,
        ["R001", "R002", "R003"],
        risk_titles={"R001": "Risk one"},
        top_n_activities_per_risk=3,
    )

    # R001 has 4 affected → top-3 by CI desc → a1 (0.95), a2 (0.50), a5 (0.30)
    r001_rows = bridge[bridge["risk_id"] == "R001"]
    assert len(r001_rows) == 3
    assert list(r001_rows["activity_id"]) == ["a1", "a2", "a5"]
    assert list(r001_rows["ci"]) == [0.95, 0.50, 0.30]
    # Title resolved from risk_titles.
    assert r001_rows["risk_title"].iloc[0] == "Risk one"
    # on_deterministic_cp flag joined correctly. (Use == not `is` —
    # pandas returns numpy.bool_, not Python bool, so identity fails.)
    assert bool(r001_rows.iloc[0]["on_deterministic_cp"]) is True   # a1
    assert bool(r001_rows.iloc[1]["on_deterministic_cp"]) is False  # a2

    # R002 has one activity → one row.
    r002_rows = bridge[bridge["risk_id"] == "R002"]
    assert len(r002_rows) == 1
    assert r002_rows.iloc[0]["activity_id"] == "a4"

    # R003 has zero activities → placeholder row with no_activity_bindings flag.
    r003_rows = bridge[bridge["risk_id"] == "R003"]
    assert len(r003_rows) == 1
    assert r003_rows.iloc[0]["activity_id"] == ""
    assert bool(r003_rows.iloc[0]["no_activity_bindings"]) is True
    # Title falls back to risk_id when not in risk_titles dict.
    assert r003_rows.iloc[0]["risk_title"] == "R003"


def test_build_risk_to_activity_bridge_handles_empty_inputs() -> None:
    """Empty top_3 list, empty CI table, or both produce an empty
    DataFrame with the correct column schema."""
    expected_cols = [
        "risk_id", "risk_title", "activity_id", "activity_name",
        "ci", "on_deterministic_cp", "no_activity_bindings",
    ]
    sched = _make_schedule_result_stub(("a1",), {"a1": 0.5})
    table = compute_criticality_table(sched)

    # Empty top_3 list.
    bridge = build_risk_to_activity_bridge({}, table, [])
    assert bridge.empty
    assert list(bridge.columns) == expected_cols

    # Empty CI table.
    empty_table = pd.DataFrame(columns=table.columns)
    bridge = build_risk_to_activity_bridge({"R001": _make_driver_stub("R001", ("a1",))}, empty_table, ["R001"])
    assert bridge.empty
    assert list(bridge.columns) == expected_cols


# ---------------------------------------------------------------------------
# compute_ci_distribution_summary — shape classification
# ---------------------------------------------------------------------------

def _build_table_from_ci_list(cis: list[float]) -> pd.DataFrame:
    """Build a CI table from a flat list of CI values."""
    activity_ids = tuple(f"a{i:03d}" for i in range(len(cis)))
    ci_values = dict(zip(activity_ids, cis))
    sched = _make_schedule_result_stub(activity_ids, ci_values)
    return compute_criticality_table(sched)


def test_compute_ci_distribution_summary_bimodal() -> None:
    """50% of activities at CI=1.0 and 50% at CI=0.0 → bimodal."""
    cis = [1.0] * 5 + [0.0] * 5
    table = _build_table_from_ci_list(cis)
    summary = compute_ci_distribution_summary(table)
    assert summary["shape_indicator"] == "bimodal"
    assert summary["n_activities_total"] == 10
    assert summary["band_pcts"]["always (90%+)"] == 0.5
    assert summary["band_pcts"]["never (<10%)"] == 0.5


def test_compute_ci_distribution_summary_stable_cp() -> None:
    """Most activities high (≥30% in always); recognisable core path."""
    cis = [0.95] * 4 + [0.50] * 3 + [0.20] * 3
    table = _build_table_from_ci_list(cis)
    summary = compute_ci_distribution_summary(table)
    assert summary["shape_indicator"] == "stable_cp"


def test_compute_ci_distribution_summary_shifty() -> None:
    """Bulk in middle band (≥50% in 10-90%); no core path."""
    # 8 of 10 activities in the near band (0.40-0.60); 2 at extremes.
    cis = [0.40, 0.45, 0.50, 0.55, 0.60, 0.40, 0.45, 0.50, 0.95, 0.05]
    table = _build_table_from_ci_list(cis)
    summary = compute_ci_distribution_summary(table)
    assert summary["shape_indicator"] == "shifty"


def test_compute_ci_distribution_summary_uniform_low() -> None:
    """Most activities at low CI; schedule has slack."""
    # 8 of 10 at CI 0.05 (never band); 2 at near band.
    cis = [0.05] * 8 + [0.50, 0.55]
    table = _build_table_from_ci_list(cis)
    summary = compute_ci_distribution_summary(table)
    assert summary["shape_indicator"] == "uniform_low"
    assert summary["band_pcts"]["never (<10%)"] >= 0.6


def test_compute_ci_distribution_summary_empty_table() -> None:
    """Empty CI table returns zero counts and shifty fallback."""
    empty_table = pd.DataFrame(columns=[
        "activity_id", "activity_name", "ci", "ci_band",
        "total_float_mean_hours", "total_float_std_hours",
        "on_deterministic_cp",
    ])
    summary = compute_ci_distribution_summary(empty_table)
    assert summary["n_activities_total"] == 0
    assert summary["shape_indicator"] == "shifty"
    assert all(c == 0 for c in summary["band_counts"].values())
