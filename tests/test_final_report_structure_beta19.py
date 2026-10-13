"""SR-S3-Beta-19 §8 — final report structure tests.

Asserts the Beta-19 structural deltas land in the rendered artefacts:

* Three H1 anchors in order: Executive summary → Main report → Appendix.
* Risk matrix block sits in the Appendix, not in the Schedule drivers
  section (the schedule drivers section carries the
  forward-reference sentence instead).
* Forward-reference sentence rendered in the schedule drivers section.

These are unit-level / docx-level tests against synthetic composed
dicts. The slow E2E test ``test_run_refproject_beta19_smoke`` exercises
the full nbconvert path and is in a separate file.
"""
from __future__ import annotations

from pathlib import Path

import pytest

docx = pytest.importorskip("docx")
Document = docx.Document


def _read_body_paragraphs(path: Path) -> list[str]:
    doc = Document(str(path))
    return [p.text for p in doc.paragraphs]


def _read_heading_sequence(path: Path) -> list[tuple[int, str]]:
    """Return [(level, text)] for every paragraph styled as a heading.

    Heading levels in python-docx are surfaced via paragraph style
    names ('Heading 1', 'Heading 2', etc.). Non-heading paragraphs are
    skipped.
    """
    doc = Document(str(path))
    out: list[tuple[int, str]] = []
    for p in doc.paragraphs:
        style = (p.style.name or "") if p.style else ""
        if style.startswith("Heading "):
            try:
                lvl = int(style.split()[-1])
            except ValueError:
                continue
            out.append((lvl, p.text))
    return out


def _composed_minimal() -> dict:
    """Synthetic composed dict sufficient to exercise the v3 renderer.

    Includes the ``page1_headline`` key (v3-layout gate) plus the
    keys the renderer needs to emit the three H1 anchors and the
    schedule drivers forward-reference. Other optional v3 fields are
    omitted; missing ones cause sub-sections to be skipped without
    raising.
    """
    return {
        # v3 layout gate.
        "page1_headline": {
            "P80": "$0.00M",
            "P80_low": "$0.00M",
            "P80_high": "$0.00M",
            "title": "TOC contingency (P80)",
        },
        "page1_range_table": [],
        "report_mode": "prod",
        "executive_summary": {
            "headline_contingency_range_p80": {
                "low": 0, "high": 0, "currency": "$M",
            },
            "top_3_cost_drivers": [],
            "top_3_schedule_drivers": [],
            "schedule_basis_note": "",
            "key_findings": [],
            "methodology_caveats": [],
            "recommendations": [],
        },
        "appendix_audit_trail": {
            "register_path": "x",
            "strawman_path": "y",
            "run_date": "2026-05-13",
            "engine_versions": {"final": "SP22"},
        },
        "disclaimer_paragraphs": ["A", "B", "C", "D"],
        "page2_distribution": {},
        "page2_confidence_curve": [],
        "page2_confidence_curve_preamble": "",
        "page2_confidence_curve_footnote": "",
        "page3_cost_drivers": {
            "orienting": "", "tornado_path": "", "drivers_table": [],
            "mode_independence_note": "", "interpretation": "",
        },
        "page4_schedule_drivers": {
            "orienting_tornado": "",
            "tornado_path": "",
            "drivers_table": [],
            "interpretation_tornado": "",
            "criticality_reframe": "",
            "orienting_matrix": "Matrix orient",
            "risk_matrix_path": "",  # no image; H2+text only when path truthy
            "interpretation_matrix": "Matrix interp",
            "risk_matrix_forward_reference": (
                "An explanatory comparison of the traditional vs "
                "probability-weighted risk matrix is included in the "
                "appendix."
            ),
        },
        "page5_reconciliation": {},
        "page6_action_implications": {
            "treatment_roi_table": None,
            "recommendations": [],
            "orienting": "",
            "interpretation": "",
            "banner": "",
        },
        "page7_methodology": {
            "methodology_summary": "",
            "standards_references": [],
            "limitations": [],
            "single_iteration_intro": "",
            "single_iteration_walkthrough": "",
        },
        "page8_audit_trail": {
            "register_path": "x", "strawman_path": "y",
            "run_date": "2026-05-13", "engine_versions": {},
            "reproducibility_paragraph": "",
            "cross_validation_sentence": "",
            "input_hashes": {},
        },
        "page4b_criticality": {},
        "callouts": {},
        "recommendation_metric": "P80",
    }


