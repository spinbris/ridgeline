"""SR9 cross-validation: reconciles three engine runs.

Hard gate: the SR9 deliverable does not ship if any of the four checks fails.

Four checks:
  1. Cost marginal: cost-only L2 mean ~= integrated cost marginal
     (within IntegratedConfig tolerances: $50k absolute OR 0.1% relative,
     where the absolute clause is iteration-aware-scaled per SR9-v3.6)
  2. Schedule marginal: SR5 mean ~= integrated schedule marginal
     (within 1 day absolute, iteration-aware-scaled per SR9-v3.6)
  3. Top-3 cost contributors consistent across cost-only and integrated runs
  4. Top-3 schedule contributors consistent across SR5 and integrated runs,
     under the register's own Mode classification — the same basis as
     checks 1-3 (3c Part A, Director 04/09/2026; it previously ranked a
     second "Dummy Realistic" Mode scenario, which was a no-op for every
     project but the reference one, making the check unfailable there. The
     two ``*_dummy_realistic`` arguments are still accepted and no longer
     consulted for this check.)

Reuses src/integrated/integrated_analysis.compute_marginal_calibration for
the first two checks (and inherits its dict keys: cost_passes_calibration,
schedule_passes_calibration). Top-3 contributor consistency is new logic
in this module.

SR9-v3.6 — iteration-aware tolerance scaling
--------------------------------------------
Absolute calibration tolerances scale by sqrt(canonical_iter / actual_iter)
so the gate enforces the same statistical confidence at any iteration count.
At canonical 100,000 iterations the scaling factor is 1.0 and production
behaviour is preserved. At lower iteration counts the absolute tolerance
widens to accommodate Monte Carlo sampling variance: SEM of the difference
between two independent-RNG means scales as 1/sqrt(N), so tolerance must
scale the same way to maintain a fixed false-positive rate. The scaling is
capped at TOLERANCE_SCALING_CAP (5.0x) so absurdly low iteration counts do
not get a free pass. The relative-clause (0.1%) is left unscaled. See
METHODOLOGY.md §6.4 and the SR9 v3.6 cross-validation diagnostic,
§11, for the rationale and
diagnostic data.
"""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from src.final._pre_flight import assert_strawman_unlocked
from src.integrated.integrated_analysis import compute_marginal_calibration
from src.integrated.integrated_simulation import IntegratedConfig


logger = logging.getLogger(__name__)


# SR9-v3.6: iteration-aware tolerance scaling
CANONICAL_ITERATIONS = 100_000
TOLERANCE_SCALING_CAP = 5.0


def compute_iteration_scaling_factor(
    n_iter: int,
    canonical_iter: int = CANONICAL_ITERATIONS,
    cap: float = TOLERANCE_SCALING_CAP,
) -> float:
    """Return the absolute-tolerance scaling factor for ``n_iter`` iterations.

    Factor = min(sqrt(canonical_iter / n_iter), cap). At n_iter = canonical_iter
    the factor is 1.0 (production behaviour preserved). At lower iteration
    counts the factor widens by sqrt(canonical / actual) to absorb Monte Carlo
    sampling noise. The cap prevents unbounded loosening at very low iter.
    """
    if n_iter <= 0:
        return float(cap)
    raw = math.sqrt(float(canonical_iter) / float(n_iter))
    return float(min(raw, cap))


# ----------------------------------------------------------------------------
# Top-N ranking helpers
# ----------------------------------------------------------------------------

def _rank_by_p_level(
    per_risk_array: np.ndarray,
    risk_ids: list[str],
    p_level: int,
    top_n: int,
) -> list[str]:
    """Return risk_ids sorted by P-level value of their per-risk array column.

    per_risk_array : (n_iter, n_risks) ndarray
    risk_ids       : list[str] of length n_risks (column order matches array)
    Returns the top_n risk_ids in descending order of their P-level percentile.
    """
    if per_risk_array.size == 0 or len(risk_ids) == 0:
        return []
    n_risks = per_risk_array.shape[1]
    if n_risks != len(risk_ids):
        raise ValueError(
            f"per_risk_array column count ({n_risks}) does not match "
            f"risk_ids length ({len(risk_ids)})"
        )
    p_values = np.percentile(per_risk_array, p_level, axis=0)
    order = np.argsort(p_values)[::-1]
    top_idx = order[:top_n].tolist()
    return [risk_ids[i] for i in top_idx]


