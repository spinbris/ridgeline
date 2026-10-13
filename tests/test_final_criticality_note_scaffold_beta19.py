"""SR-S3-Beta-19 §8 — criticality content split scaffold tests.

Asserts the sibling criticality-and-float-visibility note scaffold
lands as designed:

* ``generate_criticality_note_docx`` renders a docx with all 10
  expected sections from ``composed["criticality_note"]``.
* ``render_criticality_note_html`` produces a standalone HTML file
  with the same 10 sections and the placeholder image-frame captions
  for Charts 1, 3, 4 (Chart 2 reuses the existing Beta-12 CI
  distribution chart when present).
* The shrunk main-report criticality section:
  - Renders the 5-row near-critical summary (not the 10-row table).
  - Renders the Chart-2 placeholder caption (not the actual CI chart).
  - Renders the risk-to-CP linkage prose (not the full bridge table).
  - Renders the forward-reference line pointing at the sibling note.
* The file-name template ``sra_criticality_note_PROD_{variant}_{date}``
  produces both .html and .docx outputs.

Chart-rendering itself is SR10.B's scope; this file confirms only
the scaffold structure / wiring.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

docx = pytest.importorskip("docx")
Document = docx.Document

from src.final.criticality_note_html import (  # noqa: E402
    render_criticality_note_html,
)
from src.final.word_generator import (  # noqa: E402
    generate_criticality_note_docx,
)


def _populated_criticality_note() -> dict:
    """Composed["criticality_note"] block fully populated for the
    scaffold tests. Matches what the composer's
    ``_apply_stage3_beta_keys`` produces in real runs."""
    return {
        "purpose_and_audience": (
            "**Purpose.** Demo. **Audience.** Project controls."
        ),
        "explainer": (
            "Activity-level criticality answers a different question.\n\n"
            "The Criticality Index measures how often each activity sits "
            "on the critical path."
        ),
        "chart1_caption": (
            "_[Top-30 sorted criticality bar chart — Chart 1; populated "
            "by SR10.B.]_"
        ),
        "chart2_path": "",
        "chart2_caption": (
            "_[Criticality density Gantt by phase — Chart 2; populated "
            "by SR10.B.]_"
        ),
        "near_critical_table_10row": [
            {
                "activity_id": f"ACT{i:03d}",
                "activity_name": f"Activity {i}",
                "ci": 0.4 + i * 0.05,
                "total_float_mean_hours": 24.0,
                "total_float_std_hours": 5.0,
            }
            for i in range(1, 11)
        ],
        "near_critical_interpretation": "Ten activities sit in the band.",
        "near_critical_table_caveat": "_Calendar caveat note._",
        "risk_to_activity_bridge": [
            {
                "risk_id": "R013",
                "risk_title": "Risk thirteen",
                "activity_id": "ACT001",
                "activity_name": "Activity 1",
                "ci": 0.65,
                "on_deterministic_cp": False,
                "no_activity_bindings": False,
            },
        ],
        "risk_bridge_interpretation": (
            "Bridge connects top-3 schedule drivers to activities."
        ),
        "risk_to_activity_bridge_caveat": "_Calendar caveat note._",
        "chart3_caption": (
            "_[Risk-to-CP linkage — Chart 3; populated by SR10.B.]_"
        ),
        "chart4_caption": (
            "_[Float histogram with criticality overlay — Chart 4; "
            "populated by SR10.B.]_"
        ),
        "input_dependencies_caveat": (
            "**Inputs that drive criticality accuracy.** This analysis "
            "uses the inputs as provided.\n\n"
            "1. **Risk-driver-to-activity assignments.**\n\n"
            "2. **Schedule logic in the .xer.**\n\n"
            "3. **Calendar handling.**"
        ),
        "audit_trail_reference": (
            "_Audit trail: see `sra_final_report_PROD_*` for full "
            "register / strawman / P6 hashes._"
        ),
    }


# ---------------------------------------------------------------------------
# Sibling-note docx
# ---------------------------------------------------------------------------

def test_criticality_note_docx_renders_all_10_sections(tmp_path: Path) -> None:
    """All 10 expected sections render into the docx body. Beta-19
    Decision 3 scaffold; charts come in SR10.B."""
    composed = {"criticality_note": _populated_criticality_note()}
    out = tmp_path / "sra_criticality_note_PROD_Hybrid_2026-05-13.docx"
    result = generate_criticality_note_docx(composed, out)

    assert result["sections_rendered"] >= 10
    assert out.exists()

    doc = Document(str(out))
    body_text = "\n".join(p.text for p in doc.paragraphs)
    table_text = "\n".join(
        cell.text for t in doc.tables for row in t.rows for cell in row.cells
    )
    body = body_text + "\n" + table_text

    # Title and each section heading.
    assert "Criticality and float visibility note" in body
    assert "CI explainer" in body
    assert "Top-30 sorted criticality (Chart 1)" in body
    assert "Criticality density Gantt by phase (Chart 2)" in body
    assert "Near-critical activities (CI 20-80%) — 10-row detail" in body
    assert "Risk-to-activity bridge (top-3 schedule risk drivers)" in body
    assert "Float histogram with criticality overlay (Chart 4)" in body
    assert "Risk-to-CP linkage (Chart 3)" in body
    assert "Inputs that drive criticality accuracy" in body

    # 10-row near-critical table present; 10 rows + header.
    near_table = [t for t in doc.tables if any(
        "Activity 1" in cell.text or "Activity 5" in cell.text
        for row in t.rows for cell in row.cells
    )]
    assert near_table, "10-row near-critical activities table missing"

    # Placeholder captions for charts 1, 3, 4 land in body.
    assert "Top-30 sorted criticality bar chart" in body
    assert "Risk-to-CP linkage" in body
    assert "Float histogram with criticality overlay" in body


# ---------------------------------------------------------------------------
# Sibling-note HTML
# ---------------------------------------------------------------------------

def test_criticality_note_html_renders_with_placeholders(tmp_path: Path) -> None:
    """The HTML deliverable carries all 10 sections, the placeholder
    image frames for Charts 1, 3, 4, and the audit-trail abbreviated
    reference at the bottom."""
    composed = {"criticality_note": _populated_criticality_note()}
    out = tmp_path / "sra_criticality_note_PROD_Hybrid_2026-05-13.html"
    result = render_criticality_note_html(
        composed,
        output_path=out,
        variant="Hybrid",
        run_date="2026-05-13",
    )

    assert result["sections_rendered"] >= 10
    assert out.exists()

    text = out.read_text(encoding="utf-8")

    # Title carries variant and date.
    assert "Hybrid" in text
    assert "2026-05-13" in text

    # All H2 section headings present.
    for h in (
        "CI explainer",
        "Top-30 sorted criticality (Chart 1)",
        "Criticality density Gantt by phase (Chart 2)",
        "Near-critical activities (CI 20-80%)",
        "Risk-to-activity bridge (top-3 schedule risk drivers)",
        "Float histogram with criticality overlay (Chart 4)",
        "Risk-to-CP linkage (Chart 3)",
        "Inputs that drive criticality accuracy",
    ):
        assert f"<h2>{h}" in text, f"Missing H2 heading: {h}"

    # Placeholder image frames rendered as <div class="placeholder">.
    assert text.count('class="placeholder"') >= 3, (
        "Expected ≥3 placeholder frames (Charts 1, 3, 4; Chart 2 may "
        "also be a placeholder if chart2_path is empty)."
    )
    # Audit-trail reference at the bottom.
    assert "Audit trail:" in text


def test_criticality_note_filename_template_produces_both_extensions(
    tmp_path: Path,
) -> None:
    """The Beta-19 file-name template
    ``sra_criticality_note_PROD_{variant}_{date}.{html,docx}`` is the
    contract the sibling-note runner relies on. Both extensions land
    at the expected paths."""
    composed = {"criticality_note": _populated_criticality_note()}
    variant = "Hybrid"
    rd = date.today().isoformat()
    base = f"sra_criticality_note_PROD_{variant}_{rd}"

    html_path = tmp_path / f"{base}.html"
    docx_path = tmp_path / f"{base}.docx"

    render_criticality_note_html(composed, html_path, variant=variant, run_date=rd)
    generate_criticality_note_docx(composed, docx_path)

    assert html_path.exists()
    assert docx_path.exists()
    assert html_path.stat().st_size > 1000
    assert docx_path.stat().st_size > 1000


# ---------------------------------------------------------------------------
# Main-report shrunk criticality section
# ---------------------------------------------------------------------------

def test_main_report_criticality_shrunk_to_5_row_with_forward_reference(
    tmp_path: Path,
) -> None:
    """The shrunk main-report criticality section renders:
    - 5-row near-critical table (not 10)
    - Chart-2 placeholder caption
    - Risk-to-CP linkage prose
    - Inputs subsection
    - Forward-reference to the sibling note
    The full bridge table and 10-row near-critical detail must NOT
    appear in this section.
    """
    from src.final.word_generator import _add_criticality_section_v36

    near_full = [
        {
            "activity_id": f"ACT{i:03d}",
            "activity_name": f"Activity {i}",
            "ci": 0.4 + i * 0.05,
            "total_float_mean_hours": 24.0,
            "total_float_std_hours": 5.0,
        }
        for i in range(1, 11)
    ]
    composed = {
        "page4b_criticality": {
            "explainer": "Criticality Index explains path stability.",
            "distribution_chart_path": "",
            "near_critical_table": near_full,
            "near_critical_table_top_5": near_full[:5],
            "near_critical_interpretation": "",
            "near_critical_table_caveat": "_Cal caveat._",
            "risk_to_activity_bridge": [
                {"risk_id": "R013", "activity_name": "ACT001", "ci": 0.65,
                 "no_activity_bindings": False},
            ],
            "risk_bridge_interpretation": "",
            "risk_to_activity_bridge_caveat": "",
            "chart2_placeholder_caption": (
                "_[Criticality density Gantt by phase — Chart 2; "
                "populated by SR10.B.]_"
            ),
            "risk_to_cp_linkage_prose": (
                "Risk-to-CP linkage: R013 binds to ACT001 (CI 65%)."
            ),
            "forward_reference_to_note": (
                "Full activity-level criticality detail is in the "
                "companion sibling deliverable "
                "`sra_criticality_note_PROD_*.{html,docx}`."
            ),
            "input_dependencies_caveat": (
                "**Inputs that drive criticality accuracy.**\n\n"
                "1. Risk-driver-to-activity assignments."
            ),
        }
    }

    doc = Document()
    _add_criticality_section_v36(doc, composed)
    out = tmp_path / "main_report_criticality.docx"
    doc.save(str(out))

    doc2 = Document(str(out))
    paragraphs = [p.text for p in doc2.paragraphs]
    body = "\n".join(paragraphs)
    table_cells = [
        cell.text for t in doc2.tables for row in t.rows for cell in row.cells
    ]

    # Shrunk-section structural assertions.
    assert "Near-critical activities (top 5 by CI)" in body
    assert "Risk-to-CP linkage" in body
    assert any("criticality_note_PROD" in p for p in paragraphs), (
        "Forward-reference line missing"
    )
    assert "Chart 2" in body, "Chart-2 placeholder caption missing"

    # The 5-row table contains ACT001..ACT005 only; ACT006..ACT010 must
    # NOT appear in this section's tables.
    cells_joined = " ".join(table_cells)
    for i in range(1, 6):
        assert f"ACT{i:03d}" in cells_joined, f"ACT{i:03d} missing from 5-row table"
    for i in range(6, 11):
        assert f"ACT{i:03d}" not in cells_joined, (
            f"ACT{i:03d} present in main-report table (should only be in "
            f"the sibling note's 10-row table)"
        )

    # The full bridge table heading must NOT appear in the main report
    # (it moved to the sibling note).
    assert "Risk-to-activity bridge (top-3 schedule risk drivers)" not in body
