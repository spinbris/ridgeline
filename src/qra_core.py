"""QRAXL-01 shared cost-QRA core - the standalone, Pyodide-runnable cost sampler.

This module is the single home of the integrated engine's Layer-2 cost Monte
Carlo (the joint cost+schedule per-iteration sampler, chain resample logic, and
the cost-arm aggregation). It is extracted VERBATIM from
``src/integrated/integrated_simulation.py`` (scope A of the QRAXL-01 brief) so
that BOTH tiers run one implementation:

- Tier 2 (full engine): ``run_integrated_simulation`` resolves config + the
  pandas Risk_Scope into a plain ``dual_lookup`` dict, then delegates the numeric
  run to :func:`run_cost_layer` here.
- Tier 1 (xlwings Lite, Pyodide): imports this module directly.

IMPORT DISCIPLINE (non-negotiable - this must load under Pyodide): no pandas, no
openpyxl, no XER parsing, no file I/O, no ``IntegratedConfig`` (which drags the
Excel readers). Dependencies are numpy + scipy (via distributions/correlations),
the pure ``config`` dataclasses, and the clean ``cost_dispatcher`` / cascade
helpers. Everything config-shaped is passed in as plain scalars/dicts by the
caller.

BIT-IDENTITY: the numeric code below is a move, not a rewrite. The entire RNG
lifecycle (create rng -> fire_u -> per-risk severity -> chain resamples ->
cascade) lives inside :func:`run_cost_layer`, so the draw order is preserved by
construction. Locked by ``tests/test_qraxl01_0_bit_identity.py`` (QRAXL-01.0).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from src.config import ChainConfig
from src.correlations import build_risk_uniform_matrix
from src.rng_streams import fire_generator, require_seed
from src.distributions import pert_from_uniform
from src.integrated.cost_dispatcher import _get_attr
# Layer-1 factor model (QRAXL-01 step 4). Imported at top level (not function-
# local) ON PURPOSE: it is Pyodide-clean, so keeping it in qra_core's import
# closure means the standing cleanliness test proves the Layer-1 path is clean
# too - the brief's "cleanliness still passes with Layer 1 wired in" gate.
from src.layer1_factors import Layer1Config, run_layer1_base


# ----------------------------------------------------------------------------
# Vectorised cost sampler (per-risk batch over all iterations)
# ----------------------------------------------------------------------------

def _sample_cost_vec(
    u: np.ndarray, opt: float, ml: float, pess: float, distribution: str,
) -> np.ndarray:
    """Vectorised version of cost_dispatcher.sample_cost using src/distributions sample_cost."""
    from src.distributions import sample_cost as _vec_sample_cost
    return _vec_sample_cost(u, opt, ml, pess, distribution)


def _find_risk_index(risks: list[Any], risk_id: str) -> int | None:
    for i, r in enumerate(risks):
        if str(_get_attr(r, "risk_id")) == str(risk_id):
            return i
    return None


# ----------------------------------------------------------------------------
# Main cost-layer sampling loop (Tier-1/Tier-2 shared numeric core)
# ----------------------------------------------------------------------------

def draw_fire_matrix(
    n_iter: int,
    risks: list[Any],
    cg_coefficients: dict[str, float],
    rng: np.random.Generator,
) -> np.ndarray:
    """Whether each risk occurs, per iteration: ``(n_iter, n_risks)`` bool, columns in ``risks`` order.

    The one fire draw of a run (SPEC R-10, METHFIRE-01). A risk is one event with one
    probability, its register ``Probability``; the uniforms are correlated within each
    correlation group. :func:`run_cost_layer` consumes it as the first draw on its generator,
    and the Stage 3 schedule replay fires on the same decisions, so a dual-coded risk carries
    its cost and its delay together or neither. A route that cannot run the cost arm first
    reproduces this draw by calling it on ``src.rng_streams.fire_generator(seed)`` with the cost arm's
    own risks and coefficients.
    """
    fire_u = build_risk_uniform_matrix(n_iter, risks, cg_coefficients, rng)
    probabilities = np.array(
        [float(_get_attr(r, "probability") or 0.0) for r in risks], dtype=np.float64,
    )
    return fire_u < probabilities


def run_cost_layer(
    *,
    n_iter: int,
    risks: list[Any],
    cg_coefficients: dict[str, float],
    dual_lookup: dict[str, dict[str, Any]],
    chain_risk_ids: dict[str, Any],
    chain_config: ChainConfig,
    seed: int,
    precomputed_severity_uniforms: dict[str, np.ndarray] | None = None,
    cascade_enabled: bool = False,
    cascade_use_raw_days: bool = False,
    cascade_audit_sample_cap: int = 100,
    overlap_warnings: list[dict[str, Any]] | None = None,
    legacy_chain_ids_in_open_set: list[Any] | None = None,
    layer1: Layer1Config | None = None,
) -> dict[str, Any]:
    """Run N iterations of the integrated cost+schedule MC (numeric core).

    Pure data in, pure data out - no config object, no pandas, no file I/O.
    ``dual_lookup`` ({risk_id: {mode_multiplier, mode, opt_d, ml_d, pess_d}}) is
    resolved by the caller (Tier 2 from the Risk_Scope DataFrame; Tier 1 from the
    workbook). The returned dict carries every numeric key the engine shell needs;
    the shell adds ``config`` back before returning to its own callers.

    Sequence:
      1. Build CG-correlated fire uniform matrix (build_risk_uniform_matrix).
      2. For each risk: vectorised draw of cost/schedule arrays. Dual-coded
         risks use ONE shared severity uniform per iteration (drives both cost
         dispatch and schedule PERT). Cost-only risks use independent uniforms.
      3. Apply chain1 and chain2 via apply_chain_logic (post-iteration).
      4. Aggregate totals.

    ``precomputed_severity_uniforms`` (keys = risk_ids, values = ``(n_iter,)``
    U(0,1)) replaces the per-risk ``rng.random(n_iter)`` severity draw - used by
    the Stage 3 binding to share uniforms between the cost arm and schedule arm.
    Risks absent from the dict fall back to ``rng.random(n_iter)``. A shape
    mismatch raises a fail-fast ``ValueError``.
    """
    n_risks = len(risks)
    # Refused, not truncated: int(42.9) ran seed 42 (SEEDINPUT-01, SEEDZERO-01 D3).
    seed_used = require_seed(seed, where="src.qra_core.run_cost_layer")
    # The run seed's own stream (src.rng_streams, RNGSTREAM-01): the fire draw first.
    rng = fire_generator(seed_used)

    risk_ids_all = [str(_get_attr(r, "risk_id")) for r in risks]
    risk_ids_dual = sorted(dual_lookup.keys())
    dual_index = {rid: idx for idx, rid in enumerate(risk_ids_all)}

    # SP18c diagnostics (the legacy-hardcoded-chain-ID DeprecationWarning and the
    # chain/cascade overlap guard) are BINDING-AWARE and RNG-FREE. They are
    # computed by the caller - the Tier-2 shell, which has the active project
    # binding - and passed in. Keeping them OUT of the core is what lets qra_core
    # import under Pyodide (Tier 1 has no binding). Their result-dict keys are
    # echoed below; both default to empty for a pure standalone/Tier-1 run.
    legacy_ids_found = list(legacy_chain_ids_in_open_set or [])
    overlap_warnings = list(overlap_warnings) if overlap_warnings else []

    # SR19 §6.3 step 7: CG coefficients come from methodology_defaults (resolved
    # by the caller and passed in as cg_coefficients).
    fire_matrix = draw_fire_matrix(n_iter, risks, cg_coefficients, rng)

    per_risk_cost = np.zeros((n_iter, n_risks), dtype=np.float64)
    per_risk_sched = np.zeros((n_iter, len(risk_ids_dual)), dtype=np.float64)
    per_risk_sched_pre_mode = np.zeros((n_iter, len(risk_ids_dual)), dtype=np.float64)
    fired_array = np.zeros((n_iter, n_risks), dtype=bool)

    dual_col_index = {rid: i for i, rid in enumerate(risk_ids_dual)}

    for i, risk in enumerate(risks):
        rid = risk_ids_all[i]
        opt_c = float(_get_attr(risk, "opt_cost") or 0.0)
        ml_c = float(_get_attr(risk, "ml_cost") or 0.0)
        pess_c = float(_get_attr(risk, "pess_cost") or 0.0)
        dist = str(_get_attr(risk, "distribution") or "PERT")

        fired = fire_matrix[:, i]
        fired_array[:, i] = fired

        if (
            precomputed_severity_uniforms is not None
            and rid in precomputed_severity_uniforms
        ):
            u_severity = precomputed_severity_uniforms[rid]
            if u_severity.shape != (n_iter,):
                raise ValueError(
                    f"precomputed_severity_uniforms[{rid!r}] shape "
                    f"{u_severity.shape} != expected ({n_iter},)"
                )
        else:
            u_severity = rng.random(n_iter)
        cost_draws = _sample_cost_vec(u_severity, opt_c, ml_c, pess_c, dist)
        per_risk_cost[:, i] = np.where(fired, cost_draws, 0.0)

        if rid in dual_lookup:
            d = dual_lookup[rid]
            sched_pre_full = pert_from_uniform(
                u_severity, d["opt_d"], d["ml_d"], d["pess_d"],
            )
            sched_pre = np.where(fired, sched_pre_full, 0.0)
            sched = sched_pre * d["mode_multiplier"]
            j = dual_col_index[rid]
            per_risk_sched_pre_mode[:, j] = sched_pre
            per_risk_sched[:, j] = sched

    iteration_results = {
        "per_risk_cost_array": per_risk_cost,
        "per_risk_schedule_array": per_risk_sched,
        "per_risk_schedule_pre_mode_array": per_risk_sched_pre_mode,
        "fired_array": fired_array,
        "risk_ids_all": risk_ids_all,
        "risk_ids_dual": risk_ids_dual,
        "dual_lookup": dual_lookup,
    }

    chain_outcome = apply_chain_logic(
        iteration_results,
        risks=risks,
        chain_risk_ids=chain_risk_ids,
        chain_config=chain_config,
        rng=rng,
        dual_lookup=dual_lookup,
    )
    iteration_results.update(chain_outcome)

    # SP18c — temporal cascade activation. cascade_enabled defaults False;
    # cascade-off path is byte-identical to the pre-sp18c-baseline. Cascade
    # is the THIRD chain layer (additive over static chains _apply_chain1/2
    # and the workbook chains; expresses temporal slip-driven amplification
    # rather than constant edge effects). See SP18c brief §1.
    cascade_audit: list[dict[str, Any]] = []
    cascade_group_membership: dict[str, list[int]] = {}
    cascade_n_groups = 0
    if cascade_enabled:
        # cascade_integrated is import-clean (numpy/_cascade_kernel); imported
        # here (only when cascade is active) so the default cost-only Tier-1 path
        # never even touches it.
        from src.integrated.cascade_integrated import apply_cascade_groups_integrated
        # Build per-risk severity uniforms dict used by the joint sampler so
        # cascade resamples honour the same shared uniforms for dual-coded
        # risks (preserves cost/schedule correlation under cascade resample).
        cascade_severity = (
            dict(precomputed_severity_uniforms)
            if precomputed_severity_uniforms is not None
            else None
        )
        cascade_result = apply_cascade_groups_integrated(
            ev_costs=iteration_results["per_risk_cost_array"],
            ev_days=iteration_results["per_risk_schedule_array"],
            risks=risks,
            risk_ids_dual=risk_ids_dual,
            dual_lookup=dual_lookup,
            chain_config=chain_config,
            rng=rng,
            severity_uniforms=cascade_severity,
            use_raw_days=bool(cascade_use_raw_days),
            audit_sample_cap=int(cascade_audit_sample_cap),
        )
        # Kernel modifies in place — but reassign for clarity.
        iteration_results["per_risk_cost_array"] = cascade_result.ev_costs
        if cascade_result.ev_days is not None:
            iteration_results["per_risk_schedule_array"] = cascade_result.ev_days
        cascade_audit = cascade_result.audit
        cascade_group_membership = cascade_result.group_membership
        cascade_n_groups = cascade_result.n_groups

    # QRAXL-01 step 4 - Layer-1 factor composition (owner view). OFF by default
    # (layer1 is None): the block is skipped entirely, draws ZERO rng, and the
    # cost total below is byte-identical to the Layer-2-only baseline (the
    # OFF-reproduces-QRAXL-01.0 gate). ON: the systemic base contribution is
    # sampled from the SAME rng AFTER the chain/cascade draws (single pass, one
    # generator) and added per-iteration to the Layer-2 event total - never two
    # models with P-values added. Draw order is fixed for seed reproducibility.
    layer1_result = None
    layer1_base = None
    if layer1 is not None:
        layer1_result = run_layer1_base(n_iter, layer1, rng)
        layer1_base = layer1_result["base_array"]

    cost_total = iteration_results["per_risk_cost_array"].sum(axis=1)
    if layer1_base is not None:
        cost_total = cost_total + layer1_base
    schedule_total = iteration_results["per_risk_schedule_array"].sum(axis=1)

    # SP18b — surface (n_iter, n_risks, 2) timed_events for the per-day P-curve.
    # occurrence_day comes from each risk's planned_day attribute; cost is the
    # post-chain per-iteration cost. Same shape regardless of timeshift mode
    # (SP18c will assign occurrence_day from the shifted-day arrays).
    planned_days = np.array(
        [int(_get_attr(r, "planned_day") or 0) for r in risks],
        dtype=np.int64,
    )
    timed_events = np.empty(
        (n_iter, n_risks, 2), dtype=np.float64,
    )
    timed_events[:, :, 0] = planned_days  # broadcast across iterations
    timed_events[:, :, 1] = iteration_results["per_risk_cost_array"]

    return {
        "iterations": n_iter,
        "cost_dollars_array": cost_total,
        "schedule_days_array": schedule_total,
        "per_risk_cost_array": iteration_results["per_risk_cost_array"],
        "per_risk_schedule_array": iteration_results["per_risk_schedule_array"],
        "per_risk_schedule_pre_mode_array": iteration_results[
            "per_risk_schedule_pre_mode_array"
        ],
        "fired_array": iteration_results["fired_array"],
        "risk_ids_all": risk_ids_all,
        "risk_ids_dual": risk_ids_dual,
        "chain1_active_iterations": int(iteration_results.get("chain1_active_iterations", 0)),
        "chain2_active_iterations": int(iteration_results.get("chain2_active_iterations", 0)),
        "chain_skipped_reasons": iteration_results.get("chain_skipped_reasons", {}),
        "timed_events": timed_events,  # SP18b — (n_iter, n_risks, 2)
        # SP18c — cascade activation provenance
        "cascade_enabled": bool(cascade_enabled),
        "cascade_use_raw_days": bool(cascade_use_raw_days),
        "cascade_audit": cascade_audit,
        "cascade_group_membership": cascade_group_membership,
        "cascade_n_groups": cascade_n_groups,
        "overlap_warnings": overlap_warnings,
        "legacy_chain_ids_in_open_set": legacy_ids_found,
        "seed_used": seed_used,
        # QRAXL-01 step 4 - Layer-1 provenance (all None/False when OFF, so the
        # baseline path is byte-identical; timed_events stays Layer-2-only - the
        # systemic base has no occurrence_day).
        "layer1_enabled": layer1 is not None,
        "layer1_base_array": layer1_base,
        "layer1_corr_diag": (layer1_result["corr_diag"] if layer1_result else None),
        "layer1_corr_mode": (layer1_result["corr_mode"] if layer1_result else None),
        "layer1_factor_mean_mult": (
            layer1_result["factor_mean_mult"] if layer1_result else None
        ),
    }


# ----------------------------------------------------------------------------
# Chain logic post-pass (resample-with-elevated-probability)
# ----------------------------------------------------------------------------

def apply_chain_logic(
    iteration_results: dict[str, Any],
    risks: list[Any],
    chain_risk_ids: dict[str, Any],
    chain_config: ChainConfig,
    rng: np.random.Generator,
    dual_lookup: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply chain1 and chain2 RESAMPLE-with-elevated-probability post-iteration.

    Reference implementation: ``MonteCarloEngine._apply_chain1`` and ``._apply_chain2``
    in src/simulation.py. Algorithm replicated here as a free function (cost
    engine methods are instance-bound and cannot be called without instantiating
    the class). All parameters (chain_risk_ids, chain_config) are supplied by the
    caller from src/defaults.py and src/config.py - never redefined or hardcoded.

    Mechanism (NOT multiplicative):
      For each chain:
        1. Identify trigger risk and target(s) by risk ID. If any are absent,
           skip the chain (early-return None pattern).
        2. Compute trigger duration proxy from |trigger_cost| / max(|trigger_pess|, 1).
        3. chain_mask = (trigger fired) AND (proxy >= threshold)
        4. For iterations in chain_mask: RESAMPLE the target risk(s) with
           elevated_prob = min(target_prob * c1_amplification, 0.95) using
           FRESH INDEPENDENT uniforms for fire and magnitude.
        5. When the resampled target is dual-coded, the resample uses a single
           fresh shared uniform for cost AND schedule magnitude (preserving the
           joint-sampling property for chain-resampled iterations).

    NOTE: where the binding's legacy chain trigger/target IDs do not
    exist in the V9 Open set. _find_risk_index returns None for all of them.
    Both chains skip cleanly. iteration_results passes through unchanged.
    chain1_active_iterations and chain2_active_iterations both 0.
    """
    if dual_lookup is None:
        dual_lookup = {}

    per_risk_cost = iteration_results["per_risk_cost_array"]
    per_risk_sched = iteration_results["per_risk_schedule_array"]
    per_risk_sched_pre_mode = iteration_results["per_risk_schedule_pre_mode_array"]
    fired = iteration_results["fired_array"]
    risk_ids_all = iteration_results["risk_ids_all"]
    risk_ids_dual = iteration_results["risk_ids_dual"]

    dual_col_index = {rid: i for i, rid in enumerate(risk_ids_dual)}
    skipped: dict[str, str] = {}

    # ---- chain1 ----
    chain1_count = _apply_chain1_logic(
        per_risk_cost=per_risk_cost,
        per_risk_sched=per_risk_sched,
        per_risk_sched_pre_mode=per_risk_sched_pre_mode,
        fired=fired,
        risks=risks,
        risk_ids_all=risk_ids_all,
        chain_risk_ids=chain_risk_ids,
        chain_config=chain_config,
        rng=rng,
        dual_lookup=dual_lookup,
        dual_col_index=dual_col_index,
        skipped=skipped,
    )

    # ---- chain2 ----
    chain2_count = _apply_chain2_logic(
        per_risk_cost=per_risk_cost,
        per_risk_sched=per_risk_sched,
        per_risk_sched_pre_mode=per_risk_sched_pre_mode,
        fired=fired,
        risks=risks,
        risk_ids_all=risk_ids_all,
        chain_risk_ids=chain_risk_ids,
        chain_config=chain_config,
        rng=rng,
        dual_lookup=dual_lookup,
        dual_col_index=dual_col_index,
        skipped=skipped,
    )

    return {
        "per_risk_cost_array": per_risk_cost,
        "per_risk_schedule_array": per_risk_sched,
        "per_risk_schedule_pre_mode_array": per_risk_sched_pre_mode,
        "fired_array": fired,
        "chain1_active_iterations": int(chain1_count),
        "chain2_active_iterations": int(chain2_count),
        "chain_skipped_reasons": skipped,
    }


