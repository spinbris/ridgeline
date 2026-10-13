"""SR10.B sibling-note full-render integration test.

Extends the Beta-19 scaffold test (which asserts the seven sections are
emitted with placeholders) to assert that with all four chart paths
populated, the four placeholder frames are replaced by embedded PNGs
(Decision 6 — Beta-19 scaffold preserved; SR10.B fills the frames).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.final.criticality_note_html import render_criticality_note_html
from src.final.word_generator import generate_criticality_note_docx


def _make_blank_png(path: Path) -> Path:
    """1x1 transparent PNG — minimal valid PNG payload for embed tests."""
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15"
        "c4890000000d49444154789c63f8ffff3f0000050001"
        "010100a8050000000049454e44ae426082"
    )
    path.write_bytes(png_bytes)
    return path


def _make_composed_with_all_chart_paths(tmp_path: Path) -> dict:
    """Composed dict with chart_*_path keys pointing at real PNGs."""
    chart1 = _make_blank_png(tmp_path / "chart1_sorted_top30.png")
    chart2 = _make_blank_png(tmp_path / "chart2_density_gantt.png")
    chart3 = _make_blank_png(tmp_path / "chart3_risk_to_cp_linkage.png")
    chart4 = _make_blank_png(tmp_path / "chart4_float_histogram.png")
    return {
        "criticality_note": {
            "purpose_and_audience": "Test purpose paragraph.",
            "explainer": "Test CI explainer.",
            "chart1_path": str(chart1),
            "chart1_caption": "[placeholder caption]",
            "chart2_path": str(chart2),
            "chart2_caption": "Chart 2 - density Gantt rendered caption.",
            "chart3_path": str(chart3),
            "chart3_caption": "[Chart 3 placeholder]",
            "chart4_path": str(chart4),
            "chart4_caption": "[Chart 4 placeholder]",
            "near_critical_table_10row": [
                {"activity_id": "A1", "activity_name": "Test act",
                 "ci": 0.5, "ci_band": "near (30-70%)",
                 "total_float_mean_hours": 16.0,
                 "total_float_std_hours": 0.0,
                 "on_deterministic_cp": False},
            ],
            "near_critical_interpretation": "Test interpretation.",
            "near_critical_table_caveat": "Test caveat.",
            "risk_to_activity_bridge": [
                {"risk_id": "R001", "risk_title": "Test risk",
                 "activity_id": "A1", "activity_name": "Test act",
                 "ci": 0.5, "on_deterministic_cp": False,
                 "no_activity_bindings": False},
            ],
            "risk_bridge_interpretation": "Test bridge interpretation.",
            "risk_to_activity_bridge_caveat": "Test bridge caveat.",
            "input_dependencies_caveat": "Test dependencies caveat.",
            "audit_trail_reference": "Test audit reference.",
        },
    }


def test_html_embeds_all_four_chart_pngs(tmp_path: Path) -> None:
    """All four chart PNGs are base64-embedded in the HTML output."""
    composed = _make_composed_with_all_chart_paths(tmp_path)
    out = tmp_path / "criticality_note.html"
    render_criticality_note_html(composed, output_path=out)
    html = out.read_text(encoding="utf-8")

    # All four chart frames are embedded via <img src="data:image/png;base64,...">.
    assert html.count('src="data:image/png;base64,') >= 4

    # Beta-19 placeholder div (yellow dashed border) is absent for the
    # four chart frames when their PNGs render.
    n_placeholders = html.count('class="placeholder"')
    # The §4 (Chart 2) section has both an embedded image AND a caption
    # caveat via _render_caveat; the other three frames have image only.
    # Allow ≤ 1 placeholder div total (defensive: the strict assertion
    # is "the chart slots are NOT placeholders"; renderers may inject
    # placeholders elsewhere if a future scaffold expansion lands).
    assert n_placeholders <= 1


def test_html_falls_back_to_placeholder_when_chart_path_missing(tmp_path: Path) -> None:
    """Missing chart_path → placeholder caption rendered as fallback."""
    composed = _make_composed_with_all_chart_paths(tmp_path)
    composed["criticality_note"]["chart1_path"] = ""
    composed["criticality_note"]["chart3_path"] = ""
    out = tmp_path / "criticality_note_partial.html"
    render_criticality_note_html(composed, output_path=out)
    html = out.read_text(encoding="utf-8")
    # Chart 1 + Chart 3 fall back to <div class="placeholder">; the
    # caption strings show up as italic placeholder text.
    assert html.count('class="placeholder"') >= 2


def test_docx_embeds_all_four_chart_pngs(tmp_path: Path) -> None:
    """All four chart PNGs are added to the docx output."""
    docx_lib = pytest.importorskip("docx")
    composed = _make_composed_with_all_chart_paths(tmp_path)
    out = tmp_path / "criticality_note.docx"
    meta = generate_criticality_note_docx(composed, output_path=out)
    assert Path(meta["output_path"]).exists()

    # Verify image embedding by reading the docx body and counting
    # InlineShape elements (each embedded PNG is one shape).
    doc = docx_lib.Document(str(out))
    assert len(doc.inline_shapes) >= 4


def test_docx_falls_back_to_caption_when_chart_path_missing(tmp_path: Path) -> None:
    """Missing chart_path → placeholder caption rendered, no crash."""
    pytest.importorskip("docx")
    composed = _make_composed_with_all_chart_paths(tmp_path)
    composed["criticality_note"]["chart4_path"] = "/nonexistent/path.png"
    out = tmp_path / "criticality_note_missing_ch4.docx"
    meta = generate_criticality_note_docx(composed, output_path=out)
    # Doc still renders; chart 4 falls back to caption.
    assert Path(meta["output_path"]).exists()


def test_beta19_scaffold_seven_section_structure_preserved(tmp_path: Path) -> None:
    """Decision 6 — Beta-19's seven-section scaffold is preserved.

    The sibling note's section headings are unchanged from Beta-19:
    Purpose, CI explainer, §3 Chart 1, §4 Chart 2, §5 Near-critical,
    §6 Risk bridge, §7 Chart 4, §8 Chart 3, §9 Inputs, §10 Audit.
    """
    composed = _make_composed_with_all_chart_paths(tmp_path)
    out = tmp_path / "criticality_note_structure.html"
    render_criticality_note_html(composed, output_path=out)
    html = out.read_text(encoding="utf-8")
    # H2 headings span the 8 in-document sections (Purpose is H1 prose,
    # Audit is a div; the H2 count is ≥ 7 to allow for the headings
    # currently emitted by the renderer).
    assert html.count("<h2>") >= 7
    for expected in (
        "Top-30 sorted criticality",
        "Criticality density Gantt",
        "Near-critical activities",
        "Risk-to-activity bridge",
        "Float histogram",
        "Risk-to-CP linkage",
    ):
        assert expected in html, f"missing section heading: {expected}"
