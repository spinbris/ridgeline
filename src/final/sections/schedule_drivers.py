"""Schedule-drivers section builder.

Page 4: probability-weighted schedule tornado + Mode sensitivity
summary + RBS Level 1 schedule breakdown. Ranking metric is fixed at
probability-weighted mean (Beta-19b convention; the schedule MC's
per-risk column already encodes ``probability × mean impact × Mode
multiplier`` post-engine so column mean is the appropriate metric).

Moved here under SR14a.2 from ``src/final/composer.py`` (private
helper ``_build_probability_weighted_schedule_drivers``; public
helpers ``build_rbs_l1_schedule_breakdown`` and
``build_mode_sensitivity_summary``). Composer re-exports each helper
at module level so existing test imports keep working.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.final.sections._basis import (
    BASIS_COLUMN,
    TIME_FIELD,
    basis_cell,
    basis_lookup,
)
from src.final.sections.cost_drivers import (
    _RBS_UNASSIGNED_LABEL,
    _rbs_l1_label,
    _risk_attr,
)


# ---------------------------------------------------------------------------
# Named helpers (moved verbatim from composer)
# ---------------------------------------------------------------------------


def _build_probability_weighted_schedule_drivers(
    integrated_results: dict[str, Any],
    risks: Iterable[Any] | None,
    risk_titles: dict[str, str] | None,
    n: int = 8,
    mode_used: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Rank schedule drivers by probability-weighted mean contribution (days).

    The per_risk_schedule_array column mean equals probability x mean impact
    x mode multiplier already (post-engine), so column means are the
    appropriate ranking metric. Use them directly.
    """
    per_risk = np.asarray(integrated_results.get("per_risk_schedule_array", []))
    risk_ids = list(integrated_results.get("risk_ids_dual", []))
    if per_risk.size == 0 or len(risk_ids) == 0:
        return []

    means = per_risk.mean(axis=0)
    total = float(np.sum(means)) if np.sum(means) > 0 else 1.0

    risk_lookup = {_risk_attr(r, "risk_id"): r for r in (risks or [])}
    titles = risk_titles or {}
    mode_used = mode_used or {}

    order = np.argsort(means)[::-1][:n]
    out: list[dict[str, Any]] = []
    for idx in order:
        rid = risk_ids[int(idx)]
        risk = risk_lookup.get(rid)
        prob = float(_risk_attr(risk, "probability", 0.0)) if risk is not None else None
        mean_impact_when_fired = (
            float(means[idx]) / prob if prob and prob > 0 else None
        )
        out.append({
            "risk_id": rid,
            "title": titles.get(rid, rid),
            "probability": prob,
            "mean_impact_when_fired_days": mean_impact_when_fired,
            "prob_weighted_mean_days": float(means[idx]),
            "mode": mode_used.get(rid, "(unknown)"),
            "pct_of_total_mean": float(means[idx]) / total,
        })
    return out


