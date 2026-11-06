"""REPORTCOH-01 R2: the technical report's sections, in the order a reader needs them.

The composer builds its pages in the order the method was built (distribution, cost drivers,
schedule drivers, reconciliation...), which put the joint-confidence text before the curve that
defines the headline, the waterfall in two places and the audit trail in two. This pass runs
last, only on a CPM replay run, and lays the same content out in the review's order
(review section 7), adding what a reader could not find before:

* a summary table and a "which number to use" box that relates the three dollar figures and
  the two finishes (review section 4 item 1, S11, D5);
* a project-and-inputs section, the planned finish, and finishes as dates (items 2, 3);
* the replay's own schedule evidence: activity criticality and leave-one-out on finish days
  (item 4, D2);
* the reason the joint confidence is what it is (item 5);
* Actions from the mitigations logged in the status periods, beside each risk's value at stake
  (D4, S16); a glossary; and a disclaimer that is a disclaimer.

Every number here is read from arrays and tables the run already produced: presentation, not
methodology. Pure data (hard invariant 9): it writes ``composed["report_sections"]``, a list of
``{"key", "heading", "content"}``, and returns nothing.
"""

from __future__ import annotations

import datetime as _dt
import glob
import logging
from pathlib import Path
from typing import Any

import numpy as np

from src.final import commentary_text
from src.final.sections.worked_iteration import worked_iteration

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Hours in a working day on the project-default calendar the replay uses.
HOURS_PER_DAY = 8.0

#: The order, and the heading, of every section. The keys are the composed keys the notebook's
#: PAGES list renders (presentation_contract.HTML_SECTIONS holds the same list).
SECTIONS: tuple[tuple[str, str], ...] = (
    ("rpt_summary", "## Summary"),
    ("rpt_inputs", "## Project and inputs"),
    ("rpt_contingency", "## Contingency"),
    ("rpt_schedule", "## Schedule"),
    ("rpt_drivers", "## Risk drivers"),
    ("rpt_total_cost", "## Total cost, shared drivers and joint confidence"),
    ("rpt_checks", "## Checks"),
    ("rpt_actions", "## Actions"),
    ("rpt_method", "## Method and limitations"),
    ("rpt_appendix_iteration", "## Appendix A - one iteration"),
    ("rpt_appendix_correlation", "## Appendix B - correlation groups"),
    ("rpt_appendix_audit", "## Appendix C - audit trail"),
    ("rpt_disclaimer", "## Disclaimer"),
)

GLOSSARY: list[dict[str, str]] = [
    {"Term": "Event risk",
     "Meaning": "A discrete risk in the register that may or may not happen, with a probability "
                "and a cost and delay range if it does (Layer 2)."},
    {"Term": "Base estimate",
     "Meaning": "The cost estimate before event risks, with its own uncertainty in rates, "
                "quantities and productivity (Layer 1)."},
    {"Term": "Event-risk contingency",
     "Meaning": "The allowance for event risks: their cost plus the delay cost of the finish "
                "delay they cause. The headline of this report."},
    {"Term": "CPM replay",
     "Meaning": "Each iteration re-runs the programme's own logic (the critical path method), so "
                "a delay reaches the finish only if float does not absorb it."},
    {"Term": "Gating activity",
     "Meaning": "The activity in the programme at which a risk's delay is injected."},
    {"Term": "Delay cost",
     "Meaning": "Finish delay priced at the day rate, which covers preliminaries and site "
                "overheads."},
    {"Term": "Owner view",
     "Meaning": "Base plus event risks plus the shared drivers: the whole project cost and "
                "finish."},
    {"Term": "Shared driver",
     "Meaning": "One uncertainty, such as productivity, that moves both cost and activity "
                "durations from the same draw."},
    {"Term": "Correlation group",
     "Meaning": "A set of event risks whose firing is correlated because they share a cause."},
    {"Term": "Leave-one-out",
     "Meaning": "The P80 with a risk, less the P80 with that risk removed and every other draw "
                "held fixed: what removing that risk alone would save."},
    {"Term": "P80",
     "Meaning": "The value that 80% of simulated outcomes do not exceed."},
    {"Term": "Joint confidence level (JCL)",
     "Meaning": "The share of iterations that meet a budget and a finish date together."},
    {"Term": "Working day",
     "Meaning": "A day on the project's five-day calendar. Dates are counted from the "
                "programme's start without holidays."},
]

