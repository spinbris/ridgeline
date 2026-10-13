"""SRA Monte Carlo simulation engine (SR5, SP19).

Runs the schedule MC: per iteration, for each Time=Yes Open risk, draw a
Bernoulli on Probability (SPEC R-10), and if fired draw a PERT(Opt, ML, Pess) for
the duration in days. Apply the Mode multiplier (Series 1.0, Hybrid 0.5,
Parallel 0.0) and sum across risks for the iteration's total finish-delay.

Three public entry points:
- run_schedule_simulation: one full N-iteration simulation, optional Mode override
- run_counterfactual_table: 12-scenario counterfactual sweep (the SR5 PM pre-read)
- run_single_scenario_transparency: one iteration with full detail (transparency tool)

PERT sampler is imported from src/distributions.py (the cost engine's
calibrated PERT - one source of truth across cost and schedule).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.sra.mode_mix import format_mode_mix
from src.sra.mode_multipliers import resolve_mode_multiplier
import pandas as pd

from src.distributions import pert_from_uniform
from src.rng_streams import require_seed
from src.sra.sra_config import (
    DEFAULT_FALLBACK_MODE,
    SRAConfig,
)


# ----------------------------------------------------------------------------
# DUMMY_REALISTIC_MODE_OVERRIDE - Director-supplied Mode classification overrides
#
# These are hardcoded Mode classifications applied on top of the strawman's
# default Mode values for the "Dummy Realistic" (interim) scenario.
# This scenario is rendered ONLY in the dev report; prod report (under
# SR9 v3.3 Path A, 2026-04-27) uses DP Review baseline (strawman default,
# Risk_Scope.Mode_Aggregated) as its single source of truth.
#
# ARCHITECTURAL DEBT: this dict is hardcoded business logic in Python.
# Earmarked for retirement under SR10 (scenario directory architecture):
# the Dummy Realistic scenario will become its own time-stamped strawman
# folder under outputs/sra_strawman/scenarios/, eliminating the Python
# override layer entirely. Do not add new entries to this dict; flag any
# need for changes to the PM.
#
# Last reviewed: 2026-04-28 by the Director under SR9 v3.4.
# ----------------------------------------------------------------------------

DUMMY_REALISTIC_MODE_OVERRIDE: dict[str, str] = {
    "R017.1": "Series",
    "R067": "Series",
    "R090": "Series",
    "R013": "Hybrid",
    "R026.1": "Hybrid",
    "R015.1": "Parallel",
    "R016.1": "Parallel",
    "R016.2": "Parallel",
}


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _filter_simulating_risks(risk_scope_df: pd.DataFrame) -> pd.DataFrame:
    """Filter to Time_Impact=Yes rows. Returns a copy with reset index."""
    if "time_impact" not in risk_scope_df.columns:
        raise ValueError("risk_scope_df is missing 'time_impact' column")
    mask = risk_scope_df["time_impact"].astype(str).str.strip().str.lower() == "yes"
    sub = risk_scope_df[mask].copy().reset_index(drop=True)
    return sub


def simulating_risk_ids(risk_scope_df: pd.DataFrame) -> list[str]:
    """Return the list of risk_ids where Time_Impact == Yes.

    Single source of truth for downstream override-dict construction. Use
    this instead of any hardcoded risk-id list when building scenario
    overrides in scripts, notebooks, or tests.

    The strawman's Risk_Scope sheet is the canonical source for which
    risks simulate; this helper just exposes the filtered list as a plain
    list[str]. The shape of this list is asserted at runtime by
    `src.sra._pre_flight.assert_strawman_shape`.
    """
    sub = _filter_simulating_risks(risk_scope_df)
    return sub["risk_id"].astype(str).tolist()


def _resolve_mode(
    risk_id: str,
    strawman_mode: str,
    mode_override: dict[str, str] | None,
) -> str:
    """Return the Mode actually applied for this risk in this scenario."""
    if mode_override is not None and risk_id in mode_override:
        return mode_override[risk_id]
    return strawman_mode




# ----------------------------------------------------------------------------
# Core simulation
# ----------------------------------------------------------------------------

def run_schedule_simulation(
    config: SRAConfig,
    risk_scope_df: pd.DataFrame,
    classified_p6_df: pd.DataFrame | None = None,
    mode_override: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run N iterations of the schedule MC.

    Parameters
    ----------
    config : SRAConfig
        Run parameters (iterations, random_seed, mode_multipliers, day_rate).
    risk_scope_df : pd.DataFrame
        From strawman_reader.read_risk_scope. Filtered here to Time_Impact=Yes.
    classified_p6_df : pd.DataFrame or None
        From sra.critical_path.classify_activities. Currently unused at the
        per-iteration sampling level (Mode comes from the strawman's
        Mode_Aggregated column or mode_override). Carried through for future
        extensions.
    mode_override : dict[risk_id -> mode_string] or None
        Per-risk Mode overrides. Used by the counterfactual table to inject
        scenario classifications without modifying risk_scope_df.

    Returns
    -------
    dict with keys: iterations, finish_delay_days_array, fired_array,
    duration_array, contribution_array, mode_used, risk_ids, config, seed_used.
    """
    sub = _filter_simulating_risks(risk_scope_df)
    if len(sub) == 0:
        raise ValueError("No Time_Impact=Yes risks found in risk_scope_df")

    n_iter = int(config.iterations)
    n_risks = len(sub)
    risk_ids = sub["risk_id"].tolist()
    multipliers = config.mode_multipliers

    # Seed handling: refused by name when missing, never run as 0 (SEEDZERO-01 D1).
    seed_used = require_seed(config.random_seed,
                             where="src.sra.sra_simulation.run_schedule_simulation")
    rng = np.random.default_rng(seed_used)

    # Resolve modes per risk
    mode_used: dict[str, str] = {}
    multiplier_array = np.zeros(n_risks, dtype=np.float64)
    for i, rid in enumerate(risk_ids):
        strawman_mode = str(sub.loc[i, "mode_aggregated"] or DEFAULT_FALLBACK_MODE)
        applied_mode = _resolve_mode(rid, strawman_mode, mode_override)
        mode_used[rid] = applied_mode
        multiplier_array[i] = resolve_mode_multiplier(applied_mode, multipliers, rid)  # RS-D-3

    fired_array = np.zeros((n_iter, n_risks), dtype=bool)
    duration_array = np.zeros((n_iter, n_risks), dtype=np.float64)
    contribution_array = np.zeros((n_iter, n_risks), dtype=np.float64)

    for i, rid in enumerate(risk_ids):
        prob = float(sub.loc[i, "probability"] or 0.0)
        opt = float(sub.loc[i, "opt_days"] or 0.0)
        ml = float(sub.loc[i, "ml_days"] or 0.0)
        pess = float(sub.loc[i, "pess_days"] or 0.0)

        # Bernoulli gate for firing
        u_fire = rng.random(n_iter)
        fired = u_fire < prob
        fired_array[:, i] = fired

        # PERT duration draw (drawn for all iterations to keep RNG stream
        # deterministic across firing outcomes; only counted when fired)
        u_dur = rng.random(n_iter)
        if pess <= opt and pess <= ml:
            durations = np.full(n_iter, ml, dtype=np.float64)
        else:
            durations = pert_from_uniform(u_dur, opt, ml, pess)
        duration_array[:, i] = durations

        # Contribution: post-Mode multiplier, zero where not fired
        contribution_array[:, i] = np.where(
            fired, durations * multiplier_array[i], 0.0
        )

    finish_delay_days = contribution_array.sum(axis=1)

    return {
        "iterations": n_iter,
        "finish_delay_days_array": finish_delay_days,
        "fired_array": fired_array,
        "duration_array": duration_array,
        "contribution_array": contribution_array,
        "mode_used": mode_used,
        "risk_ids": risk_ids,
        "config": config,
        "seed_used": seed_used,
    }


