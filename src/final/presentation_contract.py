"""What the deliverable shows, in what order, and what it must disclose.

PRESENT-01 (P-2, D-1a). The deliverable had no statement of its own shape. The Word renderer's
section order lived in the order of calls inside ``word_generator``, the HTML body's lived in a
``PAGES`` list in a notebook cell, and nothing said the two were meant to agree or what either
owed the reader. A section could be reordered, or lost when a composer key was renamed, and no
test would notice - the reader of a client document cannot tell an absent section from one that
was never meant to be there.

This module is that statement. It is data, checked against the renderers by
``tests/test_presentation_contract.py``; changing what a renderer emits means changing this file,
and changing this file means bumping ``CONTRACT_VERSION``.

**The absence rule.** A section whose data is missing is **reported by name, in the artefact**,
never silently dropped. The HTML body prints a "Sections not produced by this run" line; the Word
renderer's ``if x:`` guards skip a block, which is why every Word section here names the composed
keys it needs, so a rename shows up as a named failure rather than a shorter document.
"""

from __future__ import annotations

from dataclasses import dataclass, field


#: Bumped whenever a section moves, is added, is removed, or a disclosure changes.
#: 1.0 - PRESENT-01, 18/09/2026: the first statement of the contract, written from the
#:       artefacts the two shipped projects actually render.
#: 1.1 - DELIVFIX-01, 22/09/2026: how the HTML body presents what is inside a section - each
#:       composed key's treatment and written label, and each page's order (``HTML_FIELDS``).
#: 1.2 - INTSCURVE-01 Part A, 28/10/2026: the integrated total leads the Distribution section;
#:       the HTML body gains what Word carried alone (the Stage 3 headline block, the integrated
#:       P-level table, the cost-arm S-curve), the integrated leave-one-out tornado leads the
#:       drivers, and the methodology states the delay-cost convention.
#: 1.3 - INTSCURVE-01 Part B, 28/10/2026: the total-cost S-curve (base + event-risk cost + delay
#:       cost) and its contingency table lead the Distribution section when the register's
#:       Layer 1 is on; the methodology names any Layer 1 factor D-4 leaves out of the base.
#: 1.4 - INTSCURVE-01 Part C, 28/10/2026: the joint confidence level (cost against finish, with
#:       its targets and the 70% frontier) follows the total-cost S-curve in Distribution.
CONTRACT_VERSION = "1.4"


@dataclass(frozen=True)
class Section:
    """One top-level section of a rendered deliverable.

    ``heading`` is the heading as a reader sees it. ``{label}`` resolves through
    :func:`src.final.contract_terms.term` and ``{metric}`` through the run's headline metric, so
    the contract pins the *shape* of a heading whose wording is contract- or run-dependent
    rather than pinning one project's wording.
    """

    name: str
    heading: str
    composed_keys: tuple[str, ...] = field(default_factory=tuple)
    #: True for a section that appears only when a Stage 3 result leads the run. The deliverable
    #: refuses a run without one (STAGE3HEADLINE-01 P1), so every shipped document carries these;
    #: a section-seam fixture composed without a Stage 3 result does not.
    requires_stage3: bool = False


#: The executive-summary Word document, in render order. Measured from the artefact, not read
#: off the call sequence.
WORD_SECTIONS: tuple[Section, ...] = (
    Section("executive_summary", "Executive summary", ("executive_summary",)),
    Section("stage3_headline", "{label} ({metric}, Stage 3)", ("executive_summary",),
            requires_stage3=True),
    Section("distribution_shape", "Distribution shape",
            ("page2_confidence_curve", "page2_distribution")),
    Section("main_report", "Main report"),
    Section("cost_drivers", "Risk drivers - cost", ("page3_cost_drivers",)),
    Section("schedule_drivers", "Risk drivers - schedule", ("page4_schedule_drivers",)),
    Section("criticality", "Activity-level criticality", ("page4b_criticality",),
            requires_stage3=True),
    Section("action_implications", "Action implications", ("page6_action_implications",)),
    Section("methodology", "Methodology and caveats", ("page7_methodology",)),
    Section("appendix", "Appendix"),
    Section("audit_trail", "Audit trail", ("page8_audit_trail",)),
)

#: The Stage 3 standalone document. Same order, with one extra section before the audit trail.
STAGE3_STANDALONE_SECTIONS: tuple[Section, ...] = (
    *WORD_SECTIONS[:-1],
    Section("criticality_detail", "Criticality detail"),
    WORD_SECTIONS[-1],
)

