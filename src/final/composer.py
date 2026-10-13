# SR9 v3 amendment - 2026-04-26 - presentation-layer reframe.
"""SR9 composition entry point.

Single nested-dict producer. Notebook traverses once; word_generator plucks
the executive_summary slice. Replaces v1's split between separate compose
functions to avoid drift on shared computations (top-3 drivers, headline
range).

Section docstrings describe the nested dict shape returned by
compose_final_report_data. Documented constants (key findings,
methodology caveats, recommendations, schedule basis note) live here as
the closest SR9 comes to acceptable hardcoding - methodology language is
intentionally consistent across runs.

SR9 v3 extension: when v3 inputs (risks, chart_output_dir,
programme_duration_days, etc.) are supplied, the returned dict is
extended with page1..page8_audit_trail keys for the 6-8 page executive
summary. Backward compatible: when v3 inputs are omitted, returned dict
contains only v2 keys and consumers operate as before.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.integrated.run_config_contract import require_day_rate
from src.rng_streams import require_seed
from src.sra.methodology_defaults_reader import read_calibration_tolerances
from src.final import callout_text, commentary_text, contract_terms, disclaimer_text
from src.final.sections.action_implications import (
    _build_specific_recommendations,
    _build_treatment_roi_table,
    build_action_implications_section,
)
from src.final.sections.audit_trail import (
    _build_counterfactual_narrative,
    _hash_file,
    build_audit_trail_section,
    build_cross_validation_sentence,
)
from src.final.sections.cost_drivers import (
    CG_DESCRIPTION_NOT_IN_REGISTER,
    _RBS_UNASSIGNED_LABEL,
    _build_cost_tornado_data,
    _filter_cost_drivers_for_table,
    _rbs_l1_label,
    build_cg_drivers_table,
    build_cost_drivers_section,
    build_rbs_l1_cost_breakdown,
)
from src.final.sections.criticality import (
    PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS,
    _apply_criticality_keys,
    _apply_stage3_beta_keys,
    _build_activity_dates_from_xer,
    _build_auto_mapper_zero_expansion_notice,
    _build_phase_map_from_xer,
    _ci_band,
    _compute_path_crossover_delta,
    _read_zero_expansion_risk_ids,
    _render_auto_mapper_audit_table,
    _render_risk_linkage_table_png,
    _resolve_schedule_window,
    _stage3_beta_unmapped_top_drivers,
    build_criticality_section,
    build_risk_to_activity_bridge,
    build_risk_to_cp_linkage_table,
    compute_ci_distribution_summary,
    compute_criticality_table,
    compute_extended_ci_table,
    pick_near_critical_activities,
)
from src.final.sections.page1_table import (
    _build_comparison_table,
    _build_component_breakdown_table,
    _build_dedup_footnote,
    _compute_component_breakdown,
    _dedupe_scenarios_by_signature,
    _waterfall_components,
    build_page1_table_section,
    build_page5_reconciliation_section,
    build_six_approach_reconciliation_table,
)
from src.final.sections.risk_matrix import (
    _build_risk_matrix_data,
    build_risk_matrix_section,
)
from src.final.sections.s_curves import (
    _build_confidence_curve,
    build_s_curves_section,
)
from src.final.sections.schedule_drivers import (
    _build_probability_weighted_schedule_drivers,
    build_mode_sensitivity_summary,
    build_rbs_l1_schedule_breakdown,
    build_schedule_drivers_section,
)
from src.final.sections.walkthrough import (
    _build_single_iteration_walkthrough,
    build_walkthrough_section,
)
from src.final.headline import STAGE3_SCENARIO_DISPLAY, STAGE3_SCENARIO_NAME
from src.final.executive_summary import (
    INDICATIVE_SCENARIO_DISPLAY,
    INDICATIVE_SCENARIO_NAME,
    count_modes,
    detect_strawman_variant,
    enrich_tail_risk_for_matrix,
    format_comparison_interpretation,
    format_distribution_interpretation,
    format_mode_mix,
    format_risk_matrix_interpretation,
    format_risk_matrix_orienting,
    format_scenario_label,
    pick_tail_risk,
    resolve_headline_metric,
    resolve_indicative_scenario_display,
    resolve_indicative_scenario_name,
    get_diversification_summary,
    get_headline_contingency_range,
    get_top_n_risk_drivers,
)
from src.final.charts import (
    SCENARIO_COLORS,
    MODE_COLORS,
    make_confidence_waterfall,
    make_density_histogram,
    make_methodology_convergence_chart,
    make_risk_matrix,
    make_s_curve,
    make_tornado_chart,
)
from src.integrated.integrated_simulation import IntegratedConfig
# read_treatments: composer no longer reads the Treatments sheet directly
# under SR14a.2; the section builder in
# ``src.final.sections.action_implications`` consumes it. Import retained
# at module load to preserve the unused-import-trip-on-failed-import
# behaviour SR9 v3.4 added.
from src.sra.strawman_reader import read_treatments  # noqa: F401

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Documented narrative constants (acceptable hardcoding per brief)
# ----------------------------------------------------------------------------

SCHEDULE_BASIS_NOTE = (
    "Schedule drivers are reported under the alternate Mode scenario. A near-all-Parallel "
    "baseline mix can leave only one materially contributing driver, which tells the reader "
    "little; the alternate scenario applies Series and Hybrid classifications to the remaining "
    "dual-coded risks so the drivers that would emerge under a working classification are "
    "visible."
)

KEY_FINDINGS = [
    "Joint sampling produces a measurable diversification benefit at the "
    "All Series upper-bound scenario, confirming the integrated approach's "
    "methodological value over naive sum of independent runs.",
    "Cost contingency is dominated by a small number of high-pessimistic "
    "risks; the top-3 cost drivers account for the majority of the P80 "
    "headline contribution.",
    "Schedule contribution is highly sensitive to Mode classification. A near-all-Parallel "
    "baseline can leave a single contributing driver where the Series and all-Series "
    "scenarios surface several; the driver table under each scenario shows which.",
    "Where one risk fires rarely and is large when it does, it drives the upper percentiles "
    "on its own. Such a risk is reported separately in the executive summary so the reader "
    "can assess the tail behaviour rather than have it averaged into the headline.",
    "Cross-validation against standalone cost and schedule engines passes "
    "within tolerance, confirming the integrated engine reconciles with "
    "the underlying methodologies.",
]

# STAGE3HEADLINE-01 (F-43, 10/09/2026): the three constants above are written around the
# Stage 2.5 three-scenario Mode range. When a Stage 3 result leads the deliverable, these
# are the texts that describe what the page now shows. Selected in compose_final_report_data
# on the presence of stage3_beta_result; the dev-mode texts above are unchanged.
SCHEDULE_DRIVERS_BASIS_STAGE3 = "additive per-risk draws, Mode-scaled (comparator basis)"
SCHEDULE_BASIS_NOTE_STAGE3 = (
    "Schedule drivers are ranked by each risk's additive, Mode-scaled per-risk draw from the "
    "Stage 3 cost arm's joint sample. That is the comparator basis, not the CPM replay: the "
    "CPM kernel reports the project finish and each activity's criticality, and does not "
    "attribute the finish to individual risks. The headline figure is the CPM replay; the "
    "driver ranking is not, and a CPM attribution by leave-one-out is owed (CPMATTRIB-01). "
    "Stage 3 has no Mode classification, so the Mode column reads n/a."
)
KEY_FINDINGS_STAGE3 = [
    "The headline contingency is the P80 of one integrated distribution: cost plus "
    "dollarised schedule delay from the Stage 3 CPM replay. Its P50 to P95 spread is "
    "project uncertainty, not a spread between Mode assumptions.",
    "Cost contingency is dominated by a small number of high-pessimistic risks; the top-3 "
    "cost drivers account for the majority of the P80 headline contribution.",
    "Schedule contribution to the headline follows where each risk's delay lands in the "
    "programme logic. Delays injected at zero-float gates reach the finish; delays injected "
    "into floated work are absorbed, so the Stage 3 figure can sit either side of the "
    "additive Stage 2.5 comparator, and the reconciliation table shows which. The per-risk "
    "driver ranking is still the additive comparator basis (see the schedule drivers note).",
    "The Stage 2.5 Mode-scenario range is retained beside the reconciliation as a labelled "
    "comparator, for continuity with what has been reported before. It is not the headline "
    "and no shipping gate depends on it.",
    "Cross-validation passes: the cost arm reconciles against the standalone cost engine, "
    "and the schedule arm reconciles across the two product surfaces that assemble a "
    "Stage 3 run, within the register's tolerances.",
]
METHODOLOGY_CAVEATS_STAGE3 = [
    "The headline is a single Stage 3 distribution. Mode classifications play no part in "
    "it; they remain visible only in the Stage 2.5 comparator range beside the "
    "reconciliation.",
    "Schedule analysis operates on the full programme logic exported from the planning "
    "tool. Delays propagate along that logic; a gating activity outside a risk's cohort is "
    "refused before any iteration runs.",
    "Liquidated damages and IDC layers are deferred to a later stage pending commercial "
    "input confirmation.",
]

def _methodology_caveats() -> list[str]:
    """The Stage 2.5 comparator's methodology caveats.

    PRESENT-01 (P-3): these named one project's risks, one contract's deferred layers and two
    parties by literal, and repeated the longest-path claim the Director corrected in the
    disclaimer on 18/09/2026. The parties come from the binding, the deferred-layer caveat from
    the contract type, and the replay description from what the engine does.
    """
    from src.sra.cpm.bindings import get_active_binding

    parties = get_active_binding().party_labels
    caveats = [
        "The headline range presents three Mode scenarios (baseline, alternate, all-Series "
        "upper bound) so the sensitivity to classification is visible. Reclassification "
        "shifts the range.",
        "Schedule analysis replays the full activity network exported from the planning tool. "
        "The critical path is an output of each iteration, so an activity off the planned "
        "critical path contributes to finish-date slip whenever sampling puts it on the path.",
        f"{parties.get('contractor', 'Contractor')}, {parties.get('owner', 'Owner')} and "
        f"{parties.get('shared', 'shared')} views are deferred to a later stage pending "
        "risk-share parameter confirmation. The current deliverable is the "
        f"{parties.get('whole_project', 'whole-project').lower()} view only.",
        "Where one risk fires rarely and is large when it does, P95 and P99 carry significant "
        "estimation uncertainty under classifications that put it in series.",
    ]
    if contract_terms.term("deferred_commercial_layers_note") is not None:
        caveats.insert(2, (
            "Liquidated damages and IDC layers are deferred to a later stage "
            "pending commercial input confirmation."
        ))
    return caveats

def _standing_recommendations() -> list[str]:
    """The executive summary's standing recommendations.

    PRESENT-01 (P-3/D-3): this was a constant list, rendered on every run, that named one
    project's risk and its transformer, that firm's working assumption, a three-scenario range
    the Stage 3 headline does not have, and a contract's liquidated-damages layer as though every
    project had one. What is left is what is true of any run of this product; the recommendations
    that depend on *this* run - which drivers to treat, which risk carries the tail - are built
    from the run on page 6.
    """
    recs = [
        f"Adopt the {contract_terms.term('headline_contingency_inline')} at P80. The "
        "P50-to-P95 spread either side of it is this project's uncertainty, and the "
        "confidence curve shows what a different confidence level would cost.",
        "Re-run against the strawman when it is reissued: it is the source of the schedule "
        "classifications and the run configuration, and the deliverable supersedes its prior "
        "version rather than being amended in place.",
    ]
    _deferred = contract_terms.term("deferred_commercial_layers_note")
    if _deferred is not None:
        recs.append(
            "Confirm the deferred commercial parameters so the layers named in the "
            "methodology caveats can be added in the next stage."
        )
    recs.append(
        "Use the per-risk diagnostic outputs (audit trail appendix) to drive "
        "targeted risk treatment plans for the top-3 cost and schedule drivers."
    )
    return recs


# ----------------------------------------------------------------------------
# v3 helpers
# ----------------------------------------------------------------------------

def _risk_attr(r: Any, name: str, default: Any = None) -> Any:
    """Read a field off a RiskInput-like object or dict."""
    if isinstance(r, dict):
        return r.get(name, default)
    return getattr(r, name, default)


# _build_probability_weighted_schedule_drivers: moved to src.final.sections.schedule_drivers under
# SR14a.2; re-exported above.




# build_rbs_l1_schedule_breakdown: moved to src.final.sections.schedule_drivers under
# SR14a.2; re-exported above.




# build_mode_sensitivity_summary: moved to src.final.sections.schedule_drivers under
# SR14a.2; re-exported above.




def _build_scenario_display_lookup(variant: str | None = None) -> dict[str, str]:
    """Build {scenario_id: display_label} for the three scenarios.

    PRESENT-01 (D-4): this read the engine's ``mode_used`` dicts, because the dev legend
    embedded the run's mode-mix string. A client legend does not carry the mix, so the label no
    longer depends on the run and the results argument has gone with it.

    Beta-14: `variant` is threaded so the DP_Review label is remapped to
    "All <Variant>" for variant strawman runs (Series/Hybrid/Parallel) —
    the strawman's Mode_Aggregated is uniformly the variant override, so
    "DP Review baseline" misnames the headline scenario for those runs.
    """
    lookup: dict[str, str] = {}
    for name in ("DP_Review", "Dummy_Realistic", "All_Series"):
        lookup[name] = format_scenario_label(name, variant=variant)
    return lookup


def _scenario_display(name: str, lookup: dict[str, str] | None = None) -> str:
    """Resolve a scenario_id to its display label.

    Pre-v3.5 callers passed only `name`; v3.5+ callers should pass the lookup built by
    `_build_scenario_display_lookup`. Without one, the label is built from the name alone,
    which keeps backward compat for any in-tree caller still using the single-arg signature.
    """
    if lookup is not None and name in lookup:
        return lookup[name]
    return format_scenario_label(name)


_HEADLINE_SUFFIX = " — headline"


def _generate_v3_charts(
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    cost_drivers_top_n: list[dict[str, Any]],
    schedule_drivers_top_n: list[dict[str, Any]],
    risk_matrix_data: list[dict[str, Any]],
    chart_output_dir: Path,
    day_rate: float,
    scenario_display_lookup: dict[str, str] | None = None,
    variant: str | None = None,
    headline_metric: str = "P80",
    indicative_name: str | None = None,
    *,
    seed: int,
) -> dict[str, str]:
    """Generate all v3 chart PNGs and return their paths as strings.

    Beta-16 Items 1 & 2: ``headline_metric`` (``"P80"`` default, or
    ``"Mean"``) drives the cost-tornado title and x-axis label so they
    match the metric used to rank ``cost_drivers_top_n``. Beta-16 Item 2
    additionally produces a cost-only S-curve (``cost_s_curve_path``) and
    density histogram (``cost_density_path``) from the integrated engine's
    cost arm under the indicative scenario, restoring the symmetric
    cost-vs-schedule graphical treatment dropped in the SR9 v3 trim.
    """
    cost_metric_label = (
        "Mean" if str(headline_metric).strip().lower() == "mean" else "P80"
    )
    chart_output_dir = Path(chart_output_dir)
    chart_output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    # S-curve: schedule slip across three scenarios.
    # Beta-14 §2: DP_Review is the strawman-driven headline scenario;
    # render comparators first (faded) and DP_Review last (solid, heavy,
    # zorder above the percentile reference lines). The headline curve's
    # legend label gets a " — headline" suffix so the legend reads
    # unambiguously.
    # Series-variant collapse: under a Series strawman, DP_Review and
    # All_Series produce numerically identical samples (both apply the
    # all-Series override). Suppress All_Series from the s-curve legend
    # in that case so the chart shows two distinct curves rather than two
    # coincident lines with different labels.
    s_curve_dist: dict[str, np.ndarray] = {}
    collapse_all_series = variant == "Series"
    # STAGE3HEADLINE-01: when Stage 3 is the named basis it is plotted last and carries the
    # headline suffix; DP_Review is then a comparator like the others.
    _stage3_leads = indicative_name == STAGE3_SCENARIO_NAME and STAGE3_SCENARIO_NAME in integrated_results_by_scenario
    iter_order = (
        ("Dummy_Realistic", "All_Series", "DP_Review", STAGE3_SCENARIO_NAME) if _stage3_leads
        else ("Dummy_Realistic", "All_Series", "DP_Review"))
    _headline_scenario = STAGE3_SCENARIO_NAME if _stage3_leads else "DP_Review"
    headline_label: str | None = None
    for name in iter_order:
        res = integrated_results_by_scenario.get(name)
        if res is None:
            continue
        if collapse_all_series and name == "All_Series":
            continue
        arr = res.get("schedule_days_array")
        if arr is None or len(arr) == 0:
            continue
        label = _scenario_display(name, scenario_display_lookup)
        if name == _headline_scenario:
            label = f"{label}{_HEADLINE_SUFFIX}"
            headline_label = label
        s_curve_dist[label] = np.asarray(arr)

    # Colour map must use the same labels we plotted under (including the
    # headline suffix on DP_Review).
    s_curve_color_map: dict[str, str] = {}
    for k, v in SCENARIO_COLORS.items():
        if collapse_all_series and k == "All_Series":
            continue
        if k not in integrated_results_by_scenario:
            continue
        label = _scenario_display(k, scenario_display_lookup)
        if k == _headline_scenario:
            label = f"{label}{_HEADLINE_SUFFIX}"
        s_curve_color_map[label] = v

    s_curve_path = chart_output_dir / "page2_s_curve.png"
    make_s_curve(
        distributions=s_curve_dist,
        percentile_markers=[50, 80, 90, 95],
        # DELIVFIX-01 (FW-28): the headline is Stage 3, which applies no Mode multiplier; the
        # Mode scenarios beside it are comparators, so "three Mode scenarios" misread the chart.
        title=("Schedule slip S-curve - Stage 3 headline, with Mode comparators"
               if _stage3_leads else "Schedule slip S-curve - three Mode scenarios"),
        output_path=s_curve_path,
        color_map=s_curve_color_map,
        headline_label=headline_label,
        # SR-S3-Beta-18 §4: per-percentile drop-lines + day labels on
        # the headline curve so the reader can read the value at each
        # P-level off the chart directly.
        value_label_fmt="{value:.1f}d",
    )
    paths["s_curve_path"] = str(s_curve_path.resolve())

    # Density histogram for indicative scenario.
    _indicative_name = indicative_name or resolve_indicative_scenario_name()
    _indicative_display = (
        _scenario_display(_indicative_name, scenario_display_lookup) if indicative_name
        else resolve_indicative_scenario_display())
    indicative = integrated_results_by_scenario.get(_indicative_name, {})
    indicative_sched = np.asarray(indicative.get("schedule_days_array", []))
    if indicative_sched.size > 0:
        pct_markers = {
            int(p): float(np.percentile(indicative_sched, p))
            for p in (50, 80, 90, 95)
        }
        density_path = chart_output_dir / "page2_density.png"
        make_density_histogram(
            samples=indicative_sched,
            title=f"Schedule slip distribution - {_indicative_display}",
            output_path=density_path,
            mean_value=float(indicative_sched.mean()),
            percentile_markers=pct_markers,
        )
        paths["density_path"] = str(density_path.resolve())
    else:
        paths["density_path"] = ""

    # Beta-16 Item 2: cost outturn distribution — single-curve S-curve +
    # density histogram for the indicative scenario's cost arm. Cost MC
    # is Mode-independent so a single curve is correct (brief Decision 4).
    # No P(no slip) callout — cost MC has no zero spike to surface (brief
    # Decision 4); rendered in $M for readability.
    indicative_cost = np.asarray(indicative.get("cost_dollars_array", []))
    if indicative_cost.size > 0:
        indicative_cost_m = indicative_cost / 1e6
        cost_s_curve_path = chart_output_dir / "page2_cost_s_curve.png"
        cost_s_curve_label = "Total event-risk cost (integrated cost arm)"
        make_s_curve(
            distributions={cost_s_curve_label: indicative_cost_m},
            percentile_markers=[50, 80, 90, 95],
            title="Event-risk cost S-curve - integrated cost arm",
            output_path=cost_s_curve_path,
            x_axis_label="Total event-risk cost ($M)",
            color_map={cost_s_curve_label: "#1F4E79"},
            # SR-S3-Beta-18 §4: per-percentile drop-lines + dollar
            # labels on the cost curve. Reader can read the dollar
            # value at each P-level off the chart directly.
            value_label_fmt="${value:.2f}M",
        )
        paths["cost_s_curve_path"] = str(cost_s_curve_path.resolve())

        cost_pct_markers = {
            int(p): float(np.percentile(indicative_cost_m, p))
            for p in (50, 80, 90, 95)
        }
        cost_density_path = chart_output_dir / "page2_cost_density.png"
        make_density_histogram(
            samples=indicative_cost_m,
            title=f"Event-risk cost distribution - {_indicative_display}",
            output_path=cost_density_path,
            mean_value=float(indicative_cost_m.mean()),
            percentile_markers=cost_pct_markers,
            x_axis_label="Total event-risk cost ($M)",
            color="#1F4E79",
            nil_bucket_annotation=False,
        )
        paths["cost_density_path"] = str(cost_density_path.resolve())
    else:
        paths["cost_s_curve_path"] = ""
        paths["cost_density_path"] = ""

    # Cost tornado.
    # Beta-16 Item 1: title and x-axis label track the headline metric so
    # the chart's framing matches the ranking metric used to build
    # ``cost_drivers_top_n``. The Mean docx labels the bars as Mean
    # contribution; the P80 docx labels them as P80 contribution.
    cost_tornado_path = chart_output_dir / "page3_cost_tornado.png"
    make_tornado_chart(
        ranked_risks=cost_drivers_top_n,
        title=f"Top cost contributors ({cost_metric_label} contribution)",
        x_axis_label=f"{cost_metric_label} cost contribution ($M)",
        output_path=cost_tornado_path,
        value_format="${:.2f}M",
    )
    paths["cost_tornado_path"] = str(cost_tornado_path.resolve())

    # Schedule tornado, colour-coded by Mode.
    sched_tornado_data = [
        {
            "risk_id": d["risk_id"],
            "title": d.get("title", d["risk_id"]),
            "value": d.get("prob_weighted_mean_days", 0.0),
            "color_category": d.get("mode", ""),
            "pct_of_total": d.get("pct_of_total_mean"),
        }
        for d in schedule_drivers_top_n
    ]
    sched_tornado_path = chart_output_dir / "page4_schedule_tornado.png"
    make_tornado_chart(
        ranked_risks=sched_tornado_data,
        title="Top schedule contributors (probability-weighted mean, days)",
        x_axis_label="Probability x mean impact (days)",
        output_path=sched_tornado_path,
        color_map=MODE_COLORS,
        value_format="{:.2f} d",
    )
    paths["schedule_tornado_path"] = str(sched_tornado_path.resolve())

    # Risk matrix.
    risk_matrix_path = chart_output_dir / "page4_risk_matrix.png"
    make_risk_matrix(
        risks=risk_matrix_data,
        output_path=risk_matrix_path,
    )
    paths["risk_matrix_path"] = str(risk_matrix_path.resolve())

    # Confidence-band waterfall.
    waterfall_path = chart_output_dir / "page5_waterfall.png"
    waterfall_components = _waterfall_components(
        integrated_results_by_scenario, day_rate, indicative_name=_indicative_name)
    make_confidence_waterfall(
        components=waterfall_components,
        title="Integrated P80 build-up: cost + dollarised schedule + joint adjustment",
        output_path=waterfall_path,
    )
    paths["waterfall_path"] = str(waterfall_path.resolve())

    # Beta-15 Item 2: §7 convergence diagnostic chart. Bootstrap CI on the
    # integrated cost P80 across iteration counts 1k → 100k. Falls back
    # gracefully on smoke runs (bootstrap_convergence collapses iter_grid
    # entries above sample size to a single grid point at n_iter).
    convergence_indicative = integrated_results_by_scenario.get(_indicative_name, {})
    convergence_cost_arr = np.asarray(
        convergence_indicative.get("cost_dollars_array", [])
    )
    if convergence_cost_arr.size > 0:
        convergence_path = chart_output_dir / "page7_convergence.png"
        # Outside the try: a missing seed is refused, not logged into an absent chart.
        seed = require_seed(seed, where="src.final.composer page-7 convergence chart")
        try:
            make_methodology_convergence_chart(
                sample=convergence_cost_arr,
                output_path=convergence_path,
                percentile=80.0,
                metric_label="integrated P80 cost",
                seed=seed,  # the run's: the page-7 resample reproduces from its record
            )
            paths["convergence_chart_path"] = str(convergence_path.resolve())
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Convergence chart generation failed: %s", e,
            )

    return paths


# _compute_component_breakdown: moved to src.final.sections.page1_table under SR14a.2;
# re-exported above.




# _waterfall_components: moved to src.final.sections.page1_table under SR14a.2;
# re-exported above.




# _build_component_breakdown_table: moved to src.final.sections.page1_table under SR14a.2;
# re-exported above.




# _build_confidence_curve: moved to src.final.sections.s_curves under
# SR14a.2 (session B); re-exported above.




def _write_page1_narrative_and_drop_dev_keys(
    composed: dict[str, Any], *, keep_range_table: bool = False, stage3: bool = False,
    mean_days: float | None = None, top3_pct: float | None = None,
    dual_coded_count: int | None = None, tail_risk: dict[str, Any] | None = None,
) -> None:
    """Write the page-1 narrative from this run's numbers, and drop the keys the report does
    not carry.

    It runs late because the numbers it needs - the P80 row of the confidence curve, the top
    driver's share - are not composed until after page 1's own section is built.

    PRESENT-01 (D-4): this was ``_apply_prod_mode_overrides``. It re-formatted a "prod twin" of
    each sentence over a dev sentence the composer had just written, and recovered the numbers
    for two of them by **regexing them back out of that dev sentence** - so a reworded dev
    string silently changed a prod number to a fallback. The dev sentences are gone (the entry
    point refuses any mode but prod), the numbers arrive as arguments, and each key is written
    once.

    Modifies `composed` in place.
    """
    # ---- Drop the keys the deliverable does not carry ----
    # STAGE3HEADLINE-01 D-2: when Stage 3 leads, the range table is the Stage 2.5 comparator
    # beside the reconciliation and stays in prod; otherwise it is dev-only as before.
    if not keep_range_table:
        composed["page1_range_table"] = []
    composed["page1_reading_convention"] = ""
    composed["page1_reading_convention_title"] = ""
    composed["page1_mode_caveat"] = ""
    composed["page1_mean_cost_identical_note"] = ""

    if isinstance(composed.get("callouts"), dict):
        composed["callouts"]["why_mc_matters"] = ""
        composed["callouts"]["how_ages_well"] = ""

    if isinstance(composed.get("page4_schedule_drivers"), dict):
        composed["page4_schedule_drivers"]["mode_sensitivity_table"] = pd.DataFrame()
        composed["page4_schedule_drivers"]["criticality_reframe"] = ""

    if isinstance(composed.get("page5_reconciliation"), dict):
        composed["page5_reconciliation"]["cross_validation_panel"] = {}

    if isinstance(composed.get("page7_methodology"), dict):
        composed["page7_methodology"]["dp_review_caveat"] = ""
        composed["page7_methodology"]["limitations_current"] = list(
            commentary_text.LIMITATIONS_CURRENT
        )

    # Page 3 cost-drivers mode-independence note (dev-only — names "Mode")
    if isinstance(composed.get("page3_cost_drivers"), dict):
        composed["page3_cost_drivers"]["mode_independence_note"] = ""

    # ---- Swap text-variant fields (page1_*, page2_preamble) ----
    cc = composed.get("page2_confidence_curve") or []
    p80_row = next(
        (r for r in cc if r.get("confidence_level") == "P80"), None,
    )
    if p80_row:
        composed["page1_headline_integrated"] = (
            commentary_text.HEADLINE_INTEGRATED_P80.format(
                integrated_p80_m=p80_row["integrated_contingency_m"],
            )
        )
        # The mean arrives as an argument. It used to be read back out of the sentence above
        # with a regex, which meant a reworded sentence changed the number.
        mean_days = (
            float(mean_days) if mean_days is not None
            else float(p80_row["schedule_slip_days"])
        )
        _schedule_days_context_template = (
            commentary_text.SCHEDULE_DAYS_CONTEXT_STAGE3 if stage3
            else commentary_text.SCHEDULE_DAYS_CONTEXT
        )
        composed["page1_schedule_context"] = (
            _schedule_days_context_template.format(
                p80_days=p80_row["schedule_slip_days"],
                mean_days=mean_days,
            )
        )

    composed["page2_confidence_curve_preamble"] = (
        commentary_text.CONFIDENCE_CURVE_PREAMBLE
    )

    # Page 1 top-driver dominance text
    top = composed.get("page1_top_schedule_driver") or {}
    if isinstance(top, dict) and top.get("risk_id"):
        top_pct = float(top.get("pct_of_total_mean", 0.0) or 0.0)
        top_short_title = (
            str(top.get("title", "")).split(" - ")[0].split(",")[0].strip()
        )
        if top_pct >= 0.5:
            top["dominance_text"] = (
                commentary_text.resolve_dominant_risk_template(
                    fallback=False, stage3=stage3
                ).format(
                    top_risk_id=top["risk_id"],
                    top_risk_short_title=top_short_title,
                    top_risk_pct=top_pct,
                )
            )
        else:
            # The three-driver share arrives as an argument; it used to be read back out of the
            # sentence this replaces, and fell back to the single driver's share when the regex
            # missed - a different number, printed as though it were the same one.
            share = float(top3_pct) if top3_pct is not None else top_pct
            top["dominance_text"] = (
                commentary_text.resolve_dominant_risk_template(
                    fallback=True, stage3=stage3
                ).format(
                    top3_pct=share,
                )
            )

    # Page 1 component breakdown - replace dev "Under interim" note
    bd = composed.get("page1_component_breakdown") or []
    for row in bd:
        if isinstance(row, dict):
            note = str(row.get("Notes", ""))
            if "indicative" in note.lower():
                row["Notes"] = "Schedule contingency dollarised at day rate"

    # Page 2 distribution orienting - swap to prod twin
    p2d = composed.get("page2_distribution")
    if isinstance(p2d, dict):
        p2d["orienting"] = commentary_text.DISTRIBUTION_ORIENTING

    # Page 4 schedule drivers
    # NOTE: SR17 §5.3 gating-collision note assignment happens in
    # src/final/sections/criticality.py::_apply_stage3_beta_keys (which
    # runs AFTER this prod-mode pass; beta_flag is set there). Keeping
    # the assignment in a single location keyed off beta_flag avoids
    # ordering bugs.
    p4 = composed.get("page4_schedule_drivers")
    if isinstance(p4, dict):
        p4["orienting_tornado"] = commentary_text.SCHEDULE_TORNADO_ORIENTING
        p4["interpretation_tornado"] = commentary_text.SCHEDULE_TORNADO_INTERPRETATION
        # Remap "Mode (Dummy Realistic)" column key to "Mode" in the
        # cached drivers_table (the fixture pickle was generated under
        # dev mode; live prod composer already uses the neutral key).
        drivers = p4.get("drivers_table") or []
        for row in drivers:
            if isinstance(row, dict) and "Mode (Dummy Realistic)" in row:
                row["Mode"] = row.pop("Mode (Dummy Realistic)")

    # PRESENT-01 (D-4): a filter stood here that dropped any page-6 recommendation naming
    # "PM review" or "Mode classifications" and substituted a neutral one, and a second pass
    # that rewrote the treatment-ROI "Type" column's dev labels by string replacement. Both
    # matched on the exact words of texts this brief removed at source, so both now pass
    # everything through unchanged. Matching rendered text to decide what to print is the
    # shape that made a reworded dev string able to change a client number.

    # PRESENT-01 (P-3): the disclaimer is written here and nowhere else, because this is the
    # only point at which the run's own figures - how many risks are time-impacting, which one
    # carries the tail - are known. Two of its paragraphs state them.
    _disclaimer = disclaimer_text.get_paragraphs(
        dual_coded_count=dual_coded_count, tail_risk=tail_risk,
    )
    composed["disclaimer_paragraphs"] = _disclaimer

    # Page 7 summary paragraphs (first 4 of disclaimer paragraphs)
    if isinstance(composed.get("page7_methodology"), dict):
        composed["page7_methodology"]["summary_paragraphs"] = (
            disclaimer_text.methodology_summary(_disclaimer)
        )


def _apply_headline_metric(composed: dict[str, Any], headline_metric: str) -> None:
    """Apply the chosen headline metric (P80 or Mean) to the composed dict.

    Runs after the rest of the composition. The component-breakdown table
    on Page 1 and the confidence-curve table on Page 2 are identical
    between the P80 and Mean outputs - this function only changes:
      - which figure feeds the Page 1 headline sentence
      - which row in the confidence curve is highlighted
      - which column in the component breakdown is highlighted (metadata)
      - which recommendation copy is rendered
      - the `headline_metric` and `recommendation_metric` keys

    Modifies `composed` in place. See SR9 v3.5 brief §2.
    """
    headline_metric = resolve_headline_metric(headline_metric)
    composed["headline_metric"] = headline_metric
    composed["recommendation_metric"] = headline_metric

    # Page 1 footnote (Mean / P80 methodology) and Page 2 footnote
    # (diversification flips negative at P90+) render in BOTH outputs.
    composed["page1_mean_footnote"] = commentary_text.MEAN_FOOTNOTE_TEXT
    composed["page2_diversification_tail_footnote"] = (
        commentary_text.DIVERSIFICATION_TAIL_FOOTNOTE_TEXT
    )

    # Mean-headline alt path: replace the headline sentence with the
    # integrated Mean figure and rewrite the recommendation copy.
    cc = composed.get("page2_confidence_curve") or []
    p80_row = next(
        (r for r in cc if r.get("is_p80") or r.get("confidence_level") == "P80"),
        None,
    )
    mean_row = next(
        (r for r in cc if r.get("is_mean") or r.get("confidence_level") == "Mean"),
        None,
    )

    if headline_metric == "Mean":
        if mean_row:
            integrated_mean_m = float(mean_row["integrated_contingency_m"])
            # SR17 §5.2 — Mean is the primary headline for shared-buffer
            # commercial structures (alliance / IPD / target outturn cost);
            # P80 retained as the AACE methodology-standard reference for
            # risk-appetite context. P80 BETA flavour (separate docx) is
            # the right deliverable for fixed-budget / lump-sum approval.
            composed["page1_headline_integrated"] = (
                f"Recommended project contingency: ${integrated_mean_m:.2f} M "
                f"(Mean integrated cost plus schedule — primary headline "
                f"for shared-buffer arithmetic; P80 retained for "
                f"risk-appetite context at "
                f"${float(p80_row['integrated_contingency_m']):.2f} M, "
                f"shown in the confidence curve below)."
                if p80_row
                else f"Recommended project contingency: ${integrated_mean_m:.2f} M "
                     f"(Mean integrated cost plus schedule — primary headline "
                     f"for shared-buffer arithmetic)."
            )
        for row in cc:
            row["is_recommended"] = bool(row.get("is_mean", False))
        # Component breakdown highlight - mark the headline column.
        composed["page1_component_breakdown_headline_col"] = "Mean"
    else:
        # P80 path: confidence curve highlight follows is_p80; behaviour-
        # preserving for the existing PROD output.
        for row in cc:
            row["is_recommended"] = bool(row.get("is_p80", False))
        composed["page1_component_breakdown_headline_col"] = "P80"


# ----------------------------------------------------------------------------
# Beta-08: Stage 3 beta wire-up helpers
# ----------------------------------------------------------------------------

# Criticality helpers (Charts 1-4 plumbing, extended CI table,
# risk-to-CP linkage, auto-mapper audit, _apply_criticality_keys,
# _apply_stage3_beta_keys, PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS):
# moved to src.final.sections.criticality under SR14a.2 (session B);
# re-exported above for backward-compatible imports.


def compose_final_report_data(
    cost_results: dict[str, Any],
    schedule_results: dict[str, Any],
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    schedule_results_by_scenario: dict[str, dict[str, Any]],
    strawman_path: Path | str,
    register_path: Path | str,
    cross_validation: dict[str, Any],
    risk_titles: dict[str, str] | None = None,
    config: IntegratedConfig | None = None,
    appendix_counterfactual: pd.DataFrame | None = None,
    run_date: str | None = None,
    engine_versions: dict[str, str] | None = None,
    risks: Iterable[Any] | None = None,
    chart_output_dir: Path | str | None = None,
    programme_duration_days: float | None = None,
    p6_path: Path | str | None = None,
    *,
    headline_metric: str = "P80",
    stage3_beta_result: dict[str, Any] | None = None,
    path_crossover_warn_threshold_days: float = PATH_CROSSOVER_DEFAULT_THRESHOLD_DAYS,
    single_iteration_transparency_df: pd.DataFrame | None = None,
    cg_descriptions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compose the full nested dict for the final report.

    Returned structure (top-level keys):
      v2 keys (always present):
      - cross_validation        : dict (passed through)
      - executive_summary       : dict (headline range, top-3 drivers, etc)
      - cost_section            : dict (cost MC arrays + risk_ids)
      - schedule_section        : dict (SR5 arrays + risk_ids + mode_used)
      - integrated_section      : dict (integrated arrays per scenario)
      - appendix_counterfactual : pd.DataFrame (12-scenario table or empty)
      - appendix_methodology    : dict (caveats, references)
      - appendix_audit_trail    : dict (paths, versions, run date)
      - disclaimer_paragraphs   : list[str]

      v3 keys (present when risks + chart_output_dir supplied):
      - page1_headline, page1_range_table
      - callouts
      - page2_distribution
      - page3_cost_drivers
      - page4_schedule_drivers
      - page5_reconciliation
      - page6_action_implications
      - page7_methodology
      - page8_audit_trail (extends appendix_audit_trail)

    See module-level docstring for design rationale.
    """

    headline_metric = resolve_headline_metric(headline_metric)

    if config is None:
        # SR19 §6.2: methodology_defaults is REQUIRED on IntegratedConfig.
        # Fallback construction path (composer called without a config)
        # reads from the register_path argument.
        #
        # DAYRATE-02 F-11: this builder omitted day_rate and then read it back
        # eleven lines down to dollarise the report, so it took the dataclass
        # default while every other input came from the workbook. It is the
        # fifth strawman-blind builder and the only one the brief did not name.
        from src.sra.methodology_defaults_reader import (
            read_methodology_defaults,
        )
        from src.integrated.run_config_contract import (
            read_run_config_strict,
            resolve_day_rate,
            resolve_programme_days,
        )
        from src.sra.strawman_reader import read_run_config

        _run_cfg = read_run_config_strict(Path(strawman_path), read_run_config)
        config = IntegratedConfig(
            register_path=Path(register_path),
            **read_calibration_tolerances(Path(register_path), caller_module="src/final/composer.py"),  # RS-D-2
            p6_path=Path(p6_path or register_path),
            strawman_path=Path(strawman_path),
            methodology_defaults=read_methodology_defaults(
                Path(register_path),
                caller_module="src/final/composer.py",
            ),
            day_rate=resolve_day_rate(_run_cfg, Path(strawman_path)),
            programme_days=resolve_programme_days(_run_cfg),
        )

    p_level = int(config.reporting_p_level)
    day_rate = require_day_rate(config.day_rate, caller="compose_final_report_data")
    run_date = run_date or date.today().isoformat()
    # DELIVFIX-01 (R-3): the package version, not sprint codes. "SP18-line" / "SR9 v3.5+mean"
    # were build history printed to a client as provenance. The production path passes the
    # engine SHA as well (deliverable.py); this default does not resolve it, so composing in a
    # unit test does not shell out to git.
    from src import __version__ as _package_version
    engine_versions = engine_versions or {"package": _package_version}

    # --- Executive summary (v2 baseline) ----------------------------------
    # Resolve the "indicative" scenario name and display label per mode.
    # Dev: Dummy Realistic (Python override). Prod: DP Review baseline
    # (single source of truth from strawman). See SR9 v3.3 Path A.
    _indicative_scenario_name = resolve_indicative_scenario_name()
    _indicative_scenario_display = resolve_indicative_scenario_display()
    # STAGE3HEADLINE-01 (Director D-1, 10/09/2026): when a Stage 3 result is present it is
    # the headline basis. Its arrays join a COPY of the scenario family under
    # STAGE3_SCENARIO_NAME, so every page-1 builder that resolves "the indicative scenario"
    # by name reads Stage 3, while the Mode family itself is untouched and stays the
    # Stage 2.5 comparator beside the reconciliation (D-2). Stage 3 has no Mode mix; its
    # display label says what it is instead.
    headline_family: dict[str, dict[str, Any]] = dict(integrated_results_by_scenario)
    if stage3_beta_result is not None:
        headline_family[STAGE3_SCENARIO_NAME] = {
            key: stage3_beta_result.get(key)
            for key in (
                "cost_dollars_array", "schedule_days_array", "per_risk_cost_array",
                "per_risk_schedule_array", "risk_ids_all", "risk_ids_dual", "iterations",
            )
        }
        _indicative_scenario_name = STAGE3_SCENARIO_NAME
        _indicative_scenario_display = STAGE3_SCENARIO_DISPLAY

    # SR-S3-Beta-14: derive variant tag from the strawman filename so the
    # DP_Review scenario's display label is remapped to "All <Variant>"
    # for variant runs. None for canonical un-suffixed strawman.
    _strawman_variant = detect_strawman_variant(strawman_path)

    # SR9 v3.5: data-driven scenario display labels and mode-mix strings.
    # Computed once per compose call; the variant is what the strawman drove the run with.
    _scenario_display_lookup = _build_scenario_display_lookup(variant=_strawman_variant)
    if stage3_beta_result is not None:
        _scenario_display_lookup[STAGE3_SCENARIO_NAME] = STAGE3_SCENARIO_DISPLAY
    _dp_review_modes = (
        schedule_results_by_scenario.get("DP_Review", {}).get("mode_used", {}) or {}
    )
    _indicative_modes = (
        schedule_results_by_scenario.get(_indicative_scenario_name, {})
        .get("mode_used", {})
        or {}
    )
    _all_series_modes = (
        schedule_results_by_scenario.get("All_Series", {}).get("mode_used", {}) or {}
    )
    dp_review_mix = format_mode_mix(_dp_review_modes)
    indicative_mix = format_mode_mix(_indicative_modes)
    all_series_mix = format_mode_mix(_all_series_modes)
    _dp_review_counts = count_modes(_dp_review_modes)
    n_parallel_dp = _dp_review_counts["Parallel"]
    n_total_dp = sum(_dp_review_counts.values())

    integrated_dp = integrated_results_by_scenario.get("DP_Review", {})
    integrated_dr = headline_family.get(_indicative_scenario_name, integrated_dp)
    # The Mode-scenario range below is computed on the Mode family only: with a Stage 3
    # result it is the Stage 2.5 comparator, and _apply_stage3_headline labels it so.

    headline_range = get_headline_contingency_range(
        integrated_results_by_scenario=integrated_results_by_scenario,
        p_level=p_level,
        day_rate=day_rate,
    )

    # STAGE3HEADLINE-01 (review W7): the cost drivers come from the arm whose cost component
    # the headline reports - the Stage 3 cost arm when it leads (joint-sampled with the
    # schedule arm), the DP_Review arm otherwise - and the heading names the arm.
    _cost_drivers_source = integrated_dr if stage3_beta_result is not None else integrated_dp
    cost_drivers_basis = (
        "Stage 3 cost arm, joint-sampled with the schedule arm" if stage3_beta_result is not None
        else "DP Review baseline")
    top_3_cost = get_top_n_risk_drivers(
        integrated_results=_cost_drivers_source,
        n=3,
        metric="cost",
        p_level=p_level,
        risk_titles=risk_titles,
    )
    top_3_sched = get_top_n_risk_drivers(
        integrated_results=integrated_dr,
        n=3,
        metric="schedule",
        p_level=p_level,
        risk_titles=risk_titles,
        day_rate=day_rate,
    )
    sched_dr = schedule_results_by_scenario.get(_indicative_scenario_name, {})
    # mode_used stays the real scenario's dict (empty when Stage 3 leads, since
    # schedule_results_by_scenario carries no "Stage3" key) - it feeds
    # enrich_tail_risk_for_matrix below, which resolves a real Mode multiplier from it.
    # Do NOT replace it with a display-only "n/a" fill here: a literal "n/a" flowing into
    # resolve_mode_multiplier raises (the register's grid has no "n/a" entry, D-14/D-15),
    # crashing the whole compose call whenever the picked tail risk happens to be dual-coded
    # (re-review-of-the-re-review BLOCKER). page4_mode_used below is the display-only variant.
    mode_used = sched_dr.get("mode_used", {}) if sched_dr else {}
    # Stage 3 has no Mode-scenario family, so page-4's mode_used must say "n/a" for every
    # dual-coded risk rather than fall through to build_schedule_drivers_section's own
    # "(unknown)" default (review re-review, sibling of the exec-summary top-3 fix below).
    # Display-only: never passed to anything that resolves a Mode multiplier.
    page4_mode_used = (
        {rid: "n/a" for rid in integrated_dr.get("risk_ids_dual", [])}
        if stage3_beta_result is not None
        else mode_used
    )
    for drv in top_3_sched:
        # Stage 3 has no Mode; the column says so rather than "(unknown)" (review W4).
        drv["mode"] = ("n/a" if stage3_beta_result is not None
                       else mode_used.get(drv["risk_id"], "(unknown)"))
        drv["basis_scenario"] = (
            SCHEDULE_DRIVERS_BASIS_STAGE3 if stage3_beta_result is not None
            else _indicative_scenario_display)

    diversification = get_diversification_summary(
        integrated_results_by_scenario=integrated_results_by_scenario,
        schedule_results_by_scenario=schedule_results_by_scenario,
        cost_only_l2_results=cost_results,
        config=config,
    )

    executive_summary = {
        "headline_contingency_range_p80": headline_range,
        "top_3_cost_drivers": top_3_cost,
        "cost_drivers_basis": cost_drivers_basis,
        "top_3_schedule_drivers": top_3_sched,
        "schedule_drivers_basis": (
            SCHEDULE_DRIVERS_BASIS_STAGE3 if stage3_beta_result is not None
            else f"{_indicative_scenario_display} basis"),
        "schedule_basis_note": (
            SCHEDULE_BASIS_NOTE_STAGE3 if stage3_beta_result is not None else SCHEDULE_BASIS_NOTE),
        "key_findings": list(
            KEY_FINDINGS_STAGE3 if stage3_beta_result is not None else KEY_FINDINGS),
        "methodology_caveats": list(
            METHODOLOGY_CAVEATS_STAGE3 if stage3_beta_result is not None else _methodology_caveats()),
        "recommendations": _standing_recommendations(),
        "diversification_summary": diversification,
    }

    # --- v2 section passthroughs -----------------------------------------
    cost_section = {
        "cost_dollars_array": cost_results.get("cost_dollars_array"),
        "per_risk_cost_array": cost_results.get("per_risk_cost_array"),
        "risk_ids": list(cost_results.get("risk_ids", [])),
        "risk_titles": dict(risk_titles or {}),
        "p_level": p_level,
    }
    schedule_section = {
        "finish_delay_days_array": schedule_results.get("finish_delay_days_array"),
        "contribution_array": schedule_results.get("contribution_array"),
        "risk_ids": list(schedule_results.get("risk_ids", [])),
        "mode_used": dict(schedule_results.get("mode_used", {})),
        "day_rate": day_rate,
        "p_level": p_level,
    }
    integrated_section = {
        "scenarios": {
            name: {
                "cost_dollars_array": d.get("cost_dollars_array"),
                "schedule_days_array": d.get("schedule_days_array"),
                "risk_ids_all": list(d.get("risk_ids_all", [])),
                "risk_ids_dual": list(d.get("risk_ids_dual", [])),
                "iterations": int(d.get("iterations", 0)),
            }
            for name, d in integrated_results_by_scenario.items()
        },
        "day_rate": day_rate,
        "p_level": p_level,
    }

    if appendix_counterfactual is None:
        appendix_counterfactual = pd.DataFrame()

    appendix_methodology = {
        "caveats": list(
            METHODOLOGY_CAVEATS_STAGE3 if stage3_beta_result is not None else _methodology_caveats()),
        "references": [
            "AACE 57R-09: Risk analysis and contingency determination using "
            "expected value (cost engine basis).",
            "AACE 65R-11: Integrated cost and schedule risk analysis using "
            "Monte Carlo simulation.",
            "PMI Practice Standard for Project Risk Management.",
        ],
        "distribution_choices_summary": (
            "PERT distributions for cost and schedule severity per risk "
            "(opt/ml/pess from the project risk register). Lognormal "
            "available for selected event risks where right-tail behaviour "
            "matters. Bernoulli gates for risk firing. Cholesky-decomposed "
            "correlated uniforms for within-CG correlation."
        ),
    }
    appendix_audit_trail = {
        "register_path": str(register_path),
        "strawman_path": str(strawman_path),
        # SR9 v3.6.1 C6: basename-only display variants used by HTML / Word
        # doc renderers. The full-path keys above are retained for state-
        # cache audit-trail completeness; rendered deliverables show
        # basenames only (machine paths leak operator information without
        # aiding the reader). The SHA-256 hashes in page8_audit_trail.
        # input_hashes carry the reproducibility weight.
        "register_path_display": Path(str(register_path)).name,
        "strawman_path_display": Path(str(strawman_path)).name,
        "run_date": run_date,
        "engine_versions": dict(engine_versions),
        "iterations": int(config.iterations),
        "random_seed": config.random_seed,
        "day_rate_dollars_per_workday": day_rate,
        "reporting_p_level": p_level,
    }

    composed: dict[str, Any] = {
        "cross_validation": dict(cross_validation),
        # STAGE3HEADLINE-01 re-review (sibling of W5): set before the v2 early return so
        # _apply_stage3_beta_keys -> _apply_stage3_headline reads the document's resolved
        # metric on both the v2 and v3 paths, not just v3's later _apply_headline_metric call.
        "headline_metric": resolve_headline_metric(headline_metric),
        "executive_summary": executive_summary,
        "cost_section": cost_section,
        "schedule_section": schedule_section,
        "integrated_section": integrated_section,
        "appendix_counterfactual": appendix_counterfactual,
        "appendix_methodology": appendix_methodology,
        "appendix_audit_trail": appendix_audit_trail,
    }

    # --- v3 extensions (only if v3 inputs supplied) ----------------------
    if risks is None:
        # Beta-08: apply Stage 3 beta keys before returning the v2-only
        # composed dict; no-op when stage3_beta_result is None. Beta-12
        # adds chart_output_dir for the page4b CI distribution chart;
        # the v2 path has no chart_output_dir kwarg so the chart is
        # skipped (the page4b narrative still renders).
        _apply_stage3_beta_keys(
            composed,
            integrated_results_by_scenario,
            stage3_beta_result,
            path_crossover_warn_threshold_days,
            risk_titles_override=risk_titles,
        )
        # The v2 path returns before the run's drivers exist, so it cannot know the tail risk;
        # its disclaimer is the run-agnostic one. The v3 path writes the run-aware version in
        # _write_page1_narrative_and_drop_dev_keys and is the only path a deliverable takes.
        composed["disclaimer_paragraphs"] = disclaimer_text.get_paragraphs(
            dual_coded_count=len(integrated_dr.get("risk_ids_dual", []) or []) or None,
        )
        return composed

    risks_list = list(risks)

    # SR14a.2: page-4 schedule drivers section-builder. Produces the
    # probability-weighted top-8 list (consumed by §1 top-driver block
    # and by chart helpers), the rendered Page-4 dict (drivers_table,
    # mode_sensitivity_table, rbs_l1_breakdown_table), and the RBS L1
    # schedule breakdown. tornado_path is threaded post-_generate_v3_charts.
    _sd = build_schedule_drivers_section(
        integrated_dr=integrated_dr,
        risks_list=risks_list,
        risk_titles=risk_titles,
        indicative_scenario_display=_indicative_scenario_display,
        mode_used=page4_mode_used,
        appendix_counterfactual=appendix_counterfactual,
        schedule_tornado_path="",  # filled after _generate_v3_charts
        stage3=stage3_beta_result is not None,
    )
    prob_weighted_sched_drivers = _sd["prob_weighted_sched_drivers"]

    # Top-N cost drivers for tornado (top 8). SR14a.2: ranking + RBS L1
    # data assembly via cost_drivers section-builder. ``tornado_path`` is
    # threaded in after chart generation below.
    _cd = build_cost_drivers_section(
        integrated_dp=_cost_drivers_source,
        risks_list=risks_list,
        risk_titles=risk_titles,
        p_level=p_level,
        headline_metric=headline_metric,
        cost_tornado_path="",  # filled in after _generate_v3_charts below
    )
    cost_drivers_full = _cd["cost_drivers_full"]

    # Risk matrix data (all open dual-coded risks). SR14a: data assembly
    # via section-builder; the chart-rendering call below consumes
    # `risk_matrix_data` unchanged.
    risk_matrix_data = build_risk_matrix_section(
        risks=risks_list,
        integrated_results=integrated_dr,
    )["data"]

    # Generate charts
    chart_paths: dict[str, str] = {}
    if chart_output_dir is not None:
        chart_paths = _generate_v3_charts(
            integrated_results_by_scenario=headline_family,
            indicative_name=_indicative_scenario_name,
            cost_drivers_top_n=cost_drivers_full,
            schedule_drivers_top_n=prob_weighted_sched_drivers,
            risk_matrix_data=risk_matrix_data,
            chart_output_dir=Path(chart_output_dir),
            day_rate=day_rate,
            scenario_display_lookup=_scenario_display_lookup,
            variant=_strawman_variant,
            headline_metric=headline_metric,
            seed=config.random_seed,
        )

    # Page 1 + Page 5: SR14a.2 — data assembly via section-builders.
    # Narrative format calls (commentary_text.X.format(...)) stay in this
    # composer per Decision D3=A.
    _p1 = build_page1_table_section(
        integrated_results_by_scenario=headline_family,
        integrated_dp=integrated_dp,
        integrated_dr=integrated_dr,
        risks_list=risks_list,
        programme_duration_days=programme_duration_days,
        day_rate=day_rate,
        p_level=p_level,
        headline_metric=headline_metric,
        scenario_display_lookup=_scenario_display_lookup,
        indicative_scenario_name=_indicative_scenario_name,
        indicative_display_short=composed.get("indicative_display_short", ""),
    )
    breakdown = _p1["breakdown"]
    mean_days_indicative = _p1["mean_days_indicative"]
    mean_cost_indicative_m = _p1["mean_cost_indicative_m"]
    lower_days = _p1["lower_days"]
    upper_days = _p1["upper_days"]
    p80_days_indicative = _p1["p80_days_indicative"]
    dp_review_p80_m = _p1["dp_review_p80_m"]
    all_series_p80_m = _p1["all_series_p80_m"]
    page1_component_breakdown = _p1["page1_component_breakdown"]
    page1_range_table = _p1["page1_range_table"]
    all_series = integrated_results_by_scenario.get("All_Series", {})  # used by callers below

    # v3 backwards-compatible headline; v3.1 layout no longer renders this.
    page1_headline = (
        commentary_text.HEADLINE_OPENING_STAGE3 if stage3_beta_result is not None
        else commentary_text.HEADLINE_OPENING
    ).format(
        mean_days=mean_days_indicative,
        mean_cost_m=mean_cost_indicative_m,
        day_rate=day_rate,
        lower_days=lower_days,
        upper_days=upper_days,
    )

    # v3.1 (D10): integrated P80 lead. Narrative format only — data
    # already in _p1["breakdown"].
    if breakdown:
        page1_headline_integrated = commentary_text.HEADLINE_INTEGRATED_P80.format(
            integrated_p80_m=breakdown["integrated_p80_m"],
        )
    else:
        page1_headline_integrated = ""

    # v3.1 (D10): schedule-in-days context narrative.
    page1_schedule_context = commentary_text.SCHEDULE_DAYS_CONTEXT.format(
        p80_days=p80_days_indicative,
        mean_days=mean_days_indicative,
        dp_review_mean_days=lower_days,
        all_series_mean_days=upper_days,
    )

    # v3.1 (D10): Mode caveat narrative.
    page1_mode_caveat = commentary_text.MODE_CAVEAT_HEADLINE.format(
        dp_review_p80_m=dp_review_p80_m,
        all_series_p80_m=all_series_p80_m,
        dp_review_mix=dp_review_mix,
        all_series_mix=all_series_mix,
    )

    # v3.1 (D4): top schedule driver - expose for runtime template access. PRESENT-01 (D-4):
    # the dominance sentence itself is written once, late, where the driver's share and the
    # three-driver share are both in hand; this block carries the shares to it.
    if prob_weighted_sched_drivers:
        page1_top_schedule_driver = dict(prob_weighted_sched_drivers[0])
        _top3_pct_of_mean = sum(
            float(d.get("pct_of_total_mean", 0.0) or 0.0)
            for d in prob_weighted_sched_drivers[:3]
        )
    else:
        page1_top_schedule_driver = {}
        _top3_pct_of_mean = None

    # SR14a.2: page1_range_table + dedup footnote already produced by
    # build_page1_table_section above. (Footnote is None when no dedup.)
    composed["page1_range_table_dedup_footnote"] = _p1["page1_range_table_dedup_footnote"]
    composed["page1_headline"] = page1_headline
    composed["page1_range_table"] = page1_range_table
    composed["page1_headline_interpretation"] = (
        commentary_text.HEADLINE_INTERPRETATION_STAGE3 if stage3_beta_result is not None
        else commentary_text.HEADLINE_INTERPRETATION)

    # v3.1 Page 1 keys (Deliverables 4, 5, 9, 10).
    composed["page1_headline_integrated"] = page1_headline_integrated
    # Beta-17 Item 3: Mean / median / buffer-choice framing paragraph.
    # Rendered between the headline figure and the six-approach
    # reconciliation table so the reader interprets the headline number
    # before being shown alternative comparator approaches.
    composed["page1_portfolio_framing"] = commentary_text.PORTFOLIO_FRAMING_PARAGRAPH
    composed["page1_component_breakdown"] = page1_component_breakdown
    # SR9 v3.6.1 C2: mean-diversification interpretation note rendered
    # beneath the breakdown table in HTML and Word doc.
    composed["page1_component_breakdown_diversification_note"] = (
        commentary_text.PAGE1_COMPONENT_BREAKDOWN_DIVERSIFICATION_NOTE
    )
    composed["page1_schedule_context"] = page1_schedule_context
    composed["page1_mode_caveat"] = page1_mode_caveat
    composed["page1_top_schedule_driver"] = page1_top_schedule_driver
    composed["page1_reading_convention_title"] = commentary_text.READING_CONVENTION_TITLE
    composed["page1_reading_convention"] = commentary_text.READING_CONVENTION.format(
        indicative_mix=indicative_mix,
        dp_review_mix=dp_review_mix,
        all_series_mix=all_series_mix,
    )
    composed["page1_mean_cost_identical_note"] = commentary_text.MEAN_COST_IDENTICAL_NOTE

    # Beta-15 Item 5: §1 six-approach reconciliation table — already
    # built by build_page1_table_section above (SR14a.2).
    composed["page1_six_approach_reconciliation"] = _p1["page1_six_approach_reconciliation"]

    # Callouts
    composed["callouts"] = {
        "why_mc_matters_title": callout_text.WHY_MC_MATTERS_TITLE,
        "why_mc_matters": callout_text.WHY_MC_MATTERS,
        "how_ages_well_title": callout_text.HOW_THIS_AGES_WELL_TITLE,
        "how_ages_well": callout_text.HOW_THIS_AGES_WELL,
    }

    # Page 2 (D11 confidence curve + distribution charts). SR14a.2
    # session B: data assembly via build_s_curves_section. Narrative
    # pieces (preamble, footnote, distribution orienting / interpretation,
    # cost-distribution orienting) injected at composer level per D3=A.
    _sc = build_s_curves_section(
        integrated_results_by_scenario=headline_family,
        indicative_name=_indicative_scenario_name,
        day_rate=day_rate,
        p_level=p_level,
        s_curve_path=chart_paths.get("s_curve_path", ""),
        density_path=chart_paths.get("density_path", ""),
        waterfall_path=chart_paths.get("waterfall_path", ""),
        cost_s_curve_path=chart_paths.get("cost_s_curve_path", ""),
        cost_density_path=chart_paths.get("cost_density_path", ""),
    )
    composed["page2_confidence_curve"] = _sc["page2_confidence_curve"]
    composed["page2_confidence_curve_preamble"] = commentary_text.CONFIDENCE_CURVE_PREAMBLE
    composed["page2_confidence_curve_footnote"] = commentary_text.CONFIDENCE_CURVE_FOOTNOTE

    # Beta-11 §3: dynamic narrative — pick the tail risk from the
    # current schedule drivers and route it through the three template
    # formatters. Falls back to the generic (no-name) variants when no
    # driver meets the prob < 5% threshold.
    _tail_risk = pick_tail_risk(prob_weighted_sched_drivers)

    # Beta-14 §3: variant-aware label for the headline / matrix-data
    # scenario, used both by the risk-matrix orienting paragraph and by
    # the Mode-multiplier-honest interpretation paragraph. Strips the
    # parenthetical suffix (e.g. "All Hybrid (Mode as registered)"
    # → "All Hybrid") so it reads naturally in narrative prose.
    _matrix_scenario_full = _scenario_display_lookup.get(
        _indicative_scenario_name, _indicative_scenario_display,
    )
    _matrix_scenario_short = _matrix_scenario_full.split(" (")[0].strip()
    # Beta-14 §3: enrich the tail risk with the raw EV PERT, Mode
    # multiplier, and Mode-weighted contribution so the matrix
    # interpretation paragraph names them honestly. Routes to the
    # Beta-14 template (vs the Beta-11 legacy template) via the dict-
    # shape detection in format_risk_matrix_interpretation.
    _tail_risk_enriched = enrich_tail_risk_for_matrix(
        _tail_risk,
        risks=risks_list,
        mode_used=mode_used,
        variant_label=_matrix_scenario_short,
        mode_multipliers=config.methodology_defaults.mode_multipliers,  # RS-D-3b
    ) or _tail_risk

    # SR14a.2 session B: page2_distribution + page2_cost_distribution
    # base dicts already produced by build_s_curves_section above.
    # Overlay narrative pieces (orienting / interpretation /
    # cost-distribution orienting) at composer level per D3=A.
    composed["page2_distribution"] = {
        **_sc["page2_distribution"],
        "orienting": commentary_text.DISTRIBUTION_ORIENTING,
        "interpretation": format_distribution_interpretation(_tail_risk),
    }
    composed["page2_cost_distribution"] = {
        **_sc["page2_cost_distribution"],
        "orienting": commentary_text.COST_DISTRIBUTION_ORIENTING,
    }

    # Page 3 (D2 cost-driver filter, D6 mode-independence note).
    # SR14a.2: data assembly already produced by build_cost_drivers_section
    # above (call _cd). Plug in tornado_path post-chart-generation, then
    # spread narrative pieces in at composer level per Decision D3=A.
    _page3 = dict(_cd["page3_cost_drivers"])
    _page3["tornado_path"] = chart_paths.get("cost_tornado_path", "")
    cost_metric_label = _page3["metric_name"]
    rbs_l1_cost_metric_name = _page3["rbs_l1_metric_name"]
    composed["page3_cost_drivers"] = {
        **_page3,
        "mode_independence_note": commentary_text.COST_DRIVERS_MODE_INDEPENDENCE_NOTE,
        "orienting": commentary_text.format_cost_tornado_orienting(cost_metric_label),
        "interpretation": commentary_text.COST_TORNADO_INTERPRETATION,
        # Beta-17 Item 4: RBS Level 1 category breakdown subsection.
        # Heading, orienting note (metric-aware), and rendered table rows.
        "rbs_l1_heading": "Contribution by RBS Level 1 category",
        "rbs_l1_orienting": (
            commentary_text.RBS_L1_COST_ORIENTING_TEMPLATE.format(
                metric_name=rbs_l1_cost_metric_name,
            )
        ),
    }

    # Page 4. SR14a.2: data assembly already produced by
    # build_schedule_drivers_section above (_sd). Plug in tornado_path
    # post-chart-generation, then overlay narrative pieces and the
    # risk-matrix orienting / interpretation strings at composer level
    # per Decision D3=A.
    _page4 = dict(_sd["page4_schedule_drivers"])
    _page4["tornado_path"] = chart_paths.get("schedule_tornado_path", "")
    composed["page4_schedule_drivers"] = {
        **_page4,
        "risk_matrix_path": chart_paths.get("risk_matrix_path", ""),
        "orienting_tornado": commentary_text.SCHEDULE_TORNADO_ORIENTING,
        "interpretation_tornado": commentary_text.SCHEDULE_TORNADO_INTERPRETATION,
        "criticality_reframe": commentary_text.CRITICALITY_REFRAME,
        "orienting_mode_sens": commentary_text.MODE_SENSITIVITY_ORIENTING,
        "interpretation_mode_sens": commentary_text.MODE_SENSITIVITY_INTERPRETATION,
        # Beta-17 Item 4: schedule RBS Level 1 category breakdown subsection.
        # Heading, orienting note, and rendered table rows. Schedule metric
        # is always probability-weighted mean (days) - not metric-aware -
        # matching the schedule tornado convention.
        "rbs_l1_heading": "Schedule contribution by RBS Level 1 category",
        "rbs_l1_orienting": commentary_text.RBS_L1_SCHEDULE_ORIENTING,
        # Beta-11a Fix 3 / Beta-14 §3: orienting paragraph names the
        # scenario the right-panel markers reflect. The Beta-14 update
        # uses the variant-aware lookup label so variant runs read
        # correctly (e.g. "All Hybrid" rather than the stale "DP Review
        # baseline") and dev / canonical runs keep their existing prose.
        "orienting_matrix": format_risk_matrix_orienting(
            _matrix_scenario_full,
        ),
        # Beta-14 §3: interpretation paragraph routes through the
        # enriched tail-risk dict so the rendered prose names raw EV
        # PERT (Mode-independent) separately from the Mode-multiplied
        # probability-weighted contribution, with the Mode multiplier
        # named explicitly.
        "interpretation_matrix": format_risk_matrix_interpretation(
            _tail_risk_enriched,
        ),
        # Beta-19 §2: forward-reference sentence that the schedule
        # drivers section renders in place of the relocated risk matrix
        # block. The actual chart, orienting prose, and interpretation
        # paragraph now sit in the appendix area.
        "risk_matrix_forward_reference": (
            "An explanatory comparison of the traditional vs "
            "probability-weighted risk matrix is included in the "
            "appendix."
        ),
    }

    # Page 5. SR14a.2: data assembly via section-builder; narrative
    # paragraphs stay in this composer (D3=A).
    _p5 = build_page5_reconciliation_section(
        risks_list=risks_list,
        integrated_dr=integrated_dr,
        schedule_results_indicative=schedule_results_by_scenario.get(
            _indicative_scenario_name, schedule_results,
        ),
        programme_duration_days=programme_duration_days,
        day_rate=day_rate,
        cross_validation=cross_validation,
        waterfall_path=chart_paths.get("waterfall_path", ""),
    )
    composed["page5_reconciliation"] = {
        **_p5,
        "orienting": commentary_text.COMPARISON_ORIENTING,
        "interpretation": commentary_text.COMPARISON_INTERPRETATION,
        "waterfall_orienting": commentary_text.WATERFALL_ORIENTING,
        # Beta-11 §3: the "{tail_risk_id}'s tail couples cost and
        # schedule" sentence is dynamically substituted from the
        # tail-risk picker. Generic fallback (no name) when no driver
        # meets the prob < 5% threshold.
        "waterfall_interpretation": format_comparison_interpretation(_tail_risk),
    }

    # Page 6. SR14a.2: data assembly via section-builder; narrative
    # (orienting, interpretation, banner) injected at this composer
    # per Decision D3=A. Treatments-sheet read happens inside the
    # section builder with the same graceful-fallback behaviour.
    _p6 = build_action_implications_section(
        cost_drivers=cost_drivers_full,
        schedule_drivers=prob_weighted_sched_drivers,
        strawman_path=strawman_path,
        headline_metric=headline_metric,
    )
    composed["page6_action_implications"] = {
        **_p6,
        "orienting": commentary_text.TREATMENT_ROI_ORIENTING,
        "interpretation": commentary_text.TREATMENT_ROI_INTERPRETATION,
        # SR-S3-Beta-18 §2: illustrative-only banner rendered above the
        # treatment ROI table. Pairs with the in-table
        # "Workshop input required" placeholder cells so a skim-reader
        # sees the placeholder status without having to read the row.
        "banner": commentary_text.ACTION_IMPLICATIONS_PLACEHOLDER_BANNER,
    }

    # Page 7. SR14a: walkthrough data assembly via section-builder;
    # surrounding methodology prose and convergence wiring stay inline.
    walkthrough = build_walkthrough_section(
        integrated_results=integrated_dr,
        risks=risks_list,
    )["walkthrough"]
    composed["page7_methodology"] = {
        # Beta-17 Item 2: distribution-shape explainer (intro + 4 bullets)
        # rendered immediately below the Methodology summary paragraphs.
        # Restores the V5-era April 13 §3.3 shape framing the trim
        # compressed; names PERT / Triangular / Lognormal / Binary so a
        # methodology reviewer can locate the rationale for each per-risk
        # distribution choice.
        "distribution_shape_explainer_intro": (
            commentary_text.DISTRIBUTION_SHAPE_EXPLAINER_INTRO
        ),
        "distribution_shape_explainer_bullets": list(
            commentary_text.DISTRIBUTION_SHAPE_EXPLAINER_BULLETS
        ),
        "standards_references": commentary_text.STANDARDS_REFERENCES,
        "dp_review_caveat": commentary_text.DP_REVIEW_CAVEAT.format(
            n_parallel_dp=n_parallel_dp,
            n_total_dp=n_total_dp,
        ),
        "limitations_current": list(commentary_text.LIMITATIONS_CURRENT),
        "limitations_closing": commentary_text.LIMITATIONS_CLOSING,
        "single_iteration_intro": commentary_text.SINGLE_ITERATION_INTRO,
        "single_iteration_walkthrough": walkthrough,
        # Beta-15 Item 6: structured per-risk transparency table from
        # run_single_scenario_transparency (the run's seed). The narrative
        # walkthrough above remains; the table makes the methodology
        # concrete for non-technical reviewers (probability, u_fire,
        # Fired?, u_dur, Drawn duration, Mode multiplier, Contribution).
        # Computed by the orchestrator (final_runner.ipynb) and passed
        # in as a kwarg; None when not supplied → word_generator skips.
        "single_iteration_table": single_iteration_transparency_df,
        # Beta-15 Item 2: convergence diagnostic chart + caveat. The
        # chart path is empty when chart_output_dir was not supplied or
        # the bootstrap call failed; word_generator's image-presence
        # guard skips render when empty.
        "convergence_chart_path": chart_paths.get("convergence_chart_path", ""),
        "convergence_caveat": commentary_text.CONVERGENCE_CAVEAT,
        "convergence_caption": (
            "Convergence diagnostic: 95% bootstrap CI on the integrated "
            "P80 cost across iteration counts 1k → 100k. Band tightens "
            "as iterations grow; convergence is reached when further "
            "iterations no longer materially shift the band."
        ),
        # Beta-15 Item 3: 4-row Mode-sensitivity summary. Variant-aware
        # bolding via build_mode_sensitivity_summary; word_generator
        # reads bold_row_index and applies bold formatting to that row.
        # Beta-19b item 5: pass the live integrated headline P80 (the
        # §1 figure) so the headline row reconciles to it instead of
        # showing an independent counterfactual re-run's value.
        "mode_sensitivity_summary": build_mode_sensitivity_summary(
            appendix_counterfactual,
            _strawman_variant,
            headline_p80_override_days=p80_days_indicative,
        ),
        # Beta-17 Item 5: Correlation Group (CG) drivers subsection.
        # Sits between Standards references and Limitations of current
        # analysis per brief Decision 5. Rendered as: two orienting
        # paragraphs + a table with columns CG ID / Driver description /
        # Member risks / Coefficient. Driver descriptions with a REVIEW
        # marker need Director sign-off in smoke verification.
        "cg_drivers_orienting_paragraphs": list(
            commentary_text.CG_DRIVERS_ORIENTING_PARAGRAPHS
        ),
        # Beta-17 SSoT: driver descriptions come from the register via
        # read_cg_descriptions(register_path). Tests may pass a clearly-
        # marked cg_descriptions fixture via the compose-level kwarg to
        # bypass the disk read when their register_path is synthetic.
        # SR19 §6.3: thread CG coefficients through from methodology_defaults
        # so the display table matches engine behaviour. config is always
        # populated when this code path runs (the fallback at composer top
        # constructs a config with methodology_defaults). Per Option 3
        # (orphan-only), cost_drivers' internal default-fallback to the
        # legacy headless dict stays for the synthetic-test safety net.
        "cg_drivers_table": (
            build_cg_drivers_table(
                risks_list, cg_descriptions=cg_descriptions,
                cg_coefficients=config.methodology_defaults.cg_coefficients,
            )
            if cg_descriptions is not None
            else build_cg_drivers_table(
                risks_list, register_path=register_path,
                cg_coefficients=config.methodology_defaults.cg_coefficients,
            )
        ),
    }

    # Page 8 - audit trail extension. SR14a: dict assembly via section-
    # builder; the reproducibility paragraph (narrative) is injected from
    # commentary_text here so Stage 2.5 narrative stays in this composer
    # (Decision D3=A). Beta-15 Item 1's cross-validation one-liner is
    # produced inside the section builder via
    # ``build_cross_validation_sentence`` (re-exported above).
    composed["page8_audit_trail"] = build_audit_trail_section(
        appendix_audit_trail=appendix_audit_trail,
        cross_validation=cross_validation,
        register_path=register_path,
        strawman_path=strawman_path,
        p6_path=p6_path,
        n_iter=int(config.iterations),
        reproducibility_paragraph=commentary_text.REPRODUCIBILITY,
    )

    # ----------------------------------------------------------------------
    # The report_mode tag, and the keys the deliverable does not carry.
    # ----------------------------------------------------------------------
    # PRESENT-01 (D-4): this was the caller's `mode`. There is one report, so the tag is the
    # literal; word_generator still stamps it into the docx as provenance.
    composed["report_mode"] = "prod"

    # SR9 v3.5: surface mix strings + short labels for word_generator format-
    # time use so headings / driver-section labels reflect the data.
    composed["indicative_mix"] = indicative_mix
    composed["dp_review_mix"] = dp_review_mix
    composed["all_series_mix"] = all_series_mix
    composed["indicative_display_short"] = (
        _indicative_scenario_display.split(" (")[0]
    )
    # Mirror the short label into executive_summary for the docx Top-3 table.
    if isinstance(composed.get("executive_summary"), dict):
        composed["executive_summary"]["indicative_basis_short"] = (
            composed["indicative_display_short"]
        )

    # SR9 v3.6.1 B3: counterfactual narrative. None when no duplicates,
    # when the table is empty, or when the table is missing. Rendered as
    # a leading sentence above the Appendix A1 table in both HTML and
    # Kept: not dropped by _write_page1_narrative_and_drop_dev_keys.
    composed["appendix_counterfactual_narrative"] = (
        _build_counterfactual_narrative(
            appendix_counterfactual,
            baseline_mode_mix=composed.get("indicative_display_short", ""),
        )
    )

    _write_page1_narrative_and_drop_dev_keys(
        composed,
        keep_range_table=stage3_beta_result is not None,
        stage3=stage3_beta_result is not None,
        mean_days=mean_days_indicative,
        top3_pct=_top3_pct_of_mean,
        dual_coded_count=len(integrated_dr.get("risk_ids_dual", []) or []) or None,
        tail_risk=_tail_risk,
    )

    # ----------------------------------------------------------------------
    # SR9 v3.5: headline-metric application (P80 default; Mean alt).
    # Runs AFTER the page-1 narrative so the component-breakdown rewrites land before the
    # headline highlight metadata is written.
    # ----------------------------------------------------------------------
    _apply_headline_metric(composed, headline_metric)

    # ----------------------------------------------------------------------
    # SR9 v3.2 D8: defensive key-presence audit.
    # ----------------------------------------------------------------------
    _common_keys_required = {
        # v2 baseline
        "cross_validation", "executive_summary", "cost_section",
        "schedule_section", "integrated_section", "appendix_counterfactual",
        "appendix_methodology", "appendix_audit_trail", "disclaimer_paragraphs",
        # v3 / v3.1 layout (always present when the v3 branch runs)
        "page1_headline", "page1_headline_integrated", "page1_component_breakdown",
        "page1_schedule_context", "page1_mode_caveat", "page1_top_schedule_driver",
        "page1_reading_convention_title", "page1_reading_convention",
        "page1_mean_cost_identical_note", "page1_range_table",
        "page1_headline_interpretation",
        "callouts",
        "page2_confidence_curve", "page2_confidence_curve_preamble",
        "page2_confidence_curve_footnote", "page2_distribution",
        "page3_cost_drivers", "page4_schedule_drivers", "page5_reconciliation",
        "page6_action_implications", "page7_methodology", "page8_audit_trail",
        # v3.2
        "report_mode",
    }
    _missing = _common_keys_required - set(composed.keys())
    if _missing:
        raise ValueError(
            f"Composer missing required keys: {sorted(_missing)}"
        )

    # ----------------------------------------------------------------------
    # SR-S3-Beta-08: Stage 3 beta wire-up. Runs LAST so the Stage 2.5
    # production path (stage3_beta_result is None) produces a composed
    # dict bit-identical to pre-Beta-08. When the kwarg is supplied,
    # adds the seven Stage 3 keys (consumed by word_generator's BETA
    # banner pathway and by the final_runner.ipynb Stage 3 Beta cells).
    # Beta-12 adds composed["page4b_criticality"] from this same call;
    # chart_output_dir is plumbed in so the CI distribution chart PNG
    # is written next to the other v3 charts.
    # ----------------------------------------------------------------------
    _apply_stage3_beta_keys(
        composed,
        integrated_results_by_scenario,
        stage3_beta_result,
        path_crossover_warn_threshold_days,
        chart_output_dir=chart_output_dir,
        risk_titles_override=risk_titles,
    )

    return composed
