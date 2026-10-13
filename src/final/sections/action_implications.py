"""Action-implications section builder.

Page 6: treatment ROI table + specific recommendations. The treatment
ROI table reads the strawman Treatments sheet (Beta-19 §4) and pairs
the top-3 cost drivers + top-3 schedule drivers with their workshop-
supplied treatment description and an estimated reduction; rows still
awaiting workshop input render the "Workshop input required"
placeholder (Beta-18 §2).

Moved here under SR14a.2 from ``src/final/composer.py`` (private
helpers ``_build_treatment_roi_table``, ``_build_specific_recommendations``).
Composer re-exports each helper at module level so existing test
imports keep working.

Decision D3=A: the narrative wrappers (orienting paragraph,
interpretation paragraph, illustrative-only banner) stay in the
composer; this section builder returns the pure-data treatment ROI
table + recommendations list.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.final import commentary_text, contract_terms
from src.final.executive_summary import pick_tail_risk
from src.sra.strawman_reader import read_treatments


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Named helpers (moved verbatim from composer)
# ---------------------------------------------------------------------------


def _build_treatment_roi_table(
    cost_drivers: list[dict[str, Any]],
    schedule_drivers: list[dict[str, Any]],
    headline_metric: str = "P80",
    treatments: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build the action-implications table from top drivers.

    Treatment columns are populated from the strawman Treatments sheet
    (Beta-19 §4). Workshop-populated rows render the treatment
    description and a dollar/day reduction estimate computed from the
    workshop-supplied effectiveness percentage; rows still awaiting
    workshop input render the "Workshop input required" placeholder.

    Beta-16 Item 3 (sweep): the cost-row "Current contribution" label
    tracks the docx variant's headline metric ($X.XX M (Mean) in the
    Mean docx, $X.XX M (P80) in the P80 docx). The dollar value itself
    is taken from ``d["value"]``, which `_build_cost_tornado_data`
    populates with the same metric — so the prose, the chart, and this
    table are all consistent.
    """
    # PRESENT-01 (D-4): these labels had a dev form naming an indicative basis; the
    # deliverable refuses dev, and the composer rewrote them back to these on every run.
    cost_type = "Cost"
    schedule_type = "Schedule"
    cost_metric_label = (
        "Mean" if str(headline_metric).strip().lower() == "mean" else "P80"
    )
    placeholder = commentary_text.ACTION_IMPLICATIONS_PLACEHOLDER_CELL

    treatments_by_id: dict[str, dict[str, Any]] = {}
    if treatments is not None and not treatments.empty:
        for _, row in treatments.iterrows():
            rid = str(row.get("risk_id", "")).strip()
            if not rid:
                continue
            treatments_by_id[rid] = {
                "treatment_description": str(
                    row.get("treatment_description") or ""
                ).strip(),
                "effectiveness_pct": row.get("effectiveness_pct"),
            }

    def _treatment_cells(risk_id: str, current_value: float, unit: str) -> tuple[str, str]:
        """Return (illustrative_treatment, estimated_reduction) cells.

        Empty / missing / NaN effectiveness_pct yields the placeholder
        for both columns. A populated row renders the workshop-supplied
        description and a reduction expressed in the same unit as the
        driver's current contribution.
        """
        import math
        info = treatments_by_id.get(str(risk_id).strip())
        if not info:
            return placeholder, placeholder
        eff = info.get("effectiveness_pct")
        desc = info.get("treatment_description") or ""
        # Treat NaN / None / non-numeric as "no workshop value supplied".
        # When the description is "Workshop input required" (the Beta-18
        # placeholder copy), render the placeholder for both columns so
        # the row reads consistently — workshop-supplied-description
        # is the signal that the row is populated.
        is_placeholder_desc = desc.strip().lower() == "workshop input required"
        if eff is None or is_placeholder_desc:
            return (placeholder if is_placeholder_desc else (desc or placeholder)), placeholder
        try:
            eff_float = float(eff)
        except (TypeError, ValueError):
            return (desc or placeholder), placeholder
        if math.isnan(eff_float):
            return (desc or placeholder), placeholder
        # Effectiveness_Pct is documented as a percentage (e.g. 30 for
        # 30%); we accept a 0-1 fraction too. The >= 1.0 boundary
        # treats a workshop-supplied value of exactly 1.0 as 1% rather
        # than the fraction 0.01 — the percentage interpretation
        # matches the column header in the strawman.
        eff_frac = eff_float / 100.0 if eff_float >= 1.0 else eff_float
        reduction = current_value * eff_frac
        if unit == "$M":
            red_str = f"${reduction:.2f}M ({eff_float:.0f}% effective)"
        else:
            red_str = f"{reduction:.2f} days ({eff_float:.0f}% effective)"
        return (desc or placeholder), red_str

    rows: list[dict[str, Any]] = []
    for d in (cost_drivers or [])[:3]:
        val_m = d.get("value", 0.0)
        metric_label = d.get("metric_name", cost_metric_label)
        ill, est = _treatment_cells(d.get("risk_id", ""), float(val_m or 0.0), "$M")
        rows.append({
            "Risk": d.get("risk_id", ""),
            "Type": cost_type,
            "Current contribution": f"${val_m:.2f}M ({metric_label})",
            "Illustrative treatment": ill,
            "Estimated reduction": est,
        })
    for d in (schedule_drivers or [])[:3]:
        days = d.get("prob_weighted_mean_days", 0.0)
        ill, est = _treatment_cells(d.get("risk_id", ""), float(days or 0.0), "days")
        rows.append({
            "Risk": d.get("risk_id", ""),
            "Type": schedule_type,
            "Current contribution": f"{days:.2f} days (prob-weighted mean)",
            "Illustrative treatment": ill,
            "Estimated reduction": est,
        })
    return pd.DataFrame(rows)