def _apply_chain1_logic(
    *,
    per_risk_cost: np.ndarray,
    per_risk_sched: np.ndarray,
    per_risk_sched_pre_mode: np.ndarray,
    fired: np.ndarray,
    risks: list[Any],
    risk_ids_all: list[str],
    chain_risk_ids: dict[str, Any],
    chain_config: ChainConfig,
    rng: np.random.Generator,
    dual_lookup: dict[str, dict[str, Any]],
    dual_col_index: dict[str, int],
    skipped: dict[str, str],
) -> int:
    trig_id = chain_risk_ids.get("c1_trigger")
    targ_id = chain_risk_ids.get("c1_target")
    idx_trig = _find_risk_index(risks, trig_id) if trig_id else None
    idx_targ = _find_risk_index(risks, targ_id) if targ_id else None
    if idx_trig is None or idx_targ is None:
        skipped["chain1"] = (
            f"trigger {trig_id!r} idx={idx_trig}, target {targ_id!r} idx={idx_targ} - "
            f"one or both absent in V8 Open set"
        )
        return 0
    return _resample_target(
        chain_label="chain1",
        idx_trig=idx_trig,
        target_ids=[targ_id],
        elevated_factor=chain_config.c1_amplification,
        proxy_scale=8.0,
        proxy_threshold=chain_config.c1_trigger_months,
        risks=risks,
        per_risk_cost=per_risk_cost,
        per_risk_sched=per_risk_sched,
        per_risk_sched_pre_mode=per_risk_sched_pre_mode,
        fired=fired,
        risk_ids_all=risk_ids_all,
        rng=rng,
        dual_lookup=dual_lookup,
        dual_col_index=dual_col_index,
        skipped=skipped,
    )