# ----------------------------------------------------------------------------
# Counterfactual table - the central SR5 PM pre-read artefact
# ----------------------------------------------------------------------------

# Base scenarios that always run. Flip-to-Series scenarios (one per
# simulating risk) are appended at runtime by build_counterfactual_scenarios.
BASE_COUNTERFACTUAL_SCENARIOS: tuple[tuple[int, str], ...] = (
    (1, "Baseline (DP Review)"),
    (2, "All Series"),
    (3, "All Hybrid"),
    (4, "Dummy realistic"),
    # Beta-15 Item 3: All Parallel scenario for the §7 Mode-sensitivity
    # 4-row summary. Multiplier 0.0 makes the schedule contribution zero
    # for every risk by construction; useful as the methodologically
    # pure lower bound alongside All Series (upper bound) and All
    # Hybrid (midpoint). Flip-to-Series IDs (one per simulating risk)
    # start at len(BASE_COUNTERFACTUAL_SCENARIOS) + 1 = 6 from here on;
    # tests have been updated accordingly.
    (5, "All Parallel"),
)


def build_counterfactual_scenarios(
    simulating_ids: list[str],
) -> list[tuple[int, str]]:
    """Return the full list of (scenario_id, scenario_name) tuples.

    4 base scenarios + one flip-to-Series scenario per simulating risk.
    Flip-scenario IDs start at 5 and run consecutively. The list grows or
    shrinks with the strawman's Time_Impact=Yes set, never with code edits.
    """
    result = list(BASE_COUNTERFACTUAL_SCENARIOS)
    start_id = len(BASE_COUNTERFACTUAL_SCENARIOS) + 1
    for offset, rid in enumerate(simulating_ids):
        result.append((start_id + offset, f"{rid} -> Series"))
    return result