def build_rbs_l1_schedule_breakdown(
    integrated_results: dict[str, Any],
    risks: Iterable[Any] | None,
) -> list[dict[str, Any]]:
    """Aggregate per-risk integrated schedule contributions by RBS Level 1.

    Beta-17 Item 4. Walks the integrated engine's
    ``per_risk_schedule_array`` (shape ``(n_iter, n_risks_dual)``,
    aligned with ``risk_ids_dual``), groups risks by
    ``RiskInput.rbs_l1``, and computes the probability-weighted mean
    schedule contribution (working days) per group.

    The schedule MC's per-risk column already encodes
    ``probability × mean impact × Mode multiplier`` post-engine, so the
    column mean is the appropriate per-risk ranking metric (same
    convention as :func:`_build_probability_weighted_schedule_drivers`).
    Group rows aggregate the same metric across category members.

    Returns a list sorted descending by ``prob_weighted_mean_days``;
    ``(Unassigned)`` placed last.
    """
    per_risk = np.asarray(integrated_results.get("per_risk_schedule_array", []))
    risk_ids = list(integrated_results.get("risk_ids_dual", []))
    if per_risk.size == 0 or len(risk_ids) == 0 or risks is None:
        return []

    risk_lookup = {_risk_attr(r, "risk_id"): r for r in risks}

    groups: dict[str, list[int]] = {}
    for idx, rid in enumerate(risk_ids):
        risk = risk_lookup.get(rid)
        label = _rbs_l1_label(risk) if risk is not None else _RBS_UNASSIGNED_LABEL
        groups.setdefault(label, []).append(idx)

    rows: list[dict[str, Any]] = []
    for label, member_idx in groups.items():
        group_iter_total = per_risk[:, member_idx].sum(axis=1)
        prob_weighted_mean = float(np.mean(group_iter_total))
        rows.append({
            "rbs_l1": label,
            "n_risks": len(member_idx),
            "prob_weighted_mean_days": prob_weighted_mean,
        })

    sum_value = sum(r["prob_weighted_mean_days"] for r in rows)
    for r in rows:
        r["pct_of_total"] = (
            r["prob_weighted_mean_days"] / sum_value if sum_value > 0 else 0.0
        )

    assigned = [r for r in rows if r["rbs_l1"] != _RBS_UNASSIGNED_LABEL]
    unassigned = [r for r in rows if r["rbs_l1"] == _RBS_UNASSIGNED_LABEL]
    assigned.sort(key=lambda d: -d["prob_weighted_mean_days"])
    return assigned + unassigned


