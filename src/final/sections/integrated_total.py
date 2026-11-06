"""The integrated total on the Stage 3 basis, as the Distribution section draws it.

INTSCURVE-01 Part A. The report called itself integrated, but no chart drew the integrated
result: the S-curves were schedule days and the cost arm alone. This builds what the lead chart,
its histogram and the cumulative build-up are drawn from, and the executive summary's range,
from the same two arrays and the same expression the headline uses
(:func:`src.integrated.integrated_dollars.integrated_dollars_array`), with ``np.percentile`` at
its default method as :func:`src.final.headline.stage3_headline` does. So the P80 on the chart
is the headline P80 to the bit, and a test holds it.

Pure data (hard invariant 9).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from src.integrated.integrated_dollars import integrated_dollars_array

#: RISKDRV-01 stage 3: the P-level the drivers' leave-one-out is read at - the primary
#: reporting level (hard invariant 8), as the risk tornado and the JCL targets use.
DRIVER_LOO_P = 80

#: D-2 (Director, 28/10/2026): P50 / P80 / P90 everywhere, P80 the headline; P95 supporting.
INTEGRATED_P_LEVELS: tuple[int, ...] = (50, 80, 90, 95)
#: The executive summary's range.
SUMMARY_P_LEVELS: tuple[int, ...] = (50, 80, 90)


def integrated_total_data(
    cost_dollars_array: np.ndarray,
    schedule_days_array: np.ndarray,
    day_rate: float,
    p_levels: tuple[int, ...] = INTEGRATED_P_LEVELS,
) -> dict[str, Any]:
    """Arrays and percentiles for the integrated total and its build-up, in dollars.

    Returns ``{"total_dollars", "event_cost_dollars", "delay_cost_dollars" (arrays),
    "percentiles_dollars" {p: total P}, "event_cost_percentiles_dollars" {p: cost-arm P},
    "mean_dollars"}``. ``delay_cost_dollars`` is per-iteration float-aware delay x day rate.
    """
    cost = np.asarray(cost_dollars_array, dtype=float)
    days = np.asarray(schedule_days_array, dtype=float)
    total = integrated_dollars_array(cost, days, day_rate)
    if total.size == 0:
        raise ValueError("integrated_total_data: empty integrated array")
    return {
        "total_dollars": total,
        "event_cost_dollars": cost,
        "delay_cost_dollars": days * float(day_rate),
        "percentiles_dollars": {int(p): float(np.percentile(total, p)) for p in p_levels},
        "event_cost_percentiles_dollars": {
            int(p): float(np.percentile(cost, p)) for p in p_levels},
        "mean_dollars": float(np.mean(total)),
    }


def integrated_range_sentence(headline: dict[str, Any], metric: str = "P80") -> str:
    """The executive summary's lead (property 6): the integrated range in $, P50 / P80 / P90."""
    parts = []
    for p in SUMMARY_P_LEVELS:
        value = headline.get(f"p{p}_dollars")
        if not isinstance(value, (int, float)):
            return ""
        tag = " (recommended)" if f"P{p}" == str(metric) else ""
        parts.append(f"P{p} ${value / 1e6:.2f}M{tag}")
    return ("Integrated event-risk contingency, cost plus float-aware delay cost on the CPM "
            "replay: " + ", ".join(parts) + ". Schedule slip in days follows below.")


