"""SR15, Stage 3 D3 methodology section + D4 Table 6 footnote tests.

Director-locked text under SR15 Decisions 3 and 4 (2026-05-16). The
tests verify:

* The three D3 paragraphs are present in :mod:`src.final.commentary_text`
  as ``MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3`` and match the
  brief's locked wording verbatim (including the markdown ``**lead.**``
  markers used by the docx renderer to promote each paragraph's lead
  phrase to a bold run).
* The D4 schedule-drivers Table 6 footnote is present as
  ``SCHEDULE_DRIVERS_MODE_COLUMN_FOOTNOTE_STAGE3`` and matches the
  brief's locked wording.
* The Stage 3 standalone composer
  (:func:`src.final.stage3_composer.compose_stage3_standalone_data`)
  overlays both keys onto the composed dict at the documented
  locations (``page7_methodology`` for D3, ``page4_schedule_drivers``
  for D4). The Stage 2.5 composer
  (:func:`src.final.composer.compose_final_report_data`) does NOT set
  these keys (lock-by-omission for the Stage 2.5 deliverable).
* The Stage 3 docx body contains the new H2 subsection inside the
  "Methodology and caveats" H1, with the heading text matching the
  Director-locked constant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

docx = pytest.importorskip("docx")
Document = docx.Document

# Stage 4 F-33 (08/09/2026): paragraphs 2 and 3 below are the REFERENCE PROJECT's narrative (SR16
# collapse figures, the 20.C.95.EI.466 gating collision, Director D8.1), now held in that binding
# and resolved per project. The lock is unchanged in strength; it is pinned to the project it
# describes rather than to every project's report.
pytestmark = pytest.mark.project("synthetic_wind")


# ---------------------------------------------------------------------------
# Expected verbatim text (Director-locked under SR15 Decisions 3 and 4)
# ---------------------------------------------------------------------------

EXPECTED_D3_PARAGRAPHS: list[str] = [
    (
        "**Mode multipliers and the full-CPM approach.** This "
        "deliverable uses the full Critical Path Method (CPM) replay "
        "against the .xer schedule network without applying Mode "
        "multipliers (Series 1.0 / Hybrid 0.5 / Parallel 0.0). The CPM "
        "kernel walks the network each iteration, applies per-iteration "
        "risk impacts at the bound activities, and recomputes the "
        "critical path; float consumption is handled by the kernel "
        "mechanics. Mode multipliers were retained in the Stage 2.5 "
        "deliverable as a practitioner-judgement layer where no CPM "
        "kernel was available; in Stage 3 that layer would double-count "
        "on the CPM mechanics and is not applied."
    ),
    # SR17, D8.1 reword: paragraph 2 reframes the headline figure as
    # the SR16 collapse outcome (<pre_sr16_p80>d to <stage3_p80>d) rather than the prior
    # "over-binding artefact" forcing-function framing; paragraph 3
    # promotes the figure to current production headline (was preview-
    # banner-flagged "forcing function, not defensible"). The Mode-
    # multiplier paragraph 1 is unchanged, that text is SR15
    # methodology-bearing and Director D8.1 did not amend it.
    (
        "**Implication for the headline figure.** With Mode multipliers "
        "retired, the per-risk activity scope (the auto-mapper's "
        "binding of each risk to schedule activities) and the per-risk "
        "injection methodology become the dominant input controls. SR16 "
        "(2026-05-17) flipped the binding default to discrete-event "
        "additive injection with an auto-picked gating activity per "
        "risk; this collapsed the prior over-binding artefact (5 of 8 "
        "Time=Yes risks binding to <n>-<m> longest-path activities each "
        "and broadcasting per-fire impact across all bound activities) "
        "down from a <pre_sr16_p80>-day P80 to the current <stage3_p80>-day P80 / <stage3_mean>-"
        "day mean. The auto-mapper still binds the same broad activity "
        "sets, but only the single gating activity per risk now carries "
        "the discrete injection, the broadcast effect is gone. A "
        "remaining feature of the current pattern catalogue is that "
        "five of the eight dual-coded risks (R013, R015.1, R016.1, "
        "R026.1, R067) land on the same gating activity "
        "(20.C.95.EI.466, the latest-finish activity in the "
        "construction-area electrical-instrumentation cohort); see the "
        "gating-collision note in §5.3."
    ),
    (
        "**What to read from this headline.** The figure is "
        "methodologically defensible as the current production headline "
        "(Director D8.1, 2026-05-18) and is suitable as a working "
        "headline for the DP review pending workshop sign-off on the "
        "gating-activity selection rule. Pattern-catalogue "
        "differentiation that would split the five-way gating collision "
        "is a candidate for further work."
    ),
]

EXPECTED_D3_HEADING: str = "Mode multipliers and the full-CPM approach"

EXPECTED_D4_FOOTNOTE: str = (
    "Mode classification (Series / Hybrid / Parallel) is shown for "
    "context. Under the Stage 3 full-CPM methodology (post-SR15), Mode "
    "does not affect the per-iteration impact magnitude, the CPM "
    "kernel handles float consumption directly. The Mode column "
    "reflects the strawman classification carried forward from Stage 2.5 "
    "for reporting consistency."
)


# ---------------------------------------------------------------------------
# Tests, constants match brief-locked wording verbatim
# ---------------------------------------------------------------------------

class TestVerbatimWording:
    """Constants in ``commentary_text`` match the brief's Director-locked
    wording exactly. Any wordsmithing would silently break the audit
    trail for Director sign-off; the verbatim test is the lock."""

    # REFRETIRE-01 (D-2): the verbatim paragraph test that stood here pinned three
    # paragraphs whose second and third were the retired binding's own (its SR16 figures, its
    # gating collision). They retired with it; what a project without them gets is the generic
    # fallback, asserted in tests/test_stage5_f33_standalone_narrative.py.

    def test_d3_heading_matches_verbatim(self) -> None:
        from src.final.commentary_text import (
            MODE_MULTIPLIERS_FULL_CPM_HEADING_STAGE3,
        )
        assert MODE_MULTIPLIERS_FULL_CPM_HEADING_STAGE3 == EXPECTED_D3_HEADING

    def test_d4_footnote_matches_verbatim(self) -> None:
        from src.final.commentary_text import (
            SCHEDULE_DRIVERS_MODE_COLUMN_FOOTNOTE_STAGE3,
        )
        assert SCHEDULE_DRIVERS_MODE_COLUMN_FOOTNOTE_STAGE3 == EXPECTED_D4_FOOTNOTE


# ---------------------------------------------------------------------------
# Tests, composer overlay is wired and lock-preserving
# ---------------------------------------------------------------------------

def _minimal_composed_for_stage3_overlay() -> dict:
    """Build a synthetic Stage 2.5-shape composed dict the Stage 3
    composer can overlay on top of. Mirrors the
    ``_composed_minimal`` helper in
    ``tests/test_final_report_structure_beta19.py`` but stays inlined to
    avoid coupling this test file to that one."""
    return {
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
            "run_date": "2026-05-16",
            "engine_versions": {"final": "SR15"},
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
            "orienting_matrix": "",
            "risk_matrix_path": "",
            "interpretation_matrix": "",
            "risk_matrix_forward_reference": "",
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
            "summary_paragraphs": [],
            "standards_references": "",
            "limitations_current": [],
            "limitations_closing": "",
            "single_iteration_intro": "",
            "single_iteration_walkthrough": "",
        },
        "page8_audit_trail": {
            "register_path": "x", "strawman_path": "y",
            "run_date": "2026-05-16", "engine_versions": {},
            "reproducibility_paragraph": "",
            "cross_validation_sentence": "",
            "input_hashes": {},
        },
        "page4b_criticality": {},
        "callouts": {},
        "recommendation_metric": "P80",
    }


class TestComposerOverlay:
    """The Stage 3 composer wires D3 paragraphs into
    ``composed["page7_methodology"]`` and the D4 footnote into
    ``composed["page4_schedule_drivers"]``. The keys are present on the
    Stage 3 side and absent on the Stage 2.5 side."""

    def _apply_stage3_overlay(self, composed: dict) -> dict:
        """Apply the same overlay that
        :func:`compose_stage3_standalone_data` applies, without
        actually re-running the rich Stage 2.5 composer (which would
        require live engine inputs we don't have in a unit test).

        We exercise the overlay block directly to verify it sets the
        documented keys. The integration with
        :func:`compose_stage3_standalone_data` is exercised by the
        existing Stage 3 standalone smoke tests; this unit test
        targets the overlay arithmetic so a future composer-tier
        refactor cannot silently drop the SR15 keys."""
        from src.final import commentary_text
        _p7 = composed.get("page7_methodology")
        if isinstance(_p7, dict):
            _p7["mode_multipliers_full_cpm_heading"] = (
                commentary_text.MODE_MULTIPLIERS_FULL_CPM_HEADING_STAGE3
            )
            _p7["mode_multipliers_full_cpm_paragraphs"] = list(
                commentary_text.MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3
            )
        _p4 = composed.get("page4_schedule_drivers")
        if isinstance(_p4, dict):
            _p4["mode_column_footnote_stage3"] = (
                commentary_text.SCHEDULE_DRIVERS_MODE_COLUMN_FOOTNOTE_STAGE3
            )
        return composed

    def test_stage3_overlay_sets_page7_d3_keys(self) -> None:
        """The overlay carries the heading and whatever paragraphs the active project
        resolves to. REFRETIRE-01: the paragraphs are no longer pinned to a literal here -
        the literal was the retired binding's text."""
        from src.final import commentary_text

        composed = _minimal_composed_for_stage3_overlay()
        composed = self._apply_stage3_overlay(composed)
        p7 = composed["page7_methodology"]
        assert p7["mode_multipliers_full_cpm_heading"] == EXPECTED_D3_HEADING
        assert p7["mode_multipliers_full_cpm_paragraphs"] == (
            commentary_text.resolve_mode_multipliers_full_cpm_paragraphs())

    def test_stage3_overlay_sets_page4_d4_footnote(self) -> None:
        composed = _minimal_composed_for_stage3_overlay()
        composed = self._apply_stage3_overlay(composed)
        p4 = composed["page4_schedule_drivers"]
        assert p4["mode_column_footnote_stage3"] == EXPECTED_D4_FOOTNOTE

    def test_stage25_composed_does_not_set_d3_d4_keys(self) -> None:
        """Stage 2.5 lock-by-omission: a synthetic composed dict that
        has not been through the Stage 3 overlay must lack the SR15
        keys. The renderer skips the new section + footnote when keys
        are absent, so Stage 2.5 docx output is unaffected by SR15."""
        composed = _minimal_composed_for_stage3_overlay()
        assert "mode_multipliers_full_cpm_paragraphs" not in composed.get(
            "page7_methodology", {}
        )
        assert "mode_column_footnote_stage3" not in composed.get(
            "page4_schedule_drivers", {}
        )


# ---------------------------------------------------------------------------
# Tests, Stage 3 docx body carries the new section inside H1
# ---------------------------------------------------------------------------

class TestStage3DocxBodyCarriesNewSection:
    """AC5: the rendered Stage 3 docx contains the new H2 subsection
    inside the existing "Methodology and caveats" H1, with the heading
    text matching the Director-locked D3 constant. Driven via the
    word_generator entry point with a synthetic composed dict carrying
    the SR15 overlay keys.

    AC6: the schedule drivers section carries the D4 footnote in
    italic-9pt prose immediately after the drivers table.
    """

    def _build_stage3_composed(self) -> dict:
        from src.final import commentary_text
        composed = _minimal_composed_for_stage3_overlay()
        composed["page7_methodology"]["mode_multipliers_full_cpm_heading"] = (
            commentary_text.MODE_MULTIPLIERS_FULL_CPM_HEADING_STAGE3
        )
        composed["page7_methodology"]["mode_multipliers_full_cpm_paragraphs"] = list(
            commentary_text.MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3
        )
        composed["page4_schedule_drivers"]["mode_column_footnote_stage3"] = (
            commentary_text.SCHEDULE_DRIVERS_MODE_COLUMN_FOOTNOTE_STAGE3
        )
        return composed

    @staticmethod
    def _read_heading_sequence(path: Path) -> list[tuple[int, str]]:
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

    @staticmethod
    def _read_paragraph_texts(path: Path) -> list[str]:
        doc = Document(str(path))
        return [p.text for p in doc.paragraphs]

    def test_methodology_h2_present_inside_methodology_and_caveats_h1(
        self, tmp_path: Path,
    ) -> None:
        from src.final.word_generator import generate_word_summary
        composed = self._build_stage3_composed()
        out = tmp_path / "sr15_methodology_section.docx"
        generate_word_summary(
            summary_data=composed["executive_summary"],
            audit_trail_data=composed["appendix_audit_trail"],
            disclaimer_paragraphs=composed["disclaimer_paragraphs"],
            cross_validation={"all_pass": True},
            output_path=out,
            composed=composed,
        )
        headings = self._read_heading_sequence(out)
        # H1 anchor "Methodology and caveats" must precede the new H2.
        try:
            h1_idx = next(
                i for i, (lvl, t) in enumerate(headings)
                if lvl == 1 and t == "Methodology and caveats"
            )
        except StopIteration:
            pytest.fail(
                f"H1 'Methodology and caveats' missing from docx; "
                f"headings = {headings}"
            )
        # Among the H2s after the H1, our new heading must be present.
        h2_after_h1 = [
            t for (lvl, t) in headings[h1_idx + 1:] if lvl == 2
        ]
        assert EXPECTED_D3_HEADING in h2_after_h1, (
            f"D3 heading {EXPECTED_D3_HEADING!r} not found among H2s "
            f"after 'Methodology and caveats' H1; got {h2_after_h1}"
        )

    def test_d4_footnote_paragraph_present_in_body(self, tmp_path: Path) -> None:
        from src.final.word_generator import generate_word_summary
        composed = self._build_stage3_composed()
        out = tmp_path / "sr15_table6_footnote.docx"
        generate_word_summary(
            summary_data=composed["executive_summary"],
            audit_trail_data=composed["appendix_audit_trail"],
            disclaimer_paragraphs=composed["disclaimer_paragraphs"],
            cross_validation={"all_pass": True},
            output_path=out,
            composed=composed,
        )
        body_texts = self._read_paragraph_texts(out)
        assert EXPECTED_D4_FOOTNOTE in body_texts, (
            "D4 schedule-drivers Table 6 footnote not found verbatim in "
            "rendered docx body."
        )
