"""Write the period JSON per Doc 3 v2.2.

Public entry point::

    write_period_json(...)  -> Path

Composes the ten top-level blocks (``schema_version``, ``meta``,
``headline``, ``trend``, ``risks``, ``mitigations``, ``activities``,
``distribution``, ``delta``, ``audit``) from the conditional-run
result + AM metrics + workbook data, validates the 11 contract
rules in Doc 3 v2.2 §"Validation requirements", and writes the
file to ``data/period_YYYYMMDD.json``.

Working-day -> calendar-date conversion uses a simple 5-working-days
= 7-calendar-days ratio (no holiday calendar; sufficient for v1
dashboard render). The project start anchor is supplied by the
caller (typically derived from the .xer's earliest task start in
:mod:`src.am.run_period`).

Period-over-period delta: scans ``data/period_*.json`` for the most
recent period older than the current period_end_date; if found,
populates ``delta``; otherwise emits ``{"period_0": true}`` to
signal first-period state.

Trend strip: scans up to 5 prior period_*.json files (newest 5).
First period emits a single point.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import math
import re
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np


from src.rng_streams import require_seed  # noqa: E402
from src.sra.cpm.risk_driver_schema import RiskDriver  # noqa: E402

from src.am.conditional_runner import (
    ConditionalRunResult,
    PinnedRiskState,
)
from src.am.metrics import (
    AMMetrics,
    ActivityPBand,
)
from src.am.workbook_reader import WorkbookData


logger = logging.getLogger(__name__)


# AM10 (WIND-01 A4, 2026-07-09): bumped 1.0 -> 1.1 on the removal of the
# risks[].divergence_flag field (Doc 3 contract v2.4 -> v2.5). A field
# removal must move the version so a consumer can detect it; zod accepts
# the new value. Structural-major stays 1; this is a contract-minor bump.
SCHEMA_VERSION = "1.4"  # stage 7 part B: the optional top-level `integrated` block
# 1.3 = PROVCRLF01 (input_sha256 values became {method, value} records).
# 1.4 = stage 7 part B / SPEC §5.2 decision C2, ruled 05/09/2026: the integrated
# cost-plus-schedule result reaches the cycle, in a NEW top-level block rather than inside
# `headline`. `headline` is dates and `trend` reads it back across periods; folding dollars
# into it would make one block mean different things in different periods. The block is
# OPTIONAL, so every 1.3 artefact stays valid and a register that cannot dollarise days
# still produces a period. Part C adds `meta.project_key` WITHIN 1.4 - additive, no second
# bump, sound because §5.2 ruled the key optional too.
HOURS_PER_DAY = 8.0

# AM08 / AIA-01: presentation threshold for period-over-period per-risk
# attribution. A per-risk days_at_risk_p80 move is surfaced in delta.worse /
# delta.better only when it exceeds this many working days. Grounded in the
# 10k days-at-risk precision floor: per-risk cross-seed sigma ~0.3-0.45 d
# (max observed single-seed range 1.1 d), so a period-over-period difference
# has sigma ~0.64 d; T = 1.5 d sits ~2.3 sigma above that noise floor. This is
# a disclosed presentation threshold (see _DELTA_ATTRIBUTION_NOTE), not a
# statistical significance test. Tunable.
DELTA_ATTRIBUTION_THRESHOLD_DAYS: float = 1.5

_DELTA_ATTRIBUTION_NOTE: dict[str, Any] = {
    "topic": "delta_attribution_threshold",
    "method": "presentation_threshold",
    "text": (
        "Period-over-period per-risk attribution (the What changed page) lists a "
        "risk under worse / better only when its days-at-risk P80 moved by more "
        f"than {DELTA_ATTRIBUTION_THRESHOLD_DAYS:g} working days versus the prior "
        "period. This is a disclosed presentation threshold, not a statistical "
        "significance test: it is set roughly 2x the empirical Monte Carlo "
        "standard error of a period-over-period days-at-risk difference at the "
        "10,000-iteration days-at-risk precision floor (per-risk sigma about 0.3 "
        "to 0.45 working days). Risks that closed this period are always listed, "
        "attributed to their full prior days-at-risk."
    ),
}
CALENDAR_DAYS_PER_WORKING_DAY = 7.0 / 5.0  # weekends, no holidays


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class JsonWriterError(ValueError):
    """Raised on any contract-validation failure."""


# ---------------------------------------------------------------------------
# Calendar arithmetic
# ---------------------------------------------------------------------------

def _working_days_to_calendar_date(
    project_start: _dt.date, working_days: float
) -> _dt.date:
    """Add ``working_days`` working days to ``project_start``.

    Simple 5/7 conversion: 5 working days correspond to 7 calendar
    days. Doesn't model holidays. Sufficient for v1 dashboard.
    """
    calendar_days = working_days * CALENDAR_DAYS_PER_WORKING_DAY
    return project_start + _dt.timedelta(days=float(calendar_days))


def _isoformat_date(d: _dt.date) -> str:
    return d.isoformat()


def _is_open_status(row: dict[str, Any]) -> bool:
    """Treat None/blank ``status_this_period`` as Open.

    Per AM02.1 §3.A.1: an unfilled status_this_period means the PM
    hasn't moved the risk; the risk is still open. Both this helper
    and ``_build_risks``' ``(ws.get("status_this_period") or "Open")``
    default share the same convention so the headline open count and
    the per-risk status field agree.
    """
    status = row.get("status_this_period")
    if status is None or status == "":
        return True
    return status in ("Open", "Actioned", "Monitor")


# ---------------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------------

def _build_meta(
    *,
    workbook_data: WorkbookData,
    workbook_filename: str,
    xer_filename: str,
    register_version: str,
    iterations: int,
    seed: int,
    seed_source: str | None = None,
    period_end_date: _dt.date,
    project_key: str | None = None,
    previous_period_end_date: _dt.date | None,
    engine_run_date: _dt.datetime,
    project_display_name: str | None = None,
    engine_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "period_end_date": _isoformat_date(period_end_date),
        "previous_period_end_date": (
            _isoformat_date(previous_period_end_date)
            if previous_period_end_date is not None else None
        ),
        "engine_run_date": engine_run_date.replace(microsecond=0).isoformat() + "Z",
        "engine_run_hash": str(uuid.uuid4()),
        "register_version": register_version,
        "workbook_filename": workbook_filename,
        "xer_filename": xer_filename,
        "iterations": iterations,
        "seed": seed,
    }
    # SEEDZERO-01 P3: where the period's seed came from - the binding's declaration or --seed.
    if seed_source is not None:
        meta["seed_source"] = seed_source
    # Stage 7 part C (B-2), contract 1.4: the project this period belongs to.
    #
    # OPTIONAL by ruling (§5.2, key optional), which decides how a consumer must treat it:
    # the PATH is authoritative for which project a period belongs to and this field is
    # CORROBORATING. An unkeyed period in a project directory is valid and belongs to that
    # directory. `project_display_name` beside it cannot do this job - it is a label, it is
    # optional, and two projects can share one.
    if project_key:
        meta["project_key"] = project_key
    # showcase-P5 WS5-C: optional project display name for the dashboard
    # chrome. Emitted when resolved (always, from project_binding); kept
    # OPTIONAL in the contract so the pre-P5 field-less archived artefact
    # still validates. Carries no figure; the WS4-A repro gate neutralises it.
    if project_display_name is not None:
        meta["project_display_name"] = project_display_name
    # AM09: engine-provenance stamp. Additive (Doc 3 v2.6): engine SHA (this
    # repository's HEAD; no pin, RS-A2 P-3), dirty-tree flag, and per-file input digests, so
    # a published figure is traceable to the exact code and inputs. Emitted
    # when run_period supplies it; absent on pre-AM09 (1.1) callers, which the
    # contract keeps OPTIONAL for additive-compat.
    if engine_provenance is not None:
        for key in (
            "engine_sha",
            "engine_tree_dirty",
            "input_sha256",
        ):
            if key in engine_provenance:
                meta[key] = engine_provenance[key]
    return meta


def _build_headline(
    *,
    project_finish_hours: np.ndarray,
    project_start: _dt.date,
    deterministic_finish_hours: float,
    workbook_data: WorkbookData,
) -> dict[str, Any]:
    def _percentile_date(p: int) -> _dt.date:
        return _working_days_to_calendar_date(
            project_start, float(np.percentile(project_finish_hours, p)) / HOURS_PER_DAY
        )

    p10 = _percentile_date(10)
    p50 = _percentile_date(50)
    mean = _working_days_to_calendar_date(
        project_start, float(np.mean(project_finish_hours)) / HOURS_PER_DAY
    )
    p80 = _percentile_date(80)
    p90 = _percentile_date(90)
    p95 = _percentile_date(95)
    det = _working_days_to_calendar_date(
        project_start, float(deterministic_finish_hours) / HOURS_PER_DAY
    )

    def _delta_days(target_finish: _dt.date) -> int:
        return int((target_finish - det).days)

    risk_status = workbook_data.risk_status
    # Per AM02.1 §3.A.1: an unfilled status_this_period (None or "")
    # means the risk is still open (PM hasn't moved it). Same default
    # _build_risks already applies. Fired and Closed remain
    # literal-match (a risk hasn't fired or closed unless explicitly
    # recorded by the PM).
    open_count = sum(1 for r in risk_status if _is_open_status(r))
    fired_count = sum(1 for r in risk_status if r.get("status_this_period") == "Fired")
    closed_count = sum(1 for r in risk_status if r.get("status_this_period") == "Closed")

    return {
        "p10_finish": _isoformat_date(p10),
        "p50_finish": _isoformat_date(p50),
        "mean_finish": _isoformat_date(mean),
        "p80_finish": _isoformat_date(p80),
        "p90_finish": _isoformat_date(p90),
        "p95_finish": _isoformat_date(p95),
        "deterministic_finish": _isoformat_date(det),
        "p80_days_behind_plan": _delta_days(p80),
        "p50_days_behind_plan": _delta_days(p50),
        "p90_days_behind_plan": _delta_days(p90),
        "open_risks_count": open_count,
        "fired_this_period_count": fired_count,
        "closed_this_period_count": closed_count,
        "near_critical_milestones_30d": [],
    }


def _build_risks(
    *,
    pinned_states: tuple[PinnedRiskState, ...],
    risk_drivers: dict[str, RiskDriver],
    workbook_data: WorkbookData,
    am_metrics: AMMetrics,
    project_finish_p80_days: float,
) -> list[dict[str, Any]]:
    """Per-risk dashboard rows. Sorted by days_at_risk_p80 descending."""
    by_id = {ps.risk_id: ps for ps in pinned_states}
    ws_by_id = {r["risk_id"]: r for r in workbook_data.risk_status}

    rows: list[dict[str, Any]] = []
    for rid in risk_drivers:
        driver = risk_drivers[rid]
        ws = ws_by_id.get(rid, {})
        ps = by_id.get(rid)

        # AM08 Part B: floor at 0 so a resolved risk's residual leave-one-out
        # noise (e.g. -0.4 d) does not surface as a negative on the risk table
        # or leak into the delta attribution arithmetic. Display-only clamp.
        days_at_risk = max(
            0.0, float(am_metrics.days_at_risk_p80_per_risk.get(rid, 0.0))
        )
        cruciality_proxy = (
            days_at_risk / project_finish_p80_days
            if project_finish_p80_days > 0 else 0.0
        )

        # AM08 Part B / AIA-01b: surface the EFFECTIVE period probability
        # (workbook Probability_override where set, else register baseline).
        # PinnedRiskState.new_probability is the pinned value the MC actually
        # sampled with; None only when the risk was removed from the run. The
        # register baseline stays recoverable via ps.original_probability. See
        # Doc 3 v2.4 "probability semantics (AM08 clarification)".
        effective_probability = (
            float(ps.new_probability)
            if ps is not None and ps.new_probability is not None
            else float(driver.probability)
        )
        # impact_days_emv = effective probability * ml_pert (days; v8 register units)
        impact_days_emv = effective_probability * float(driver.ml_pert)

        # AM02.1 §3.A.3: per-risk Mode-conditioned + Mode-independent CI
        # populated from compute_per_risk_criticality. AM10 (WIND-01 A4):
        # the divergence_flag field is DROPPED from the contract - under the
        # pure-MC AM basis (apply_mode_multipliers=False, WIND-01) the two
        # CIs coincide, so the flag was structurally constant "consistent"
        # and is the same vacuous-field defect the Mode-pie removal targeted.
        # metrics.divergence_flag() is retained dormant for WIND-01b.
        per_risk_crit = am_metrics.per_risk_criticality.get(rid, {})
        cond_ci = per_risk_crit.get("criticality_conditioned")
        indep_ci = per_risk_crit.get("criticality_independent")

        # AM04: sample-based per-risk tornado sigma (working days). null for
        # any risk outside the evaluated set (not in the dict) and for a
        # risk whose leave-one-out re-run was skipped (NaN); the dashboard
        # falls back to the PERT proxy tornado_sigma_days for those rows.
        sample_sigma_raw = am_metrics.tornado_sample_sigma_days_per_risk.get(rid)
        if sample_sigma_raw is None or math.isnan(float(sample_sigma_raw)):
            tornado_sample_sigma_days: float | None = None
        else:
            tornado_sample_sigma_days = round(float(sample_sigma_raw), 2)

        rows.append({
            "risk_id": rid,
            "title": ws.get("risk_title") or rid,
            "context": ws.get("notes_this_period") or "",
            "days_at_risk_p80": round(days_at_risk, 1),
            "owner": ws.get("owner") or "Unassigned",
            "status": (ws.get("status_this_period") or "Open").lower(),
            "probability": round(effective_probability, 4),
            "impact_days_emv": round(impact_days_emv, 1),
            "criticality_conditioned": cond_ci,
            "criticality_independent": indep_ci,
            # AM10: divergence_flag removed from the contract (see above).
            "ssi": round(float(am_metrics.ssi_per_risk.get(rid, 0.0)), 4),
            "cruciality_proxy_p80": round(cruciality_proxy, 4),
            "mode": (ps.new_mode if ps and ps.new_mode else str(driver.mode)),
            "cg_code": None,
            "tornado_sigma_days": round(
                float(am_metrics.tornado_sigma_days_per_risk.get(rid, 0.0)), 2
            ),
            "tornado_sample_sigma_days": tornado_sample_sigma_days,
        })

    rows.sort(key=lambda r: r["days_at_risk_p80"], reverse=True)
    return rows


def _build_mitigations(
    *,
    workbook_data: WorkbookData,
    am_metrics: AMMetrics,
    project_start: _dt.date,
    baseline_p80_hours: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in workbook_data.mitigations:
        mit_id = m.get("mitigation_id")
        if mit_id is None:
            continue
        days_saved = float(
            am_metrics.counterfactual_days_saved_p80_per_mitigation.get(str(mit_id), 0.0)
        )
        p80_with_mit_hours = max(0.0, baseline_p80_hours - days_saved * HOURS_PER_DAY)
        p80_with_mit_date = _working_days_to_calendar_date(
            project_start, p80_with_mit_hours / HOURS_PER_DAY,
        )
        rows.append({
            "mitigation_id": mit_id,
            "risk_id": m.get("risk_id"),
            "description": m.get("description"),
            "cost_aud": m.get("cost_aud"),
            "lead_time_weeks": m.get("lead_time_weeks"),
            "owner": m.get("owner"),
            "status": (m.get("status") or "").lower(),
            "days_saved_p80": round(days_saved, 1),
            "p80_finish_with_mitigation": _isoformat_date(p80_with_mit_date),
        })
    rows.sort(key=lambda r: r["days_saved_p80"], reverse=True)
    return rows


def _build_activities(
    *,
    am_metrics: AMMetrics,
    p_band_method: str,
    top_n: int,
    ci_threshold: float,
    schedule_result: Any,
    risk_drivers: dict[str, RiskDriver],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for ab in am_metrics.per_activity_p_bands:
        items.append({
            "activity_id": ab.activity_id,
            "name": ab.name,
            "p10_start_days": ab.p10_start_days,
            "p50_start_days": ab.p50_start_days,
            "p90_start_days": ab.p90_start_days,
            "p10_finish_days": ab.p10_finish_days,
            "p50_finish_days": ab.p50_finish_days,
            "p90_finish_days": ab.p90_finish_days,
            "det_es_days": ab.det_es_days,
            "det_ef_days": ab.det_ef_days,
            "criticality_index": ab.criticality_index,
            # AM02.1 §4.B.1: removed per-activity "mode" (category
            # error - Mode is a per-risk attribute, see Doc 3 v2.3).
        })
    items.sort(key=lambda r: r["criticality_index"], reverse=True)

    # mode_summary: count drivers by mode
    mode_summary: dict[str, int] = {"series": 0, "hybrid": 0, "parallel": 0}
    for d in risk_drivers.values():
        m = str(d.mode).lower()
        if m in mode_summary:
            mode_summary[m] += 1
    mode_summary["total"] = schedule_result.n_act

    # cp_stats: per-activity criticality counts
    n_act = schedule_result.n_act
    ci = schedule_result.criticality_index
    ci_gt_50 = sum(1 for v in ci.values() if v > 0.5)
    ci_gt_80 = sum(1 for v in ci.values() if v > 0.8)
    activities_on_det_cp = len(schedule_result.deterministic_critical_path)
    tf_mean = float(np.mean(schedule_result.total_float_mean_hours))
    tf_std = float(np.std(schedule_result.total_float_mean_hours))

    # AM02.1 §3.A.2: stochastic_cp_additions is a set-difference, not
    # arithmetic. It counts activities the stochastic analysis surfaces
    # as critical (CI > 0.8) which are NOT on the deterministic CP.
    # Pre-fix used (ci_gt_80 - activities_on_det_cp) which produced
    # negative values when the deterministic CP was longer than the
    # CI>0.8 cohort (real Stage 3 case for the engagement V8: 91 det CP
    # activities vs 16 with CI > 80%, so the old formula gave -75).
    det_cp_set = set(schedule_result.deterministic_critical_path)
    high_ci_set = {act_id for act_id, ci_val in ci.items() if ci_val > 0.8}
    stochastic_cp_additions = len(high_ci_set - det_cp_set)

    return {
        "top_n_by_ci": top_n,
        "ci_threshold": ci_threshold,
        "p_band_derivation_method": p_band_method,
        "items": items,
        "mode_summary": mode_summary,
        "cp_stats": {
            "activities_on_det_cp": activities_on_det_cp,
            "activities_ci_gt_50": ci_gt_50,
            "activities_ci_gt_80": ci_gt_80,
            "stochastic_cp_additions": stochastic_cp_additions,
            "longest_path_p80_days": round(
                float(np.percentile(schedule_result.project_finish_hours, 80))
                / HOURS_PER_DAY, 1
            ),
            "zero_float_activities": sum(
                1 for v in schedule_result.total_float_mean_hours if v == 0.0
            ),
            "mean_activity_float_days": round(tf_mean / HOURS_PER_DAY, 1),
            "float_sigma_days": round(tf_std / HOURS_PER_DAY, 1),
        },
    }


def _build_distribution(
    *,
    project_finish_hours: np.ndarray,
    project_start: _dt.date,
    deterministic_finish_hours: float,
) -> dict[str, Any]:
    pf_days = project_finish_hours / HOURS_PER_DAY
    det_days = float(deterministic_finish_hours) / HOURS_PER_DAY

    # S-curve: 21 points from 0% to 100%
    probs = np.linspace(0.0, 1.0, 21)
    s_curve_points = [
        {
            "date": _isoformat_date(_working_days_to_calendar_date(
                project_start, float(np.quantile(pf_days, p))
            )),
            "cumulative_prob": round(float(p), 2),
        }
        for p in probs
    ]

    # Histogram bins: 20 bins between min and max
    hist, edges = np.histogram(pf_days, bins=20)
    histogram_bins = [
        {
            "date_range_start": _isoformat_date(
                _working_days_to_calendar_date(project_start, float(edges[i]))
            ),
            "date_range_end": _isoformat_date(
                _working_days_to_calendar_date(project_start, float(edges[i + 1]))
            ),
            "count": int(hist[i]),
        }
        for i in range(len(hist))
    ]

    # Percentile table
    #
    # delta_vs_det is CALENDAR days, matching _build_headline's
    # p*_days_behind_plan and the ``date`` column beside it. Before AM11 it
    # subtracted working days (``d - det_days``) while the date column was
    # calendar-converted, so a single row mixed two clocks and the analyst
    # view read 1.4x lower than the PM headline for the same finish date.
    # Doc 3's worked example is authoritative: delta_vs_det equals
    # p*_days_behind_plan at every shared percentile.
    det_cal = _working_days_to_calendar_date(project_start, det_days)
    percentile_table = []
    for p in (10, 25, 50, 75, 80, 90, 95):
        d = float(np.percentile(pf_days, p))
        cal = _working_days_to_calendar_date(project_start, d)
        delta_vs_det = int((cal - det_cal).days)
        percentile_table.append({
            "percentile": p,
            "days_from_start": round(d, 1),
            "date": _isoformat_date(cal),
            "delta_vs_det": delta_vs_det,
        })

    return {
        "s_curve_points": s_curve_points,
        "histogram_bins": histogram_bins,
        "percentile_table": percentile_table,
    }


def _delta_change_meta(prev_r: dict[str, Any], curr_r: dict[str, Any]) -> str:
    """Deterministic change annotation from status / probability / days-at-risk.

    Probability clause appears only when the effective period probability
    actually moved (AM08 Part B surfaces the effective value); status clause
    only on a transition. Days-at-risk clause is always present.
    """
    parts: list[str] = []
    prev_status = str(prev_r.get("status", "") or "").lower()
    curr_status = str(curr_r.get("status", "") or "").lower()
    if prev_status and curr_status and prev_status != curr_status:
        parts.append(f"Status {prev_status} -> {curr_status}")
    prev_p = prev_r.get("probability")
    curr_p = curr_r.get("probability")
    if (prev_p is not None and curr_p is not None
            and abs(float(prev_p) - float(curr_p)) >= 0.005):
        parts.append(f"probability {float(prev_p):.2f} -> {float(curr_p):.2f}")
    prev_d = max(0.0, float(prev_r.get("days_at_risk_p80", 0.0) or 0.0))
    curr_d = max(0.0, float(curr_r.get("days_at_risk_p80", 0.0) or 0.0))
    parts.append(f"{prev_d:.1f} -> {curr_d:.1f} days at risk")
    return "; ".join(parts)


def _delta_net_summary(
    delta_days: int,
    worse: list[dict[str, Any]],
    better: list[dict[str, Any]],
) -> str:
    """Base movement sentence plus deterministic driver attribution.

    Reads like the Doc 3 example ("Increase led by X, partially offset by Y")
    while preserving risk-id casing. Names up to the top-3 drivers each side.
    """
    direction = (
        "later" if delta_days > 0 else "earlier" if delta_days < 0 else "unchanged"
    )
    sentence = f"P80 forecast moved {delta_days} days {direction}."
    worse_ids = ", ".join(e["risk_id"] for e in worse[:3])
    better_ids = ", ".join(e["risk_id"] for e in better[:3])
    if delta_days > 0:
        primary = f"Increase led by {worse_ids}" if worse_ids else ""
        secondary = f"partially offset by {better_ids}" if better_ids else ""
    elif delta_days < 0:
        primary = f"Improvement led by {better_ids}" if better_ids else ""
        secondary = f"partially offset by {worse_ids}" if worse_ids else ""
    else:
        primary = (
            f"Offsetting moves: {worse_ids} worse, {better_ids} better"
            if (worse_ids or better_ids) else ""
        )
        secondary = ""
    tail = ", ".join(p for p in (primary, secondary) if p)
    if tail:
        sentence += " " + tail + "."
    return sentence


def _build_delta(
    *,
    headline: dict[str, Any],
    current_risks: list[dict[str, Any]],
    previous_period_path: Path | None,
) -> dict[str, Any]:
    if previous_period_path is None:
        return {"period_0": True, "note": "First period; no prior data for delta"}
    try:
        with previous_period_path.open("r", encoding="utf-8") as fh:
            prev = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Could not load previous-period JSON at %s: %s; delta skipped",
            previous_period_path, exc,
        )
        return {"period_0": False, "note": "Previous JSON unreadable; delta skipped"}
    prev_p80 = prev.get("headline", {}).get("p80_finish")
    if prev_p80 is None:
        return {"period_0": False, "note": "Previous JSON missing p80_finish"}
    prev_p80_date = _dt.date.fromisoformat(prev_p80)
    curr_p80_date = _dt.date.fromisoformat(headline["p80_finish"])
    delta_days = int((curr_p80_date - prev_p80_date).days)

    # Per-risk attribution from days_at_risk_p80 movement (AM08 / AIA-01).
    # days_at_risk_p80 tracks the effective period probability, so it is the
    # override-aware signal even for a risk whose displayed probability did not
    # move. Threshold T suppresses moves within the 10k days-at-risk precision
    # floor (see DELTA_ATTRIBUTION_THRESHOLD_DAYS). Values are floored at 0 to
    # match the risk-table clamp (Part B) so a closed risk's residual noise does
    # not leak into the attribution arithmetic.
    prev_by_id = {r["risk_id"]: r for r in prev.get("risks", [])}
    curr_ids = {r["risk_id"] for r in current_risks}
    t = DELTA_ATTRIBUTION_THRESHOLD_DAYS
    worse: list[dict[str, Any]] = []
    better: list[dict[str, Any]] = []
    new: list[dict[str, Any]] = []

    for curr_r in current_risks:
        rid = curr_r["risk_id"]
        curr_d = max(0.0, float(curr_r.get("days_at_risk_p80", 0.0) or 0.0))
        title = curr_r.get("title") or rid
        prev_r = prev_by_id.get(rid)
        if prev_r is None:
            new.append({
                "risk_id": rid, "description": title,
                "change_meta": f"New this period; {curr_d:.1f} days at risk",
                "delta_days": round(curr_d, 1),
            })
            continue
        prev_d = max(0.0, float(prev_r.get("days_at_risk_p80", 0.0) or 0.0))
        curr_status = str(curr_r.get("status", "") or "").lower()
        prev_status = str(prev_r.get("status", "") or "").lower()
        if curr_status == "closed" and prev_status != "closed":
            better.append({
                "risk_id": rid, "description": title,
                "change_meta": f"Closed this period; was {prev_d:.1f} days at risk",
                "delta_days": round(-prev_d, 1),
            })
            continue
        move = curr_d - prev_d
        if move >= t:
            worse.append({
                "risk_id": rid, "description": title,
                "change_meta": _delta_change_meta(prev_r, curr_r),
                "delta_days": round(move, 1),
            })
        elif move <= -t:
            better.append({
                "risk_id": rid, "description": title,
                "change_meta": _delta_change_meta(prev_r, curr_r),
                "delta_days": round(move, 1),
            })

    # Risks present last period but absent this period (removed from the run).
    for rid, prev_r in prev_by_id.items():
        if rid in curr_ids:
            continue
        prev_d = max(0.0, float(prev_r.get("days_at_risk_p80", 0.0) or 0.0))
        if prev_d >= t:
            better.append({
                "risk_id": rid, "description": prev_r.get("title") or rid,
                "change_meta": f"Removed this period; was {prev_d:.1f} days at risk",
                "delta_days": round(-prev_d, 1),
            })

    # Sort by magnitude, cap 3 each side, degrade to actual count (D3).
    worse.sort(key=lambda e: e["delta_days"], reverse=True)
    better.sort(key=lambda e: e["delta_days"])
    worse = worse[:3]
    better = better[:3]

    return {
        "p80_delta_days": delta_days,
        "p80_previous": prev_p80,
        "p80_current": headline["p80_finish"],
        "worse": worse,
        "better": better,
        "new": new,
        "net_movement_summary": _delta_net_summary(delta_days, worse, better),
    }


def _build_trend(*, data_dir: Path, current_p80: str, current_period_end: str) -> dict[str, Any]:
    """Last 5 prior periods + current."""
    periods: list[dict[str, str]] = []
    if data_dir.is_dir():
        prior = sorted(
            p for p in data_dir.glob("period_*.json")
            if not p.name.endswith(f"_{current_period_end.replace('-', '')}.json")
        )
        for p in prior[-4:]:
            try:
                with p.open("r", encoding="utf-8") as fh:
                    d = json.load(fh)
                periods.append({
                    "period_end": d["meta"]["period_end_date"],
                    "p80_finish": d["headline"]["p80_finish"],
                })
            except (OSError, json.JSONDecodeError, KeyError):
                continue
    periods.append({"period_end": current_period_end, "p80_finish": current_p80})
    return {"periods": periods}


def _build_integrated(result: Any) -> dict[str, Any]:
    """Stage 7 part B: the `integrated` block (contract 1.4, decision C2).

    Percentiles of the integrated dollars distribution, plus the two marginals it was built
    from and the pinning that conditioned them. The day rate and the deterministic baseline are
    carried so a reader can reproduce the arithmetic rather than take the total on trust: the
    integrated array IS ``cost + delay_days * day_rate``, and every input to that is here.
    """
    def _pct(arr, p: int) -> float:
        return round(float(np.percentile(arr, p)), 2)

    from src.integrated.run_config_contract import require_day_rate

    integrated = result.integrated_dollars_array
    return {
        "basis": "cost + dollarised schedule delay, with risk states pinned from the status workbook on both arms",
        # Re-asserted at the point of PUBLICATION, not merely at the point of calculation. The
        # rate has already been through require_day_rate upstream, so this cannot fire in
        # practice - but DAYRATE-02's contract is that every day-rate read in src/ goes through
        # that call, and the read which writes the number into a client-facing artefact is the
        # last place to make an exception.
        "day_rate": round(require_day_rate(
            result.day_rate, caller="json_writer._build_integrated"), 2),
        "deterministic_baseline_days": round(float(result.deterministic_baseline_days), 3),
        "iterations": int(result.iterations),
        "p50_dollars": _pct(integrated, 50),
        "mean_dollars": round(float(np.mean(integrated)), 2),
        "p80_dollars": _pct(integrated, 80),
        "p90_dollars": _pct(integrated, 90),
        "p95_dollars": _pct(integrated, 95),
        "cost_marginal": {
            "mean_dollars": round(float(np.mean(result.cost_dollars_array)), 2),
            "p80_dollars": _pct(result.cost_dollars_array, 80),
        },
        "schedule_marginal": {
            "mean_delay_days": round(float(np.mean(result.schedule_days_array)), 3),
            "p80_delay_days": _pct(result.schedule_days_array, 80),
        },
        "pinning": {
            "risks_priced": int(result.pinning.n_priced),
            "risks_removed": int(result.pinning.n_removed),
            "risks_closed": int(result.pinning.n_closed),
            "risks_reprobabilised": int(result.pinning.n_reprobabilised),
            "removed_risk_ids": list(result.pinning.removed_risk_ids),
            "closed_risk_ids": list(result.pinning.closed_risk_ids),
            "reprobabilised_risk_ids": list(result.pinning.reprobabilised_risk_ids),
        },
    }


def _build_audit(
    *,
    config: dict[str, Any],
    methodology_notes: list[dict[str, Any]],
    stage_brief: str,
) -> dict[str, Any]:
    return {
        "config": config,
        "calibration_gates": [],  # Populated by future briefs; v1 emits empty
        # AM08: append the disclosed delta-attribution presentation threshold.
        "methodology_notes": list(methodology_notes) + [_DELTA_ATTRIBUTION_NOTE],
        "stage_brief": stage_brief,
        "reviewer": None,
        "reviewer_approved_date": None,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Date-only ISO format (YYYY-MM-DD) for all date fields in the contract.
# Datetime fields like engine_run_date are validated separately via a
# slightly looser ISO 8601 regex that allows the T...Z suffix.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?$")

# Field names whose value is an ISO 8601 datetime (not a date).
_DATETIME_FIELD_NAMES = frozenset({"engine_run_date"})


def _walk_assert_dates(obj: Any, path: str = "") -> None:
    """Walk the JSON; assert any date-like string is well-formed ISO.

    Date-only fields must match YYYY-MM-DD. Datetime fields named in
    ``_DATETIME_FIELD_NAMES`` must match ISO 8601 with a T separator
    and optional Z suffix.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and any(
                k.endswith(suffix) for suffix in ("_finish", "_date", "_start", "_end")
            ) and "behind" not in k and "delta" not in k:
                if k in _DATETIME_FIELD_NAMES:
                    if not _ISO_DATETIME_RE.match(v):
                        raise JsonWriterError(
                            f"Validation rule 1: {path}.{k} = {v!r} is not "
                            f"ISO 8601 datetime"
                        )
                elif not _ISO_DATE_RE.match(v):
                    raise JsonWriterError(
                        f"Validation rule 1: {path}.{k} = {v!r} is not "
                        f"YYYY-MM-DD ISO format"
                    )
            _walk_assert_dates(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_assert_dates(v, f"{path}[{i}]")


def _validate(doc: dict[str, Any]) -> None:
    """Apply Doc 3 v2.2 §"Validation requirements" rules 1-11."""
    # Rule 1: ISO dates
    _walk_assert_dates(doc)

    # Rule 2: probabilities 0-1
    for r in doc.get("risks", []):
        p = r.get("probability")
        if p is not None and not (0.0 <= p <= 1.0):
            raise JsonWriterError(
                f"Validation rule 2: risk {r.get('risk_id')} probability "
                f"{p} not in [0, 1]"
            )

    # Rule 4: risks sorted by days_at_risk_p80 desc
    risks = doc.get("risks", [])
    if risks:
        days = [r["days_at_risk_p80"] for r in risks]
        if days != sorted(days, reverse=True):
            raise JsonWriterError(
                "Validation rule 4: risks not sorted by days_at_risk_p80 desc"
            )

    # Rule 5: mitigations sorted by days_saved_p80 desc
    mits = doc.get("mitigations", [])
    if mits:
        ds = [m["days_saved_p80"] for m in mits]
        if ds != sorted(ds, reverse=True):
            raise JsonWriterError(
                "Validation rule 5: mitigations not sorted by days_saved_p80 desc"
            )

    # Rule 6: activities.items sorted by criticality_index desc
    items = doc.get("activities", {}).get("items", [])
    if items:
        cs = [i["criticality_index"] for i in items]
        if cs != sorted(cs, reverse=True):
            raise JsonWriterError(
                "Validation rule 6: activities.items not sorted by "
                "criticality_index desc"
            )

    # Rule 7: engine_run_hash uuid-like
    h = doc.get("meta", {}).get("engine_run_hash", "")
    try:
        uuid.UUID(h)
    except (ValueError, AttributeError):
        raise JsonWriterError(
            f"Validation rule 7: engine_run_hash {h!r} is not a UUID"
        ) from None

    # Rule 8: p_band_derivation_method
    method = doc.get("activities", {}).get("p_band_derivation_method")
    if method not in ("A", "B", "C"):
        raise JsonWriterError(
            f"Validation rule 8: p_band_derivation_method = {method!r} not in "
            f"{{A, B, C}}"
        )

    # Rule 9: methodology_notes present when method in B/C
    if method in ("B", "C"):
        notes = doc.get("audit", {}).get("methodology_notes", [])
        if not any(
            n.get("topic") == "per_activity_p_bands" and n.get("method") == method
            for n in notes
        ):
            raise JsonWriterError(
                f"Validation rule 9: methodology_notes missing required entry "
                f"for topic='per_activity_p_bands' method={method!r}"
            )

    # Rules 10 & 11: per-item monotonicity + non-negativity
    for it in items:
        for prefix in ("start", "finish"):
            p10 = it[f"p10_{prefix}_days"]
            p50 = it[f"p50_{prefix}_days"]
            p90 = it[f"p90_{prefix}_days"]
            if not (p10 <= p50 <= p90):
                raise JsonWriterError(
                    f"Validation rule 10: activity {it['activity_id']} "
                    f"{prefix} P-band not monotonic: P10={p10} P50={p50} P90={p90}"
                )
            for v in (p10, p50, p90):
                if v < 0:
                    raise JsonWriterError(
                        f"Validation rule 11: activity {it['activity_id']} "
                        f"{prefix} {v} is negative"
                    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def write_period_json(
    *,
    conditional_result: ConditionalRunResult,
    am_metrics: AMMetrics,
    workbook_data: WorkbookData,
    risk_drivers: dict[str, RiskDriver],
    project_start: _dt.date,
    deterministic_finish_hours: float,
    workbook_filename: str,
    xer_filename: str,
    output_dir: Path,
    period_end_date: _dt.date,
    previous_period_end_date: _dt.date | None,
    engine_run_date: _dt.datetime,
    register_version: str = "register",
    project_key: str | None = None,
    project_display_name: str | None = None,
    iterations: int | None = None,
    seed: int | None = None,
    seed_source: str | None = None,
    p_band_method: str = "B",
    top_n: int = 10,
    ci_threshold: float = 0.05,
    stage_brief: str = "Period status run",
    engine_provenance: dict[str, Any] | None = None,
    integrated_result: Any | None = None,
    integrated_unavailable_reason: str | None = None,
) -> Path:
    """Compose, validate, and write the period JSON.

    Returns the path of the written file (``data/period_YYYYMMDD.json``).
    """
    schedule_result = conditional_result.schedule_result
    iters = iterations or schedule_result.n_iter
    sd = require_seed(seed if seed is not None else schedule_result.seed_used,
                      where="src.am.json_writer.write_period_json")

    meta = _build_meta(
        workbook_data=workbook_data,
        workbook_filename=workbook_filename,
        xer_filename=xer_filename,
        register_version=register_version,
        iterations=iters,
        seed=sd,
        seed_source=seed_source,
        period_end_date=period_end_date,
        previous_period_end_date=previous_period_end_date,
        project_key=project_key,
        engine_run_date=engine_run_date,
        project_display_name=project_display_name,
        engine_provenance=engine_provenance,
    )
    headline = _build_headline(
        project_finish_hours=schedule_result.project_finish_hours,
        project_start=project_start,
        deterministic_finish_hours=deterministic_finish_hours,
        workbook_data=workbook_data,
    )

    baseline_p80_hours = float(
        np.percentile(schedule_result.project_finish_hours, 80)
    )
    baseline_p80_days = baseline_p80_hours / HOURS_PER_DAY

    risks = _build_risks(
        pinned_states=conditional_result.pinned_states,
        risk_drivers=risk_drivers,
        workbook_data=workbook_data,
        am_metrics=am_metrics,
        project_finish_p80_days=baseline_p80_days,
    )
    mitigations = _build_mitigations(
        workbook_data=workbook_data,
        am_metrics=am_metrics,
        project_start=project_start,
        baseline_p80_hours=baseline_p80_hours,
    )
    activities = _build_activities(
        am_metrics=am_metrics,
        p_band_method=p_band_method,
        top_n=top_n,
        ci_threshold=ci_threshold,
        schedule_result=schedule_result,
        risk_drivers=risk_drivers,
    )
    distribution = _build_distribution(
        project_finish_hours=schedule_result.project_finish_hours,
        project_start=project_start,
        deterministic_finish_hours=deterministic_finish_hours,
    )

    # Find previous-period JSON for delta.
    output_dir.mkdir(parents=True, exist_ok=True)
    period_filename = f"period_{period_end_date.strftime('%Y%m%d')}.json"
    period_path = output_dir / period_filename
    prior_jsons = sorted(
        p for p in output_dir.glob("period_*.json") if p.name < period_filename
    )
    previous_period_path = prior_jsons[-1] if prior_jsons else None

    delta = _build_delta(
        headline=headline,
        current_risks=risks,
        previous_period_path=previous_period_path,
    )
    trend = _build_trend(
        data_dir=output_dir,
        current_p80=headline["p80_finish"],
        current_period_end=meta["period_end_date"],
    )

    audit = _build_audit(
        config={
            "engine": "SRA Stage 3 CPM-replay",
            "iterations": iters,
            "sampling_method": "Joint severity uniforms (cost + schedule)",
            # True of BOTH arms since stage 7 part B: the integrated cost arm consumes
            # the schedule run's own severity uniforms. Before the part B review it was
            # stamped beside a cost arm that drew independently, which made this line an
            # attestation to something the artefact did not do.
            "seed": sd,
            "cp_rule": "Option Z Hybrid",
            "p_level_reporting": 80,
            "cl_mode": "Mode-conditioned" if conditional_result.config_summary.get(
                "criticality_measurement_mode") in ("mode_conditioned", "both")
                else "Mode-independent",
        },
        methodology_notes=am_metrics.methodology_notes,
        stage_brief=stage_brief,
    )

    doc = {
        "schema_version": SCHEMA_VERSION,
        "meta": meta,
        "headline": headline,
        "trend": trend,
        "risks": risks,
        "mitigations": mitigations,
        "activities": activities,
        "distribution": distribution,
        "delta": delta,
        "audit": audit,
    }

    # Contract 1.4, decision C2: OPTIONAL, so absence is valid rather than malformed. When
    # the arm could not run, the reason is recorded in `audit` rather than the block being
    # silently missing - absent-and-unexplained is the state this repository keeps finding
    # and calling a defect.
    if integrated_result is not None:
        doc["integrated"] = _build_integrated(integrated_result)
    elif integrated_unavailable_reason:
        audit["integrated_unavailable"] = integrated_unavailable_reason

    _validate(doc)

    # JSONEOL-01: pin the served bytes to LF. Without an explicit newline
    # Python translates to os.linesep, so the same document is CRLF on the XPS
    # and LF on the Mac - the machine-dependence PROVCRLF01 removed from the
    # input digests, left standing on the output.
    with period_path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    logger.info("Wrote %s (%d bytes)", period_path, period_path.stat().st_size)
    return period_path
