"""Stage 4 F-33 (fixed under stage 5a, 08/09/2026): the Stage 3 standalone report carries no
other project's narrative.

Found on the Kestrel run: ``sra_stage3_standalone_PROD_DPReview_2026-09-08.html`` printed
``<pre_sr16_p80>d``, ``<stage3_p80>d`` and ``<stage3_mean>d`` six times each and a paragraph
about the reference engagement's five-of-eight gating collision on a construction-area
electrical-instrumentation activity - in a road project's report. The preview banner and the D3
methodology paragraphs were module constants written for the reference project; the cover caveat
had already gone binding-first (BINDINGSNAPSHOT-01) and these two had not.

The rule now: a binding that supplies ``stage3_preview_banner`` / ``stage3_methodology_paragraphs``
gets its own text verbatim; any other binding gets a generic text with no project figure, no
activity ID and no unrendered token.
"""
from __future__ import annotations

import pytest

from src.final import commentary_text, stage3_beta_report, stage3_composer
from src.final.stage3_beta_report import (
    build_stage3_beta_composed,
    render_stage3_beta_report_html,
    resolve_preview_banner,
)
from tests.conftest import TEST_CALIBRATION_TOLERANCES
from tests.final.test_sr11_stage3_beta_report import _make_synthetic_result

#: Text that belongs to the reference engagement and must not reach another project's page.
#: The tokens are the client-gate's redactions of that engagement's figures; the phrase and the
#: risk IDs are its narrative.
REFERENCE_ONLY = (
    "<pre_sr16_p80>", "<stage3_p80>", "<stage3_mean>",
    "electrical-instrumentation", "20.C.95.EI.466", "R013", "D8.1",
)


def _assert_none_of_reference(text: str, where: str) -> None:
    hits = [t for t in REFERENCE_ONLY if t in text]
    assert not hits, f"{where} carries the reference project's narrative: {hits}"


# --- the road project, the case stage 4 ran ---------------------------------------------------

@pytest.mark.project("synthetic_road")
def test_road_banner_and_paragraphs_carry_no_reference_narrative():
    _assert_none_of_reference(resolve_preview_banner(), "preview banner")
    # the §5.3 note the banner refers to: a project without one gets no note, not the reference's
    # (found in the Kestrel deliverable's page 4 by the stage 5a review)
    assert commentary_text.resolve_gating_collision_note() == ""
    assert commentary_text.GATING_COLLISION_NOTE_STAGE3 == ""
    for i, p in enumerate(commentary_text.resolve_mode_multipliers_full_cpm_paragraphs()):
        _assert_none_of_reference(p, f"D3 paragraph {i + 1}")
    # the module attributes resolve the same way (the composer reads them as attributes)
    _assert_none_of_reference(stage3_beta_report.PREVIEW_BANNER_TEXT, "PREVIEW_BANNER_TEXT")
    _assert_none_of_reference(stage3_composer.PREVIEW_BANNER_TEXT, "composer PREVIEW_BANNER_TEXT")
    for p in commentary_text.MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3:
        _assert_none_of_reference(p, "MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3")


@pytest.mark.project("synthetic_road")
def test_road_standalone_html_has_no_unrendered_token(tmp_path):
    """The symptom itself: the rendered page. Stage 4 counted six of each token."""
    result = _make_synthetic_result()
    composed = build_stage3_beta_composed(
        result, day_rate=48_000.0, run_date="2026-09-08",
        calibration_tolerances=TEST_CALIBRATION_TOLERANCES,
    )
    out = tmp_path / "stage3_standalone.html"
    render_stage3_beta_report_html(composed, out)
    html = out.read_text(encoding="utf-8")
    for token in ("<pre_sr16_p80>", "&lt;pre_sr16_p80&gt;", "<stage3_p80>", "&lt;stage3_p80&gt;",
                  "<stage3_mean>", "&lt;stage3_mean&gt;", "electrical-instrumentation"):
        assert token not in html, f"the road project's Stage 3 page prints {token!r}"
    assert "preview" in composed["preview_banner"].lower()


# REFRETIRE-01 (D-2): the test that stood here pinned the retired binding's own
# narrative verbatim - text that lived in that binding and retired with it.


# --- the rule, not the project: a binding without the key gets the generic text -------------

@pytest.mark.project("synthetic_wind")
def test_a_binding_without_the_keys_gets_the_generic_text():
    from src.sra.cpm.bindings import get_active_binding

    b = get_active_binding()
    assert not b.narrative("stage3_preview_banner")
    assert not b.narrative("stage3_methodology_paragraphs")
    assert resolve_preview_banner() == stage3_beta_report._GENERIC_PREVIEW_BANNER_TEXT
    assert (commentary_text.resolve_mode_multipliers_full_cpm_paragraphs()
            == commentary_text._GENERIC_MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3)
    # the resolver hands out a fresh list - a consumer mutating it cannot corrupt the fallback
    got = commentary_text.resolve_mode_multipliers_full_cpm_paragraphs()
    got.append("x")
    assert len(commentary_text.resolve_mode_multipliers_full_cpm_paragraphs()) == 2


def test_the_generic_text_itself_is_clean():
    """Red-first anchor: the fallback is what a stranger's project prints, so it is checked as a
    string, independent of any binding."""
    _assert_none_of_reference(stage3_beta_report._GENERIC_PREVIEW_BANNER_TEXT, "generic banner")
    for p in commentary_text._GENERIC_MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3:
        _assert_none_of_reference(p, "generic paragraph")
        assert "<" not in p and ">" not in p
