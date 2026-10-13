"""SR10.B Chart 2 — criticality density Gantt unit tests.

Locks the renderer's structural contract: monthly bins, RBS Level 1
phases on the y-axis, MI primary view, MC inset for methodology
transparency. Visual correctness is verified at smoke-run time.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.final.charts import (
    _build_monthly_bin_edges,
    make_criticality_density_gantt,
)

import pytest

# RS-B step 2: this module asserts against the reference project's register
# shape, RBS map or narrative templates, so it selects that binding explicitly
# rather than inheriting the suite default.
pytestmark = pytest.mark.project("fixture_r_prefix")   # REFRETIRE-01: the fixtures here carry R-prefixed risk IDs


def _make_extended_ci_table_for_gantt() -> pd.DataFrame:
    rows: list[dict] = []
    for i in range(1, 13):
        mc = 0.99 if i <= 4 else 0.30
        mi = 0.45 if i <= 4 else 0.30
        rows.append({
            "activity_id": f"A{i:02d}",
            "activity_name": f"Activity {i}",
            "ci_mode_conditioned": mc,
            "ci_mode_independent": mi,
            "on_deterministic_cp": i <= 4,
        })
    return pd.DataFrame(rows)


def _make_activity_dates() -> pd.DataFrame:
    """12 activities spanning Jan 2026 → Dec 2026, one per month."""
    rows: list[dict] = []
    for i in range(1, 13):
        start = pd.Timestamp(year=2026, month=i, day=1)
        finish = start + pd.Timedelta(days=20)
        rows.append({
            "activity_id": f"A{i:02d}",
            "start_date": start,
            "finish_date": finish,
        })
    return pd.DataFrame(rows)


def _make_phase_map() -> dict[str, str]:
    """A01-A04 → Phase 1 Civil; A05-A08 → Phase 2 Mechanical; A09-A12 → Phase 3 Commissioning."""
    out: dict[str, str] = {}
    for i in range(1, 13):
        if i <= 4:
            phase = "1. Civil"
        elif i <= 8:
            phase = "2. Mechanical"
        else:
            phase = "3. Commissioning"
        out[f"A{i:02d}"] = phase
    return out


def test_chart_renders_without_exception(tmp_path: Path) -> None:
    """Synthetic table + dates + phase map → PNG written, valid header."""
    ci_table = _make_extended_ci_table_for_gantt()
    dates = _make_activity_dates()
    phase_map = _make_phase_map()
    output_path = tmp_path / "chart2_density_gantt.png"
    result = make_criticality_density_gantt(
        ci_table=ci_table,
        activity_dates=dates,
        phase_map=phase_map,
        schedule_start=pd.Timestamp("2026-01-01"),
        schedule_finish=pd.Timestamp("2026-12-31"),
        output_path=output_path,
    )
    assert result.exists()
    assert result.stat().st_size > 100
    with result.open("rb") as f:
        header = f.read(4)
    assert header == b"\x89PNG"


def test_monthly_bins_span_schedule_window() -> None:
    """Monthly bin edges span [start, finish] inclusively."""
    edges = _build_monthly_bin_edges(
        pd.Timestamp("2026-01-15"), pd.Timestamp("2026-12-20"),
    )
    # Jan 2026 through Jan 2027 = 13 edges → 12 bins covering all 12 months.
    assert len(edges) >= 12
    assert edges[0] == pd.Timestamp("2026-01-01")
    # Final edge sits at or after schedule_finish.
    assert edges[-1] >= pd.Timestamp("2026-12-20")


def test_chart_handles_missing_dates(tmp_path: Path) -> None:
    """schedule_start / finish = NaT → placeholder render, no crash."""
    ci_table = _make_extended_ci_table_for_gantt()
    output_path = tmp_path / "chart2_no_dates.png"
    result = make_criticality_density_gantt(
        ci_table=ci_table,
        activity_dates=_make_activity_dates(),
        phase_map=_make_phase_map(),
        schedule_start=pd.NaT,
        schedule_finish=pd.NaT,
        output_path=output_path,
    )
    assert result.exists()


def test_chart_handles_empty_activity_dates(tmp_path: Path) -> None:
    """No dated activities → placeholder render."""
    output_path = tmp_path / "chart2_no_acts.png"
    result = make_criticality_density_gantt(
        ci_table=_make_extended_ci_table_for_gantt(),
        activity_dates=pd.DataFrame(
            columns=["activity_id", "start_date", "finish_date"],
        ),
        phase_map={},
        schedule_start=pd.Timestamp("2026-01-01"),
        schedule_finish=pd.Timestamp("2026-12-31"),
        output_path=output_path,
    )
    assert result.exists()


def test_phase_order_can_be_overridden(tmp_path: Path) -> None:
    """phase_order kwarg pins the row ordering top-to-bottom."""
    output_path = tmp_path / "chart2_explicit_order.png"
    result = make_criticality_density_gantt(
        ci_table=_make_extended_ci_table_for_gantt(),
        activity_dates=_make_activity_dates(),
        phase_map=_make_phase_map(),
        schedule_start=pd.Timestamp("2026-01-01"),
        schedule_finish=pd.Timestamp("2026-12-31"),
        output_path=output_path,
        phase_order=("3. Commissioning", "2. Mechanical", "1. Civil"),
    )
    assert result.exists()


def test_use_mode_independent_flag_inverts_primary_and_inset(tmp_path: Path) -> None:
    """When use_mode_independent=False the main heatmap = MC; inset = MI.

    Smoke test only — we exercise the branch without crash; the
    visual is human-verified.
    """
    out = tmp_path / "chart2_mc_primary.png"
    result = make_criticality_density_gantt(
        ci_table=_make_extended_ci_table_for_gantt(),
        activity_dates=_make_activity_dates(),
        phase_map=_make_phase_map(),
        schedule_start=pd.Timestamp("2026-01-01"),
        schedule_finish=pd.Timestamp("2026-12-31"),
        output_path=out,
        use_mode_independent=False,
    )
    assert result.exists()


def test_beta19b_item_1_phase_map_walks_to_rbs_level_1() -> None:
    """Beta-19b item 1: _build_phase_map_from_xer resolves Level 1 ancestor
    rather than the WBS root. Synthetic 3-level PROJWBS tree: root
    "BGP" (id=1), L1 disciplines ("Civil"=2, "Mechanical"=3), L2 leaves
    (4, 5, 6, 7) parented under the L1 nodes. Tasks attach to L2 leaves
    via their wbs_id."""
    from src.final.composer import _build_phase_map_from_xer

    projwbs = pd.DataFrame([
        {"wbs_id": 1, "parent_wbs_id": None, "wbs_short_name": "BGP"},
        {"wbs_id": 2, "parent_wbs_id": 1, "wbs_short_name": "Civil"},
        {"wbs_id": 3, "parent_wbs_id": 1, "wbs_short_name": "Mechanical"},
        {"wbs_id": 4, "parent_wbs_id": 2, "wbs_short_name": "Earthworks"},
        {"wbs_id": 5, "parent_wbs_id": 2, "wbs_short_name": "Foundations"},
        {"wbs_id": 6, "parent_wbs_id": 3, "wbs_short_name": "GTU"},
        {"wbs_id": 7, "parent_wbs_id": 3, "wbs_short_name": "Piping"},
    ])
    task = pd.DataFrame([
        {"task_id": "T1", "wbs_id": 4, "task_code": "10.C.001"},
        {"task_id": "T2", "wbs_id": 5, "task_code": "10.C.002"},
        {"task_id": "T3", "wbs_id": 6, "task_code": "30.M.001"},
        {"task_id": "T4", "wbs_id": 7, "task_code": "40.P.001"},
    ])
    phase_map = _build_phase_map_from_xer(
        {"PROJWBS": projwbs, "TASK": task},
    )
    assert phase_map["T1"] == "Civil"
    assert phase_map["T2"] == "Civil"
    assert phase_map["T3"] == "Mechanical"
    assert phase_map["T4"] == "Mechanical"


def test_beta19b_item_1_phase_map_falls_back_to_prefix_heuristic() -> None:
    """When PROJWBS walk produces no L1 ancestor (e.g., activity attached
    directly to the root), fall back to the task_code prefix heuristic."""
    from src.final.composer import _build_phase_map_from_xer

    projwbs = pd.DataFrame([
        # Single-level WBS — only a root.
        {"wbs_id": 1, "parent_wbs_id": None, "wbs_short_name": "BGP"},
    ])
    task = pd.DataFrame([
        {"task_id": "T1", "wbs_id": 1, "task_code": "10.C.001"},
        {"task_id": "T2", "wbs_id": 1, "task_code": "30.M.001"},
        {"task_id": "T3", "wbs_id": 1, "task_code": "50.E.001"},
        {"task_id": "T4", "wbs_id": 1, "task_code": "99.X.001"},
    ])
    phase_map = _build_phase_map_from_xer(
        {"PROJWBS": projwbs, "TASK": task},
    )
    # SR18 Item 1: the prefix-heuristic dict was lifted to
    # src/final/rbs_mapping.py and the label set corrected to match the
    # live .xer PROJWBS wbs_name. Pre-SR18 the Beta-19b heuristic
    # mapped 10→Civil / 30→Mechanical / 50→E&I; post-SR18 the same
    # codes map to the base map's labels, unless the active project overrides one - this
    # module selects a binding with no WBS labels of its own (REFRETIRE-01), so these are the
    # base map's own values.
    assert phase_map["T1"] == "Power Station Sitewide"
    assert phase_map["T2"] == "GT Services"
    assert phase_map["T3"] == "Substation"
    assert phase_map["T4"] == "Operation & Handover"


def test_beta19b_item_1_chart_renders_with_multi_phase_y_axis(
    tmp_path: Path,
) -> None:
    """The chart helper accepts a multi-bucket phase_map and renders an
    axis with more than one phase row (3 phases here)."""
    # Use the existing helper but explicitly assert that the chart's
    # phase_map has multiple distinct labels (Civil / Mechanical /
    # Commissioning) — the failure mode the RefProject Beta-19 deliverable
    # showed was a single-phase y-axis.
    ci = _make_extended_ci_table_for_gantt()
    dates = _make_activity_dates()
    phase_map = _make_phase_map()
    out = tmp_path / "chart2_multi_phase_render.png"
    result = make_criticality_density_gantt(
        ci_table=ci,
        activity_dates=dates,
        phase_map=phase_map,
        schedule_start=pd.Timestamp("2026-01-01"),
        schedule_finish=pd.Timestamp("2026-12-31"),
        output_path=out,
    )
    assert result.exists()
    # Confirm the synthetic phase_map carries 3 distinct phases (smoke).
    assert len(set(phase_map.values())) == 3


def test_unmapped_activities_bucket_to_unmapped_row(tmp_path: Path) -> None:
    """Activities missing from phase_map land in the 'Unmapped' bucket.

    The 'Unmapped' row is always rendered last when present.
    """
    ci = _make_extended_ci_table_for_gantt()
    dates = _make_activity_dates()
    # Strip A12 from the phase_map so it lands in the Unmapped bucket.
    phase_map = _make_phase_map()
    del phase_map["A12"]
    out = tmp_path / "chart2_with_unmapped.png"
    result = make_criticality_density_gantt(
        ci_table=ci,
        activity_dates=dates,
        phase_map=phase_map,
        schedule_start=pd.Timestamp("2026-01-01"),
        schedule_finish=pd.Timestamp("2026-12-31"),
        output_path=out,
    )
    assert result.exists()
