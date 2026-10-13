"""Tests for SR-S3-Beta-12 word_generator activity-level criticality section.

Builds a minimal ``composed`` dict with the page4b_criticality slot
populated, calls :func:`src.final.word_generator._add_criticality_section_v36`
against a fresh Document, saves it, re-reads the body text, and asserts:

* the section heading "Activity-level criticality" is present
* the explainer paragraph (data-driven) is rendered
* the near-critical sub-heading is present
* the risk-to-activity bridge sub-heading is present
* the input-dependencies caveat sub-heading is present
* the input-dependencies caveat body is present
* the section body contains NO dev/prod or workshop-pending phrasing
  (Beta-12 §3.3 caveat invariant)

The Stage 2.5 production path is also exercised — when
``composed["page4b_criticality"]`` is empty, the function is a no-op and
no headings are added to the document.

Per Beta-12 §5 the slow-tier brief variant of this test executes
nbconvert end-to-end with a real RefProject run; that test is exercised
indirectly by the smoke run at PM-hat sign-off and is not added to the
suite (the test would duplicate the smoke run's coverage and add
~2 minutes to the slow-tier).
"""

from __future__ import annotations

from pathlib import Path

import pytest

docx = pytest.importorskip("docx")
Document = docx.Document


def _read_body_paragraphs(path: Path) -> list[str]:
    """Re-open the saved docx and return all body paragraph text."""
    doc = Document(str(path))
    return [p.text for p in doc.paragraphs]


def _read_body_tables_text(path: Path) -> list[str]:
    """Re-open the saved docx and return all table cells' text values."""
    doc = Document(str(path))
    out: list[str] = []
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                out.append(cell.text)
    return out


def _populated_p4b() -> dict:
    """Synthetic composed["page4b_criticality"] block with all surfaces
    populated. Mirrors what the composer produces from a real run."""
    return {
        "explainer": (
            "Activity-level criticality answers a different question. "
            "The risk-driver tornado tells you which RISKS add the most "
            "days. Criticality tells you which ACTIVITIES sit on the "
            "path that controls the project finish date.\n\n"
            "The Criticality Index measures how often each activity "
            "sits on the critical path."
        ),
        "distribution_chart_path": "",  # chart path not required for test
        "distribution_summary": {
            "shape_indicator": "shifty",
            "n_activities_total": 100,
            "band_pcts": {
                "never (<10%)": 0.10,
                "rarely (10-30%)": 0.20,
                "near (30-70%)": 0.40,
                "often (70-90%)": 0.20,
                "always (90%+)": 0.10,
            },
            "band_counts": {},
            "n_on_deterministic_cp": 10,
        },
        "distribution_interpretation": (
            "Of 100 schedule activities, only 10% are critical in 90%+ "
            "of iterations; 80% sit in the 10-90% middle bands. The "
            "critical path moves materially between iterations."
        ),
        "near_critical_table": [
            {
                "activity_id": "ACT001",
                "activity_name": "Foundation pour A",
                "ci": 0.65,
                "ci_band": "near (30-70%)",
                "total_float_mean_hours": 24.0,
                "total_float_std_hours": 5.5,
                "on_deterministic_cp": False,
            },
            {
                "activity_id": "ACT002",
                "activity_name": "Cable pull B",
                "ci": 0.55,
                "ci_band": "near (30-70%)",
                "total_float_mean_hours": 36.0,
                "total_float_std_hours": 8.0,
                "on_deterministic_cp": False,
            },
        ],
        # Beta-19 §3: top-5 slice used by the shrunk main-report section.
        "near_critical_table_top_5": [
            {
                "activity_id": "ACT001",
                "activity_name": "Foundation pour A",
                "ci": 0.65,
                "ci_band": "near (30-70%)",
                "total_float_mean_hours": 24.0,
                "total_float_std_hours": 5.5,
                "on_deterministic_cp": False,
            },
            {
                "activity_id": "ACT002",
                "activity_name": "Cable pull B",
                "ci": 0.55,
                "ci_band": "near (30-70%)",
                "total_float_mean_hours": 36.0,
                "total_float_std_hours": 8.0,
                "on_deterministic_cp": False,
            },
        ],
        "near_critical_interpretation": (
            "The 2 activities in the table above are the near-critical "
            "set — activities that flip in and out of the critical path."
        ),
        "risk_to_activity_bridge": [
            {
                "risk_id": "R013",
                "risk_title": "Risk thirteen",
                "activity_id": "ACT001",
                "activity_name": "Foundation pour A",
                "ci": 0.65,
                "on_deterministic_cp": False,
                "no_activity_bindings": False,
            },
            {
                "risk_id": "R067",
                "risk_title": "Transformer lead time",
                "activity_id": "",
                "activity_name": "(no activity bindings under current input mapping)",
                "ci": float("nan"),
                "on_deterministic_cp": False,
                "no_activity_bindings": True,
            },
        ],
        "risk_bridge_interpretation": (
            "The table below connects the top-3 schedule risk drivers "
            "to the activities each one's modelling expands to."
        ),
        "input_dependencies_caveat": (
            "**Inputs that drive activity-level criticality accuracy.** "
            "This analysis uses the inputs as provided.\n\n"
            "1. **Risk-driver-to-activity assignments.** The current "
            "mapping is pattern-based.\n\n"
            "2. **Schedule logic in the .xer.** The CPM kernel uses "
            "precedence relations exactly as exported.\n\n"
            "3. **Calendar handling.** The current model uses a single "
            "project-default working calendar."
        ),
        # Beta-19 §3: shrunk-main-report scaffold keys. The Chart-2
        # placeholder caption sits where SR10.B's criticality density
        # Gantt image will land; the risk-to-CP linkage prose replaces
        # the (now-relocated) full bridge table; the forward reference
        # points readers at the sibling criticality note for full detail.
        "chart2_placeholder_caption": (
            "_[Criticality density Gantt by phase — Chart 2; populated "
            "by SR10.B.]_"
        ),
        "risk_to_cp_linkage_prose": (
            "Risk-to-CP linkage: R013 binds to Foundation pour A "
            "(CI 65%); R067 has no activity bindings under the current "
            "auto-mapper expansion. Treatment effort on these risks "
            "narrows the criticality distribution at the named "
            "activities."
        ),
        "forward_reference_to_note": (
            "Full activity-level criticality detail is in the "
            "companion sibling deliverable "
            "`sra_criticality_note_PROD_*.{html,docx}`."
        ),
    }