def test_beta19_three_h1_anchors_present_and_in_order(tmp_path: Path) -> None:
    """The rendered docx contains the three Beta-19 H1 anchors in the
    expected sequence: Executive summary → Main report → Appendix.
    """
    from src.final.word_generator import generate_word_summary

    composed = _composed_minimal()
    # Force the v3 layout path by ensuring the composed dict carries the
    # v3 page keys (it does — see _composed_minimal above).
    out = tmp_path / "beta19_structure.docx"
    generate_word_summary(
        summary_data=composed["executive_summary"],
        audit_trail_data=composed["appendix_audit_trail"],
        disclaimer_paragraphs=composed["disclaimer_paragraphs"],
        cross_validation={"all_pass": True},
        output_path=out,
        composed=composed,
    )

    headings = _read_heading_sequence(out)
    h1_texts = [t for (lvl, t) in headings if lvl == 1]

    assert "Executive summary" in h1_texts, (
        f"Executive summary H1 missing; h1s = {h1_texts}"
    )
    assert "Main report" in h1_texts, (
        f"Main report H1 missing; h1s = {h1_texts}"
    )
    assert "Appendix" in h1_texts, (
        f"Appendix H1 missing; h1s = {h1_texts}"
    )

    exec_idx = h1_texts.index("Executive summary")
    main_idx = h1_texts.index("Main report")
    app_idx = h1_texts.index("Appendix")
    assert exec_idx < main_idx < app_idx, (
        f"H1 order wrong; expected Exec < Main < Appendix, got "
        f"{[h1_texts[i] for i in (exec_idx, main_idx, app_idx)]}"
    )


def test_beta19_risk_matrix_in_appendix_not_schedule_drivers(tmp_path: Path) -> None:
    """The risk matrix H2 heading sits AFTER the Appendix H1, not
    inside the schedule drivers section. Verified by walking the
    heading sequence: the Risk matrix heading must appear after the
    Appendix H1 in document order.
    """
    from src.final.word_generator import generate_word_summary

    composed = _composed_minimal()
    composed["page4_schedule_drivers"]["risk_matrix_path"] = (
        # A path that doesn't exist will still cause the H2 + text to
        # render; only the image insertion is skipped on missing path.
        # But the section is gated on truthiness of risk_matrix_path,
        # so we use a non-empty placeholder.
        "non-empty-placeholder-path"
    )
    out = tmp_path / "beta19_matrix.docx"
    generate_word_summary(
        summary_data=composed["executive_summary"],
        audit_trail_data=composed["appendix_audit_trail"],
        disclaimer_paragraphs=composed["disclaimer_paragraphs"],
        cross_validation={"all_pass": True},
        output_path=out,
        composed=composed,
    )

    headings = _read_heading_sequence(out)
    # Find the index of the Appendix H1 and the Risk matrix H2.
    appendix_idx = next(
        (i for i, (lvl, t) in enumerate(headings)
         if lvl == 1 and t == "Appendix"),
        None,
    )
    matrix_idx = next(
        (i for i, (lvl, t) in enumerate(headings)
         if "Risk matrix" in t and "explanatory" in t),
        None,
    )
    assert appendix_idx is not None, (
        f"Appendix H1 not in headings: {headings}"
    )
    assert matrix_idx is not None, (
        f"Risk matrix H2 not in headings: {headings}"
    )
    assert matrix_idx > appendix_idx, (
        f"Risk matrix H2 appears at index {matrix_idx}, before the "
        f"Appendix H1 at index {appendix_idx}: matrix relocation "
        f"failed. Headings: {headings}"
    )


def test_beta19_schedule_drivers_has_forward_reference(tmp_path: Path) -> None:
    """The schedule drivers section carries the Beta-19 forward-
    reference sentence pointing readers at the appendix risk matrix.
    """
    from src.final.word_generator import generate_word_summary

    composed = _composed_minimal()
    out = tmp_path / "beta19_forward.docx"
    generate_word_summary(
        summary_data=composed["executive_summary"],
        audit_trail_data=composed["appendix_audit_trail"],
        disclaimer_paragraphs=composed["disclaimer_paragraphs"],
        cross_validation={"all_pass": True},
        output_path=out,
        composed=composed,
    )

    body = "\n".join(_read_body_paragraphs(out))
    assert "included in the appendix" in body, (
        "Beta-19 forward-reference sentence missing from schedule "
        "drivers section."
    )