def _build_scenario_overrides(
    sub: pd.DataFrame,
) -> dict[int, dict[str, str] | None]:
    """Build the mode_override dict for each scenario.

    Scenario 1 returns None (use strawman as-is). Scenarios 2-4 force
    All-Series, All-Hybrid, and Dummy Realistic respectively. Each
    flip-to-Series scenario (5..(4+N) where N=len(risk_ids)) forces one
    named risk to Series and leaves others at strawman state. If the
    flipped risk is already Series in the strawman, the result equals
    the baseline (flagged by the caller).
    """
    risk_ids = sub["risk_id"].tolist()
    overrides: dict[int, dict[str, str] | None] = {
        1: None,
        2: {rid: "Series" for rid in risk_ids},
        3: {rid: "Hybrid" for rid in risk_ids},
        4: {
            rid: DUMMY_REALISTIC_MODE_OVERRIDE.get(rid, DEFAULT_FALLBACK_MODE)
            for rid in risk_ids
        },
        5: {rid: "Parallel" for rid in risk_ids},
    }
    start_id = len(BASE_COUNTERFACTUAL_SCENARIOS) + 1
    for offset, rid in enumerate(risk_ids):
        overrides[start_id + offset] = {rid: "Series"}
    return overrides


def _is_duplicate_of_baseline(
    scenario_modes_used: dict[str, str],
    baseline_modes_used: dict[str, str],
) -> bool:
    """True iff every risk's resolved mode matches between the two scenarios."""
    if set(scenario_modes_used.keys()) != set(baseline_modes_used.keys()):
        return False
    return all(scenario_modes_used[k] == baseline_modes_used[k] for k in scenario_modes_used)


