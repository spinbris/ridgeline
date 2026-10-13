"""Active-management metrics computed on top of a ScheduleMCResult.

Split into three layers:

1. **Pure-data** — closed-form computations that consume a single
   ScheduleMCResult and per-risk metadata:
   - ``lognormal_p_band`` (the v1.4 methodology centrepiece)
   - ``compute_per_activity_p_bands``
   - ``compute_ssi_per_risk``
   - ``compute_tornado_proxy_per_risk``

2. **Per-risk leave-one-out** — re-runs the conditional Stage 3 MC
   with one risk removed; reports ``days_at_risk_p80`` per risk.
   At standard precision floor (10,000 iter per re-run, ~8 risks)
   this completes in seconds for V8.

3. **Counterfactual mitigation sweep** — re-runs with a proposed
   mitigation applied; reports ``days_saved_p80`` per proposed
   mitigation.

Composition: :func:`compute_am_metrics` runs the full bundle and
returns an :class:`AMMetrics` dataclass with the values shaped for
the JSON writer.

Methodology disclosures (verbatim text required by Doc 3 v2.2
``audit.methodology_notes``) are emitted by
:func:`build_methodology_notes`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import norm


from src.sra.cpm.cpm_simulation import ScheduleMCResult  # noqa: E402
from src.sra.cpm.risk_driver_schema import RiskDriver  # noqa: E402


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants (default knobs — overridable by callers)
# ---------------------------------------------------------------------------

DEFAULT_TOP_N_BY_CI: int = 10
DEFAULT_CI_THRESHOLD: float = 0.05
DEFAULT_PERCENTILES: tuple[float, float, float] = (0.10, 0.50, 0.90)
DEFAULT_DAYS_AT_RISK_ITERATIONS: int = 10_000
DEFAULT_COUNTERFACTUAL_ITERATIONS: int = 10_000


# ---------------------------------------------------------------------------
# Layer 1: pure-data metrics
# ---------------------------------------------------------------------------

def lognormal_p_band(
    mean_h: float,
    std_h: float,
    percentiles: tuple[float, ...] = DEFAULT_PERCENTILES,
) -> tuple[float, ...]:
    """Per-activity lognormal moment-fit P-band derivation.

    Given a target Mean ``m`` and standard deviation ``s``, the
    lognormal distribution that matches these moments has location
    parameter ``mu`` and scale parameter ``sigma``::

        sigma^2 = ln(1 + (s/m)^2)
        mu      = ln(m) - sigma^2/2

    Percentiles read off via::

        P_q = exp(mu + sigma * Phi^{-1}(q))

    Where ``Phi^{-1}`` is the standard normal inverse CDF.

    Degenerate-case handling per AC §6 of AM02 v1.4-final:
    when ``mean_h <= 0`` or ``std_h <= 0``, the P-band collapses to
    the mean value (every percentile equals the mean). This prevents
    NaN / division-by-zero artefacts for activities with no
    risk-driven variance (e.g. risk-free baseline activities).

    Parameters
    ----------
    mean_h : float
        Per-activity Mean of early-finish (working hours). Sourced
        from ``ScheduleMCResult.finish_mean_hours[a]`` post-SR10.D.
    std_h : float
        Per-activity standard deviation of early-finish (working
        hours). Sourced from ``ScheduleMCResult.finish_std_hours[a]``
        post-SR10.D.
    percentiles : tuple[float, ...]
        Percentiles to compute, in 0.0 - 1.0. Defaults to
        ``(0.10, 0.50, 0.90)``.

    Returns
    -------
    tuple[float, ...]
        One value per requested percentile, in the same units as
        ``mean_h`` (working hours).
    """
    if mean_h <= 0.0 or std_h <= 0.0:
        return tuple(float(mean_h) for _ in percentiles)
    cv_sq = (std_h / mean_h) ** 2
    sigma_sq = float(np.log(1.0 + cv_sq))
    sigma = float(np.sqrt(sigma_sq))
    mu = float(np.log(mean_h)) - sigma_sq / 2.0
    return tuple(float(np.exp(mu + sigma * norm.ppf(q))) for q in percentiles)


def _enforce_monotonic_non_negative(
    p10: float, p50: float, p90: float
) -> tuple[float, float, float]:
    """Defensive: clip P-band to non-negative + non-decreasing order.

    Per Doc 3 v2.2 validation rule 10 (``p10 <= p50 <= p90`` for
    every item) and rule 11 (``all percentile values >= 0``). The
    lognormal moment-fit produces strictly monotonic values by
    construction, but FP rounding at extreme CVs can produce tiny
    inversions; this guard makes the contract honest.
    """
    p10 = max(0.0, p10)
    p50 = max(p10, p50)
    p90 = max(p50, p90)
    return p10, p50, p90


@dataclass(frozen=True)
class ActivityPBand:
    """One row of the dashboard's analyst-view A3 stochastic Gantt.

    AM02.1 §4.B.1: removed the ``mode`` field. Mode is a per-RISK
    attribute (Series / Hybrid / Parallel for risk-impact propagation
    through the schedule network); activities don't have a Mode. The
    field was a category error inherited from Doc 3 v2.2 example
    JSON. Doc 3 v2.3 publishes alongside v2.2 removing it.
    """
    activity_id: str
    name: str
    p10_start_days: float
    p50_start_days: float
    p90_start_days: float
    p10_finish_days: float
    p50_finish_days: float
    p90_finish_days: float
    det_es_days: float | None
    det_ef_days: float | None
    criticality_index: float


def compute_per_activity_p_bands(
    *,
    schedule_result: ScheduleMCResult,
    activity_durations_hours: dict[str, float],
    activity_names: dict[str, str],
    deterministic_ef_hours: dict[str, float] | None,
    hours_per_day: float,
    top_n: int = DEFAULT_TOP_N_BY_CI,
    ci_threshold: float = DEFAULT_CI_THRESHOLD,
) -> list[ActivityPBand]:
    """Return the top-N activities by criticality_index with P-bands.

    Filters out activities below ``ci_threshold`` (the brief's
    "executive view" / Doc 3 v2.2 ``ci_threshold`` knob), then sorts
    by criticality_index desc and takes the first ``top_n``.

    For each activity:

    - ``p10/p50/p90 finish`` from ``lognormal_p_band(finish_mean,
      finish_std)``, converted to working days
    - ``p10/p50/p90 start = finish - duration_hours`` (per brief §4
      Phase 2.D §7: "per-activity start derived from finish by
      subtracting deterministic duration; this is a reasonable
      approximation when activity duration variance is small relative
      to the network-induced finish variance")
    - ``det_ef_days`` from a single zero-risk deterministic CPM pass
      (passed in by the caller). ``None`` if not available.
    - ``det_es_days = det_ef_days - duration_days`` (same approximation)

    Caller responsibilities:

    - ``activity_durations_hours`` maps activity_id ->
      ``Activity.original_duration_hours`` from the schedule graph
    - ``activity_names`` maps activity_id -> ``Activity.name``
    - ``deterministic_ef_hours`` is from a zero-risk forward pass
      (e.g. ``cpm_kernel.forward_pass(base_durations)`` or the cached
      output already in the conditional-run pipeline)
    """
    n_act = schedule_result.n_act
    activity_ids = schedule_result.activity_ids
    finish_mean = schedule_result.finish_mean_hours
    finish_std = schedule_result.finish_std_hours
    ci = schedule_result.criticality_index

    if finish_mean.shape != (n_act,) or finish_std.shape != (n_act,):
        raise ValueError(
            "ScheduleMCResult.finish_mean_hours / finish_std_hours not "
            "populated; SR10.D fields are a hard precondition for "
            "Method B per-activity P-bands. Check the engine at this repository's "
            "HEAD (src/am/_provenance.py stamps it)."
        )

    # Sort by CI desc, filter by threshold, take top_n.
    indexed = [
        (i, activity_ids[i], float(ci[activity_ids[i]]))
        for i in range(n_act)
    ]
    # AM02.1 §4.B.2 / Curiosity 9 fix: filter to activities with
    # non-zero risk-driven finish-time variance. High-CI activities in
    # the engagement's current register are anchor points (project-finish
    # milestones, key handover gates) that no risk directly perturbs;
    # their lognormal P-band collapses to a single point. Showing 10
    # collapsed points at the top of the analyst Page A3 stochastic
    # Gantt is visually misleading. Trade CI-completeness for
    # variance-informativeness in v1; methodology note discloses the
    # trade-off.
    indexed = [
        (i, act_id, ci_val) for (i, act_id, ci_val) in indexed
        if float(finish_std[i]) > 0.0
    ]
    indexed.sort(key=lambda t: t[2], reverse=True)
    rows: list[ActivityPBand] = []
    for i, act_id, ci_val in indexed:
        if ci_val < ci_threshold:
            break  # sorted desc → remaining all below
        if len(rows) >= top_n:
            break

        mean_h = float(finish_mean[i])
        std_h = float(finish_std[i])
        duration_h = float(activity_durations_hours.get(act_id, 0.0))

        p10_h, p50_h, p90_h = lognormal_p_band(mean_h, std_h)
        p10_h, p50_h, p90_h = _enforce_monotonic_non_negative(p10_h, p50_h, p90_h)

        p10_d = p10_h / hours_per_day
        p50_d = p50_h / hours_per_day
        p90_d = p90_h / hours_per_day

        duration_d = duration_h / hours_per_day
        # Start = finish - duration (deterministic-duration approximation
        # per brief §4 Phase 2.D §7). Clipped non-negative.
        start_p10_d = max(0.0, p10_d - duration_d)
        start_p50_d = max(0.0, p50_d - duration_d)
        start_p90_d = max(0.0, p90_d - duration_d)

        det_ef_h = (
            deterministic_ef_hours.get(act_id)
            if deterministic_ef_hours is not None
            else None
        )
        det_ef_d = det_ef_h / hours_per_day if det_ef_h is not None else None
        det_es_d = (det_ef_d - duration_d) if det_ef_d is not None else None

        rows.append(ActivityPBand(
            activity_id=act_id,
            name=activity_names.get(act_id, act_id),
            p10_start_days=round(start_p10_d, 2),
            p50_start_days=round(start_p50_d, 2),
            p90_start_days=round(start_p90_d, 2),
            p10_finish_days=round(p10_d, 2),
            p50_finish_days=round(p50_d, 2),
            p90_finish_days=round(p90_d, 2),
            det_es_days=round(det_es_d, 2) if det_es_d is not None else None,
            det_ef_days=round(det_ef_d, 2) if det_ef_d is not None else None,
            criticality_index=round(ci_val, 4),
        ))

    return rows


def compute_ssi_per_risk(
    schedule_result: ScheduleMCResult,
    risk_drivers: dict[str, RiskDriver],
) -> dict[str, float]:
    """Per-risk Schedule Sensitivity Index (SSI).

    Per-activity SSI definition (AACE / PMBOK):

        SSI[a] = (finish_std[a] * CI[a]) / project_finish_std

    Aggregated per-risk by summing the SSI of every activity the risk
    affects (per its ``affected_activity_ids``):

        SSI[r] = sum over a in driver[r].affected_activity_ids of SSI[a]

    SSI values are dimensionless. A higher value indicates the risk's
    affected activities have both high finish-time variance and high
    probability of being on the critical path — both contribute to
    project-level finish-time sensitivity.
    """
    project_std = float(np.std(schedule_result.project_finish_hours))
    if project_std <= 0.0:
        # Degenerate case: no project-level variance (e.g. all risks
        # have probability=0). Return zeros.
        return {rid: 0.0 for rid in risk_drivers}

    activity_ids = schedule_result.activity_ids
    finish_std = schedule_result.finish_std_hours
    ci = schedule_result.criticality_index

    # Per-activity SSI lookup.
    ssi_per_activity: dict[str, float] = {}
    for i, act_id in enumerate(activity_ids):
        ssi_per_activity[act_id] = (
            float(finish_std[i]) * float(ci[act_id])
        ) / project_std

    # Aggregate per risk.
    ssi_per_risk: dict[str, float] = {}
    for rid, driver in risk_drivers.items():
        ssi_per_risk[rid] = sum(
            ssi_per_activity.get(a, 0.0)
            for a in driver.affected_activity_ids
        )
    return ssi_per_risk


def compute_per_risk_criticality(
    schedule_result: ScheduleMCResult,
    risk_drivers: dict[str, RiskDriver],
) -> dict[str, dict[str, float | None]]:
    """Per-risk Mode-conditioned and Mode-independent CI aggregation.

    For each risk, aggregates the per-activity CI values of every
    activity the risk affects (per ``affected_activity_ids``) by
    taking the MAXIMUM. Max captures the dashboard's tornado
    semantics: "criticality of the risk = criticality of its most
    critical affected activity". A risk whose worst affected
    activity sits on a 95% CI path matters more than its average
    affected activity.

    Mode-independent CI is consumed from
    ``ScheduleMCResult.mode_independent_criticality_index`` which is
    populated by the engine only when
    ``criticality_measurement_mode in ("mode_independent", "both")``.
    When that field is None or empty, ``criticality_independent`` is
    returned as None per AM02.1 §3.A.3 (no silent fallback to
    Mode-conditioned).

    Returns
    -------
    dict[risk_id, dict[str, float | None]]
        Outer key is risk_id. Inner dict has two keys:
        ``criticality_conditioned`` and ``criticality_independent``.
        Both round to 4 decimal places when populated.

    Refs: AM02.1 brief §3.A.3.
    """
    ci_conditioned = schedule_result.criticality_index
    ci_independent = getattr(
        schedule_result, "mode_independent_criticality_index", None
    )
    has_independent = ci_independent is not None and len(ci_independent) > 0

    out: dict[str, dict[str, float | None]] = {}
    for rid, driver in risk_drivers.items():
        affected = list(driver.affected_activity_ids)
        if not affected:
            out[rid] = {
                "criticality_conditioned": None,
                "criticality_independent": None,
            }
            continue
        conditioned_vals = [
            float(ci_conditioned[a]) for a in affected
            if a in ci_conditioned
        ]
        cond = max(conditioned_vals) if conditioned_vals else None
        if has_independent:
            independent_vals = [
                float(ci_independent[a]) for a in affected
                if a in ci_independent
            ]
            indep = max(independent_vals) if independent_vals else None
        else:
            indep = None
        out[rid] = {
            "criticality_conditioned": (
                round(cond, 4) if cond is not None else None
            ),
            "criticality_independent": (
                round(indep, 4) if indep is not None else None
            ),
        }
    return out


def divergence_flag(
    conditioned: float | None, independent: float | None,
    threshold: float = 0.05,
) -> str:
    """Classify Mode-divergence as consistent / amplifies / suppresses.

    DORMANT since AM10 (WIND-01 A4, 2026-07-09). The ``risks[].divergence_flag``
    contract field this fed was dropped: under the pure-MC AM basis
    (``apply_mode_multipliers=False``, WIND-01) the conditioned and
    independent CIs coincide, so the classification is structurally always
    ``"consistent"``. ``json_writer`` no longer imports this. It is RETAINED,
    unused, as the revival surface for the deferred WIND-01b Mode-sensitivity
    (``apply=True``) run - the one basis under which the two CIs genuinely
    diverge - mirroring the retention of ``ModePieChart.tsx`` /
    ``DivergenceBadge.tsx``. Do not delete without retiring WIND-01b.

    The dashboard's tornado divergence pill renders one of three
    states per risk:

    - ``"consistent"`` when conditioned and independent CI are within
      ``threshold`` of each other (default 0.05). Also the safe
      default when either input is None (no signal to detect
      divergence from).
    - ``"mode_amplifies"`` when ``conditioned > independent + threshold``.
      The Mode multiplier is INCREASING this risk's stochastic
      criticality relative to the AACE 65R-11 "independent"
      measurement.
    - ``"mode_suppresses"`` when ``conditioned < independent - threshold``.
      The Mode multiplier is suppressing this risk's contribution
      relative to the independent measurement.

    Refs: AM02.1 brief §3.A.3.
    """
    if conditioned is None or independent is None:
        return "consistent"
    diff = conditioned - independent
    if diff > threshold:
        return "mode_amplifies"
    if diff < -threshold:
        return "mode_suppresses"
    return "consistent"


def compute_tornado_proxy_per_risk(
    risk_drivers: dict[str, RiskDriver],
    hours_per_day: float,
) -> dict[str, float]:
    """Model-based per-risk sigma_days proxy.

    Standard PERT std formula::

        sigma = (pess - opt) / 6

    Multiplied by ``probability`` to weight by Bernoulli firing rate,
    then converted to working days. This is a closed-form proxy
    sufficient for tornado ordering; sample-based per-risk sigma would
    require per-iteration fired-indicator arrays which Stage 3
    intentionally does not persist.

    Documented in audit methodology notes; consumers know this is a
    PERT-derived approximation rather than a direct sample standard
    deviation.
    """
    out: dict[str, float] = {}
    for rid, d in risk_drivers.items():
        opt_h = float(d.opt_pert)
        pess_h = float(d.pess_pert)
        # Injection method "additive_pert_days" / "discrete_event_additive_days"
        # PERT params ARE in days already; multiplicative methods are
        # dimensionless factors. For tornado purposes the additive case
        # is what the V8 the engagement register uses (see
        # the register's default injection method (RS-D-6)).
        # Multiplicative branches return 0 from this proxy.
        if d.injection_method in (
            "multiplicative_pert_factor", "productivity_multiplicative_factor",
        ):
            out[rid] = 0.0
            continue
        # PERT params in DAYS (per the V8 register convention); no
        # conversion needed.
        pert_sigma_days = max(0.0, (pess_h - opt_h) / 6.0)
        out[rid] = float(d.probability) * pert_sigma_days
    return out


# ---------------------------------------------------------------------------
# Layer 2: per-risk leave-one-out (days_at_risk)
# ---------------------------------------------------------------------------

def compute_leave_one_out_metrics(
    *,
    baseline_inputs: Any,  # ConditionalRunInputs; typed as Any to avoid import cycle
    baseline_schedule_result: ScheduleMCResult,
    risks_to_iterate: list[str],
    n_iter: int = DEFAULT_DAYS_AT_RISK_ITERATIONS,
    p_level: int = 80,
) -> dict[str, dict[str, float]]:
    """Single leave-one-out loop yielding BOTH per-risk metrics (AM04).

    The leave-one-out re-runs are the expensive part (``n_risks`` x
    ``n_iter`` iterations). AM04's hard AC (brief Section 6) is that the
    sample-based tornado sigma is derived from the SAME re-runs that
    already produce ``days_at_risk_p80`` - not a second pass. This helper
    runs the loop ONCE and returns, per risk, both derived quantities
    read off the identical leave-one-out finish distribution.

    For each ``risk_id`` in ``risks_to_iterate`` the conditional Stage 3
    MC is re-run at the smaller ``n_iter`` count with that risk forced
    Closed (probability -> 0), exactly the synthetic-workbook mechanism
    ``_force_close_risk_in_workbook`` already uses. From the resulting
    finish distribution ``F_minus_r`` (working days) two values are
    derived against the baseline distribution ``F_baseline``:

    - ``days_at_risk_p80`` = ``P{p_level}(F_baseline) - P{p_level}(F_minus_r)``.
      Positive when removing the risk pulls the project P80 earlier (the
      risk drives P80 upward when present). Negatives are rare but
      possible at the 10k-iter precision floor.
    - ``sample_sigma_days`` = ``std(F_baseline) - std(F_minus_r)`` (AM04).
      The marginal contribution of the risk to project-finish standard
      deviation. Non-negative in expectation (removing a risk reduces
      variance) but MC noise at 10k iterations can yield small negatives;
      the raw rounded value is stored and the dashboard clamps the bar at
      0 while the tooltip shows the raw figure. Non-additive: per-risk
      sigmas do not sum to total project sigma (risks interact through
      the schedule network), so the metric is valid for tornado ordering
      and relative magnitude, not decomposition arithmetic.

    Both share the ~0.3-day 10k-iter precision-floor caveat documented in
    the audit block; values within the floor should not be
    over-interpreted.

    Returns
    -------
    dict[str, dict[str, float]]
        ``{risk_id: {"days_at_risk_p80": float, "sample_sigma_days": float}}``.
        A risk whose re-run raises (e.g. all sources pinned out) maps both
        values to NaN; downstream serialisation emits ``null`` for those.
    """
    from src.am.conditional_runner import (  # local import — avoids circular
        ConditionalRunInputs, run_conditional_mc,
    )
    from dataclasses import replace as dc_replace

    hours_per_day = 8.0  # the engagement calendar default; same as the graph

    baseline_finish_hours = baseline_schedule_result.project_finish_hours
    # Baseline P{p_level} and standard deviation, both in working days,
    # read off the SAME baseline distribution.
    baseline_p_days = float(
        np.percentile(baseline_finish_hours, p_level)
    ) / hours_per_day
    baseline_std_days = float(np.std(baseline_finish_hours)) / hours_per_day

    sub_inputs = dc_replace(baseline_inputs, n_iter=n_iter)

    out: dict[str, dict[str, float]] = {}
    for rid in risks_to_iterate:
        # Build a synthetic workbook view that closes this one risk.
        synthetic_workbook = _force_close_risk_in_workbook(
            baseline_inputs.workbook_data, rid,
        )
        loop_inputs = dc_replace(sub_inputs, workbook_data=synthetic_workbook)
        try:
            sub_result = run_conditional_mc(loop_inputs)
        except ValueError as exc:
            logger.warning(
                "Leave-one-out for %s skipped: %s. days_at_risk_p%d and "
                "sample_sigma_days set to NaN.",
                rid, exc, p_level,
            )
            out[rid] = {
                "days_at_risk_p80": float("nan"),
                "sample_sigma_days": float("nan"),
            }
            continue
        # ONE finish distribution per re-run; both metrics derive from it.
        sub_finish_hours = sub_result.schedule_result.project_finish_hours
        sub_p_days = float(np.percentile(sub_finish_hours, p_level)) / hours_per_day
        sub_std_days = float(np.std(sub_finish_hours)) / hours_per_day
        out[rid] = {
            "days_at_risk_p80": round(baseline_p_days - sub_p_days, 2),
            "sample_sigma_days": round(baseline_std_days - sub_std_days, 2),
        }

    return out


def compute_days_at_risk_per_risk(
    *,
    baseline_inputs: Any,  # ConditionalRunInputs; typed as Any to avoid import cycle
    baseline_schedule_result: ScheduleMCResult,
    risks_to_iterate: list[str],
    n_iter: int = DEFAULT_DAYS_AT_RISK_ITERATIONS,
    p_level: int = 80,
) -> dict[str, float]:
    """Per-risk leave-one-out days_at_risk_P{p_level} computation.

    Thin back-compat wrapper over :func:`compute_leave_one_out_metrics`
    (AM04 single-loop refactor): projects out only the ``days_at_risk_p80``
    key so the public signature and return shape stay byte-stable for the
    existing callers and integration tests. New code that also wants the
    sample-based tornado sigma should call
    :func:`compute_leave_one_out_metrics` directly to avoid a second pass.
    """
    combined = compute_leave_one_out_metrics(
        baseline_inputs=baseline_inputs,
        baseline_schedule_result=baseline_schedule_result,
        risks_to_iterate=risks_to_iterate,
        n_iter=n_iter,
        p_level=p_level,
    )
    return {rid: m["days_at_risk_p80"] for rid, m in combined.items()}


def _force_close_risk_in_workbook(workbook_data: Any, risk_id: str) -> Any:
    """Return a WorkbookData copy with one risk marked Closed.

    Used by the leave-one-out computation: forcing a risk's status
    to "Closed" causes ``_build_pinning_decisions`` to set its
    probability to 0 (rather than removing the driver entirely, which
    would change the severity-uniform projection shape). The remaining
    risks sample with the same RNG state as baseline.
    """
    from src.am.workbook_reader import WorkbookData

    new_rows = []
    found = False
    for row in workbook_data.risk_status:
        if row["risk_id"] == risk_id:
            new_row = dict(row)
            new_row["status_this_period"] = "Closed"
            new_rows.append(new_row)
            found = True
        else:
            new_rows.append(row)
    if not found:
        # Risk wasn't in the workbook; inject a synthetic Closed row.
        new_rows.append({
            "risk_id": risk_id,
            "risk_title": f"(synthetic for leave-one-out)",
            "status_this_period": "Closed",
            "probability_current": None,
            "probability_override": None,
            "probability_resolved": None,
            "owner": "(synthetic)",
            "fired_date": None,
            "closed_date": None,
            "notes_this_period": None,
            "helper_data_missing": False,
            "status_changed": None,
        })
    return WorkbookData(
        period_info=workbook_data.period_info,
        risk_status=new_rows,
        milestones=workbook_data.milestones,
        mitigations=workbook_data.mitigations,
        am_risk_ids=workbook_data.am_risk_ids,
    )


# ---------------------------------------------------------------------------
# Layer 3: counterfactual mitigation sweep
# ---------------------------------------------------------------------------

def compute_counterfactual_sweep(
    *,
    baseline_inputs: Any,  # ConditionalRunInputs
    baseline_schedule_result: ScheduleMCResult,
    proposed_mitigations: list[dict[str, Any]],
    n_iter: int = DEFAULT_COUNTERFACTUAL_ITERATIONS,
    p_level: int = 80,
) -> dict[str, float]:
    """Per-proposed-mitigation days_saved_P{p_level} computation.

    For each mitigation in ``proposed_mitigations`` with non-blank
    ``risk_id``, re-runs the conditional Stage 3 MC at the smaller
    ``n_iter`` count with the linked risk treated as "Completed
    mitigation" (i.e. removed from the MC, same as
    Status=Completed). Reports::

        days_saved_p80[m] = baseline_p80 - counterfactual_p80

    Positive when the mitigation reduces P80 (i.e. the linked risk
    was driving project finish upward). The precision floor is
    documented in audit.methodology_notes.

    Empty input or mitigations with no linked risk_id are skipped
    silently (Doc 3 v2.2 ``mitigations[]`` will simply not carry
    those rows).
    """
    from src.am.conditional_runner import (  # local import
        run_conditional_mc,
    )
    from dataclasses import replace as dc_replace

    hours_per_day = 8.0
    baseline_p_hours = float(
        np.percentile(baseline_schedule_result.project_finish_hours, p_level)
    )
    baseline_p_days = baseline_p_hours / hours_per_day

    out: dict[str, float] = {}
    for m in proposed_mitigations:
        mit_id = m.get("mitigation_id")
        risk_id = m.get("risk_id")
        status = m.get("status")
        if mit_id is None or risk_id is None or status != "Proposed":
            continue

        synthetic_workbook = _apply_counterfactual_mitigation(
            baseline_inputs.workbook_data, str(risk_id), str(mit_id),
        )
        loop_inputs = dc_replace(
            baseline_inputs, workbook_data=synthetic_workbook, n_iter=n_iter,
        )
        try:
            sub_result = run_conditional_mc(loop_inputs)
        except ValueError as exc:
            logger.warning(
                "Counterfactual for mitigation %s (risk %s) skipped: %s",
                mit_id, risk_id, exc,
            )
            out[str(mit_id)] = float("nan")
            continue
        sub_p_hours = float(np.percentile(
            sub_result.schedule_result.project_finish_hours, p_level
        ))
        sub_p_days = sub_p_hours / hours_per_day
        out[str(mit_id)] = round(baseline_p_days - sub_p_days, 2)
    return out


def _apply_counterfactual_mitigation(
    workbook_data: Any, risk_id: str, mitigation_id: str,
) -> Any:
    """Synthesize a WorkbookData where the named mitigation is Completed.

    Same approach as the leave-one-out helper, but operating on the
    mitigations list rather than risk_status. The pinning logic
    treats Completed mitigations by removing the linked risk from
    the MC.
    """
    from src.am.workbook_reader import WorkbookData

    new_mits = []
    found = False
    for m in workbook_data.mitigations:
        if m.get("mitigation_id") == mitigation_id:
            new_m = dict(m)
            new_m["status"] = "Completed"
            new_mits.append(new_m)
            found = True
        else:
            new_mits.append(m)
    if not found:
        new_mits.append({
            "mitigation_id": mitigation_id,
            "risk_id": risk_id,
            "description": "(synthetic counterfactual)",
            "cost_aud": None,
            "lead_time_weeks": None,
            "status": "Completed",
            "approved_date": None,
            "completed_date": None,
            "owner": None,
            "estimated_days_saved": None,
            "actual_days_saved": None,
            "notes": None,
        })
    return WorkbookData(
        period_info=workbook_data.period_info,
        risk_status=workbook_data.risk_status,
        milestones=workbook_data.milestones,
        mitigations=new_mits,
        am_risk_ids=workbook_data.am_risk_ids,
    )


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AMMetrics:
    """All AM-side metrics, shaped for the JSON writer."""
    per_activity_p_bands: list[ActivityPBand]
    ssi_per_risk: dict[str, float]
    tornado_sigma_days_per_risk: dict[str, float]
    days_at_risk_p80_per_risk: dict[str, float]
    counterfactual_days_saved_p80_per_mitigation: dict[str, float]
    methodology_notes: list[dict[str, Any]]
    # AM02.1 §3.A.3: per-risk Mode-conditioned and Mode-independent CI
    # aggregation. Outer dict keyed by risk_id; inner dict has
    # "criticality_conditioned" and "criticality_independent" keys
    # (float | None). Default-factory empty so pre-AM02.1 stub callers
    # in tests continue to work; run_period.run_period always populates
    # it from compute_per_risk_criticality.
    per_risk_criticality: dict[str, dict[str, float | None]] = field(
        default_factory=dict
    )
    # AM04: sample-based per-risk tornado sigma (working days) via
    # leave-one-out variance reduction, derived from the same re-runs as
    # days_at_risk_p80 (no double compute). Keyed by risk_id; populated for
    # every risk in risks_to_evaluate. Default-factory empty so the stub
    # callers in tests construct AMMetrics without it; run_period always
    # populates it from compute_leave_one_out_metrics. A risk absent from
    # this dict serialises as null and the dashboard falls back to the PERT
    # proxy (tornado_sigma_days_per_risk) for that row.
    tornado_sample_sigma_days_per_risk: dict[str, float] = field(
        default_factory=dict
    )


def build_methodology_notes(
    *,
    p_band_method: str = "B",
    days_at_risk_iterations: int = DEFAULT_DAYS_AT_RISK_ITERATIONS,
    counterfactual_iterations: int = DEFAULT_COUNTERFACTUAL_ITERATIONS,
    project_label: str | None = None,
) -> list[dict[str, Any]]:
    """Return the audit.methodology_notes block per Doc 3 v2.2.

    Verbatim text matches the brief §4 Phase 2.D §8 and Doc 3 v2.2
    §audit. Method "B" is the v1 default (lognormal moment-fit).

    ``project_label`` names the active project in the top-N filter note
    (``None`` resolves to the active binding's name; the wind path passes
    "synthetic wind" so the JSON carries no engagement identifier).
    """
    if project_label is None:
        from src.sra.cpm.bindings.registry import active_project_name
        project_label = active_project_name()

    notes: list[dict[str, Any]] = []
    if p_band_method == "B":
        notes.append({
            "topic": "per_activity_p_bands",
            "method": "B",
            "text": (
                "Per-activity P10/P50/P90 envelopes derived from "
                "per-activity Mean and standard deviation of finish day "
                "using lognormal "
                "moment-fit. The lognormal distribution is fit to the "
                "(Mean, std) of each activity's finish day via the "
                "standard formulae sigma_sq = ln(1 + (std/Mean)^2), "
                "mu = ln(Mean) - sigma_sq/2. Percentiles read off via "
                "exp(mu + sigma * Phi-inverse(q)). This captures the "
                "right-skew that CPM-replay produces at merge points "
                "more faithfully than a normal-approximation. "
                "Project-level percentiles in the headline S-curve are "
                "direct percentiles from the 100k-iteration project "
                "finish distribution and are not affected by this "
                "per-activity derivation. Direct per-iteration sampling "
                "(AACE 57R-09 Tier 3) is a planned refinement. "
                "Methodology aligned with AACE 132R-23 Level 2 / GN3A "
                "Risk Factor Model 2."
            ),
            "queued_for_v1_1": "Per-iteration ES/EF persistence",
        })
    notes.append({
        "topic": "counterfactual_iteration_budget",
        "method": "subsampled",
        "text": (
            f"Counterfactual analyses for proposed mitigations and "
            f"per-risk days-at-risk computations are run at "
            f"{counterfactual_iterations:,} / {days_at_risk_iterations:,} "
            f"iterations respectively (vs 100,000 for the main run). "
            f"Precision floor on each per-mitigation days_saved estimate "
            f"is approximately 0.3 days at standard project variance. "
            f"Insufficient for fine ranking of mitigations within 1 day "
            f"of each other; sufficient for the top-of-list ranking the "
            f"dashboard surfaces."
        ),
    })
    notes.append({
        "topic": "per_risk_tornado_sigma",
        "method": "sample_leave_one_out_with_pert_fallback",
        "text": (
            f"Per-risk tornado sigma is reported two ways. The PRIMARY is "
            f"a sample-based sigma_days (tornado_sample_sigma_days), the "
            f"marginal contribution of each risk to project-finish standard "
            f"deviation measured by leave-one-out: std(finish) minus "
            f"std(finish with the risk forced Closed), in working days, off "
            f"the same {days_at_risk_iterations:,}-iteration re-runs that "
            f"produce days_at_risk (no additional Monte Carlo cost). Unlike "
            f"the model-based proxy it responds to per-period status: because "
            f"the conditional runner removes Fired / Completed-mitigation "
            f"risks and zeroes Closed risks' probability, a resolved risk's "
            f"leave-one-out re-run equals baseline and its sample sigma falls "
            f"to approximately 0, so resolved risks self-correct to the bottom "
            f"of the tornado with no explicit filter. Caveats: the metric is "
            f"NON-ADDITIVE (risks interact through the schedule network, so "
            f"per-risk sigmas do not sum to total project sigma; it is valid "
            f"for ordering and relative magnitude, not decomposition "
            f"arithmetic), sits at the {days_at_risk_iterations:,}-iteration "
            f"precision floor (approximately 0.3 days; differences within the "
            f"floor, including small negatives from MC noise, should not be "
            f"over-interpreted - the raw value is stored and the dashboard "
            f"clamps the bar at 0), and is a marginal-removal definition "
            f"rather than a within-run variance decomposition. The FALLBACK, "
            f"retained for back-compat and for any risk outside the evaluated "
            f"set, is the closed-form PERT proxy tornado_sigma_days: "
            f"(pess - opt) / 6 weighted by Bernoulli probability, which "
            f"depends only on register inputs and does not respond to status. "
            f"The dashboard prefers the sample sigma when present and labels "
            f"which is shown. The textbook within-run per-iteration variance "
            f"decomposition (AACE 57R-09 Tier 3) is not yet implemented; "
            f"it would need engine-side support."
        ),
        "queued_for_v1_1": "Per-iteration risk-fired persistence",
    })
    notes.append({
        "topic": "per_risk_cruciality_proxy",
        "method": "days_at_risk_normalised",
        "text": (
            "Per-risk cruciality is reported as a proxy: "
            "days_at_risk_p80 / project_finish_p80. True Pearson "
            "correlation between per-risk fired indicators and project "
            "finish would require per-iteration risk-fired persistence "
            "(the same capability the per-iteration variance decomposition "
            "needs). The proxy is sufficient for "
            "risk ranking; the dashboard labels the field "
            "cruciality_proxy_p80 to distinguish."
        ),
    })
    # AM02.1 §4.B.2: discloses the top-N filter that hides
    # always-critical anchor activities whose lognormal P-band
    # collapses to a point.
    notes.append({
        "topic": "top_n_activity_filter",
        "method": "non_zero_variance",
        "text": (
            "The analyst-view top-N activity table is filtered to "
            "activities with non-zero risk-driven finish-time variance "
            "(finish_std_hours > 0). Activities with the highest "
            "criticality_index but no risks directly mapped to them "
            "(e.g. project-finish milestones, schedule anchor points) "
            "are excluded because their lognormal P-band collapses to "
            "a single point and is uninformative on a stochastic "
            "Gantt. This trades CI-completeness for "
            "variance-informativeness; a refinement of the filter "
            "(e.g. hybrid CI-times-variance ranking) is a planned "
            "refinement, alongside the broader question of "
            f"whether the current {project_label} risk-to-activity mapping "
            "needs more coverage of always-critical anchor activities."
        ),
        "queued_for_v1_1": "Top-N filter refinement + register-coverage review",
    })
    return notes