def stage3_headline_block(headline: dict[str, Any], heading: str) -> dict[str, Any]:
    """The Stage 3 headline block as the HTML body shows it (property 4): what Word shows.

    Word's ``_add_stage3_headline`` writes a heading, a bold lead, a percentile table and the
    basis sentence; this returns the same four pieces as composed keys the HTML renderer knows.
    """
    metric = str(headline.get("headline_metric", "P80"))
    lead = headline.get("headline_dollars")
    rows = [
        {"Percentile": f"P{p}", "Integrated contingency ($M)": _m(headline.get(f"p{p}_dollars"))}
        for p in headline.get("p_levels", ())
    ]
    rows.append({"Percentile": "Mean",
                 "Integrated contingency ($M)": _m(headline.get("mean_dollars"))})
    return {
        "stage3_headline_heading": f"### {heading}",
        "stage3_headline_lead": (
            f"**Recommended contingency: ${lead / 1e6:.2f}M ({metric}, event-risk cost plus "
            f"delay cost)**" if isinstance(lead, (int, float)) else ""),
        "stage3_headline_table": rows,
        "stage3_headline_basis": f"*{str(headline.get('basis', '')).strip()}*",
    }


def total_cost_data(
    base_layer: dict[str, Any] | None,
    cost_dollars_array: np.ndarray,
    schedule_days_array: np.ndarray,
    day_rate: float,
    p_levels: tuple[int, ...] = SUMMARY_P_LEVELS,
) -> dict[str, Any] | None:
    """INTSCURVE-01 Part B: total cost = base + event-risk cost + delay cost, per iteration.

    ``base_layer`` is :func:`src.integrated.base_layer.deliverable_base_layer`'s dict, drawn on
    its own stream, so the event-risk part of the total is the headline's own array, unmoved.
    Contingency at each P-level is the total's P-value less the declared base. ``None`` when the
    register has Layer 1 off, or the arrays do not pair, so the report renders as Part A.

    Returns ``{"base_dollars", "base_plus_cost_dollars", "total_dollars" (arrays),
    "base_total_dollars", "percentiles_dollars", "contingency_dollars", "excluded_factors"}``.
    """
    if not base_layer:
        return None
    base = np.asarray(base_layer["base_array"], dtype=float)
    cost = np.asarray(cost_dollars_array, dtype=float)
    if base.size == 0 or base.shape != cost.shape:
        return None
    owner = base_layer.get("owner_view")
    if owner is not None:
        # RISKDRV-01 (plan R2 (b)): the total is the owner view, so its delay is the drivers-on
        # pass's, which pairs with the base draw that carries the same drivers' cost. The
        # event-risk headline keeps the event-only delay; only the total and the JCL read this.
        owner_days = np.asarray(owner["delay_days"], dtype=float)
        if owner_days.shape != cost.shape:
            return None
        event_total = cost + owner_days * float(day_rate)
    else:
        event_total = integrated_dollars_array(cost, schedule_days_array, day_rate)
    total = base + event_total
    declared = float(base_layer["base_total_dollars"])
    pct = {int(p): float(np.percentile(total, p)) for p in p_levels}
    extra: dict[str, Any] = {}
    if owner is not None:
        rows = list(base_layer.get("shared_drivers") or [])
        if owner.get("finish_days_without") is not None:
            # RISKDRV-01 stage 3 (S2): the driver's masked leave-one-out on this total, one
            # function for the report and the period JSON.
            from src.integrated.driver_pass import driver_leave_one_out
            loo = driver_leave_one_out(
                base_array=base, base_without_driver=base_layer.get("base_without_driver") or {},
                cost_dollars_array=cost, owner=owner, day_rate=day_rate, p_level=DRIVER_LOO_P)
            rows = [{**r, "loo_total_dollars": loo[r["driver_id"]]["total_p_dollars"],
                     "loo_finish_days": loo[r["driver_id"]]["finish_p_days"],
                     "loo_p_level": DRIVER_LOO_P} for r in rows]
        extra = {"owner_finish_days": np.asarray(owner["finish_days"], dtype=float),
                 "owner_delay_days": owner_days,
                 "event_finish_days": np.asarray(owner["event_finish_days"], dtype=float),
                 "shared_drivers": rows}
    return {
        "base_dollars": base,
        "base_plus_cost_dollars": base + cost,
        "total_dollars": total,
        "base_total_dollars": declared,
        "percentiles_dollars": pct,
        "contingency_dollars": {p: v - declared for p, v in pct.items()},
        "mean_dollars": float(np.mean(total)),
        "excluded_factors": list(base_layer.get("excluded_factors") or []),
        **extra,
    }