def _rank_by_mean(
    per_risk_array: np.ndarray,
    risk_ids: list[str],
    top_n: int,
) -> list[str]:
    """Return risk_ids sorted by the mean of their per-risk array column.

    Beta-19b item 6: schedule top-3 contributors now rank by probability-
    weighted mean impact (i.e. the iteration-mean of the contribution
    array == probability × mean impact when fired × Mode multiplier) to
    match the §10.4 schedule-drivers table. The cross-validation gate's
    "same risks appear in top-3 on standalone and integrated" criterion
    is metric-agnostic and continues to function under the new metric.
    """
    if per_risk_array.size == 0 or len(risk_ids) == 0:
        return []
    n_risks = per_risk_array.shape[1]
    if n_risks != len(risk_ids):
        raise ValueError(
            f"per_risk_array column count ({n_risks}) does not match "
            f"risk_ids length ({len(risk_ids)})"
        )
    means = per_risk_array.mean(axis=0)
    order = np.argsort(means)[::-1]
    top_idx = order[:top_n].tolist()
    return [risk_ids[i] for i in top_idx]


def _means_by_id(per_risk_array: np.ndarray, risk_ids: list[str]) -> dict[str, float]:
    """Each risk's iteration-mean contribution, keyed by id - the ranking's own basis."""
    per_risk_array = np.asarray(per_risk_array)
    if per_risk_array.size == 0 or not risk_ids:
        return {}
    means = per_risk_array.mean(axis=0)
    return {rid: float(means[i]) for i, rid in enumerate(risk_ids)}