def run_counterfactual_table(
    config: SRAConfig,
    risk_scope_df: pd.DataFrame,
    classified_p6_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run all 12 counterfactual scenarios and return a summary DataFrame.

    Each scenario uses an independent simulation with a fresh seed sequence
    (the simulation seeds are derived from config.random_seed plus an offset
    per scenario, to keep results reproducible while not having all scenarios
    use the same RNG draws).
    """
    sub = _filter_simulating_risks(risk_scope_df)
    overrides = _build_scenario_overrides(sub)
    scenarios = build_counterfactual_scenarios(sub["risk_id"].astype(str).tolist())

    base_seed = require_seed(config.random_seed,
                             where="src.sra.sra_simulation.run_counterfactual_table")

    rows: list[dict[str, Any]] = []
    baseline_modes_used: dict[str, str] | None = None
    baseline_mean: float | None = None

    for sid, name in scenarios:
        scenario_config = SRAConfig(
            register_path=config.register_path,
            p6_path=config.p6_path,
            strawman_path=config.strawman_path,
            iterations=config.iterations,
            seasons=config.seasons,
            p_levels=config.p_levels,
            random_seed=base_seed + sid,
            day_rate=config.day_rate,
            cp_hybrid_float_threshold=config.cp_hybrid_float_threshold,
            reporting_p_level=config.reporting_p_level,
            mode_multipliers=dict(config.mode_multipliers),
        )
        result = run_schedule_simulation(
            scenario_config, risk_scope_df, classified_p6_df,
            mode_override=overrides[sid],
        )
        delays = result["finish_delay_days_array"]
        mean_days = float(np.mean(delays))
        p50 = float(np.percentile(delays, 50))
        p80 = float(np.percentile(delays, 80))
        p90 = float(np.percentile(delays, 90))

        if sid == 1:
            baseline_modes_used = dict(result["mode_used"])
            baseline_mean = mean_days

        modes_list = [result["mode_used"][rid] for rid in result["risk_ids"]]
        is_dup = (
            sid != 1
            and baseline_modes_used is not None
            and _is_duplicate_of_baseline(result["mode_used"], baseline_modes_used)
        )

        rows.append({
            "scenario_id": sid,
            "scenario_name": name,
            "mode_mix_summary": format_mode_mix(modes_list),
            "mc_mean_days": mean_days,
            "mc_p50_days": p50,
            "mc_p80_days": p80,
            "mc_p90_days": p90,
            "mc_mean_dollars": mean_days * float(config.day_rate),
            "delta_from_baseline_days": (
                mean_days - baseline_mean if baseline_mean is not None else 0.0
            ),
            "is_duplicate_of_baseline": bool(is_dup),
        })

    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# Single-run transparency
# ----------------------------------------------------------------------------

def run_single_scenario_transparency(
    config: SRAConfig,
    risk_scope_df: pd.DataFrame,
    classified_p6_df: pd.DataFrame | None = None,
    seed: int | None = None,
    mode_override: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Single iteration with full per-risk detail, one row per simulating risk.

    Whatever seed produces is what gets reported. R067 fires only 2.5% of the
    time so most seeds will not fire it; the report is honest about this.

    ``seed`` is the caller's: there is no walkthrough seed of its own (SEEDZERO-01), so a
    walkthrough reproduces from the seed recorded with the run that asked for it.

    Beta-19b item 4: Mode source aligned with the schedule MC engine
    (:func:`run_schedule_simulation`). Reads each risk's Mode from
    ``risk_scope_df["mode_aggregated"]`` (the strawman's Risk_Scope sheet —
    the canonical run-time source). ``mode_override`` allows callers to
    inject scenario overrides analogous to the engine; legacy callers
    that previously relied on the hardcoded ``DUMMY_REALISTIC_MODE_OVERRIDE``
    fallback can pass it explicitly.
    """
    sub = _filter_simulating_risks(risk_scope_df)
    multipliers = config.mode_multipliers

    rng = np.random.default_rng(
        require_seed(seed, where="src.sra.sra_simulation.run_single_scenario_transparency"))
    rows: list[dict[str, Any]] = []
    total_contribution = 0.0

    risk_ids = sub["risk_id"].tolist()

    for i, rid in enumerate(risk_ids):
        prob = float(sub.loc[i, "probability"] or 0.0)
        opt = float(sub.loc[i, "opt_days"] or 0.0)
        ml = float(sub.loc[i, "ml_days"] or 0.0)
        pess = float(sub.loc[i, "pess_days"] or 0.0)
        strawman_mode = str(
            sub.loc[i, "mode_aggregated"] or DEFAULT_FALLBACK_MODE
        )
        applied_mode = _resolve_mode(rid, strawman_mode, mode_override)
        mult = resolve_mode_multiplier(applied_mode, multipliers, rid)  # RS-D-3

        u_fire = float(rng.random())
        fired = u_fire < prob
        u_dur = float(rng.random())

        if fired:
            if pess <= opt and pess <= ml:
                drawn = ml
            else:
                drawn = float(pert_from_uniform(np.array([u_dur]), opt, ml, pess)[0])
            contribution = drawn * mult
        else:
            drawn = float("nan")
            contribution = 0.0

        total_contribution += contribution
        rows.append({
            "risk_id": rid,
            "probability": prob,
            # Beta-15 Item 6: surface the per-risk uniform draws so the §7
            # walkthrough table can show how Fire? was decided (u_fire vs
            # probability) and which point on the PERT inverse-CDF the
            # duration was sampled at. No sampling-stream change — these
            # values were already drawn, just not previously returned.
            "u_fire_draw": u_fire,
            "fired": bool(fired),
            "u_dur_draw": u_dur,
            "drawn_duration_days": drawn,
            "mode": applied_mode,
            "mode_multiplier": mult,
            "contribution_days": contribution,
        })

    rows.append({
        "risk_id": "TOTAL",
        "probability": float("nan"),
        "u_fire_draw": float("nan"),
        "fired": "",
        "u_dur_draw": float("nan"),
        "drawn_duration_days": float("nan"),
        "mode": "",
        "mode_multiplier": float("nan"),
        "contribution_days": total_contribution,
    })
    df = pd.DataFrame(rows)
    # Beta-15 Item 6: state_cache (parquet) can't serialise mixed
    # bool / "" column dtype. Normalise the `fired` column to a string
    # type ("Yes"/"No"/"") so parquet round-trip works and the
    # word_generator's str branch handles the cell render. The bool
    # semantics are preserved by the deterministic mapping below.
    df["fired"] = df["fired"].map(
        lambda v: "Yes" if v is True else ("No" if v is False else "")
    )
    return df
