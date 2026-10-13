# SR9 v3 amendment - 2026-04-26 - presentation-layer reframe.
"""Tests for SR9 v3 word_generator extension.

Verifies the v3 layout renders all expected sections (callouts, charts,
DP review caveat, standards refs, limitations) when the optional
`composed` parameter is supplied with v3 keys.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.final.charts import make_density_histogram, make_tornado_chart
from src.final.word_generator import generate_word_summary

# Reuse the composer fixture for full v3 composed dict.
from tests.test_sr9_v3_composer import _fixture_inputs


def _generate_v3_doc(tmp_path: Path) -> tuple[Path, dict]:
    """Compose v3 dict, generate Word doc, return path + composed."""
    from src.final.composer import compose_final_report_data

    f = _fixture_inputs(tmp_path)
    chart_dir = tmp_path / "charts"

    composed = compose_final_report_data(
        cost_results=f["cost_results"],
        schedule_results=f["schedule_results"],
        integrated_results_by_scenario=f["integrated_by_scenario"],
        schedule_results_by_scenario=f["schedule_by_scenario"],
        strawman_path=f["strawman_path"],
        register_path=f["register_path"],
        cross_validation=f["cv_result"],
        risk_titles=f["risk_titles"],
        risks=f["risks"],
        chart_output_dir=chart_dir,
        programme_duration_days=300.0,
        # Beta-17 SSoT: bypass register read - fixture register file is a
        # text stub, not a real xlsx; pass empty cg_descriptions so the
        # CG drivers table renders "(not in register)" placeholders.
        cg_descriptions={},
        config=f["config"],
    )

    output_path = tmp_path / "v3_test.docx"
    word_meta = generate_word_summary(
        summary_data=composed["executive_summary"],
        audit_trail_data=composed["appendix_audit_trail"],
        disclaimer_paragraphs=composed["disclaimer_paragraphs"],
        cross_validation=f["cv_result"],
        output_path=output_path,
        composed=composed,
    )
    assert output_path.exists()
    return output_path, composed


def _read_doc_text(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def test_word_doc_omits_the_retired_dev_callouts(tmp_path: Path):
    """PRESENT-01 (D-4): the two callouts were dev-only.

    The composer emptied their bodies on every shipped run and word_generator's `if x:` guard
    skipped the block, so no reader saw them. This asserts their absence, so reinstating either
    reds here rather than arriving unnoticed in a client document.
    """
    path, composed = _generate_v3_doc(tmp_path)
    text = _read_doc_text(path)
    assert "Why MC matters here" not in text
    assert "How this analysis ages well" not in text


def test_word_doc_includes_charts(tmp_path: Path):
    path, composed = _generate_v3_doc(tmp_path)
    # python-docx exposes images via inline_shapes
    from docx import Document
    doc = Document(str(path))
    assert len(doc.inline_shapes) >= 4, (
        f"expected >=4 charts (s-curve, density, cost tornado, schedule tornado, "
        f"risk matrix, waterfall); found {len(doc.inline_shapes)}"
    )


def test_word_doc_omits_the_retired_dp_review_caveat(tmp_path: Path):
    """PRESENT-01 (D-4): the page-7 DP Review classification caveat was dev-only.

    Same shape as the callouts above - composed, emptied, never rendered.
    """
    path, composed = _generate_v3_doc(tmp_path)
    text = _read_doc_text(path)
    assert "DP Review classification caveat" not in text


def test_word_doc_includes_standards_references(tmp_path: Path):
    path, composed = _generate_v3_doc(tmp_path)
    text = _read_doc_text(path)
    assert "Standards references" in text
    assert "AACE" in text  # at least one AACE standard cited
    assert "PMI" in text or "ISO" in text


def test_word_doc_includes_limitations_section(tmp_path: Path):
    path, composed = _generate_v3_doc(tmp_path)
    text = _read_doc_text(path)
    assert "Limitations of current analysis" in text
    assert "deferred" in text.lower()
