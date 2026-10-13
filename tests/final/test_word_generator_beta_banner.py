"""SR-S3-Beta-08 tests for the BETA banner infrastructure.

Covers banner constants, banner injection (including FAIL+BETA
co-existence ordering), filename prefix idempotency, custom property
round-trip, and the architectural-anchor end-to-end smoke test that
guarantees there is no path through generate_word_summary which
produces beta-flagged output without the banner.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from src.final import disclaimer_text
from src.final.word_generator import (
    BANNER_COLOR,
    BETA_BANNER_BORDER_HEX,
    BETA_BANNER_COLOR,
    BETA_BANNER_FONT_NAME,
    BETA_BANNER_FONT_SIZE_PT,
    BETA_BANNER_LINES,
    CUSTOM_PROPERTY_BETA_FLAG,
    FAIL_BANNER_LINES,
    _apply_beta_filename_prefix,
    _get_custom_property,
    _inject_beta_banner,
    _inject_fail_banner,
    generate_word_summary,
)


# ----------------------------------------------------------------------------
# Test fixtures (synthetic; no real RefProject data)
# ----------------------------------------------------------------------------

def _make_summary_data() -> dict:
    return {
        "headline_contingency_range_p80": {
            "lower_bound_dollars": 25_000_000.0,
            "lower_bound_scenario": "DP Review baseline",
            "indicative_dollars": 30_000_000.0,
            "indicative_scenario": "Dummy Realistic (" + "S" + "JP indicative)",
            "upper_bound_dollars": 35_000_000.0,
            "upper_bound_scenario": "All Series",
            "p_level": 80,
        },
        "top_3_cost_drivers": [],
        "top_3_schedule_drivers": [],
        "schedule_basis_note": "",
        "key_findings": ["Finding 1."],
        "methodology_caveats": ["Caveat 1."],
        "recommendations": ["Recommendation 1."],
    }


def _make_audit_trail() -> dict:
    return {
        "register_path": "/path/to/register.xlsx",
        "strawman_path": "/path/to/strawman.xlsx",
        "run_date": "2026-04-30",
        "iterations": 1000,
        "random_seed": 42,
        "day_rate_dollars_per_workday": 100000.0,
        "reporting_p_level": 80,
        "engine_versions": {
            "cost": "SP18-line",
            "schedule": "SP19 (SR5)",
            "integrated": "SP21 (SR8)",
            "final": "SP22 (SR9 v3.5+beta08)",
        },
    }


# ----------------------------------------------------------------------------
# Banner constants
# ----------------------------------------------------------------------------

def test_beta_banner_lines_match_documented_text():
    """The three lines must be the verbatim brief specification.

    The em dash (U+2014) is preserved per Director-signed-off text. SR17
    Workstream C amended the lines after Director D8.1 (2026-05-18)
    promoted Stage 3 + SR16 to current production headline; the previous
    lines named Stage 2.5 as production headline and Stage 3 as
    methodology demonstration only — both are obsolete under D8.1.
    """
    # SR18 Item 2: em-dash in the first line replaced with a colon as
    # part of the scoped sweep (BETA_BANNER_LINES is one of the four
    # surfaces named in the SR18 brief §3 Item 2).
    assert BETA_BANNER_LINES == (
        "STAGE 3 + SR16: CURRENT PRODUCTION HEADLINE.",
        "FIGURES PENDING WORKSHOP VALIDATION OF AUTO-MAPPER BINDINGS.",
        "STAGE 2.5 HYBRID $<stage25_mean>M RETAINED AS HISTORICAL COMPARATOR ONLY.",
    )


def test_beta_banner_color_amber_distinct_from_fail_red():
    """BETA must be visibly distinct from FAIL.

    Brief §9 risk: reviewer mistakes BETA banner for FAIL. Mitigation:
    Manhattan distance in RGB ≥ 80 units (amber #CC6600 vs FAIL red
    #C00000 = 0x66 + 0x66 + 0x00 = 204 unit Manhattan distance).
    """
    assert BETA_BANNER_COLOR != BANNER_COLOR
    # Manhattan distance in RGB; assert ≥ 80 units (well above the
    # quantitative threshold the brief calls out). RGBColor is an
    # iterable of three 0-255 ints (R, G, B).
    fail_rgb = tuple(BANNER_COLOR)
    beta_rgb = tuple(BETA_BANNER_COLOR)
    assert len(fail_rgb) == 3 and len(beta_rgb) == 3
    distance = sum(abs(a - b) for a, b in zip(fail_rgb, beta_rgb))
    assert distance >= 80, (
        f"BETA color {BETA_BANNER_COLOR} is too close to FAIL color "
        f"{BANNER_COLOR}: Manhattan distance {distance} < 80"
    )


# ----------------------------------------------------------------------------
# Banner injection behaviour (synthetic Document)
# ----------------------------------------------------------------------------

def _read_all_text(docx_path: Path) -> str:
    doc = Document(str(docx_path))
    parts = [p.text for p in doc.paragraphs]
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def test_inject_beta_banner_inserts_three_lines_above_title(tmp_path):
    """Synthetic doc; banner injected; banner table is first body element."""
    doc = Document()
    doc.add_heading("Title", level=1)
    _inject_beta_banner(doc)
    out = tmp_path / "beta_only.docx"
    doc.save(str(out))

    saved = Document(str(out))
    # The first body element should now be the banner table.
    assert len(saved.tables) >= 1
    banner_cell = saved.tables[0].cell(0, 0)
    text = "\n".join(p.text for p in banner_cell.paragraphs)
    for line in BETA_BANNER_LINES:
        assert line in text


def test_inject_beta_banner_below_fail_when_both_present(tmp_path):
    """FAIL+BETA co-existence: FAIL above, BETA below.

    Brief §9 invariant: when cross-validation fails AND Stage 3 beta
    is enabled, the document carries both banners. FAIL is the more
    urgent message (cross-validation failure is blocking) and goes
    on top; BETA below provides additional context.
    """
    doc = Document()
    doc.add_heading("Title", level=1)
    _inject_fail_banner(doc)
    _inject_beta_banner(doc)
    out = tmp_path / "fail_and_beta.docx"
    doc.save(str(out))

    saved = Document(str(out))
    assert len(saved.tables) >= 2
    fail_cell_text = "\n".join(p.text for p in saved.tables[0].cell(0, 0).paragraphs)
    beta_cell_text = "\n".join(p.text for p in saved.tables[1].cell(0, 0).paragraphs)
    # FAIL is in the first table, BETA in the second (i.e. below FAIL).
    assert FAIL_BANNER_LINES[0] in fail_cell_text
    assert BETA_BANNER_LINES[0] in beta_cell_text
    # And NOT swapped.
    assert FAIL_BANNER_LINES[0] not in beta_cell_text
    assert BETA_BANNER_LINES[0] not in fail_cell_text


def test_inject_beta_banner_above_title_when_only_beta(tmp_path):
    """When no FAIL is present, BETA injects at body[0] above the title."""
    doc = Document()
    doc.add_heading("My Title", level=1)
    _inject_beta_banner(doc)
    out = tmp_path / "beta_only_above_title.docx"
    doc.save(str(out))

    saved = Document(str(out))
    # Walk body elements; banner table should appear before the title heading.
    body_elements = list(saved.element.body)
    # Find positions
    table_positions = [
        i for i, el in enumerate(body_elements) if el.tag.endswith("}tbl")
    ]
    heading_positions = [
        i
        for i, el in enumerate(body_elements)
        if el.tag.endswith("}p") and "My Title" in "".join(el.itertext())
    ]
    assert table_positions and heading_positions
    assert min(table_positions) < min(heading_positions), (
        "BETA banner table should appear before the title heading"
    )


def test_inject_beta_banner_includes_audit_path_footer_when_provided(tmp_path):
    """A 4th line "Audit trail: <path>" appears when beta_metadata supplies it."""
    doc = Document()
    doc.add_heading("Title", level=1)
    audit_path = Path("/tmp/audit.parquet")
    _inject_beta_banner(doc, beta_metadata={"auto_mapper_audit_path": audit_path})
    out = tmp_path / "beta_with_audit.docx"
    doc.save(str(out))

    saved = Document(str(out))
    banner_cell = saved.tables[0].cell(0, 0)
    text = "\n".join(p.text for p in banner_cell.paragraphs)
    assert "Audit trail:" in text
    assert str(audit_path) in text


def test_inject_beta_banner_no_audit_path_when_metadata_missing(tmp_path):
    """When metadata is None or has no path, only the three banner lines render."""
    doc = Document()
    doc.add_heading("Title", level=1)
    _inject_beta_banner(doc, beta_metadata=None)
    out = tmp_path / "beta_no_audit.docx"
    doc.save(str(out))

    saved = Document(str(out))
    banner_cell = saved.tables[0].cell(0, 0)
    text = "\n".join(p.text for p in banner_cell.paragraphs)
    assert "Audit trail:" not in text


def test_beta_banner_styling_amber_bold_12pt(tmp_path):
    """Banner runs are bold, BETA color, 12pt Arial."""
    doc = Document()
    doc.add_heading("Title", level=1)
    _inject_beta_banner(doc)
    out = tmp_path / "beta_styling.docx"
    doc.save(str(out))

    saved = Document(str(out))
    banner_cell = saved.tables[0].cell(0, 0)
    found_styled_run = False
    for para in banner_cell.paragraphs:
        for run in para.runs:
            if run.text.strip() and run.text.strip() in BETA_BANNER_LINES:
                assert run.bold is True
                assert run.font.size is not None
                assert run.font.size.pt == BETA_BANNER_FONT_SIZE_PT
                assert run.font.color.rgb is not None
                assert str(run.font.color.rgb).upper() == BETA_BANNER_BORDER_HEX
                found_styled_run = True
    assert found_styled_run, "No BETA banner run with expected styling was found"


# ----------------------------------------------------------------------------
# Filename prefix
# ----------------------------------------------------------------------------

def test_apply_beta_filename_prefix_appends_when_flag_true():
    assert _apply_beta_filename_prefix("refproject_final_report.docx", True) == (
        "BETA_refproject_final_report.docx"
    )


def test_apply_beta_filename_prefix_idempotent_on_already_prefixed():
    """Running the notebook twice must not produce BETA_BETA_*.docx."""
    once = _apply_beta_filename_prefix("refproject_final_report.docx", True)
    twice = _apply_beta_filename_prefix(once, True)
    assert twice == once == "BETA_refproject_final_report.docx"


def test_apply_beta_filename_prefix_no_op_when_flag_false():
    assert _apply_beta_filename_prefix("refproject_final_report.docx", False) == (
        "refproject_final_report.docx"
    )


def test_apply_beta_filename_prefix_preserves_directory_path():
    """Idempotency must preserve the directory path component."""
    result = _apply_beta_filename_prefix("outputs/refproject_final_report.docx", True)
    # Use forward-slash compare (Path may normalise to backslash on Windows).
    assert Path(result).name == "BETA_refproject_final_report.docx"
    assert Path(result).parent == Path("outputs")


# ----------------------------------------------------------------------------
# Custom property round-trip
# ----------------------------------------------------------------------------

def test_custom_property_beta_flag_set_true_when_composed_beta_flag_true(tmp_path):
    """Generate v2 doc with composed['beta_flag']=True; property is 'true'."""
    out = tmp_path / "doc.docx"
    cv = {"all_pass": True}
    composed = {"beta_flag": True}
    result = generate_word_summary(
        summary_data=_make_summary_data(),
        audit_trail_data=_make_audit_trail(),
        disclaimer_paragraphs=disclaimer_text.get_paragraphs(),
        cross_validation=cv,
        output_path=out,
        composed=composed,
    )
    saved_path = Path(result["output_path"])
    assert _get_custom_property(saved_path, CUSTOM_PROPERTY_BETA_FLAG) == "true"


def test_custom_property_beta_flag_set_false_when_composed_beta_flag_absent(tmp_path):
    """No beta_flag in composed; property is "false" (or None - either is OK)."""
    out = tmp_path / "doc.docx"
    cv = {"all_pass": True}
    result = generate_word_summary(
        summary_data=_make_summary_data(),
        audit_trail_data=_make_audit_trail(),
        disclaimer_paragraphs=disclaimer_text.get_paragraphs(),
        cross_validation=cv,
        output_path=out,
        composed=None,
    )
    saved_path = Path(result["output_path"])
    val = _get_custom_property(saved_path, CUSTOM_PROPERTY_BETA_FLAG)
    assert val in (None, "false")


# ----------------------------------------------------------------------------
# End-to-end architectural-anchor smoke (slow-marked)
# ----------------------------------------------------------------------------

# TESTLANE-01 A sweep: unmarked - measured 0.40s in the lane-1 durations, no
# subprocess, no notebook, no engine run. It was in the slow class by habit.
def test_word_generator_beta_banner_always_applied_when_flag_set(tmp_path):
    """Architectural anchor (Beta-00 §5).

    There is no path through generate_word_summary that produces a
    docx with composed['beta_flag']=True without the banner being
    applied AND the filename prefixed AND the custom property set.
    Tested at the smoke level (not unit) so the full integration is
    exercised.
    """
    out = tmp_path / "exec_summary.docx"
    cv = {"all_pass": True}
    composed = {
        "beta_flag": True,
        "auto_mapper_audit_path": Path("/tmp/audit.parquet"),
    }
    result = generate_word_summary(
        summary_data=_make_summary_data(),
        audit_trail_data=_make_audit_trail(),
        disclaimer_paragraphs=disclaimer_text.get_paragraphs(),
        cross_validation=cv,
        output_path=out,
        composed=composed,
    )

    saved_path = Path(result["output_path"])
    # 1. filename has BETA_ prefix
    assert saved_path.name.startswith("BETA_")
    # 2. doc contains the banner text
    text = _read_all_text(saved_path)
    for line in BETA_BANNER_LINES:
        assert line in text, f"BETA banner line missing: {line!r}"
    # 3. audit-trail footer line present
    assert "Audit trail:" in text
    assert "/tmp/audit.parquet" in text or "tmp\\audit.parquet" in text
    # 4. result dict reports both flags
    assert result["beta_banner_present"] is True
    # 5. custom property is "true"
    assert _get_custom_property(saved_path, CUSTOM_PROPERTY_BETA_FLAG) == "true"
