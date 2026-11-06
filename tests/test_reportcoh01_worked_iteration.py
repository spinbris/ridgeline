"""REPORTCOH-01 R3: Appendix A works one iteration from the risks that fired to its contingency.

Built on a three-iteration stand-in run so every number can be checked by hand: the iteration
chosen is the one nearest the P80, the table's figures are that iteration's, and each sentence
of the reconciliation multiplies and adds out.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from src.final import report_guard as g
from src.final.sections import worked_iteration as wi

RATE = 35_000.0


def _beta() -> dict:
    # Three iterations; two risks: R1 cost and delay (dual), R2 cost only.
    per_cost = np.array([[0.0, 0.0], [1_000_000.0, 500_000.0], [2_000_000.0, 0.0]])
    injected = np.array([[0.0], [30.0], [60.0]])
    return {
        "cost_dollars_array": per_cost.sum(axis=1),
        "schedule_days_array": np.array([0.0, 20.0, 60.0]),  # 10 days of float in iteration 2
        "per_risk_cost_array": per_cost,
        "per_risk_schedule_pre_mode_array": injected,
        "fired_array": per_cost > 0,
        "risk_ids_all": ["R1", "R2"],
        "risk_ids_dual": ["R1"],
        "risk_drivers": {"R1": SimpleNamespace(gating_activity_id="A1")},
        "schedule_graph": SimpleNamespace(activities={"A1": SimpleNamespace(name="Gate one")}),
    }


RISKS = [SimpleNamespace(risk_id="R1", probability=0.4), SimpleNamespace(risk_id="R2",
                                                                         probability=0.3)]


def test_the_iteration_nearest_the_p80_is_chosen():
    totals = np.array([0.0, 2.2e6, 4.1e6])
    target = np.percentile(totals, 80)
    assert wi.pick_iteration(totals) == int(np.argmin(np.abs(totals - target)))


def test_table_lists_what_fired_with_its_gate_and_a_total():
    out = wi.worked_iteration(_beta(), day_rate=RATE, risks=RISKS, titles={"R1": "One"},
                              p_level=50)
    rows = out["worked_iteration_table"]
    assert rows[0] == {"Risk": "R1 One", "Probability": "40%", "Cost drawn ($M)": "$1.00M",
                       "Delay injected (working days)": "30.0", "Gating activity": "Gate one"}
    assert rows[1]["Gating activity"] == "cost only"
    assert rows[-1]["Risk"] == "Total" and rows[-1]["Cost drawn ($M)"] == "$1.50M"


def test_reconciliation_adds_out():
    out = wi.worked_iteration(_beta(), day_rate=RATE, risks=RISKS, titles={}, p_level=50)
    text = " ".join(out["worked_iteration_steps"])
    assert "add to 30.0 working days" in text and "by 20.0" in text
    assert "10.0 working days were absorbed" in text
    # 20 days at $35,000 = $0.70M; plus $1.50M of cost = $2.20M.
    assert "$0.70M of delay cost" in text and "$2.20M, this iteration's" in text
    assert g.unpriced_days(text) == []


def test_the_appendix_passes_the_guard():
    out = wi.worked_iteration(_beta(), day_rate=RATE, risks=RISKS, titles={}, p_level=50)
    text = "\n".join([out["worked_iteration_intro"], *out["worked_iteration_steps"]])
    assert g.check_page(f"<p>{text}</p>") == []


def test_owner_view_line_only_when_the_run_has_one():
    beta = _beta()
    assert not any("owner view" in s for s in wi.worked_iteration(
        beta, day_rate=RATE, risks=RISKS, titles={}, p_level=50)["worked_iteration_steps"])
    beta["base_layer"] = {"owner_view": {"finish_days": np.array([300.0, 330.0, 370.0]),
                                         "deterministic_finish_days": 300.0}}
    steps = wi.worked_iteration(beta, day_rate=RATE, risks=RISKS, titles={},
                                p_level=50)["worked_iteration_steps"]
    assert "working day 330, 30 working days after the plan" in steps[-1]


def test_chart_is_drawn_when_there_is_a_folder(tmp_path):
    out = wi.worked_iteration(_beta(), day_rate=RATE, risks=RISKS, titles={}, p_level=50,
                              chart_dir=tmp_path)
    assert out["worked_iteration_chart_path"].endswith("appendix_a_worked_iteration.png")
    assert (tmp_path / "appendix_a_worked_iteration.png").exists()


def test_no_run_no_appendix():
    assert wi.worked_iteration(None, day_rate=RATE, risks=None, titles=None) == {}
