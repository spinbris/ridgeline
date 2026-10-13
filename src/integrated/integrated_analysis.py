"""SR8 post-simulation analysis. Pure-data layer. No rendering.

Consumes the dict returned by run_integrated_simulation plus standalone cost
(L2-only) and schedule (SR5) results, and emits DataFrames and dicts that the
notebook formats for display.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from src.integrated.integrated_simulation import IntegratedConfig
from src.integrated.run_config_contract import require_day_rate
from src.per_day_curve import compute_per_day_curve as _compute_per_day_curve


# ----------------------------------------------------------------------------
# Marginal calibration: integrated vs L2-only standalone (cost) and SR5 (schedule)
# ----------------------------------------------------------------------------

def compute_marginal_calibration(
    integrated_results: dict[str, Any],
    standalone_cost_l2only_results: dict[str, Any],
    standalone_schedule_results: dict[str, Any],
    config: IntegratedConfig,
) -> dict[str, Any]:
    """Compare integrated marginals to standalone runs.

    standalone_cost_l2only_results : dict with key "ev_costs_array" (or "cost_dollars_array")
        carrying a 1-D ndarray of total per-iteration cost from a cost engine
        run with view='L2Only'.
    standalone_schedule_results : dict with key "finish_delay_days_array" from
        SR5 run_schedule_simulation.
    """
    cost_int = np.asarray(integrated_results["cost_dollars_array"], dtype=np.float64)
    cost_std = np.asarray(_get(standalone_cost_l2only_results,
                                ("cost_dollars_array", "ev_costs_array")),
                          dtype=np.float64)
    cost_int_mean = float(np.mean(cost_int))
    cost_std_mean = float(np.mean(cost_std))
    cost_gap = abs(cost_int_mean - cost_std_mean)
    # Review WARN (RS-D-2): the gap is |.|, so the denominator is |.| too - a negative
    # standalone mean (opportunity-dominated) must not yield a negative pct that passes.
    cost_pct = cost_gap / abs(cost_std_mean) if cost_std_mean else float("inf")
    cost_passes = (
        cost_gap <= float(config.cost_calibration_tolerance_dollars)
        or cost_pct <= float(config.cost_calibration_tolerance_pct)
    )

    sched_int = np.asarray(integrated_results["schedule_days_array"], dtype=np.float64)
    sched_std = np.asarray(
        standalone_schedule_results["finish_delay_days_array"], dtype=np.float64,
    )
    sched_int_mean = float(np.mean(sched_int))
    sched_std_mean = float(np.mean(sched_std))
    sched_gap = abs(sched_int_mean - sched_std_mean)
    sched_pct = sched_gap / abs(sched_std_mean) if sched_std_mean else float("inf")
    # RS-D-2 (D-14): the schedule check takes the cost check's shape - days OR percent.
    sched_passes = (
        sched_gap <= float(config.schedule_calibration_tolerance_days)
        or sched_pct <= float(config.schedule_calibration_tolerance_pct)
    )

    both = bool(cost_passes and sched_passes)

    interp = (
        f"Cost marginal: integrated mean=${cost_int_mean/1e6:.3f}M vs "
        f"L2-only standalone mean=${cost_std_mean/1e6:.3f}M "
        f"(gap ${cost_gap/1e3:.0f}k absolute, {cost_pct*100:.3f}% relative; "
        f"tol ${config.cost_calibration_tolerance_dollars/1e3:.0f}k OR "
        f"{config.cost_calibration_tolerance_pct*100:.2f}%) - "
        f"{'PASS' if cost_passes else 'FAIL'}.\n"
        f"Schedule marginal: integrated mean={sched_int_mean:.3f} days vs "
        f"SR5 standalone mean={sched_std_mean:.3f} days "
        f"(gap {sched_gap:.3f} days absolute, {sched_pct*100:.2f}% relative; "
        f"tol {config.schedule_calibration_tolerance_days:.1f} days OR "
        f"{config.schedule_calibration_tolerance_pct*100:.1f}%) - "
        f"{'PASS' if sched_passes else 'FAIL'}."
    )

    return {
        "cost_integrated_mean": cost_int_mean,
        "cost_standalone_l2only_mean": cost_std_mean,
        "cost_absolute_gap_dollars": cost_gap,
        "schedule_relative_gap_pct": sched_pct,
        "cost_relative_gap_pct": cost_pct,
        "cost_passes_calibration": bool(cost_passes),
        "schedule_integrated_mean_days": sched_int_mean,
        "schedule_standalone_mean_days": sched_std_mean,
        "schedule_absolute_gap_days": sched_gap,
        "schedule_passes_calibration": bool(sched_passes),
        "both_pass": both,
        "interpretation": interp,
    }


# ----------------------------------------------------------------------------
# Mean-equivalents of the SR9 component-breakdown row set (SR9 v3.5)
# ----------------------------------------------------------------------------

def compute_mean_metrics(
    integrated_results: dict[str, Any],
    standalone_cost_l2only_results: dict[str, Any],
    standalone_schedule_results: dict[str, Any],
    config: IntegratedConfig,
) -> dict[str, float]:
    """Mean-equivalents of the Page 1 component-breakdown row set.

    Returns a dict with keys:
        cost_mean_dollars
        schedule_mean_days
        schedule_mean_dollars (= schedule_mean_days * day_rate)
        naive_sum_mean_dollars (= cost_mean + schedule_mean_dollars)
        integrated_mean_dollars (= np.mean(cost + schedule * day_rate))
        diversification_at_mean_dollars (= naive_sum_mean - integrated_mean)

    Mean is the arithmetic mean of the underlying numpy arrays; reuses the
    same arrays compute_marginal_calibration / compute_diversification_benefit
    consume, no new sampler.

    Sign convention. `diversification_at_mean_dollars` is computed as
    `naive_sum_mean - integrated_mean` here, matching the convention used by
    `compute_diversification_benefit` (positive = naive sum exceeds joint
    integrated; conventionally a "benefit"). Note that
    `src/final/composer._compute_component_breakdown` uses the OPPOSITE
    sign convention internally for both its P80 and Mean rows
    (`integrated - naive_sum`; positive = joint MC adds cost vs naive sum).
    Both conventions are internally consistent; they predate SR9 v3.5.
    Consumers calling both functions should be aware of the difference.
    """
    day_rate = require_day_rate(config.day_rate, caller="compute_mean_metrics")

    cost_arr = np.asarray(_get(standalone_cost_l2only_results,
                               ("cost_dollars_array", "ev_costs_array")),
                          dtype=np.float64)
    sched_arr = np.asarray(
        standalone_schedule_results["finish_delay_days_array"], dtype=np.float64,
    )
    cost_int = np.asarray(integrated_results["cost_dollars_array"], dtype=np.float64)
    sched_int = np.asarray(integrated_results["schedule_days_array"], dtype=np.float64)
    integrated_total = cost_int + sched_int * day_rate

    cost_mean = float(np.mean(cost_arr))
    sched_mean_days = float(np.mean(sched_arr))
    sched_mean_dollars = sched_mean_days * day_rate
    naive_sum_mean = cost_mean + sched_mean_dollars
    integrated_mean = float(np.mean(integrated_total))
    diversification_at_mean = naive_sum_mean - integrated_mean

    return {
        "cost_mean_dollars": cost_mean,
        "schedule_mean_days": sched_mean_days,
        "schedule_mean_dollars": sched_mean_dollars,
        "naive_sum_mean_dollars": naive_sum_mean,
        "integrated_mean_dollars": integrated_mean,
        "diversification_at_mean_dollars": diversification_at_mean,
    }


# ----------------------------------------------------------------------------
# Diversification: three Mode-classification scenarios
# ----------------------------------------------------------------------------

def compute_diversification_benefit(
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    standalone_cost_l2only_results: dict[str, Any],
    standalone_schedule_results_by_scenario: dict[str, dict[str, Any]],
    config: IntegratedConfig,
) -> dict[str, Any]:
    """Quantify diversification benefit across three Mode scenarios.

    integrated_results_by_scenario : {"DP_Review": dict, "All_Series": dict, "Dummy_Realistic": dict}
        From run_integrated_simulation under each Mode override.
    standalone_cost_l2only_results :
        Single L2-only cost run (cost is independent of Mode classification).
    standalone_schedule_results_by_scenario : {"DP_Review": dict, "All_Series": dict, "Dummy_Realistic": dict}
        Schedule SR5 runs under each Mode override (different per scenario because
        schedule depends on Mode multipliers).
    """
    p_level = int(config.reporting_p_level)
    day_rate = require_day_rate(config.day_rate, caller="compute_diversification_benefit")
    cost_arr = np.asarray(_get(standalone_cost_l2only_results,
                               ("cost_dollars_array", "ev_costs_array")),
                          dtype=np.float64)
    cost_only_p = float(np.percentile(cost_arr, p_level))

    scenarios_out: dict[str, dict[str, Any]] = {}
    for name in ("DP_Review", "All_Series", "Dummy_Realistic"):
        sched_std = standalone_schedule_results_by_scenario.get(name)
        integrated = integrated_results_by_scenario.get(name)
        if sched_std is None or integrated is None:
            continue
        sched_arr = np.asarray(sched_std["finish_delay_days_array"], dtype=np.float64)
        sched_only_p_days = float(np.percentile(sched_arr, p_level))
        sched_only_p_dollars = sched_only_p_days * day_rate
        naive_sum = cost_only_p + sched_only_p_dollars

        cost_int = np.asarray(integrated["cost_dollars_array"], dtype=np.float64)
        sched_int = np.asarray(integrated["schedule_days_array"], dtype=np.float64)
        total_int = cost_int + sched_int * day_rate
        integrated_p = float(np.percentile(total_int, p_level))

        diversification_dollars = naive_sum - integrated_p
        diversification_pct = (
            diversification_dollars / naive_sum if naive_sum > 0 else 0.0
        )
        scenarios_out[name] = {
            "p_level": p_level,
            "cost_only_p80_dollars": cost_only_p,
            "schedule_only_p80_days": sched_only_p_days,
            "schedule_only_p80_dollars_at_day_rate": sched_only_p_dollars,
            "naive_sum_p80_dollars": naive_sum,
            "integrated_p80_dollars": integrated_p,
            "diversification_dollars": diversification_dollars,
            "diversification_pct": diversification_pct,
        }

    all_series = scenarios_out.get("All_Series")
    all_series_passes = bool(
        all_series is not None and all_series["diversification_dollars"] > 0
    )

    interp_parts: list[str] = []
    if "DP_Review" in scenarios_out:
        d = scenarios_out["DP_Review"]
        interp_parts.append(
            f"DP Review (informational): diversification "
            f"${d['diversification_dollars']/1e6:.3f}M "
            f"({d['diversification_pct']*100:.2f}%). Near-zero is expected because "
            f"only R090 contributes schedule under all-Parallel + R090-Series baseline."
        )
    if all_series is not None:
        d = all_series
        interp_parts.append(
            f"All Series (gate): diversification ${d['diversification_dollars']/1e6:.3f}M "
            f"({d['diversification_pct']*100:.2f}%). "
            f"{'PASSES (>0)' if all_series_passes else 'FAILS (<=0; mathematically impossible under correct joint sampling)'}."
        )
    if "Dummy_Realistic" in scenarios_out:
        d = scenarios_out["Dummy_Realistic"]
        interp_parts.append(
            f"Dummy realistic (informational): diversification "
            f"${d['diversification_dollars']/1e6:.3f}M ({d['diversification_pct']*100:.2f}%)."
        )

    return {
        "scenarios": scenarios_out,
        "all_series_passes_gate": all_series_passes,
        "interpretation": "\n".join(interp_parts),
    }


# ----------------------------------------------------------------------------
# Joint percentiles (cost, schedule, integrated total at each P-level)
# ----------------------------------------------------------------------------

def compute_joint_percentiles(
    integrated_results: dict[str, Any],
    # DAYRATE-02 B2: required, same treatment and same reasoning as B1. All
    # three callers pass it by keyword already.
    day_rate: float,
    p_levels: tuple[int, ...] = (50, 80, 90, 95, 99),
) -> pd.DataFrame:
    cost_arr = np.asarray(integrated_results["cost_dollars_array"], dtype=np.float64)
    sched_arr = np.asarray(integrated_results["schedule_days_array"], dtype=np.float64)
    total_arr = cost_arr + sched_arr * float(day_rate)

    rows = []
    for p in p_levels:
        rows.append({
            "p_level": int(p),
            "cost_dollars": float(np.percentile(cost_arr, p)),
            "schedule_days": float(np.percentile(sched_arr, p)),
            "schedule_dollars": float(np.percentile(sched_arr, p)) * float(day_rate),
            "integrated_total_dollars": float(np.percentile(total_arr, p)),
        })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# Correlation metrics
# ----------------------------------------------------------------------------

def compute_correlation_metrics(integrated_results: dict[str, Any]) -> dict[str, Any]:
    """Correlations to verify the joint sampling mechanism.

    Returns:
      {
        "per_risk_correlations_pre_mode": dict,    # PRIMARY (mode-independent sampler check)
        "per_risk_correlations_post_mode": dict,   # SECONDARY (NaN if Parallel)
        "pearson_correlation_total": float,
        "spearman_correlation_total": float,
        "per_risk_correlations_cost_only": dict,
      }
    """
    risk_ids_all: list[str] = list(integrated_results["risk_ids_all"])
    risk_ids_dual: list[str] = list(integrated_results["risk_ids_dual"])
    cost_arr = np.asarray(integrated_results["per_risk_cost_array"], dtype=np.float64)
    sched_arr = np.asarray(integrated_results["per_risk_schedule_array"], dtype=np.float64)
    sched_pre_arr = np.asarray(
        integrated_results["per_risk_schedule_pre_mode_array"], dtype=np.float64,
    )
    total_sched = np.asarray(
        integrated_results["schedule_days_array"], dtype=np.float64,
    )
    total_cost = np.asarray(
        integrated_results["cost_dollars_array"], dtype=np.float64,
    )

    cost_idx = {rid: i for i, rid in enumerate(risk_ids_all)}
    dual_idx = {rid: i for i, rid in enumerate(risk_ids_dual)}

    pre_mode: dict[str, float] = {}
    post_mode: dict[str, float] = {}
    for rid in risk_ids_dual:
        ci = cost_idx.get(rid)
        di = dual_idx.get(rid)
        if ci is None or di is None:
            continue
        c = cost_arr[:, ci]
        s_pre = sched_pre_arr[:, di]
        s_post = sched_arr[:, di]
        pre_mode[rid] = _safe_corr(c, s_pre)
        post_mode[rid] = _safe_corr(c, s_post)

    cost_only_corr: dict[str, float] = {}
    for rid in risk_ids_all:
        if rid in dual_idx:
            continue
        ci = cost_idx.get(rid)
        if ci is None:
            continue
        cost_only_corr[rid] = _safe_corr(cost_arr[:, ci], total_sched)

    pearson_total = _safe_corr(total_cost, total_sched)
    try:
        spearman_total = float(stats.spearmanr(total_cost, total_sched).statistic)
    except Exception:
        spearman_total = float("nan")

    return {
        "per_risk_correlations_pre_mode": pre_mode,
        "per_risk_correlations_post_mode": post_mode,
        "pearson_correlation_total": pearson_total,
        "spearman_correlation_total": spearman_total,
        "per_risk_correlations_cost_only": cost_only_corr,
    }


# ----------------------------------------------------------------------------
# SP18b — Per-day P-curve
# ----------------------------------------------------------------------------

def compute_per_day_curve(
    integrated_results: dict[str, Any],
    config: IntegratedConfig,
) -> dict[str, Any]:
    """Build the per-day P-curve from the integrated engine's timed_events.

    Pure-data layer: returns the matrix + percentile trajectories for the
    notebook / chart layer to render. No I/O, no plotting.

    Returns the dict produced by :func:`src.per_day_curve.compute_per_day_curve`.
    When the curve is disabled (``programme_days <= 0`` or
    ``per_day_curve_enabled is False``), the returned dict has
    ``enabled = False`` and a ``reason`` string; callers should skip rendering.

    NOTE: this is NOT a phased S-curve. It shows when risk-driven cost
    crystallises across project days, not when contractual cash flows occur.
    The chart caption (in src/charts.generate_per_day_pcurve) makes this
    explicit; commentary built on these numbers must do the same.
    """
    if not getattr(config, "per_day_curve_enabled", True):
        return {
            "enabled": False,
            "reason": "per_day_curve_enabled is False",
        }
    timed_events = integrated_results.get("timed_events")
    if timed_events is None:
        return {
            "enabled": False,
            "reason": "integrated_results has no timed_events key",
        }
    return _compute_per_day_curve(
        timed_events,
        programme_days=int(config.programme_days),
        cost_bin_size=int(config.per_day_cost_bin_size),
        max_cost=int(config.per_day_max_cost),
        percentiles=(50.0, 80.0, 90.0),
    )


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _safe_corr(x: np.ndarray, y: np.ndarray) -> float:
    """Pearson correlation, NaN if either has zero variance."""
    if np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return float("nan")
    try:
        return float(np.corrcoef(x, y)[0, 1])
    except Exception:
        return float("nan")


def _get(d: dict, keys: tuple[str, ...]) -> Any:
    """Get the first present key from a tuple of candidates."""
    for k in keys:
        if k in d:
            return d[k]
    raise KeyError(f"None of the keys {keys} found in dict")
