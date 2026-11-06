"""REPORTCOH-01 R2: the report's order, and the new sections' sentences, follow their numbers.

Three surfaces:

* the section list is one list: ``report_layout.SECTIONS`` (which builds each section) and
  ``presentation_contract.HTML_SECTIONS`` (which the contract tests read) must agree, key for key
  and heading for heading, and the notebook's PAGES list must name the same keys in order;
* each builder that turns a number into a sentence is tested on numbers built for it;
* the summary and the which-number box quote the run's figures and nothing else.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.final import presentation_contract as pc
from src.final import report_guard as g
from src.final.sections import report_layout as rl

REPO = Path(__file__).resolve().parents[1]


# --- 1. one section list -----------------------------------------------------------------

def test_layout_sections_match_the_contract():
    contract = [(s.composed_keys[0], s.heading) for s in pc.HTML_SECTIONS]
    assert contract == list(rl.SECTIONS)


def test_notebook_renders_the_sections_in_order():
    nb = json.loads((REPO / "final_runner.ipynb").read_text(encoding="utf-8"))
    src = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    keys = re.findall(r'\("(rpt_[a-z_]+)",', src)
    assert keys == [k for k, _ in rl.SECTIONS]


def test_every_rendered_key_is_in_the_contract():
    for key, _ in rl.SECTIONS:
        assert key in {k for s in pc.HTML_SECTIONS for k in s.composed_keys}


# --- 2. sentence builders ----------------------------------------------------------------

def _facts(**over):
    f = {"p50": 10.16e6, "p80": 14.41e6, "p90": 16.90e6, "planned_finish_wd": 305.0,
         "start": None, "finish_wd": {50: 373.0, 80: 407.0, 90: 425.0},
         "owner_p80_finish_wd": 422.0, "day_rate": 35_000.0,
         "loo_top": [{"risk_id": "WT-008", "saved_dollars": 1.33e6},
                     {"risk_id": "WT-021", "saved_dollars": 1.12e6},
                     {"risk_id": "WT-009", "saved_dollars": 0.92e6}],
         "cv_pass": True,
         "total": {50: 137.89e6, 80: 146.45e6, 90: 150.87e6}, "declared_base": 120e6,
         "base_median": 126.85e6,
         "jcl": {"jcl": 0.33, "cost_confidence": 0.35, "finish_confidence": 0.80,
                 "cost_target": 134.41e6}}
    f.update(over)
    return f


def test_summary_table_quotes_the_run():
    rows = {r["Item"]: r["Value"] for r in rl.summary_table(_facts(), {"WT-008": "WTG"})}
    assert rows["Event-risk contingency, P80 (recommended)"] == "$14.41M"
    assert "$10.16M" in rows["Event-risk contingency, P50 and P90"]
    assert "WT-008" in " ".join(rows.values())


def test_which_number_states_the_base_below_its_median_only_when_it_is():
    above = " ".join(rl.which_number(_facts()))
    assert "below its own median" in above and "$126.85M" in above
    below = " ".join(rl.which_number(_facts(base_median=118e6)))
    assert "below its own median" not in below


def test_which_number_passes_the_guard():
    text = "\n".join(rl.which_number(_facts()))
    assert g.retired_terms(text) == [] and g.unpriced_days(text) == []


def test_finish_table_counts_delay_from_the_plan():
    rows = rl.finish_table(_facts())
    assert [r["Delay after the plan (working days)"] for r in rows] == ["68", "102", "120"]


def test_schedule_loo_ranks_by_finish_saved_and_keeps_schedule_risks_only():
    beta = {"risk_ids_dual": ["A", "B"], "leave_one_out": {"rows": [
        {"risk_id": "A", "finish_saved_days": 3.0, "saved_dollars": 1.0},
        {"risk_id": "B", "finish_saved_days": 9.0, "saved_dollars": 1.0},
        {"risk_id": "C", "finish_saved_days": 20.0, "saved_dollars": 1.0}]}}
    table = rl.schedule_loo_table(beta, {})
    assert [r["Risk"] for r in table] == ["B", "A"]
    assert "removing B alone" in rl.schedule_loo_sentence(table)


def test_criticality_sentence_counts_bands():
    crit = {"distribution_summary": {"n_activities_total": 100, "band_counts": {
        "always (90%+)": 10, "often (70-90%)": 2, "near (30-70%)": 3, "rarely (10-30%)": 4}}}
    out = rl.criticality_sentence(crit)
    assert "Of 100 activities, 10 are" in out and "9 in between" in out


def test_actions_value_at_stake_is_the_leave_one_out():
    beta = {"leave_one_out": {"rows": [
        {"risk_id": "WT-008", "saved_dollars": 1.33e6, "finish_saved_days": 11.3},
        {"risk_id": "WT-012", "saved_dollars": 0.5e6, "finish_saved_days": 0.0}]}}
    mits = [{"mitigation_id": "MIT-01", "risk_id": "WT-008", "description": "Expedite",
             "cost_aud": 1.08e6, "status": "Actioned", "period_end": "31/05/2026"}]
    table = rl.actions_table(mits, beta, {})
    assert table[0]["Value at stake at P80 ($M)"] == "$1.33M"
    text = " ".join(rl.actions_text(table, beta, mits, "31/05/2026"))
    assert "WT-012" in text and "31/05/2026" in text


def test_no_mitigations_says_so():
    text = " ".join(rl.actions_text([], {"leave_one_out": {"rows": []}}, [], ""))
    assert "No mitigations are logged" in text


def test_logged_mitigations_without_a_glob_is_empty():
    assert rl.logged_mitigations(None) == ([], "")


def test_layout_is_a_no_op_without_the_replay():
    c: dict = {}
    rl.build_report_layout(c, None, day_rate=35_000.0, total_cost=None, jcl=None, risks=None,
                           risk_titles=None, run_date=None, status_period_glob=None)
    assert c == {}


def test_glossary_and_disclaimer_pass_the_guard():
    text = "\n".join([*(f"{r['Term']} {r['Meaning']}" for r in rl.GLOSSARY),
                      *(p.format(project_note="") for p in rl.DISCLAIMER_PARAGRAPHS)])
    assert g.check_page(f"<p>{text}</p>") == []


def test_finish_date_uses_the_five_day_rule():
    import datetime as dt
    assert rl.finish_date(dt.date(2025, 4, 28), 305.0) == dt.date(2026, 6, 29)
    assert rl.finish_date(None, 1.0) is None


# --- 3. the Word documents' fixed texts --------------------------------------------------

def test_word_fixed_texts_carry_no_retired_term():
    # The Word summary is not a rendered page the guard reads, so its fixed texts are read here.
    from src.final import commentary_text as ct
    from src.final import stage3_beta_report as sb
    from src.final import word_generator as wg
    texts = [*wg.BETA_BANNER_LINES, sb._GENERIC_PREVIEW_BANNER_TEXT,
             ct.SCHEDULE_DAYS_CONTEXT_STAGE3, ct.DOMINANT_RISK_TEMPLATE_STAGE3,
             ct.DOMINANT_RISK_FALLBACK_STAGE3, ct.SCHEDULE_DRIVERS_MODE_COLUMN_FOOTNOTE_STAGE3,
             ct.CRITICALITY_FORWARD_REFERENCE_TO_NOTE,
             *ct._GENERIC_MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3]
    for t in texts:
        assert g.retired_terms(t) == [], t


def test_word_headline_heading_names_the_method():
    s = next(s for s in pc.WORD_SECTIONS if s.name == "stage3_headline")
    assert "CPM replay" in s.heading and g.retired_terms(s.heading) == []
