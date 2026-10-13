"""SRA post-simulation analysis (SR5, SP19).

Pure data manipulation. No rendering. Consumes the dict returned by
src.sra.sra_simulation.run_schedule_simulation and emits DataFrames and
dicts that the notebook formats for display.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------
# Percentiles and summary stats
# ----------------------------------------------------------------------------

def compute_percentiles(
    sim_results: dict[str, Any],
    p_levels: tuple[int, ...] = (50, 80, 90, 95, 99),
) -> pd.DataFrame:
    """Return DataFrame with columns p_level, finish_delay_days, finish_delay_dollars."""
    delays = np.asarray(sim_results["finish_delay_days_array"], dtype=np.float64)
    cfg = sim_results.get("config")
    day_rate = float(cfg.day_rate) if cfg is not None else 0.0

    rows = []
    for p in p_levels:
        days = float(np.percentile(delays, p))
        rows.append({
            "p_level": int(p),
            "finish_delay_days": days,
            "finish_delay_dollars": days * day_rate,
        })
    return pd.DataFrame(rows)


def compute_summary_stats(sim_results: dict[str, Any]) -> dict[str, float]:
    """Return mean, median, std, min, max, P50/P80/P90/P95/P99."""
    delays = np.asarray(sim_results["finish_delay_days_array"], dtype=np.float64)
    return {
        "mean": float(np.mean(delays)),
        "median": float(np.median(delays)),
        "std": float(np.std(delays)),
        "min": float(np.min(delays)),
        "max": float(np.max(delays)),
        "p50": float(np.percentile(delays, 50)),
        "p80": float(np.percentile(delays, 80)),
        "p90": float(np.percentile(delays, 90)),
        "p95": float(np.percentile(delays, 95)),
        "p99": float(np.percentile(delays, 99)),
    }


# ----------------------------------------------------------------------------
# Per-risk criticality (tornado-shaped table)
# ----------------------------------------------------------------------------

def compute_per_risk_criticality(
    sim_results: dict[str, Any],
    risk_scope_df: pd.DataFrame,
) -> pd.DataFrame:
    """Per-risk fire frequency, mean and P80 contribution, and P80 share.

    Sorted descending by contribution_to_p80_pct.
    """
    risk_ids: list[str] = list(sim_results["risk_ids"])
    fired_array = np.asarray(sim_results["fired_array"], dtype=bool)
    contribution_array = np.asarray(sim_results["contribution_array"], dtype=np.float64)
    delays = np.asarray(sim_results["finish_delay_days_array"], dtype=np.float64)
    mode_used: dict[str, str] = sim_results["mode_used"]
    n_iter = int(sim_results["iterations"])

    portfolio_p80 = float(np.percentile(delays, 80))
    p80_mask = delays >= portfolio_p80

    # Avoid divide-by-zero for the share column
    p80_band_total = float(contribution_array[p80_mask, :].sum()) if p80_mask.any() else 0.0

    # Pull title and probability from risk_scope_df
    scope_lookup = risk_scope_df.set_index("risk_id")

    rows = []
    for i, rid in enumerate(risk_ids):
        fired_count = int(fired_array[:, i].sum())
        fired_pct = fired_count / n_iter if n_iter > 0 else 0.0
        mean_contrib = float(contribution_array[:, i].mean())
        p80_contrib = float(np.percentile(contribution_array[:, i], 80))

        if p80_band_total > 0 and p80_mask.any():
            risk_p80_band_total = float(contribution_array[p80_mask, i].sum())
            share = risk_p80_band_total / p80_band_total
        else:
            share = 0.0

        title = ""
        prob = 0.0
        if rid in scope_lookup.index:
            row_lu = scope_lookup.loc[rid]
            title = str(row_lu.get("risk_title", "") or "")
            prob = float(row_lu.get("probability", 0.0) or 0.0)

        rows.append({
            "risk_id": rid,
            "risk_title": title,
            "mode": mode_used.get(rid, ""),
            "probability": prob,
            "fired_count": fired_count,
            "fired_pct": fired_pct,
            "mean_contribution_days": mean_contrib,
            "p80_contribution_days": p80_contrib,
            "contribution_to_p80_pct": share,
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("contribution_to_p80_pct", ascending=False).reset_index(drop=True)
    return df


# ----------------------------------------------------------------------------
# Calibration check
# ----------------------------------------------------------------------------

def compute_calibration_check(
    sim_results: dict[str, Any],
    strawman_calibration: dict[str, Any],
    absolute_tolerance_days: float,  # RS-D-2 review WARN: a register value, no code default
) -> dict[str, Any]:
    """Compare baseline MC Mean against strawman Comparator 2.

    Both quantities are expected to be near 1.75 days under the DP Review
    state (R090 Series, others Parallel). The check is on absolute agreement.
    """
    delays = np.asarray(sim_results["finish_delay_days_array"], dtype=np.float64)
    mc_mean = float(np.mean(delays))
    comp2 = strawman_calibration.get("comparator_2_finish_delay_days_pert")
    if comp2 is None:
        comp2_val = float("nan")
        gap = float("nan")
        passes = False
        interp = (
            "Strawman Comparator 2 not found in Summary sheet. Cannot evaluate "
            "calibration. Investigate the strawman read."
        )
    else:
        comp2_val = float(comp2)
        gap = abs(mc_mean - comp2_val)
        passes = gap <= float(absolute_tolerance_days)
        interp = (
            f"MC Mean = {mc_mean:.3f} days vs strawman Comparator 2 = "
            f"{comp2_val:.3f} days. Absolute gap = {gap:.3f} days "
            f"(tolerance {absolute_tolerance_days:.1f} days). "
            f"Both values are expected to be near 1.75 days under the DP "
            f"Review classification (R090 = Series; other 7 = Parallel), "
            f"with R090 the sole driver of baseline finish-delay."
        )
    return {
        "mc_mean_days": mc_mean,
        "strawman_comparator_2_days": comp2_val,
        "absolute_gap_days": gap,
        "absolute_tolerance_days": float(absolute_tolerance_days),
        "passes_calibration": bool(passes),
        "interpretation": interp,
    }
