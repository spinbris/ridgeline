"""Integrated cost+schedule MC outer loop (SR8, SP21).

Mirrors the cost engine architecture (Layer 2 + chains) but joint-samples
cost and schedule for the 8 dual-coded (Time=Yes) risks via a shared per-risk
severity uniform.

Scope: Layer 2 only (event risks). No Layer 1 WBS variation in the integrated
engine; calibration target is the cost engine's L2-only standalone run.

Chain logic is applied post-iteration via apply_chain_logic, replicating the
RESAMPLE-with-elevated-probability mechanism from MonteCarloEngine._apply_chain1
and ._apply_chain2. The chain trigger/target IDs come from the active project
binding's legacy chain map (see ``defaults.get_chain_risk_ids``); for a project
none of them are in the V9 Open set, so chains skip cleanly via _find_risk_index
returning None. The replication code path is dormant there but ready for
projects whose binding declares a live chain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.config import ChainConfig
from src.correlations import build_risk_uniform_matrix
from src.distributions import pert_from_uniform
from src.integrated.cost_dispatcher import _get_attr, sample_cost
from src.rng_streams import require_seed
from src.integrated.run_config_contract import (
    read_run_config_strict,
    resolve_day_rate,
    resolve_programme_days,
)
from src.layer1_factors import Layer1Config
from src.sra.methodology_defaults_reader import (
    read_calibration_tolerances,
    MethodologyDefaults,
    read_methodology_defaults,
)
from src.sra.mode_multipliers import resolve_mode_multiplier
from src.sra.strawman_reader import read_run_config

# QRAXL-01 scope A: the numeric cost sampler was moved VERBATIM to
# src/qra_core.py (the Pyodide-clean shared core both tiers import). This module
# is now the pandas-bound Tier-2 shell: it resolves config + Risk_Scope, then
# delegates the whole RNG-consuming run to qra_core.run_cost_layer. Re-exported
# here so existing importers of these symbols from integrated_simulation keep
# working.
from src.qra_core import (  # noqa: E402  (re-export for backward-compat)
    run_cost_layer,
    apply_chain_logic,
    _apply_chain1_logic,
    _apply_chain2_logic,
    _resample_target,
    _find_risk_index,
    _sample_cost_vec,
)


# ----------------------------------------------------------------------------
# IntegratedConfig
# ----------------------------------------------------------------------------

def _default_chain_risk_ids() -> dict[str, Any]:
    """Default-factory for ``IntegratedConfig.chain_risk_ids``.

    Resolved at config-construction time (not import time) from the active
    project binding, via ``defaults.get_chain_risk_ids``. Deferring to
    call time keeps the binding off this module's import path and avoids a
    cycle (the binding imports this module).
    """
    from src.defaults import get_chain_risk_ids

    return get_chain_risk_ids()


@dataclass
class IntegratedConfig:
    register_path: Path
    p6_path: Path
    strawman_path: Path
    # SR19 §6.2: methodology_defaults is REQUIRED (no default per SR19-D1
    # type-level enforcement). Field placed with kw_only=True so the
    # existing positional-construction surface is preserved for callers
    # that pass the four required fields by position (register_path,
    # p6_path, strawman_path, methodology_defaults). load_integrated_config
    # is the canonical construction path; tests that build IntegratedConfig
    # directly use src.sra.methodology_defaults_reader.build_test_methodology_defaults()
    # to construct the dataclass.
    methodology_defaults: MethodologyDefaults = field(kw_only=True)
    iterations: int = 100000
    p_levels: tuple[int, ...] = (50, 80, 90, 95, 99)
    random_seed: int | None = None
    # DAYRATE-02 B3, Director ruling 31/08: NO default, and not a
    # binding-resolved one either. Every hardcoded number is wrong, because it
    # belongs to some other project - and a literal relocated into a binding is
    # still a hardcoded number that can go stale against the workbook it was
    # copied from. So the field is None until something sources a rate, and
    # every calculation that consumes one goes through require_day_rate and
    # stops if nothing did. The ~40 construction sites that never read the
    # field are unaffected; the ones that do read it now fail loudly instead of
    # quietly inheriting another project's commercial rate.
    day_rate: float | None = None
    # RS-D-2 (D-14): the four calibration tolerances are register values, required,
    # no default - cost passes on dollars OR percent, schedule on days OR percent.
    # Read them with methodology_defaults_reader.read_calibration_tolerances.
    cost_calibration_tolerance_dollars: float = field(kw_only=True)
    cost_calibration_tolerance_pct: float = field(kw_only=True)
    schedule_calibration_tolerance_days: float = field(kw_only=True)
    schedule_calibration_tolerance_pct: float = field(kw_only=True)
    # Stage 4 F-30: the schedule top-3 tie band, a fraction of third place. Register-read with
    # the four above; the engine carries no default.
    schedule_top3_tie_tolerance_pct: float = field(kw_only=True)
    reporting_p_level: int = 80
    cost_view: str = "L2Only"
    chain_config_source: str = "cost_engine"
    # Set by callers (Stage 3 client path, wind, capture) but not read by the
    # engine (the cost arm uses methodology_defaults.cg_coefficients). QRAXL-01
    # Coupling C: the default no longer references the evacuated
    # defaults.HEADLESS_CG_COEFFICIENTS constant (which now fails loud without a
    # selected binding); an empty default is safe since the field is never read.
    cg_correlation_coefficients: dict[str, float] = field(default_factory=dict)
    chain_config: ChainConfig = field(default_factory=ChainConfig)
    chain_risk_ids: dict[str, Any] = field(
        default_factory=_default_chain_risk_ids
    )
    # SP18b — Per-day P-curve parameters.
    # programme_days is auto-populated from the strawman in load_integrated_config
    # below (read_run_config -> schedule_duration_weeks * 5 working days).
    # If 0 after auto-populate, the per-day curve is disabled with a warning.
    per_day_curve_enabled: bool = True
    per_day_cost_bin_size: int = 100_000          # AUD per bin
    per_day_max_cost: int = 200_000_000           # cap for binning
    programme_days: int = 0                        # 0 ⇒ disable curve, warn
    # SP18c — Temporal cascade activation parameters.
    # cascade_enabled mirrors ChainConfig.cascade_enabled — kept on
    # IntegratedConfig for the integrated engine's hook in addition to the
    # cost-only engine's existing flag. Default False; the cascade-off path
    # is byte-identical to the pre-sp18c-baseline locked output.
    cascade_enabled: bool = False
    # Option A (default) propagates Mode-multiplied days into cascade slip.
    # Option B (cascade_use_raw_days=True) propagates raw, unmultiplied days.
    # See METHODOLOGY.md §10.4 and the SP18c brief §3.
    cascade_use_raw_days: bool = False
    # When True, raise on any parent-child pair found in BOTH a
    # Risk_Network_Edges entry AND a shared Cascade_Group. When False,
    # warn and continue. See SP18c brief §7.
    strict_overlap_check: bool = False
    # Cap on how many cascade events the kernel records into the audit log.
    cascade_audit_sample_cap: int = 100
    # QRAXL-01 step 4 - Layer-1 factor model (owner / whole-project view).
    # None => Layer 1 OFF (shared-pool view), byte-identical to the L2-only
    # baseline. A populated Layer1Config switches Layer 1 ON for the owner view.
    layer1_config: Layer1Config | None = None


_ENV_REGISTER = "REGISTER_FILE"
_ENV_P6 = "P6_FILE"
_ENV_STRAWMAN = "STRAWMAN_FILE"


def _resolve_path(cli_override: str | None, env_var: str) -> Path | None:
    if cli_override:
        return Path(cli_override)
    env_val = os.environ.get(env_var)
    if env_val:
        return Path(env_val)
    return None


def load_integrated_config(
    register_override: str | None = None,
    p6_override: str | None = None,
    strawman_override: str | None = None,
    seed_override: int | None = None,
) -> IntegratedConfig:
    """Resolve IntegratedConfig from CLI overrides > env vars > strawman defaults > fallback."""
    register_path = _resolve_path(register_override, _ENV_REGISTER)
    p6_path = _resolve_path(p6_override, _ENV_P6)
    strawman_path = _resolve_path(strawman_override, _ENV_STRAWMAN)

    missing = []
    if register_path is None:
        missing.append("register_path (CLI --register or env REGISTER_FILE)")
    if p6_path is None:
        missing.append("p6_path (CLI --p6 or env P6_FILE)")
    if strawman_path is None:
        missing.append("strawman_path (CLI --strawman or env STRAWMAN_FILE)")
    if missing:
        raise ValueError(
            f"Integrated config missing required paths: {', '.join(missing)}"
        )

    # DAYRATE-01: the strawman read is now a contract, not a best effort. A
    # workbook that is absent or will not parse stops the run rather than
    # being swallowed to {} and leaving four literals in force. day_rate has
    # no literal here at all - it is sourced or the run stops.
    cfg = read_run_config_strict(strawman_path, read_run_config)
    day_rate = resolve_day_rate(cfg, strawman_path)

    iterations = 100000
    reporting_p_level = 80
    if cfg.get("iterations"):
        iterations = int(cfg["iterations"])
    if cfg.get("p_level_reporting"):
        reporting_p_level = int(cfg["p_level_reporting"])
    # SP18b derivation, moved to the shared contract by DAYRATE-02 so the two
    # Stage 3 builders can use the same one instead of leaving it at 0.
    programme_days = resolve_programme_days(cfg)

    # SR19 §6.2: read MethodologyDefaults from the reference register (the register
    # workbook). Hard-fails with a structured MethodologyDefaultsError
    # per SR19-D1 if any expected named range is missing / mistyped /
    # the workbook is locked by Excel.
    methodology_defaults = read_methodology_defaults(
        register_path, caller_module="src/integrated/integrated_simulation.load_integrated_config",
    )

    return IntegratedConfig(
        register_path=register_path,
        **read_calibration_tolerances(
            register_path, caller_module="src/integrated/integrated_simulation.load_integrated_config"),
        p6_path=p6_path,
        strawman_path=strawman_path,
        methodology_defaults=methodology_defaults,
        iterations=iterations,
        random_seed=seed_override,
        day_rate=day_rate,
        reporting_p_level=reporting_p_level,
        programme_days=programme_days,
    )


# ----------------------------------------------------------------------------
# Schedule scope helpers
# ----------------------------------------------------------------------------

def _filter_dual_coded(risk_scope_df: pd.DataFrame) -> pd.DataFrame:
    if "time_impact" not in risk_scope_df.columns:
        return risk_scope_df.iloc[:0]
    mask = risk_scope_df["time_impact"].astype(str).str.strip().str.lower() == "yes"
    return risk_scope_df[mask].copy().reset_index(drop=True)


def _resolve_modes(
    risk_scope_df: pd.DataFrame,
    mode_overrides: dict[str, str] | None,
    *,
    mode_multipliers: Mapping[str, float],
) -> dict[str, dict[str, Any]]:
    """Returns {risk_id: {mode_multiplier, mode, opt_d, ml_d, pess_d}} for dual-coded risks."""
    out: dict[str, dict[str, Any]] = {}
    sub = _filter_dual_coded(risk_scope_df)
    for _, row in sub.iterrows():
        rid = str(row["risk_id"])
        strawman_mode = str(row.get("mode_aggregated") or "Parallel")
        applied_mode = (
            mode_overrides[rid] if mode_overrides and rid in mode_overrides
            else strawman_mode
        )
        out[rid] = {
            "mode_multiplier": resolve_mode_multiplier(applied_mode, mode_multipliers, rid),  # RS-D-3
            "mode": applied_mode,
            "opt_d": float(row.get("opt_days") or 0.0),
            "ml_d": float(row.get("ml_days") or 0.0),
            "pess_d": float(row.get("pess_days") or 0.0),
        }
    return out


# ----------------------------------------------------------------------------
# Main simulation loop
# ----------------------------------------------------------------------------
# _sample_cost_vec and _find_risk_index moved to src/qra_core.py (re-imported above).


def run_integrated_simulation(
    config: IntegratedConfig,
    risks: list[Any],
    risk_scope_df: pd.DataFrame,
    mode_overrides: dict[str, str] | None = None,
    *,
    precomputed_severity_uniforms: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    """Run N iterations of the integrated cost+schedule MC.

    Sequence:
      1. Build CG-correlated fire uniform matrix (build_risk_uniform_matrix).
      2. For each risk: vectorised draw of cost/schedule arrays. Dual-coded
         risks use ONE shared severity uniform per iteration (drives both
         cost dispatch and schedule PERT). Cost-only risks use independent
         severity uniforms.
      3. Apply chain1 and chain2 via apply_chain_logic (post-iteration).
      4. Aggregate totals.

    Parameters
    ----------
    precomputed_severity_uniforms : dict[str, np.ndarray] | None
        When provided, replaces the per-risk ``rng.random(n_iter)``
        severity uniform draw inside the loop with
        ``precomputed_severity_uniforms[risk_id]``. Keys are risk_ids
        matching ``[r.risk_id for r in risks]``; values are
        ``(n_iter,)`` ``U(0, 1)`` arrays. Used by the Stage 3 engine
        (:func:`src.integrated.integrated_simulation_stage3.run_integrated_simulation_stage3`)
        to share severity uniforms between the cost arm (this function)
        and the schedule arm (:func:`run_schedule_mc`) for joint sampling.
        Risks not present in the dict fall back to ``rng.random(n_iter)``.
        When ``None`` (default), behaviour is bit-identical to the
        pre-refactor implementation — Stage 2.5 production deliverable
        is unchanged. A shape mismatch raises a fail-fast
        :class:`ValueError`.
    """
    # QRAXL-01 scope A: this shell does ONLY RNG-free work (pandas mode
    # resolution + config-scalar extraction), then delegates the entire
    # RNG-consuming numeric run to qra_core.run_cost_layer. No generator is
    # created here and nothing consumes a draw before delegation, so the draw
    # order is preserved by construction (bit-identity, QRAXL-01.0 gate).
    dual_lookup = _resolve_modes(
        risk_scope_df, mode_overrides,
        mode_multipliers=config.methodology_defaults.mode_multipliers,  # RS-D-3b
    )
    seed = require_seed(config.random_seed,
                        where="src.integrated.integrated_simulation.run_integrated_simulation")

    # SP18c diagnostics are BINDING-AWARE and RNG-FREE, so they live in this
    # (pandas/binding-bound) shell rather than the Pyodide-clean core: the
    # legacy-hardcoded-chain-ID DeprecationWarning and the chain/cascade overlap
    # guard. Computed here and handed to run_cost_layer to echo in its result.
    # Being RNG-free, running them before run_cost_layer creates its generator
    # does not perturb the draw order.
    from src.integrated.cascade_integrated import (
        emit_legacy_chain_deprecation_warning,
        detect_chain_cascade_overlap,
    )
    legacy_ids_found = emit_legacy_chain_deprecation_warning(risks)
    overlap_warnings = detect_chain_cascade_overlap(
        risks=risks, edges=[],
        strict=bool(getattr(config, "strict_overlap_check", False)),
    )

    core = run_cost_layer(
        n_iter=int(config.iterations),
        risks=risks,
        cg_coefficients=config.methodology_defaults.cg_coefficients,
        dual_lookup=dual_lookup,
        chain_risk_ids=config.chain_risk_ids,
        chain_config=config.chain_config,
        seed=seed,
        precomputed_severity_uniforms=precomputed_severity_uniforms,
        cascade_enabled=(
            bool(getattr(config, "cascade_enabled", False))
            or bool(getattr(config.chain_config, "cascade_enabled", False))
        ),
        cascade_use_raw_days=bool(getattr(config, "cascade_use_raw_days", False)),
        cascade_audit_sample_cap=int(getattr(config, "cascade_audit_sample_cap", 100)),
        overlap_warnings=overlap_warnings,
        legacy_chain_ids_in_open_set=legacy_ids_found,
        # QRAXL-01 step 4: Layer-1 owner view. None (default) => OFF, byte-
        # identical to the L2-only baseline. Populated only for the owner /
        # whole-project view; the shared-pool view leaves it None.
        layer1=getattr(config, "layer1_config", None),
    )
    core["config"] = config
    return core


# ----------------------------------------------------------------------------
# Chain logic post-pass (resample-with-elevated-probability)
# ----------------------------------------------------------------------------
# apply_chain_logic / _apply_chain1_logic / _apply_chain2_logic / _resample_target
# were moved VERBATIM to src/qra_core.py (QRAXL-01 scope A) and are re-imported at
# the top of this module for backward-compatible callers.
