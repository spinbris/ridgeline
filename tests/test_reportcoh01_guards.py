"""REPORTCOH-01 R1: the report's words follow its numbers and its sections.

Review section 10 items 1 to 3. The report drifted for a year because nothing checked the
text: a retired method left its words behind, sentences claimed agreements the tables beside
them did not show, and references pointed at appendices that no longer existed. These tests
are the check, over three surfaces:

* the guard functions themselves (``src.final.report_guard``), on pages built to fail;
* the sentence builders that compare numbers (``src.final.sections.report_cohesion``), on
  tables built to sit each side of every threshold they test;
* the committed report page (``dashboard/public/report/index.html``), which predates this
  stage. It was ``xfail(strict=True)`` until the release re-cut; the re-cut page must pass.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.final import commentary_text, composer, headline
from src.final import report_guard as g
from src.final.sections import report_cohesion as rc

REPO = Path(__file__).resolve().parents[1]
REPORT_PAGE = REPO / "dashboard" / "public" / "report" / "index.html"


# --- 1. the guards bite ------------------------------------------------------------------

def test_retired_term_is_caught_and_named():
    probs = g.check_page("<p>The DP Review baseline and the All Series bound.</p>")
    assert any("dp review" in p for p in probs)
    assert any("all series" in p for p in probs)


def test_engagement_vocabulary_is_caught():
    # "Strawman" and "workshop input" came from the engagement this codebase was extracted from;
    # a reader of the product's report sees the register's methodology sheets instead.
    probs = g.check_page("<p>Strawman methodology workbook</p><p>Workshop input required</p>")
    assert any("strawman" in p for p in probs) and any("workshop input" in p for p in probs)


def test_provenance_names_inputs_in_words():
    from src.final.run_identity import provenance_markdown
    prov = {"input_sha256": {k: {"method": "git_blob_oid", "value": "ab" * 20}
                             for k in ("register", "xer", "strawman")}}
    page = provenance_markdown(prov)
    assert "methodology sheets" in page and g.retired_terms(page) == []


def test_register_field_names_are_not_retired_terms():
    # The register's own classification may be named; only the retired basis is barred.
    assert g.check_page("<p>The register carries Series, Hybrid or Parallel.</p>") == []


def test_na_cell_is_caught_but_not_inside_a_word_or_fraction():
    assert g.retired_terms("WT-020 | n/a | 0.4")
    assert g.retired_terms("value NaN")
    assert g.retired_terms("and/or a cost/n/a split") == []


def test_days_to_dollars_that_multiply_out_pass():
    # 70.7 days at $35,000 = $2.4745M, shown as $2.47M.
    text = "a mean finish delay of 70.7 working days, which is $2.47M of delay cost at " \
           "$35,000 per working day."
    assert g.unpriced_days(text) == []


def test_days_to_dollars_placeholder_is_caught():
    # E1: the old executive summary priced the mean delay with the mean cost.
    text = "70.1 days, equivalent to $8.07M at $35,000 per working day"
    probs = g.unpriced_days(text)
    assert len(probs) == 1 and "$2.45M" in probs[0]


def test_reference_to_a_present_section_passes():
    page = "<h2>Audit trail</h2><p>recorded in the audit trail appendix.</p>"
    assert g.orphan_references(g.page_text(page)) == []


def test_reference_to_an_absent_section_is_caught():
    page = "<h2>Audit trail</h2><p>documented in the Mode sensitivity appendix.</p>"
    probs = g.orphan_references(g.page_text(page))
    assert len(probs) == 1 and "mode sensitivity" in probs[0]


def test_bold_label_counts_as_a_target():
    page = "<p><strong>References</strong></p><p>listed under References in the appendices</p>"
    assert g.orphan_references(g.page_text(page)) == []


# --- 2. the Stage 3 texts carry no retired term ------------------------------------------

def _stage3_texts() -> dict[str, str]:
    texts = {name: getattr(commentary_text, name) for name in (
        "HEADLINE_OPENING_STAGE3", "SCHEDULE_TORNADO_ORIENTING_STAGE3",
        "RISK_MATRIX_ORIENTING_STAGE3", "RISK_MATRIX_INTERPRETATION",
        "INTEGRATED_TORNADO_INTERPRETATION", "STANDARDS_REFERENCES", "REPRODUCIBILITY")}
    texts.update({f"REFERENCES[{i}]": r for i, r in enumerate(commentary_text.REFERENCES)})
    texts.update({f"KEY_FINDINGS_STAGE3[{i}]": t
                  for i, t in enumerate(composer.KEY_FINDINGS_STAGE3)})
    texts.update({f"METHODOLOGY_CAVEATS_STAGE3[{i}]": t
                  for i, t in enumerate(composer.METHODOLOGY_CAVEATS_STAGE3)})
    texts["SCHEDULE_BASIS_NOTE_STAGE3"] = composer.SCHEDULE_BASIS_NOTE_STAGE3
    texts["SCHEDULE_DRIVERS_BASIS_STAGE3"] = composer.SCHEDULE_DRIVERS_BASIS_STAGE3
    texts["STAGE3_HEADLINE_BASIS"] = headline.STAGE3_HEADLINE_BASIS
    return texts


@pytest.mark.parametrize("name", sorted(_stage3_texts()))
def test_stage3_text_has_no_retired_term(name):
    assert g.retired_terms(str(_stage3_texts()[name])) == []


# --- 3. comparative sentences are built from the numbers they compare --------------------

DAYS, COST = "Schedule contingency (days)", "Cost contingency ($M)"


def _table(emv_d, emv_c, mean_d, mean_c, p80_d, rule10, rule20) -> pd.DataFrame:
    return pd.DataFrame([
        {"Approach": "Engineering judgement (10% of duration)", DAYS: rule10, COST: None},
        {"Approach": "Engineering judgement (20% of duration)", DAYS: rule20, COST: None},
        {"Approach": "EMV (sum of probability x Most Likely impact)", DAYS: emv_d, COST: emv_c},
        {"Approach": "Monte Carlo mean (CPM replay)", DAYS: mean_d, COST: mean_c},
        {"Approach": "Monte Carlo P80, cost and schedule each on its own", DAYS: p80_d,
         COST: emv_c * 1.5},
    ])


def test_agreement_is_claimed_only_within_tolerance():
    close = rc.comparison_interpretation(_table(100, 10, 103, 10.2, 130, 40, 80))
    assert "agrees with the expected-value sum" in close
    apart = rc.comparison_interpretation(_table(100, 10, 83, 12.2, 130, 40, 80))
    assert "agrees" not in apart
    assert "(-17%)" in apart and "(+22%)" in apart


def test_rules_of_thumb_below_the_result_are_said_to_fall_short():
    out = rc.comparison_interpretation(_table(100, 10, 83, 12, 130, 40, 80))
    assert "fall short" in out and "bracket" not in out


def test_rules_of_thumb_above_the_p80_are_said_to_exceed():
    out = rc.comparison_interpretation(_table(100, 10, 83, 12, 70, 90, 180))
    assert "exceed the simulated P80" in out


def test_rules_of_thumb_either_side_are_said_to_straddle():
    out = rc.comparison_interpretation(_table(100, 10, 83, 12, 130, 40, 160))
    assert "either side" in out


def test_no_table_no_sentence():
    assert rc.comparison_interpretation(None) == ""
    assert rc.comparison_interpretation(pd.DataFrame()) == ""


@pytest.mark.parametrize("value, word", [("-$0.22M", "below"), ("$0.40M", "above"),
                                         ("$0.00M", "nil")])
def test_waterfall_sentence_takes_its_sign_from_the_adjustment(value, word):
    rows = [{"Component": "Diversification adjustment", "P80": value}]
    assert word in rc.waterfall_interpretation(rows)


def test_waterfall_sentence_absent_without_the_row():
    assert rc.waterfall_interpretation([]) == ""


_LOO = {"p_level": 80, "rows": [
    {"risk_id": "WT-002", "saved_dollars": 2_340_000.0},
    {"risk_id": "WT-010", "saved_dollars": 1_100_000.0},
    {"risk_id": "WT-007", "saved_dollars": 900_000.0},
]}


def test_tornado_sentence_names_the_top_three_and_their_savings():
    out = rc.integrated_tornado_interpretation(_LOO)
    for rid, money in (("WT-002", "$2.34M"), ("WT-010", "$1.10M"), ("WT-007", "$0.90M")):
        assert rid in out and money in out


def test_recommendations_drop_the_orphan_and_use_the_leave_one_out():
    recs = rc._recommendations(_LOO, [
        "Treatment effort focused on WT-001 ($9.99M P80 contribution) reduces it.",
        "Use the per-risk diagnostic outputs (audit trail appendix) to drive plans.",
        "Keep this one.",
    ])
    assert recs[0].startswith("Treatment effort focused on WT-002") and "$2.34M" in recs[0]
    assert recs[1:] == ["Keep this one."]


# --- 4. the composed report under Stage 3 ------------------------------------------------

def _composed() -> dict:
    return {
        "page1_headline_interpretation": "The Stage 2.5 comparator range ...",
        "page1_range_table": [{"Scenario": "DP Review baseline"}],
        "page1_range_table_dedup_footnote": "x",
        "appendix_counterfactual": pd.DataFrame({"a": [1]}),
        "appendix_counterfactual_narrative": "12-scenario counterfactual",
        "page3_cost_drivers": {"tornado_path": "p.png", "drivers_table": [{"a": 1}]},
        "page4_schedule_drivers": {"mode_sensitivity_table": pd.DataFrame({"a": [1]}),
                                   "risk_matrix_forward_reference": "see the appendix"},
        "page5_reconciliation": {"comparison_table": None},
        "page6_action_implications": {"recommendations": []},
        "page7_methodology": {"dp_review_caveat": "DP Review", "mode_sensitivity_summary": {1: 2}},
    }


def test_cohesion_pass_is_a_no_op_without_stage3():
    c = _composed()
    rc.apply_stage3_cohesion(c, None)
    assert c["page1_range_table"] == [{"Scenario": "DP Review baseline"}]


def test_cohesion_pass_removes_the_retired_basis():
    c = _composed()
    rc.apply_stage3_cohesion(c, {"leave_one_out": _LOO})
    assert c["page1_range_table"] == [] and c["page1_headline_interpretation"] == ""
    assert c["appendix_counterfactual"] is None
    assert c["page3_cost_drivers"]["tornado_path"] == ""
    assert "WT-002" in c["page3_cost_drivers"]["interpretation"]
    assert c["page4_schedule_drivers"]["mode_sensitivity_table"] is None
    assert c["page4_schedule_drivers"]["risk_matrix_forward_reference"] == ""
    assert c["page7_methodology"]["dp_review_caveat"] == ""


# --- 5. the committed report page --------------------------------------------------------

def test_committed_report_page_passes_the_guards():
    if not REPORT_PAGE.exists():
        pytest.fail("no committed report page")
    assert g.check_page(REPORT_PAGE.read_text(encoding="utf-8")) == []