def _apply_chain2_logic(
    *,
    per_risk_cost: np.ndarray,
    per_risk_sched: np.ndarray,
    per_risk_sched_pre_mode: np.ndarray,
    fired: np.ndarray,
    risks: list[Any],
    risk_ids_all: list[str],
    chain_risk_ids: dict[str, Any],
    chain_config: ChainConfig,
    rng: np.random.Generator,
    dual_lookup: dict[str, dict[str, Any]],
    dual_col_index: dict[str, int],
    skipped: dict[str, str],
) -> int:
    trig_id = chain_risk_ids.get("c2_trigger")
    targ_ids = chain_risk_ids.get("c2_targets") or []
    idx_trig = _find_risk_index(risks, trig_id) if trig_id else None
    if idx_trig is None:
        skipped["chain2"] = (
            f"trigger {trig_id!r} absent in V8 Open set"
        )
        return 0
    return _resample_target(
        chain_label="chain2",
        idx_trig=idx_trig,
        target_ids=list(targ_ids),
        elevated_factor=chain_config.c2_cascade_factor,
        proxy_scale=4.0,
        proxy_threshold=chain_config.c2_trigger_weeks,
        risks=risks,
        per_risk_cost=per_risk_cost,
        per_risk_sched=per_risk_sched,
        per_risk_sched_pre_mode=per_risk_sched_pre_mode,
        fired=fired,
        risk_ids_all=risk_ids_all,
        rng=rng,
        dual_lookup=dual_lookup,
        dual_col_index=dual_col_index,
        skipped=skipped,
    )