# ---------------------------------------------------------------------------
# Section rendering
# ---------------------------------------------------------------------------

def test_section_present_in_beta_docx(tmp_path: Path) -> None:
    """Populated page4b_criticality block produces all expected headings,
    body paragraphs, and tables. The section also satisfies the
    audience-tone invariant: no dev/prod or workshop-pending phrasing
    in the rendered body."""
    from src.final.word_generator import _add_criticality_section_v36

    doc = Document()
    composed = {"page4b_criticality": _populated_p4b()}
    _add_criticality_section_v36(doc, composed)

    output_path = tmp_path / "beta12_section.docx"
    doc.save(str(output_path))

    paragraphs = _read_body_paragraphs(output_path)
    table_text = _read_body_tables_text(output_path)
    body_text = "\n".join(paragraphs + table_text)

    # Beta-19 §3: section structure is the shrunk main-report variant.
    # Headings present:
    assert "Activity-level criticality" in body_text
    assert "Near-critical activities (top 5 by CI)" in body_text
    assert "Inputs that drive criticality accuracy" in body_text

    # Beta-19 §3: the full bridge sub-heading and bridge table have
    # been MOVED to the sibling criticality note. They must NOT appear
    # in the shrunk main-report section.
    assert "Risk-to-activity bridge (top-3 schedule risk drivers)" not in body_text

    # Explainer paragraph is rendered (data-driven; first paragraph).
    assert any("Criticality Index" in p for p in paragraphs)

    # Beta-19 §3: Chart 2 placeholder caption rendered in place of the
    # SR10.B-pending criticality density Gantt.
    assert any("Chart 2" in p for p in paragraphs)
    assert any("populated by SR10.B" in p for p in paragraphs)

    # Beta-19 §3: risk-to-CP linkage prose paragraph rendered. Replaces
    # the full bridge table in the main report.
    assert any("Risk-to-CP linkage" in p for p in paragraphs)

    # Input-dependencies caveat — the three input-category sentences.
    assert any("Risk-driver-to-activity assignments" in p for p in paragraphs)
    assert any("Schedule logic in the .xer" in p for p in paragraphs)
    assert any("Calendar handling" in p for p in paragraphs)

    # Near-critical activity table renders the activity names.
    assert any("Foundation pour A" in cell for cell in table_text)
    assert any("Cable pull B" in cell for cell in table_text)

    # Beta-19 §3: bridge table rows must NOT be in the main-report
    # cells (the bridge table moved to the sibling criticality note).
    assert not any(
        "no activity bindings under current input mapping" in cell
        for cell in table_text
    )

    # Beta-19 §3: forward-reference paragraph rendered pointing readers
    # at the sibling criticality note.
    assert any(
        "criticality_note_PROD" in p for p in paragraphs
    ), "forward-reference line to sibling criticality note must render"

    # Audience-tone invariant — no dev/prod or workshop-pending phrasing
    # in the section body. Beta-12 §3.3.
    forbidden_phrases = (
        "BETA - methodology demonstration",
        "BETA — methodology demonstration",
        "workshop-pending",
        "workshop pending",
        "dev mode",
        "prod mode",
        "indicative scenario",
        "PM review",
        "Dummy Realistic",
        "DP Review",
    )
    for phrase in forbidden_phrases:
        assert phrase.lower() not in body_text.lower(), (
            f"Section body contains forbidden phrase '{phrase}' — "
            f"the input-dependencies caveat should be the only caveat "
            f"language and it must not reference dev/prod or "
            f"workshop-pending framing"
        )


