"""Cost-drivers section builder.

Page 3: cost tornado data + Page-3 drivers tables + RBS Level 1 cost
category breakdown. Also hosts the Correlation Group (CG) drivers
helper that page-7 methodology consumes — singletons aside, the CG
data flows alongside the cost-driver tornado.

Beta-16 Item 1 made the tornado ranking metric-aware: the P80 docx
ranks drivers by their P80 contribution; the Mean docx ranks by mean.
Beta-17 Item 4 added the RBS Level 1 breakdown; the same metric ranks
both surfaces.

Moved here under SR14a.2 from ``src/final/composer.py`` (private
helpers ``_build_cost_tornado_data``, ``_filter_cost_drivers_for_table``,
``_rbs_l1_label``; public helpers ``build_rbs_l1_cost_breakdown``,
``build_cg_drivers_table``; constants ``_RBS_UNASSIGNED_LABEL`` and
``CG_DESCRIPTION_NOT_IN_REGISTER``). Composer re-exports each helper
at module level so existing test imports keep working.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np

from src.final.sections._basis import (
    BASIS_COLUMN,
    COST_FIELD,
    basis_cell,
    basis_lookup,
)


def _risk_attr(r: Any, name: str, default: Any = None) -> Any:
    """Read a field off a RiskInput-like object or dict."""
    if isinstance(r, dict):
        return r.get(name, default)
    return getattr(r, name, default)


_RBS_UNASSIGNED_LABEL = "(Unassigned)"

#: Beta-17 SSoT cleanup: rendered into the deliverable's "Driver
#: description" cell when a CG ID is present in the member-risk data but
#: missing from the register's MC_Params CG block. Surfaces register
#: drift / authoring gaps without silently substituting a Python value.
CG_DESCRIPTION_NOT_IN_REGISTER = "(not in register)"


def _rbs_l1_label(risk: Any) -> str:
    """Resolve an RBS Level 1 label off a RiskInput-like object.

    Returns the trimmed label when present and non-empty; falls back to
    ``"(Unassigned)"`` otherwise so all risks land in some row of the
    breakdown table rather than vanishing silently.
    """
    label = (_risk_attr(risk, "rbs_l1", "") or "")
    label = str(label).strip()
    return label if label else _RBS_UNASSIGNED_LABEL


def _build_cost_tornado_data(
    integrated_results: dict[str, Any],
    risk_titles: dict[str, str] | None,
    n: int = 8,
    p_level: int = 80,
    headline_metric: str = "P80",
) -> list[dict[str, Any]]:
    """Extract top-N cost drivers ranked by the headline metric ($M).

    Beta-16 Item 1: ``headline_metric`` selects which metric ranks the
    drivers and labels the output dict. When ``"P80"`` (default,
    behaviour-preserving), each risk's contribution is the ``p_level`` th
    percentile of its per-iteration cost array; when ``"Mean"``, each
    risk's contribution is the mean of its per-iteration cost array. The
    Mean docx (``BETA_sra_executive_summary_PROD_MEAN_*.docx``) ranks by
    Mean; the P80 docx ranks by P80. ``pct_of_total`` is computed against
    the sum of the chosen metric so the percentage tracks the metric
    named in the prose. ``metric_name`` is echoed in each dict so callers
    can render dynamic table column headers without re-resolving.
    """
    per_risk = np.asarray(integrated_results.get("per_risk_cost_array", []))
    risk_ids = list(integrated_results.get("risk_ids_all", []))
    if per_risk.size == 0 or len(risk_ids) == 0:
        return []

    metric_label = "Mean" if str(headline_metric).strip().lower() == "mean" else "P80"
    if metric_label == "Mean":
        metric_values = per_risk.mean(axis=0)
    else:
        metric_values = np.percentile(per_risk, p_level, axis=0)
    total = float(np.sum(metric_values)) if np.sum(metric_values) > 0 else 1.0

    titles = risk_titles or {}
    order = np.argsort(metric_values)[::-1][:n]
    out: list[dict[str, Any]] = []
    for idx in order:
        rid = risk_ids[int(idx)]
        out.append({
            "risk_id": rid,
            "title": titles.get(rid, rid),
            "value": float(metric_values[idx]) / 1e6,  # $M
            "value_dollars": float(metric_values[idx]),
            "pct_of_total": float(metric_values[idx]) / total,
            "metric_name": metric_label,
        })
    return out


def _filter_cost_drivers_for_table(
    cost_drivers: list[dict[str, Any]],
    threshold_m: float = 0.10,
    cap: int = 5,
) -> list[dict[str, Any]]:
    """Trim cost drivers list for the Page 3 table (Deliverable 2).

    Returns the top 3 drivers unconditionally, plus any drivers in
    positions 4..cap with `value` (in $M) above `threshold_m`. Caps
    output at `cap` rows. The cost tornado chart can still receive the
    untrimmed list; this filter only narrows the textual table so a
    "drivers" table does not pad with zero-contribution rows.
    """
    if not cost_drivers:
        return []
    if len(cost_drivers) <= 3:
        return list(cost_drivers)

    out = list(cost_drivers[:3])
    for d in cost_drivers[3:cap]:
        if float(d.get("value", 0.0) or 0.0) > threshold_m:
            out.append(d)
    return out[:cap]


def build_rbs_l1_cost_breakdown(
    integrated_results: dict[str, Any],
    risks: Iterable[Any] | None,
    headline_metric: str = "P80",
    p_level: int = 80,
) -> list[dict[str, Any]]:
    """Aggregate per-risk integrated cost contributions by RBS Level 1.

    Beta-17 Item 4. Walks the integrated engine's
    ``per_risk_cost_array`` (shape ``(n_iter, n_risks_all)``), groups
    risks by ``RiskInput.rbs_l1``, and for each group computes the
    headline-metric value over the *group total* iteration array:

    - ``headline_metric="Mean"`` → ``np.mean`` over group iteration sums.
    - ``headline_metric="P80"`` (default) → the ``p_level`` th percentile
      over the group iteration sums.

    The dual rankings mirror :func:`_build_cost_tornado_data` (Beta-16
    Item 1), so the §3 RBS table follows the same headline metric as
    the §3 driver tornado. Returns a list sorted descending by
    ``value_dollars``; the ``(Unassigned)`` row is always placed last
    regardless of magnitude so directors see assigned categories first.
    """
    per_risk = np.asarray(integrated_results.get("per_risk_cost_array", []))
    risk_ids = list(integrated_results.get("risk_ids_all", []))
    if per_risk.size == 0 or len(risk_ids) == 0 or risks is None:
        return []

    metric_label = "Mean" if str(headline_metric).strip().lower() == "mean" else "P80"
    risk_lookup = {_risk_attr(r, "risk_id"): r for r in risks}

    groups: dict[str, list[int]] = {}
    for idx, rid in enumerate(risk_ids):
        risk = risk_lookup.get(rid)
        if risk is None:
            label = _RBS_UNASSIGNED_LABEL
        else:
            label = _rbs_l1_label(risk)
        groups.setdefault(label, []).append(idx)

    rows: list[dict[str, Any]] = []
    for label, member_idx in groups.items():
        group_iter_total = per_risk[:, member_idx].sum(axis=1)
        if metric_label == "Mean":
            value = float(np.mean(group_iter_total))
        else:
            value = float(np.percentile(group_iter_total, p_level))
        rows.append({
            "rbs_l1": label,
            "n_risks": len(member_idx),
            "value_dollars": value,
            "value_M": value / 1e6,
            "metric_name": metric_label,
        })

    sum_value = sum(r["value_dollars"] for r in rows)
    for r in rows:
        r["pct_of_total"] = (
            r["value_dollars"] / sum_value if sum_value > 0 else 0.0
        )

    assigned = [r for r in rows if r["rbs_l1"] != _RBS_UNASSIGNED_LABEL]
    unassigned = [r for r in rows if r["rbs_l1"] == _RBS_UNASSIGNED_LABEL]
    assigned.sort(key=lambda d: -d["value_dollars"])
    return assigned + unassigned


def build_cg_drivers_table(
    risks: Iterable[Any] | None,
    register_path: str | Path | None = None,
    *,
    cg_descriptions: dict[str, str] | None = None,
    cg_coefficients: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build the §7 Correlation Group (CG) drivers table.

    Beta-17 SSoT-clean implementation. The register's MC_Params CG block
    is the single source of truth for driver descriptions. Walks the
    Open MC-Include risks list, groups by
    ``RiskInput.correlation_group``, pairs each active CG with its
    register-sourced description and joint-firing coefficient.

    No-fallback policy
    ------------------
    Driver descriptions come from
    :func:`src.openpyxl_reader.read_cg_descriptions` exclusively. When a
    CG ID is present in the member-risk data but absent from the
    register's CG block, the driver description renders as
    ``CG_DESCRIPTION_NOT_IN_REGISTER`` — the absence is visible to the
    reader of the deliverable; nothing hidden. When the register read
    itself fails (e.g. ``MC_Params`` sheet missing), the exception
    propagates and the deliverable build halts. No hardcoded fallback
    dict exists in run code (Beta-17 SSoT cleanup; the earlier
    ``commentary_text.CG_DRIVER_DESCRIPTIONS`` mechanism was deleted).

    Parameters
    ----------
    risks : iterable of RiskInput-like
        Open MC-Include risks. Each must carry ``risk_id`` and
        ``correlation_group``.
    register_path : str or Path
        Path to the V5/V8 register workbook. Required for the
        register-sourced description read. ``None`` is only acceptable
        when ``cg_descriptions`` is supplied explicitly (test override).
    cg_descriptions : dict[str, str], keyword-only
        Test-override hook. When supplied, bypasses
        ``read_cg_descriptions`` and uses the dict directly. Run code
        does NOT supply this; tests pass a clearly-marked fixture.
    cg_coefficients : dict[str, float], keyword-only
        The joint-firing coefficients, normally the register's. When supplied
        they are used alone - no binding is consulted (stage 4 F-29); when
        omitted, :data:`src.defaults.HEADLESS_CG_COEFFICIENTS` is read from the
        active binding (the legacy path). CGs missing from
        the coefficient dict (e.g. singleton CG11/CG12/CG13 in V8)
        render coefficient ``None`` — singletons have no within-group
        correlation by definition.

    Returns
    -------
    list of dict
        One row per active CG with keys: ``cg_id``, ``driver_description``
        (register-sourced; falls to ``CG_DESCRIPTION_NOT_IN_REGISTER``
        when absent from register), ``member_risk_ids`` (sorted list),
        ``member_risk_count``, ``coefficient`` (float or None). Sorted
        by CG ID ascending.
    """
    if risks is None:
        return []
    if cg_coefficients is not None:
        # Stage 4 F-29 (08/09/2026, first-rank): the register's coefficients are the table's,
        # and the binding is not consulted. This used to import HEADLESS_CG_COEFFICIENTS first
        # and lay the register's values over it - so a project with no headless_config (the
        # road binding omits it on purpose) halted the deliverable after every engine had run,
        # for a base dictionary the override then replaced. A CG the register does not price
        # renders None, which is what the docstring already promised.
        coefs = dict(cg_coefficients)
    else:
        # The legacy cost-MC / test path: nothing else to draw on, so the binding's dictionary.
        from src.defaults import HEADLESS_CG_COEFFICIENTS
        coefs = dict(HEADLESS_CG_COEFFICIENTS)

    if cg_descriptions is None:
        if register_path is None:
            raise ValueError(
                "build_cg_drivers_table requires register_path (or an "
                "explicit cg_descriptions test override). No hardcoded "
                "fallback under the Beta-17 SSoT policy."
            )
        from src.openpyxl_reader import read_cg_descriptions
        cg_descriptions = read_cg_descriptions(register_path)

    groups: dict[str, list[str]] = {}
    for r in risks:
        cg = _risk_attr(r, "correlation_group", "") or ""
        cg = str(cg).strip()
        if not cg:
            continue
        rid = _risk_attr(r, "risk_id", "") or ""
        rid = str(rid).strip()
        if rid:
            groups.setdefault(cg, []).append(rid)

    rows: list[dict[str, Any]] = []
    for cg_id in sorted(groups.keys()):
        member_ids = sorted(groups[cg_id])
        register_value = cg_descriptions.get(cg_id)
        if register_value is None:
            description = CG_DESCRIPTION_NOT_IN_REGISTER
        else:
            description = register_value.strip()
            if not description:
                description = CG_DESCRIPTION_NOT_IN_REGISTER
        coefficient = coefs.get(cg_id)
        rows.append({
            "cg_id": cg_id,
            "driver_description": description,
            "member_risk_ids": member_ids,
            "member_risk_count": len(member_ids),
            "coefficient": coefficient,
        })
    return rows


