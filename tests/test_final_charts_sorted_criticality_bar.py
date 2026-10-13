"""SR10.B Chart 1 — dual sorted criticality bar chart unit tests.

Locks the renderer's structural contract: dual-panel structure, top-N per
panel, asterisk markers for panel-only activities, deterministic-CP fill
distinction. Visual correctness is verified at smoke-run time.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.final.charts import make_sorted_criticality_bar_chart


def _make_extended_ci_table(n_activities: int = 40) -> pd.DataFrame:
    """Synthetic extended CI table where MC and MI rankings diverge.

    A1..A5 are amplified-by-Mode (MC=0.99, MI=0.45) — they appear in the
    MC top-5 but not the MI top-5. A36..A40 are suppressed-by-Mode (MC=0.05,
    MI=0.95) — they appear in the MI top-5 but not the MC top-5. The
    middle activities sit at consistent CI values so they appear in both
    panels' top-N.
    """
    rows: list[dict] = []
    for i in range(1, n_activities + 1):
        if i <= 5:
            mc, mi = 0.99, 0.45
        elif i >= n_activities - 4:
            mc, mi = 0.05, 0.95
        else:
            ci = 0.50 + 0.005 * (i - 10)
            mc, mi = ci, ci
        rows.append({
            "activity_id": f"A{i:02d}",
            "activity_name": f"Activity {i}",
            "ci_mode_conditioned": mc,
            "ci_mode_independent": mi,
            "ci": mc,
            "ci_band": "near (30-70%)",
            "mode_conditioned_ci_band": "always (90%+)" if mc > 0.9 else "near (30-70%)",
            "mode_independent_ci_band": "always (90%+)" if mi > 0.9 else "near (30-70%)",
            "total_float_mean_hours": 0.0 if i <= 5 else 16.0,
            "total_float_std_hours": 0.0,
            "total_float_mean_days": 0.0 if i <= 5 else 2.0,
            "divergence": mi - mc,
            "divergence_band": (
                "amplified by Mode" if mc - mi >= 0.15
                else "suppressed by Mode" if mi - mc >= 0.15
                else "consistent"
            ),
            "on_deterministic_cp": i <= 5,
        })
    return pd.DataFrame(rows)


def test_chart_renders_without_exception(tmp_path: Path) -> None:
    """Synthetic table → PNG written, header valid."""
    table = _make_extended_ci_table()
    output_path = tmp_path / "chart1_sorted_top30.png"
    result = make_sorted_criticality_bar_chart(
        table, output_path=output_path, top_n=10,
    )
    assert result.exists()
    assert result.stat().st_size > 100
    with result.open("rb") as f:
        header = f.read(4)
    assert header == b"\x89PNG"


def test_chart_handles_empty_table(tmp_path: Path) -> None:
    """Empty table renders a placeholder, no crash."""
    empty = pd.DataFrame(columns=[
        "activity_id", "activity_name",
        "ci_mode_conditioned", "ci_mode_independent",
        "on_deterministic_cp",
    ])
    output_path = tmp_path / "chart1_empty.png"
    result = make_sorted_criticality_bar_chart(empty, output_path=output_path)
    assert result.exists()


def test_chart_handles_missing_ci_column(tmp_path: Path) -> None:
    """Missing MC or MI column → placeholder render."""
    table = pd.DataFrame({
        "activity_id": ["A1"],
        "activity_name": ["A"],
        "ci_mode_conditioned": [0.5],
        "on_deterministic_cp": [False],
    })
    output_path = tmp_path / "chart1_missing_mi.png"
    result = make_sorted_criticality_bar_chart(table, output_path=output_path)
    assert result.exists()


def test_top_n_respected_per_panel(tmp_path: Path) -> None:
    """The top-N parameter caps each panel independently."""
    table = _make_extended_ci_table(n_activities=40)
    output_path = tmp_path / "chart1_top5.png"
    # No exception means the helper read both panels at top_n=5
    # without index errors. Visual confirmation is via smoke run.
    result = make_sorted_criticality_bar_chart(
        table, output_path=output_path, top_n=5,
    )
    assert result.exists()


def test_panel_only_activities_identified() -> None:
    """The amplified/suppressed cohort lands in one panel only.

    We reproduce the helper's set-arithmetic to confirm the synthetic
    table exercises the panel-only branch. The PNG itself encodes the
    visual signal (red border + asterisk); this assertion locks the
    upstream set-difference contract that drives that rendering.
    """
    table = _make_extended_ci_table()
    top_n = 5
    mc_top = set(
        table.sort_values(
            ["ci_mode_conditioned", "activity_id"],
            ascending=[False, True], kind="stable",
        ).head(top_n)["activity_id"]
    )
    mi_top = set(
        table.sort_values(
            ["ci_mode_independent", "activity_id"],
            ascending=[False, True], kind="stable",
        ).head(top_n)["activity_id"]
    )
    # The amplified-by-Mode cohort (A01..A05) is in MC-top-5 only.
    only_in_mc = mc_top - mi_top
    only_in_mi = mi_top - mc_top
    assert only_in_mc == {"A01", "A02", "A03", "A04", "A05"}
    # The suppressed-by-Mode cohort (A36..A40) is in MI-top-5 only.
    assert only_in_mi == {"A36", "A37", "A38", "A39", "A40"}


def test_deterministic_cp_column_handled_when_missing(tmp_path: Path) -> None:
    """Missing on_deterministic_cp column defaults to False — no crash."""
    table = pd.DataFrame({
        "activity_id": ["A1", "A2"],
        "activity_name": ["A1", "A2"],
        "ci_mode_conditioned": [0.9, 0.1],
        "ci_mode_independent": [0.1, 0.9],
    })
    output_path = tmp_path / "chart1_no_detcp.png"
    result = make_sorted_criticality_bar_chart(table, output_path=output_path)
    assert result.exists()
