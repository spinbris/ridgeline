"""REPORTCOH-01 R1: the Stage 3 report says what Stage 3 does, and nothing it no longer does.

The report was built in layers (the Stage 2.5 Mode scenarios, then the Stage 3 CPM replay, then
the total-cost S-curve and shared drivers) and each layer added sections without retiring the
last one's. This pass runs after the composer, only when the Stage 3 replay leads, and:

* removes what belongs to the retired Mode-scenario basis: the comparator table and its
  paragraph, the 12-scenario counterfactual text and its empty appendix, the forward reference
  to an appendix the matrix is not in;
* makes the leave-one-out tornado the one cost ranking (Director D3, 05/11/2026), so the
  per-risk P80 chart and table, which ranked differently, are dropped;
* writes the sentences that compare numbers from the numbers themselves, so a sentence cannot
  claim agreement, a bracket or a sign the table beside it does not show.

Pure data: it edits the composed dict and returns nothing (hard invariant 9).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.final import commentary_text

#: Relative gap within which the expected-value and Monte Carlo means are said to agree.
#: Beyond it the report explains the gap instead.
AGREE_REL = 0.05


def _money(dollars: float) -> str:
    m = dollars / 1e6
    return f"-${abs(m):.2f}M" if m < 0 else f"${m:.2f}M"


def integrated_tornado_interpretation(loo: dict[str, Any] | None) -> str:
    """The leave-one-out paragraph, naming the top three risks and what each would save."""
    rows = list((loo or {}).get("rows") or [])
    if len(rows) < 3:
        return ""
    return commentary_text.INTEGRATED_TORNADO_INTERPRETATION.format(
        p=(loo or {}).get("p_level", 80),
        top1=rows[0]["risk_id"], saved1=_money(rows[0]["saved_dollars"]),
        top2=rows[1]["risk_id"], saved2=_money(rows[1]["saved_dollars"]),
        top3=rows[2]["risk_id"], saved3=_money(rows[2]["saved_dollars"]),
    )


def _row(table: pd.DataFrame, starts: str) -> pd.Series | None:
    hit = table[table["Approach"].astype(str).str.startswith(starts)]
    return None if hit.empty else hit.iloc[0]


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def comparison_interpretation(table: pd.DataFrame | None) -> str:
    """The reconciliation paragraph, every comparison read from the table it sits under.

    REPORTCOH-01 E2/E3: the fixed text claimed the Monte Carlo mean reconciled with EMV "within
    MC noise" (it was 17% and 22% away) and that the 10-20% rules of thumb bracketed the result
    (both sat below it). Each claim is now made only when the numbers support it.
    """
    if not isinstance(table, pd.DataFrame) or table.empty or "Approach" not in table:
        return ""
    days_col, cost_col = "Schedule contingency (days)", "Cost contingency ($M)"
    emv, mean, p80 = (_row(table, "EMV"), _row(table, "Monte Carlo mean"),
                      _row(table, "Monte Carlo P80"))
    out: list[str] = []
    if emv is not None and mean is not None:
        e_d, m_d = _num(emv[days_col]), _num(mean[days_col])
        e_c, m_c = _num(emv[cost_col]), _num(mean[cost_col])
        if e_d and m_d is not None:
            gap = (m_d - e_d) / e_d
            if abs(gap) <= AGREE_REL:
                out.append(f"The Monte Carlo mean slip ({m_d:.1f} days) agrees with the "
                           f"expected-value sum ({e_d:.1f} days) to within {abs(gap):.0%}.")
            else:
                out.append(
                    f"The Monte Carlo mean slip is {m_d:.1f} days against an expected-value sum "
                    f"of {e_d:.1f} days ({gap:+.0%}). The two are not meant to agree: the sum "
                    "adds every delay at its Most Likely value, while the replay draws each "
                    "delay from its full range and lets float absorb what does not reach the "
                    "finish.")
        if e_c and m_c is not None:
            gap = (m_c - e_c) / e_c
            if abs(gap) <= AGREE_REL:
                out.append(f"On cost the mean (${m_c:.2f}M) agrees with the expected value "
                           f"(${e_c:.2f}M) to within {abs(gap):.0%}.")
            else:
                out.append(
                    f"On cost the mean is ${m_c:.2f}M against ${e_c:.2f}M ({gap:+.0%}): the "
                    "expected value uses each risk's Most Likely cost, and the mean of a "
                    "right-skewed range sits above its Most Likely.")
    rules = [r for r in (_row(table, "Engineering judgement (10%"),
                         _row(table, "Engineering judgement (20%")) if r is not None]
    if rules and p80 is not None and mean is not None:
        lo = min(_num(r[days_col]) or 0.0 for r in rules)
        hi = max(_num(r[days_col]) or 0.0 for r in rules)
        m_d, p_d = _num(mean[days_col]) or 0.0, _num(p80[days_col]) or 0.0
        if hi < m_d:
            out.append(f"The 10% and 20% rules of thumb ({lo:.0f} and {hi:.0f} days) both fall "
                       f"short of the simulated mean ({m_d:.0f} days) and P80 ({p_d:.0f} days): "
                       "on this register a rule of thumb would under-provide for delay.")
        elif lo > p_d:
            out.append(f"The 10% and 20% rules of thumb ({lo:.0f} and {hi:.0f} days) both "
                       f"exceed the simulated P80 ({p_d:.0f} days).")
        else:
            out.append(f"The 10% and 20% rules of thumb ({lo:.0f} and {hi:.0f} days) sit either "
                       f"side of the simulated mean ({m_d:.0f} days) or P80 ({p_d:.0f} days).")
    out.append("Beyond the mean, the simulation adds what no deterministic method gives: the "
               "spread, and so the P80 and P95.")
    return " ".join(out)


def waterfall_interpretation(breakdown_rows: list[dict[str, Any]] | None) -> str:
    """The waterfall paragraph, its sign read from the joint-sampling adjustment it explains."""
    div = None
    for r in breakdown_rows or []:
        if str(r.get("Component", "")).startswith("Diversification"):
            text = str(r.get("P80", "")).replace("$", "").replace("M", "").replace(",", "")
            div = _num(text)
    if div is None:
        return ""
    if div < 0:
        return (f"At P80 the joint-sampling adjustment is {_money(div * 1e6)}: the worst cost "
                "outcomes and the worst delays do not always fall in the same iteration, so the "
                "integrated P80 is a little below the two P80s added together.")
    if div > 0:
        return (f"At P80 the joint-sampling adjustment is +{_money(div * 1e6)}: the same risks "
                "drive the cost and delay tails, so the integrated P80 is above the two P80s "
                "added together.")
    return "At P80 the joint-sampling adjustment is nil: the integrated P80 equals the sum."


def _recommendations(loo: dict[str, Any] | None, existing: list[str]) -> list[str]:
    """Page-6 recommendations on the leave-one-out ranking, with orphan references removed."""
    rows = list((loo or {}).get("rows") or [])
    out: list[str] = []
    for rec in existing:
        if rec.startswith("Treatment effort focused on"):
            if rows:
                out.append(
                    f"Treatment effort focused on {rows[0]['risk_id']} (removing it alone would "
                    f"save {_money(rows[0]['saved_dollars'])} of the P{loo.get('p_level', 80)} "
                    "contingency) reduces the contingency more than effort spread across the "
                    "long tail.")
            continue
        if rec.startswith("Use the per-risk diagnostic outputs"):
            # It pointed at diagnostic outputs the audit trail appendix does not contain.
            continue
        out.append(rec)
    return out


def apply_stage3_cohesion(composed: dict[str, Any], stage3_beta_result: dict[str, Any] | None,
                          ) -> None:
    """Rewrite the composed report for a Stage 3 run. A no-op when Stage 3 did not run."""
    if stage3_beta_result is None:
        return
    loo = stage3_beta_result.get("leave_one_out") or {}

    # Page 1: the Stage 2.5 comparator range and its paragraph.
    composed["page1_headline_interpretation"] = ""
    composed["page1_range_table"] = []
    composed["page1_range_table_dedup_footnote"] = None

    # The Mode-classification appendix: empty under Stage 3, and its heading with it.
    composed["appendix_counterfactual"] = None
    composed["appendix_counterfactual_narrative"] = None

    p3 = composed.get("page3_cost_drivers")
    if isinstance(p3, dict):
        # D3: the leave-one-out tornado is the one cost ranking.
        p3.update({"tornado_path": "", "drivers_table": [], "drivers_table_full": [],
                   "orienting": "", "mode_independence_note": "",
                   "interpretation": integrated_tornado_interpretation(loo)
                   or commentary_text.COST_TORNADO_INTERPRETATION})

    p4 = composed.get("page4_schedule_drivers")
    if isinstance(p4, dict):
        p4.update({"orienting_tornado": commentary_text.SCHEDULE_TORNADO_ORIENTING_STAGE3,
                   "orienting_mode_sens": "", "interpretation_mode_sens": "",
                   "mode_sensitivity_table": None, "risk_matrix_forward_reference": "",
                   "mode_column_footnote_stage3": "",
                   "orienting_matrix": commentary_text.RISK_MATRIX_ORIENTING_STAGE3,
                   "interpretation_matrix": commentary_text.RISK_MATRIX_INTERPRETATION})

    p5 = composed.get("page5_reconciliation")
    if isinstance(p5, dict):
        p5["interpretation"] = comparison_interpretation(p5.get("comparison_table"))
        p5["waterfall_interpretation"] = waterfall_interpretation(
            composed.get("page1_component_breakdown"))

    p6 = composed.get("page6_action_implications")
    if isinstance(p6, dict) and isinstance(p6.get("recommendations"), list):
        p6["recommendations"] = _recommendations(loo, p6["recommendations"])

    p7 = composed.get("page7_methodology")
    if isinstance(p7, dict):
        p7["dp_review_caveat"] = ""
        p7["mode_sensitivity_summary"] = {}