# ---------------------------------------------------------------------------
# Section builder
# ---------------------------------------------------------------------------


def build_cost_drivers_section(
    integrated_dp: dict[str, Any],
    risks_list: Iterable[Any],
    risk_titles: dict[str, str] | None,
    p_level: int,
    headline_metric: str,
    cost_tornado_path: str = "",
) -> dict[str, Any]:
    """Build the page-3 cost drivers section dict (data + value_column_header).

    Returns
    -------
    dict[str, Any]
        Keys:

        * ``cost_drivers_full`` (list[dict]): top-8 cost drivers from
          ``_build_cost_tornado_data`` (exposed so action_implications
          and chart helpers can ingest the same ranking).
        * ``page3_cost_drivers`` (dict): rendered section payload
          (tornado_path passthrough, drivers_table, drivers_table_full,
          metric_name, value_column_header, rbs_l1_breakdown_table,
          rbs_l1_metric_name). Narrative pieces (mode_independence_note,
          orienting, interpretation, rbs_l1_heading, rbs_l1_orienting)
          are injected at the composer per Decision D3=A.

    Notes
    -----
    Beta-16 Item 1: the value_column_header / metric_name pair tracks
    the docx variant's headline metric (Mean / P80) so renderers can
    label the table column dynamically without re-deriving the metric.
    """
    cost_drivers_full = _build_cost_tornado_data(
        integrated_results=integrated_dp,
        risk_titles=risk_titles,
        n=8,
        p_level=p_level,
        headline_metric=headline_metric,
    )

    cost_metric_label = (
        cost_drivers_full[0].get("metric_name", "P80")
        if cost_drivers_full
        else ("Mean" if str(headline_metric).strip().lower() == "mean" else "P80")
    )
    cost_value_col = f"{cost_metric_label} contribution ($M)"

    # REPORT01 F-F: the Contingent section's elicitation basis, on the cost arm's own
    # table. The Time section's is a different claim and belongs to the schedule table.
    cost_basis = basis_lookup(risks_list, COST_FIELD)

    cost_drivers_table_full: list[dict[str, Any]] = []
    for d in cost_drivers_full[:8]:
        cost_drivers_table_full.append({
            "Risk": d["risk_id"],
            "Title": d.get("title", d["risk_id"]),
            cost_value_col: round(d.get("value", 0.0), 2),
            "% of total": f"{d.get('pct_of_total', 0.0)*100:.1f}%",
            BASIS_COLUMN: basis_cell(cost_basis, d["risk_id"]),
        })
    cost_drivers_filtered_input = _filter_cost_drivers_for_table(
        cost_drivers_full, threshold_m=0.10, cap=5,
    )
    cost_drivers_table: list[dict[str, Any]] = []
    for d in cost_drivers_filtered_input:
        cost_drivers_table.append({
            "Risk": d["risk_id"],
            "Title": d.get("title", d["risk_id"]),
            cost_value_col: round(d.get("value", 0.0), 2),
            "% of total": f"{d.get('pct_of_total', 0.0)*100:.1f}%",
            BASIS_COLUMN: basis_cell(cost_basis, d["risk_id"]),
        })

    rbs_l1_cost_rows = build_rbs_l1_cost_breakdown(
        integrated_results=integrated_dp,
        risks=risks_list,
        headline_metric=headline_metric,
        p_level=p_level,
    )
    rbs_l1_cost_table = [
        {
            "RBS Level 1 category": r["rbs_l1"],
            "Risk count": r["n_risks"],
            f"{r['metric_name']} contribution ($M)": round(r["value_M"], 2),
            "% of total": f"{r.get('pct_of_total', 0.0) * 100:.1f}%",
        }
        for r in rbs_l1_cost_rows
    ]
    rbs_l1_cost_metric_name = (
        rbs_l1_cost_rows[0]["metric_name"]
        if rbs_l1_cost_rows
        else cost_metric_label
    )

    page3_cost_drivers = {
        "tornado_path": cost_tornado_path,
        "drivers_table": cost_drivers_table,
        "drivers_table_full": cost_drivers_table_full,
        "metric_name": cost_metric_label,
        "value_column_header": cost_value_col,
        "rbs_l1_breakdown_table": rbs_l1_cost_table,
        "rbs_l1_metric_name": rbs_l1_cost_metric_name,
    }

    return {
        "cost_drivers_full": cost_drivers_full,
        "page3_cost_drivers": page3_cost_drivers,
    }
