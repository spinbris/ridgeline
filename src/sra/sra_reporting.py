"""SRA pure-data reporting layer (SR5, SP19).

Returns dicts and DataFrames that the notebook formats for display.
NO HTML, NO display() calls, NO matplotlib. The notebook is the
presentation layer; this module is the data layer.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.sra.sra_config import SRAConfig
from src.sra.methodology_defaults_reader import read_calibration_tolerances


# ----------------------------------------------------------------------------
# Configuration panel
# ----------------------------------------------------------------------------

def _strawman_version_date(strawman_path: Path) -> str:
    try:
        ts = strawman_path.stat().st_mtime
        return datetime.fromtimestamp(ts).date().isoformat()
    except Exception:
        return "(unknown)"


def get_config_panel_data(config: SRAConfig, run_config: dict[str, Any]) -> dict[str, Any]:
    """Key-value pairs for the configuration panel section of the report."""
    return {
        "register_path": str(config.register_path),
        "p6_path": str(config.p6_path),
        "strawman_path": str(config.strawman_path),
        "strawman_version_date": _strawman_version_date(Path(config.strawman_path)),
        "iterations": int(config.iterations),
        "seasons": int(config.seasons),
        "day_rate": float(config.day_rate),
        "reconciliation_default": str(run_config.get("reconciliation_default", "A")),
        "cp_rule": str(run_config.get("cp_rule", "Option_Z_Hybrid")),
        "ld_layer_status": str(run_config.get("ld_layer_status", "OFF")),
        "reporting_p_level": int(config.reporting_p_level),
        # RS-D-2 (D-14): the tolerance is a register value now, not an SRAConfig field.
        "calibration_absolute_tolerance_days": float(
            read_calibration_tolerances(config.register_path, caller_module="src/sra/sra_reporting.py")[
                "schedule_calibration_tolerance_days"]
        ),
    }


# ----------------------------------------------------------------------------
# Calibration panel
# ----------------------------------------------------------------------------

def get_calibration_panel_data(calibration_check: dict[str, Any]) -> dict[str, Any]:
    """Pass-through with consistent key names; ensures the notebook has a
    single contract for the calibration card.
    """
    return {
        "mc_mean_days": calibration_check["mc_mean_days"],
        "strawman_comparator_2_days": calibration_check["strawman_comparator_2_days"],
        "absolute_gap_days": calibration_check["absolute_gap_days"],
        "absolute_tolerance_days": calibration_check["absolute_tolerance_days"],
        "passes_calibration": calibration_check["passes_calibration"],
        "interpretation": calibration_check["interpretation"],
        "status_label": "PASS" if calibration_check["passes_calibration"] else "FAIL",
    }


# ----------------------------------------------------------------------------
# Distribution panel (histogram data)
# ----------------------------------------------------------------------------

def get_distribution_panel_data(sim_results: dict[str, Any]) -> dict[str, Any]:
    """Histogram bin edges and counts plus key percentile lines.

    Notebook renders this with matplotlib; this module just shapes the data.
    """
    delays = np.asarray(sim_results["finish_delay_days_array"], dtype=np.float64)
    counts, bin_edges = np.histogram(delays, bins=50)
    return {
        "bin_edges": bin_edges.tolist(),
        "counts": counts.tolist(),
        "p50": float(np.percentile(delays, 50)),
        "p80": float(np.percentile(delays, 80)),
        "p90": float(np.percentile(delays, 90)),
        "p95": float(np.percentile(delays, 95)),
        "p99": float(np.percentile(delays, 99)),
        "mean": float(np.mean(delays)),
        "n": int(len(delays)),
    }


# ----------------------------------------------------------------------------
# Per-risk table
# ----------------------------------------------------------------------------

def get_per_risk_table(criticality_df: pd.DataFrame) -> pd.DataFrame:
    """Trim the criticality DataFrame for report display."""
    cols = [
        "risk_id", "risk_title", "mode", "probability", "fired_pct",
        "mean_contribution_days", "p80_contribution_days",
        "contribution_to_p80_pct",
    ]
    available = [c for c in cols if c in criticality_df.columns]
    return criticality_df[available].copy()


# ----------------------------------------------------------------------------
# Disclaimer text
# ----------------------------------------------------------------------------

def get_disclaimer_text(config: SRAConfig, run_config: dict[str, Any]) -> str:
    """Return the disclaimer text covering baseline state, R090 driver,
    counterfactual table purpose, R067 tail, day rate basis, LD status,
    Longest Path subset caveat, and strawman version date.
    """
    sv_date = _strawman_version_date(Path(config.strawman_path))
    day_rate = float(config.day_rate)
    ld_status = str(run_config.get("ld_layer_status", "OFF"))

    paragraphs = [
        (
            "Baseline state. The strawman's DP Review classification has 7 of "
            "the 8 Time=Yes simulating risks as Parallel and 1 (R090, "
            "Commissioning SP1/SP2) as Series. Baseline MC Mean is "
            "approximately 1.75 days, driven entirely by R090 (17.5% "
            "probability, PERT(0/10/20) days, Series multiplier 1.0). The "
            "other 7 risks contribute zero days to finish-date slippage "
            "because Mode = Parallel. PM review will determine whether each "
            "classification is correct."
        ),
        (
            "R090 worked example. A single Series risk with these parameters "
            "produces approximately 1.75 days Mean and approximately 14 days "
            "at P90. Parallel risks contribute zero regardless of how often "
            "they fire."
        ),
        (
            "The 12-scenario counterfactual table is the central artefact for "
            "PM review. Scenario 4 (Dummy realistic, interim) is a "
            "starting position for discussion, not a final answer. Scenario "
            "12 (R090 -> Series) equals baseline because R090 is already "
            "Series in the strawman; it is flagged is_duplicate_of_baseline "
            "for transparency."
        ),
        (
            "R067 tail handling. P80 is the primary metric, P90 secondary, "
            "and P99 is outlier-driven by R067's 2.5% probability and "
            "0/0/365 day distribution. R067 is Parallel under baseline so "
            "contributes zero; under alternative scenarios where R067 is "
            "Series, its tail dominates P99."
        ),
        (
            f"Day rate basis. ${day_rate:,.0f} per working day (V8 derivation: "
            "$<weekly_prelims> weekly prelims x <programme_weeks> weeks / <programme_days> working days)."
        ),
        (
            f"LD layer status: {ld_status}. Deferred to SR10 when LD inputs "
            "land (LD rate, EOT grounds, per-risk LD-impact flags from Contractor "
            "Commercial)."
        ),
        (
            "Longest Path subset caveat. The P6 file is a filtered subset, "
            "not the full schedule. Activities outside the longest path are "
            "by construction not on the critical path; the SR2 classifier "
            "operates within this subset."
        ),
        (
            f"Strawman version date: {sv_date}. Source: "
            f"{Path(config.strawman_path).name}."
        ),
    ]
    return "\n\n".join(paragraphs)