#: The HTML body, rendered by ``final_runner.ipynb``. Its order is the notebook's ``PAGES``
#: list; the test reads that list out of the committed notebook and compares it to this.
HTML_SECTIONS: tuple[Section, ...] = (
    Section("distribution", "## Distribution", ("page2_distribution",)),
    Section("cost_drivers", "## Cost drivers", ("page3_cost_drivers",)),
    Section("schedule_drivers", "## Schedule drivers", ("page4_schedule_drivers",)),
    Section("reconciliation", "## Reconciliation", ("page5_reconciliation",)),
    Section("action_implications", "## Actions and implications",
            ("page6_action_implications",)),
    Section("methodology", "## Methodology and caveats", ("page7_methodology",)),
    Section("audit_trail", "## Audit trail", ("page8_audit_trail",)),
)


@dataclass(frozen=True)
class Disclosure:
    """A statement the deliverable owes its reader, and where it owes it."""

    name: str
    where: str
    why: str


#: Statements that must appear, and the section that carries each. A disclosure is not a
#: stylistic preference: each is here because a reader who did not see it would draw a
#: different conclusion from the same numbers.
REQUIRED_DISCLOSURES: tuple[Disclosure, ...] = (
    Disclosure(
        "methodology_disclaimer",
        "Word: Methodology and caveats; HTML: page7_methodology",
        "The disclaimer states what the headline is a distribution of, what the schedule "
        "analysis replays, and what is deferred. Without it the headline is a number with no "
        "stated basis.",
    ),
    Disclosure(
        "cross_validation_status",
        "Word: the FAIL banner above the title, and the report_mode document property",
        "D-11 writes the artefact and then fails. A document produced by a failed run must say "
        "so on its face, because it exists and can be forwarded.",
    ),
    Disclosure(
        "absent_sections",
        "HTML: the 'Sections not produced by this run' line",
        "A section lost to a renamed composer key must not vanish quietly; the reader cannot "
        "tell an absence from an omission.",
    ),
    Disclosure(
        "reporting_p_level",
        "Word: the headline section; HTML: page2_distribution",
        "P80 is the recommendation and P99 is outlier-driven. A percentile quoted without its "
        "convention invites the reader to size contingency off the wrong one.",
    ),
    Disclosure(
        "input_provenance",
        "Word and HTML: the audit trail appendix",
        "Register, schedule and strawman hashes, the seed and the engine versions - what makes "
        "the run reproducible and the deliverable supersedable.",
    ),
)


# ---------------------------------------------------------------------------
# Inside a section: how the HTML body presents each composed key (DELIVFIX-01, FW-19, FW-20)
# ---------------------------------------------------------------------------
#
# The HTML body used to label every key with ``key.replace("_", " ").capitalize()`` - so the
# reader met "Orienting", "Metric name: P80", "Register path display" - and to show every dict as
# a stack of one-line paragraphs, never a table. The Word renderer states each key's treatment by
# hand and gets it right; this is that statement made once, as data, for the HTML body.
# The wording is taken from the Word renderer's where it has one.

LABEL = "label"      #: shown under a written label; a run of scalar labels is one two-column table
ROWS = "rows"        #: a flat dict whose entries join the enclosing two-column table
PROSE = "prose"      #: shown with no label - paragraphs, charts, and tables the heading introduces
HEADING = "heading"  #: the value IS a heading, shown only when the key it heads has content
HIDDEN = "hidden"    #: renderer settings and duplicates; never shown to a reader


@dataclass(frozen=True)
class Field:
    treatment: str
    label: str = ""
    #: ``str.format`` pattern for a scalar value, e.g. ``"${:,.0f}/wd"``.
    fmt: str = ""
    #: For a HEADING: the key whose content it heads.
    heads: str = ""


def _l(label: str, fmt: str = "") -> Field:
    return Field(LABEL, label, fmt)


_P, _X = Field(PROSE), Field(HIDDEN)

