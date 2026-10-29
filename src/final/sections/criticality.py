"""Criticality section builder.

Page 4b (in-main-report short summary) + sibling criticality-note
dict assembly. Hosts the SR10.A / SR10.B / Beta-12 / Beta-18 /
Beta-19 / Beta-19b plumbing — extended CI table, risk-to-CP linkage
table, near-critical activities, auto-mapper audit, Charts 1-4 PNG
generators (delegated to ``src.final.charts``), Stage 3 Beta
path-crossover delta.

The two orchestrators :func:`_apply_stage3_beta_keys` and
:func:`_apply_criticality_keys` mutate the ``composed`` dict in
place — they are the Stage 2.5 composer's call path. SR14b can call
them on a fresh empty dict to obtain a pure-data section dict, or wrap
the inner pure functions (``compute_extended_ci_table``,
``build_risk_to_cp_linkage_table``, ``compute_criticality_table``,
``pick_near_critical_activities``, ``compute_ci_distribution_summary``,
``build_risk_to_activity_bridge``) directly.

Moved here under SR14a.2 (session B) from ``src/final/composer.py``
(constants ``PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS`` +
``_SR10B_DEFAULT_WORKING_HOURS_PER_DAY``; eighteen helpers /
orchestrators listed above). Composer re-exports every public symbol
at module level so the ~30+ existing test sites that import private
composer helpers keep working without churn.

Decision D3=A: per-key narrative substitutions inside
:func:`_apply_criticality_keys` continue to read templates from
``src.final.commentary_text`` and the ``executive_summary``
formatters — Stage 2.5 narrative stays in the Stage 2.5 composer's
control flow. SR14b's Stage 3 standalone composer will replicate
the same dict-mutation pattern with its own templates / call site.

Brief §4.3 short-summary scope
------------------------------
The Stage 2.5 main report renders a 5-row near-critical table + a
chart-2 placeholder + the §10.5 risk-to-CP linkage prose. The full
detail (10-row table, Charts 1+3+4, risk-to-activity bridge) lives
in the sibling criticality-note. Both surfaces are produced by
:func:`_apply_criticality_keys` here; SR14b retires the sibling.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.final import commentary_text


# SR18 Item 4: source .xer activity names carry inconsistent internal
# whitespace (e.g. "Ready for Hot Commissioning  - GTU12" with a double
# space before the hyphen). Apply at every activity_name injection
# point so the rendered docx / HTML / chart text is uniform. The .xer
# itself stays untouched (read-only); transformation is at the use site.
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _normalise_activity_name(name: Any) -> str:
    if name is None:
        return ""
    return _WHITESPACE_RUN_RE.sub(" ", str(name)).strip()


logger = logging.getLogger(__name__)


PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS = 30.0


def _apply_stage3_headline(composed: dict[str, Any], stage3_beta_result: dict[str, Any]) -> None:
    """Put the Stage 3 headline on ``composed`` and mark the Mode range as a comparator.

    ``composed["executive_summary"]["headline_stage3"]`` is the block the deliverable leads
    with. ``["headline_contingency_range_p80"]`` is left in place for the Stage 2.5 comparator
    table beside the reconciliation (Director D-2) and gains a ``basis`` saying so.
    """
    from src.final.headline import STAGE3_SCENARIO_NAME, stage3_headline

    # Absence is recorded, not raised, here: section builders and tests hand this function
    # partial dicts. The production seam, ``deliverable.compose``, refuses a composed dict
    # whose headline is absent, so a real run cannot ship without one.
    summary = composed.setdefault("executive_summary", {})
    integrated_section = composed.get("integrated_section") or {}
    day_rate = integrated_section.get("day_rate")
    cost_arr = np.asarray(stage3_beta_result.get("cost_dollars_array", []))
    sched_arr = np.asarray(stage3_beta_result.get("schedule_days_array", []))
    absent = None
    if day_rate is None:
        absent = "composed['integrated_section'] carries no day_rate"
    elif cost_arr.size == 0 or sched_arr.size == 0:
        absent = "stage3_beta_result carries no cost_dollars_array / schedule_days_array"
    if absent is not None:
        summary["headline_stage3"] = None
        summary["headline_stage3_absent_reason"] = absent
        return
    p_level = int(integrated_section.get("p_level", 80))
    legacy = summary.get("headline_contingency_range_p80")
    # The run's headline metric is what the composer resolved for the whole document
    # (composed["headline_metric"], set by _apply_headline_metric before this runs); the
    # legacy range dict always says P80 (review W5).
    headline_metric = composed.get("headline_metric") or (legacy or {}).get("headline_metric", "P80")
    # INTSCURVE-01 (D-2): P50 / P80 / P90 everywhere, P95 supporting. Adds the P90 row; no
    # existing figure moves.
    from src.final.sections.integrated_total import INTEGRATED_P_LEVELS
    summary["headline_stage3"] = stage3_headline(
        cost_arr, sched_arr, float(day_rate), p_levels=INTEGRATED_P_LEVELS, p_level=p_level,
        headline_metric=headline_metric,
    )
    if isinstance(legacy, dict):
        # The Stage 3 standalone artefact rewires DP_Review to the Stage 3 arm before composing
        # (stage3_composer), so there the range is not a Stage 2.5 comparator and must not be
        # labelled one (review W6). Detected on the arrays, not on a flag that could be forgotten.
        _dp = (integrated_section.get("scenarios") or {}).get("DP_Review") or {}
        _dp_sched = np.asarray(_dp.get("schedule_days_array", []))
        _rewired = _dp_sched.shape == sched_arr.shape and _dp_sched.size > 0 and np.array_equal(_dp_sched, sched_arr)
        legacy["basis"] = (
            "Stage 3 standalone: DP Review here carries the Stage 3 arm; the range is that arm "
            "against the Stage 2.5 All Series bound, shown for reconciliation, not a Stage 2.5 "
            "comparator" if _rewired else
            "Stage 2.5 comparator: the Mode-scenario range the deliverable published before "
            "STAGE3HEADLINE-01, retained beside the reconciliation, not the headline")
    integrated_section[STAGE3_SCENARIO_NAME.lower()] = {
        "cost_dollars_array": cost_arr,
        "schedule_days_array": sched_arr,
        "risk_ids_all": list(stage3_beta_result.get("risk_ids_all", [])),
        "risk_ids_dual": list(stage3_beta_result.get("risk_ids_dual", [])),
        "iterations": int(stage3_beta_result.get("iterations", cost_arr.size)),
    }


def _compute_path_crossover_delta(
    integrated_results: dict[str, Any],
    stage3_beta_result: dict[str, Any],
    threshold_days: float = PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS,
) -> tuple[float, float, float, bool]:
    """Compute path-crossover delta and WARN flag.

    Returns
    -------
    (stage25_p80, stage3_p80, delta_days, warn)
        stage25_p80 : P80 of integrated_results["schedule_days_array"] - a DELAY
        stage3_p80  : P80 of stage3_beta_result["schedule_days_array"] - also a DELAY.
                      Until STAGE3HEADLINE-01 (D-5, F-40, 10/09/2026) this was the P80
                      of ``schedule_result.project_finish_days``, an ABSOLUTE finish, so
                      the delta subtracted a delay from a finish and the WARN it fed
                      was never about path crossover.
        delta_days  : stage25_p80 - stage3_p80; positive means Stage 3 is lower
                      (Stage 3 finds less schedule risk than the Mode-multiplier
                      Stage 2.5 approach); negative means Stage 3 is higher
                      (path-crossover risk is surfacing through the CPM-replay)
        warn        : abs(delta_days) > threshold_days

    The 30-day default threshold is per Beta-00 §9. WARN does not fail the
    run; it surfaces in the deliverable as a methodology flag.
    """
    s25_arr = np.asarray(integrated_results.get("schedule_days_array", []))
    if s25_arr.size == 0:
        raise ValueError(
            "_compute_path_crossover_delta: integrated_results['schedule_days_array'] "
            "is empty; cannot compute Stage 2.5 P80"
        )
    s3_arr = np.asarray(stage3_beta_result.get("schedule_days_array", []))
    if s3_arr.size == 0:
        raise ValueError(
            "_compute_path_crossover_delta: stage3_beta_result['schedule_days_array'] "
            "is empty; cannot compute the Stage 3 P80 delay. The Beta-06 dict carries "
            "the delay array beside schedule_result (deliverable._stage3_beta_dict)."
        )
    s25_p80 = float(np.percentile(s25_arr, 80))
    s3_p80 = float(np.percentile(s3_arr, 80))
    delta = s25_p80 - s3_p80
    warn = bool(abs(delta) > float(threshold_days))
    return s25_p80, s3_p80, delta, warn


def _render_auto_mapper_audit_table(
    risk_drivers: dict[str, Any],
) -> list[dict[str, Any]]:
    """One row per RiskDriver; rendered in notebook + Word appendix.

    Columns: risk_id, activity_count, pattern_id, injection_method,
    probability, opt_d, ml_d, pess_d, derived_at_run_time,
    workshop_validated. The full per-(risk, activity) detail lives in
    the auto-mapper parquet (referenced via composed["auto_mapper_audit_path"]);
    this table is the summary.
    """
    rows: list[dict[str, Any]] = []
    for risk_id, drv in (risk_drivers or {}).items():
        rows.append(
            {
                "risk_id": str(risk_id),
                "activity_count": len(getattr(drv, "affected_activity_ids", ()) or ()),
                "pattern_id": getattr(drv, "pattern_id", None),
                "injection_method": str(getattr(drv, "injection_method", "")),
                # SR12 — per-risk gating activity surfaced in the §10.5
                # audit table so a reviewer can verify each discrete-
                # event risk points at the methodologically-correct
                # single column. Empty for legacy / multiplicative
                # methods.
                "gating_activity_id": str(
                    getattr(drv, "gating_activity_id", "") or ""
                ),
                "probability": float(getattr(drv, "probability", 0.0) or 0.0),
                "opt_d": float(getattr(drv, "opt_pert", 0.0) or 0.0),
                "ml_d": float(getattr(drv, "ml_pert", 0.0) or 0.0),
                "pess_d": float(getattr(drv, "pess_pert", 0.0) or 0.0),
                "derived_at_run_time": bool(
                    getattr(drv, "derived_at_run_time", False)
                ),
                "workshop_validated": bool(
                    getattr(drv, "workshop_validated", False)
                ),
            }
        )
    return rows


# ----------------------------------------------------------------------------
# SR9 v3.6.1 - Credibility-patch helpers (A5, B1a, B2a, B3)
# ----------------------------------------------------------------------------
# Audit-parquet schema reminder: AutoMapAuditRow carries
#   [risk_id, activity_id, pattern_id, injection_method, opt_pert, ml_pert,
#    pess_pert, probability, derived_at_run_time, workshop_validated].
# Zero-expansion is signalled by a single row per affected risk with
# activity_id == "" (see src/sra/cpm/auto_mapper.py::_audit_rows_for_driver).


def _read_zero_expansion_risk_ids(audit_path: Any) -> list[str] | None:
    """Read the audit parquet at ``audit_path`` and return sorted risk_ids
    whose every row carries ``activity_id == ""`` (the zero-expansion form).

    Returns ``None`` on schema drift / unreadable file - callers degrade
    to "no notice" / "no suppression" rather than raise.
    """
    if not audit_path:
        return None
    try:
        df = pd.read_parquet(audit_path)
    except Exception:
        return None
    if "risk_id" not in df.columns or "activity_id" not in df.columns:
        return None
    zero_mask = df.groupby("risk_id")["activity_id"].apply(
        lambda s: (s == "").all()
    )
    return sorted(zero_mask[zero_mask].index.tolist())


def _build_auto_mapper_zero_expansion_notice(
    stage3_beta_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """A5: notice content for the auto-mapper zero-expansion banner.

    Returns ``None`` when there are no zero-expansion rules, when
    ``stage3_beta_result`` is missing, or when the audit parquet is
    unreadable. Callers render the ``paragraph`` field above the
    Stage 3 Beta comparison table and in the corresponding Word doc
    section.
    """
    if not stage3_beta_result:
        return None
    audit_path = stage3_beta_result.get("auto_mapper_audit_path")
    zero_risk_ids = _read_zero_expansion_risk_ids(audit_path)
    if not zero_risk_ids:
        return None
    try:
        df = pd.read_parquet(audit_path)
        n_total = int(df["risk_id"].nunique())
    except Exception:
        n_total = len(zero_risk_ids)
    return {
        "n_zero": len(zero_risk_ids),
        "n_total": n_total,
        "zero_risk_ids": zero_risk_ids,
        "paragraph": (
            f"**Auto-mapper zero-expansion notice.** "
            f"{len(zero_risk_ids)} of {n_total} risk drivers "
            f"({', '.join(zero_risk_ids)}) currently bind to zero activities "
            f"under the strawman's pattern-based auto-mapper. Stage 3 Beta "
            f"figures for these drivers should be treated as un-validated "
            f"until workshop-defined per-(risk, activity) bindings replace "
            f"the auto-mapper. See Stage 3 roadmap §5. The Stage 2.5 "
            f"production headline above is unaffected by this notice."
        ),
    }


def _stage3_beta_unmapped_top_drivers(
    stage3_beta_result: dict[str, Any] | None,
    top3_schedule_driver_ids: list[str] | tuple[str, ...] | None,
) -> set[str]:
    """B1a: subset of ``top3_schedule_driver_ids`` with zero activity
    bindings under the auto-mapper.

    Returns the empty set when nothing is unmapped, when inputs are
    missing, or when the audit parquet is unreadable. Empty set means
    safe to display the Stage 3 Beta P80 numerically; non-empty set
    triggers the suppression render.
    """
    if not stage3_beta_result or not top3_schedule_driver_ids:
        return set()
    audit_path = stage3_beta_result.get("auto_mapper_audit_path")
    zero_risk_ids = _read_zero_expansion_risk_ids(audit_path)
    if not zero_risk_ids:
        return set()
    return set(zero_risk_ids) & set(top3_schedule_driver_ids)


# _dedupe_scenarios_by_signature: moved to src.final.sections.page1_table under SR14a.2;
# re-exported above.




# _build_dedup_footnote: moved to src.final.sections.page1_table under SR14a.2;
# re-exported above.




def _run_activity_count(stage3_beta_result: dict[str, Any] | None) -> int:
    """How many activities the replayed schedule has.

    PRESENT-01 (D-5): the over-bind classification's denominator. It is the run's own count,
    never defaulted - a borrowed schedule size silently changes which risks the narrative calls
    over-bound. Taken from an explicit ``activity_count`` where the result carries one, and from
    the replayed graph otherwise; a result with neither is refused rather than guessed at.
    """
    result = stage3_beta_result or {}
    declared = result.get("activity_count")
    if declared is not None:
        if int(declared) <= 0:
            raise ValueError(
                f"the Stage 3 result declares activity_count={declared!r}; the over-bind "
                "classification divides by it (PRESENT-01 D-5), so it is refused rather than "
                "silently replaced by the graph's count."
            )
        return int(declared)
    graph = result.get("schedule_graph")
    activities = getattr(graph, "activities", None)
    if not activities:
        raise ValueError(
            "the Stage 3 result carries no schedule graph, so the run's activity count is "
            "unknown; the over-bind classification needs it as a denominator (PRESENT-01 D-5)."
        )
    return len(activities)


def _apply_stage3_beta_keys(
    composed: dict[str, Any],
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    stage3_beta_result: dict[str, Any] | None,
    path_crossover_warn_threshold_days: float = (
        PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS
    ),
    chart_output_dir: Path | None = None,
    risk_titles_override: dict[str, str] | None = None,
) -> None:
    """Populate Stage 3 beta keys on ``composed`` in place.

    No-op when ``stage3_beta_result`` is ``None`` - this preserves the
    Stage 2.5 production output bit-identical (Beta-00 §5 invariant).
    Called from both the v2 and v3 return paths in
    :func:`compose_final_report_data` so the kwarg works regardless of
    whether v3 inputs were supplied.

    Beta-12: when ``stage3_beta_result`` is non-None, also populates
    ``composed["page4b_criticality"]`` from the schedule_result's new
    criticality_index / total_float_* / deterministic_critical_path
    fields. ``chart_output_dir`` is plumbed in so the CI distribution
    chart can be written next to the other v3 chart PNGs; if ``None``,
    the chart is skipped and ``distribution_chart_path`` is left empty.
    """
    if stage3_beta_result is None:
        return
    integrated_dp = integrated_results_by_scenario.get("DP_Review", {})
    s25_p80, s3_p80, delta, warn = _compute_path_crossover_delta(
        integrated_dp,
        stage3_beta_result,
        threshold_days=path_crossover_warn_threshold_days,
    )
    composed["beta_flag"] = True
    composed["stage25_p80_schedule_days"] = s25_p80
    composed["stage3_beta_p80_schedule_days"] = s3_p80
    # STAGE3HEADLINE-01 P1 (Director D-1, 10/09/2026): the headline block is the Stage 3
    # distribution's percentiles, and the arrays it was read from travel in the
    # integrated section so the executive summary and the audit trail carry one source.
    _apply_stage3_headline(composed, stage3_beta_result)
    composed["path_crossover_delta_days"] = delta
    composed["path_crossover_warn"] = warn
    composed["path_crossover_warn_threshold_days"] = float(
        path_crossover_warn_threshold_days
    )

    # SR17 §5.3 — gating-collision note. Composer's _apply_prod_mode_overrides
    # ran BEFORE this function (the Stage 3 wire-up runs LAST so Stage 2.5
    # paths stay bit-identical), so the prod-mode pass cannot see beta_flag
    # and the assignment must happen here. Always assigned when the Stage 3
    # engine ran; renderers gate display on the field being non-empty, and a
    # project whose binding carries no note gets '' (stage 4 F-33).
    from src.final import commentary_text
    page4 = composed.get("page4_schedule_drivers")
    if isinstance(page4, dict):
        page4["gating_collision_note"] = commentary_text.resolve_gating_collision_note()
    composed["auto_mapper_audit_path"] = stage3_beta_result.get(
        "auto_mapper_audit_path"
    )
    composed["stage3_beta_audit_table"] = _render_auto_mapper_audit_table(
        stage3_beta_result.get("risk_drivers", {})
    )

    # SR-S3-Beta-18 §1: auto-mapper interpretation paragraph. Derives
    # the over-bound risk list, the activity-count range, and the
    # Stage 2.5 / Stage 3 Beta P80 contrast from the live audit table
    # and the path-crossover values populated above. Empty string when
    # no over-bound risks exist (degrades cleanly when the auto-mapper
    # ruleset changes or the strawman gains explicit per-(risk, activity)
    # bindings).
    from src.final.executive_summary import (
        format_auto_mapper_audit_interpretation,
    )
    composed["auto_mapper_audit_interpretation"] = (
        format_auto_mapper_audit_interpretation(
            audit_table=composed["stage3_beta_audit_table"],
            stage25_p80_days=s25_p80,
            stage3_p80_days=s3_p80,
            schedule_size=_run_activity_count(stage3_beta_result),
        )
    )

    # SR9 v3.6.1 A5: zero-expansion notice (None if all risks mapped).
    composed["auto_mapper_zero_expansion_notice"] = (
        _build_auto_mapper_zero_expansion_notice(stage3_beta_result)
    )

    # SR9 v3.6.1 B1a: top-3 unmapped detection. The top-3 schedule
    # drivers are populated in composed["page4_schedule_drivers"]
    # ["drivers_table"] earlier in the v3 path (composer.py ~line 2359),
    # before _apply_stage3_beta_keys is called from the v3 site
    # (composer.py ~line 2529). On the early v2 return path the table
    # is absent, so top3_ids degrades to [] and the suppression flag
    # stays False - which is the correct behaviour because the v2
    # return path does not render a Stage 3 Beta comparison anyway.
    drivers_table = (
        composed.get("page4_schedule_drivers", {}).get("drivers_table") or []
    )
    top3_ids = [
        d.get("Risk")
        for d in drivers_table[:3]
        if isinstance(d, dict) and d.get("Risk")
    ]
    unmapped_top3 = _stage3_beta_unmapped_top_drivers(stage3_beta_result, top3_ids)
    composed["path_crossover_display_suppressed"] = bool(unmapped_top3)
    composed["path_crossover_unmapped_top_drivers"] = sorted(unmapped_top3)
    composed["path_crossover_display_message"] = (
        "n/a - top-3 schedule drivers unmapped" if unmapped_top3 else None
    )

    # Beta-12 — activity-level criticality output. Populates
    # composed["page4b_criticality"] consumed by final_runner.ipynb's
    # new section cells and word_generator's _add_criticality_section_v36.
    # Beta-19b item 7a: thread the composer's risk_titles parameter so
    # the criticality linkage table emits real titles instead of falling
    # back to risk_id (the binding doesn't populate
    # stage3_beta_result["risk_titles"]).
    _apply_criticality_keys(
        composed,
        stage3_beta_result,
        chart_output_dir=chart_output_dir,
        risk_titles_override=risk_titles_override,
    )


# ----------------------------------------------------------------------------
# Beta-12: Activity-level criticality output (composer aggregation)
# ----------------------------------------------------------------------------

#: CI band thresholds (Beta-12 §3.2). Activities with CI in
#: ``[lower, upper)`` belong to the named band. Bands are mutually
#: exclusive; CI = 1.0 sits in ``"always (90%+)"``.
CI_BAND_DEFINITIONS = (
    ("never (<10%)", 0.0, 0.10),
    ("rarely (10-30%)", 0.10, 0.30),
    ("near (30-70%)", 0.30, 0.70),
    ("often (70-90%)", 0.70, 0.90),
    ("always (90%+)", 0.90, 1.0 + 1e-9),
)


def _ci_band(ci: float) -> str:
    """Return the band label for a CI value (Beta-12 §3.2)."""
    for label, lower, upper in CI_BAND_DEFINITIONS:
        if lower <= ci < upper:
            return label
    # Defensive fallback — guards against tiny negative/over-1 CI from
    # numerical edge cases. CI is bounded in [0, 1] by construction
    # (count / n_iter), so this branch is unreachable in practice.
    return CI_BAND_DEFINITIONS[-1][0]


def compute_criticality_table(
    schedule_result: Any,
    *,
    activity_titles: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Activity-level CI table built from the Beta-12 schedule_result.

    One row per activity in :attr:`schedule_result.activity_ids` order
    (i.e. graph topological order). Reads
    :attr:`~src.sra.cpm.cpm_simulation.ScheduleMCResult.criticality_index`
    (dict),
    :attr:`~src.sra.cpm.cpm_simulation.ScheduleMCResult.total_float_mean_hours`
    /
    :attr:`~src.sra.cpm.cpm_simulation.ScheduleMCResult.total_float_std_hours`
    (float arrays, precision-typed), and
    :attr:`~src.sra.cpm.cpm_simulation.ScheduleMCResult.deterministic_critical_path`
    (tuple[str, ...]).

    Parameters
    ----------
    schedule_result :
        :class:`~src.sra.cpm.cpm_simulation.ScheduleMCResult`. Duck-typed
        so test fixtures can supply a minimal object with the same field
        surface.
    activity_titles : dict[str, str] | None
        Optional ``activity_id → human name`` lookup; falls back to
        ``activity_id`` when missing. A binding populates this
        from ``graph.activities[*].name``.

    Returns
    -------
    pd.DataFrame
        Columns: ``activity_id``, ``activity_name``, ``ci``, ``ci_band``,
        ``total_float_mean_hours``, ``total_float_std_hours``,
        ``on_deterministic_cp``.
    """
    activity_ids = list(getattr(schedule_result, "activity_ids", ()))
    ci_dict: dict[str, float] = dict(
        getattr(schedule_result, "criticality_index", {}) or {}
    )
    tf_mean = np.asarray(
        getattr(schedule_result, "total_float_mean_hours", np.zeros(0)),
        dtype=np.float64,
    )
    tf_std = np.asarray(
        getattr(schedule_result, "total_float_std_hours", np.zeros(0)),
        dtype=np.float64,
    )
    det_cp = set(getattr(schedule_result, "deterministic_critical_path", ()))
    titles = dict(activity_titles or {})

    rows: list[dict[str, Any]] = []
    for idx, a_id in enumerate(activity_ids):
        ci = float(ci_dict.get(a_id, 0.0))
        rows.append({
            "activity_id": str(a_id),
            # SR18 Item 4: normalise at the upstream source so every
            # downstream consumer (Chart 3, risk-to-CP linkage, bridge
            # table, §10.5 prose) receives whitespace-clean names.
            "activity_name": _normalise_activity_name(titles.get(a_id, a_id)),
            "ci": ci,
            "ci_band": _ci_band(ci),
            "total_float_mean_hours": (
                float(tf_mean[idx]) if idx < len(tf_mean) else float("nan")
            ),
            "total_float_std_hours": (
                float(tf_std[idx]) if idx < len(tf_std) else float("nan")
            ),
            "on_deterministic_cp": a_id in det_cp,
        })

    columns = [
        "activity_id", "activity_name", "ci", "ci_band",
        "total_float_mean_hours", "total_float_std_hours",
        "on_deterministic_cp",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def pick_near_critical_activities(
    ci_table: pd.DataFrame,
    *,
    low: float = 0.20,
    high: float = 0.80,
    top_n: int = 10,
) -> pd.DataFrame:
    """Activities in the ``[low, high]`` CI band, sorted by ``ci`` desc.

    The "near-critical" cut — activities that flip in and out of the
    critical path across simulated futures. Float management here is the
    highest-leverage schedule treatment after risk-driver treatment
    (Beta-12 §3.3 narrative).
    """
    if ci_table.empty:
        return ci_table.copy()
    mask = (ci_table["ci"] >= low) & (ci_table["ci"] <= high)
    filtered = ci_table.loc[mask].sort_values("ci", ascending=False)
    return filtered.head(top_n).reset_index(drop=True)


def build_risk_to_activity_bridge(
    risk_drivers: dict[str, Any],
    ci_table: pd.DataFrame,
    top_schedule_risk_ids: list[str],
    *,
    risk_titles: dict[str, str] | None = None,
    top_n_activities_per_risk: int = 5,
) -> pd.DataFrame:
    """Top-N schedule risk drivers joined to their auto-mapped activities.

    For each risk in ``top_schedule_risk_ids`` (typically the top-3 from
    the Page 4 schedule tornado), emits one row per affected activity
    with the activity's CI and deterministic-CP membership flag. When a
    risk's auto-mapper expansion produced zero activities (current
    common situation where several risks gate on one activity), the bridge emits a
    single placeholder row with ``activity_id == ""`` so the section is
    not empty for that risk — Beta-12 §4 edge case.

    Parameters
    ----------
    risk_drivers : dict[str, RiskDriver]
        From ``stage3_beta_result["risk_drivers"]``. Iterated by lookup
        on ``top_schedule_risk_ids``.
    ci_table : pd.DataFrame
        Output of :func:`compute_criticality_table`.
    top_schedule_risk_ids : list[str]
        Risk ids in priority order (typically top-3 from the schedule
        tornado). The composer call site reads these from
        ``composed["page4_schedule_drivers"]["drivers_table"]``.
    risk_titles : dict[str, str] | None
        Optional ``risk_id → description`` lookup; falls back to
        ``risk_id`` when missing.
    top_n_activities_per_risk : int
        Cap on activities per risk row group. Activities are sorted by
        ``ci`` desc so the most-critical cut surfaces first.

    Returns
    -------
    pd.DataFrame
        Columns: ``risk_id``, ``risk_title``, ``activity_id``,
        ``activity_name``, ``ci``, ``on_deterministic_cp``,
        ``no_activity_bindings`` (bool flag — True only on the
        zero-expansion placeholder row).
    """
    titles = dict(risk_titles or {})
    columns = [
        "risk_id", "risk_title", "activity_id", "activity_name",
        "ci", "on_deterministic_cp", "no_activity_bindings",
    ]
    if not top_schedule_risk_ids or ci_table.empty:
        return pd.DataFrame(columns=columns)

    ci_lookup = ci_table.set_index("activity_id")
    rows: list[dict[str, Any]] = []

    for risk_id in top_schedule_risk_ids:
        risk_id = str(risk_id)
        driver = (risk_drivers or {}).get(risk_id)
        risk_title = titles.get(risk_id, risk_id)
        affected_ids = []
        if driver is not None:
            affected_ids = list(
                getattr(driver, "affected_activity_ids", ()) or ()
            )

        if not affected_ids:
            # Edge case — auto-mapper expanded to zero activities for
            # this risk (Beta-12 §4). Surface a placeholder row so the
            # narrative reads correctly.
            rows.append({
                "risk_id": risk_id,
                "risk_title": str(risk_title),
                "activity_id": "",
                "activity_name": "(no activity bindings under current input mapping)",
                "ci": float("nan"),
                "on_deterministic_cp": False,
                "no_activity_bindings": True,
            })
            continue

        # Resolve each affected activity's CI from the table; activities
        # not present in the CI lookup (shouldn't happen, but defensive)
        # are skipped silently.
        per_risk_rows: list[dict[str, Any]] = []
        for a_id in affected_ids:
            if a_id not in ci_lookup.index:
                continue
            ci_row = ci_lookup.loc[a_id]
            per_risk_rows.append({
                "risk_id": risk_id,
                "risk_title": str(risk_title),
                "activity_id": str(a_id),
                # SR18 Item 4 defensive: compute_criticality_table
                # already normalises upstream, but the bridge may be
                # built from CI tables produced by other callers in
                # future. Idempotent re-application is cheap.
                "activity_name": _normalise_activity_name(ci_row["activity_name"]),
                "ci": float(ci_row["ci"]),
                "on_deterministic_cp": bool(ci_row["on_deterministic_cp"]),
                "no_activity_bindings": False,
            })

        # Sort within risk group by CI desc; cap at top_n_activities_per_risk.
        per_risk_rows.sort(key=lambda r: r["ci"], reverse=True)
        rows.extend(per_risk_rows[:top_n_activities_per_risk])

    return pd.DataFrame(rows, columns=columns)


def compute_ci_distribution_summary(ci_table: pd.DataFrame) -> dict[str, Any]:
    """Distribution-shape summary used by the format-time narrative.

    Returns
    -------
    dict
        Keys:
          ``band_counts`` — dict[str, int]
          ``band_pcts`` — dict[str, float]
          ``shape_indicator`` — one of
            ``"bimodal"`` | ``"stable_cp"`` | ``"shifty"`` | ``"uniform_low"``
          ``n_activities_total`` — int
          ``n_on_deterministic_cp`` — int

    Shape classification rules (Beta-12 §3.3):

      bimodal     — pct_always ≥ 30% AND pct_never ≥ 30% AND pct_middle ≤ 30%
      stable_cp   — pct_always ≥ 30% AND not bimodal (some movement but a
                    recognisable core CP exists)
      shifty      — pct_middle (rarely + near + often) ≥ 50% AND
                    pct_always < 30% (no core path; many activities flip)
      uniform_low — pct_never ≥ 60% AND pct_always < 10% (most activities
                    sit at low CI; schedule has slack relative to the
                    modelled risk drivers)
      shifty (fallback) — anything else; the safest narrative when no
                          single shape pattern dominates
    """
    counts = {label: 0 for label, _, _ in CI_BAND_DEFINITIONS}
    n_total = 0
    n_det_cp = 0
    if not ci_table.empty:
        for label in counts:
            counts[label] = int((ci_table["ci_band"] == label).sum())
        n_total = int(len(ci_table))
        n_det_cp = int(ci_table["on_deterministic_cp"].sum())

    pct = {
        label: (counts[label] / n_total) if n_total else 0.0
        for label in counts
    }

    pct_always = pct["always (90%+)"]
    pct_never = pct["never (<10%)"]
    pct_middle = (
        pct["rarely (10-30%)"]
        + pct["near (30-70%)"]
        + pct["often (70-90%)"]
    )

    if (
        pct_always >= 0.30 and pct_never >= 0.30 and pct_middle <= 0.30
    ):
        shape = "bimodal"
    elif pct_never >= 0.60 and pct_always < 0.10:
        shape = "uniform_low"
    elif pct_always >= 0.30:
        shape = "stable_cp"
    elif pct_middle >= 0.50:
        shape = "shifty"
    else:
        # Fallback when no rule matches — "shifty" is the safest
        # narrative because it does not make a strong claim about
        # path stability.
        shape = "shifty"

    return {
        "band_counts": counts,
        "band_pcts": pct,
        "shape_indicator": shape,
        "n_activities_total": n_total,
        "n_on_deterministic_cp": n_det_cp,
    }


# ----------------------------------------------------------------------------
# SR10.B — Extended CI table + risk-to-CP linkage table
# ----------------------------------------------------------------------------
#
# The four SR10.B chart helpers all consume a single "extended" CI table
# that joins the Beta-12 per-activity CI table to SR10.A's Mode-independent
# CI dict and the divergence helper's banding. ``compute_extended_ci_table``
# is the single source of truth — every chart helper reads its inputs from
# the columns this builder emits.
#
# Working-day float column. ``total_float_mean_hours`` is normalised to
# working days using the graph's ``project_default_calendar.working_hours_per_day``
# (8 hours / working day is typical). The conversion lives at the
# composer layer so the chart helpers stay unit-agnostic.

#: Default working hours per working day for the conversion from
#: ``total_float_mean_hours`` to ``total_float_mean_days``. A project's
#: project-default calendar is 8 working hours per working day; the
#: divisor is sourced from the live :class:`ScheduleGraph` when present
#: and falls back to this constant only for tests that construct a
#: schedule_result without a graph.
_SR10B_DEFAULT_WORKING_HOURS_PER_DAY: float = 8.0


def compute_extended_ci_table(
    schedule_result: Any,
    *,
    activity_titles: dict[str, str] | None = None,
    working_hours_per_day: float = _SR10B_DEFAULT_WORKING_HOURS_PER_DAY,
) -> pd.DataFrame:
    """Per-activity CI table extended with SR10.B presentation columns.

    Wraps :func:`compute_criticality_table` and joins:

    * ``ci_mode_conditioned`` — copy of the existing ``ci`` column (the
      Beta-12 Mode-conditioned CI).
    * ``ci_mode_independent`` — value from
      :attr:`~src.sra.cpm.cpm_simulation.ScheduleMCResult.mode_independent_criticality_index`;
      defaults to ``ci_mode_conditioned`` when MI CI is ``None`` (legacy
      ``criticality_measurement_mode="mode_conditioned"`` runs — the
      chart helpers then render the same series in both panels).
    * ``mode_conditioned_ci_band`` / ``mode_independent_ci_band`` — five-band
      taxonomy labels for each CI series.
    * ``divergence`` — ``ci_mode_independent - ci_mode_conditioned``.
    * ``divergence_band`` — banded via the SR10.A
      :data:`~src.sra.cpm.criticality_metrics.DIVERGENCE_BAND_SUPPRESSED`
      /
      :data:`~src.sra.cpm.criticality_metrics.DIVERGENCE_BAND_CONSISTENT`
      /
      :data:`~src.sra.cpm.criticality_metrics.DIVERGENCE_BAND_AMPLIFIED`
      labels at the 0.15 default threshold.
    * ``total_float_mean_days`` — ``total_float_mean_hours`` divided by
      ``working_hours_per_day`` (commonly 8.0).

    Row ordering follows :func:`compute_criticality_table` (graph topo
    order from :attr:`ScheduleMCResult.activity_ids`). Chart helpers sort
    by their own keys downstream — preserving topo order here keeps the
    helper deterministic and audit-friendly.
    """
    from src.sra.cpm.criticality_metrics import (
        DIVERGENCE_BAND_AMPLIFIED,
        DIVERGENCE_BAND_CONSISTENT,
        DIVERGENCE_BAND_SUPPRESSED,
    )

    base = compute_criticality_table(
        schedule_result, activity_titles=activity_titles,
    )
    if base.empty:
        columns = list(base.columns) + [
            "ci_mode_conditioned",
            "ci_mode_independent",
            "mode_conditioned_ci_band",
            "mode_independent_ci_band",
            "divergence",
            "divergence_band",
            "total_float_mean_days",
        ]
        return pd.DataFrame(columns=columns)

    mi_dict_raw = getattr(
        schedule_result, "mode_independent_criticality_index", None,
    )
    mc_series = base["ci"].astype(float)
    if mi_dict_raw is None:
        mi_series = mc_series.copy()
    else:
        mi_dict = dict(mi_dict_raw or {})
        mi_series = base["activity_id"].map(
            lambda a: float(mi_dict.get(str(a), 0.0))
        )

    out = base.copy()
    out["ci_mode_conditioned"] = mc_series
    out["ci_mode_independent"] = mi_series
    out["mode_conditioned_ci_band"] = mc_series.map(_ci_band)
    out["mode_independent_ci_band"] = mi_series.map(_ci_band)
    divergence = mi_series - mc_series
    out["divergence"] = divergence

    # Apply the 0.15 default banding here so the chart helpers consume a
    # single ready-made column. SR10.A's compute_criticality_divergence
    # uses the same thresholds; the band labels match exactly.
    band_labels = np.full(len(out), DIVERGENCE_BAND_CONSISTENT, dtype=object)
    band_labels[divergence.to_numpy() >= 0.15] = DIVERGENCE_BAND_SUPPRESSED
    band_labels[divergence.to_numpy() <= -0.15] = DIVERGENCE_BAND_AMPLIFIED
    out["divergence_band"] = band_labels

    # Working-day float conversion. Guard against zero divisor (a misuse
    # would normally raise on Calendar construction, but the composer is
    # defensive).
    if working_hours_per_day <= 0:
        working_hours_per_day = _SR10B_DEFAULT_WORKING_HOURS_PER_DAY
    out["total_float_mean_days"] = (
        out["total_float_mean_hours"].astype(float) / float(working_hours_per_day)
    )
    return out


def build_risk_to_cp_linkage_table(
    risk_drivers: dict[str, Any],
    extended_ci_table: pd.DataFrame,
    *,
    risk_titles: dict[str, str] | None = None,
    top_n_activities_in_summary: int = 3,
    risk_impact_lookup: dict[str, float] | None = None,
) -> pd.DataFrame:
    """One row per Time=Yes risk surfacing dual-CI and divergence stats.

    SR10.B Chart 3 table (brief §4.3). For each risk in
    ``risk_drivers`` the row carries:

    * ``risk_id`` — risk identifier (str)
    * ``risk_title`` — from ``risk_titles`` lookup; falls back to ``risk_id``
    * ``mode`` — :attr:`RiskDriver.mode` (current declared Mode)
    * ``n_activities_bound`` — len(:attr:`affected_activity_ids`)
    * ``top_3_activities_by_MI_CI`` — semicolon-separated
      ``activity_id|activity_name (MI-CI%)`` strings, top-N by MI-CI desc
    * ``mean_MC_CI_across_bound`` — mean of ``ci_mode_conditioned`` across
      bound activities (NaN when n_activities_bound = 0)
    * ``mean_MI_CI_across_bound`` — mean of ``ci_mode_independent``
    * ``divergence_summary`` — median signed divergence across bound
      activities; positive = AACE detects criticality the Mode tuning
      is suppressing.
    * ``prob_weighted_mean_days`` — probability-weighted mean schedule
      impact for this risk, sourced from the schedule MC tornado data
      (matches §10.4 ranking metric). 0.0 when ``risk_impact_lookup``
      doesn't carry an entry for the risk (Beta-19b item 3).

    Risks whose auto-mapper expansion produced zero activities are kept
    as rows with NaN means and an empty top-N string so the table reads
    as a complete risk roster (rather than silently dropping zero-bound
    risks). The brief's wording — "one row per Time=Yes risk" — is
    preserved.

    Beta-19b item 3 + 7d: rows are emitted in descending order of
    ``prob_weighted_mean_days`` when ``risk_impact_lookup`` is supplied so
    Chart 3 and the §10.5 top-3 ranking match §10.4. When the lookup is
    None, ordering falls back to the natural ``risk_drivers`` dict order
    (legacy / test-fixture behaviour).
    """
    titles = dict(risk_titles or {})
    impact_lookup = dict(risk_impact_lookup or {})
    columns = [
        "risk_id",
        "risk_title",
        "mode",
        # SR12 — per-risk injection method (additive_pert_days /
        # discrete_event_additive_days / productivity_multiplicative_factor
        # / multiplicative_pert_factor). Surfaced in the §10.5 linkage
        # table so a reviewer can read the per-risk dispatch alongside
        # the Mode-conditioned and Mode-independent CI bands.
        "injection_method",
        "n_activities_bound",
        "top_3_activities_by_MI_CI",
        "mean_MC_CI_across_bound",
        "mean_MI_CI_across_bound",
        "divergence_summary",
        "prob_weighted_mean_days",
    ]
    if not risk_drivers:
        return pd.DataFrame(columns=columns)

    if extended_ci_table is None or extended_ci_table.empty:
        # Schedule MC ran with no activities; the linkage table is
        # structurally degenerate but we still surface the risk roster.
        rows: list[dict[str, Any]] = []
        for rid, driver in risk_drivers.items():
            affected = list(getattr(driver, "affected_activity_ids", ()) or ())
            rows.append({
                "risk_id": str(rid),
                "risk_title": str(titles.get(str(rid), rid)),
                "mode": str(getattr(driver, "mode", "Series") or "Series"),
                "injection_method": str(
                    getattr(driver, "injection_method", "") or ""
                ),
                "n_activities_bound": len(affected),
                "top_3_activities_by_MI_CI": "",
                "mean_MC_CI_across_bound": float("nan"),
                "mean_MI_CI_across_bound": float("nan"),
                "divergence_summary": float("nan"),
                "prob_weighted_mean_days": float(
                    impact_lookup.get(str(rid), 0.0)
                ),
            })
        df = pd.DataFrame(rows, columns=columns)
        if impact_lookup:
            df = df.sort_values(
                "prob_weighted_mean_days", ascending=False, kind="stable",
            ).reset_index(drop=True)
        return df

    ci_lookup = extended_ci_table.set_index("activity_id")

    rows = []
    for rid, driver in risk_drivers.items():
        affected = list(getattr(driver, "affected_activity_ids", ()) or ())
        # Filter to activities actually present in the CI lookup;
        # silently drop any IDs the auto-mapper produced that aren't in
        # the live graph (shouldn't happen, but defensive).
        bound_in_table = [a for a in affected if a in ci_lookup.index]
        n_bound = len(bound_in_table)
        mode_label = str(getattr(driver, "mode", "Series") or "Series")
        prob_weighted_days = float(impact_lookup.get(str(rid), 0.0))

        if n_bound == 0:
            rows.append({
                "risk_id": str(rid),
                "risk_title": str(titles.get(str(rid), rid)),
                "mode": mode_label,
                "injection_method": str(
                    getattr(driver, "injection_method", "") or ""
                ),
                "n_activities_bound": len(affected),
                "top_3_activities_by_MI_CI": "",
                "mean_MC_CI_across_bound": float("nan"),
                "mean_MI_CI_across_bound": float("nan"),
                "divergence_summary": float("nan"),
                "prob_weighted_mean_days": prob_weighted_days,
            })
            continue

        subset = ci_lookup.loc[bound_in_table].copy()
        mc_mean = float(subset["ci_mode_conditioned"].mean())
        mi_mean = float(subset["ci_mode_independent"].mean())
        divergence_median = float(subset["divergence"].median())

        # Top-N activities by MI CI desc; stable secondary sort by
        # activity_id so the rendering is deterministic when ties exist.
        top_n = subset.sort_values(
            ["ci_mode_independent"], ascending=False, kind="stable",
        ).head(top_n_activities_in_summary)
        pieces: list[str] = []
        for a_id, row in top_n.iterrows():
            # SR18 Item 4 defensive: normalise even though upstream
            # compute_criticality_table now produces clean names. The
            # top_3_activities_by_MI_CI string feeds Chart 3 + the §10.5
            # linkage prose.
            name = _normalise_activity_name(row.get("activity_name", a_id))
            mi_ci = float(row.get("ci_mode_independent", 0.0))
            pieces.append(f"{a_id}|{name} (MI-CI {mi_ci:.0%})")
        top_str = "; ".join(pieces)

        rows.append({
            "risk_id": str(rid),
            "risk_title": str(titles.get(str(rid), rid)),
            "mode": mode_label,
            "injection_method": str(
                getattr(driver, "injection_method", "") or ""
            ),
            "n_activities_bound": n_bound,
            "top_3_activities_by_MI_CI": top_str,
            "mean_MC_CI_across_bound": mc_mean,
            "mean_MI_CI_across_bound": mi_mean,
            "divergence_summary": divergence_median,
            "prob_weighted_mean_days": prob_weighted_days,
        })

    df = pd.DataFrame(rows, columns=columns)
    if impact_lookup:
        df = df.sort_values(
            "prob_weighted_mean_days", ascending=False, kind="stable",
        ).reset_index(drop=True)
    return df


# ----------------------------------------------------------------------------
# SR10.B — XER-derived activity dates + phase map (Chart 2 plumbing)
# ----------------------------------------------------------------------------

def _build_activity_dates_from_xer(
    xer_tables: dict[str, pd.DataFrame] | None,
) -> pd.DataFrame:
    """Project ``TASK.task_id, early_start_date, early_end_date`` to the
    activity-dates frame the Chart 2 density Gantt consumes.

    Returns a DataFrame with columns ``activity_id`` (str — matches the
    :class:`ScheduleGraph` activity id, which is the XER ``task_id``
    string), ``start_date``, ``finish_date``. Rows missing either date
    are kept; the chart helper drops NaT rows at render time.

    Returns an empty frame when ``xer_tables`` is ``None`` or missing
    the TASK table — the chart helper then renders a placeholder.
    """
    columns = ["activity_id", "start_date", "finish_date"]
    if not xer_tables or "TASK" not in xer_tables:
        return pd.DataFrame(columns=columns)
    task = xer_tables["TASK"]
    required = {"task_id", "early_start_date", "early_end_date"}
    if not required.issubset(set(task.columns)):
        return pd.DataFrame(columns=columns)
    out = pd.DataFrame({
        "activity_id": task["task_id"].astype(str),
        "start_date": pd.to_datetime(
            task["early_start_date"], errors="coerce",
        ),
        "finish_date": pd.to_datetime(
            task["early_end_date"], errors="coerce",
        ),
    })
    return out


def _build_phase_map_from_xer(
    xer_tables: dict[str, pd.DataFrame] | None,
) -> dict[str, str]:
    """Build a per-activity RBS Level 1 phase label from PROJWBS + TASK.

    Walks the WBS parent chain UP but stops one level before the root so
    the label resolves to the Level 1 discipline / phase node (Civil /
    Structural / Mechanical / etc.) rather than the project root
    ("BGP.BoP.WRK.01"). When the walk yields the root (single-level WBS,
    or activity attached directly to root), falls back to the
    task_code-prefix heuristic per Beta-19b Decision 1.

    Returns a dict ``activity_id → phase``. Activities with no phase
    inference produce no entry; the caller's downstream rendering
    buckets them into ``"Unmapped"``.
    """
    out: dict[str, str] = {}
    if not xer_tables or "TASK" not in xer_tables:
        return out
    task = xer_tables["TASK"]

    level1_by_wbs: dict[int, str] = {}
    root_ids: set[int] = set()
    if "PROJWBS" in xer_tables:
        wbs = xer_tables["PROJWBS"]
        parent_by_id: dict[int, int | None] = {}
        short_by_id: dict[int, str] = {}
        for _, row in wbs.iterrows():
            try:
                wbs_id = int(row.get("wbs_id"))
            except (TypeError, ValueError):
                continue
            parent_raw = row.get("parent_wbs_id")
            try:
                parent_by_id[wbs_id] = (
                    int(parent_raw) if pd.notna(parent_raw) else None
                )
            except (TypeError, ValueError):
                parent_by_id[wbs_id] = None
            short_by_id[wbs_id] = str(row.get("wbs_short_name") or "").strip()

        # Identify roots (nodes whose parent is None or absent from the
        # parent_by_id map).
        for wbs_id, parent in parent_by_id.items():
            if parent is None or parent not in parent_by_id:
                root_ids.add(wbs_id)

        # For every node walk up; record the LAST node before reaching a
        # root. That node is the Level 1 ancestor. If the node itself is
        # a root (top-level activity), no Level 1 mapping is produced —
        # the prefix fallback handles it.
        for wbs_id in list(parent_by_id.keys()):
            seen: set[int] = set()
            cur: int | None = wbs_id
            level1: int | None = None
            while cur is not None and cur not in seen:
                seen.add(cur)
                parent = parent_by_id.get(cur)
                if parent is None or parent not in parent_by_id:
                    # `cur` is a root; `level1` was set on the previous
                    # iteration (or stays None when cur was a root from
                    # the start).
                    break
                # Track the candidate Level 1 as we walk up — it's the
                # current node when the NEXT step lands on a root.
                if parent in root_ids:
                    level1 = cur
                    break
                cur = parent
            if level1 is not None:
                label = short_by_id.get(level1, "").strip()
                if label:
                    level1_by_wbs[wbs_id] = label

    # SR18 Item 1: prefix-heuristic map lifted to src/final/rbs_mapping.py
    # so the same lookup applies at the Chart 2 Y-axis render layer (where
    # PROJWBS short_names like "01" / "10" reach the axis when the WBS
    # walk succeeds). The shared map also corrects the labels to match
    # the live .xer PROJWBS wbs_name and expands the key set from 8 to 17.
    from src.final.rbs_mapping import resolve_rbs_l1_label

    for _, row in task.iterrows():
        a_id = str(row.get("task_id") or "").strip()
        if not a_id:
            continue
        label: str | None = None
        wbs_raw = row.get("wbs_id")
        try:
            wbs_id = int(wbs_raw) if pd.notna(wbs_raw) else None
        except (TypeError, ValueError):
            wbs_id = None
        if wbs_id is not None and wbs_id in level1_by_wbs:
            label = level1_by_wbs[wbs_id]

        if not label:
            code = str(row.get("task_code") or "").strip()
            if code:
                first_segment = code.split(".")[0].strip()
                if first_segment:
                    label = resolve_rbs_l1_label(first_segment)

        if label:
            out[a_id] = label
    return out


def _resolve_schedule_window(
    stage3_beta_result: dict[str, Any],
    composed: dict[str, Any],
) -> tuple["pd.Timestamp", "pd.Timestamp"]:
    """Determine the project's [start, finish] window for Chart 2.

    Preference order (Decision 3 says monthly bins span the strawman
    schedule window):

    1. ``Run_Config_Preview.schedule_start`` / ``schedule_finish`` read
       from the strawman (canonical source).
    2. ``min(TASK.early_start_date)`` / ``max(TASK.early_end_date)`` from
       the XER as a fall-through (covers test paths and strawman runs
       without populated window cells).
    3. ``(NaT, NaT)`` — the chart renders a placeholder.
    """
    strawman_path = composed.get("audit_trail_strawman_path") or composed.get(
        "appendix_audit_trail", {}
    ).get("strawman_path")
    if strawman_path:
        try:
            from src.sra.strawman_reader import read_run_config

            run_cfg = read_run_config(str(strawman_path))
            start_val = run_cfg.get("schedule_start")
            finish_val = run_cfg.get("schedule_finish")
            start_ts = pd.to_datetime(start_val, errors="coerce")
            finish_ts = pd.to_datetime(finish_val, errors="coerce")
            if not pd.isna(start_ts) and not pd.isna(finish_ts):
                return (pd.Timestamp(start_ts), pd.Timestamp(finish_ts))
        except Exception:
            pass

    xer_tables = stage3_beta_result.get("xer_tables")
    if xer_tables and "TASK" in xer_tables:
        task = xer_tables["TASK"]
        start_col = pd.to_datetime(
            task.get("early_start_date"), errors="coerce",
        )
        finish_col = pd.to_datetime(
            task.get("early_end_date"), errors="coerce",
        )
        if start_col is not None and finish_col is not None:
            valid_start = start_col.dropna()
            valid_finish = finish_col.dropna()
            if not valid_start.empty and not valid_finish.empty:
                return (
                    pd.Timestamp(valid_start.min()),
                    pd.Timestamp(valid_finish.max()),
                )

    return (pd.NaT, pd.NaT)


def _render_risk_linkage_table_png(
    linkage_table: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Render the Chart 3 risk-to-CP linkage table as a styled PNG.

    Chart 3 is a tabular deliverable; we render it as a PNG so the
    sibling note's HTML / docx can embed it the same way as the other
    chart PNGs (uniform handling at the renderer layer).
    """
    # Local matplotlib import keeps the composer's cold-import cost low
    # on cost-only / Stage 2.5 paths.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # SR17 Workstream D — chart theme on this code path. apply_theme is
    # idempotent so repeated calls from sibling chart helpers do not
    # conflict.
    from src.final.chart_theme import apply_theme
    apply_theme()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if linkage_table is None or linkage_table.empty:
        fig, ax = plt.subplots(figsize=(12, 2))
        ax.text(
            0.5, 0.5, "No risk-to-CP linkage data available",
            ha="center", va="center", fontsize=12, color="#999999",
        )
        ax.set_axis_off()
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path.resolve()

    # Render-time formatting. Keep numeric columns as percentages /
    # signed decimals; leave text columns as-is. Beta-19b item 7b: the
    # top_3_activities_by_MI_CI column is semicolon-separated by the
    # builder; rewrite each "; " into a newline so matplotlib wraps the
    # cell contents instead of truncating at the right edge.
    fmt_table = linkage_table.copy()
    for col in ("mean_MC_CI_across_bound", "mean_MI_CI_across_bound"):
        if col in fmt_table.columns:
            fmt_table[col] = fmt_table[col].map(
                lambda v: "" if pd.isna(v) else f"{float(v):.0%}"
            )
    if "divergence_summary" in fmt_table.columns:
        fmt_table["divergence_summary"] = fmt_table["divergence_summary"].map(
            lambda v: "" if pd.isna(v) else f"{float(v):+.2f}"
        )
    if "prob_weighted_mean_days" in fmt_table.columns:
        fmt_table["prob_weighted_mean_days"] = fmt_table[
            "prob_weighted_mean_days"
        ].map(lambda v: "" if pd.isna(v) else f"{float(v):.2f}")
    if "top_3_activities_by_MI_CI" in fmt_table.columns:
        fmt_table["top_3_activities_by_MI_CI"] = fmt_table[
            "top_3_activities_by_MI_CI"
        ].astype(str).str.replace("; ", "\n", regex=False)

    header_labels = list(fmt_table.columns)
    row_values = fmt_table.astype(str).values.tolist()

    # Beta-19b item 7c: widened from 14" to 18" so the rightmost column
    # is no longer clipped at the page edge.
    n_rows = len(row_values)
    # Multi-line cells in the top-3-activities column need taller rows;
    # 3 wrapped lines per row is typical under the current
    # auto-mapper expansion.
    fig_height = max(2.5, 0.9 * (n_rows + 1) + 0.6)
    fig, ax = plt.subplots(figsize=(18, fig_height))
    ax.set_axis_off()
    table = ax.table(
        cellText=row_values,
        colLabels=header_labels,
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.6)

    # Beta-19b item 7b: per-column relative width allocation so the wide
    # top-3-activities column has room without crowding the others.
    # matplotlib doesn't expose a public column-width API on Table, so we
    # set per-cell widths via the cell width attribute. Sum is normalised
    # to 1.0 across all visible columns.
    relative_widths: dict[str, float] = {
        "risk_id": 0.045,
        "risk_title": 0.16,
        "mode": 0.06,
        "n_activities_bound": 0.06,
        "top_3_activities_by_MI_CI": 0.40,
        "mean_MC_CI_across_bound": 0.07,
        "mean_MI_CI_across_bound": 0.07,
        "divergence_summary": 0.07,
        "prob_weighted_mean_days": 0.075,
    }
    n_cols = len(header_labels)
    width_vec = [
        relative_widths.get(col, 1.0 / max(n_cols, 1))
        for col in header_labels
    ]
    width_sum = float(sum(width_vec))
    if width_sum > 0:
        width_vec = [w / width_sum for w in width_vec]
    for j, w in enumerate(width_vec):
        # Apply to header row (row 0) and every data row.
        for i in range(n_rows + 1):
            cell = table[(i, j)]
            cell.set_width(w)
            # Beta-19b item 7b: enable text wrapping on the wide
            # activities column.
            if header_labels[j] == "top_3_activities_by_MI_CI":
                cell.set_text_props(wrap=True)

    # Header styling (dark navy fill, white bold text).
    for j in range(len(header_labels)):
        cell = table[(0, j)]
        cell.set_facecolor("#2C3E50")
        cell.set_text_props(color="white", weight="bold")

    ax.set_title(
        "Risk-to-CP linkage, one row per Time=Yes risk, "
        "ranked by probability-weighted mean impact (matches §10.4) "
        "(MC = Mode-conditioned CI, MI = Mode-independent CI)",
        fontsize=11, pad=12,
    )
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


def _apply_criticality_keys(
    composed: dict[str, Any],
    stage3_beta_result: dict[str, Any],
    *,
    chart_output_dir: Path | None,
    risk_titles_override: dict[str, str] | None = None,
) -> None:
    """Populate ``composed["page4b_criticality"]`` from stage3_beta_result.

    Reads:
      - ``stage3_beta_result["schedule_result"]`` for activity-level
        criticality fields (Beta-12 commits 3-4)
      - ``stage3_beta_result["schedule_graph"]`` for activity_titles
      - ``stage3_beta_result["risk_drivers"]`` for the bridge table
      - ``composed["page4_schedule_drivers"]["drivers_table"]`` for the
        top-3 schedule risk-driver ids (the Page 4 ranking)

    Generates the CI distribution chart PNG when ``chart_output_dir`` is
    not None; skips the chart and leaves ``distribution_chart_path`` ""
    otherwise (the section narrative still renders without the chart).

    Imports are deferred to function scope to avoid pulling matplotlib
    into modules that don't need it (commentary_text / executive_summary
    are pure-text; charts already imports matplotlib).
    """
    schedule_result = stage3_beta_result.get("schedule_result")
    if schedule_result is None:
        composed["page4b_criticality"] = {}
        return

    schedule_graph = stage3_beta_result.get("schedule_graph")
    activity_titles: dict[str, str] | None = None
    if schedule_graph is not None:
        try:
            activity_titles = {
                a_id: getattr(act, "name", a_id)
                for a_id, act in schedule_graph.activities.items()
            }
        except AttributeError:
            activity_titles = None

    ci_table = compute_criticality_table(
        schedule_result, activity_titles=activity_titles,
    )
    distribution_summary = compute_ci_distribution_summary(ci_table)
    near_critical = pick_near_critical_activities(ci_table)

    # Top-3 risk ids from the Page 4 schedule tornado. The composer
    # call site for _apply_stage3_beta_keys runs after page4_schedule_drivers
    # is populated, so this lookup is reliable.
    top_drivers = (
        composed.get("page4_schedule_drivers", {}).get("drivers_table") or []
    )
    top_3_risk_ids = [str(r.get("Risk", "")) for r in top_drivers[:3] if r.get("Risk")]

    # Beta-19b item 7a: fall back to the composer-provided override when
    # the binding hasn't populated stage3_beta_result["risk_titles"]
    # (a binding need not, so this is the live path).
    risk_titles = (
        dict(risk_titles_override or {})
        or stage3_beta_result.get("risk_titles")
        or {}
    )
    bridge = build_risk_to_activity_bridge(
        stage3_beta_result.get("risk_drivers", {}) or {},
        ci_table,
        top_3_risk_ids,
        risk_titles=risk_titles,
    )

    # CI distribution chart — only generated when chart_output_dir is
    # provided. Function-local import so this module doesn't pay the
    # matplotlib cost on the cost-only / Stage 2.5 path.
    distribution_chart_path = ""
    if chart_output_dir is not None:
        from src.final.charts import make_ci_distribution_chart

        chart_output_dir = Path(chart_output_dir)
        chart_output_dir.mkdir(parents=True, exist_ok=True)
        ci_chart_path = chart_output_dir / "page4b_ci_distribution.png"
        n_iter = int(getattr(schedule_result, "n_iter", 0))
        make_ci_distribution_chart(
            ci_table,
            output_path=ci_chart_path,
            n_iter=n_iter,
        )
        distribution_chart_path = str(ci_chart_path.resolve())

    # ----------------------------------------------------------------
    # SR10.B — build the extended CI table and the four chart paths.
    # Active only when chart_output_dir is provided. The composer always
    # builds the extended table (so the linkage table + §10.5 prose can
    # still surface when chart rendering is disabled) but the four chart
    # PNGs are only emitted when an output directory is available.
    # ----------------------------------------------------------------
    working_hours_per_day = _SR10B_DEFAULT_WORKING_HOURS_PER_DAY
    if schedule_graph is not None:
        try:
            working_hours_per_day = float(
                schedule_graph.project_default_calendar.working_hours_per_day
            )
        except (AttributeError, TypeError, ValueError):
            working_hours_per_day = _SR10B_DEFAULT_WORKING_HOURS_PER_DAY

    extended_ci_table = compute_extended_ci_table(
        schedule_result,
        activity_titles=activity_titles,
        working_hours_per_day=working_hours_per_day,
    )
    # Beta-19b item 3 + 7d: surface the probability-weighted mean impact
    # (the §10.4 ranking metric) on the linkage table so both Chart 3 and
    # the §10.5 prose rank consistently.
    _sched_drivers_for_lookup = (
        composed.get("page4_schedule_drivers", {}).get("drivers_table") or []
    )
    risk_impact_lookup: dict[str, float] = {}
    for _row in _sched_drivers_for_lookup:
        _rid = str(_row.get("Risk", "")).strip()
        _val = _row.get("Probability x mean impact (days)")
        if _rid and isinstance(_val, (int, float)):
            risk_impact_lookup[_rid] = float(_val)
    linkage_table = build_risk_to_cp_linkage_table(
        stage3_beta_result.get("risk_drivers", {}) or {},
        extended_ci_table,
        # Beta-19b item 7a: reuse the resolved title lookup from above so
        # the linkage table's risk_title column shows real titles.
        risk_titles=risk_titles,
        risk_impact_lookup=risk_impact_lookup,
    )

    sr10b_chart_paths: dict[str, str] = {
        "chart1_sorted_top30_path": "",
        "chart2_density_gantt_path": "",
        "chart3_risk_to_cp_linkage_path": "",
        "chart4_float_histogram_path": "",
    }
    if chart_output_dir is not None:
        from src.final.charts import (
            make_criticality_density_gantt,
            make_float_histogram_with_ci_overlay,
            make_sorted_criticality_bar_chart,
        )

        # Chart 1 — sorted Top-30 dual bar chart.
        ch1_path = chart_output_dir / "sr10b_chart1_sorted_top30.png"
        make_sorted_criticality_bar_chart(
            extended_ci_table, output_path=ch1_path,
        )
        sr10b_chart_paths["chart1_sorted_top30_path"] = str(ch1_path.resolve())

        # Chart 2 — criticality density Gantt by phase. Requires XER
        # tables for activity dates and the WBS-derived phase map +
        # strawman schedule window for the x-axis bounds.
        xer_tables = stage3_beta_result.get("xer_tables")
        activity_dates = _build_activity_dates_from_xer(xer_tables)
        phase_map = _build_phase_map_from_xer(xer_tables)
        schedule_window = _resolve_schedule_window(stage3_beta_result, composed)
        ch2_path = chart_output_dir / "sr10b_chart2_density_gantt.png"
        make_criticality_density_gantt(
            ci_table=extended_ci_table,
            activity_dates=activity_dates,
            phase_map=phase_map,
            schedule_start=schedule_window[0],
            schedule_finish=schedule_window[1],
            output_path=ch2_path,
        )
        sr10b_chart_paths["chart2_density_gantt_path"] = str(ch2_path.resolve())

        # Chart 3 — risk-to-CP linkage table rendered as a styled PNG.
        ch3_path = chart_output_dir / "sr10b_chart3_risk_to_cp_linkage.png"
        _render_risk_linkage_table_png(linkage_table, ch3_path)
        sr10b_chart_paths["chart3_risk_to_cp_linkage_path"] = str(ch3_path.resolve())

        # Chart 4 — float histogram with CI overlay.
        ch4_path = chart_output_dir / "sr10b_chart4_float_histogram.png"
        make_float_histogram_with_ci_overlay(
            extended_ci_table, output_path=ch4_path,
        )
        sr10b_chart_paths["chart4_float_histogram_path"] = str(ch4_path.resolve())

    # Format-time narrative substitutions — deferred to executive_summary
    # helpers so the templates live next to the other data-driven format
    # helpers (pick_tail_risk pattern; Beta-11a precedent).
    from src.final.executive_summary import (
        format_criticality_distribution_interpretation,
        format_criticality_explainer,
        format_criticality_near_critical_interpretation,
    )

    n_iter_for_narrative = int(getattr(schedule_result, "n_iter", 0))
    # Beta-19b item 10: pass the live auto-mapper binding counts so the
    # explainer's Mode-conditioned vs Mode-independent paragraph names
    # the {n_min}-{n_max} range from this run. linkage_table is already
    # built above this site.
    _binding_counts = []
    if linkage_table is not None and "n_activities_bound" in linkage_table.columns:
        _binding_counts = [
            int(v) for v in linkage_table["n_activities_bound"].tolist()
            if isinstance(v, (int, float)) and int(v) > 0
        ]
    explainer = format_criticality_explainer(
        n_iter_for_narrative, binding_counts=_binding_counts,
    )
    distribution_interpretation = format_criticality_distribution_interpretation(
        distribution_summary,
    )
    near_critical_interpretation = format_criticality_near_critical_interpretation(
        near_critical,
    )

    near_critical_records = near_critical.to_dict(orient="records")
    bridge_records = bridge.to_dict(orient="records")

    # SR10.B Item 5 / §10.5 prose flip: when the Mode-independent CI
    # is present on the schedule_result we route the §10.5 prose
    # through the SR10.B templated formatter that names the
    # amplified-by-Mode finding. The Beta-19 formatter remains the
    # fallback for legacy mode_conditioned-only runs.
    has_mode_independent = (
        getattr(schedule_result, "mode_independent_criticality_index", None)
        is not None
    )
    if has_mode_independent:
        from src.final.executive_summary import (
            format_risk_to_cp_linkage_prose_sr10b,
        )

        risk_to_cp_linkage_prose = format_risk_to_cp_linkage_prose_sr10b(
            linkage_table=linkage_table,
            extended_ci_table=extended_ci_table,
        )
    else:
        from src.final.executive_summary import format_risk_to_cp_linkage_prose

        risk_to_cp_linkage_prose = format_risk_to_cp_linkage_prose(bridge_records)

    # SR10.B Chart 2 main-report placement — when the chart was rendered,
    # surface the actual path so the docx renderer embeds the image
    # instead of the placeholder caption. Falls back to the placeholder
    # caption when chart_output_dir is None (test paths) or when the
    # rendered file is unavailable.
    chart2_main_path = sr10b_chart_paths.get("chart2_density_gantt_path", "")
    chart2_caption_text = (
        commentary_text.CRITICALITY_CHART_2_PLACEHOLDER_CAPTION
        if not chart2_main_path
        else commentary_text.CRITICALITY_CHART_2_RENDERED_CAPTION
    )

    composed["page4b_criticality"] = {
        "explainer": explainer,
        "distribution_chart_path": distribution_chart_path,
        "distribution_summary": distribution_summary,
        "distribution_interpretation": distribution_interpretation,
        # Beta-19 §3: main-report keeps a 5-row summary (top 5 by CI),
        # full 10-row content sits in the sibling note. The records
        # below are the engine's full near-critical list (10 rows);
        # the main-report renderer slices to 5.
        "near_critical_table": near_critical_records,
        "near_critical_table_top_5": near_critical_records[:5],
        "near_critical_interpretation": near_critical_interpretation,
        "risk_to_activity_bridge": bridge_records,
        "risk_bridge_interpretation": commentary_text.CRITICALITY_RISK_BRIDGE_INTERPRETATION,
        "input_dependencies_caveat": commentary_text.CRITICALITY_INPUT_DEPENDENCIES_CAVEAT,
        # SR-S3-Beta-18 §5: single-sentence calendar caveat surfaced
        # inline immediately under each activity-level table.
        #
        # SR18 Item 3 (root-cause fix for the duplicate-caveat
        # regression at HTML lines 8690 / 8893 in the 2026-05-18 PROD
        # render): the same caveat string was being attached to BOTH
        # ``near_critical_table_caveat`` AND
        # ``risk_to_activity_bridge_caveat`` and rendered by two
        # separate notebook cells (49 + 51 in final_runner.ipynb), so
        # readers saw the caveat twice in the §10.5 area. Fix: keep
        # the caveat inline under the first activity-level table
        # (near-critical) so the Beta-18 §5 intent is preserved; the
        # second table (risk-to-activity bridge) inherits the caveat
        # by section context (set to empty string so the notebook's
        # ``if _bridge_caveat:`` guard renders nothing).
        "near_critical_table_caveat": (
            commentary_text.CRITICALITY_CALENDAR_CAVEAT_INLINE
        ),
        "risk_to_activity_bridge_caveat": "",
        # SR10.B: Chart 2 image path supersedes the Beta-19 caption-only
        # placeholder. The docx renderer embeds the image when the path
        # exists; HTML / placeholder-only renderers fall back to the
        # caption string.
        "chart2_density_gantt_path": chart2_main_path,
        "chart2_placeholder_caption": chart2_caption_text,
        "risk_to_cp_linkage_prose": risk_to_cp_linkage_prose,
        "forward_reference_to_note": (
            commentary_text.CRITICALITY_FORWARD_REFERENCE_TO_NOTE
        ),
        # SR14b.1: additional keys consumed by the Stage 3 standalone
        # docx's Criticality detail appendix section (renderer:
        # :func:`src.final.word_generator._add_criticality_appendix`).
        # Each path / table key carries the same source object as the
        # corresponding orphan ``composed["criticality_note"]`` field so
        # the new appendix and the deprecated sibling note render
        # identical content; the orphan dict stays one release cycle
        # per the SR14b session-2 deprecation plan.
        "chart1_sorted_top30_path": sr10b_chart_paths[
            "chart1_sorted_top30_path"
        ],
        "chart3_risk_to_cp_linkage_path": sr10b_chart_paths[
            "chart3_risk_to_cp_linkage_path"
        ],
        "chart4_float_histogram_path": sr10b_chart_paths[
            "chart4_float_histogram_path"
        ],
        "ci_distribution_chart_path": distribution_chart_path,
        "near_critical_table_full": near_critical_records,
        "risk_to_activity_bridge_full": bridge_records,
        "chart1_caption": (
            commentary_text.CRITICALITY_CHART_1_PLACEHOLDER_CAPTION
        ),
        "chart3_caption": (
            commentary_text.CRITICALITY_CHART_3_PLACEHOLDER_CAPTION
        ),
        "chart4_caption": (
            commentary_text.CRITICALITY_CHART_4_PLACEHOLDER_CAPTION
        ),
        "ci_distribution_caption": (
            commentary_text.CRITICALITY_CI_DISTRIBUTION_CAPTION_STAGE3
        ),
    }

    # Beta-19 §3: sibling criticality-note dict. Holds the full-detail
    # content moved out of the main report plus the four chart image
    # paths (SR10.B Item 8 — the placeholder captions stay as
    # accessibility fallbacks for renderers that can't embed PNGs).
    composed["criticality_note"] = {
        "purpose_and_audience": (
            commentary_text.CRITICALITY_NOTE_PURPOSE_AND_AUDIENCE
        ),
        "explainer": explainer,
        # SR10.B: chart_*_path fields carry the rendered PNGs. When a
        # path is empty (chart_output_dir was None) the renderer falls
        # back to the caption text in chart_*_caption.
        "chart1_path": sr10b_chart_paths["chart1_sorted_top30_path"],
        "chart1_caption": (
            commentary_text.CRITICALITY_CHART_1_PLACEHOLDER_CAPTION
        ),
        # Chart 2's path field name remains "chart2_path" for
        # back-compat with the Beta-19 sibling-note renderer. The
        # source is the SR10.B density Gantt PNG when rendered; falls
        # back to the Beta-12 CI distribution chart otherwise.
        "chart2_path": (
            sr10b_chart_paths["chart2_density_gantt_path"]
            or distribution_chart_path
        ),
        "chart2_caption": (
            commentary_text.CRITICALITY_CHART_2_RENDERED_CAPTION
            if sr10b_chart_paths["chart2_density_gantt_path"]
            else commentary_text.CRITICALITY_CHART_2_PLACEHOLDER_CAPTION
        ),
        "near_critical_table_10row": near_critical_records,
        "near_critical_interpretation": near_critical_interpretation,
        # SR18 Item 3 same fix applied to the sibling criticality_note
        # dict for consistency. Sibling emission was stopped under SR14b
        # D4 (Cell 7c no longer writes sra_criticality_note_PROD_*) but
        # the dict is still built and may be consumed by future renderer
        # paths; the duplicate would otherwise re-appear when sibling
        # emission resumes.
        "near_critical_table_caveat": (
            commentary_text.CRITICALITY_CALENDAR_CAVEAT_INLINE
        ),
        "risk_to_activity_bridge": bridge_records,
        "risk_bridge_interpretation": (
            commentary_text.CRITICALITY_RISK_BRIDGE_INTERPRETATION
        ),
        "risk_to_activity_bridge_caveat": "",
        "chart3_path": sr10b_chart_paths["chart3_risk_to_cp_linkage_path"],
        "chart3_caption": (
            commentary_text.CRITICALITY_CHART_3_PLACEHOLDER_CAPTION
        ),
        "chart4_path": sr10b_chart_paths["chart4_float_histogram_path"],
        "chart4_caption": (
            commentary_text.CRITICALITY_CHART_4_PLACEHOLDER_CAPTION
        ),
        # SR10.B: the linkage table records carry the same shape the
        # PNG image encodes; HTML renderers can choose to embed the
        # PNG (preferred) or render the records as a table.
        "risk_to_cp_linkage_records": linkage_table.to_dict(orient="records"),
        "input_dependencies_caveat": (
            commentary_text.CRITICALITY_INPUT_DEPENDENCIES_CAVEAT
        ),
        "audit_trail_reference": (
            commentary_text.CRITICALITY_NOTE_AUDIT_TRAIL_REFERENCE
        ),
    }




# ---------------------------------------------------------------------------
# Section builder
# ---------------------------------------------------------------------------


def build_criticality_section(
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    stage3_beta_result: dict[str, Any] | None,
    page4_schedule_drivers: dict[str, Any] | None = None,
    path_crossover_warn_threshold_days: float = PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS,
    chart_output_dir: Path | None = None,
    risk_titles_override: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the criticality section dict (pure-data wrapper).

    Returns
    -------
    dict[str, Any]
        Returns a fresh dict containing the Stage 3 Beta wire-up keys
        (set by :func:`_apply_stage3_beta_keys`) and the
        ``page4b_criticality`` + ``criticality_note`` keys (set by
        :func:`_apply_criticality_keys`). Empty dict when
        ``stage3_beta_result`` is ``None`` — the Stage 2.5 production
        path does not produce criticality data.

    Notes
    -----
    The Stage 2.5 composer calls ``_apply_stage3_beta_keys`` and
    ``_apply_criticality_keys`` directly on its in-progress ``composed``
    dict for path-of-least-resistance reasons (the orchestrators read
    ``page4_schedule_drivers["drivers_table"]`` for the top-3 risk
    ranking). This wrapper exists so SR14b's Stage 3 standalone
    composer can obtain the same data dict as a fresh return value:

        composed_seed = {"page4_schedule_drivers": page4_schedule_drivers}
        criticality = build_criticality_section(..., page4_schedule_drivers=...)
        composed.update(criticality)

    Decision D3=A: narrative substitutions inside the orchestrators
    pull from ``commentary_text`` directly — narrative belongs to the
    Stage 2.5 composer; SR14b replicates the same pattern with its
    own templates if needed.
    """
    if stage3_beta_result is None:
        return {}
    composed_local: dict[str, Any] = {}
    if page4_schedule_drivers is not None:
        composed_local["page4_schedule_drivers"] = page4_schedule_drivers
    _apply_stage3_beta_keys(
        composed_local,
        integrated_results_by_scenario,
        stage3_beta_result,
        path_crossover_warn_threshold_days,
        chart_output_dir=chart_output_dir,
        risk_titles_override=risk_titles_override,
    )
    return composed_local
