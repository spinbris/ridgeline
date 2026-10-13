"""SR11 — Stage 3 Beta sibling deliverable composer + renderer tests.

Covers:

* Page 1 table assembly — 5 rows × 3 numeric columns; correct $-format;
  diversification sign rendering.
* build_stage3_beta_composed produces all expected top-level keys.
* HTML renderer writes a file with preview banner on every page section.
* docx renderer writes a non-empty file with preview banner present.
* Filename pattern resolver.
* Cover-page caveat references the mapping reasonableness review path.
"""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

import os
from pathlib import Path

import numpy as np
import pytest

# RS-B step 4: imported as a MODULE, not `from ... import _s3br.COVER_PAGE_CAVEAT_TEXT`.
# That constant is resolved from the active binding by a module __getattr__, and
# `from X import Y` binds ONCE at import time - so the from-form captures whichever
# project was active during collection and no per-test selection can reach it. The
# __getattr__ gives lazy resolution, not dynamic re-resolution, and its docstring's
# claim that it keeps the from-form working held only while one project existed.
from src.final import stage3_beta_report as _s3br
from src.final.stage3_beta_report import (
    build_page1_stage3_beta_table,
    build_stage3_beta_composed,
    generate_stage3_beta_report_docx,
    render_stage3_beta_report_html,
    resolve_sibling_filename,
)
from src.integrated.integrated_simulation_stage3 import Stage3IntegratedResult



# ---------------------------------------------------------------------------
# Synthetic result builder
# ---------------------------------------------------------------------------

def _make_synthetic_result(
    *,
    iterations: int = 1000,
    cost_p80_dollars: float = 12_500_000.0,
    schedule_p80_days: float = 50.0,
    schedule_baseline_days: float = 0.0,
    variant_label: str = "Hybrid",
) -> Stage3IntegratedResult:
    """Build a Stage3IntegratedResult with controlled distribution shape."""
    rng = np.random.default_rng(42)
    # Cost: lognormal-ish around the target P80.
    cost_arr = rng.uniform(0, cost_p80_dollars * 1.5, size=iterations)
    # Schedule: uniform [0, p80*1.5]
    sched_arr = rng.uniform(
        schedule_baseline_days,
        schedule_baseline_days + schedule_p80_days * 1.5,
        size=iterations,
    )
    # Use a minimal mock for the cost_result dict
    cost_result = {
        "cost_dollars_array": cost_arr,
        "schedule_days_array": np.zeros(iterations),
        "per_risk_cost_array": cost_arr.reshape(-1, 1),
        "per_risk_schedule_array": np.zeros((iterations, 0)),
        "risk_ids_all": ["R001"],
        "risk_ids_dual": [],
        "iterations": iterations,
        "fired_array": (cost_arr > 0).reshape(-1, 1),
    }

    class _ScheduleStub:
        beta_flag = True
        project_finish_days = sched_arr
        n_iter = iterations

    return Stage3IntegratedResult(
        cost_result=cost_result,
        schedule_result=_ScheduleStub(),
        schedule_days_array=sched_arr,
        severity_uniforms_by_risk_id={},
        risk_drivers={},
        schedule_graph=None,
        xer_tables={},
        auto_mapper_audit_path=None,
        beta_flag=True,
        iterations=iterations,
        seed_used=42,
        variant_label=variant_label,
        config_summary={"criticality_measurement_mode": "mode_conditioned"},
    )


# ---------------------------------------------------------------------------
# Test 14 — Page 1 table has 5 rows
# ---------------------------------------------------------------------------

def test_page1_table_has_five_rows():
    result = _make_synthetic_result()
    table = build_page1_stage3_beta_table(result, day_rate=100_000.0)
    assert len(table) == 5
    components = [row["Component"] for row in table]
    assert components == [
        "Cost contingency",
        "Schedule contingency (dollarised)",
        "Naive sum",
        "Diversification effect",
        "Integrated total",
    ]


# ---------------------------------------------------------------------------
# Test 15 — Page 1 table columns are correct
# ---------------------------------------------------------------------------

def test_page1_table_has_correct_columns():
    result = _make_synthetic_result()
    table = build_page1_stage3_beta_table(result, day_rate=100_000.0)
    required_cols = {"Component", "P80", "Mean", "Value", "Notes"}
    for row in table:
        assert required_cols.issubset(set(row.keys()))
        # Numeric columns are $-formatted strings
        for c in ("P80", "Mean", "Value"):
            assert isinstance(row[c], str)
            assert "$" in row[c] and "M" in row[c]