#: Every composed key the HTML body can meet inside a section. Keyed by the bare key: one key
#: means one thing wherever it appears (``orienting`` is prose on every page). A key missing here
#: still renders - under its code name, never dropped - and ``tests/test_delivfix01_html_blocks``
#: reds naming it.
HTML_FIELDS: dict[str, Field] = {
    # prose, charts, and tables their section heading already introduces
    **{k: _P for k in (
        "orienting", "interpretation", "orienting_tornado", "interpretation_tornado",
        "orienting_mode_sens", "interpretation_mode_sens", "orienting_matrix",
        "interpretation_matrix", "waterfall_orienting", "waterfall_interpretation",
        "rbs_l1_orienting", "why_mc_matters", "how_ages_well", "waterfall_caption",
        "convergence_caption", "convergence_caveat", "mode_independence_note",
        "criticality_reframe", "risk_matrix_forward_reference", "gating_collision_note",
        "banner", "summary_paragraphs", "standards_references", "dp_review_caveat",
        "distribution_shape_explainer_intro", "distribution_shape_explainer_bullets",
        "limitations_closing", "single_iteration_intro", "single_iteration_walkthrough",
        "single_iteration_table", "cg_drivers_orienting_paragraphs", "cross_validation_sentence",
        "reproducibility_paragraph", "distribution_choices_summary",
        "s_curve_path", "density_path", "waterfall_path", "tornado_path", "risk_matrix_path",
        "convergence_chart_path", "drivers_table", "rbs_l1_breakdown_table",
        "mode_sensitivity_table", "mode_sensitivity_summary", "table", "comparison_table",
        "cross_validation_panel", "treatment_roi_table",
        # INTSCURVE-01 Part A
        "integrated_orienting", "integrated_s_curve_path", "integrated_density_path",
        "buildup_orienting", "buildup_s_curve_path", "confidence_curve_preamble",
        "confidence_curve_table", "confidence_curve_footnote", "cost_distribution_orienting",
        "cost_s_curve_path", "cost_density_path", "integrated_tornado_orienting",
        "integrated_tornado_path", "delay_cost_convention", "stage3_headline_heading",
        "stage3_headline_lead", "stage3_headline_table", "stage3_headline_basis",
        # INTSCURVE-01 Part B
        "total_cost_orienting", "total_cost_s_curve_path", "total_cost_table",
        "total_cost_basis", "base_layer_exclusion",
        # INTSCURVE-01 Part C
        "jcl_orienting", "jcl_path", "jcl_sentence", "jcl_basis",
    )},
    # headings carried as data
    "why_mc_matters_title": Field(HEADING, heads="why_mc_matters"),
    "how_ages_well_title": Field(HEADING, heads="how_ages_well"),
    "rbs_l1_heading": Field(HEADING, heads="rbs_l1_breakdown_table"),
    "confidence_curve_heading": Field(HEADING, heads="confidence_curve_table"),
    "cost_distribution_heading": Field(HEADING, heads="cost_s_curve_path"),
    "schedule_distribution_heading": Field(HEADING, heads="s_curve_path"),
    "integrated_tornado_heading": Field(HEADING, heads="integrated_tornado_path"),
    "delay_cost_convention_heading": Field(HEADING, heads="delay_cost_convention"),
    "total_cost_heading": Field(HEADING, heads="total_cost_s_curve_path"),
    "jcl_heading": Field(HEADING, heads="jcl_path"),
    # renderer settings, and what the Word renderer deliberately leaves out
    **{k: _X for k in (
        "metric_name", "value_column_header", "rbs_l1_metric_name", "bold_row_index",
        "drivers_table_full",              # the top-five table's rows plus the rest; Word omits it
        "register_path", "strawman_path",  # the analyst's local paths; the basenames are shown
    )},
    # written labels
    "cg_drivers_table": _l("Correlation group (CG) drivers"),
    "limitations_current": _l("Limitations of current analysis"),
    "recommendations": _l("Recommendations"),
    "caveats": _l("Caveats"),
    "references": _l("References"),
    "register_path_display": _l("Risk register file"),
    "strawman_path_display": _l("Strawman methodology workbook"),
    "run_date": _l("Run date"),
    "iterations": _l("Iterations", "{:,}"),
    "random_seed": _l("Random seed"),
    "day_rate_dollars_per_workday": _l("Day rate", "${:,.0f}/wd"),
    "reporting_p_level": _l("Reporting P-level", "P{}"),
    "engine_versions": Field(ROWS),
    "package": _l("Package version"),
    "engine": _l("Engine commit"),
    "input_hashes": _l("Input file hashes (SHA-256)"),
    "register_sha256": _l("Risk register"),
    "strawman_sha256": _l("Strawman"),
    "p6_sha256": _l("Schedule (P6)"),
}