def build_mode_sensitivity_summary(
    counterfactual: pd.DataFrame | None,
    strawman_variant: str | None,
    *,
    headline_p80_override_days: float | None = None,
) -> dict[str, Any]:
    """Compress the full counterfactual sweep into a 4-row §7 summary.

    Beta-15 Item 3. Returns a dict with:

      * ``table`` : pandas DataFrame with columns Scenario, MC Mean (days),
        P50 (days), P80 (days), Delta from headline (days). 4 rows: DP
        Review baseline (or "Mode as registered" labelled per
        variant), All Series, All Hybrid, All Parallel.
      * ``bold_row_index`` : 0-based index of the headline row to bold
        in the rendered table, or None when no match found.
      * ``orienting`` : 1-paragraph orienting note for the section.

    Variant-aware bolding follows Beta-14's mechanism: for a canonical
    un-suffixed DP Review strawman the Baseline row is bolded; for
    Series / Hybrid / Parallel variant strawmans the matching pure-Mode
    row is bolded (and the Baseline row's numerics will equal the
    pure-Mode row's by construction — transparent rather than
    obfuscated).

    Beta-19b item 5: ``headline_p80_override_days`` reuses the live
    integrated headline P80 (Executive Summary §1) for the headline row
    in lieu of the counterfactual sweep's independent re-run, eliminating
    MC sampling-noise drift between §1 and the §7 table. The other rows
    (upper bound, Mode as registered, lower bound) remain
    independent re-runs because they are sensitivity scenarios.
    """
    if counterfactual is None or len(counterfactual) == 0:
        return {
            "table": pd.DataFrame(),
            "bold_row_index": None,
            "orienting": "",
        }

    variant = (strawman_variant or "").capitalize() or None
    baseline_label = (
        f"Mode as registered (All {variant})"
        if variant in ("Series", "Hybrid", "Parallel")
        else "DP Review baseline (Mode as registered)"
    )

    headline_engine_name = {
        None: "Baseline (DP Review)",
        "Series": "All Series",
        "Hybrid": "All Hybrid",
        "Parallel": "All Parallel",
    }.get(variant, "Baseline (DP Review)")

    desired: list[tuple[str, str]] = [
        ("Baseline (DP Review)", baseline_label),
        ("All Series", "All Series (upper bound)"),
        ("All Hybrid", "All Hybrid (midpoint)"),
        (
            "All Parallel",
            "All Parallel (lower bound; zero schedule contribution)",
        ),
    ]

    rows: list[dict[str, Any]] = []
    bold_idx: int | None = None
    headline_mean: float | None = None
    for engine_name, display in desired:
        match = counterfactual[
            counterfactual["scenario_name"] == engine_name
        ]
        if len(match) == 0:
            continue
        r = match.iloc[0]
        is_headline = engine_name == headline_engine_name
        label = display + (" — headline" if is_headline else "")
        # Beta-19b item 5: substitute the live integrated headline P80
        # on the headline row only. Mean / P50 are intentionally left as
        # counterfactual figures because they characterise the
        # distribution shape under the pure-Mode counterfactual run; the
        # P80 override is the reader-facing reconciliation point to §1.
        p80_value = round(float(r["mc_p80_days"]), 2)
        if is_headline and headline_p80_override_days is not None:
            p80_value = round(float(headline_p80_override_days), 2)
        rows.append({
            "Scenario": label,
            "MC Mean (days)": round(float(r["mc_mean_days"]), 2),
            "P50 (days)": round(float(r["mc_p50_days"]), 2),
            "P80 (days)": p80_value,
            "Delta from headline (days)": 0.0,  # filled below
        })
        if is_headline:
            bold_idx = len(rows) - 1
            headline_mean = float(r["mc_mean_days"])

    if headline_mean is not None:
        for row in rows:
            row["Delta from headline (days)"] = round(
                row["MC Mean (days)"] - headline_mean, 2,
            )

    if variant in ("Series", "Hybrid", "Parallel"):
        baseline_explainer = (
            f"The \"Mode as registered\" row is the register's own "
            f"override (All {variant}) — this run is a variant against the "
            "canonical baseline. "
        )
    else:
        baseline_explainer = (
            "The \"Mode as registered\" row is the methodologically "
            "pure read — what the activity-level Mode classifier produces "
            "without override. "
        )
    orienting = (
        "The Mode-classification choice (Series / Hybrid / Parallel "
        "multipliers per dual-coded risk) materially affects the "
        "schedule-side headline. The table below shows the schedule "
        "slip distribution under four canonical Mode scenarios. "
        f"{baseline_explainer}"
        "The three pure-Mode rows (All Series / All Hybrid / All Parallel) "
        "are the sensitivity envelope showing the spread under simplified "
        "single-Mode assumptions; All Series is the conservative upper "
        "bound, All Parallel the lower bound. The bolded row is the "
        "headline scenario for this run. The full counterfactual sweep "
        "(single-risk-to-Series for each of the dual-coded risks) is "
        "available in the engineering drilldown notebook."
    )

    return {
        "table": pd.DataFrame(rows),
        "bold_row_index": bold_idx,
        "orienting": orienting,
    }


# ---------------------------------------------------------------------------
# Section builder
# ---------------------------------------------------------------------------