# ---------------------------------------------------------------------------
# Test 16 — Diversification line carries signed format
# ---------------------------------------------------------------------------

def test_diversification_line_has_signed_format():
    result = _make_synthetic_result()
    table = build_page1_stage3_beta_table(result, day_rate=100_000.0)
    div_row = next(r for r in table if r["Component"] == "Diversification effect")
    # Must start with +$ or -$
    assert div_row["P80"][0] in ("+", "-")
    assert div_row["Mean"][0] in ("+", "-")


# ---------------------------------------------------------------------------
# Test 17 — composer produces all required top-level keys
# ---------------------------------------------------------------------------

def test_composer_produces_required_keys():
    result = _make_synthetic_result()
    composed = build_stage3_beta_composed(
        result, day_rate=100_000.0, run_date="2026-05-14",
    calibration_tolerances=TEST_CALIBRATION_TOLERANCES)
    required = {
        "preview_banner", "cover_caveat", "run_date", "variant_label",
        "iterations", "seed_used", "page1_table", "headline",
        "methodology_summary", "cost_summary", "schedule_summary",
        "audit_trail", "beta_flag",
    }
    assert required.issubset(set(composed.keys()))
    assert composed["preview_banner"] == _s3br.PREVIEW_BANNER_TEXT
    assert composed["cover_caveat"] == _s3br.COVER_PAGE_CAVEAT_TEXT
    assert composed["run_date"] == "2026-05-14"


# REFRETIRE-01 (D-2): the test that stood here pinned the retired binding's own
# narrative verbatim - text that lived in that binding and retired with it. The generic
# fallback these resolvers now return is asserted where it is defined.


# ---------------------------------------------------------------------------
# Test 20 — HTML renderer writes file with banner on every section
# ---------------------------------------------------------------------------

def test_html_renderer_writes_file_with_banners(tmp_path: Path):
    result = _make_synthetic_result()
    composed = build_stage3_beta_composed(
        result, day_rate=100_000.0, run_date="2026-05-14",
    calibration_tolerances=TEST_CALIBRATION_TOLERANCES)
    out = tmp_path / "stage3_beta.html"
    info = render_stage3_beta_report_html(composed, out)
    assert out.exists()
    assert info["size_bytes"] > 0
    # The HTML should contain the preview banner multiple times — once per
    # major section. The brief mandates "on every page" — for the
    # single-document HTML we render the banner ahead of every H2 block.
    html_text = out.read_text(encoding="utf-8")
    banner_count = html_text.count("preview-banner")
    assert banner_count >= 6, (
        f"Expected preview-banner on every major section; "
        f"found {banner_count} occurrences"
    )


# ---------------------------------------------------------------------------
# Test 21 — HTML renderer includes 5-row Page 1 table
# ---------------------------------------------------------------------------

def test_html_renderer_includes_page1_table(tmp_path: Path):
    result = _make_synthetic_result()
    composed = build_stage3_beta_composed(result, day_rate=100_000.0, calibration_tolerances=TEST_CALIBRATION_TOLERANCES)
    out = tmp_path / "stage3_beta.html"
    render_stage3_beta_report_html(composed, out)
    text = out.read_text(encoding="utf-8")
    for component in (
        "Cost contingency",
        "Schedule contingency",
        "Naive sum",
        "Diversification effect",
        "Integrated total",
    ):
        assert component in text


# ---------------------------------------------------------------------------
# Test 22 — docx renderer writes a non-empty docx file
# ---------------------------------------------------------------------------

def test_docx_renderer_writes_non_empty_file(tmp_path: Path):
    pytest.importorskip("docx")
    result = _make_synthetic_result()
    composed = build_stage3_beta_composed(
        result, day_rate=100_000.0, run_date="2026-05-14",
    calibration_tolerances=TEST_CALIBRATION_TOLERANCES)
    out = tmp_path / "stage3_beta.docx"
    info = generate_stage3_beta_report_docx(composed, out)
    assert out.exists()
    assert info["size_bytes"] > 1000  # any real docx is > 1KB
    # docx ZIP magic = "PK"
    with open(out, "rb") as f:
        head = f.read(2)
    assert head == b"PK", "Expected docx (ZIP) magic header"


# ---------------------------------------------------------------------------
# Test 23 — Filename resolver follows the brief pattern
# ---------------------------------------------------------------------------

