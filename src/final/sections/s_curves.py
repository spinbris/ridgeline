"""S-curves / confidence-curve section builder.

Page 2: integrated P-level confidence curve table (Deliverable 11) +
schedule-side S-curve / density histogram (Beta-11) + cost-side
S-curve / density histogram (Beta-16 Item 2) + diversification
waterfall figure (Beta-15 Item 4).

Moved here under SR14a.2 (session B) from ``src/final/composer.py``
(private helper ``_build_confidence_curve``). Composer re-exports the
helper at module level so existing test imports keep working.

Decision D3=A: the narrative wrappers (orienting paragraph,
interpretation paragraph, preamble, footnote) stay in the composer;
this section builder returns the pure-data confidence-curve table and
the chart-path / waterfall-caption dicts. The composer composes the
orientation / interpretation strings (which depend on the dynamically-
picked tail risk) on top.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.final.executive_summary import resolve_indicative_scenario_name


# ---------------------------------------------------------------------------
# Named helpers (moved verbatim from composer)
# ---------------------------------------------------------------------------


def _build_confidence_curve(
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    day_rate: float,
    p_levels: tuple[int, ...] = (50, 70, 80, 90, 95),
    recommended_p_level: int = 80,
    indicative_name: str | None = None,
) -> list[dict[str, Any]]:
    """Build the Page 2 confidence curve table (Deliverable 11).

    Uses the integrated engine's marginal arrays for naive_sum, NOT the
    standalone cost_results / schedule_results_by_scenario arrays.

    Why: the page 5 waterfall renders against `_waterfall_components` which
    uses the integrated engine's marginal arrays. If the page 2 confidence
    curve naive_sum used standalone arrays instead, the page 2 P80 row's
    "above naive sum" value would not match the page 5 waterfall's "joint
    sampling adjustment" exactly. Cross-validator's calibration check
    guarantees standalone and integrated marginals agree within MC noise,
    but a back-to-back read of pages 2 and 5 would surface the small
    discrepancy. This choice picks the convention already used by the v3
    waterfall - single source of truth across pages 1, 2, and 5.

    Under SR9 v3.5 a Mean row is added; rows are sorted ascending by
    integrated_contingency_m so Mean lands at its natural position
    (typically between P50 and P70 on right-skewed distributions).

    The row matching `recommended_p_level` is flagged via is_p80=True; the
    Mean row is flagged via is_mean=True. The legacy is_recommended flag is
    kept on the P80 row to preserve backward compatibility for any
    consumer that reads it.
    """
    # STAGE3HEADLINE-01: the composer names the headline basis (Stage 3 when present); the
    # Mode-resolved name is the fallback for Stage 2.5 sensitivity views.
    indicative = integrated_results_by_scenario.get(
        indicative_name or resolve_indicative_scenario_name(), {},
    )
    cost_arr = np.asarray(indicative.get("cost_dollars_array", []))
    sched_days_arr = np.asarray(indicative.get("schedule_days_array", []))
    if cost_arr.size == 0 or sched_days_arr.size == 0:
        return []

    day_rate = float(day_rate)
    sched_dollars_arr = sched_days_arr * day_rate
    integrated_total_arr = cost_arr + sched_dollars_arr

    out: list[dict[str, Any]] = []
    for p in p_levels:
        integrated_p = float(np.percentile(integrated_total_arr, p))
        sched_p_days = float(np.percentile(sched_days_arr, p))
        cost_p = float(np.percentile(cost_arr, p))
        sched_p_dollars = float(np.percentile(sched_dollars_arr, p))
        naive_sum_p = cost_p + sched_p_dollars
        above_naive = integrated_p - naive_sum_p
        out.append({
            "confidence_level": f"P{int(p)}",
            "integrated_contingency_m": integrated_p / 1e6,
            "schedule_slip_days": sched_p_days,
            "above_naive_sum_m": above_naive / 1e6,
            "is_recommended": int(p) == int(recommended_p_level),
            "is_p80": int(p) == int(recommended_p_level),
            "is_mean": False,
        })

    # SR9 v3.5: Mean row inserted at its natural sort position. Mean naive
    # sum / above-naive use the means of the marginal arrays; consistent
    # with how the P-level rows compute naive_sum (off marginal arrays).
    integrated_mean = float(np.mean(integrated_total_arr))
    sched_mean_days = float(np.mean(sched_days_arr))
    cost_mean = float(np.mean(cost_arr))
    sched_mean_dollars = float(np.mean(sched_dollars_arr))
    naive_sum_mean = cost_mean + sched_mean_dollars
    above_naive_mean = integrated_mean - naive_sum_mean
    mean_row = {
        "confidence_level": "Mean",
        "integrated_contingency_m": integrated_mean / 1e6,
        "schedule_slip_days": sched_mean_days,
        "above_naive_sum_m": above_naive_mean / 1e6,
        "is_recommended": False,
        "is_p80": False,
        "is_mean": True,
    }

    # Insert at the position where its integrated_contingency_m falls.
    # Use a count rather than a break-on-ascending-violation so the
    # placement is correct regardless of whether `p_levels` was supplied
    # in ascending order.
    insert_idx = sum(
        1 for row in out
        if row["integrated_contingency_m"] <= mean_row["integrated_contingency_m"]
    )
    out.insert(insert_idx, mean_row)
    return out


# ---------------------------------------------------------------------------
# Section builder
# ---------------------------------------------------------------------------


def build_s_curves_section(
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    day_rate: float,
    p_level: int,
    s_curve_path: str = "",
    density_path: str = "",
    waterfall_path: str = "",
    cost_s_curve_path: str = "",
    cost_density_path: str = "",
    indicative_name: str | None = None,
) -> dict[str, Any]:
    """Build the page-2 s-curves / distribution section dict (data only).

    Returns
    -------
    dict[str, Any]
        Keys:

        * ``page2_confidence_curve`` (list[dict]): output of
          ``_build_confidence_curve`` — rows for P50/P70/P80/P90/P95 +
          a Mean row at its natural sort position.
        * ``page2_distribution`` (dict): chart-path passthroughs for
          the schedule-side S-curve, density histogram, and the
          confidence-band waterfall figure, plus a formatted
          ``waterfall_caption`` string that embeds the run's day rate
          for the dollarisation factor.
        * ``page2_cost_distribution`` (dict): chart-path passthroughs
          for the cost-side S-curve and density histogram (Beta-16
          Item 2).

    Notes
    -----
    Narrative pieces — confidence-curve preamble / footnote,
    distribution orienting + interpretation (which threads the
    dynamically-picked tail risk), cost-distribution orienting — are
    injected at the composer per Decision D3=A.
    """
    page2_confidence_curve = _build_confidence_curve(
        integrated_results_by_scenario=integrated_results_by_scenario,
        day_rate=day_rate,
        recommended_p_level=p_level,
        indicative_name=indicative_name)

    waterfall_caption = (
        f"Decomposition of integrated P80 contingency: cost-P80 plus "
        f"schedule-P80 dollarised at the day rate (${day_rate:,.0f}/wd), "
        f"less the diversification adjustment from joint sampling, equals "
        f"the integrated P80 reported in the headline."
    )

    return {
        "page2_confidence_curve": page2_confidence_curve,
        "page2_distribution": {
            "s_curve_path": s_curve_path,
            "density_path": density_path,
            "waterfall_path": waterfall_path,
            "waterfall_caption": waterfall_caption,
        },
        "page2_cost_distribution": {
            "s_curve_path": cost_s_curve_path,
            "density_path": cost_density_path,
        },
    }
