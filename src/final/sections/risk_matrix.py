"""Risk-matrix section builder.

Produces the per-risk plot data underpinning the two-panel risk matrix
that sits in the schedule-drivers area (page 4) and the appendix
(per Beta-19 §2 relocation). The LEFT panel plots probability vs raw
EV PERT (Mode-independent expected impact when fired); the RIGHT panel
plots probability vs the Mode-multiplied per-risk column mean from the
indicative-scenario integrated engine.

Moved here under SR14a from ``src/final/composer.py`` (private helper
``_build_risk_matrix_data``). Composer re-exports the helper at module
level so existing test imports keep working.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def _risk_attr(r: Any, name: str, default: Any = None) -> Any:
    """Read a field off a RiskInput-like object or dict."""
    if isinstance(r, dict):
        return r.get(name, default)
    return getattr(r, name, default)


def _build_risk_matrix_data(
    risks: Iterable[Any],
    integrated_results: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build risk matrix data for the side-by-side scatter plots.

    Beta-14 §3: the LEFT (traditional) panel's ``mean_impact`` is the
    raw EV PERT from the register three-point — ``(opt + 4*ml + pess) / 6``
    — i.e. the Mode-independent expected impact when fired. The Beta-11
    derivation (engine column-mean / probability) was Mode-multiplied,
    which silently conflated the matrix's "mean impact when fired" axis
    with the Mode-weighted per-fire contribution; the prose-side
    interpretation paragraph (composer ``page4_schedule_drivers``)
    rewrites alongside this fix to name the Mode multiplier explicitly.

    The RIGHT (probability-weighted) panel continues to plot the engine's
    per-risk column mean (Mode-multiplied) — that is its definition.

    The two panels therefore differ by the Mode multiplier × probability
    factor; the prose reads the two panels honestly rather than passing
    the Mode-multiplied figure off as "mean impact when fired".

    Documented in ``commentary_text.RISK_MATRIX_ORIENTING(_TEMPLATE)``.
    """
    per_risk = np.asarray(integrated_results.get("per_risk_schedule_array", []))
    risk_ids = list(integrated_results.get("risk_ids_dual", []))
    pw_lookup = {}
    if per_risk.size > 0 and risk_ids:
        means = per_risk.mean(axis=0)
        pw_lookup = {rid: float(means[i]) for i, rid in enumerate(risk_ids)}

    out: list[dict[str, Any]] = []
    for r in risks:
        rid = _risk_attr(r, "risk_id")
        prob = float(_risk_attr(r, "probability", 0.0) or 0.0)
        opt_days = float(_risk_attr(r, "opt_schedule_days", 0.0) or 0.0)
        ml_days = float(_risk_attr(r, "ml_days", 0.0) or 0.0)
        pess_days = float(_risk_attr(r, "pess_schedule_days", 0.0) or 0.0)
        if prob <= 0 and ml_days <= 0 and rid not in pw_lookup:
            continue
        # RIGHT panel: Mode-aware column mean (zero when the risk is
        # Parallel in the indicative scenario). pw_lookup falls back to
        # prob × ml_days for risks not in the dual-coded set (cost-only).
        column_mean = pw_lookup.get(rid, prob * ml_days)
        # LEFT panel: raw EV PERT from the register three-point. Mode-
        # independent — the value is the same whether the indicative
        # scenario classifies this risk Series, Hybrid, or Parallel. A
        # risk with all three points zero plots at the origin (cost-only
        # risks excluded by the filter above).
        raw_ev_pert = (opt_days + 4.0 * ml_days + pess_days) / 6.0
        out.append({
            "risk_id": rid,
            "probability": prob,
            "mean_impact": raw_ev_pert,
            "prob_weighted_impact": column_mean,
        })
    return out


def build_risk_matrix_section(
    risks: Iterable[Any],
    integrated_results: dict[str, Any],
) -> dict[str, Any]:
    """Build the risk-matrix section dict.

    Returns
    -------
    dict[str, Any]
        Risk-matrix dict with keys:

        * ``data`` (list[dict]): one entry per included risk with keys
          ``risk_id``, ``probability``, ``mean_impact`` (raw EV PERT
          working-days, Mode-independent — LEFT panel), and
          ``prob_weighted_impact`` (engine column-mean working-days,
          Mode-multiplied — RIGHT panel).

    Notes
    -----
    Risks with probability ≤ 0 AND ml_days ≤ 0 AND no entry in the
    integrated engine's ``risk_ids_dual`` are excluded (cost-only risks
    with no schedule footprint).

    The chart-rendering path (orienting / interpretation prose, panel
    PNG, forward-reference sentence) is the composer's responsibility
    (Decision D3=A — narrative text applies in the stage-specific
    composer, not in the section builder).
    """
    return {
        "data": _build_risk_matrix_data(risks, integrated_results),
    }