def _top_ranks_consistent(
    top_a: list[str], top_b: list[str],
    means_a: dict[str, float], means_b: dict[str, float],
    tie_band: float,
) -> tuple[bool, str]:
    """Stage 4 F-30 (08/09/2026): the same risks in the same order, except where the two arms'
    members at a position are within-noise ties in both arms.

    Before this the check was ``list == list`` with no tie rule. On the Kestrel Highway register
    two schedule risks tie exactly on the register basis (7.35 days each); each arm broke the tie
    by its own sampled means and a register that was internally consistent was stamped DO NOT
    DISTRIBUTE. The Director ruled a within-noise tie consistent, at a band the REGISTER carries
    (``Schedule_Top3_Tie_Tolerance_Pct``, scaled for iteration count like the other tolerances),
    never a constant. Order still counts beyond the band: a reversed ranking of clearly different
    risks is the disagreement this check exists to catch (test_3c_a_check4), and a rule that
    compared bare sets would hide it. So at each rank position the two arms' members must be the
    same risk, or a pair whose means lie within ``tie_band`` of each other in BOTH arms.

    Returns (consistent, note); the note names every position that differs and its ratios.
    """
    if top_a == top_b:
        return True, ""
    notes: list[str] = []
    ok = True

    def near(x: str, y: str, means: dict[str, float]) -> tuple[bool, float | None]:
        mx, my = means.get(x), means.get(y)
        if mx is None or my is None:
            return False, None
        hi = max(mx, my)
        if hi <= 0.0:
            return mx == my, 1.0
        ratio = min(mx, my) / hi
        return ratio >= 1.0 - tie_band, ratio

    for k, (x, y) in enumerate(zip(top_a, top_b), start=1):
        if x == y:
            continue
        ok_a, r_a = near(x, y, means_a)
        ok_b, r_b = near(x, y, means_b)
        fmt = lambda r: "n/a" if r is None else f"{r:.4f}"
        if ok_a and ok_b:
            notes.append(f"rank {k}: {x} vs {y} tie within the band (SR5 {fmt(r_a)}, integrated {fmt(r_b)})")
        else:
            ok = False
            notes.append(f"rank {k}: {x} vs {y} differ beyond the band (SR5 {fmt(r_a)}, integrated {fmt(r_b)})")
    if len(top_a) != len(top_b):
        ok = False
        notes.append(f"the arms rank {len(top_a)} and {len(top_b)} contributors")
    return ok, "; ".join(notes)


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def cross_validate_reports(
    cost_results: dict[str, Any],
    schedule_results: dict[str, Any],
    integrated_results: dict[str, Any],
    strawman_path: Path | str,
    config: IntegratedConfig | None = None,
    integrated_results_dummy_realistic: dict[str, Any] | None = None,
    schedule_results_dummy_realistic: dict[str, Any] | None = None,
    p_level: int = 80,
    top_n: int = 3,
    stage3_results: dict[str, Any] | None = None,
    cross_surface: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cross-validate the three engine runs.

    STAGE3HEADLINE-01 (Director D-3, D-4; F-42), 10/09/2026. Two optional inputs move the
    schedule side of the gate onto Stage 3, the engine that produces the headline:

    ``stage3_results``
        The Stage 3 result in the integrated-results shape (``per_risk_schedule_array``,
        ``risk_ids_dual``, ``schedule_days_array``). When given, check 4 ranks the SR5
        contributors against Stage 3's, not Stage 2.5's.
    ``cross_surface``
        ``{"deliverable_delay_days", "period_delay_days", "p_level", "n_iter", "seed",
        "tolerance_days", "tolerance_pct"}``: the deliverable's Stage 3 delay at the
        register's reporting P-level (``p_level``, not necessarily 80) and the
        app's period engine's, on the same register, .xer, seed and iteration count. When
        given, check 2 is this comparison - it replaces the SR5-against-Stage-2.5 check,
        which compared two copies of one additive formula and could not fail (F-42).
        Coverage stated on its face (P4): both sides share the CPM kernel, so this limb
        catches divergence in how the two surfaces assemble a Stage 3 run - drivers,
        pinning, configuration - and not a defect inside the kernel itself.

    Without them the gate runs exactly as before, and its interpretation says which basis
    each limb used.

    Parameters
    ----------
    cost_results : dict
        From the cost engine MonteCarloEngine, materialised by the notebook
        as a dict with the following keys:
          - "cost_dollars_array"  : (n_iter,) ndarray of total cost per iter
                                     (== ev_costs.sum(axis=1) at L2-only view)
          - "per_risk_cost_array" : (n_iter, n_risks) ndarray (== ev_costs)
          - "risk_ids"            : list[str] of length n_risks
        The cost-only standalone L2-only run. Used for both calibration mean
        comparison and top-3 cost contributor ranking.

    schedule_results : dict
        From src.sra.sra_simulation.run_schedule_simulation under DP Review.
        Required keys:
          - "finish_delay_days_array" : (n_iter,) ndarray
          - "contribution_array"      : (n_iter, n_risks) ndarray (post-mode)
          - "risk_ids"                : list[str]
        Used for schedule calibration (DP Review baseline).

    integrated_results : dict
        From src.integrated.integrated_simulation.run_integrated_simulation
        under DP Review baseline. Required keys:
          - "cost_dollars_array"        : (n_iter,) ndarray
          - "schedule_days_array"       : (n_iter,) ndarray
          - "per_risk_cost_array"       : (n_iter, n_risks_all) ndarray
          - "per_risk_schedule_array"   : (n_iter, n_risks_dual) ndarray
          - "risk_ids_all"              : list[str]
          - "risk_ids_dual"             : list[str]
        Used for both calibration mean comparison and top-3 cost contributor
        ranking (DP Review basis for cost; schedule top-3 takes Dummy Realistic
        run instead, see optional argument below).

    strawman_path : Path or str
        Used for the lock-file pre-flight check.

    config : IntegratedConfig or None
        If None, a default IntegratedConfig is constructed for tolerance lookup.
        Tolerances inherited: cost <= $50k OR 0.1%, schedule <= 1 day.

    integrated_results_dummy_realistic : dict or None
        **No longer consulted for check 4** (3c Part A): the check ranks the
        baseline arms above. Still accepted so existing callers do not break.
        Optional. Integrated run under Dummy Realistic Mode override. When
        provided alongside schedule_results_dummy_realistic, the schedule
        top-3 contributor consistency check uses these arrays. Per the
        Director scope decision, schedule drivers are reported under Dummy
        Realistic because a near-all-Parallel DP Review baseline can leave a
        single risk contributing meaningfully. If None, the schedule top-3 check is skipped (returns
        consistent=False with a note in interpretation).

    schedule_results_dummy_realistic : dict or None
        Optional. SR5 schedule run under Dummy Realistic Mode override.

    p_level : int
        Percentile used for top-N ranking. Default 80 (matches reporting P-level).

    top_n : int
        Number of top contributors to compare. Default 3.

    Returns
    -------
    dict with keys:
      - cost_passes_calibration              : bool
      - cost_integrated_mean                 : float
      - cost_standalone_l2only_mean          : float
      - cost_absolute_gap_dollars            : float
      - cost_relative_gap_pct                : float
      - schedule_passes_calibration          : bool
      - schedule_integrated_mean_days        : float
      - schedule_standalone_mean_days        : float
      - schedule_absolute_gap_days           : float
      - top_3_cost_contributors_consistent   : bool
      - top_3_cost_contributors_cost_only    : list[str]
      - top_3_cost_contributors_integrated   : list[str]
      - top_3_schedule_contributors_consistent : bool
      - top_3_schedule_contributors_sr5      : list[str]
      - top_3_schedule_contributors_integrated : list[str]
      - schedule_top3_tie_tolerance_pct_base / _effective : float (F-30: the register's tie
        band and its iteration-scaled value; the interpretation names any within-band swap)
      - all_pass                             : bool
      - interpretation                       : str (human-readable summary)

    Raises
    ------
    RuntimeError
        If the strawman workbook lock file is present.
    ValueError
        If required dict keys are missing or array shapes are inconsistent.
    """
    assert_strawman_unlocked(strawman_path)

    if config is None:
        # SR19 §6.2: methodology_defaults is REQUIRED on IntegratedConfig.
        # cross_validate_reports does not actually read methodology_defaults,
        # but the dataclass-required field still needs a value. Use the
        # build_test_methodology_defaults factory with lock-preserve values
        # rather than read from disk (the register_path here is the
        # strawman_path placeholder anyway, not a real register).
        from src.sra.methodology_defaults_reader import (
            build_test_methodology_defaults,
            read_calibration_tolerances,
        )
        config = IntegratedConfig(
            register_path=Path(strawman_path),  # not read here
            # RS-D-2: the tolerances ARE read here (they gate the cross-check), so this
            # fallback takes them from the workbook it was handed. In the product's
            # consolidated model the register IS that workbook (REG-01 s3); a legacy
            # strawman carries no settings grid and refuses by name, and the caller
            # passes a config built from the register instead.
            **read_calibration_tolerances(Path(strawman_path), caller_module="src/final/cross_validator.py"),
            p6_path=Path(strawman_path),
            strawman_path=Path(strawman_path),
            methodology_defaults=build_test_methodology_defaults(),
        )

    # SR9-v3.6: derive iteration count from the integrated cost array (the
    # actual run shape, not config.iterations which may differ from a smoke
    # override) and scale the absolute tolerances by sqrt(canonical/actual).
    n_iter_used = int(np.asarray(integrated_results["cost_dollars_array"]).shape[0])
    scaling_factor = compute_iteration_scaling_factor(n_iter_used)
    cost_tol_dollars_base = float(config.cost_calibration_tolerance_dollars)
    sched_tol_days_base = float(config.schedule_calibration_tolerance_days)
    cost_tol_dollars_effective = cost_tol_dollars_base * scaling_factor
    sched_tol_days_effective = sched_tol_days_base * scaling_factor

    scaled_config = replace(
        config,
        cost_calibration_tolerance_dollars=cost_tol_dollars_effective,
        schedule_calibration_tolerance_days=sched_tol_days_effective,
    )

    # --- Calibration (reuse SR8 logic; scaled tolerances) ----------------
    standalone_cost_for_calib = {
        "cost_dollars_array": cost_results["cost_dollars_array"],
    }
    calibration = compute_marginal_calibration(
        integrated_results=integrated_results,
        standalone_cost_l2only_results=standalone_cost_for_calib,
        standalone_schedule_results=schedule_results,
        config=scaled_config,
    )

    # SR9-v3.6: WARN when cost passes via relative-clause only (i.e. absolute
    # clause failed but the OR-relative-tolerance saved the gate). This
    # surfaces the fragility flagged by the v3.6 diagnostic — the relative
    # clause is currently *not* the binding constraint at canonical iter, so
    # if it ever becomes binding we want a visible signal.
    cost_abs_gap = float(calibration.get("cost_absolute_gap_dollars", 0.0))
    cost_rel_gap = float(calibration.get("cost_relative_gap_pct", 0.0))
    cost_tol_pct = float(config.cost_calibration_tolerance_pct)
    if (
        cost_abs_gap > cost_tol_dollars_effective
        and cost_rel_gap <= cost_tol_pct
        and calibration.get("cost_passes_calibration", False)
    ):
        logger.warning(
            "Cost calibration passes via relative-clause only "
            "(absolute gap $%.0f > scaled tolerance $%.0f at iter=%d; "
            "relative gap %.4f%% <= tolerance %.4f%%). "
            "See METHODOLOGY.md §6.4 for the relative-clause fragility note.",
            cost_abs_gap, cost_tol_dollars_effective, n_iter_used,
            cost_rel_gap * 100.0, cost_tol_pct * 100.0,
        )

    # --- Top-3 cost contributors ------------------------------------------
    top_3_cost_only = _rank_by_p_level(
        per_risk_array=np.asarray(cost_results["per_risk_cost_array"]),
        risk_ids=list(cost_results["risk_ids"]),
        p_level=p_level,
        top_n=top_n,
    )
    top_3_cost_int = _rank_by_p_level(
        per_risk_array=np.asarray(integrated_results["per_risk_cost_array"]),
        risk_ids=list(integrated_results["risk_ids_all"]),
        p_level=p_level,
        top_n=top_n,
    )
    top_3_cost_consistent = top_3_cost_only == top_3_cost_int

    # --- Top-3 schedule contributors (the register's own Mode basis) ------
    # Beta-19b item 6: ranked by probability-weighted mean impact (mean of
    # the per-iteration contribution array) so the cross-validation top-3
    # uses the same metric as the §10.4 schedule-drivers table. The
    # standalone-vs-integrated equality criterion is metric-agnostic so
    # the gate continues to pass under the new metric.
    #
    # 3c Part A (Director, 04/09/2026): this check ranks the BASELINE arms - the same
    # Mode classification, read from the register, that checks 1-3 already use. It used to
    # rank a second "Dummy Realistic" Mode scenario, produced by applying
    # ``sra_simulation.DUMMY_REALISTIC_MODE_OVERRIDE``. That dict is eight hardcoded
    # reference-project risk IDs, so for any other project it overrode nothing: the second
    # scenario was identical to the baseline, and the check compared a run with itself and
    # could not fail. Supplying no second scenario was not an escape either - the check then
    # reported INCONSISTENT and failed every run.
    #
    # On the baseline basis it is a real standalone-vs-integrated agreement test for every
    # project, with nothing to declare per project: the SR5 schedule engine and the
    # integrated engine's schedule arm must rank the same top-3 drivers from the same
    # register. Two engines, one answer - the same shape as checks 1-3.
    #
    # The two ``*_dummy_realistic`` arguments are still accepted so existing callers do not
    # break, and are no longer consulted for this check; ``schedule_top3_basis`` in the
    # result records which basis was used, so a stored result cannot be misread later.
    top_3_sched_sr5 = _rank_by_mean(
        per_risk_array=np.asarray(schedule_results["contribution_array"]),
        risk_ids=list(schedule_results["risk_ids"]),
        top_n=top_n,
    )
    # D-3 as ruled could not be built as written, and D-6 (Director, 10/09/2026, Option A)
    # replaced it: the Stage 3 result's per-risk schedule array is the cost engine's
    # additive, Mode-scaled draw (integrated_simulation_stage3.adapt_to_integrated_results_
    # shape), and the CPM kernel exposes no per-risk contribution at all. So this ranking
    # is additive on BOTH sides whichever arm supplies it, and the label says so. A CPM
    # attribution (leave-one-out, the app's days-at-risk measure) is CPMATTRIB-01.
    sched_basis = integrated_results if stage3_results is None else stage3_results
    sched_basis_label = (
        "Stage 2.5 integrated arm (additive, Mode-scaled)" if stage3_results is None
        else "Stage 3 cost arm's per-risk schedule draws (additive, Mode-scaled; NOT the CPM replay)")
    top_3_sched_int = _rank_by_mean(
        per_risk_array=np.asarray(sched_basis["per_risk_schedule_array"]),
        risk_ids=list(sched_basis["risk_ids_dual"]),
        top_n=top_n,
    )
    # F-30: same order up to within-band ties, with the register's tie band (scaled for
    # iteration count as the absolute tolerances are - noise widens as iterations fall).
    tie_band_base = float(config.schedule_top3_tie_tolerance_pct)
    tie_band_effective = min(tie_band_base * scaling_factor, 1.0)
    top_3_sched_consistent, tie_note = _top_ranks_consistent(
        top_3_sched_sr5, top_3_sched_int,
        _means_by_id(np.asarray(schedule_results["contribution_array"]),
                     list(schedule_results["risk_ids"])),
        _means_by_id(np.asarray(sched_basis["per_risk_schedule_array"]),
                     list(sched_basis["risk_ids_dual"])),
        tie_band_effective,
    )
    # F-42 / D-4: check 2 is the cross-surface Stage 3 comparison when supplied.
    schedule_check_basis = "stage25_sr5_legacy"
    cross_surface_gap_days = None
    cross_surface_line = None
    cross_surface_deliverable = None
    cross_surface_period = None
    cross_surface_p_level = None
    if cross_surface is not None:
        a = float(cross_surface["deliverable_delay_days"])
        b = float(cross_surface["period_delay_days"])
        # The label must read the P-level the two arrays were actually cut at
        # (the register's reporting_p_level), not this function's own p_level
        # parameter, which governs unrelated top-N ranking and defaults to 80.
        cross_surface_p_level = int(cross_surface.get("p_level", p_level))
        cross_surface_gap_days = abs(a - b)
        tol_days = float(cross_surface["tolerance_days"])
        tol_pct = float(cross_surface.get("tolerance_pct", 0.0))
        rel = cross_surface_gap_days / max(abs(b), 1e-9)
        passes = cross_surface_gap_days <= tol_days or rel <= tol_pct
        calibration["schedule_passes_calibration"] = bool(passes)
        calibration["schedule_absolute_gap_days"] = cross_surface_gap_days
        calibration["schedule_relative_gap_pct"] = rel
        schedule_check_basis = "stage3_cross_surface"
        cross_surface_deliverable = a
        cross_surface_period = b
        cross_surface_line = (
            f"Schedule cross-surface (Stage 3, both surfaces, n={int(cross_surface.get('n_iter', 0))}, "
            f"seed={cross_surface.get('seed')}): deliverable P{cross_surface_p_level} delay={a:.3f} d "
            f"vs period engine P{cross_surface_p_level} delay={b:.3f} d "
            f"(gap {cross_surface_gap_days:.3f} d absolute, "
            f"{rel*100:.2f}% relative; tol {tol_days:.2f} d OR {tol_pct*100:.1f}%) - "
            f"{'PASS' if passes else 'FAIL'}. Coverage: both surfaces share the CPM kernel; "
            f"this limb tests how each assembles a Stage 3 run, not the kernel."
        )

    all_pass = bool(
        calibration["cost_passes_calibration"]
        and calibration["schedule_passes_calibration"]
        and top_3_cost_consistent
        and top_3_sched_consistent
    )

    interp_lines = [
        (cross_surface_line if cross_surface_line is not None else
         calibration["interpretation"] + " Coverage: SR5 against the Stage 2.5 integrated "
         "schedule marginal - two copies of one additive formula (F-42); this limb cannot "
         "fail on the headline engine."),
        (
            f"Top-3 cost contributors at P{p_level}: "
            f"cost-only={top_3_cost_only}, integrated={top_3_cost_int}. "
            f"{'CONSISTENT' if top_3_cost_consistent else 'INCONSISTENT'}."
        ),
        (
            "Top-3 schedule contributors by probability-weighted mean impact "
            f"(SR5 on the register Mode basis vs {sched_basis_label}): "
            f"SR5={top_3_sched_sr5}, integrated={top_3_sched_int}; tie band "
            f"{tie_band_effective:.2%} of the cut (register {tie_band_base:.2%} x {scaling_factor:.2f})"
            + (f"; {tie_note}" if tie_note else "") + ". "
            f"{'CONSISTENT' if top_3_sched_consistent else 'INCONSISTENT'}."
        ),
    ]
    interp_lines.append(f"Overall: {'PASS' if all_pass else 'FAIL'}.")
    coverage = {
        "check_1_cost_calibration": "cost-only L2 vs Stage 2.5 integrated cost marginal (different constructions)",
        "check_2_schedule": (
            f"deliverable Stage 3 P{cross_surface_p_level} delay vs period-engine Stage 3 "
            f"P{cross_surface_p_level} delay, same inputs (shared kernel)"
            if schedule_check_basis == "stage3_cross_surface"
            else "SR5 vs Stage 2.5 integrated schedule marginal (same additive formula; cannot fail - F-42)"),
        "check_3_cost_ranking": "cost-only vs Stage 2.5 integrated cost contributors",
        "check_4_schedule_ranking": (
            f"SR5 vs {sched_basis_label}: two additive per-risk sums, so this limb cannot fail "
            f"on the headline engine; a CPM attribution is owed (CPMATTRIB-01)"),
    }
    return {
        # Calibration (inherits SR8 keys)
        "schedule_check_basis": schedule_check_basis,
        "schedule_top3_engine": sched_basis_label,
        "cross_surface_gap_days": cross_surface_gap_days,
        "cross_surface_deliverable_delay_days": cross_surface_deliverable,
        "cross_surface_period_delay_days": cross_surface_period,
        "cross_surface_p_level": cross_surface_p_level,
        "coverage": coverage,
        "cost_passes_calibration": calibration["cost_passes_calibration"],
        "cost_integrated_mean": calibration["cost_integrated_mean"],
        "cost_standalone_l2only_mean": calibration["cost_standalone_l2only_mean"],
        "cost_absolute_gap_dollars": calibration["cost_absolute_gap_dollars"],
        "cost_relative_gap_pct": calibration["cost_relative_gap_pct"],
        "schedule_passes_calibration": calibration["schedule_passes_calibration"],
        "schedule_integrated_mean_days": calibration["schedule_integrated_mean_days"],
        "schedule_standalone_mean_days": calibration["schedule_standalone_mean_days"],
        "schedule_absolute_gap_days": calibration["schedule_absolute_gap_days"],
        "schedule_relative_gap_pct": calibration.get("schedule_relative_gap_pct"),  # RS-D-2
        "cost_tolerance_pct": cost_tol_pct,
        "schedule_tolerance_pct": float(config.schedule_calibration_tolerance_pct),
        # Top-3 contributor consistency (new SR9 logic)
        "top_3_cost_contributors_consistent": top_3_cost_consistent,
        "top_3_cost_contributors_cost_only": top_3_cost_only,
        "top_3_cost_contributors_integrated": top_3_cost_int,
        "top_3_schedule_contributors_consistent": top_3_sched_consistent,
        "top_3_schedule_contributors_sr5": top_3_sched_sr5,
        "top_3_schedule_contributors_integrated": top_3_sched_int,
        # 3c Part A: which Mode classification check 4 ranked, recorded so a stored result
        # from before or after the change cannot be misread as the other.
        "schedule_top3_basis": (
            "register_mode_baseline" if stage3_results is None else "stage3_cost_arm_additive"),
        "schedule_top3_tie_tolerance_pct_base": tie_band_base,
        "schedule_top3_tie_tolerance_pct_effective": tie_band_effective,
        # Aggregate gate
        "all_pass": all_pass,
        "interpretation": "\n".join(interp_lines),
        # SR9-v3.6: iteration-aware tolerance instrumentation
        "n_iter_used_for_scaling": n_iter_used,
        "tolerance_scaling_factor": scaling_factor,
        "tolerance_scaling_canonical_iter": int(CANONICAL_ITERATIONS),
        "tolerance_scaling_cap": float(TOLERANCE_SCALING_CAP),
        "cost_tolerance_dollars_base": cost_tol_dollars_base,
        "cost_tolerance_dollars_effective": cost_tol_dollars_effective,
        "schedule_tolerance_days_base": sched_tol_days_base,
        "schedule_tolerance_days_effective": sched_tol_days_effective,
    }
