"""SR9 executive summary helpers.

Stateless helpers consumed by composer. Computes the executive summary
numbers: top-N risk drivers, headline contingency range, diversification
summary.

Per Director scope decisions:
  - Headline range bounds computed via min/max over the three integrated
    scenarios (DP Review, Dummy Realistic, All Series). Labels follow the
    DATA, not a fixed scenario-to-bound assumption. Indicative midpoint
    is fixed to Dummy Realistic.
  - Top-3 schedule drivers ranked from Dummy Realistic basis (a near-all-Parallel
    DP Review mix can yield only one material driver).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.integrated.integrated_analysis import compute_diversification_benefit
from src.integrated.integrated_simulation import IntegratedConfig


# ----------------------------------------------------------------------------
# SR-S3-Beta-14 — strawman variant detection
#
# Mirrors the findstr-based auto-tag block at RUN_FINAL.bat (after the
# STRAWMAN_FILE assignment), which sets STRAWMAN_TAG to Series / Hybrid /
# Parallel or leaves it empty for the canonical un-suffixed strawman.
# Variant detection in Python is consumed by _build_scenario_display_lookup
# (composer.py) and the variant-aware label remapping in
# format_scenario_label below.
# ----------------------------------------------------------------------------

_VARIANT_PATTERN = re.compile(r"_(Series|Hybrid|Parallel)\.xlsx$", re.IGNORECASE)


def detect_strawman_variant(strawman_path: str | Path | None) -> str | None:
    """Return 'Series' / 'Hybrid' / 'Parallel', or None for canonical.

    Matches the bat's case-insensitive ``_<Variant>.xlsx`` suffix detection.
    A None / empty / malformed path returns None (caller treats this as the
    canonical un-suffixed strawman).
    """
    if not strawman_path:
        return None
    m = _VARIANT_PATTERN.search(str(strawman_path))
    return m.group(1).capitalize() if m else None


# Fixed Director scope decision: indicative scenario for the headline range.
# Dev report uses the Dummy Realistic (interim) scenario as the
# indicative source for headline + Page 4 drivers. Prod report (under
# Path A from SR9 v3.3) uses the DP Review baseline as the indicative
# source - single source of truth from the strawman, no Python override
# layer. Use resolve_indicative_scenario_name() instead of these
# constants directly.
INDICATIVE_SCENARIO_NAME = "Dummy_Realistic"
INDICATIVE_SCENARIO_DISPLAY = "Dummy Realistic (interim)"

DP_REVIEW_SCENARIO_NAME = "DP_Review"
DP_REVIEW_SCENARIO_DISPLAY = "DP Review baseline"


def resolve_indicative_scenario_name() -> str:
    """Return the scenario name that drives the headline / Page 4 / dominance.

    The DP Review baseline: one source of truth, the strawman's ``Risk_Scope.Mode_Aggregated``,
    with no Python override layer. Use this helper rather than the scenario constants directly.

    PRESENT-01 (D-4) removed the other answer - Dummy Realistic, the hardcoded Mode override
    used during development - because the deliverable refuses the mode that selected it.
    """
    return DP_REVIEW_SCENARIO_NAME


def resolve_indicative_scenario_display() -> str:
    """Display label corresponding to :func:`resolve_indicative_scenario_name`."""
    return DP_REVIEW_SCENARIO_DISPLAY


# ----------------------------------------------------------------------------
# Mode-mix formatting helpers (SR9 v3.5 - data-driven narrative)
#
# RS-D-5: the one implementation lives beside the engine in src/sra/mode_mix.py
# and is re-exported here so composer, word_generator and the tests keep their
# import path. An unknown Mode raises there; nothing here buckets it.
# ----------------------------------------------------------------------------

from src.sra.mode_mix import count_modes, format_mode_mix  # noqa: E402,F401


# Scenario-name → display-label suffixes, audience-neutral. The mix string is filled at format
# time. Locked by tests/test_sr9_v33_path_a_chart_legends.py (PNG OCR) plus the body-text
# assertion in tests/test_sr9_v35_narrative_data_driven.py.
#
# PRESENT-01 (D-4): a second dict stood beside this one carrying "interim classification -
# PM review pending" and its siblings, selected when mode was dev. The deliverable refuses any
# mode but prod, so those suffixes could not reach a reader; they are gone rather than guarded.
SCENARIO_LABEL_SUFFIX: dict[str, str] = {
    # DELIVFIX-01 (FW-28): was "current strawman state". The strawman is no longer a separate
    # workbook - the Mode classification is the register's own Risk_Scope sheet.
    "DP_Review": "Mode as registered",
    "Dummy_Realistic": "alternate Mode scenario",
    "All_Series": "all-Series upper bound",
}


def resolve_scenario_label_suffix() -> dict[str, str]:
    """The scenario label suffixes. One dict since PRESENT-01; the argument is gone."""
    return SCENARIO_LABEL_SUFFIX


def format_scenario_label(
    scenario_id: str,
    suffix: str | None = None,
    *,
    variant: str | None = None,
) -> str:
    """Build a display label like 'DP Review baseline (Mode as registered)'.

    Beta-14: when ``variant`` is one of "Series" / "Hybrid" / "Parallel",
    the DP_Review scenario's base label is remapped to "All <Variant>"
    because the strawman's Mode_Aggregated column is uniformly the variant
    override; calling it "DP Review baseline" misnames the headline
    scenario for variant runs. Other scenarios are unchanged.

    If `suffix` is None, the canonical suffix comes from
    :func:`resolve_scenario_label_suffix`. Pass an explicit suffix to override (e.g. for custom
    scenarios under SR10's --scenario architecture).

    PRESENT-01 (D-4): there was a second form of every label, selected when mode was dev, which
    carried "Dummy Realistic" and the mix string ('8S', '3S/2H/3P', '1S/7P') into the legend. The
    deliverable refuses any mode but prod, so that form could not reach a reader, and the
    ``mix_string`` parameter that fed it went with it.
    """
    base = {
        "DP_Review": "DP Review baseline",
        "Dummy_Realistic": "Alternate Mode scenario",
        "All_Series": "All Series",
    }.get(scenario_id, scenario_id)

    if variant and scenario_id == "DP_Review":
        # Beta-14: variant-aware DP_Review base - the strawman drives the headline scenario.
        # Capitalise the variant so the legend reads "All Hybrid" rather than "All hybrid".
        base = f"All {str(variant).capitalize()}"

    suffix_text = (
        resolve_scenario_label_suffix().get(scenario_id, "") if suffix is None else suffix
    )

    # Mix strings do not belong in a client legend. Beta-11a Fix 1: suppress the parenthetical
    # when the suffix only restates the base ("Alternate Mode scenario (alternate Mode
    # scenario)"); the comparison is generic, so a future scenario cannot reintroduce it.
    if suffix_text and not _is_redundant_suffix(base, suffix_text):
        return f"{base} ({suffix_text})"
    return base


def _is_redundant_suffix(base: str, suffix: str) -> bool:
    """Return True iff ``suffix`` is just a re-statement of ``base``.

    Comparison strips whitespace and is case-insensitive; the rendered
    parenthetical "Alternate Mode scenario (alternate Mode scenario)"
    is the canonical case Beta-11a Fix 1 targets.
    """
    return base.strip().casefold() == suffix.strip().casefold()


# ----------------------------------------------------------------------------
# Beta-11 §3 — tail-risk picker + narrative formatters
#
# A "tail risk" is the lowest-probability schedule driver with the largest
# mean impact when fired — the one that anchors the right edge of the
# distribution shape. Three narrative templates name it explicitly; the
# picker lets the narrative track engine output instead of hardcoding a
# single risk_id, as it did historically. Fallback returns the generic
# (non-named) variants of the templates when no driver meets the
# probability threshold.
# ----------------------------------------------------------------------------

def pick_tail_risk(
    schedule_drivers: list[dict[str, Any]] | Any,
    *,
    prob_threshold: float = 0.05,
) -> dict[str, Any] | None:
    """Pick the canonical 'tail risk' for narrative.

    The tail risk is the lowest-probability driver whose probability is
    below ``prob_threshold`` AND whose mean impact when fired is the
    largest among that subset — i.e. the one whose tail dominates the
    right edge of the schedule distribution.

    Beta-11 design choice: the tail risk identity is well-defined
    independent of which Mode scenario is being plotted; the identity
    changes only when the register / strawman changes. The threshold
    matches the Open set of the earlier reference register, with its two-strata structure (17.5% vs 2.5%);
    a future register that shifts the strata structure may need a
    different threshold (see brief §7).

    Parameters
    ----------
    schedule_drivers : list of dicts (or DataFrame-like)
        Each entry must contain at minimum:
            risk_id (str)
            probability (float in 0..1)
            mean_impact_when_fired_days (float, may be None for prob=0)
            pct_of_total_mean (float in 0..1)
        Typically the output of
        :func:`src.final.composer._build_probability_weighted_schedule_drivers`.
    prob_threshold : float
        Drivers with probability strictly below this value are
        considered candidates. Default 0.05.

    Returns
    -------
    dict with keys:
        tail_risk_id (str)
        tail_risk_prob (float)
        tail_risk_mean_when_fired (float, days)
        tail_risk_pct_of_mean_slip (float, 0..1)
        tail_risk_rank (int — position in pct_of_mean_slip ranking, 1-based)
        n_drivers (int)
    or ``None`` if no driver meets the criterion (or
    ``schedule_drivers`` is empty).
    """
    if hasattr(schedule_drivers, "to_dict"):
        rows = schedule_drivers.to_dict(orient="records")
    else:
        rows = list(schedule_drivers or [])
    if not rows:
        return None

    candidates = [
        r for r in rows
        if r.get("probability") is not None
        and float(r["probability"]) < prob_threshold
        and r.get("mean_impact_when_fired_days") is not None
    ]
    if not candidates:
        return None

    top = max(
        candidates,
        key=lambda r: float(r.get("mean_impact_when_fired_days", 0.0) or 0.0),
    )

    # Rank by pct_of_total_mean across ALL drivers, descending.
    pct_values = [
        (r.get("risk_id"), float(r.get("pct_of_total_mean", 0.0) or 0.0))
        for r in rows
    ]
    pct_values.sort(key=lambda x: x[1], reverse=True)
    rank = next(
        (i + 1 for i, (rid, _) in enumerate(pct_values) if rid == top["risk_id"]),
        len(pct_values),
    )

    return {
        "tail_risk_id": str(top["risk_id"]),
        "tail_risk_prob": float(top["probability"]),
        "tail_risk_mean_when_fired": float(top["mean_impact_when_fired_days"]),
        "tail_risk_pct_of_mean_slip": float(top.get("pct_of_total_mean", 0.0) or 0.0),
        "tail_risk_rank": int(rank),
        "n_drivers": int(len(rows)),
    }


def format_distribution_interpretation(tail_risk: dict[str, Any] | None) -> str:
    """Render DISTRIBUTION_INTERPRETATION_TEMPLATE with the tail-risk
    picker's output. Falls back to the generic
    ``DISTRIBUTION_INTERPRETATION`` (no risk_id named) when ``tail_risk``
    is ``None``.
    """
    from src.final import commentary_text
    if tail_risk is None:
        return commentary_text.DISTRIBUTION_INTERPRETATION
    return commentary_text.DISTRIBUTION_INTERPRETATION_TEMPLATE.format(**tail_risk)


def format_risk_matrix_interpretation(tail_risk: dict[str, Any] | None) -> str:
    """Render the risk-matrix interpretation paragraph.

    Generic fallback (``commentary_text.RISK_MATRIX_INTERPRETATION``) when
    ``tail_risk`` is ``None``.

    Beta-14 §3: when the dict has been enriched (carries ``raw_ev_pert_days``,
    ``mode_label``, ``multiplier_value``, ``mode_weighted_days``,
    ``variant_label``), the Beta-14 template is used — it reports the raw
    EV PERT as the traditional-matrix mean impact when fired and names
    the Mode multiplier explicitly when describing the probability-weighted
    matrix. Un-enriched dicts (from pick_tail_risk alone) route to the
    legacy Beta-11 template, which names the column-mean-derived mean
    impact when fired without naming the Mode multiplier. Composer call
    sites should always enrich; tests may pass either shape.
    """
    from src.final import commentary_text
    if tail_risk is None:
        return commentary_text.RISK_MATRIX_INTERPRETATION
    if "raw_ev_pert_days" in tail_risk:
        return commentary_text.RISK_MATRIX_INTERPRETATION_TEMPLATE.format(**tail_risk)
    return commentary_text.RISK_MATRIX_INTERPRETATION_TEMPLATE_LEGACY.format(**tail_risk)


def enrich_tail_risk_for_matrix(
    tail_risk: dict[str, Any] | None,
    risks: Any,
    mode_used: dict[str, str] | None,
    variant_label: str,
    *,
    mode_multipliers: Mapping[str, float],
) -> dict[str, Any] | None:
    """Add Beta-14 fields to a tail_risk dict for the risk-matrix narrative.

    The base ``tail_risk`` dict (from :func:`pick_tail_risk`) carries
    Beta-11 fields: ``tail_risk_id``, ``tail_risk_prob``,
    ``tail_risk_mean_when_fired`` (Mode-multiplied), etc. The Beta-14
    risk-matrix interpretation template additionally needs the
    Mode-independent raw EV PERT, the Mode label, the multiplier value,
    the Mode-weighted figure derived from the raw EV PERT, and a friendly
    scenario label.

    Parameters
    ----------
    tail_risk : dict or None
        Output of :func:`pick_tail_risk`. None passes through unchanged.
    risks : Iterable
        Register risks (objects with ``risk_id``, ``opt_schedule_days``,
        ``ml_days``, ``pess_schedule_days`` attributes — same shape
        :func:`src.final.composer._build_risk_matrix_data` consumes).
    mode_used : dict or None
        ``schedule_results[scenario].mode_used`` — maps risk_id to its
        Mode label under the indicative scenario. Empty / None routes
        to the default fallback Mode (Hybrid). A label the grid does not
        define raises (RS-D-3, D-15); nothing here falls back to 0.5.
    variant_label : str
        Friendly label for the headline scenario whose Mode multipliers
        drive the matrix (e.g. "All Hybrid", "DP Review baseline"). Used
        verbatim in the rendered prose.

    Returns
    -------
    dict or None
        Copy of ``tail_risk`` with the additional Beta-14 fields, or
        ``None`` if ``tail_risk`` is ``None`` or the matching register
        risk cannot be located (caller treats this as the generic-
        fallback case).
    """
    if tail_risk is None:
        return None
    from src.sra.mode_multipliers import resolve_mode_multiplier

    target_rid = str(tail_risk.get("tail_risk_id", ""))
    matching = None
    for r in risks or []:
        rid = getattr(r, "risk_id", None)
        if rid is None and isinstance(r, dict):
            rid = r.get("risk_id")
        if str(rid) == target_rid:
            matching = r
            break
    if matching is None:
        return None

    def _attr(name: str, default: float = 0.0) -> float:
        if isinstance(matching, dict):
            val = matching.get(name, default)
        else:
            val = getattr(matching, name, default)
        try:
            return float(val) if val is not None else float(default)
        except (TypeError, ValueError):
            return float(default)

    opt = _attr("opt_schedule_days")
    ml = _attr("ml_days")
    pess = _attr("pess_schedule_days")
    raw_ev_pert = (opt + 4.0 * ml + pess) / 6.0

    mode_label = (mode_used or {}).get(target_rid, "Hybrid")
    multiplier_value = resolve_mode_multiplier(mode_label, mode_multipliers, target_rid)  # RS-D-3
    mode_weighted_days = raw_ev_pert * multiplier_value

    enriched = dict(tail_risk)
    enriched.update({
        "raw_ev_pert_days": raw_ev_pert,
        "mode_label": str(mode_label),
        "multiplier_value": multiplier_value,
        "mode_weighted_days": mode_weighted_days,
        "variant_label": str(variant_label),
    })
    return enriched


def format_comparison_interpretation(tail_risk: dict[str, Any] | None) -> str:
    """Render WATERFALL_INTERPRETATION_TEMPLATE (the "tail couples cost
    and schedule" sentence the brief refers to as the
    COMPARISON_INTERPRETATION site at :316-326); fallback to the
    generic ``WATERFALL_INTERPRETATION`` when ``tail_risk`` is ``None``."""
    from src.final import commentary_text
    if tail_risk is None:
        return commentary_text.WATERFALL_INTERPRETATION
    return commentary_text.WATERFALL_INTERPRETATION_TEMPLATE.format(**tail_risk)


def format_risk_matrix_orienting(matrix_scenario: str | None) -> str:
    """Render RISK_MATRIX_ORIENTING_TEMPLATE with the scenario name
    feeding the matrix.

    Beta-11a Fix 3: the orienting paragraph above the risk matrix now
    names the scenario the markers reflect. Falls back to the generic
    ``RISK_MATRIX_ORIENTING`` (no name) when ``matrix_scenario`` is
    None or empty.
    """
    from src.final import commentary_text
    if not matrix_scenario:
        return commentary_text.RISK_MATRIX_ORIENTING
    # Strip parenthetical decoration from the scenario display name
    # (e.g. "Dummy Realistic (interim)" → "Dummy Realistic")
    # so the rendered sentence reads naturally.
    cleaned = matrix_scenario.split(" (")[0].strip()
    return commentary_text.RISK_MATRIX_ORIENTING_TEMPLATE.format(
        matrix_scenario=cleaned,
    )


# ----------------------------------------------------------------------------
# Beta-12 — Activity-level criticality narrative format helpers
# ----------------------------------------------------------------------------

def format_criticality_explainer(
    n_iter: int,
    binding_counts: list[int] | None = None,
) -> str:
    """Render :data:`commentary_text.CRITICALITY_EXPLAINER_TEMPLATE` with
    the run's iteration count.

    Beta-19b item 10: when ``binding_counts`` is supplied, append the
    Mode-conditioned vs Mode-independent differentiation paragraph
    (:data:`commentary_text.CI_EXPLAINER_MODE_DIFFERENTIATION`) with
    ``{n_min}`` / ``{n_max}`` populated from the live auto-mapper
    binding counts. When the list is empty / None the appended
    paragraph is omitted (legacy / pre-SR10.B behaviour).
    """
    from src.final import commentary_text
    if n_iter <= 0:
        # The template substring is ``the {n_iter:,} simulated futures``;
        # collapse the whole phrase rather than the token alone to avoid
        # the duplicate-word render ("the the simulated simulated").
        base = commentary_text.CRITICALITY_EXPLAINER_TEMPLATE.replace(
            "the {n_iter:,} simulated futures",
            "the simulated futures",
        )
    else:
        base = commentary_text.CRITICALITY_EXPLAINER_TEMPLATE.format(
            n_iter=n_iter,
        )
    if binding_counts:
        positive = [int(c) for c in binding_counts if int(c) > 0]
        if positive:
            mode_para = (
                commentary_text.CI_EXPLAINER_MODE_DIFFERENTIATION.format(
                    n_min=min(positive),
                    n_max=max(positive),
                )
            )
            return base + mode_para
    return base


def format_criticality_distribution_interpretation(
    distribution_summary: dict[str, Any] | None,
) -> str:
    """Render the distribution-shape interpretation paragraph.

    Selects the template from
    :data:`commentary_text.CRITICALITY_DISTRIBUTION_INTERPRETATION_TEMPLATES`
    using the ``shape_indicator`` returned by
    :func:`src.final.composer.compute_ci_distribution_summary`, then
    substitutes the band percentages.

    Falls back to the ``"shifty"`` template (the safest narrative —
    does not make a strong claim about path stability) when the summary
    is missing or the shape indicator is unrecognised.
    """
    from src.final import commentary_text
    templates = commentary_text.CRITICALITY_DISTRIBUTION_INTERPRETATION_TEMPLATES
    if not distribution_summary:
        return templates["shifty"].format(
            n_total=0, pct_always=0.0, pct_never=0.0, pct_middle=0.0,
        )
    shape = str(distribution_summary.get("shape_indicator", "shifty"))
    template = templates.get(shape, templates["shifty"])
    pcts = distribution_summary.get("band_pcts", {}) or {}
    pct_always = float(pcts.get("always (90%+)", 0.0))
    pct_never = float(pcts.get("never (<10%)", 0.0))
    pct_middle = float(
        pcts.get("rarely (10-30%)", 0.0)
        + pcts.get("near (30-70%)", 0.0)
        + pcts.get("often (70-90%)", 0.0)
    )
    n_total = int(distribution_summary.get("n_activities_total", 0))
    return template.format(
        n_total=n_total,
        pct_always=pct_always,
        pct_never=pct_never,
        pct_middle=pct_middle,
    )


def format_criticality_near_critical_interpretation(
    near_critical_table: Any,
) -> str:
    """Render the near-critical interpretation paragraph.

    Reads the count of activities and the top CI from the picker output
    DataFrame (or list-of-dicts). Returns the empty-state fallback when
    the picker found zero activities in the [20%, 80%] band.

    Parameters
    ----------
    near_critical_table : pd.DataFrame | list[dict]
        Output of :func:`src.final.composer.pick_near_critical_activities`
        OR its ``to_dict(orient="records")`` form (the composed dict
        stores the latter; tests may pass the DataFrame directly).
    """
    from src.final import commentary_text

    # Coerce list-of-dicts → DataFrame for uniform indexing. Empty
    # input (None, empty df, empty list) routes through the fallback.
    if near_critical_table is None:
        n = 0
    elif hasattr(near_critical_table, "empty"):
        n = 0 if near_critical_table.empty else int(len(near_critical_table))
    else:
        n = int(len(near_critical_table))

    if n == 0:
        return commentary_text.CRITICALITY_NEAR_CRITICAL_INTERPRETATION_EMPTY

    # Top CI is the first row's ``ci`` (the picker returns sorted desc).
    if hasattr(near_critical_table, "iloc"):
        top_ci = float(near_critical_table.iloc[0]["ci"])
    else:
        top_ci = float(near_critical_table[0]["ci"])

    # The "top {n_top} activities (CI ≥ ...)" phrasing reads naturally
    # for n_top in {3, 5}. Use min(3, n) so the phrase still makes
    # grammatical sense at small picker sizes.
    n_top = min(3, n)
    return commentary_text.CRITICALITY_NEAR_CRITICAL_INTERPRETATION_TEMPLATE.format(
        n_near_critical=n,
        n_top=n_top,
        top_ci=top_ci,
    )


# ----------------------------------------------------------------------------
# SR-S3-Beta-18 §1 — Auto-mapper interpretation formatter
# ----------------------------------------------------------------------------

def format_auto_mapper_audit_interpretation(
    audit_table: Any,
    stage25_p80_days: float | None,
    stage3_p80_days: float | None,
    schedule_size: int | None = None,
    over_bind_floor: float | None = None,
) -> str:
    """Render the Stage 3 Beta auto-mapper interpretation paragraph.

    Reads the audit table to classify each Time=Yes risk as "over-bound"
    (activity_count / schedule_size >= over_bind_floor) and emits the
    plain-English explanation of why the Stage 3 Beta P80 inflates the
    Stage 2.5 P80 — the over-binding of the auto-mapper, not a real
    schedule-risk signal. Names workshop validation as the remediation.

    All numeric values (over-bound risk IDs, activity-count range, P80
    figures) come from live inputs; no hardcoded literals.

    Parameters
    ----------
    audit_table : pd.DataFrame | list[dict] | None
        ``composed["stage3_beta_audit_table"]`` — one row per RiskDriver
        with at minimum ``risk_id`` and ``activity_count`` columns. The
        list-of-dicts form (post-``to_dict(orient="records")``) is also
        accepted.
    stage25_p80_days, stage3_p80_days : float | None
        P80 schedule values from
        ``composed["stage25_p80_schedule_days"]`` /
        ``["stage3_beta_p80_schedule_days"]``.
    schedule_size : int
        The number of activities in the schedule this run replayed. It is the denominator of
        the fraction-of-schedule classification, so it is a fact about the project's own
        programme. PRESENT-01 (D-5): there is no default - a borrowed schedule size changes
        which risks are called over-bound, and the caller has the graph.
    over_bind_floor : float | None
        Lower bound on (activity_count / schedule_size) above which a
        risk is classified as over-bound. Defaults to
        ``AUTO_MAPPER_OVER_BIND_FRACTION_FLOOR`` (0.15).
    """
    from src.final import commentary_text

    if audit_table is None:
        return ""

    if hasattr(audit_table, "to_dict"):
        rows = audit_table.to_dict(orient="records")
    else:
        rows = list(audit_table)

    if not rows:
        return ""

    if schedule_size is None or schedule_size <= 0:
        raise ValueError(
            "the over-bind classification needs the run's own activity count as its "
            f"denominator; got schedule_size={schedule_size!r}. Pass len(graph.activities) "
            "from the run that produced the audit table (PRESENT-01 D-5)."
        )
    if over_bind_floor is None:
        over_bind_floor = (
            commentary_text.AUTO_MAPPER_OVER_BIND_FRACTION_FLOOR
        )

    floor_count = float(over_bind_floor) * float(schedule_size)
    over_bound = [
        r for r in rows
        if float(r.get("activity_count", 0) or 0) >= floor_count
    ]
    if not over_bound:
        # No over-bound risks under current ruleset — nothing to caveat.
        return ""

    over_bound_sorted = sorted(over_bound, key=lambda r: str(r.get("risk_id", "")))
    over_bound_ids = ", ".join(str(r.get("risk_id", "")) for r in over_bound_sorted)
    counts = [int(r.get("activity_count", 0) or 0) for r in over_bound_sorted]
    min_count = min(counts)
    max_count = max(counts)

    return commentary_text.AUTO_MAPPER_AUDIT_INTERPRETATION_TEMPLATE.format(
        n_over_bound=len(over_bound),
        n_total=len(rows),
        over_bound_ids=over_bound_ids,
        min_count=min_count,
        max_count=max_count,
        schedule_size=int(schedule_size),
        stage3_p80_days=float(stage3_p80_days or 0.0),
        stage25_p80_days=float(stage25_p80_days or 0.0),
    )


def format_auto_mapper_audit_interpretation_stage3(
    audit_table: Any,
    stage3_p80_days: float | None,
    schedule_size: int | None = None,
    over_bind_floor: float | None = None,
) -> str:
    """SR14b D3 — Stage 3 standalone variant of the auto-mapper
    interpretation paragraph.

    Mirrors :func:`format_auto_mapper_audit_interpretation` but uses
    :data:`commentary_text.AUTO_MAPPER_AUDIT_INTERPRETATION_TEMPLATE_STAGE3`
    (the Stage 3 standalone wording — Stage 2.5 comparison clause
    stripped per AC5 zero-reference audit). The ``stage25_p80_days``
    argument is intentionally absent here: the Stage 3 standalone
    template does not interpolate it.

    Parameters
    ----------
    audit_table, stage3_p80_days, schedule_size, over_bind_floor
        Same semantics as :func:`format_auto_mapper_audit_interpretation`.
    """
    from src.final import commentary_text

    if audit_table is None:
        return ""

    if hasattr(audit_table, "to_dict"):
        rows = audit_table.to_dict(orient="records")
    else:
        rows = list(audit_table)

    if not rows:
        return ""

    if schedule_size is None or schedule_size <= 0:
        raise ValueError(
            "the over-bind classification needs the run's own activity count as its "
            f"denominator; got schedule_size={schedule_size!r}. Pass len(graph.activities) "
            "from the run that produced the audit table (PRESENT-01 D-5)."
        )
    if over_bind_floor is None:
        over_bind_floor = (
            commentary_text.AUTO_MAPPER_OVER_BIND_FRACTION_FLOOR
        )

    floor_count = float(over_bind_floor) * float(schedule_size)
    over_bound = [
        r for r in rows
        if float(r.get("activity_count", 0) or 0) >= floor_count
    ]
    if not over_bound:
        return ""

    over_bound_sorted = sorted(over_bound, key=lambda r: str(r.get("risk_id", "")))
    over_bound_ids = ", ".join(str(r.get("risk_id", "")) for r in over_bound_sorted)
    counts = [int(r.get("activity_count", 0) or 0) for r in over_bound_sorted]
    min_count = min(counts)
    max_count = max(counts)

    return commentary_text.AUTO_MAPPER_AUDIT_INTERPRETATION_TEMPLATE_STAGE3.format(
        n_over_bound=len(over_bound),
        n_total=len(rows),
        over_bound_ids=over_bound_ids,
        min_count=min_count,
        max_count=max_count,
        schedule_size=int(schedule_size),
        stage3_p80_days=float(stage3_p80_days or 0.0),
    )


# ----------------------------------------------------------------------------
# Top-N risk drivers
# ----------------------------------------------------------------------------

def get_top_n_risk_drivers(
    integrated_results: dict[str, Any],
    n: int = 3,
    metric: str = "cost",
    p_level: int = 80,
    risk_titles: dict[str, str] | None = None,
    day_rate: float | None = None,
) -> list[dict[str, Any]]:
    """Return top-N risk drivers ranked by the specified metric.

    Parameters
    ----------
    integrated_results : dict
        From run_integrated_simulation. For metric="cost", uses
        per_risk_cost_array and risk_ids_all. For metric="schedule",
        uses per_risk_schedule_array and risk_ids_dual. Caller chooses
        which scenario's results to pass; per Director scope, schedule
        ranking is taken from Dummy Realistic.

    n : int
        Number of top drivers to return.

    metric : str
        "cost" or "schedule".

    p_level : int
        Percentile used for ranking (default 80; matches reporting P-level).

    risk_titles : dict[risk_id -> title] or None
        Optional. If provided, each entry includes a "title" field.
        If None, title is the risk_id.

    day_rate : float or None
        Required for metric="schedule" only. Used to compute a dollarised
        schedule contribution per driver (informational).

    Returns
    -------
    list of dicts. Each dict has:
      - risk_id          : str
      - title            : str (== risk_id if risk_titles is None)
      - metric_value     : float (P-level value of per-risk array, in metric units)
      - mean_value       : float (mean per-risk value across iterations)
      - percentage_of_total : float (this driver's metric_value / sum of all P-level values)
      - units            : "dollars" or "days"
    For schedule metric, dicts also include:
      - p_level_dollars  : float (metric_value * day_rate)
    """
    if metric not in ("cost", "schedule"):
        raise ValueError(f"metric must be 'cost' or 'schedule', got {metric!r}")

    if metric == "cost":
        per_risk = np.asarray(integrated_results["per_risk_cost_array"])
        risk_ids = list(integrated_results["risk_ids_all"])
        units = "dollars"
    else:
        per_risk = np.asarray(integrated_results["per_risk_schedule_array"])
        risk_ids = list(integrated_results["risk_ids_dual"])
        units = "days"
        if day_rate is None:
            day_rate = 0.0

    if per_risk.size == 0 or len(risk_ids) == 0:
        return []

    p_values = np.percentile(per_risk, p_level, axis=0)
    means = per_risk.mean(axis=0)
    total_p = float(np.sum(p_values)) if np.sum(p_values) > 0 else 1.0

    order = np.argsort(p_values)[::-1][:n]
    out: list[dict[str, Any]] = []
    titles = risk_titles or {}
    for idx in order:
        rid = risk_ids[idx]
        entry = {
            "risk_id": rid,
            "title": titles.get(rid, rid),
            "metric_value": float(p_values[idx]),
            "mean_value": float(means[idx]),
            "percentage_of_total": float(p_values[idx]) / total_p,
            "units": units,
        }
        if metric == "schedule":
            entry["p_level_dollars"] = float(p_values[idx]) * float(day_rate)
        out.append(entry)
    return out


# ----------------------------------------------------------------------------
# Headline contingency range (P80, dynamically labelled)
# ----------------------------------------------------------------------------

def resolve_headline_metric(headline_metric: str) -> str:
    """Validate and return the canonical headline-metric label.

    Accepts "P80" or "Mean" (case-insensitive). Returns the canonical
    capitalised form. Raises ValueError on anything else.
    """
    canonical = {"p80": "P80", "mean": "Mean"}
    key = str(headline_metric).strip().lower()
    if key not in canonical:
        raise ValueError(
            f"Unknown headline_metric: {headline_metric!r} "
            f"(expected 'P80' or 'Mean')"
        )
    return canonical[key]


def get_headline_contingency_range(
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    # DAYRATE-02 B1: required, and moved ahead of the defaulted parameters to
    # make it so. Every caller already passes it by keyword (composer.py plus
    # four test callsites), so no callsite changes and no number moves; the
    # only effect is that one per-project literal leaves a signature in
    # engine code.
    day_rate: float,
    p_level: int = 80,
    headline_metric: str = "P80",
) -> dict[str, Any]:
    """Compute lower/indicative/upper bounds via min/max over scenarios.

    Bound LABELS follow the data (which scenario actually has the min/max
    P80 total), NOT a fixed scenario-to-bound assumption. PM Mode amendments
    could shift the ordering.

    Indicative midpoint follows resolve_indicative_scenario_name():
    Dummy Realistic in dev, DP Review baseline in prod (SR9 v3.3 Path A).

    Parameters
    ----------
    integrated_results_by_scenario : dict
        {scenario_name: integrated_results_dict, ...}. Expected scenario
        names: "DP_Review", "Dummy_Realistic", "All_Series". The function
        accepts any non-empty subset; min/max are taken over what is supplied.

    p_level : int
        Percentile (default 80) used for the P80 metric.

    day_rate : float
        Used to dollarise schedule_days_array for the integrated total.

    headline_metric : str
        "P80" (default) or "Mean". Drives which metric the headline figures
        report: P80 follows the AU GN3A v2.0 / AACE 18R-97 standard;
        Mean is provided as a supplementary metric per SR9 v3.5 client
        framing. Mean uses the arithmetic mean of the integrated total.

    Returns
    -------
    dict with keys:
      - lower_bound_dollars     : float
      - lower_bound_scenario    : str
      - indicative_dollars      : float (None if indicative scenario missing)
      - indicative_scenario     : str
      - upper_bound_dollars     : float
      - upper_bound_scenario    : str
      - all_three_scenarios     : dict {display_name: metric_dollars}
      - p_level                 : int
      - headline_metric         : str ("P80" or "Mean")
    """
    if not integrated_results_by_scenario:
        raise ValueError("integrated_results_by_scenario must be non-empty")

    headline_metric = resolve_headline_metric(headline_metric)

    p_by_scenario: dict[str, float] = {}
    for name, integrated in integrated_results_by_scenario.items():
        cost_arr = np.asarray(integrated["cost_dollars_array"])
        sched_arr = np.asarray(integrated["schedule_days_array"])
        total = cost_arr + sched_arr * float(day_rate)
        if headline_metric == "Mean":
            p_by_scenario[name] = float(np.mean(total))
        else:
            p_by_scenario[name] = float(np.percentile(total, p_level))

    lower_name = min(p_by_scenario, key=p_by_scenario.get)
    upper_name = max(p_by_scenario, key=p_by_scenario.get)

    indicative_name = resolve_indicative_scenario_name()
    indicative_value = p_by_scenario.get(indicative_name)
    indicative_display = (
        resolve_indicative_scenario_display()
        if indicative_name in p_by_scenario
        else "(not supplied)"
    )

    display_name_map = {
        "DP_Review": "DP Review baseline",
        "Dummy_Realistic": "Dummy Realistic (interim)",
        "All_Series": "All Series",
    }
    all_three_display = {
        display_name_map.get(k, k): v for k, v in p_by_scenario.items()
    }

    return {
        "lower_bound_dollars": p_by_scenario[lower_name],
        "lower_bound_scenario": display_name_map.get(lower_name, lower_name),
        "indicative_dollars": indicative_value,
        "indicative_scenario": indicative_display,
        "upper_bound_dollars": p_by_scenario[upper_name],
        "upper_bound_scenario": display_name_map.get(upper_name, upper_name),
        "all_three_scenarios": all_three_display,
        "p_level": int(p_level),
        "headline_metric": headline_metric,
    }


# ----------------------------------------------------------------------------
# Diversification summary
# ----------------------------------------------------------------------------

def get_diversification_summary(
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    schedule_results_by_scenario: dict[str, dict[str, Any]],
    cost_only_l2_results: dict[str, Any],
    config: IntegratedConfig | None = None,
) -> dict[str, Any]:
    """Return one-line diversification summary suitable for executive summary.

    Reuses src/integrated/integrated_analysis.compute_diversification_benefit.
    Headline number is the All Series scenario diversification benefit at the
    reporting P-level (gate scenario).

    Parameters
    ----------
    integrated_results_by_scenario : dict
        {"DP_Review", "All_Series", "Dummy_Realistic"} -> integrated results.
    schedule_results_by_scenario : dict
        Same scenario keys -> SR5 results.
    cost_only_l2_results : dict
        Cost-only L2 standalone results (with cost_dollars_array).
    config : IntegratedConfig or None
        Used for p_level and day_rate. If None, uses defaults.

    Returns
    -------
    dict:
      - all_series_dollars : float
      - all_series_pct     : float
      - interpretation     : str (one-sentence summary)
      - per_scenario       : dict (full scenarios output for transparency)
    """
    if config is None:
        # SR19 §6.2: methodology_defaults is REQUIRED on IntegratedConfig.
        # This fallback is for compute_diversification_benefit which does
        # not read methodology_defaults; placeholder factory values are
        # safe because the dataclass-required field still needs a value.
        from src.sra.methodology_defaults_reader import (
            build_test_methodology_defaults,
        )
        config = IntegratedConfig(
            register_path="",  # placeholder; not read here
            p6_path="",
            strawman_path="",
            methodology_defaults=build_test_methodology_defaults(),
            # RS-D-2: the tolerances are required fields; this placeholder config feeds
            # compute_diversification_benefit, which reads none of them. NaN, not a
            # number: a NaN tolerance can never pass a calibration check by accident.
            cost_calibration_tolerance_dollars=float("nan"),
            cost_calibration_tolerance_pct=float("nan"),
            schedule_calibration_tolerance_days=float("nan"),
            schedule_calibration_tolerance_pct=float("nan"),
            schedule_top3_tie_tolerance_pct=float("nan"),
        )

    div = compute_diversification_benefit(
        integrated_results_by_scenario=integrated_results_by_scenario,
        standalone_cost_l2only_results=cost_only_l2_results,
        standalone_schedule_results_by_scenario=schedule_results_by_scenario,
        config=config,
    )

    all_series = div["scenarios"].get("All_Series")
    if all_series is None:
        return {
            "all_series_dollars": 0.0,
            "all_series_pct": 0.0,
            "interpretation": (
                "All Series scenario not supplied; diversification benefit "
                "cannot be reported."
            ),
            "per_scenario": div["scenarios"],
        }

    dollars = float(all_series["diversification_dollars"])
    pct = float(all_series["diversification_pct"])
    sign = "benefit" if dollars > 0 else "penalty"
    interp = (
        f"Joint cost-schedule sampling produces a ${abs(dollars)/1e6:.2f}M "
        f"({abs(pct)*100:.1f}%) diversification {sign} at "
        f"P{config.reporting_p_level} under All Series classification, "
        f"confirming the integrated approach's methodological value."
        if dollars > 0
        else
        f"Joint cost-schedule sampling produces a ${abs(dollars)/1e6:.2f}M "
        f"({abs(pct)*100:.1f}%) divergence at P{config.reporting_p_level} "
        f"under All Series classification; investigate before shipping."
    )
    return {
        "all_series_dollars": dollars,
        "all_series_pct": pct,
        "interpretation": interp,
        "per_scenario": div["scenarios"],
    }


# ----------------------------------------------------------------------------
# SR-S3-Beta-19 §3 — Risk-to-CP linkage prose for the shrunk main-report
# ----------------------------------------------------------------------------

def format_risk_to_cp_linkage_prose(
    bridge_records: Any,
    max_activities_per_risk: int = 2,
) -> str:
    """Render 2-3 sentence risk-to-CP linkage prose.

    Used in the shrunk main-report criticality section in place of the
    full risk-to-activity bridge table (which moves to the sibling
    note). Names the top schedule-driver risks and the most-critical
    activities each binds to.

    Parameters
    ----------
    bridge_records : pd.DataFrame | list[dict] | None
        Same shape as ``composed["page4b_criticality"]["risk_to_activity_bridge"]``
        — list of dicts with risk_id, risk_title, activity_id,
        activity_name, ci, no_activity_bindings.
    max_activities_per_risk : int
        Cap on activities per risk surfaced in the prose. Default 2 keeps
        the paragraph readable; raise for richer detail.
    """
    if bridge_records is None:
        return ""
    if hasattr(bridge_records, "to_dict"):
        records = bridge_records.to_dict(orient="records")
    else:
        records = list(bridge_records)
    if not records:
        return ""

    by_risk: dict[str, list[dict[str, Any]]] = {}
    risk_order: list[str] = []
    for row in records:
        rid = str(row.get("risk_id", "")).strip()
        if not rid:
            continue
        if rid not in by_risk:
            risk_order.append(rid)
            by_risk[rid] = []
        by_risk[rid].append(row)

    clauses: list[str] = []
    for rid in risk_order:
        rows = by_risk[rid]
        # Skip zero-binding placeholder rows but acknowledge briefly.
        no_bind = all(r.get("no_activity_bindings") for r in rows)
        if no_bind:
            clauses.append(
                f"{rid} has no activity bindings under the current "
                "auto-mapper expansion"
            )
            continue
        bound = [r for r in rows if not r.get("no_activity_bindings")]
        bound.sort(key=lambda r: (
            -float(r.get("ci") or 0.0) if r.get("ci") is not None else 0.0
        ))
        top = bound[:max_activities_per_risk]
        names = []
        for r in top:
            name = str(r.get("activity_name") or r.get("activity_id") or "").strip()
            if not name:
                continue
            ci = r.get("ci")
            if isinstance(ci, (int, float)) and ci == ci:  # not NaN
                names.append(f"{name} (CI {float(ci):.0%})")
            else:
                names.append(name)
        if not names:
            continue
        if len(names) == 1:
            clauses.append(f"{rid} binds to {names[0]}")
        else:
            clauses.append(f"{rid} binds to " + " and ".join(names))

    if not clauses:
        return ""

    return (
        "Risk-to-CP linkage: "
        + "; ".join(clauses)
        + ". Treatment effort on these risks narrows the criticality "
        "distribution at the named activities; the full per-(risk, "
        "activity) detail sits in the criticality note."
    )


# ----------------------------------------------------------------------------
# SR10.B Item 5 / §10.5 — Risk-to-CP linkage prose with dual-CI surfacing
# ----------------------------------------------------------------------------
#
# Per Decision 7 the §10.5 paragraph names the GTU electrical-chain finding
# from SR10.A's smoke ("5 amplified-by-Mode GTU electrical-installation
# activities sit at MC-CI ≈ 99.8% but MI-CI ≈ 45%") as a worked example.
# The formatter below derives every sentence from the live Chart 3 data +
# the extended CI table's amplified-by-Mode rows — no hand-written prose;
# the brief reviewer pass item 6 requires "the formatter is the only
# path; no fallback text". Empty / degenerate inputs return an empty
# string and the renderer skips the paragraph.

#: Cap on activities named inline in the §10.5 paragraph. Keeps the
#: paragraph readable — five names is the deep-research note §5.1
#: chart 1 default for the "panel-only" call-outs.
_SR10B_LINKAGE_PROSE_MAX_NAMES: int = 5


#: SR14b D3 additive: default amplified-cohort note for the SR10.B
#: §10.5 linkage prose. The Stage 2.5 wording references the "Stage
#: 2.5 Mode tuning" by name (appropriate for the Stage 2.5
#: deliverable's audience). The Stage 3 standalone variant must read
#: without the comparison frame per AC5 zero-Stage-2.5-references
#: audit; pass ``amplified_mode_tuning_note=`` the
#: :data:`AMPLIFIED_COHORT_NOTE_STAGE3` value below.
AMPLIFIED_COHORT_NOTE_DEFAULT = (
    "; the amplified cohort — {named_list} — sits at high "
    "Mode-conditioned CI but materially lower Mode-independent "
    "CI, indicating the Stage 2.5 Mode tuning is "
    "over-prioritising those activities relative to AACE 65R-11 "
    "Mode-independent measurement"
)
AMPLIFIED_COHORT_NOTE_STAGE3 = (
    "; the amplified cohort — {named_list} — sits at high "
    "Mode-conditioned CI but materially lower Mode-independent "
    "CI, indicating the Mode-conditioned tuning is over-prioritising "
    "those activities relative to AACE 65R-11 Mode-independent "
    "measurement"
)


def format_risk_to_cp_linkage_prose_sr10b(
    linkage_table: Any,
    extended_ci_table: Any,
    *,
    max_names: int = _SR10B_LINKAGE_PROSE_MAX_NAMES,
    amplified_mode_tuning_note: str | None = None,
) -> str:
    """Templated §10.5 risk-to-CP linkage paragraph (SR10.B Item 5).

    The formatter pulls three signal points from the SR10.B data plumb:

    1. The top-3 risk drivers (rows of ``linkage_table`` sorted by
       ``n_activities_bound`` desc, ties broken by ``risk_id``).
    2. Up to ``max_names`` activities with Mode-independent CI ≥ 0.70,
       sorted by MI CI desc (the "treatment-leverage" cohort).
    3. The count of amplified-by-Mode and suppressed-by-Mode activities
       (from the extended CI table's ``divergence_band`` column) plus a
       worked-example list of the top amplified activities — the
       a project-specific electrical-chain finding when the engine actually
       picks one up.

    Parameters
    ----------
    linkage_table : pd.DataFrame | Iterable[dict]
        Output of :func:`build_risk_to_cp_linkage_table`.
    extended_ci_table : pd.DataFrame | Iterable[dict]
        Output of :func:`compute_extended_ci_table` — needs
        ``activity_id``, ``activity_name``, ``ci_mode_conditioned``,
        ``ci_mode_independent``, ``divergence_band``.
    max_names : int
        Cap on activities named in any inline list.

    Returns
    -------
    str
        Two-to-three-sentence paragraph or empty string when both
        inputs are empty.
    """
    import pandas as _pd

    def _to_records(obj: Any) -> list[dict[str, Any]]:
        if obj is None:
            return []
        if hasattr(obj, "to_dict"):
            return obj.to_dict(orient="records")
        return list(obj)

    linkage_records = _to_records(linkage_table)
    ci_records = _to_records(extended_ci_table)

    if not linkage_records and not ci_records:
        return ""

    # --- Sentence 1: top-3 risk drivers ----------------------------------
    # Beta-19b item 3: ranking metric changed from n_activities_bound to
    # prob_weighted_mean_days (the §10.4 metric) so §10.5 / §10.4 / §10.6
    # / the criticality note's bridge all name the same top-3. The
    # n_activities_bound figure remains in the prose because it is the
    # auto-mapper artefact that gives the reader scope of impact.
    # Fallback: when the linkage table doesn't carry the impact column
    # (legacy callers / fixtures), revert to the previous binding-count
    # ordering.
    if linkage_records:
        has_impact_column = any(
            r.get("prob_weighted_mean_days") not in (None, 0, 0.0)
            for r in linkage_records
        )
        if has_impact_column:
            sorted_linkage = sorted(
                linkage_records,
                key=lambda r: (
                    -float(r.get("prob_weighted_mean_days") or 0.0),
                    str(r.get("risk_id") or ""),
                ),
            )
        else:
            sorted_linkage = sorted(
                linkage_records,
                key=lambda r: (
                    -int(r.get("n_activities_bound") or 0),
                    str(r.get("risk_id") or ""),
                ),
            )
        top_risks = sorted_linkage[:3]
        ids_with_counts = [
            f"{str(r.get('risk_id') or '').strip()} "
            f"({int(r.get('n_activities_bound') or 0)} act.)"
            for r in top_risks
        ]
        risk_phrase = ", ".join([p for p in ids_with_counts if p.strip()])
    else:
        risk_phrase = ""

    # --- Sentence 2: MI ≥ 70% cohort sourced from the extended table ----
    high_mi_names: list[str] = []
    if ci_records:
        # Filter to rows with MI CI ≥ 0.70 and sort by MI CI desc.
        high_mi = [
            row for row in ci_records
            if _is_number(row.get("ci_mode_independent"))
            and float(row.get("ci_mode_independent") or 0.0) >= 0.70
        ]
        high_mi.sort(
            key=lambda r: -float(r.get("ci_mode_independent") or 0.0),
        )
        for row in high_mi[:max_names]:
            name = str(
                row.get("activity_name") or row.get("activity_id") or ""
            ).strip()
            if name:
                mi = float(row.get("ci_mode_independent") or 0.0)
                high_mi_names.append(f"{name} (MI-CI {mi:.0%})")

    # --- Sentence 3: amplified vs suppressed counts + worked example ----
    amp_count = 0
    sup_count = 0
    amp_named: list[str] = []
    if ci_records:
        amp_rows = [
            r for r in ci_records
            if str(r.get("divergence_band") or "") == "amplified by Mode"
        ]
        sup_rows = [
            r for r in ci_records
            if str(r.get("divergence_band") or "") == "suppressed by Mode"
        ]
        amp_count = len(amp_rows)
        sup_count = len(sup_rows)

        # Worked example: top amplified-by-Mode activities by MC CI desc
        # (matches the "MC ≈ 99.8% but MI ≈ 45%" framing).
        amp_rows.sort(
            key=lambda r: -float(r.get("ci_mode_conditioned") or 0.0),
        )
        for row in amp_rows[:max_names]:
            name = str(
                row.get("activity_name") or row.get("activity_id") or ""
            ).strip()
            if name:
                amp_named.append(name)

    # Assemble the paragraph. Each sentence is conditional on its inputs;
    # an empty input degrades to omission rather than producing
    # ungrammatical placeholder text.
    sentences: list[str] = []

    if risk_phrase:
        sentences.append(
            f"The top-3 schedule risk drivers — {risk_phrase} — bind to "
            "the activities listed in the criticality note's risk-to-CP "
            "linkage table."
        )

    if high_mi_names:
        joined_high = "; ".join(high_mi_names)
        sentences.append(
            f"Activities with Mode-independent CI ≥ 70% from this linkage "
            f"include {joined_high}."
        )

    if amp_count or sup_count:
        merge_clause = (
            f"surfaces {amp_count} activities in the amplified-by-Mode "
            f"band and {sup_count} in the suppressed-by-Mode band"
        )
        if amp_named:
            named_list = ", ".join(amp_named)
            cohort_template = (
                amplified_mode_tuning_note
                if amplified_mode_tuning_note is not None
                else AMPLIFIED_COHORT_NOTE_DEFAULT
            )
            merge_clause += cohort_template.format(named_list=named_list)
        sentences.append(
            "The merge-bias signal — activities where MC-CI and MI-CI "
            "diverge by more than the 0.15 band threshold — "
            + merge_clause
            + "."
        )

    return " ".join(sentences).strip()


def _is_number(value: Any) -> bool:
    """True when value is a finite int/float (rejects NaN)."""
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        try:
            return not (float(value) != float(value))  # noqa: PLR0124
        except Exception:
            return False
    return False