def build_schedule_drivers_section(
    integrated_dr: dict[str, Any],
    risks_list: Iterable[Any],
    risk_titles: dict[str, str] | None,
    indicative_scenario_display: str,
    mode_used: dict[str, str],
    appendix_counterfactual: pd.DataFrame | None,
    schedule_tornado_path: str = "",
    stage3: bool = False,
) -> dict[str, Any]:
    """Build the page-4 schedule drivers section dict (data only).

    Returns
    -------
    dict[str, Any]
        Keys:

        * ``prob_weighted_sched_drivers`` (list[dict]): top-8
          probability-weighted schedule drivers (exposed so the page-1
          top-driver block and chart helpers can reuse the same
          ranking).
        * ``page4_schedule_drivers`` (dict): rendered Page-4 payload
          minus the narrative wrappers and the risk-matrix orienting
          interpretation strings (those stay in composer per D3=A).
          Carries tornado_path passthrough, drivers_table,
          mode_sensitivity_table, rbs_l1_breakdown_table.

    Notes
    -----
    Beta-19b convention: schedule ranking is by probability-weighted
    mean (days), Mode-multiplied via the engine column mean. Per-driver
    Mode column label is derived from the indicative scenario name —
    "Mode" in prod, "Mode (Dummy Realistic)" in dev — so SR14b can
    substitute its own per-scenario label without touching the engine
    output shape.

    ``stage3`` (STAGE3HEADLINE-01 re-review): ``pct_of_total_mean`` is always the additive
    per-risk sum's own share, never a share of a CPM mean — true regardless of ``mode``. When
    ``stage3=True`` the drivers-table percentage column is headed "% of additive draws
    (comparator)" instead of "% of mean schedule slip", naming the basis truthfully for a
    caller whose headline is the Stage 3 CPM replay.
    """
    risks_list = list(risks_list)
    prob_weighted_sched_drivers = _build_probability_weighted_schedule_drivers(
        integrated_results=integrated_dr,
        risks=risks_list,
        risk_titles=risk_titles,
        n=8,
        mode_used=mode_used,
    )

    # PRESENT-01 (D-4): the dev column header carried the indicative scenario's name, and the
    # composer renamed the key back to "Mode" before the table was rendered.
    mode_column_label = "Mode"

    # STAGE3HEADLINE-01 re-review: pct_of_total_mean is always the additive per-risk sum's
    # own share (schedule_drivers.py's own docstring/comment above), never a share of the
    # CPM mean - sibling of the item-1 dominance-text fix, unreached there because this
    # header lives in a different module. Header must not claim "of mean schedule slip"
    # beside a CPM mean the percentage was never computed from.
    pct_column_label = (
        "% of additive draws (comparator)" if stage3 else "% of mean schedule slip"
    )

    # REPORT01 F-F: the Time section's own elicitation basis. The Contingent section's
    # basis is a claim about the cost numbers and belongs to the cost drivers table;
    # these rows are days, so they carry TIME_FIELD.
    time_basis = basis_lookup(risks_list, TIME_FIELD)

    sched_drivers_table: list[dict[str, Any]] = []
    for d in prob_weighted_sched_drivers[:8]:
        prob = d.get("probability")
        mean_imp = d.get("mean_impact_when_fired_days")
        sched_drivers_table.append({
            "Risk": d["risk_id"],
            "Title": d.get("title", d["risk_id"]),
            "Probability": f"{prob*100:.1f}%" if prob is not None else "n/a",
            "Mean impact when fired (days)": (
                round(mean_imp, 2) if mean_imp is not None else None
            ),
            "Probability x mean impact (days)": round(
                d.get("prob_weighted_mean_days", 0.0), 3,
            ),
            mode_column_label: d.get("mode", "(unknown)"),
            pct_column_label: f"{d.get('pct_of_total_mean', 0.0)*100:.1f}%",
            BASIS_COLUMN: basis_cell(time_basis, d["risk_id"]),
        })

    rbs_l1_sched_rows = build_rbs_l1_schedule_breakdown(
        integrated_results=integrated_dr,
        risks=risks_list,
    )
    rbs_l1_sched_table = [
        {
            "RBS Level 1 category": r["rbs_l1"],
            "Risk count": r["n_risks"],
            "Probability x mean impact (days)": round(
                r["prob_weighted_mean_days"], 2,
            ),
            "% of total": f"{r.get('pct_of_total', 0.0) * 100:.1f}%",
        }
        for r in rbs_l1_sched_rows
    ]

    page4_schedule_drivers = {
        "tornado_path": schedule_tornado_path,
        "drivers_table": sched_drivers_table,
        "mode_sensitivity_table": (
            appendix_counterfactual.copy()
            if appendix_counterfactual is not None
            else pd.DataFrame()
        ),
        "rbs_l1_breakdown_table": rbs_l1_sched_table,
    }

    return {
        "prob_weighted_sched_drivers": prob_weighted_sched_drivers,
        "page4_schedule_drivers": page4_schedule_drivers,
    }