def _resample_target(
    *,
    chain_label: str,
    idx_trig: int,
    target_ids: list[str],
    elevated_factor: float,
    proxy_scale: float,
    proxy_threshold: float,
    risks: list[Any],
    per_risk_cost: np.ndarray,
    per_risk_sched: np.ndarray,
    per_risk_sched_pre_mode: np.ndarray,
    fired: np.ndarray,
    risk_ids_all: list[str],
    rng: np.random.Generator,
    dual_lookup: dict[str, dict[str, Any]],
    dual_col_index: dict[str, int],
    skipped: dict[str, str],
) -> int:
    """Common resample routine used by chain1 and chain2.

    Algorithm follows MonteCarloEngine._apply_chain1 / _apply_chain2 exactly.
    """
    trigger_risk = risks[idx_trig]
    pess_trig = float(_get_attr(trigger_risk, "pess_cost") or 0.0)
    max_pess = max(abs(pess_trig), 1.0)
    proxy = (np.abs(per_risk_cost[:, idx_trig]) / max_pess) * proxy_scale
    chain_mask = (per_risk_cost[:, idx_trig] != 0) & (proxy >= proxy_threshold)
    n_chain = int(np.sum(chain_mask))
    if n_chain == 0:
        return 0

    for targ_id in target_ids:
        idx_targ = _find_risk_index(risks, targ_id)
        if idx_targ is None:
            skipped[f"{chain_label}_target_{targ_id}"] = (
                f"target {targ_id!r} absent in Open set"
            )
            continue
        target_risk = risks[idx_targ]
        target_prob = float(_get_attr(target_risk, "probability") or 0.0)
        elevated_prob = min(target_prob * elevated_factor, 0.95)

        u_fire_new = rng.random(n_chain)
        new_fire = u_fire_new < elevated_prob
        u_mag_new = rng.random(n_chain)

        opt_c = float(_get_attr(target_risk, "opt_cost") or 0.0)
        ml_c = float(_get_attr(target_risk, "ml_cost") or 0.0)
        pess_c = float(_get_attr(target_risk, "pess_cost") or 0.0)
        dist = str(_get_attr(target_risk, "distribution") or "PERT")
        new_cost = _sample_cost_vec(u_mag_new, opt_c, ml_c, pess_c, dist) * new_fire

        per_risk_cost[chain_mask, idx_targ] = new_cost
        fired_chain = np.where(chain_mask)[0]
        fired[fired_chain, idx_targ] = new_fire

        if targ_id in dual_lookup:
            d = dual_lookup[targ_id]
            sched_pre_new = pert_from_uniform(
                u_mag_new, d["opt_d"], d["ml_d"], d["pess_d"],
            ) * new_fire
            sched_new = sched_pre_new * d["mode_multiplier"]
            j = dual_col_index[targ_id]
            per_risk_sched_pre_mode[chain_mask, j] = sched_pre_new
            per_risk_sched[chain_mask, j] = sched_new

    return n_chain
