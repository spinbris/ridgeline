"""Per-iteration joint cost+schedule sampler (SR8, SP21).

For dual-coded risks (Time=Yes), draws ONE shared uniform per iteration that
drives both the cost severity (via cost_dispatcher.sample_cost honouring V8
distribution_type) AND the schedule severity (via PERT on opt_d/ml_d/pess_d).
This produces correlated cost+schedule severity for the same risk: when a
risk has a bad iteration, it is bad on both axes simultaneously.

For cost-only risks (Time=No), draws an independent severity uniform; schedule
contribution is zero.

NO chain logic in this module. Chain1 and chain2 RESAMPLE-with-elevated-
probability mechanics are applied post-iteration in apply_chain_logic
(see integrated_simulation.py).
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.distributions import pert_from_uniform
from src.integrated.cost_dispatcher import _get_attr, sample_cost
from src.sra.mode_multipliers import resolve_mode_multiplier


# ----------------------------------------------------------------------------
# Per-risk single-iteration sampler
# ----------------------------------------------------------------------------

def sample_joint_risk(
    rng: np.random.Generator,
    risk_row: Any,
    is_dual_coded: bool,
    mode_multiplier: float,
    u_fire: float,
    opt_d: float = 0.0,
    ml_d: float = 0.0,
    pess_d: float = 0.0,
) -> dict[str, Any]:
    """Sample one risk's contribution for a single iteration.

    Parameters
    ----------
    rng : np.random.Generator
        Used to draw the severity uniform(s) for this risk this iteration.
    risk_row :
        RiskInput dataclass (from v5_register_reader). Must carry distribution,
        opt_cost, ml_cost, pess_cost, probability.
    is_dual_coded : bool
        True iff this risk is in the 8 Time=Yes set. Drives whether the
        severity uniform is shared (dual-coded) or independent (cost-only).
    mode_multiplier : float
        Series 1.0 / Hybrid 0.5 / Parallel 0.0 (read from the register's grid, RS-D-3b
        upstream). Multiplied into schedule_days_pre_mode to give schedule_days.
    u_fire : float
        The CG-correlated firing uniform for this risk this iteration. Comes
        from build_risk_uniform_matrix upstream.
    opt_d, ml_d, pess_d : float
        Schedule PERT parameters from strawman Risk_Scope. Zero for cost-only
        risks (or when not dual-coded).

    Returns
    -------
    dict with keys:
        - fired (bool)
        - u_fire (float; passed through)
        - u_cost_schedule (float | None; the shared uniform if dual-coded+fired)
        - u_cost_only (float | None; the independent uniform if cost-only+fired)
        - cost_dollars (float; 0 if not fired)
        - schedule_days_pre_mode (float; 0 if not fired or not dual-coded;
          raw PERT draw before mode multiplier - used by correlation health check)
        - schedule_days (float; = schedule_days_pre_mode * mode_multiplier)
    """
    probability = float(_get_attr(risk_row, "probability") or 0.0)
    fired = bool(u_fire < probability)

    out: dict[str, Any] = {
        "fired": fired,
        "u_fire": float(u_fire),
        "u_cost_schedule": None,
        "u_cost_only": None,
        "cost_dollars": 0.0,
        "schedule_days_pre_mode": 0.0,
        "schedule_days": 0.0,
    }

    if not fired:
        return out

    if is_dual_coded:
        u_shared = float(rng.random())
        out["u_cost_schedule"] = u_shared
        out["cost_dollars"] = float(sample_cost(risk_row, u_shared))
        sched_pre = float(
            pert_from_uniform(np.array([u_shared]), opt_d, ml_d, pess_d)[0]
        )
        out["schedule_days_pre_mode"] = sched_pre
        out["schedule_days"] = sched_pre * float(mode_multiplier)
    else:
        u_indep = float(rng.random())
        out["u_cost_only"] = u_indep
        out["cost_dollars"] = float(sample_cost(risk_row, u_indep))
        # schedule_days_pre_mode and schedule_days remain 0.0

    return out


# ----------------------------------------------------------------------------
# Per-iteration aggregator
# ----------------------------------------------------------------------------

def sample_iteration(
    rng: np.random.Generator,
    risks: list[Any],
    risk_scope_df: pd.DataFrame,
    fire_uniform_matrix_row: np.ndarray,
    mode_overrides: dict[str, str] | None = None,
    *,
    mode_multipliers: Mapping[str, float],
) -> dict[str, Any]:
    """Run one full integrated iteration across all risks in `risks`.

    Parameters
    ----------
    rng :
        RNG used for severity draws (shared u for dual-coded; independent for cost-only).
        The fire uniforms are NOT drawn here - they come pre-computed from
        build_risk_uniform_matrix to preserve CG correlations across risks.
    risks :
        List of RiskInput dataclasses from v5_register_reader. The full Open set.
    risk_scope_df :
        From strawman_reader.read_risk_scope. Used to identify the 8 dual-coded
        (Time_Impact=Yes) and look up their schedule PERT params + Mode.
    fire_uniform_matrix_row :
        np.ndarray of shape (n_risks,) - one row of the CG-correlated firing
        uniform matrix.
    mode_overrides :
        Optional {risk_id: mode_string} for counterfactual scenarios (All_Series,
        All_Hybrid, Dummy_Realistic). When None, Mode comes from risk_scope_df.

    Returns
    -------
    dict with per-iteration aggregates and per-risk values.
    """
    dual_lookup = _build_dual_lookup(risk_scope_df, mode_overrides, mode_multipliers=mode_multipliers)

    per_risk_cost: dict[str, float] = {}
    per_risk_schedule: dict[str, float] = {}
    per_risk_schedule_pre_mode: dict[str, float] = {}
    per_risk_fired: dict[str, bool] = {}

    for i, risk in enumerate(risks):
        rid = str(_get_attr(risk, "risk_id"))
        is_dc = rid in dual_lookup
        mode_mult = dual_lookup.get(rid, {}).get("mode_multiplier", 0.0)
        opt_d = dual_lookup.get(rid, {}).get("opt_d", 0.0)
        ml_d = dual_lookup.get(rid, {}).get("ml_d", 0.0)
        pess_d = dual_lookup.get(rid, {}).get("pess_d", 0.0)

        result = sample_joint_risk(
            rng=rng,
            risk_row=risk,
            is_dual_coded=is_dc,
            mode_multiplier=mode_mult,
            u_fire=float(fire_uniform_matrix_row[i]),
            opt_d=opt_d,
            ml_d=ml_d,
            pess_d=pess_d,
        )

        per_risk_cost[rid] = result["cost_dollars"]
        per_risk_schedule[rid] = result["schedule_days"]
        per_risk_schedule_pre_mode[rid] = result["schedule_days_pre_mode"]
        per_risk_fired[rid] = result["fired"]

    return {
        "total_cost_dollars": float(sum(per_risk_cost.values())),
        "total_schedule_days": float(sum(per_risk_schedule.values())),
        "per_risk_cost": per_risk_cost,
        "per_risk_schedule": per_risk_schedule,
        "per_risk_schedule_pre_mode": per_risk_schedule_pre_mode,
        "per_risk_fired": per_risk_fired,
    }


# ----------------------------------------------------------------------------
# Helper
# ----------------------------------------------------------------------------

def _build_dual_lookup(
    risk_scope_df: pd.DataFrame,
    mode_overrides: dict[str, str] | None,
    *,
    mode_multipliers: Mapping[str, float],
) -> dict[str, dict[str, Any]]:
    """Build {risk_id: {mode_multiplier, opt_d, ml_d, pess_d}} for dual-coded risks."""
    lookup: dict[str, dict[str, Any]] = {}
    if "time_impact" not in risk_scope_df.columns:
        return lookup
    mask = risk_scope_df["time_impact"].astype(str).str.strip().str.lower() == "yes"
    for _, row in risk_scope_df[mask].iterrows():
        rid = str(row["risk_id"])
        strawman_mode = str(row.get("mode_aggregated") or "Parallel")
        if mode_overrides and rid in mode_overrides:
            applied_mode = mode_overrides[rid]
        else:
            applied_mode = strawman_mode
        mode_mult = resolve_mode_multiplier(applied_mode, mode_multipliers, rid)  # RS-D-3
        lookup[rid] = {
            "mode_multiplier": mode_mult,
            "mode": applied_mode,
            "opt_d": float(row.get("opt_days") or 0.0),
            "ml_d": float(row.get("ml_days") or 0.0),
            "pess_d": float(row.get("pess_days") or 0.0),
        }
    return lookup
