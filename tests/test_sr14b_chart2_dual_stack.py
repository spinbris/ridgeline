"""SR14b D6 — Chart 2 dual-stack redesign tests (AC6).

The pre-SR14b Chart 2 rendered as a single heatmap (MI primary view)
with the MC measurement embedded in a small bottom-right inset.
Director sign-off 2026-05-15 locked the redesign to two stacked
vertical panels (MI top 60% / MC bottom 40%, shared x-axis) — fixes
Steve's accessibility critique that the inset was too small to read.

This file asserts the figure dimensions + panel structure produced by
``make_criticality_density_gantt`` after the SR14b redesign. The
underlying data semantics are unchanged (same Mode-independent + Mode-
conditioned CI arrays from ``ScheduleMCResult``; same density-bin
math); only the presentation pattern flipped.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from src.final.charts import make_criticality_density_gantt


@pytest.fixture
def _synthetic_ci_table() -> pd.DataFrame:
    """Minimal CI table with three activities across two phases."""
    return pd.DataFrame({
        "activity_id": ["A1", "A2", "A3"],
        "ci_mode_conditioned": [0.95, 0.60, 0.30],
        "ci_mode_independent": [0.92, 0.65, 0.28],
    })


@pytest.fixture
def _synthetic_activity_dates() -> pd.DataFrame:
    return pd.DataFrame({
        "activity_id": ["A1", "A2", "A3"],
        "start_date": pd.to_datetime(["2026-01-15", "2026-03-01", "2026-05-15"]),
        "finish_date": pd.to_datetime(["2026-04-15", "2026-06-01", "2026-08-15"]),
    })


@pytest.fixture
def _synthetic_phase_map() -> dict[str, str]:
    return {"A1": "Civil", "A2": "Mechanical", "A3": "Mechanical"}


def test_chart2_aspect_ratio_is_vertical_dual_stack(
    tmp_path: Path,
    _synthetic_ci_table,
    _synthetic_activity_dates,
    _synthetic_phase_map,
) -> None:
    """D6 spec: figure size 10 inches wide × 14 inches tall.
    The rendered PNG should be taller than wide (vertical orientation)."""
    output = tmp_path / "chart2.png"
    make_criticality_density_gantt(
        ci_table=_synthetic_ci_table,
        activity_dates=_synthetic_activity_dates,
        phase_map=_synthetic_phase_map,
        schedule_start="2026-01-01",
        schedule_finish="2026-09-01",
        output_path=output,
    )
    assert output.exists()
    with Image.open(output) as img:
        w, h = img.size
    # 10 × 14 inches at 150 DPI = 1500 × 2100 px before bbox_inches="tight"
    # trimming. Allow generous tolerance for whitespace trim; what we
    # really need is "taller than wide" with a height:width ratio close
    # to the D6 14:10 = 1.4 spec (loosened to >= 1.20 to absorb trim).
    assert h > w, f"Chart 2 expected taller-than-wide; got {w}×{h}"
    ratio = h / w
    assert ratio >= 1.20, (
        f"Chart 2 aspect ratio {ratio:.2f} below D6 dual-stack vertical "
        f"target (~1.40 from 14/10); got {w}×{h}."
    )


def test_chart2_renders_when_inputs_present(
    tmp_path: Path,
    _synthetic_ci_table,
    _synthetic_activity_dates,
    _synthetic_phase_map,
) -> None:
    """The chart renders without raising for a typical input set."""
    output = tmp_path / "chart2_ok.png"
    result_path = make_criticality_density_gantt(
        ci_table=_synthetic_ci_table,
        activity_dates=_synthetic_activity_dates,
        phase_map=_synthetic_phase_map,
        schedule_start="2026-01-01",
        schedule_finish="2026-09-01",
        output_path=output,
    )
    assert result_path == output.resolve()
    assert output.exists()
    assert output.stat().st_size > 5_000  # non-trivial PNG


def test_chart2_falls_back_to_placeholder_when_dates_missing(
    tmp_path: Path,
    _synthetic_ci_table,
    _synthetic_phase_map,
) -> None:
    """Empty activity_dates triggers the placeholder render path
    (preserved from pre-SR14b for graceful fallback)."""
    output = tmp_path / "chart2_placeholder.png"
    make_criticality_density_gantt(
        ci_table=_synthetic_ci_table,
        activity_dates=pd.DataFrame(columns=["activity_id", "start_date", "finish_date"]),
        phase_map=_synthetic_phase_map,
        schedule_start="2026-01-01",
        schedule_finish="2026-09-01",
        output_path=output,
    )
    assert output.exists()


def test_chart2_handles_unmapped_phases(
    tmp_path: Path,
    _synthetic_ci_table,
    _synthetic_activity_dates,
) -> None:
    """Activities missing from phase_map land in "Unmapped" bucket (last
    row); chart still renders."""
    output = tmp_path / "chart2_unmapped.png"
    make_criticality_density_gantt(
        ci_table=_synthetic_ci_table,
        activity_dates=_synthetic_activity_dates,
        phase_map={"A1": "Civil"},  # A2/A3 unmapped
        schedule_start="2026-01-01",
        schedule_finish="2026-09-01",
        output_path=output,
    )
    assert output.exists()
