"""Page 1 quantitative tables + page 5 reconciliation section builder.

Encapsulates the data assembly behind:

- Page 1 integrated-P80 headline figure (numerical inputs only — the
  narrative wrapper stays in composer per Decision D3=A).
- Page 1 component breakdown table (Cost / Schedule / Naive sum /
  Diversification / Integrated total; P80 + Mean columns).
- Page 1 three-scenario range table (DP Review baseline / indicative /
  All Series; with B2a dedup against (P80, Mean cost, Mean schedule
  slip) rounded to 2 dp).
- Page 1 six-approach reconciliation table (Beta-15 Item 5).
- Page 5 comparison table (engineering judgement 10%/20%, sum of pess,
  EMV, MC mean/P80/P95) — also lives here because the page-1 and
  page-5 reconciliation tables share data plumbing.
- Page 5 waterfall components (Cost-only P80, Schedule slip P80,
  Joint sampling adjustment, Integrated P80) — sourced from the same
  ``_compute_component_breakdown`` single source of truth.

Moved here under SR14a.2 from ``src/final/composer.py`` (private
helpers ``_build_comparison_table``, ``_compute_component_breakdown``,
``_waterfall_components``, ``_build_component_breakdown_table``,
``_dedupe_scenarios_by_signature``, ``_build_dedup_footnote``, plus the
public ``build_six_approach_reconciliation_table``). Composer re-exports
each helper at module level so existing test imports keep working.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.final.executive_summary import resolve_indicative_scenario_name


def _risk_attr(r: Any, name: str, default: Any = None) -> Any:
    """Read a field off a RiskInput-like object or dict."""
    if isinstance(r, dict):
        return r.get(name, default)
    return getattr(r, name, default)


# ---------------------------------------------------------------------------
# Named helpers (moved verbatim from composer)
# ---------------------------------------------------------------------------


def _build_comparison_table(
    risks: Iterable[Any],
    integrated_results_indicative: dict[str, Any],
    schedule_results_indicative: dict[str, Any],
    programme_duration_days: float | None,
    day_rate: float,
) -> pd.DataFrame:
    """Build the deterministic-vs-MC comparison table.

    Rows: engineering judgement 10%, 20% of programme; sum of pessimistic
    impacts; EMV (probability x mean impact); MC mean; MC P80; MC P95.
    """
    cost_arr = np.asarray(integrated_results_indicative.get("cost_dollars_array", []))
    sched_arr = np.asarray(integrated_results_indicative.get("schedule_days_array", []))

    # EMV from analytic formula on the register.
    emv_cost = 0.0
    emv_days = 0.0
    sum_pess_cost = 0.0
    sum_pess_days = 0.0
    for r in risks:
        prob = float(_risk_attr(r, "probability", 0.0) or 0.0)
        emv_cost += prob * float(_risk_attr(r, "ml_cost", 0.0) or 0.0)
        emv_days += prob * float(_risk_attr(r, "ml_days", 0.0) or 0.0)
        sum_pess_cost += float(_risk_attr(r, "pess_cost", 0.0) or 0.0)
        sum_pess_days += float(_risk_attr(r, "pess_schedule_days", 0.0) or 0.0)

    rows: list[dict[str, Any]] = []

    if programme_duration_days and programme_duration_days > 0:
        for pct in (10, 20):
            days = programme_duration_days * pct / 100.0
            rows.append({
                "Approach": f"Engineering judgement ({pct}% of programme)",
                "Schedule contingency (days)": round(days, 1),
                "Cost contingency ($M)": None,
                "Notes": (
                    "Common rule of thumb"
                    if pct == 10
                    else "Conservative gut-feel"
                ),
            })

    rows.append({
        "Approach": "Sum of pessimistic impacts (worst case, no probability)",
        "Schedule contingency (days)": round(sum_pess_days, 1) if sum_pess_days else None,
        "Cost contingency ($M)": round(sum_pess_cost / 1e6, 2) if sum_pess_cost else None,
        "Notes": "Adds all worst-case impacts; ignores probability",
    })

    rows.append({
        "Approach": "EMV (sum of probability x ML impact)",
        "Schedule contingency (days)": round(emv_days, 2),
        "Cost contingency ($M)": round(emv_cost / 1e6, 2),
        "Notes": "First-principles probability-weighted estimate (deterministic)",
    })

    if cost_arr.size > 0:
        rows.append({
            "Approach": "MC mean, Stage 3 headline (recommended central estimate)",
            "Schedule contingency (days)": round(float(sched_arr.mean()), 2),
            "Cost contingency ($M)": round(float(cost_arr.mean()) / 1e6, 2),
            "Notes": "Reconciles with EMV; adds tail visibility",
        })
        rows.append({
            "Approach": "MC P80, Stage 3 headline",
            "Schedule contingency (days)": round(float(np.percentile(sched_arr, 80)), 2),
            "Cost contingency ($M)": round(float(np.percentile(cost_arr, 80)) / 1e6, 2),
            "Notes": "Useful for contingency floor",
        })
        rows.append({
            "Approach": "MC P95, Stage 3 headline",
            "Schedule contingency (days)": round(float(np.percentile(sched_arr, 95)), 2),
            "Cost contingency ($M)": round(float(np.percentile(cost_arr, 95)) / 1e6, 2),
            "Notes": "For risk-aware contingency",
        })

    return pd.DataFrame(rows)


def build_six_approach_reconciliation_table(
    risks: Iterable[Any] | None,
    integrated_results_indicative: dict[str, Any],
    programme_duration_days: float | None,
    day_rate: float,
    headline_metric: str = "P80",
) -> dict[str, Any]:
    """Compose the §1 six-approach reconciliation table for prod.

    Beta-15 Item 5. Returns a dict with:

      * ``table``  : DataFrame, 7 rows (10% rule of thumb, 20% rule of
        thumb, sum of pessimistic, EMV PERT, MC Mean, MC P80, MC P95)
        with columns Approach, Schedule (days), Cost ($M),
        Delta-schedule (days), Delta-cost ($M), Notes.
      * ``bold_row_index`` : 0-based index of the headline row (MC P80
        by default; MC Mean when headline_metric is "Mean").
      * ``orienting`` : 1-paragraph orienting note.

    Differs from ``_build_comparison_table`` (which feeds the dev-only
    page5_reconciliation block) by carrying audience-neutral wording —
    no "interim classification" or "Dummy Realistic" string
    leaks — and by adding the variant-aware Delta-from-headline columns
    that this Beta-15 surface needs.
    """
    if risks is None:
        risks = []
    cost_arr = np.asarray(integrated_results_indicative.get("cost_dollars_array", []))
    sched_arr = np.asarray(integrated_results_indicative.get("schedule_days_array", []))

    emv_cost = 0.0
    emv_days = 0.0
    sum_pess_cost = 0.0
    sum_pess_days = 0.0
    for r in risks:
        prob = float(_risk_attr(r, "probability", 0.0) or 0.0)
        emv_cost += prob * float(_risk_attr(r, "ml_cost", 0.0) or 0.0)
        emv_days += prob * float(_risk_attr(r, "ml_days", 0.0) or 0.0)
        sum_pess_cost += float(_risk_attr(r, "pess_cost", 0.0) or 0.0)
        sum_pess_days += float(_risk_attr(r, "pess_schedule_days", 0.0) or 0.0)

    rows: list[dict[str, Any]] = []

    if programme_duration_days and programme_duration_days > 0:
        for pct in (10, 20):
            note = (
                "Common rule of thumb"
                if pct == 10 else "Conservative rule of thumb"
            )
            rows.append({
                "Approach": f"{pct}% of programme rule of thumb",
                "Schedule (days)": round(programme_duration_days * pct / 100.0, 1),
                "Cost ($M)": None,
                "Notes": note,
            })

    rows.append({
        "Approach": "Sum of pessimistic durations / costs",
        "Schedule (days)": round(sum_pess_days, 1) if sum_pess_days else None,
        "Cost ($M)": round(sum_pess_cost / 1e6, 2) if sum_pess_cost else None,
        "Notes": "Treats every risk firing at Pess; ignores probability",
    })
    rows.append({
        "Approach": "Deterministic EMV PERT",
        "Schedule (days)": round(emv_days, 2),
        "Cost ($M)": round(emv_cost / 1e6, 2),
        "Notes": "Probability x PERT mean; ignores tail and Mode",
    })

    bold_row_index: int | None = None
    if cost_arr.size > 0:
        rows.append({
            "Approach": "MC Mean",
            "Schedule (days)": round(float(sched_arr.mean()), 2),
            "Cost ($M)": round(float(cost_arr.mean()) / 1e6, 2),
            "Notes": "Probabilistic mean; reconciles with EMV",
        })
        if str(headline_metric).strip().lower() == "mean":
            bold_row_index = len(rows) - 1

        rows.append({
            "Approach": "MC P80 (recommended contingency)",
            "Schedule (days)": round(float(np.percentile(sched_arr, 80)), 2),
            "Cost ($M)": round(float(np.percentile(cost_arr, 80)) / 1e6, 2),
            "Notes": "Headline contingency level per AACE / GN3A convention",
        })
        if bold_row_index is None:
            bold_row_index = len(rows) - 1

        rows.append({
            "Approach": "MC P95",
            "Schedule (days)": round(float(np.percentile(sched_arr, 95)), 2),
            "Cost ($M)": round(float(np.percentile(cost_arr, 95)) / 1e6, 2),
            "Notes": "Tail percentile; outlier-sensitive",
        })

    # Compute Delta-from-headline columns once the headline row is set.
    if bold_row_index is not None and rows:
        h_sched = rows[bold_row_index]["Schedule (days)"]
        h_cost = rows[bold_row_index]["Cost ($M)"]
        for row in rows:
            row_sched = row["Schedule (days)"]
            row_cost = row["Cost ($M)"]
            row["Delta-schedule (days)"] = (
                None
                if row_sched is None or h_sched is None
                else round(float(row_sched) - float(h_sched), 2)
            )
            row["Delta-cost ($M)"] = (
                None
                if row_cost is None or h_cost is None
                else round(float(row_cost) - float(h_cost), 2)
            )

    # Re-order columns so Notes is last (after the two delta columns).
    final_cols = [
        "Approach", "Schedule (days)", "Cost ($M)",
        "Delta-schedule (days)", "Delta-cost ($M)", "Notes",
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.reindex(columns=[c for c in final_cols if c in df.columns])

    orienting = (
        "The headline P80 contingency sits within a range bounded by "
        "simpler heuristics on one side (10% / 20% of programme rules "
        "of thumb) and tail-percentile readings on the other (P95 and "
        "beyond). The table below shows where the headline sits against "
        "six common reference points so the reader can plant the Monte "
        "Carlo number against first-principles comparators. The "
        "deterministic EMV PERT is the textbook expected-value answer; "
        "the MC Mean reconciles with it by construction; the MC P80 is "
        "the recommended contingency level per AACE / GN3A convention."
    )

    return {
        "table": df,
        "bold_row_index": bold_row_index,
        "orienting": orienting,
    }


def _compute_component_breakdown(
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    day_rate: float,
    p_level: int = 80,
    indicative_name: str | None = None,
) -> dict[str, float]:
    """Canonical component breakdown for the indicative scenario.

    Single source of truth for the v3 page 5 waterfall (`_waterfall_components`),
    the v3.1 page 1 component breakdown table (Deliverable 10), and the v3.1
    page 2 confidence curve P80 row reconciliation (Deliverable 11). All three
    consumers must agree on cost_p80 / sched_p80 / integrated_p80 / naive_sum
    by construction; pulling the arithmetic into one place catches any future
    drift.

    Indicative scenario follows resolve_indicative_scenario_name():
    Dummy Realistic in dev, DP Review baseline in prod (SR9 v3.3 Path A).

    Returns an empty dict if the indicative integrated results are missing or
    empty arrays.
    """
    # STAGE3HEADLINE-01: the composer names the headline basis explicitly (Stage 3 when a
    # Stage 3 result is present); the Mode-resolved name is the fallback for callers that
    # still build Stage 2.5 sensitivity views from the Mode family.
    indicative = integrated_results_by_scenario.get(
        indicative_name or resolve_indicative_scenario_name(), {},
    )
    cost_arr = np.asarray(indicative.get("cost_dollars_array", []))
    sched_arr = np.asarray(indicative.get("schedule_days_array", []))
    if cost_arr.size == 0 or sched_arr.size == 0:
        return {}

    day_rate = float(day_rate)
    cost_p80_dollars = float(np.percentile(cost_arr, p_level))
    sched_p80_days = float(np.percentile(sched_arr, p_level))
    sched_p80_dollars = sched_p80_days * day_rate
    integrated_p80_dollars = float(
        np.percentile(cost_arr + sched_arr * day_rate, p_level)
    )
    naive_sum_dollars = cost_p80_dollars + sched_p80_dollars
    diversification_dollars = integrated_p80_dollars - naive_sum_dollars

    # SR9 v3.5: Mean-equivalents of the same row set, computed off the
    # indicative scenario's integrated arrays. Identical formulae to the
    # P80 lines above but using arithmetic mean instead of percentile.
    cost_mean_dollars = float(np.mean(cost_arr))
    sched_mean_days = float(np.mean(sched_arr))
    sched_mean_dollars = sched_mean_days * day_rate
    integrated_mean_dollars = float(np.mean(cost_arr + sched_arr * day_rate))
    naive_sum_mean_dollars = cost_mean_dollars + sched_mean_dollars
    diversification_at_mean_dollars = (
        integrated_mean_dollars - naive_sum_mean_dollars
    )

    return {
        "p_level": int(p_level),
        "cost_p80_dollars": cost_p80_dollars,
        "cost_p80_m": cost_p80_dollars / 1e6,
        "sched_p80_days": sched_p80_days,
        "sched_p80_dollars": sched_p80_dollars,
        "sched_p80_dollars_m": sched_p80_dollars / 1e6,
        "naive_sum_dollars": naive_sum_dollars,
        "naive_sum_m": naive_sum_dollars / 1e6,
        "integrated_p80_dollars": integrated_p80_dollars,
        "integrated_p80_m": integrated_p80_dollars / 1e6,
        "diversification_dollars": diversification_dollars,
        "diversification_m": diversification_dollars / 1e6,
        # SR9 v3.5 Mean-equivalents
        "cost_mean_dollars": cost_mean_dollars,
        "cost_mean_m": cost_mean_dollars / 1e6,
        "sched_mean_days": sched_mean_days,
        "sched_mean_dollars": sched_mean_dollars,
        "sched_mean_dollars_m": sched_mean_dollars / 1e6,
        "naive_sum_mean_dollars": naive_sum_mean_dollars,
        "naive_sum_mean_m": naive_sum_mean_dollars / 1e6,
        "integrated_mean_dollars": integrated_mean_dollars,
        "integrated_mean_m": integrated_mean_dollars / 1e6,
        "diversification_at_mean_dollars": diversification_at_mean_dollars,
        "diversification_at_mean_m": diversification_at_mean_dollars / 1e6,
    }


def _waterfall_components(
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    day_rate: float,
    indicative_name: str | None = None,
) -> list[dict[str, Any]]:
    """Assemble waterfall components for the indicative scenario.

    Thin presentation wrapper over `_compute_component_breakdown`. Returns
    [] if the breakdown is empty so existing callers continue to handle
    missing data the same way.
    """
    breakdown = _compute_component_breakdown(
        integrated_results_by_scenario, day_rate, indicative_name=indicative_name)
    if not breakdown:
        return []

    diversification_m = breakdown["diversification_m"]
    return [
        {"label": "Cost-only P80", "value": breakdown["cost_p80_m"], "category": "base"},
        {
            "label": "Schedule slip P80 dollarised",
            "value": breakdown["sched_p80_dollars_m"],
            "category": "delta",
        },
        {
            "label": "Joint sampling adjustment",
            "value": diversification_m,
            "category": "delta" if diversification_m >= 0 else "delta_neg",
        },
        {"label": "Integrated P80", "value": breakdown["integrated_p80_m"], "category": "total"},
    ]


def _build_component_breakdown_table(
    breakdown: dict[str, float],
) -> list[dict[str, Any]]:
    """Render the Page 1 component breakdown table (Deliverable 10).

    Five rows: Cost contingency, Schedule contingency dollarised,
    Naive sum, Diversification effect, Integrated total. Each row carries
    BOTH a P80 column ("P80" key) and a Mean column ("Mean" key) under
    SR9 v3.5; both PROD outputs render the same expanded table and differ
    only in which column is highlighted as the headline. Values
    pre-formatted as $X.XXM strings; the diversification effect keeps its
    sign explicit.

    The "Value" key is retained as an alias for the P80 column so any
    legacy consumer that read the dev/prev-prod table by "Value" continues
    to read the P80 figure unchanged.
    """
    if not breakdown:
        return []
    div_p80_m = breakdown["diversification_m"]
    div_mean_m = breakdown["diversification_at_mean_m"]
    p80_sign = "+" if div_p80_m >= 0 else "-"
    mean_sign = "+" if div_mean_m >= 0 else "-"
    # PRESENT-01 (D-4): the dev note named an indicative classification, and the composer
    # replaced it with this one on every shipped run.
    schedule_note = "Schedule contingency dollarised at day rate"
    return [
        {
            "Component": "Cost contingency",
            "P80": f"${breakdown['cost_p80_m']:.2f}M",
            "Mean": f"${breakdown['cost_mean_m']:.2f}M",
            "Value": f"${breakdown['cost_p80_m']:.2f}M",
            "Notes": "Mode-independent",
        },
        {
            "Component": "Schedule contingency (dollarised)",
            "P80": f"${breakdown['sched_p80_dollars_m']:.2f}M",
            "Mean": f"${breakdown['sched_mean_dollars_m']:.2f}M",
            "Value": f"${breakdown['sched_p80_dollars_m']:.2f}M",
            "Notes": schedule_note,
        },
        {
            "Component": "Naive sum",
            "P80": f"${breakdown['naive_sum_m']:.2f}M",
            "Mean": f"${breakdown['naive_sum_mean_m']:.2f}M",
            "Value": f"${breakdown['naive_sum_m']:.2f}M",
            "Notes": "Cost + schedule, no joint adjustment",
        },
        {
            "Component": "Diversification effect",
            "P80": f"{p80_sign}${abs(div_p80_m):.2f}M",
            "Mean": f"{mean_sign}${abs(div_mean_m):.2f}M",
            "Value": f"{p80_sign}${abs(div_p80_m):.2f}M",
            "Notes": "Joint MC adjustment (integrated minus naive sum)",
        },
        {
            "Component": "Integrated total",
            "P80": f"${breakdown['integrated_p80_m']:.2f}M",
            "Mean": f"${breakdown['integrated_mean_m']:.2f}M",
            "Value": f"${breakdown['integrated_p80_m']:.2f}M",
            "Notes": "Single contingency figure",
        },
    ]


def _dedupe_scenarios_by_signature(
    scenarios_iterable,
    signature_fn,
):
    """B2a: collapse scenarios whose ``signature_fn(name, payload)``
    matches a previously-seen entry. First occurrence is kept.

    Generic across the two B2a surfaces:
      - Surface 1 (page1_range_table): items are dicts; signature_fn
        rounds the three numeric columns and ignores Notes/Scenario.
      - Surface 2 (div["scenarios"]): items are dicts with
        integrated_p80_dollars / naive_sum_p80_dollars; signature_fn
        rounds those.

    Parameters
    ----------
    scenarios_iterable : iterable of (name, payload) tuples
    signature_fn : callable (name, payload) -> hashable

    Returns
    -------
    (kept, deduped)
        kept    : list[(name, payload)] in original order, first-seen
        deduped : list[(kept_name, dropped_name)] for footnote rendering
    """
    seen: dict[Any, str] = {}
    kept: list[tuple[str, Any]] = []
    deduped: list[tuple[str, str]] = []
    for name, payload in scenarios_iterable:
        key = signature_fn(name, payload)
        if key in seen:
            deduped.append((seen[key], name))
            continue
        seen[key] = name
        kept.append((name, payload))
    return kept, deduped


def _build_dedup_footnote(
    deduped_pairs: list[tuple[str, str]],
    mode_mix_summary: str,
) -> str:
    """B2a: footnote text used by both dedup surfaces. Empty string
    when no dedup occurred (callers treat empty as 'no footnote').
    """
    if not deduped_pairs:
        return ""
    parts = []
    for kept, dropped in deduped_pairs:
        parts.append(
            f"{dropped} scenario coincides with {kept} at the current Mode "
            f"classification ({mode_mix_summary or 'unspecified'}); rendered "
            f"as a single row."
        )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def build_page1_table_section(
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    integrated_dp: dict[str, Any],
    integrated_dr: dict[str, Any],
    risks_list: Iterable[Any],
    programme_duration_days: float | None,
    day_rate: float,
    p_level: int,
    headline_metric: str,
    scenario_display_lookup: dict[str, str],
    indicative_scenario_name: str,
    indicative_display_short: str,
) -> dict[str, Any]:
    """Build the page-1 table data (data only; narrative format calls
    happen in the composer per Decision D3=A).

    Returns
    -------
    dict[str, Any]
        Keys:

        * ``breakdown`` (dict): output of ``_compute_component_breakdown``.
        * ``page1_component_breakdown`` (list[dict]): rendered component
          breakdown table rows (P80 + Mean columns, dollar-formatted).
        * ``page1_range_table`` (list[dict]): three-scenario range table
          (DP Review baseline / indicative / All Series), dedup-collapsed
          where signatures coincide.
        * ``page1_range_table_dedup_footnote`` (str | None): footnote
          prose for the range-table dedup (None when no dedup occurred).
        * ``page1_six_approach_reconciliation`` (dict): output of
          ``build_six_approach_reconciliation_table``.
        * Scalar inputs for the composer-side narrative templates:
          ``mean_days_indicative``, ``mean_cost_indicative_m``,
          ``lower_days``, ``upper_days``, ``p80_days_indicative``,
          ``dp_review_p80_m``, ``all_series_p80_m``.

    Notes
    -----
    The composer reads these scalars and feeds them into
    ``commentary_text.HEADLINE_OPENING``, ``HEADLINE_INTEGRATED_P80``,
    ``SCHEDULE_DAYS_CONTEXT``, and ``MODE_CAVEAT_HEADLINE`` template
    strings — narrative formatting stays in the composer (D3=A).
    """
    risks_list = list(risks_list)
    indicative_sched_arr = np.asarray(integrated_dr.get("schedule_days_array", []))
    indicative_cost_arr = np.asarray(integrated_dr.get("cost_dollars_array", []))

    mean_days_indicative = (
        float(indicative_sched_arr.mean()) if indicative_sched_arr.size else 0.0
    )
    mean_cost_indicative_m = (
        float(indicative_cost_arr.mean()) / 1e6 if indicative_cost_arr.size else 0.0
    )

    dp_sched = np.asarray(integrated_dp.get("schedule_days_array", []))
    all_series = integrated_results_by_scenario.get("All_Series", {})
    as_sched = np.asarray(all_series.get("schedule_days_array", []))
    lower_days = float(dp_sched.mean()) if dp_sched.size else mean_days_indicative
    upper_days = float(as_sched.mean()) if as_sched.size else mean_days_indicative

    breakdown = _compute_component_breakdown(
        integrated_results_by_scenario=integrated_results_by_scenario,
        day_rate=day_rate,
        p_level=p_level,
        indicative_name=indicative_scenario_name,
    )

    page1_component_breakdown = _build_component_breakdown_table(
        breakdown,
    )

    p80_days_indicative = (
        float(np.percentile(indicative_sched_arr, p_level))
        if indicative_sched_arr.size
        else 0.0
    )

    integrated_as = integrated_results_by_scenario.get("All_Series", {})
    dp_cost = np.asarray(integrated_dp.get("cost_dollars_array", []))
    dp_sched_d = np.asarray(integrated_dp.get("schedule_days_array", []))
    as_cost = np.asarray(integrated_as.get("cost_dollars_array", []))
    as_sched_d = np.asarray(integrated_as.get("schedule_days_array", []))
    dp_review_p80_m = (
        float(np.percentile(dp_cost + dp_sched_d * day_rate, p_level)) / 1e6
        if dp_cost.size and dp_sched_d.size
        else 0.0
    )
    all_series_p80_m = (
        float(np.percentile(as_cost + as_sched_d * day_rate, p_level)) / 1e6
        if as_cost.size and as_sched_d.size
        else 0.0
    )

    def _scenario_display_local(name: str) -> str:
        if scenario_display_lookup and name in scenario_display_lookup:
            return scenario_display_lookup[name]
        return name

    page1_range_table: list[dict[str, Any]] = []
    for name, scenario_dict in (
        ("DP_Review", integrated_dp),
        (indicative_scenario_name, integrated_dr),
        ("All_Series", all_series),
    ):
        if not scenario_dict:
            continue
        s_arr = np.asarray(scenario_dict.get("schedule_days_array", []))
        c_arr = np.asarray(scenario_dict.get("cost_dollars_array", []))
        if s_arr.size == 0 or c_arr.size == 0:
            continue
        p80_total = float(np.percentile(c_arr + s_arr * day_rate, 80)) / 1e6
        notes = {
            "DP_Review": "Conservative starting point",
            "Dummy_Realistic": "Interim working classification - PM review pending",
            "All_Series": "Methodological extreme",
        }.get(name, "")
        page1_range_table.append({
            "Scenario": _scenario_display_local(name),
            "Mean schedule slip (days)": round(float(s_arr.mean()), 2),
            "Mean cost ($M)": round(float(c_arr.mean()) / 1e6, 2),
            "P80 contingency ($M)": round(p80_total, 2),
            "Notes": notes,
        })

    # SR9 v3.6.1 B2a (surface 1): dedup against (P80 contingency,
    # Mean cost, Mean schedule slip) rounded to 2 dp.
    def _range_table_signature(name, row):
        return (
            round(float(row.get("P80 contingency ($M)", 0.0)), 2),
            round(float(row.get("Mean cost ($M)", 0.0)), 2),
            round(float(row.get("Mean schedule slip (days)", 0.0)), 2),
        )

    _range_named = [(r.get("Scenario", ""), r) for r in page1_range_table]
    _range_kept, _range_deduped = _dedupe_scenarios_by_signature(
        _range_named, _range_table_signature,
    )
    page1_range_table = [r for _, r in _range_kept]
    page1_range_table_dedup_footnote = _build_dedup_footnote(
        _range_deduped, mode_mix_summary=indicative_display_short,
    ) or None

    page1_six_approach_reconciliation = build_six_approach_reconciliation_table(
        risks=risks_list,
        integrated_results_indicative=integrated_dr,
        programme_duration_days=programme_duration_days,
        day_rate=day_rate,
        headline_metric=headline_metric,
    )

    return {
        "breakdown": breakdown,
        "page1_component_breakdown": page1_component_breakdown,
        "page1_range_table": page1_range_table,
        "page1_range_table_dedup_footnote": page1_range_table_dedup_footnote,
        "page1_six_approach_reconciliation": page1_six_approach_reconciliation,
        "mean_days_indicative": mean_days_indicative,
        "mean_cost_indicative_m": mean_cost_indicative_m,
        "lower_days": lower_days,
        "upper_days": upper_days,
        "p80_days_indicative": p80_days_indicative,
        "dp_review_p80_m": dp_review_p80_m,
        "all_series_p80_m": all_series_p80_m,
    }


def build_page5_reconciliation_section(
    risks_list: Iterable[Any],
    integrated_dr: dict[str, Any],
    schedule_results_indicative: dict[str, Any],
    programme_duration_days: float | None,
    day_rate: float,
    cross_validation: dict[str, Any],
    waterfall_path: str,
) -> dict[str, Any]:
    """Build the page-5 reconciliation section dict (data only).

    Returns
    -------
    dict[str, Any]
        Keys:

        * ``comparison_table`` (DataFrame): rows for engineering judgement
          10% / 20%, sum of pessimistic, EMV, MC mean / P80 / P95.
        * ``waterfall_path`` (str): pass-through PNG path for the joint-
          sampling waterfall (chart generated upstream).
        * ``cross_validation_panel`` (dict): copy of the cross-validation
          dict passed in.

    Notes
    -----
    The orienting / interpretation / waterfall_orienting prose stays in
    the composer (D3=A); ``waterfall_interpretation`` is composed at the
    composer from the dynamically-picked tail risk.
    """
    comparison_table = _build_comparison_table(
        risks=risks_list,
        integrated_results_indicative=integrated_dr,
        schedule_results_indicative=schedule_results_indicative,
        programme_duration_days=programme_duration_days,
        day_rate=day_rate,
    )
    return {
        "comparison_table": comparison_table,
        "waterfall_path": waterfall_path,
        "cross_validation_panel": dict(cross_validation),
    }