def test_empty_p4b_renders_no_section(tmp_path: Path) -> None:
    """Stage 2.5 production path: ``composed["page4b_criticality"]`` is
    empty / missing, the section function is a no-op, no headings or
    paragraphs are added."""
    from src.final.word_generator import _add_criticality_section_v36

    doc = Document()
    # Stage 2.5 path: no page4b_criticality key.
    _add_criticality_section_v36(doc, composed={})
    output_path = tmp_path / "no_section.docx"
    doc.save(str(output_path))

    paragraphs = _read_body_paragraphs(output_path)
    body_text = "\n".join(paragraphs)
    assert "Activity-level criticality" not in body_text
    assert "Near-critical" not in body_text
    assert "Risk-to-activity bridge" not in body_text


def test_empty_dict_p4b_renders_no_section(tmp_path: Path) -> None:
    """Empty page4b_criticality dict → no-op, same as missing key."""
    from src.final.word_generator import _add_criticality_section_v36

    doc = Document()
    _add_criticality_section_v36(doc, composed={"page4b_criticality": {}})
    output_path = tmp_path / "no_section_empty.docx"
    doc.save(str(output_path))

    paragraphs = _read_body_paragraphs(output_path)
    body_text = "\n".join(paragraphs)
    assert "Activity-level criticality" not in body_text


def test_empty_near_critical_renders_placeholder(tmp_path: Path) -> None:
    """When the picker returns zero rows, the section renders the
    empty-state placeholder paragraph instead of an empty table."""
    from src.final.word_generator import _add_criticality_section_v36

    p4b = _populated_p4b()
    p4b["near_critical_table"] = []
    p4b["near_critical_table_top_5"] = []  # Beta-19 §3: top-5 slice empty too
    p4b["near_critical_interpretation"] = ""  # empty fallback paragraph
    doc = Document()
    _add_criticality_section_v36(doc, composed={"page4b_criticality": p4b})
    output_path = tmp_path / "no_near.docx"
    doc.save(str(output_path))

    paragraphs = _read_body_paragraphs(output_path)
    body_text = "\n".join(paragraphs)
    # Heading still rendered.
    assert "Activity-level criticality" in body_text
    # Empty-state placeholder language present.
    assert "No activities sit in the near-critical" in body_text