def total_cost_rows(total: dict[str, Any]) -> list[dict[str, str]]:
    """The total-cost table: P-level, total cost, and contingency read as P-value less base.

    No row is marked "recommended": the recommended figure stays the event-risk contingency
    (D-1 (a)), and a contingency read off the total also carries the base's own uncertainty.
    """
    rows = []
    for p, value in total["percentiles_dollars"].items():
        rows.append({
            "Confidence level": f"P{p}",
            "Total cost ($M)": _m(value),
            "Declared base ($M)": _m(total["base_total_dollars"]),
            "Contingency, P-value less base ($M)": _m(total["contingency_dollars"][p]),
        })
    return rows


def shared_drivers_sentence(total: dict[str, Any]) -> str:
    """RISKDRV-01: the shared-driver paragraph, with both P80 finishes. Empty with no drivers."""
    from src.final import commentary_text

    if not total.get("shared_drivers"):
        return ""
    text = commentary_text.SHARED_DRIVERS_SENTENCE.format(
        finish=float(np.percentile(total["owner_finish_days"], 80)),
        event_finish=float(np.percentile(total["event_finish_days"], 80)))
    rows = total["shared_drivers"]
    if all("loo_total_dollars" in r for r in rows):
        from src.integrated.driver_pass import DRIVER_LEAVE_ONE_OUT_METHOD
        p = rows[0]["loo_p_level"]
        text += " The last two columns are " + DRIVER_LEAVE_ONE_OUT_METHOD.format(p=p)
    return text


def shared_driver_display_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """RISKDRV-01: one display row per shared driver, from ``driver_pass.driver_rows``."""
    return [{
        "Driver": f"{r['driver_id']} {r['name']}",
        "Kind": "Productivity" if r["kind"] == "P" else "Quantity",
        "WBS": ", ".join(r["wbs_codes"]),
        "Range (P10, most likely, P90)": r["range"],
        "Acts on": r["source"],
        "Mean duration change": f"{r['mean_delta']:+.1%}",
        **({f"Adds to P{r['loo_p_level']} total ($M)": _m(r["loo_total_dollars"]),
            f"Adds to P{r['loo_p_level']} finish (wd)": f"{r['loo_finish_days']:+.1f}"}
           if "loo_total_dollars" in r else {}),
    } for r in rows]


def base_exclusion_sentence(excluded: list[dict[str, Any]]) -> str:
    """D-4 (a), stated: which Layer 1 factors the base leaves out, and why. Empty if none."""
    if not excluded:
        return ""
    parts = [
        f"{d['name']} (rows: {', '.join(d['rows'])}; about ${d['mean_effect_dollars'] / 1e6:.2f}M "
        f"at the mean)" for d in excluded]
    return ("Left out of the base layer because they price project duration, which the delay "
            "cost already prices through the schedule replay: " + "; ".join(parts) + ". The "
            "register is unchanged.")