DISCLAIMER_PARAGRAPHS: tuple[str, ...] = (
    "This report demonstrates a method. {project_note}",
    "It is not advice and must not be relied on for funding, investment, contract or "
    "procurement decisions. The figures are the output of a model and are only as good as the "
    "register, programme and estimate it was given.",
    "What the figures do not cover: escalation beyond the estimate's own rates, financing and "
    "interest during construction, liquidated damages, per-party allocation of risk, and any "
    "risk not in the register.",
    "The software is licensed under the Business Source License 1.1. The method follows the "
    "references in Method and limitations; it is not endorsed by any of those bodies.",
)


# ---------------------------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------------------------

def _m(dollars: float) -> str:
    m = float(dollars) / 1e6
    return f"-${abs(m):.2f}M" if m < 0 else f"${m:.2f}M"


def _date(d: _dt.date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def finish_date(start: _dt.date | None, working_days: float) -> _dt.date | None:
    """A finish ``working_days`` after ``start``, on the 5/7 rule the app uses (no holidays)."""
    if start is None:
        return None
    from src.am.json_writer import _working_days_to_calendar_date
    return _working_days_to_calendar_date(start, float(working_days))


def _project_start(beta: dict[str, Any]) -> _dt.date | None:
    try:
        from src.sra.cpm.xer_reader import xer_project_start
        return xer_project_start(beta["xer_tables"])
    except Exception:  # a section-seam fixture carries no schedule tables
        return None


# ---------------------------------------------------------------------------------------------
# the numbers the new sections quote
# ---------------------------------------------------------------------------------------------

def report_facts(composed: dict[str, Any], beta: dict[str, Any], *, day_rate: float,
                 total_cost: dict[str, Any] | None, jcl: dict[str, Any] | None,
                 risks: list[Any] | None) -> dict[str, Any]:
    """Every figure the summary, the box and the inputs section quote, read from the run."""
    es = composed.get("executive_summary") or {}
    head = (es.get("headline_stage3") or {}).get("percentiles_dollars") or {}
    sched = beta.get("schedule_result")
    finish = np.asarray(getattr(sched, "project_finish_days", []), dtype=float)
    base_layer = beta.get("base_layer") or {}
    owner = base_layer.get("owner_view") or {}
    # The planned finish is the zero-risk pass the delays are measured from: finish less delay.
    days = np.asarray(beta.get("schedule_days_array", []), dtype=float)
    planned = float(owner.get("deterministic_finish_days") or 0.0)
    if not planned and finish.size and days.size == finish.size:
        planned = float(np.median(finish - days))
    loo = list((beta.get("leave_one_out") or {}).get("rows") or [])
    facts: dict[str, Any] = {
        "p50": head.get(50), "p80": head.get(80), "p90": head.get(90),
        "planned_finish_wd": planned,
        "start": _project_start(beta),
        "finish_wd": {p: float(np.percentile(finish, p)) for p in (50, 80, 90)}
        if finish.size else {},
        "owner_p80_finish_wd": (float(np.percentile(owner["finish_days"], 80))
                                if owner.get("finish_days") is not None else None),
        "day_rate": float(day_rate),
        "loo_top": loo[:3],
        "cv_pass": bool((composed.get("cross_validation") or {}).get("all_pass")),
        "total": None, "jcl": None, "base_median": None,
    }
    if total_cost:
        pct = total_cost.get("percentiles_dollars") or {}
        facts["total"] = {int(k): float(v) for k, v in pct.items()}
        facts["declared_base"] = float(total_cost["base_total_dollars"])
        facts["base_median"] = float(np.median(np.asarray(total_cost["base_dollars"])))
    if jcl:
        facts["jcl"] = jcl
    if risks is not None:
        rl = list(risks)
        facts["n_risks"] = len(rl)
        facts["dists"] = sorted({str(getattr(r, "distribution", "") or "") for r in rl} - {""})
        facts["n_cg"] = len({getattr(r, "correlation_group", None) for r in rl} - {None, ""})
    facts["n_time"] = len(beta.get("risk_ids_dual") or [])
    facts["n_drivers"] = len(base_layer.get("shared_drivers") or [])
    return facts


def _finish_text(f: dict[str, Any], wd: float) -> str:
    d = finish_date(f["start"], wd)
    return f"working day {wd:.0f}" + (f" ({_date(d)})" if d else "")


def summary_table(f: dict[str, Any], risk_titles: dict[str, str]) -> list[dict[str, str]]:
    rows = [{"Item": "Event-risk contingency, P80 (recommended)", "Value": _m(f["p80"])},
            {"Item": "Event-risk contingency, P50 and P90",
             "Value": f"{_m(f['p50'])} and {_m(f['p90'])}"}]
    if f["planned_finish_wd"]:
        rows.append({"Item": "Planned finish", "Value": _finish_text(f, f["planned_finish_wd"])})
    if f["finish_wd"]:
        p80 = f["finish_wd"][80]
        rows.append({"Item": "P80 finish (event risks)",
                     "Value": f"{_finish_text(f, p80)}, "
                              f"{p80 - f['planned_finish_wd']:.0f} working days after the plan"})
    if f["total"]:
        t = f["total"]
        rows.append({"Item": "Total project cost, P50 / P80 / P90",
                     "Value": f"{_m(t[50])} / {_m(t[80])} / {_m(t[90])}"})
    if f["jcl"]:
        rows.append({"Item": "Joint confidence (budget and P80 finish both met)",
                     "Value": f"{f['jcl']['jcl']:.0%}"})
    if f["loo_top"]:
        rows.append({"Item": "Largest risks (saving at P80 if removed)",
                     "Value": "; ".join(
                         f"{r['risk_id']} {risk_titles.get(r['risk_id'], '')} "
                         f"{_m(r['saved_dollars'])}".replace("  ", " ")
                         for r in f["loo_top"])})
    rows.append({"Item": "Consistency checks",
                 "Value": "All four passed (see Checks)" if f["cv_pass"]
                 else "FAILED - see Checks; this report must not be distributed"})
    return rows


def which_number(f: dict[str, Any]) -> list[str]:
    """The box that relates the dollar figures and the finishes, each sentence from its numbers."""
    out = [f"**Which number to use.** **{_m(f['p80'])}** is the event-risk contingency at P80: "
           "the allowance for the register's event risks and the delay cost of the finish delay "
           f"they cause, priced at ${f['day_rate']:,.0f} a working day. It is the figure to "
           "carry as risk contingency on top of the base estimate."]
    if f["total"] and f.get("declared_base"):
        base, tot = f["declared_base"], f["total"][80]
        s = (f"**{_m(tot)}** is total project cost at P80: the {_m(base)} base with its own "
             "uncertainty, the event risks and the shared drivers. It is "
             f"{_m(tot - base)} above the base, more than the contingency, because the base "
             "itself is uncertain")
        bm = f.get("base_median")
        if bm is not None and bm > base:
            s += (f": half of its draws exceed {_m(bm)}, so the declared {_m(base)} sits below "
                  "its own median")
        out.append(s + ".")
    if f["jcl"]:
        j = f["jcl"]
        out.append(f"**{_m(j['cost_target'])}** is the budget the joint confidence tests (the "
                   "base plus the P80 contingency). Budget and P80 finish are met together in "
                   f"{j['jcl']:.0%} of iterations; Total cost, shared drivers and joint "
                   "confidence explains why.")
    if f["finish_wd"]:
        s = (f"For the finish, **{_finish_text(f, f['finish_wd'][80])}** is the P80 on the "
             "event risks alone")
        if f["owner_p80_finish_wd"]:
            s += (f"; **working day {f['owner_p80_finish_wd']:.0f}** also lets the shared "
                  "drivers stretch activity durations (the owner view)")
        out.append(s + ".")
    out.append("Why P80 of the event-risk contingency: the analysis sizes the allowance for "
               "discrete risks on top of a base estimate the owner already holds, and P80 is "
               "the reporting convention it recommends. Australian Government guidance "
               "(Guidance Note 3A) asks for the P50 and P90 of total project cost, which the "
               "table above shows.")
    return out


def report_vs_app(run_date: str | None) -> str:
    when = ""
    try:
        when = _dt.date.fromisoformat(str(run_date)).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        pass
    return ("This report is the baseline analysis" + (f" run on {when}" if when else "")
            + ": the register and programme as they stood before delivery began. The app shows "
              "the latest reporting month, so its figures move as risks fire, retire and are "
              "mitigated.")


def inputs_table(f: dict[str, Any], composed: dict[str, Any]) -> list[dict[str, str]]:
    audit = composed.get("page8_audit_trail") or {}
    rows: list[dict[str, str]] = []
    if f.get("declared_base"):
        rows.append({"Item": "Base estimate", "Value": _m(f["declared_base"])})
    if f["start"]:
        rows.append({"Item": "Programme start", "Value": _date(f["start"])})
    if f["planned_finish_wd"]:
        rows.append({"Item": "Planned finish",
                     "Value": f"{_finish_text(f, f['planned_finish_wd'])}, about "
                              f"{f['planned_finish_wd'] * 7 / 5 / 30.4:.0f} months"})
    if f.get("n_risks") is not None:
        rows.append({"Item": "Event risks (open)",
                     "Value": f"{f['n_risks']}, of which {f['n_time']} also delay the "
                              "programme"})
        rows.append({"Item": "Cost distributions used", "Value": ", ".join(f["dists"])})
        rows.append({"Item": "Correlation groups", "Value": str(f["n_cg"])})
    if f["n_drivers"]:
        rows.append({"Item": "Shared drivers", "Value": str(f["n_drivers"])})
    rows.append({"Item": "Day rate",
                 "Value": f"${f['day_rate']:,.0f} per working day (preliminaries and site "
                          "overheads only)"})
    if audit.get("iterations"):
        rows.append({"Item": "Iterations and seed",
                     "Value": f"{int(audit['iterations']):,}, seed {audit.get('random_seed')}"})
    return rows


INPUTS_ORIENTING = (
    "What the analysis was given. The register supplies the event risks and the base estimate's "
    "uncertainty, the programme supplies the logic each delay runs through, and the day rate "
    "prices finish delay. Each risk's delay is injected at a gating activity chosen from the "
    "programme; those bindings are listed in the audit trail.")


# ---------------------------------------------------------------------------------------------
# schedule evidence on the replay (D2) and criticality
# ---------------------------------------------------------------------------------------------

def finish_table(f: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for p, wd in sorted(f["finish_wd"].items()):
        d = finish_date(f["start"], wd)
        out.append({"Confidence level": f"P{p}", "Finish (working day)": f"{wd:.0f}",
                    "Finish date": _date(d),
                    "Delay after the plan (working days)":
                        f"{wd - f['planned_finish_wd']:.0f}"})
    return out


def schedule_loo_table(beta: dict[str, Any], titles: dict[str, str]) -> list[dict[str, str]]:
    sched = set(beta.get("risk_ids_dual") or [])
    rows = [r for r in ((beta.get("leave_one_out") or {}).get("rows") or [])
            if r["risk_id"] in sched and "finish_saved_days" in r]
    rows.sort(key=lambda r: r["finish_saved_days"], reverse=True)
    return [{"Risk": r["risk_id"], "Title": titles.get(r["risk_id"], ""),
             "P80 finish delay saved if removed (working days)": f"{r['finish_saved_days']:.1f}"}
            for r in rows[:8]]


def schedule_loo_sentence(table: list[dict[str, str]]) -> str:
    if len(table) < 2:
        return ""
    a, b = table[0], table[1]
    return (f"On the replay itself, removing {a['Risk']} alone would bring the P80 finish in by "
            f"{a['P80 finish delay saved if removed (working days)']} working days, and "
            f"{b['Risk']} by {b['P80 finish delay saved if removed (working days)']}. As with "
            "cost, the savings do not add: two risks on parallel paths can each be absorbed "
            "while the other still drives the finish.")


def criticality_table(crit: dict[str, Any]) -> list[dict[str, str]]:
    rows = list(crit.get("near_critical_table_full") or crit.get("near_critical_table") or [])
    rows.sort(key=lambda r: float(r.get("ci", 0.0)), reverse=True)
    return [{"Activity": str(r.get("activity_name", r.get("activity_id", ""))),
             "On the critical path (share of iterations)": f"{float(r.get('ci', 0.0)):.0%}",
             "On the planned critical path": "Yes" if r.get("on_deterministic_cp") else "No",
             "Mean total float (working days)":
                 f"{float(r.get('total_float_mean_hours', 0.0)) / HOURS_PER_DAY:.1f}"}
            for r in rows[:8]]


def criticality_sentence(crit: dict[str, Any]) -> str:
    s = crit.get("distribution_summary") or {}
    counts = s.get("band_counts") or {}
    n = s.get("n_activities_total")
    if not n:
        return ""
    always = counts.get("always (90%+)", 0)
    near = counts.get("near (30-70%)", 0) + counts.get("often (70-90%)", 0) \
        + counts.get("rarely (10-30%)", 0)
    return (f"Criticality is the replay's own evidence of where the finish is decided. Of {n} "
            f"activities, {always} are on the critical path in at least 90% of iterations and "
            f"{near} in between 10% and 90%; the rest almost never are. The table lists the "
            "near-critical activities, those most often on the path without always being on "
            "it. They are where the critical path moves from one chain to another, so float "
            "there is worth protecting.")


# ---------------------------------------------------------------------------------------------
# joint confidence (review section 4 item 5)
# ---------------------------------------------------------------------------------------------

def jcl_reason(f: dict[str, Any]) -> str:
    j = f["jcl"]
    if not j:
        return ""
    s = (f"Why the joint confidence is {j['jcl']:.0%}: the budget alone is met in "
         f"{j['cost_confidence']:.0%} of iterations and the P80 finish alone in "
         f"{j['finish_confidence']:.0%}. The budget is the base plus the event-risk "
         "contingency, so it does not fund the base estimate's own uncertainty")
    bm, base = f.get("base_median"), f.get("declared_base")
    if bm is not None and base and bm > base:
        s += f", and the base's median ({_m(bm)}) is above the declared {_m(base)}"
    return s + (". Meeting both needs both, so the joint figure sits a little below the lower of "
                "the two. To raise it, fund the base's uncertainty as well as the event risks.")


# ---------------------------------------------------------------------------------------------
# Actions (D4, S16)
# ---------------------------------------------------------------------------------------------

def logged_mitigations(pattern: str | None) -> tuple[list[dict[str, Any]], str]:
    """The mitigations logged across a project's status periods, each at its latest state.

    Returns ``(rows, period_end)``: each row the latest period's record of that mitigation; the
    end date of the last period read. ``([], "")`` when the project declares no workbooks.
    """
    if not pattern:
        return [], ""
    from src.am.workbook_reader import read_workbook
    latest: dict[str, dict[str, Any]] = {}
    last_end = ""
    for path in sorted(glob.glob(str(REPO_ROOT / pattern))):
        try:
            wb = read_workbook(path)
        except Exception as exc:  # a broken period workbook must not stop the report
            logger.warning("REPORTCOH-01 D4: status period %s not read: %s", path, exc)
            continue
        end = wb.period_info.get("am_period_end")
        end_s = end.strftime("%d/%m/%Y") if hasattr(end, "strftime") else str(end or "")
        last_end = end_s or last_end
        for m in wb.mitigations:
            latest[str(m["mitigation_id"])] = {**m, "period_end": end_s}
    return list(latest.values()), last_end


def actions_table(mitigations: list[dict[str, Any]], beta: dict[str, Any],
                  titles: dict[str, str]) -> list[dict[str, str]]:
    loo = {r["risk_id"]: r for r in ((beta.get("leave_one_out") or {}).get("rows") or [])}
    out = []
    for m in sorted(mitigations, key=lambda m: -loo.get(m.get("risk_id"), {})
                    .get("saved_dollars", 0.0)):
        r = loo.get(m.get("risk_id")) or {}
        out.append({
            "Mitigation": str(m.get("mitigation_id", "")),
            "Risk": f"{m.get('risk_id', '')} {titles.get(m.get('risk_id'), '')}".strip(),
            "Action": str(m.get("description") or ""),
            "Cost ($M)": _m(m["cost_aud"]) if m.get("cost_aud") is not None else "-",
            "Status": f"{m.get('status') or '-'} at {m.get('period_end', '')}".strip(),
            "Value at stake at P80 ($M)": _m(r["saved_dollars"]) if r else "-",
            "P80 finish at stake (working days)":
                f"{r['finish_saved_days']:.1f}" if r.get("finish_saved_days") else "-",
        })
    return out


def actions_text(table: list[dict[str, str]], beta: dict[str, Any],
                 mitigations: list[dict[str, Any]], period_end: str) -> list[str]:
    loo = list((beta.get("leave_one_out") or {}).get("rows") or [])
    out = ["Where treatment pays. The value at stake is what removing a risk entirely would save "
           "at P80 in this baseline run, from the leave-one-out results; a mitigation that only "
           "reduces a risk saves less. Set it against the mitigation's cost."]
    if not table:
        out.append("No mitigations are logged in a status period for this project. The "
                   "leave-one-out savings under Risk drivers show the value at stake per risk.")
    else:
        out.insert(1, f"The mitigations below are those logged in the project's status periods "
                      f"up to {period_end}, each at its latest status.")
    covered = {m.get("risk_id") for m in mitigations}
    gaps = [r["risk_id"] for r in loo[:5] if r["risk_id"] not in covered]
    if gaps:
        out.append("Of the five largest risks, these have no mitigation logged: "
                   + ", ".join(gaps) + ".")
    return out


# ---------------------------------------------------------------------------------------------
# the pass
# ---------------------------------------------------------------------------------------------

def _chart_dir(p2: dict[str, Any]) -> Path | None:
    """The run's chart folder, read from a chart it already drew; None when it drew none."""
    path = str(p2.get("integrated_s_curve_path") or "")
    return Path(path).parent if path else None


def _pick(d: dict[str, Any] | None, *keys: str) -> dict[str, Any]:
    d = d or {}
    return {k: d[k] for k in keys if k in d}


def build_report_layout(composed: dict[str, Any], beta: dict[str, Any] | None, *,
                        day_rate: float, total_cost: dict[str, Any] | None,
                        jcl: dict[str, Any] | None, risks: list[Any] | None,
                        risk_titles: dict[str, str] | None, run_date: str | None,
                        status_period_glob: str | None, project_note: str = "") -> None:
    """Write ``composed["report_sections"]``. A no-op when the CPM replay did not run."""
    if beta is None:
        return
    titles = dict(risk_titles or {})
    f = report_facts(composed, beta, day_rate=day_rate, total_cost=total_cost, jcl=jcl,
                     risks=risks)
    p2 = composed.get("page2_distribution") or {}
    p3 = composed.get("page3_cost_drivers") or {}
    p4 = composed.get("page4_schedule_drivers") or {}
    p5 = composed.get("page5_reconciliation") or {}
    p6 = composed.get("page6_action_implications") or {}
    p7 = composed.get("page7_methodology") or {}
    crit = composed.get("page4b_criticality") or {}
    app_m = composed.get("appendix_methodology") or {}

    mitigations, period_end = logged_mitigations(status_period_glob)
    act = actions_table(mitigations, beta, titles)
    sched_loo = schedule_loo_table(beta, titles)

    content: dict[str, dict[str, Any]] = {
        "rpt_summary": {
            "report_vs_app": report_vs_app(run_date),
            "summary_table": summary_table(f, titles),
            # One block, set apart: each paragraph a quoted line.
            "which_number": "\n>\n".join(f"> {para}" for para in which_number(f)),
        },
        "rpt_inputs": {
            "inputs_orienting": INPUTS_ORIENTING,
            "inputs_table": inputs_table(f, composed),
        },
        "rpt_contingency": {
            **_pick(p2, "integrated_orienting", "integrated_s_curve_path",
                    "integrated_density_path", "buildup_orienting", "buildup_s_curve_path",
                    "confidence_curve_heading", "confidence_curve_preamble",
                    "confidence_curve_table", "confidence_curve_footnote"),
            **_pick(p5, "waterfall_orienting", "waterfall_path", "waterfall_interpretation"),
            **_pick(p2, "cost_distribution_heading", "cost_distribution_orienting",
                    "cost_s_curve_path", "cost_density_path"),
        },
        "rpt_schedule": {
            **_pick(p2, "schedule_distribution_heading", "orienting", "s_curve_path",
                    "density_path", "interpretation"),
            "finish_heading": "Finish dates",
            "finish_table": finish_table(f) if f["finish_wd"] else [],
            "criticality_heading": "Activity criticality",
            "criticality_sentence": criticality_sentence(crit),
            "criticality_chart_path": crit.get("ci_distribution_chart_path")
            or crit.get("distribution_chart_path"),
            "criticality_table": criticality_table(crit),
            "schedule_loo_heading": "Schedule drivers on the replay",
            "schedule_loo_sentence": schedule_loo_sentence(sched_loo),
            "schedule_loo_table": sched_loo,
            "input_view_heading": "Schedule drivers as registered",
            **_pick(p4, "orienting_tornado", "tornado_path", "drivers_table",
                    "interpretation_tornado", "rbs_l1_heading", "rbs_l1_orienting",
                    "rbs_l1_breakdown_table"),
        },
        "rpt_drivers": {
            **_pick(p3, "integrated_tornado_heading", "integrated_tornado_orienting",
                    "integrated_tornado_path", "interpretation", "rbs_l1_heading",
                    "rbs_l1_orienting", "rbs_l1_breakdown_table"),
            **_pick(p4, "orienting_matrix", "risk_matrix_path", "interpretation_matrix"),
        },
        "rpt_total_cost": {
            **_pick(p2, "total_cost_heading", "total_cost_orienting", "total_cost_s_curve_path",
                    "total_cost_table", "total_cost_basis", "shared_drivers_sentence",
                    "shared_drivers_table", "jcl_heading", "jcl_orienting", "jcl_path",
                    "jcl_sentence", "jcl_basis"),
            "jcl_reason": jcl_reason(f),
        },
        "rpt_checks": {
            "checks_orienting": commentary_text.CHECKS_ORIENTING,
            "cross_validation_table": cross_validation_table(
                composed.get("cross_validation") or {}),
            "reconciliation_heading": "Against first-principles methods",
            **_pick(p5, "orienting", "comparison_table", "interpretation"),
            "convergence_heading": "Convergence",
            **_pick(p7, "convergence_chart_path", "convergence_caption", "convergence_caveat"),
        },
        "rpt_actions": {
            "actions_text": actions_text(act, beta, mitigations, period_end),
            "actions_table": act,
            **_pick(p6, "recommendations"),
        },
        "rpt_method": {
            **_pick(p7, "summary_paragraphs", "distribution_shape_explainer_intro",
                    "distribution_shape_explainer_bullets", "delay_cost_convention_heading",
                    "delay_cost_convention", "base_layer_exclusion", "standards_references",
                    "limitations_current", "limitations_closing"),
            **_pick(app_m, "caveats", "references"),
            "glossary_heading": "Glossary",
            "glossary": GLOSSARY,
        },
        # R3: the iteration nearest the P80, from the risks that fired to its contingency.
        "rpt_appendix_iteration": worked_iteration(
            beta, day_rate=day_rate, risks=risks, titles=titles,
            chart_dir=_chart_dir(p2)),
        "rpt_appendix_correlation": _pick(p7, "cg_drivers_orienting_paragraphs",
                                          "cg_drivers_table"),
        "rpt_appendix_audit": dict(composed.get("page8_audit_trail") or {}),
        "rpt_disclaimer": {"disclaimer": [
            p.format(project_note=project_note).strip() for p in DISCLAIMER_PARAGRAPHS]},
    }
    # The distribution explainer names only the distributions this register uses.
    bullets = content["rpt_method"].get("distribution_shape_explainer_bullets")
    if isinstance(bullets, list) and f.get("dists"):
        used = [b for b in bullets if any(b.lower().startswith(d.lower()) for d in f["dists"])]
        if used:
            content["rpt_method"]["distribution_shape_explainer_bullets"] = used
    composed["report_sections"] = [
        {"key": key, "heading": heading, "content": content[key]} for key, heading in SECTIONS]
    for key, _ in SECTIONS:
        composed[key] = content[key]


def cross_validation_table(cv: dict[str, Any]) -> list[dict[str, str]]:
    """The four consistency checks, each named for what it compares (S2)."""
    if not cv:
        return []

    def mark(ok: Any) -> str:
        return "PASS" if ok else "FAIL"

    return [
        {"Check": "Cost engines agree (standalone and integrated mean cost)",
         "Result": mark(cv.get("cost_passes_calibration")),
         "Detail": f"gap ${cv.get('cost_absolute_gap_dollars', 0):,.0f} "
                   f"({cv.get('cost_relative_gap_pct', 0) * 100:.3f}%)"},
        {"Check": "Report and dashboard engines agree (P80 finish delay)",
         "Result": mark(cv.get("schedule_passes_calibration")),
         "Detail": f"gap {cv.get('schedule_absolute_gap_days', 0):.3f} days"},
        {"Check": "Same top-3 cost risks in both cost engines (per-risk P80)",
         "Result": mark(cv.get("top_3_cost_contributors_consistent")),
         "Detail": "standalone " + ", ".join(cv.get("top_3_cost_contributors_cost_only") or [])
                   + "; integrated "
                   + ", ".join(cv.get("top_3_cost_contributors_integrated") or [])},
        {"Check": "Same top-3 schedule risks in both schedule engines (per-risk draws)",
         "Result": mark(cv.get("top_3_schedule_contributors_consistent")),
         "Detail": "standalone " + ", ".join(cv.get("top_3_schedule_contributors_sr5") or [])
                   + "; integrated "
                   + ", ".join(cv.get("top_3_schedule_contributors_integrated") or [])},
        {"Check": "Overall", "Result": mark(cv.get("all_pass")), "Detail": ""},
    ]