def test_filename_pattern_resolver():
    p_html = resolve_sibling_filename(
        "Hybrid", "2026-05-14", extension="html", output_dir=Path("outputs"),
    )
    assert p_html.name == "sra_stage3_beta_report_PROD_Hybrid_2026-05-14.html"
    assert p_html.parent.name == "outputs"

    p_docx = resolve_sibling_filename(
        "Series", "2026-05-14", extension="docx",
    )
    assert p_docx.name == "sra_stage3_beta_report_PROD_Series_2026-05-14.docx"


# ---------------------------------------------------------------------------
# Test 24 — Schedule contingency dollarises correctly
# ---------------------------------------------------------------------------

def test_schedule_contingency_dollarises_at_day_rate():
    """A controlled-input check: schedule P80 days × day rate = the
    dollarised contingency rendered in the Page 1 table."""
    rng = np.random.default_rng(42)
    iterations = 1000
    # Force schedule_days such that np.percentile(arr, 80) == 100.
    sched_arr = np.linspace(0.0, 125.0, num=iterations)  # P80 ≈ 100
    cost_arr = np.full(iterations, 10_000_000.0)
    cost_result = {
        "cost_dollars_array": cost_arr,
        "schedule_days_array": np.zeros(iterations),
        "per_risk_cost_array": cost_arr.reshape(-1, 1),
        "per_risk_schedule_array": np.zeros((iterations, 0)),
        "risk_ids_all": ["R001"],
        "risk_ids_dual": [],
        "iterations": iterations,
        "fired_array": np.ones((iterations, 1), dtype=bool),
    }

    class _Stub:
        beta_flag = True
        project_finish_days = sched_arr
        n_iter = iterations

    result = Stage3IntegratedResult(
        cost_result=cost_result, schedule_result=_Stub(),
        schedule_days_array=sched_arr,
        severity_uniforms_by_risk_id={}, risk_drivers={},
        schedule_graph=None, xer_tables={},
        auto_mapper_audit_path=None, beta_flag=True,
        iterations=iterations, seed_used=42,
        variant_label="Hybrid",
        config_summary={"criticality_measurement_mode": "mode_conditioned"},
    )
    day_rate = 100_000.0
    table = build_page1_stage3_beta_table(result, day_rate=day_rate)
    # P80 schedule days = ~100; dollarised = ~100 × 100000 = $28.28M
    sched_row = next(
        r for r in table if r["Component"] == "Schedule contingency (dollarised)"
    )
    # Expected ≈ $28.28M (loose due to interpolation)
    p80_days = float(np.percentile(sched_arr, 80))
    expected_m = p80_days * day_rate / 1e6
    rendered = sched_row["P80"]
    # Parse "$28.28M"
    rendered_val = float(rendered.replace("$", "").replace("M", ""))
    assert rendered_val == pytest.approx(expected_m, abs=0.01)


# ---------------------------------------------------------------------------
# Test 25 — Composer headline carries integrated total at P80 and Mean
# ---------------------------------------------------------------------------

def test_headline_carries_integrated_p80_and_mean():
    result = _make_synthetic_result()
    composed = build_stage3_beta_composed(result, day_rate=100_000.0, calibration_tolerances=TEST_CALIBRATION_TOLERANCES)
    h = composed["headline"]
    assert "integrated_p80_m_str" in h and h["integrated_p80_m_str"].startswith("$")
    assert "integrated_mean_m_str" in h and h["integrated_mean_m_str"].startswith("$")
    assert h["p_level"] == 80


# ---------------------------------------------------------------------------
# Test 26 — Audit trail captures iterations, seed, paths
# ---------------------------------------------------------------------------

def test_audit_trail_captures_metadata():
    result = _make_synthetic_result()
    composed = build_stage3_beta_composed(
        result, day_rate=100_000.0,
        register_path="inputs/register.xlsx",
        strawman_path="outputs/sra_strawman/strawman.xlsx",
        xer_path="docs/full_report.xer",
    calibration_tolerances=TEST_CALIBRATION_TOLERANCES)
    a = composed["audit_trail"]
    assert a["iterations"] == 1000
    assert a["seed_used"] == 42
    # The reader gets file names, not the analyst's folders (PUBLICFACE-01).
    assert a["register_path"] == "register.xlsx"
    assert a["strawman_path"] == "strawman.xlsx"
    assert a["xer_path"] == "full_report.xer"