def stage3_jcl(
    stage3_beta_result: dict[str, Any] | None,
    total_cost: dict[str, Any] | None,
    day_rate: float,
    p_level: int = 80,
) -> dict[str, Any] | None:
    """INTSCURVE-01 P11 / JCLAXIS-01: the JCL on the Stage 3 run, cost axis with delay cost.

    Cost axis: base (when Part B drew one) + event-risk cost + delay cost, per iteration: the
    integrated total the budget is set against (JCLAXIS-01, Director 01/11/2026). A JCL counts
    iterations meeting both targets and adds nothing across axes, so delay is not counted twice.
    Finish axis: the run's own ``project_finish_days``, paired with the cost arm by construction (the cost arm's
    fire record drove the replay). Targets (D-3): cost = declared base + the integrated
    contingency at ``p_level`` (the headline's own figure); finish = the P80 finish. ``None``
    when the run carries no Stage 3 arrays (a section-seam fixture), so nothing is drawn.
    """
    from src.integrated.jcl import jcl_data

    s3 = stage3_beta_result or {}
    cost = np.asarray((s3.get("cost_result") or {}).get("cost_dollars_array", []), dtype=float)
    days = np.asarray(s3.get("schedule_days_array", []), dtype=float)
    schedule = s3.get("schedule_result")
    finish = np.asarray(getattr(schedule, "project_finish_days", []), dtype=float)
    if cost.size == 0 or cost.shape != finish.shape or cost.shape != days.shape:
        return None
    integrated = integrated_dollars_array(cost, days, day_rate)
    headline_contingency = float(np.percentile(integrated, p_level))
    base = total_cost["base_dollars"] if total_cost else 0.0
    declared = total_cost["base_total_dollars"] if total_cost else 0.0
    owner_finish = (total_cost or {}).get("owner_finish_days")
    if owner_finish is not None:
        # RISKDRV-01: with shared drivers the JCL is drawn on the owner view - its total (base
        # with the drivers' cost + event cost + drivers-on delay cost) against its own finish.
        # The budget stays declared base + the event-risk headline (D-3).
        axis, finish = total_cost["total_dollars"], np.asarray(owner_finish, dtype=float)
    else:
        axis = integrated + base
    out = jcl_data(axis, finish, cost_target=declared + headline_contingency,
                   finish_target=float(np.percentile(finish, 80)))
    out.update(p_level=int(p_level), base_drawn=bool(total_cost),
               headline_contingency_dollars=headline_contingency,
               declared_base_dollars=float(declared),
               shared_drivers=owner_finish is not None)
    return out


def jcl_sentence(jcl: dict[str, Any]) -> str:
    """The JCL in one sentence, with both targets and what each achieves on its own."""
    q = jcl["quadrants"]
    budget = (f"${jcl['cost_target'] / 1e6:.2f}M (the ${jcl['declared_base_dollars'] / 1e6:.2f}M "
              f"base plus the P{jcl['p_level']} contingency)" if jcl["base_drawn"] else
              f"${jcl['cost_target'] / 1e6:.2f}M (the P{jcl['p_level']} contingency)")
    return (f"Joint confidence level {jcl['jcl']:.0%}: the share of iterations that come in at "
            f"or under a budget of {budget} AND finish by the P80 finish, working day "
            f"{jcl['finish_target']:.0f}. On their own the budget is met in "
            f"{jcl['cost_confidence']:.0%} of iterations and the finish in "
            f"{jcl['finish_confidence']:.0%}. Rank correlation of cost with finish "
            f"{jcl['rank_correlation']:.2f}; meets both {q['meets_both']:.0%}, budget only "
            f"{q['cost_only']:.0%}, date only {q['finish_only']:.0%}, neither {q['neither']:.0%}.")


def confidence_curve_display_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The integrated P-level table with Word's columns and formats, for the HTML body."""
    out = []
    for r in rows:
        level = str(r.get("confidence_level", ""))
        if r.get("is_recommended"):
            level += " (recommended)"
        days = r.get("schedule_slip_days")
        out.append({
            "Confidence level": level,
            "Integrated contingency ($M)": _m(r.get("integrated_contingency_m"), scale=1.0),
            # REPORTCOH-01 S9: the schedule-only percentile, not the slip in the iterations that
            # make up the integrated figure on the same row.
            "Schedule-only slip (days)": f"{float(days):.1f}" if days is not None else "-",
            "Above naive sum ($M)": _m(r.get("above_naive_sum_m"), scale=1.0),
        })
    return out


def _m(value: Any, scale: float = 1e6) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    # REPORTCOH-01 S14: the minus sign leads the currency symbol (-$0.12M, never $-0.12M).
    v = float(value) / scale
    return f"-${abs(v):.2f}M" if v < 0 else f"${v:.2f}M"
