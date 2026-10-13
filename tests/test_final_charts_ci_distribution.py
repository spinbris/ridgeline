"""Smoke test for SR-S3-Beta-12 CI distribution chart.

Confirms :func:`src.final.charts.make_ci_distribution_chart` writes a
non-empty PNG without exception against a synthetic CI table. Visual
correctness is verified at smoke-run time by the human PM-hat reviewer;
this test only locks the renderer's structural contract.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.final.charts import make_ci_distribution_chart


def _make_synthetic_ci_table(n_per_band: int = 4) -> pd.DataFrame:
    """Synthetic CI table with the same number of activities in each
    of the five reporting bands."""
    bands = [
        ("never (<10%)", 0.05),
        ("rarely (10-30%)", 0.20),
        ("near (30-70%)", 0.50),
        ("often (70-90%)", 0.80),
        ("always (90%+)", 0.95),
    ]
    rows: list[dict] = []
    for band, ci in bands:
        for i in range(n_per_band):
            rows.append({
                "activity_id": f"{band[:5]}_{i}",
                "activity_name": f"{band[:5]}_{i}",
                "ci": ci,
                "ci_band": band,
                "total_float_mean_hours": 0.0,
                "total_float_std_hours": 0.0,
                "on_deterministic_cp": ci > 0.9,
            })
    return pd.DataFrame(rows)


def test_chart_renders_without_exception(tmp_path: Path) -> None:
    """Synthetic CI table → non-empty PNG; no exception raised."""
    ci_table = _make_synthetic_ci_table(n_per_band=4)
    output_path = tmp_path / "ci_distribution.png"

    result = make_ci_distribution_chart(
        ci_table, output_path=output_path, n_iter=100_000,
    )

    assert result.exists()
    # Sanity: PNG header is the first 8 bytes; non-zero file size.
    assert result.stat().st_size > 100
    with result.open("rb") as f:
        header = f.read(8)
    assert header[:4] == b"\x89PNG"


def test_chart_handles_empty_ci_table(tmp_path: Path) -> None:
    """Empty CI table renders a placeholder PNG without exception."""
    empty_table = pd.DataFrame(columns=[
        "activity_id", "activity_name", "ci", "ci_band",
        "total_float_mean_hours", "total_float_std_hours",
        "on_deterministic_cp",
    ])
    output_path = tmp_path / "ci_distribution_empty.png"

    result = make_ci_distribution_chart(empty_table, output_path=output_path)

    assert result.exists()
    assert result.stat().st_size > 100


def test_chart_title_uses_n_iter_when_provided(tmp_path: Path) -> None:
    """When n_iter is supplied, the auto-generated title formats the
    iteration count into the chart title. We can't read text out of a
    PNG without OCR; this test just exercises the title-building branch
    to confirm the call signature accepts n_iter."""
    ci_table = _make_synthetic_ci_table(n_per_band=2)
    output_path = tmp_path / "ci_distribution_with_n_iter.png"
    result = make_ci_distribution_chart(
        ci_table, output_path=output_path, n_iter=50_000,
    )
    assert result.exists()


def test_chart_accepts_explicit_title_override(tmp_path: Path) -> None:
    """Caller-supplied title parameter is accepted (renders without error)."""
    ci_table = _make_synthetic_ci_table(n_per_band=2)
    output_path = tmp_path / "ci_distribution_titled.png"
    result = make_ci_distribution_chart(
        ci_table,
        output_path=output_path,
        title="Custom criticality chart",
    )
    assert result.exists()
