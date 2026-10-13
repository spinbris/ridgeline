"""SR8 pure-data reporting layer. No HTML, no display, no matplotlib.

Returns dicts and DataFrames the integrated_runner.ipynb formats for display.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.integrated.integrated_simulation import IntegratedConfig
from src.integrated.run_config_contract import require_day_rate


# ----------------------------------------------------------------------------
# Configuration panel
# ----------------------------------------------------------------------------

def _strawman_version_date(p: Path) -> str:
    try:
        ts = p.stat().st_mtime
        return datetime.fromtimestamp(ts).date().isoformat()
    except Exception:
        return "(unknown)"


def get_config_panel_data(
    config: IntegratedConfig, run_config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "register_path": str(config.register_path),
        "p6_path": str(config.p6_path),
        "strawman_path": str(config.strawman_path),
        "strawman_version_date": _strawman_version_date(Path(config.strawman_path)),
        "iterations": int(config.iterations),
        "day_rate": require_day_rate(config.day_rate, caller="get_config_panel_data"),
        "cost_view": str(config.cost_view),
        "cost_calibration_tolerance_dollars": float(
            config.cost_calibration_tolerance_dollars
        ),
        "cost_calibration_tolerance_pct": float(config.cost_calibration_tolerance_pct),
        "schedule_calibration_tolerance_days": float(
            config.schedule_calibration_tolerance_days
        ),
        "reporting_p_level": int(config.reporting_p_level),
        "ld_layer_status": str(run_config.get("ld_layer_status", "OFF")),
    }


# ----------------------------------------------------------------------------
# Calibration panel
# ----------------------------------------------------------------------------

def get_calibration_panel_data(calibration: dict[str, Any]) -> dict[str, Any]:
    return {
        "cost_status_label": (
            "PASS" if calibration["cost_passes_calibration"] else "FAIL"
        ),
        "schedule_status_label": (
            "PASS" if calibration["schedule_passes_calibration"] else "FAIL"
        ),
        "both_pass": bool(calibration["both_pass"]),
        "cost_integrated_mean": float(calibration["cost_integrated_mean"]),
        "cost_standalone_l2only_mean": float(calibration["cost_standalone_l2only_mean"]),
        "cost_absolute_gap_dollars": float(calibration["cost_absolute_gap_dollars"]),
        "cost_relative_gap_pct": float(calibration["cost_relative_gap_pct"]),
        "schedule_integrated_mean_days": float(
            calibration["schedule_integrated_mean_days"]
        ),
        "schedule_standalone_mean_days": float(
            calibration["schedule_standalone_mean_days"]
        ),
        "schedule_absolute_gap_days": float(calibration["schedule_absolute_gap_days"]),
        "interpretation": str(calibration["interpretation"]),
    }


# ----------------------------------------------------------------------------
# Diversification panel (3 scenarios)
# ----------------------------------------------------------------------------

def get_diversification_panel_data(diversification: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenarios": diversification.get("scenarios", {}),
        "all_series_passes_gate": bool(diversification.get("all_series_passes_gate", False)),
        "interpretation": str(diversification.get("interpretation", "")),
    }


# ----------------------------------------------------------------------------
# Joint percentile table
# ----------------------------------------------------------------------------

def get_joint_percentile_table(joint_percentiles_df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "p_level", "cost_dollars", "schedule_days",
        "schedule_dollars", "integrated_total_dollars",
    ]
    available = [c for c in cols if c in joint_percentiles_df.columns]
    return joint_percentiles_df[available].copy()


# ----------------------------------------------------------------------------
# Correlation panel
# ----------------------------------------------------------------------------

def get_correlation_panel_data(correlations: dict[str, Any]) -> dict[str, Any]:
    return {
        "per_risk_correlations_pre_mode": correlations.get(
            "per_risk_correlations_pre_mode", {}
        ),
        "per_risk_correlations_post_mode": correlations.get(
            "per_risk_correlations_post_mode", {}
        ),
        "per_risk_correlations_cost_only": correlations.get(
            "per_risk_correlations_cost_only", {}
        ),
        "pearson_correlation_total": float(
            correlations.get("pearson_correlation_total", float("nan"))
        ),
        "spearman_correlation_total": float(
            correlations.get("spearman_correlation_total", float("nan"))
        ),
    }


# ----------------------------------------------------------------------------
# Disclaimer text
# ----------------------------------------------------------------------------

def get_disclaimer_text(
    config: IntegratedConfig, run_config: dict[str, Any],
) -> str:
    sv_date = _strawman_version_date(Path(config.strawman_path))
    day_rate = require_day_rate(config.day_rate, caller="get_joint_percentile_table")
    ld_status = str(run_config.get("ld_layer_status", "OFF"))

    paragraphs = [
        (
            "Joint sampling mechanism. For each of the 8 dual-coded "
            "(Time=Yes) risks, one shared uniform per iteration drives both "
            "the cost severity (via native distribution dispatch: PERT for "
            "R015.1/R016.2/R017.1/R090; Lognormal for R013/R016.1/R067; "
            "Triangular for R026.1) AND the schedule severity (via PERT on "
            "Opt/ML/Pess days from the strawman, scaled by the Mode "
            "multiplier). When a dual-coded risk has a bad iteration "
            "(u in the upper tail), it is bad on both axes simultaneously. "
            "Cost-only risks (the other 25 in V8 Open) use independent "
            "severity uniforms."
        ),
        (
            "Risk-set partitioning. 8 dual-coded risks (R013, R015.1, R016.1, "
            "R016.2, R017.1, R026.1, R067, R090) get joint cost+schedule "
            "treatment with shared uniform. The remaining 25 V8 Open risks "
            "get cost-only treatment with independent uniforms. Total 33 "
            "simulating risks. R044.2 was skipped at register read (zero "
            "probability)."
        ),
        (
            "Calibration gates. Cost marginal must reconcile to the cost "
            "engine's L2-only standalone run within $50,000 absolute OR "
            "0.1% relative. Schedule marginal must reconcile to SR5's "
            "standalone schedule MC within 1 day absolute. Both gates are "
            "evaluated at the headline mean. The L2-only target excludes "
            "Layer 1 WBS variation (the integrated engine does not include "
            "Layer 1; calibration vs full-cost standalone would be apples "
            "to oranges)."
        ),
        (
            "Diversification benefit. The integrated P80 (in dollars, with "
            "schedule converted at the day rate) sits below the naive sum "
            "of the cost-only P80 and the schedule-only P80 dollarised. "
            "The benefit is reported across three Mode-classification "
            "scenarios: DP Review baseline (informational, near-zero "
            "expected because only R090 contributes schedule), All Series "
            "(strict gate - must be > 0), and Dummy realistic interim "
            "(informational)."
        ),
        (
            f"Day rate basis. ${day_rate:,.0f} per working day (V8 derivation: "
            "$<weekly_prelims> weekly prelims x <programme_weeks> weeks / <programme_days> working days). "
            "Used to dollarise schedule contributions for the integrated "
            "P80 calculation."
        ),
        (
            f"LD layer status: {ld_status}. IDC layer status: OFF. Both "
            "deferred to SR10 when commercial inputs land (LD rate, EOT "
            "grounds, per-risk LD-impact flags from the contractor's commercial team)."
        ),
        (
            "Mode classification source. The strawman's DP Review state is "
            "the canonical Mode_Aggregated source, with R090 = Series and "
            "the other 7 dual-coded = Parallel. PM review will produce "
            "amended Mode classifications which propagate through "
            "Risk_Scope without code changes."
        ),
        (
            "Chain logic. Chain1 and chain2 RESAMPLE-with-elevated-"
            "probability mechanics are replicated post-iteration from "
            "MonteCarloEngine._apply_chain1 / ._apply_chain2 in "
            "src/simulation.py. The project binding's legacy chain trigger "
            "and target IDs do not exist in the Open set; chains skip "
            "cleanly. The replication code path is dormant for this project "
            "but ready for a binding that declares a live chain."
        ),
        (
            f"Strawman version date: {sv_date}. Source: "
            f"{Path(config.strawman_path).name}."
        ),
    ]
    return "\n\n".join(paragraphs)