def _build_specific_recommendations(
    cost_drivers: list[dict[str, Any]],
    schedule_drivers: list[dict[str, Any]],
) -> list[str]:
    """Action-oriented quantified recommendations replacing generic ones.

    PRESENT-01 (D-4): the first recommendation had two forms. The dev form read explicit risk
    ids and Mode-shift deltas out of the counterfactual table and asked the reader to complete a
    PM review of the classifications; the client form names the top schedule drivers. The
    deliverable refuses dev, so only the second ever shipped - and with the first gone, the
    counterfactual table and its delta threshold are read by nothing here, so they are no longer
    taken.
    """
    recs: list[str] = []

    if schedule_drivers:
        top_ids = [d.get("risk_id", "") for d in schedule_drivers[:3] if d.get("risk_id")]
        if top_ids:
            recs.append(
                f"Prioritise risk-treatment plans for the top schedule "
                f"drivers: {', '.join(top_ids)}. Resolution of these "
                f"risks narrows the headline contingency materially."
            )

    if cost_drivers:
        top_cost = cost_drivers[0]
        # Beta-16 Item 3 (sweep): the label tracks the metric used to
        # rank ``cost_drivers`` so this recommendation reads consistently
        # with the §3 cost-tornado prose and the §6 treatment ROI table.
        cost_metric_label = top_cost.get("metric_name", "P80")
        recs.append(
            f"Treatment effort focused on {top_cost.get('risk_id', '')} "
            f"(${top_cost.get('value', 0):.2f}M {cost_metric_label} "
            f"contribution) reduces cost contingency more than effort "
            f"spread across the long tail."
        )

    # PRESENT-01 (P-4): this branched on one project's risk id, and named that project's
    # transformer. A risk earns this recommendation by its shape - rarely fired, large when it
    # is - so the run picks it, through the same helper the narrative templates use.
    tail = pick_tail_risk(schedule_drivers)
    if tail is not None:
        recs.append(
            f"Confirm lead-time and procurement protections for "
            f"{tail['tail_risk_id']}: it fires in "
            f"{tail['tail_risk_prob']:.1%} of iterations but contributes "
            f"{tail['tail_risk_mean_when_fired']:.0f} days when it does, so its tail "
            f"dominates upper-percentile contingency."
        )

    # PRESENT-01 (D-3), found by the numerics panel: a deferred commercial layer is a fact
    # about the reader's contract. Every other statement of it is gated; this one was not, so a
    # neutral-binding project was told about layers its own methodology caveats do not name.
    if contract_terms.term("deferred_commercial_layers_note") is not None:
        recs.append(
            "Confirm the deferred commercial parameters so the layers named in the "
            "methodology caveats can be added in the next stage."
        )
    recs.append(
        "Use the per-risk diagnostic outputs (audit trail appendix) to drive "
        "targeted risk treatment plans for the top-3 cost and schedule drivers."
    )
    return recs


# ---------------------------------------------------------------------------
# Section builder
# ---------------------------------------------------------------------------


def build_action_implications_section(
    cost_drivers: Iterable[dict[str, Any]],
    schedule_drivers: Iterable[dict[str, Any]],
    strawman_path: Path | str,
    headline_metric: str,
) -> dict[str, Any]:
    """Build the page-6 action-implications section dict.

    Returns
    -------
    dict[str, Any]
        Keys:

        * ``treatment_roi_table`` (DataFrame): six rows (top-3 cost +
          top-3 schedule drivers) with Risk / Type / Current
          contribution / Illustrative treatment / Estimated reduction
          columns. Workshop-populated rows render the treatment
          description + computed reduction; missing rows render the
          ``ACTION_IMPLICATIONS_PLACEHOLDER_CELL`` placeholder.
        * ``recommendations`` (list[str]): three to five quantified
          recommendation strings (schedule-driver focus / cost-focus /
          tail-risk watch / LD-IDC / per-risk-treatments).

    Notes
    -----
    Reads the strawman ``Treatments`` sheet via
    :func:`src.sra.strawman_reader.read_treatments`; missing-sheet falls
    back to an empty DataFrame and the placeholder cell rows. Narrative
    wrappers (orienting paragraph, interpretation paragraph, banner)
    are injected at the composer per Decision D3=A.
    """
    cost_drivers_list = list(cost_drivers or [])
    schedule_drivers_list = list(schedule_drivers or [])
    try:
        treatments_df = read_treatments(strawman_path)
    except Exception as exc:  # pragma: no cover - safety net for malformed sheets
        logger.warning("read_treatments failed; falling back to placeholders: %s", exc)
        treatments_df = pd.DataFrame(
            columns=["risk_id", "treatment_description",
                     "effectiveness_pct", "effectiveness_confidence"],
        )
    treatment_roi = _build_treatment_roi_table(
        cost_drivers=cost_drivers_list[:3],
        schedule_drivers=schedule_drivers_list[:3],
        headline_metric=headline_metric,
        treatments=treatments_df,
    )
    specific_recs = _build_specific_recommendations(
        cost_drivers=cost_drivers_list,
        schedule_drivers=schedule_drivers_list,
    )
    return {
        "treatment_roi_table": treatment_roi,
        "recommendations": specific_recs,
    }