#: Column headers the composer emits as code names; written headers pass through unchanged.
COLUMN_LABELS: dict[str, str] = {
    "cg_id": "CG ID",
    "driver_description": "Driver description",
    "member_risk_ids": "Member risks",
    "member_risk_count": "Member risk count",
    "coefficient": "Coefficient",
}

#: Enumerated values that reach the reader.
VALUE_LABELS: dict[str, str] = {
    "stage3_cost_arm_additive": "the Stage 3 replay",
    "register_mode_baseline": "the register's Mode baseline",
}

#: Each page's order, from the Word renderer's. Keys not listed follow, in composed order, so a
#: new key is shown rather than lost.
HTML_ORDER: dict[str, tuple[str, ...]] = {
    "page2_distribution": ("total_cost_heading", "total_cost_orienting",
                           "total_cost_s_curve_path", "total_cost_table", "total_cost_basis",
                           "jcl_heading", "jcl_orienting", "jcl_path", "jcl_sentence",
                           "jcl_basis",
                           "integrated_orienting", "integrated_s_curve_path",
                           "integrated_density_path", "buildup_orienting",
                           "buildup_s_curve_path", "confidence_curve_heading",
                           "confidence_curve_preamble", "confidence_curve_table",
                           "confidence_curve_footnote", "waterfall_caption", "waterfall_path",
                           "cost_distribution_heading", "cost_distribution_orienting",
                           "cost_s_curve_path", "cost_density_path",
                           "schedule_distribution_heading", "orienting", "s_curve_path",
                           "density_path", "interpretation"),
    "page3_cost_drivers": ("integrated_tornado_heading", "integrated_tornado_orienting",
                           "integrated_tornado_path", "orienting", "tornado_path", "drivers_table", "mode_independence_note",
                           "interpretation", "rbs_l1_heading", "rbs_l1_orienting",
                           "rbs_l1_breakdown_table"),
    "page4_schedule_drivers": ("orienting_tornado", "tornado_path", "drivers_table",
                               "interpretation_tornado", "criticality_reframe",
                               "risk_matrix_forward_reference", "rbs_l1_heading",
                               "rbs_l1_orienting", "rbs_l1_breakdown_table",
                               "orienting_mode_sens", "mode_sensitivity_table",
                               "interpretation_mode_sens", "orienting_matrix", "risk_matrix_path",
                               "interpretation_matrix", "gating_collision_note"),
    "page5_reconciliation": ("orienting", "comparison_table", "interpretation",
                             "waterfall_orienting", "waterfall_path", "waterfall_interpretation",
                             "cross_validation_panel"),
    "page6_action_implications": ("orienting", "banner", "treatment_roi_table", "interpretation",
                                  "recommendations"),
    "page7_methodology": ("summary_paragraphs", "distribution_shape_explainer_intro",
                          "distribution_shape_explainer_bullets", "mode_sensitivity_summary",
                          "standards_references", "delay_cost_convention_heading",
                          "delay_cost_convention", "base_layer_exclusion",
                          "convergence_chart_path", "convergence_caption",
                          "convergence_caveat", "dp_review_caveat",
                          "cg_drivers_orienting_paragraphs", "cg_drivers_table",
                          "limitations_current", "limitations_closing", "single_iteration_intro",
                          "single_iteration_walkthrough", "single_iteration_table"),
    "page8_audit_trail": ("register_path_display", "strawman_path_display", "run_date",
                          "iterations", "random_seed", "day_rate_dollars_per_workday",
                          "reporting_p_level", "engine_versions", "cross_validation_sentence",
                          "reproducibility_paragraph", "input_hashes"),
}
HTML_ORDER["appendix_audit_trail"] = HTML_ORDER["page8_audit_trail"]


def word_sections(
    *, stage3_standalone: bool = False, stage3: bool = True,
) -> tuple[Section, ...]:
    """The Word section sequence for one of the two documents this product writes.

    ``stage3=False`` drops the sections that only a Stage 3 run produces, which is what a
    section-seam fixture renders. No shipped deliverable takes that path.
    """
    sections = STAGE3_STANDALONE_SECTIONS if stage3_standalone else WORD_SECTIONS
    return sections if stage3 else tuple(s for s in sections if not s.requires_stage3)


def resolve_heading(section: Section, *, metric: str = "P80") -> str:
    """The heading as a reader sees it, for the active project."""
    from src.final import contract_terms

    return section.heading.format(
        label=contract_terms.term("headline_contingency_label"), metric=metric,
    )
