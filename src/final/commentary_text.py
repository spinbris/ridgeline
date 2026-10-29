# SR9 v3 amendment - 2026-04-26 - presentation-layer reframe.
# SR9 v3.1 amendment - 2026-04-26 - clarity / Director eyeball + research peer review.
"""SR9 v3 / v3.1 commentary text.

Single source of truth for narrative content used by composer,
word_generator, and notebook. Following the COMMENTARY-FIRST RENDERING
principle from the v3 brief, each chart and table is bracketed by an
orienting paragraph (above) and an interpretation paragraph (below).

Templates with placeholders (HEADLINE_OPENING etc.) are filled at runtime
by composer using engine outputs - no hardcoded numerical literals.

Static narrative (standards refs, DP review caveat, limitations,
criticality reframe, callouts) lives here and in callout_text.py.

v3.1 additions:
  - HEADLINE_INTEGRATED_P80, SCHEDULE_DAYS_CONTEXT, MODE_CAVEAT_HEADLINE
    (Deliverable 10 Page 1 restructure around integrated P80 dollar
    figure as the single recommended contingency).
  - READING_CONVENTION (Deliverable 5 framed paragraph at top of
    executive summary).
  - DOMINANT_RISK_TEMPLATE (Deliverable 4 single-risk dominance
    finding surfaced near headline; project copy lives in the active
    binding's NARRATIVE_TEMPLATES, this is the generic fallback).
  - COST_DRIVERS_MODE_INDEPENDENCE_NOTE (Deliverable 6 clarity note
    below cost drivers table).
  - MEAN_COST_IDENTICAL_NOTE (Deliverable 9 explanation below the
    headline range table).
  - CONFIDENCE_CURVE_PREAMBLE / CONFIDENCE_CURVE_FOOTNOTE
    (Deliverable 11 Page 2 confidence curve table, industry-standard
    multi-P-level integrated contingency view).

  HEADLINE_OPENING is retained for backward compatibility but is no
  longer rendered by the v3.1 Page 1 layout; the new sequence is
  HEADLINE_INTEGRATED_P80 -> component breakdown -> SCHEDULE_DAYS_CONTEXT
  -> MODE_CAVEAT_HEADLINE -> READING_CONVENTION callout -> dominant-risk
  dominance -> existing range table (Table 0) with mean-cost note.
"""

from __future__ import annotations


# ----------------------------------------------------------------------------
# Page 1 - Headline (v3.1: integrated P80 lead)
# ----------------------------------------------------------------------------

# v3 headline (retained for back-compat; not rendered in v3.1 Page 1).
#: Beta-17 Item 3, Mean / median / buffer-choice framing paragraph.
#: Rendered immediately after the headline figure and BEFORE the
#: six-approach reconciliation table + component breakdown in §1.
#: Three sentences:
#:   1. Mean = expected outcome across simulated futures (portfolio answer).
#:   2. P80 = conservative buffer where ~4 in 5 futures finish at or below.
#:   3. Choice is risk-appetite, not arithmetic, Mean for shared-risk
#:      buffer arithmetic; P80 for unilateral conservative provisioning.
#:
#: Restores the V5-era April 13 §7.1-7.4 portfolio framing the trim
#: over-compressed. Static text, no per-mode variant required because
#: the framing is methodology-neutral.
PORTFOLIO_FRAMING_PARAGRAPH = (
    "Mean reflects the expected outcome across all simulated futures, "
    "the portfolio answer rather than the single-instance answer. P80 "
    "reflects a conservative buffer at which roughly four in five "
    "simulated futures finish at or below the contingency level. The "
    "choice between Mean and P80 framing is a risk-appetite judgement: "
    "Mean for shared-risk buffer arithmetic where parties agree to size "
    "to expected losses, P80 for unilateral conservative provisioning "
    "where one party bears the tail."
)


HEADLINE_OPENING = (
    "Schedule risk analysis indicates a mean schedule slip of "
    "{mean_days:.1f} days under interim classification, "
    "equivalent to ${mean_cost_m:.2f}M at ${day_rate:,.0f} per working "
    "day. The classification is interim; PM review of Mode "
    "classifications may shift this number. Range across plausible "
    "classifications: {lower_days:.1f} to {upper_days:.1f} days mean."
)

HEADLINE_INTERPRETATION = (
    "The three-scenario range below shows how Mode classifications drive "
    "the headline. DP Review is a methodologically conservative starting "
    "point; Dummy Realistic is the working assumption pending PM "
    "review; All Series is the methodological upper bound. Both the "
    "indicative and the range matter - the range is the consequence of "
    "interim classification uncertainty."
)

# STAGE3HEADLINE-01 (D-1, D-2; review B4): the page-one HTML strings when Stage 3 leads.
# The placeholders match HEADLINE_OPENING so the composer's one format call serves both.
HEADLINE_OPENING_STAGE3 = (
    "Schedule risk analysis on the Stage 3 CPM replay indicates a mean schedule slip of "
    "{mean_days:.1f} days, equivalent to ${mean_cost_m:.2f}M at ${day_rate:,.0f} per working "
    "day. The Stage 2.5 Mode-scenario comparators span {lower_days:.1f} to {upper_days:.1f} "
    "days mean; they are shown for continuity with earlier reporting and are not the headline."
)
HEADLINE_INTERPRETATION_STAGE3 = (
    "The headline is one Stage 3 distribution: each risk's delay is injected at its declared "
    "gating activity and propagated through the programme's own logic, and the P50 to P95 "
    "spread is project uncertainty rather than a spread between Mode assumptions. The table "
    "below is the Stage 2.5 comparator range - the DP Review baseline and the All Series upper "
    "bound that earlier reports published as the headline - with the Stage 3 figure placed "
    "between them for reconciliation. Cost analysis is independent of Mode classification."
)

# v3.1 Page 1 lead: single recommended contingency figure.
HEADLINE_INTEGRATED_P80 = (
    "Recommended project contingency: ${integrated_p80_m:.2f} M "
    "(P80, integrated cost plus schedule)."
)

SCHEDULE_DAYS_CONTEXT = (
    "Schedule slip in days: {p80_days:.1f} days at P80 "
    "(schedule contingency at 80% confidence, matching cost contingency "
    "convention per AACE RP 41R-08 / 65R-11); {mean_days:.1f} days mean "
    "(expected slip on average; reconciles with EMV)."
)

MODE_CAVEAT_HEADLINE = (
    "The headline reflects interim Mode classification. The "
    "Mode as registered (DP Review baseline, {dp_review_mix}) gives an "
    "integrated P80 of ${dp_review_p80_m:.2f} M; the methodological "
    "upper bound (All Series, {all_series_mix}) is ${all_series_p80_m:.2f} M. PM "
    "review of Mode classifications will narrow this range."
)

# Reading convention callout (D5).
READING_CONVENTION_TITLE = "Reading convention"

READING_CONVENTION = (
    "This document presents the schedule analysis primarily under the "
    "interim Mode classification (Dummy Realistic, {indicative_mix}) "
    "because it provides interpretable headline numbers pending PM "
    "review. The Mode as registered (DP Review baseline, {dp_review_mix}) "
    "is presented as the lower bound of the headline range. The All "
    "Series scenario ({all_series_mix}) is the methodological upper bound. Cost "
    "analysis is independent of Mode classification."
)

# Single-risk dominance finding template (D4), parameterised on the top
# driver. Filled at runtime with composed['page1_top_schedule_driver'] data.
# This is the GENERIC engine fallback; the project's own copy lives in the
# active binding's NARRATIVE_TEMPLATES["dominant_risk"] and is preferred by
# resolve_dominant_risk_template() below. (Was R017_DOMINANCE_TEMPLATE.)
DOMINANT_RISK_TEMPLATE = (
    "A single risk - {top_risk_id} ({top_risk_short_title}) - "
    "accounts for approximately {top_risk_pct:.0%} of the mean schedule "
    "slip. Resolution of {top_risk_id} is the highest-value "
    "risk-treatment action."
)

# Generic fallback phrasing when the top risk's share is below 50%.
# (Was R017_DOMINANCE_FALLBACK.)
DOMINANT_RISK_FALLBACK = (
    "The top three schedule risks account for approximately "
    "{top3_pct:.0%} of the mean schedule slip. Resolution of these "
    "risks is the highest-value risk-treatment action."
)

# Note immediately below the headline range table (D9).
MEAN_COST_IDENTICAL_NOTE = (
    "Mean cost is identical across scenarios because cost contingency "
    "is independent of Mode classification. Schedule contingency "
    "varies with Mode; integrated P80 contingency includes both."
)

# Note below the cost drivers table (D6) - cost drivers are
# Mode-independent, surface that point so the reader does not infer
# a Mode dependency from surrounding context.
COST_DRIVERS_MODE_INDEPENDENCE_NOTE = (
    "Cost contingency is independent of Mode classification; top cost "
    "drivers are the same across all three scenarios in the headline "
    "range."
)

# Confidence curve table preamble (D11).
CONFIDENCE_CURVE_PREAMBLE = (
    "P80 is the recommended industry-standard contingency level for "
    "engineering and construction projects (USACE Cost Engineering DX "
    "guidance, AACE RP 41R-08 / 65R-11). Higher confidence increases "
    "conservatism; lower reduces it."
)

CONFIDENCE_CURVE_FOOTNOTE = (
    "Above naive sum column shows how much the integrated "
    "(joint cost+schedule) contingency exceeds the simple addition "
    "of cost-only and schedule-only contingencies at the same "
    "P-level. Positive values indicate cost and schedule are "
    "correlated through shared tail risks. Schedule slip column "
    "is dollarised at the day rate to populate the integrated "
    "contingency; raw days shown for engineering reference."
)


# ----------------------------------------------------------------------------
# Page 2 - Distribution shape (S-curve + density histogram)
# ----------------------------------------------------------------------------

DISTRIBUTION_ORIENTING = (
    "These charts show the full probability distribution of schedule "
    "slip, not just point estimates. The S-curve shows cumulative "
    "probability; the histogram shows the right-skewed shape. "
    "Cumulative probability runs from 0 (no slip) to 100 (all simulated "
    "outcomes are at or below this level). Reference percentiles "
    "(P50, P80, P90, P95) are marked as vertical lines."
)

# Beta-11 §3: GENERIC fallback (no specific risk named). Used by the
# notebook display cell and by the formatter when no tail risk meets
# the picker's prob < 5% threshold. The dynamic version with the actual
# tail risk's id / probability / mean-when-fired comes from
# `format_distribution_interpretation(tail_risk)` in executive_summary.py
# and is wired into composed["page2_distribution"]["interpretation"].
DISTRIBUTION_INTERPRETATION = (
    "The right-skew is a direct consequence of low-probability, "
    "high-impact risks. Mean is pulled to the right of median by the "
    "tail; the distance between P80 and P95 widens as Mode shifts from "
    "Parallel toward Series. Selecting a contingency at the mean leaves "
    "roughly half the simulated outcomes uncovered; selecting at P80 "
    "covers four in five. The choice is risk appetite, not arithmetic."
)

# Beta-11 §3: dynamic template, placeholders filled at format time by
# `format_distribution_interpretation(tail_risk)` from a synthetic dict
# returned by `pick_tail_risk(schedule_drivers)`.
DISTRIBUTION_INTERPRETATION_TEMPLATE = (
    "The right-skew is a direct consequence of low-probability, "
    "high-impact risks like {tail_risk_id} ({tail_risk_prob:.1%} "
    "probability, {tail_risk_mean_when_fired:.0f}d mean impact when "
    "fired). Mean is pulled to the right of median by the tail; the "
    "distance between P80 and P95 widens as Mode shifts from Parallel "
    "toward Series. Selecting a contingency at the mean leaves roughly "
    "half the simulated outcomes uncovered; selecting at P80 covers "
    "four in five. The choice is risk appetite, not arithmetic."
)


# ----------------------------------------------------------------------------
# Page 3 - Cost drivers (tornado + table)
# ----------------------------------------------------------------------------

COST_TORNADO_ORIENTING = (
    "The cost tornado ranks risks by their P80 contribution to total "
    "cost contingency. Each bar's length is the dollar value at the "
    "P80 percentile of that risk's per-iteration cost; longer bars are "
    "larger drivers. The label shows the dollar value and the share of "
    "total P80 cost contingency."
)

# Beta-16 Item 1: dynamic template, composer fills {metric_name} with
# either "Mean" (in the Mean-headline docx) or "P80" (in the P80-headline
# docx) so the prose tracks the docx variant. The static
# COST_TORNADO_ORIENTING above is retained for back-compat / notebook
# display where the metric is unambiguously P80.
COST_TORNADO_ORIENTING_TEMPLATE = (
    "The cost tornado ranks risks by their {metric_name} contribution to "
    "total cost contingency. Each bar's length is the dollar value at "
    "the {metric_phrase} of that risk's per-iteration cost; longer bars "
    "are larger drivers. The label shows the dollar value and the share "
    "of total {metric_name} cost contingency."
)


def format_cost_tornado_orienting(metric_name: str) -> str:
    """Render the cost-tornado orienting paragraph for the given metric.

    Beta-16 Item 1: composer passes the resolved headline metric ("P80" or
    "Mean") so the section opens with a sentence that matches the docx
    variant's ranking metric. ``metric_phrase`` is a thin grammar shim so
    the rendered prose reads naturally ("the P80 percentile" vs "the mean")
    without forcing the caller to think about the noun form.
    """
    metric_name = str(metric_name).strip()
    if metric_name.lower() == "mean":
        metric_phrase = "mean"
    else:
        # Treat anything else (default / "P80") as the percentile case so
        # the legacy notebook path keeps reading naturally.
        metric_phrase = f"{metric_name} percentile"
    return COST_TORNADO_ORIENTING_TEMPLATE.format(
        metric_name=metric_name,
        metric_phrase=metric_phrase,
    )


COST_TORNADO_INTERPRETATION = (
    "A small number of risks dominate cost contingency. Treatment effort "
    "concentrated on the top three drivers delivers the largest "
    "contingency reduction; the long tail contributes incrementally. "
    "This pattern - top-3 dominance - is consistent with industry "
    "experience and validates focusing risk treatment plans on the "
    "ranked top slice."
)


# ----------------------------------------------------------------------------
# Beta-16 Item 2, Cost outturn distribution (Page 2 subsection)
# ----------------------------------------------------------------------------
# Sits between *Confidence curve - integrated contingency by P-level* and
# *Schedule slip distribution* inside the Page 2 *Distribution shape*
# section. Restores the cost-side graphical view dropped in the SR9 v3
# trim. The chart pair (S-curve + density histogram) is built from the
# integrated engine's cost-arm samples under the indicative scenario; the
# cost arm is Mode-independent so a single curve is correct (brief
# Decision 4). No P(no slip) callout, cost MC has no zero spike.

# INTSCURVE-01 P1: the lead chart of the Distribution section.
INTEGRATED_TOTAL_ORIENTING = (
    "The integrated contingency is the headline distribution: in each iteration, the event-risk "
    "cost plus the finish delay that survives float, priced at the day rate. The S-curve gives "
    "the probability that the contingency needed is at or below any dollar value, with P50, "
    "P80, P90 and P95 marked; the recommended contingency is read off it at P80. The histogram "
    "below shows the same distribution's shape."
)

# INTSCURVE-01 P2: the cumulative build-up.
INTEGRATED_BUILDUP_ORIENTING = (
    "The build-up draws the same total in layers on one dollar axis: event-risk cost alone, then "
    "with delay cost added. The gap between the two curves at any probability is what schedule "
    "delay adds at that confidence level. Because the two arms are sampled jointly, the gap at "
    "P80 is not the delay cost's own P80; the P80 build-up further down shows the difference as "
    "the joint-sampling adjustment."
)

# INTSCURVE-01 Part B: the total-cost S-curve, base beneath the contingency.
TOTAL_COST_ORIENTING = (
    "The total-cost S-curve puts the base estimate beneath the contingency, in layers on one "
    "dollar axis: the base with its systemic (Layer 1) uncertainty, then plus event-risk cost, "
    "then plus delay cost. Contingency at any confidence level is the total at that level less "
    "the declared base. Read that way it also carries the base's own uncertainty, so it is "
    "larger than the event-risk contingency the headline recommends, which this chart does not "
    "replace: it shows where that contingency sits on the project's whole cost."
)

TOTAL_COST_BASIS = (
    "Base: the register's Layer 1 estimate of {base}, sampled with its systemic factors on a "
    "random stream of its own, so the event-risk figures above are unchanged by it, and "
    "independent of the event risks. {illustrative}"
)

#: Said wherever a synthetic project's base is drawn (Part B property 9).
ILLUSTRATIVE_BASE = "The base is illustrative: this is a synthetic project."

#: Replaces ``L1_SYSTEMIC_CAVEAT_BULLET`` when the run draws the base layer (Part B).
L1_BASE_DRAWN_CAVEAT_BULLET = (
    "The headline presents the event-risk contingency (Layer 2) on an input base estimate. The "
    "total-cost S-curve adds that base with its systemic uncertainty (Layer 1), sampled "
    "independently of the event risks; the base estimate itself remains an input, not an "
    "estimate this product makes."
)

# INTSCURVE-01 Part C: the joint confidence level.
JCL_ORIENTING = (
    "Each dot is one iteration: its cost on the vertical axis and its finish on the horizontal. "
    "The dashed lines are the budget and the P80 finish; the dark dots meet both. The cost axis "
    "leaves out delay cost, because delay is already on the finish axis and would otherwise be "
    "counted twice. The orange line is where 70% of iterations meet both (the NASA reference "
    "norm); no Australian guidance requires a joint confidence level, so it is shown beside the "
    "headline, not as one."
)

JCL_BASIS = (
    "Cost and schedule are sampled jointly: a risk that fires raises cost and delays the finish "
    "in the same iteration. That pulls the dots toward one diagonal, so the JCL is higher than "
    "it would be if the two were drawn independently."
)

# INTSCURVE-01 P3: the integrated tornado.
INTEGRATED_TORNADO_ORIENTING = (
    "Each bar is the integrated P{p} saved if that one risk were removed, with every other "
    "risk's draws held fixed ({iterations:,} iterations, the run's own seed and joint sampling). "
    "It is a leave-one-out figure, not a contribution: the bars do not add up to the total, "
    "because removing two risks together is not the same as removing each alone. Each bar is "
    "split into the risk's cost and the delay cost its removal saves, which is zero for a risk "
    "with no time impact and can be small for one whose delay float absorbs. A chain child keeps "
    "the fire state the run gave it when its parent is removed."
)

# INTSCURVE-01 P7 (Director, 28/10/2026; last sentence the Reviewer's, Director-approved the
# same day): the delay-cost convention, word for word in the register instructions, the playbook, METHODOLOGY.md section 4.4 and the report caveats.
DELAY_COST_CONVENTION = (
    "Risk cost impacts exclude project time-related costs (preliminaries and site overheads). "
    "The model prices those once, through the day rate, on the finish delay that survives float "
    "in each iteration. Event-specific standby (idle plant or crew, demobilise / remobilise) is "
    "a direct cost and stays in the risk's cost impact. The day rate itself covers "
    "preliminaries and site overheads only, with no standby, so the same cost cannot enter "
    "through both the day rate and a risk's cost impact."
)

COST_DISTRIBUTION_ORIENTING = (
    "The event-risk cost distribution shows the per-iteration total "
    "event-risk cost from the integrated Monte Carlo simulation. The "
    "S-curve gives the cumulative probability of total event-risk cost at "
    "any dollar value; the density histogram shows the right-skewed "
    "shape characteristic of event-risk distributions where most "
    "iterations cluster near the mean and a long tail captures rare "
    "high-cost scenarios. Reference percentiles P50, P80, P90, and P95 "
    "are marked. Read this view alongside the integrated P-level table "
    "above to understand both the marginal cost distribution shape and "
    "the joint integrated headline figure."
)


# ----------------------------------------------------------------------------
# Page 4 - Schedule drivers and Mode sensitivity
# ----------------------------------------------------------------------------

SCHEDULE_TORNADO_ORIENTING = (
    "The schedule tornado ranks risks by **probability-weighted mean "
    "contribution** in days, not by P80. For low-probability discrete "
    "risks the P80 quantile is mathematically zero; reporting at P80 "
    "would obscure the contribution. Probability-weighted mean (firing "
    "probability times mean impact when fired) is the appropriate "
    "ranking metric and matches the EMV first-principles calculation."
)

SCHEDULE_TORNADO_INTERPRETATION = (
    "Schedule contribution concentrates in a different set of risks "
    "than cost contribution. Cost-only analysis cannot infer schedule "
    "drivers; integrated cost-and-schedule MC is required to surface "
    "the schedule-dominant risks."
)

MODE_SENSITIVITY_ORIENTING = (
    "The 12-scenario counterfactual table quantifies how the headline "
    "mean schedule slip would shift under each plausible single-risk "
    "Mode reclassification. Each row shows mean slip if that risk were "
    "reclassified to Series while all other classifications remain at "
    "DP Review. Rows with delta > 1 day from baseline are the "
    "high-leverage Mode decisions; resolving these classifications "
    "narrows the headline range substantially."
)

MODE_SENSITIVITY_INTERPRETATION = (
    "PM review should prioritise the rows highlighted above. The "
    "highest-leverage classifications are the ones where reclassifying "
    "to Series shifts the mean by more than one day; these are the "
    "decisions that move the contingency. Risks whose Mode shift "
    "produces sub-day movement contribute to range width but not to "
    "the central estimate."
)

CRITICALITY_REFRAME = (
    "Note: the per-risk contribution column above is "
    "Mode-conditioned - it equals probability times mean impact times "
    "Mode multiplier. Risks classified Parallel show zero contribution "
    "by construction. This validates the Mode mechanism is applied "
    "correctly; it does not test the Mode classifications themselves. "
    "True Mode-independent empirical criticality (running each risk at "
    "full impact regardless of assumed Mode and measuring "
    "finish-extension rate) is computed in a future stage."
)

RISK_MATRIX_ORIENTING = (
    "Two risk matrices compared side by side. Left: traditional "
    "probability vs mean impact (days when fired), the matrix engineers "
    "see in standard QRA. Right: probability vs probability-weighted "
    "impact (probability times mean impact) - the matrix that ranks "
    "risks the way Monte Carlo does. Both panels use the same indicative "
    "Mode scenario data as the schedule drivers table immediately above, "
    "so plotted x-coordinates match the table values. Each marker is a "
    "risk; the top contributors are labelled with their risk IDs."
)

# Beta-11a Fix 3: dynamic template, placeholder filled at format time
# by `format_risk_matrix_orienting(matrix_scenario)` so the Word doc
# names the scenario explicitly. Notebook display cell continues to
# render the static RISK_MATRIX_ORIENTING above (out of scope per
# Beta-11 / Beta-11a, no notebook changes).
RISK_MATRIX_ORIENTING_TEMPLATE = (
    "Two risk matrices compared side by side. Left: traditional "
    "probability vs mean impact (days when fired), the matrix engineers "
    "see in standard QRA. Mean impact when fired is the PERT mean of the "
    "register Optimistic/Most Likely/Pessimistic days and is independent "
    "of Mode classification. Right: probability vs probability-weighted "
    "impact (probability times Mode-multiplied mean impact), the matrix "
    "that ranks risks the way Monte Carlo does. Markers on the right panel "
    "reflect the {matrix_scenario} Mode scenario; the schedule-drivers "
    "table immediately above uses the same scenario for consistency, so "
    "right-panel x-coordinates match the table's Probability x mean impact "
    "column. Each marker is a risk; the top contributors are labelled "
    "with their risk IDs."
)

# Beta-11 §3: GENERIC fallback (no specific risk named). Used by the
# notebook display cell and by the formatter when no tail risk meets
# the picker's prob < 5% threshold. Dynamic version comes from
# `format_risk_matrix_interpretation(tail_risk)` in executive_summary.py.
RISK_MATRIX_INTERPRETATION = (
    "Compare the position of low-probability, high-impact risks across "
    "the two panels. On the traditional matrix they sit at low "
    "probability and high mean impact - easy to deprioritise in "
    "standard prioritisation. On the probability-weighted matrix they "
    "rank higher because the integrated mean impact captures the tail. "
    "This differential ranking is the visual case for MC over standard "
    "matrices."
)

# Beta-11 §3: dynamic template, placeholders filled at format time by
# `format_risk_matrix_interpretation(tail_risk)`. Beta-14 §3 replaces
# the prior prose with a Mode-multiplier-honest version that names the
# raw EV PERT (Mode-independent) separately from the Mode-multiplied
# probability-weighted contribution.
RISK_MATRIX_INTERPRETATION_TEMPLATE = (
    "Compare the position of {tail_risk_id} across the two panels. On "
    "the traditional matrix {tail_risk_id} sits at {tail_risk_prob:.1%} "
    "probability and {raw_ev_pert_days:.0f}d mean impact when fired, "
    "the PERT mean of its registered Optimistic/Most Likely/Pessimistic "
    "days, Mode-independent. On the probability-weighted matrix "
    "{tail_risk_id} ranks at {tail_risk_pct_of_mean_slip:.1%} of mean "
    "schedule slip ({tail_risk_rank} of {n_drivers} drivers). The "
    "probability-weighted figure applies the Mode multiplier "
    "({mode_label}: {multiplier_value:.1f}), under {variant_label} that "
    "contribution is {mode_weighted_days:.1f}d per fire, materially less "
    "than the traditional matrix's mean-impact-when-fired figure because "
    "the multiplier accounts for the activity's position relative to the "
    "longest path. This differential ranking is the visual case for MC "
    "over standard matrices."
)

# Beta-11 era template, retained for backwards compatibility with tests
# (and any caller) that pass an un-enriched tail_risk dict (i.e. without
# raw_ev_pert_days / mode_label / multiplier_value / mode_weighted_days /
# variant_label). New composer call sites should enrich via
# `enrich_tail_risk_for_matrix(...)` and the format helper will route to
# the Beta-14 template above.
RISK_MATRIX_INTERPRETATION_TEMPLATE_LEGACY = (
    "Compare the position of {tail_risk_id} across the two panels. On "
    "the traditional matrix {tail_risk_id} sits at {tail_risk_prob:.1%} "
    "probability and {tail_risk_mean_when_fired:.0f}d mean impact when "
    "fired - a low-probability, high-impact risk easy to deprioritise "
    "in standard prioritisation. On the probability-weighted matrix "
    "{tail_risk_id} ranks at {tail_risk_pct_of_mean_slip:.1%} of mean "
    "schedule slip ({tail_risk_rank} of {n_drivers} drivers) - higher "
    "in the integrated ranking than in the traditional matrix because "
    "the mean impact captures the tail. This differential ranking is "
    "the visual case for MC over standard matrices."
)


# ----------------------------------------------------------------------------
# Page 5 - Reconciliation and validation
# ----------------------------------------------------------------------------

COMPARISON_ORIENTING = (
    "How does this MC result compare to first-principles and gut-feel "
    "methods that the reader is likely familiar with? The table below "
    "lists six approaches that all aim at the same question - how much "
    "contingency? - and shows what each one produces against the same "
    "risk register."
)

# Beta-11 §3: COMPARISON_INTERPRETATION did not previously hardcode a tail risk directly
# (that lived in WATERFALL_INTERPRETATION below); kept here for parity with the brief's
# three-site list and as the generic fallback.
COMPARISON_INTERPRETATION = (
    "MC mean reconciles with EMV (sum of probability times mean impact) "
    "to within MC noise - this is a validation check that the "
    "simulation is implementing the underlying first-principles "
    "calculation correctly. Beyond that reconciliation, MC adds tail "
    "visibility (P80, P95) that deterministic methods cannot provide. "
    "Engineering judgement bounds (10-20% of programme) bracket the MC "
    "result, confirming the result sits within the range a seasoned "
    "engineer would recognise."
)

WATERFALL_ORIENTING = (
    "How is the integrated cost-plus-schedule P80 constructed? The "
    "waterfall below traces the components: cost-only P80, then "
    "schedule slip dollarised, then the diversification adjustment "
    "(or anti-diversification) under joint sampling. The two scenarios "
    "shown are the headline and the All Series upper bound."
)

# Beta-11 §3: GENERIC fallback (no specific risk named). Dynamic
# version comes from `format_comparison_interpretation(tail_risk)`.
# Brief §3.3 listed this as the COMPARISON_INTERPRETATION site at
# :316-326, corrected: the named-risk reference lived here in
# WATERFALL_INTERPRETATION. The placeholder substitution is the same
# either way (single tail-risk picker drives both narratives).
WATERFALL_INTERPRETATION = (
    "Under the headline distribution, integrated P80 may exceed "
    "the naive sum of cost-only P80 and schedule-only P80. This is a "
    "counterintuitive but real result of joint sampling: when a "
    "low-probability, high-impact tail risk couples cost and schedule "
    "simultaneously, the joint P80 captures correlated worst-case "
    "behaviour the marginal P80s miss. Under All Series, joint sampling "
    "produces a small diversification benefit because cost-driver and "
    "schedule-driver risks fire independently."
)

# Beta-11 §3: dynamic template, placeholders filled at format time by
# `format_comparison_interpretation(tail_risk)`. Composer routes this
# into composed["page5_reconciliation"]["waterfall_interpretation"]
# (the WATERFALL_INTERPRETATION slot, that is the "tail couples cost
# and schedule" sentence the brief refers to).
WATERFALL_INTERPRETATION_TEMPLATE = (
    "Under the headline distribution, integrated P80 may exceed "
    "the naive sum of cost-only P80 and schedule-only P80. This is a "
    "counterintuitive but real result of joint sampling: when "
    "{tail_risk_id}'s tail couples cost and schedule simultaneously, "
    "the joint P80 captures correlated worst-case behaviour the "
    "marginal P80s miss. Under All Series, joint sampling produces a "
    "small diversification benefit because cost-driver and "
    "schedule-driver risks fire independently."
)


# ----------------------------------------------------------------------------
# Page 6 - Action implications
# ----------------------------------------------------------------------------

TREATMENT_ROI_ORIENTING = (
    "What is the ROI on risk treatment? The table below pairs each top "
    "driver with an illustrative treatment and the contingency "
    "reduction that would follow. Treatment effects are scenario "
    "estimates for prioritisation purposes; actual treatment "
    "effectiveness depends on project-specific factors."
)

TREATMENT_ROI_INTERPRETATION = (
    "Treatment effort directed at the top drivers reduces contingency "
    "more than effort spread across the long tail. The ranking gives "
    "the project team a defensible prioritisation for treatment plans "
    "and a quantified sense of the contingency at stake against each "
    "treatment decision."
)


# ----------------------------------------------------------------------------
# Page 7 - Methodology and caveats
# ----------------------------------------------------------------------------

#: Beta-17 Item 2, Distribution-shape explainer. Rendered as a paragraph
#: + bullet list at the end of the §7 Methodology summary subsection.
#: Restores the V5-era April 13 §3.3 shape-and-rationale framing the trim
#: compressed; current trim does not name the available shapes, so a
#: methodology reviewer querying the distribution choice has no source.
#: Static text, composer passes the intro and bullets straight to
#: word_generator.
DISTRIBUTION_SHAPE_EXPLAINER_INTRO = (
    "Distribution choice per risk reflects the shape of the underlying "
    "uncertainty:"
)

DISTRIBUTION_SHAPE_EXPLAINER_BULLETS: list[str] = [
    "PERT (default), three-point Optimistic / Most Likely / Pessimistic "
    "where the Most Likely value carries more weight than the extremes; "
    "the standard for contingency analysis.",
    "Triangular, three-point with no central-tendency weighting; used "
    "where the Most Likely value is genuinely uncertain.",
    "Lognormal, right-skewed continuous; used for cost categories with "
    "fat-tail exposure (e.g. commodity price spikes).",
    "Binary, fires fully or not at all; used for irreducible "
    "step-change events.",
]


#: Beta-17 Item 4, RBS Level 1 cost category breakdown orienting note.
#: Template substituted with the metric name ("Mean" / "P80") at format
#: time. Rendered as a two-sentence note above the cost RBS L1 table.
RBS_L1_COST_ORIENTING_TEMPLATE = (
    "Cost contingency concentrates by Risk Breakdown Structure (RBS) "
    "category as well as by individual risk. The table below shows "
    "{metric_name} contribution aggregated by RBS Level 1, useful for "
    "assigning treatment-plan ownership and for stakeholder discussions "
    "about which discipline carries the largest contingency."
)

#: Beta-17 Item 4, RBS Level 1 schedule category breakdown orienting
#: note. Two-sentence static prose (always probability-weighted mean days
#: per the schedule tornado convention).
RBS_L1_SCHEDULE_ORIENTING = (
    "Schedule slip concentrates by Risk Breakdown Structure (RBS) "
    "category as well as by individual risk. The table below shows "
    "probability-weighted mean schedule contribution (working days) "
    "aggregated by RBS Level 1, useful for assigning treatment-plan "
    "ownership and for stakeholder discussions about which discipline "
    "carries the largest schedule exposure."
)


#: Beta-17 Item 5, orienting prose above the CG drivers table.
#: Two paragraphs: (1) why CGs exist (joint firing of related risks);
#: (2) what the table shows and how it fits with the other two legs of
#: the cost MC's correlation structure (within-CG joint sampling via
#: Cholesky-decomposed correlated uniforms; shared severity uniform for
#: joint cost-and-schedule on dual-coded risks).
CG_DRIVERS_ORIENTING_PARAGRAPHS: list[str] = [
    (
        "The cost Monte Carlo engine groups risks by their underlying "
        "driver, common conditions that increase the joint probability "
        "of multiple risks firing together. A tight construction market "
        "that drives commodity prices up simultaneously raises the "
        "probability of multiple downstream risks; modelling those as "
        "independent would understate the joint tail exposure at exactly "
        "the contingency-relevant probability levels. Risks within a "
        "Correlation Group fire together more often than chance per the "
        "coefficient shown; risks across groups fire independently."
    ),
    (
        "The table below maps each active Correlation Group to its "
        "driver description, the member risks, and the joint-firing "
        "coefficient. Together with the per-risk Probability and "
        "three-point distributions in the register, the CG mapping is "
        "the third leg of the cost MC's correlation structure, the "
        "other two being within-CG joint sampling (Cholesky-decomposed "
        "correlated uniforms) and the shared severity uniform on the "
        "dual-coded risks for joint cost-and-schedule sampling."
    ),
]


STANDARDS_REFERENCES = (
    "The methodology aligns with the following standards and "
    "recommended practices: AACE RP 44R-08 Risk Analysis and "
    "Contingency Determination Using Range Estimating; AACE RP 65R-11 "
    "Integrated Cost and Schedule Risk Analysis Using Risk Drivers and "
    "Monte Carlo Simulation of a CPM Model; AACE RP 57R-09 Integrated "
    "Cost and Schedule Risk Analysis Using Monte Carlo Simulation of a "
    "CPM Model (cited as future scope for full CPM-based replay); "
    "AACE RP 113R-21 Integrated Cost and Schedule Risk Analysis - "
    "Sampling and Computational Aspects; PMI PMBOK 7th edition (Project "
    "Risk Management); ISO 31000:2018 (Risk management guidelines)."
)

# Beta-15 Item 2: convergence diagnostic caveat. Names the distinction
# between Monte-Carlo simulation error (which the chart measures) and
# model uncertainty in inputs / methodology (which it does not).
CONVERGENCE_CAVEAT = (
    "Monte Carlo simulation produces a sample, not the truth. The "
    "convergence diagnostic above shows how the headline figure "
    "stabilises as iteration count grows; a tight 95% bootstrap "
    "confidence band at the iteration count this run used indicates the simulation has "
    "run enough iterations for the headline to be reliable to within "
    "the band's width. The diagnostic measures Monte Carlo error only, "
    "it does not measure model uncertainty in the inputs (probability "
    "estimates, three-point distributions, Mode classifications) or in "
    "the methodology itself."
)

DP_REVIEW_CAVEAT = (
    "DP Review classification caveat. The DP Review state classifies "
    "{n_parallel_dp} of {n_total_dp} schedule-impacting risks as Parallel. "
    "Where Parallel risks dominate, this is a methodologically conservative "
    "starting point: it gives no schedule contingency credit to risks where "
    "the project may have float available to absorb impact. Where Parallel "
    "risks are few or absent, the DP Review state is closer to the upper "
    "bound and the conservatism claim weakens. Whether the current "
    "conservatism is realistic or excessive is a question for PM review - "
    "and that review is the principal outstanding action on this analysis. "
    "Dummy Realistic is the indicative working classification pending PM "
    "review; it applies Series and Hybrid classifications to dual-coded "
    "risks that are likely on or near the longest path. All Series is the "
    "methodological extreme. The headline range spans these three plausible "
    "states deliberately, so the reader can see the consequence of "
    "classification uncertainty rather than being given a single number "
    "that hides it. PM review of the Mode classifications is the "
    "highest-value next step; it narrows the range without changing the "
    "methodology."
)

#: Beta-17 Item 1, the Layer 1 (systemic cost) caveat, reworded by RIDGELINE-01 to what D-21
#: ruled. This deliverable presents the event-risk contingency (Layer 2) and never samples
#: Layer 1: its cost arm passes no buckets and no ``layer1_config``. Base plus contingency is a
#: product output of the Tier 1 owner view, and only where the register sets
#: ``Set_Layer1_Enabled`` (default FALSE). Kept in the limitations list so a reader looking for
#: Layer 1 gets an explicit answer.
L1_SYSTEMIC_CAVEAT_BULLET = (
    "This deliverable presents the event-risk contingency (Layer 2) on an "
    "input base estimate. Systemic uncertainty on that base (Layer 1) is "
    "outside its view: where a register enables Layer 1, the Tier 1 owner "
    "view samples it and reports the distribution of base plus contingency "
    "as a product output."
)

LIMITATIONS_CURRENT = [
    "Per-party views are deferred to the next stage. The current deliverable "
    "presents the whole-project view only.",
    "Criticality assessment uses the conservative starting-point "
    "classification informed by current schedule structure",
    # PRESENT-01, found by the numerics panel: this said full CPM replay was reserved for a
    # future stage, the same claim the Director corrected in disclaimer paragraph 4 on
    # 18/09/2026. It renders in the limitations list of the document that states the opposite
    # three paragraphs earlier. Corrected to the signed wording's substance.
    "Per-activity attribution of the finish to individual risks is deferred. The replay "
    "reports the project finish and each activity's criticality; the per-risk driver ranking "
    "beside it is the additive comparator basis, not the replay.",
    "Sensitivity analysis on individual risk probabilities and "
    "impacts (one-at-a-time, top-driver) is deferred to the next "
    "stage.",
    L1_SYSTEMIC_CAVEAT_BULLET,
]

LIMITATIONS_CLOSING = (
    "None of these are limitations of the methodology; they are inputs "
    "not yet available or capabilities deferred to the next stage. "
    "When inputs land, the analysis extends without re-engineering."
)

REPRODUCIBILITY = (
    "To regenerate this deliverable: restore the listed register and "
    "strawman files to the versions specified in the audit trail, "
    "set SR9_SEED to the seed recorded in this run's provenance and "
    "execute RUN_FINAL.bat. Outputs reproduce within MC noise "
    "tolerance. This deliverable reflects the input "
    "data as recorded in the audit trail. Inputs evolve as the "
    "project progresses; re-running the analysis against current "
    "inputs produces an updated deliverable."
)


# ----------------------------------------------------------------------------
# SR9 v3.6.1-03 (C1) - Cost MC drilldown noise interpretation
# ----------------------------------------------------------------------------
# Rendered beneath the Cost percentile table in the Cost MC drilldown
# section of the notebook. Static one-sentence note explaining why the
# standalone Cost MC P80 may differ slightly from the executive summary
# integrated figure - sampling noise within the marginal calibration
# tolerance.

COST_MC_DRILLDOWN_NOISE_NOTE = (
    "P80 cost values may differ slightly between the executive summary "
    "integrated figure and the standalone drilldown figure (~0.4% in "
    "this run). This is Monte Carlo sampling noise; the formal marginal "
    "calibration test in the integrated drilldown reports the precise "
    "gap and confirms it is within tolerance."
)


# ----------------------------------------------------------------------------
# SR9 v3.6.1-03 (C2) - Page 1 component breakdown mean-diversification note
# ----------------------------------------------------------------------------
# Rendered beneath the Page 1 component breakdown table. Static
# one-sentence note explaining why mean diversification is structurally
# near-zero while P80 diversification is meaningful.

PAGE1_COMPONENT_BREAKDOWN_DIVERSIFICATION_NOTE = (
    "Diversification effect is structurally near-zero at the mean (joint "
    "MC and naive-sum agree at the expectation by construction) and "
    "meaningful at P80 (the joint percentile captures cross-component "
    "tail behaviour). The difference between the Mean and P80 columns "
    "of this row is the value of the integrated MC over a naive sum at "
    "the contingency level."
)


# ----------------------------------------------------------------------------
# Single-iteration walkthrough template
# ----------------------------------------------------------------------------

SINGLE_ITERATION_INTRO = (
    "What does one Monte Carlo iteration actually compute? The "
    "walkthrough below traces a single iteration from the simulation "
    "in concrete terms. Read it as one of the simulated futures "
    "the analysis explored; the distribution charts above are the "
    "ensemble of all such futures. "
    "Some risks listed in this iteration may sit outside the Page 3 "
    "top-cost-driver tornado - the walkthrough captures every firing "
    "risk in the simulated iteration regardless of overall ranking. "
    "Iteration-specific firings reflect the random draw, not the "
    "headline driver hierarchy."
)


# ----------------------------------------------------------------------------
# Audience-neutral deliverable text.
#
# SR9 v3.2 introduced a second copy of each of these - a "_PROD" twin - because the report then
# had two audiences. PRESENT-01 (D-4) retired the first: the deliverable refuses any mode but
# prod, so a dev text could not reach a reader, and the composer recovered prod numbers by
# regexing them back out of the dev sentence it had just written. There is one text per key now.
#
# These constants are NOT rendered (the composer drops the corresponding composed[...] key and
# word_generator's `if x:` guards skip the block); they belong to the retired dev report and
# are kept only until the keys stop being built:
#   - MODE_CAVEAT_HEADLINE
#   - READING_CONVENTION (and READING_CONVENTION_TITLE)
#   - MEAN_COST_IDENTICAL_NOTE
#   - COST_DRIVERS_MODE_INDEPENDENCE_NOTE
#   - CRITICALITY_REFRAME
#   - MODE_SENSITIVITY_ORIENTING / _INTERPRETATION
#   - WATERFALL_ORIENTING / _INTERPRETATION (entire Page 5 dropped)
#   - DP_REVIEW_CAVEAT (Page 7 sub-block dropped)
# ----------------------------------------------------------------------------

# STAGE3HEADLINE-01 re-review: "reconciles with EMV" is true of the additive, Mode-scaled
# per-risk sum (Stage 2.5) - it is not a claim the Stage 3 CPM-replay mean supports, since
# nothing in the CPM kernel is constructed to equal a probability-weighted per-risk sum.
SCHEDULE_DAYS_CONTEXT_STAGE3 = (
    "Schedule slip in days: {p80_days:.1f} days at P80 "
    "(schedule contingency at 80% confidence, matching cost contingency "
    "convention per AACE RP 41R-08 / 65R-11); {mean_days:.1f} days mean "
    "(expected slip on average, from the Stage 3 CPM-replay distribution)."
)

# Generic prod fallbacks (project copy preferred from the binding).
# (Was R017_DOMINANCE_TEMPLATE_PROD / R017_DOMINANCE_FALLBACK_PROD.)
# STAGE3HEADLINE-01 re-review: the CPM mean is not decomposable per risk, so a
# dominance share computed from per_risk_schedule_array (the additive,
# Mode-scaled comparator basis) must not be captioned as a share "of the mean
# schedule slip" when Stage 3 leads. These variants name the basis instead.
DOMINANT_RISK_TEMPLATE_STAGE3 = (
    "A single risk - {top_risk_id} ({top_risk_short_title}) - "
    "accounts for approximately {top_risk_pct:.0%} of the summed "
    "additive per-risk schedule draws (comparator basis, not the CPM "
    "mean). Resolution of {top_risk_id} is the highest-value "
    "risk-treatment action."
)

DOMINANT_RISK_FALLBACK_STAGE3 = (
    "The top three schedule risks account for approximately "
    "{top3_pct:.0%} of the summed additive per-risk schedule draws "
    "(comparator basis, not the CPM mean). Resolution of these risks "
    "is the highest-value risk-treatment action."
)

def resolve_dominant_risk_template(*, fallback: bool, stage3: bool = False) -> str:
    """Return the dominant-risk dominance template for the active project.

    Reads the active project binding's ``NARRATIVE_TEMPLATES`` first (key
    ``dominant_risk`` / ``dominant_risk_fallback``, each suffixed ``_prod``), and falls back to
    the generic engine copy in this module when the binding supplies no override. Placeholders
    are identical across binding and fallback, so the caller's ``.format(...)`` kwargs are
    unchanged.

    ``stage3=True`` (the top driver's share is Stage 3's additive comparator basis, not a
    CPM-decomposable mean) selects the STAGE3 variants above directly, bypassing the binding
    lookup: no binding carries a Stage 3 override today, and the STAGE3 wording is
    basis-truthful regardless of project.

    PRESENT-01 (D-4): the ``mode`` argument is gone. It chose between a dev text and a prod one,
    and the deliverable refuses any mode but prod - so the dev branch could not reach a reader.
    """
    if stage3:
        return DOMINANT_RISK_FALLBACK_STAGE3 if fallback else DOMINANT_RISK_TEMPLATE_STAGE3

    from src.sra.cpm.bindings import get_active_binding

    base_key = "dominant_risk_fallback" if fallback else "dominant_risk"
    text = get_active_binding().narrative(base_key + "_prod")
    if text:
        return text
    return DOMINANT_RISK_FALLBACK if fallback else DOMINANT_RISK_TEMPLATE

# SR17 §5.3, Gating-collision methodology note.
#
# Under SR16 (default discrete-event additive injection + auto-pick gating
# activity), the five-of-eight collision is a feature of the current
# pattern catalogue, not a bug: P01 / P03 / P07 share prefix_list rules
# (see running memory note stage3_pattern_duplication.md). The auto-pick
# rule selects the latest-finish activity in each risk's binding cohort;
# for the construction-area cohort that activity is 20.C.95.EI.466.
#
# The risk-ID list was hardcoded against one strawman's five over-binding risks. When the
# strawman changes or the pattern catalogue gains differentiated rules, this note must be
# revisited.
#
# Stage 4 F-33, extended 08/09/2026 by the stage 5a review: this note is that project's, and it
# was rendered into the Kestrel deliverable's page 4. It now lives verbatim in the reference
# binding's NARRATIVE_TEMPLATES["stage3_gating_collision_note"]; a project without the key gets
# an empty note, which the renderers already treat as "no note". ``GATING_COLLISION_NOTE_STAGE3``
# resolves per access (``__getattr__``).
def resolve_gating_collision_note() -> str:
    """The §5.3 gating-collision note for the active project, or '' when it has none."""
    from src.sra.cpm.bindings import get_active_binding

    return get_active_binding().narrative("stage3_gating_collision_note")

# ----------------------------------------------------------------------------
# SR9 v3.5 - Mean as supplementary metric in PROD summary tables.
#
# Two footnote constants rendered in BOTH PROD outputs (P80-headline and
# Mean-headline). MEAN_FOOTNOTE_TEXT explains the methodology integrity
# stance: P80 remains the AU GN3A v2.0 / AACE 18R-97 standard contingency
# level; Mean is shown alongside at client request and is a supplementary
# metric, not the methodology-standard recommendation. The
# DIVERSIFICATION_TAIL_FOOTNOTE_TEXT addresses an artefact of joint
# sampling visible on the Page 2 confidence curve at higher P-levels.
# ----------------------------------------------------------------------------

MEAN_FOOTNOTE_TEXT = (
    "Mean is the recommended headline for shared-buffer commercial "
    "structures (alliance, IPD, target outturn cost) where both parties "
    "expose to expected losses by construction. P80 remains the "
    "methodology-standard contingency level for fixed-budget or lump-"
    "sum approval contexts per AU Department of Infrastructure GN3A v2.0 "
    "and AACE RP 18R-97 / 41R-08 / 65R-11, and is retained alongside as "
    "a confidence-level reference. The dual-flavour deliverable design "
    "(Mean BETA / P80 BETA) supports selecting the appropriate headline "
    "for the commercial structure of each deal. Mean reflects the "
    "expected value across simulated outcomes and reconciles with EMV; "
    "P80 covers approximately four in five simulated outcomes."
)

DIVERSIFICATION_TAIL_FOOTNOTE_TEXT = (
    "The diversification effect is positive at lower confidence levels; "
    "the data in this run flips negative at P80 (the flip point varies "
    "with the joint cost-schedule correlation structure) once the joint "
    "cost-plus-schedule tail exceeds the sum of the independent marginal "
    "tails. This is methodologically correct behaviour reflecting the "
    "correlated firing of dual-coded risks under joint sampling: shared "
    "severity uniforms produce larger combined tail outcomes than "
    "independent marginals would predict. The integrated figure is the "
    "appropriate one for contingency sizing at any chosen confidence level."
)


# Production-mode limitations list. Drops:
#   - dev entry 1 (LD/IDC layer deferred - commercial-input language)
#   - dev entry 6 (PM review of Mode classifications pending)
# Rephrases dev entry 3 with PM-approved text (per SR9 v3.2 PM addendum
# Section 1.4; phrasing supplied verbatim by PM).
# ----------------------------------------------------------------------------
# Beta-12, Activity-level criticality narrative
# ----------------------------------------------------------------------------

#: Plain-English explainer that opens the activity-level criticality
#: section. Substituted at format time via
#: :func:`src.final.executive_summary.format_criticality_explainer` to
#: insert ``{n_iter}``. ~250 words. Beta-12 §3.3.
CRITICALITY_EXPLAINER_TEMPLATE = (
    "Activity-level criticality answers a different question to the "
    "risk-driver analysis above. The risk-driver tornado tells you "
    "which RISKS, when fired, add the most days to the project. "
    "Criticality tells you which ACTIVITIES, across simulated futures, "
    "sit on the path that controls the project finish date.\n\n"
    "The deterministic critical path comes from the planner's logic - "
    "the longest chain of dependent activities under their nominal "
    "durations. Risks then perturb durations. In any given simulated "
    "future, some activities may slip enough to flip the critical path "
    "onto a different chain. The Criticality Index (CI) measures how "
    "often each activity sits on the critical path across the "
    "{n_iter:,} simulated futures: CI = 100% means the activity is "
    "critical in every iteration; CI = 0% means it never is; CI = 50% "
    "means it flips in and out.\n\n"
    "The shape of the CI distribution across all activities is "
    "informative. A bimodal shape - most activities at either 0% or "
    "100%, few in between - means the deterministic critical path is "
    "stable: the project finish date is reliably governed by the same "
    "chain. A flat shape - many activities in the 20-80% middle band - "
    "means path crossover is real, the critical path moves between "
    "iterations, and contingency is doing more work than the "
    "deterministic schedule alone would suggest.\n\n"
    "Activities in the middle band (CI 20-80%) are the most useful "
    "ones to watch. They are not currently driving the deterministic "
    "finish date but they are plausible alternates - float management "
    "on this set is the highest-leverage schedule-treatment action "
    "after risk-driver treatment."
)

#: Beta-19b item 10: Mode-conditioned vs Mode-independent CI
#: differentiation paragraph. Appended to the explainer above at format
#: time. ``{n_min}`` and ``{n_max}`` populate from the live auto-mapper
#: binding counts so the project-specific "convergence under broad
#: bindings" reading updates if the auto-mapper ruleset narrows in a
#: future revision.
CI_EXPLAINER_MODE_DIFFERENTIATION = (
    "\n\nThe deliverable produces two flavours of Criticality Index. "
    "**Mode-conditioned CI** runs the simulation with each risk's "
    "declared Mode multiplier (Series 1.0 / Hybrid 0.5 / Parallel 0.0) "
    "applied to its duration impact - the CI then reflects \"where the "
    "critical path goes given the project's chosen Mode tuning\". "
    "**Mode-independent CI** (AACE 65R-11 §5.4) runs every risk at "
    "multiplier 1.0 regardless of declared Mode - the CI then reflects "
    "\"where the critical path goes if every risk's full impact were "
    "felt\". The two readings agree on activities the Mode tuning is "
    "methodologically aligned with and diverge on activities the Mode "
    "tuning is either suppressing (Mode-conditioned under-reports "
    "criticality) or amplifying (Mode-conditioned over-reports). Charts "
    "and tables in this section show both views side by side where the "
    "comparison adds information; in the current run the two readings "
    "converge on most activities because the project's strawman "
    "declares every Time=Yes risk Hybrid and the auto-mapper binds "
    "each to a broad activity set ({n_min}-{n_max} activities per risk) "
    "which dilutes the per-activity Mode-tuning effect below the "
    "divergence-band threshold. Workshop validation of the risk-driver-"
    "to-activity mappings - narrower per-risk activity sets reflecting "
    "genuinely affected scope - is the path to a more discriminating "
    "Mode-independent reading."
)

#: Distribution-shape interpretation sentence, selected by the shape
#: indicator returned from
#: :func:`src.final.composer.compute_ci_distribution_summary`. Substituted
#: at format time with band percentages. Beta-12 §3.3.
CRITICALITY_DISTRIBUTION_INTERPRETATION_TEMPLATES = {
    "bimodal": (
        "Of {n_total:,} schedule activities, {pct_always:.0%} are "
        "critical in 90%+ of iterations and {pct_never:.0%} are never "
        "critical. Only {pct_middle:.0%} sit in the middle bands "
        "(10-90%). This is a stable critical path: the deterministic "
        "schedule reliably predicts which activities control the "
        "finish date, and the contingency is sized primarily for "
        "duration uncertainty on those always-critical activities."
    ),
    "stable_cp": (
        "Of {n_total:,} schedule activities, {pct_always:.0%} are "
        "critical in 90%+ of iterations. The critical path shifts "
        "occasionally ({pct_middle:.0%} of activities sit in the "
        "10-90% middle bands) but the core path is recognisable "
        "across most simulated futures. Contingency is sized for "
        "duration uncertainty on the core path plus a margin for "
        "occasional path crossover."
    ),
    "shifty": (
        "Of {n_total:,} schedule activities, only {pct_always:.0%} "
        "are critical in 90%+ of iterations; {pct_middle:.0%} sit in "
        "the 10-90% middle bands. The critical path moves materially "
        "between iterations - path crossover is real. The contingency "
        "is doing more work than the deterministic schedule alone "
        "suggests, because no single chain reliably governs the "
        "finish date."
    ),
    "uniform_low": (
        "Of {n_total:,} schedule activities, only {pct_always:.0%} "
        "ever reach 90%+ CI; the bulk ({pct_never:.0%}) sit at "
        "below-10% criticality. This pattern typically indicates the "
        "schedule has substantial slack relative to the modelled risk "
        "drivers - the contingency may be smaller than the headline "
        "figure if the model is missing risk drivers, or "
        "proportionate if the schedule is genuinely well-buffered. "
        "Where the auto-mapper zero-expansion notice (top of Stage 3 "
        "Beta section) lists unmapped risk drivers in the current run, "
        "this caveat is materially relevant: criticality rankings "
        "derived from drivers without activity bindings will appear "
        "muted."
    ),
}

#: Interpretation paragraph rendered below the near-critical activities
#: table. Substituted at format time with the table's actual row count
#: and the top activity's CI. Beta-12 §3.3.
CRITICALITY_NEAR_CRITICAL_INTERPRETATION_TEMPLATE = (
    "The {n_near_critical} activities in the table above are the "
    "near-critical set - activities that flip in and out of the "
    "critical path across simulated futures. They are not currently "
    "driving the deterministic finish date, but they are plausible "
    "alternates: float management here is the highest-leverage "
    "schedule-treatment action after risk-driver treatment. "
    "Specifically, adding even small amounts of float to the top "
    "{n_top} activities (CI >= {top_ci:.0%}) reduces the probability "
    "of path crossover, which in turn narrows the schedule "
    "contingency."
)

#: Fallback near-critical interpretation when the picker returns zero
#: rows (no activity sits in the [0.20, 0.80] band - the schedule is
#: either fully bimodal or all-low-CI). Beta-12 §4.
CRITICALITY_NEAR_CRITICAL_INTERPRETATION_EMPTY = (
    "No activities sit in the near-critical band (CI between 20% and "
    "80%). Either the deterministic critical path is fully stable "
    "(every activity is reliably critical or reliably non-critical) "
    "or the schedule has substantial slack relative to the modelled "
    "risk drivers. In either case there is no actionable "
    "float-management cut at the activity level under the current "
    "inputs."
)

#: Interpretation paragraph above the risk-to-activity bridge table.
#: Static - the table itself carries the per-(risk, activity) detail.
#: Beta-12 §3.3.
CRITICALITY_RISK_BRIDGE_INTERPRETATION = (
    "The table below connects the top-3 schedule risk drivers (Page 4 "
    "above) to the specific activities each one's modelling expands "
    "to. When one of these risks fires in a simulated future, the "
    "activity duration on the listed activity expands accordingly. "
    "Activities on this list with high CI (90%+) are the ones where "
    "treatment of the upstream risk has the largest "
    "contingency-narrowing effect; activities with mid CI (20-80%) "
    "are the ones where treatment can flip the critical path onto a "
    "more predictable chain."
)

#: Closing caveat rendered at the end of the activity-level criticality
#: section. User-direction-driven editorial frame: positions the model
#: as deterministic-given-inputs and the user as the controller of
#: input quality. Beta-12 §3.3.
CRITICALITY_INPUT_DEPENDENCIES_CAVEAT = (
    "**Inputs that drive activity-level criticality accuracy.** This "
    "analysis uses the inputs as provided and the rankings reflect "
    "those inputs deterministically. Three input categories most "
    "affect the rankings above:\n\n"
    "1. **Risk-driver-to-activity assignments.** Each risk in the "
    "register maps to one or more schedule activities. The current "
    "mapping is pattern-based (rules from the strawman expanded "
    "against the schedule network); replacing this with explicit "
    "per-(risk, activity) assignments - typically the output of a "
    "workshop with the planner and risk register owners - will "
    "materially affect which activities show high CI. Activities not "
    "currently mapped to any risk driver appear in the analysis with "
    "their planner-derived float as the only source of variability.\n\n"
    "2. **Schedule logic in the .xer.** The CPM kernel uses the "
    "precedence relations (FS / SS / FF / SF) and lags exactly as "
    "exported from Primavera P6. Logic errors, missing dependencies, "
    "or unrealistic lags in the source schedule propagate directly "
    "into the criticality rankings.\n\n"
    "3. **Calendar handling.** The current model uses a single "
    "project-default working calendar. Activities that genuinely run "
    "on different calendars (e.g., commissioning shifts, "
    "weather-restricted activities, weekend/holiday-exempt work) have "
    "their durations and floats computed at the project default; "
    "rankings shift if per-activity calendars differ materially from "
    "the project default.\n\n"
    "Items 1 and 2 are the responsibility of the schedule owner and "
    "risk register owner; item 3 is a current model simplification "
    "flagged for upgrade. The intended workflow is to treat the "
    "rankings as directional, re-run against updated inputs as they "
    "evolve, and refine the criticality narrative as input quality "
    "improves."
)


# ----------------------------------------------------------------------------
# SR-S3-Beta-18 §1, Auto-mapper interpretation paragraph
# ----------------------------------------------------------------------------
# Sits immediately before the Stage 3 Beta auto-mapper audit table. Names
# the over-binding (<n>-<m> activities per risk for the affected drivers)
# as the cause of the inflated Stage 3 Beta P80 vs Stage 2.5, and names
# workshop validation as the path to a credible Stage 3 figure.
#
# Placeholders filled at runtime by
# `format_auto_mapper_audit_interpretation` in executive_summary.py;
# the formatter derives all numeric values from the live audit table +
# composed["stage3_beta_p80_schedule_days"] / ["stage25_p80_schedule_days"]
#, no hardcoded literals.
AUTO_MAPPER_AUDIT_INTERPRETATION_TEMPLATE = (
    "**Auto-mapper binding breadth (Stage 3 Beta methodology note).** "
    "The auto-mapper expands each risk-driver pattern across every "
    "activity in the replayed network matching the pattern's prefix rules. "
    "{n_over_bound} of the {n_total} Time=Yes risks ({over_bound_ids}) "
    "are currently bound to between {min_count} and {max_count} "
    "activities, a substantial fraction of the ~{schedule_size}-"
    "activity network. Under additive PERT injection on "
    "the CPM replay engine, broad bindings compound: each risk "
    "effectively perturbs most of the network "
    "simultaneously, producing the Stage 3 Beta P80 of "
    "{stage3_p80_days:.1f} days against Stage 2.5's {stage25_p80_days:.1f} "
    "days. The Stage 3 Beta figure is therefore an auto-mapper artefact "
    "arising from the breadth of the current pattern-based binding, not "
    "a real schedule-risk signal. Workshop validation of the risk-"
    "driver-to-activity mappings will narrow each risk's activity set "
    "to its genuinely affected scope; the path-crossover comparison "
    "becomes a meaningful methodological signal only after that step. "
    "The per-risk activity counts behind these figures are exposed in "
    "the risk-to-CP linkage table later in this section."
)


#: SR14b additive, Stage 3 standalone variant of the auto-mapper
#: interpretation paragraph. The Stage 2.5 version names the Stage 3
#: Beta P80 against the Stage 2.5 P80 ("...against Stage 2.5's X days")
#: because Stage 2.5 is the headline of the Stage 2.5 deliverable. The
#: Stage 3 standalone reads as a deliverable in its own right
#: (Director D3 sign-off 2026-05-15; AC5 zero-Stage-2.5-references
#: audit), so the comparison clause is stripped and the Stage 3 figure
#: stands on its own. The ``{stage25_p80_days}`` placeholder is still
#: accepted by the Stage 3 formatter to keep the kwargs surface aligned
#: with the Stage 2.5 path, but is not interpolated into the rendered
#: text. Brief §4.1 amendment (Director-signed-off): commentary_text.py
#: stays unchanged on the Stage 2.5 path; additive Stage 3-specific
#: constants with ``_STAGE3`` suffix are permitted.
AUTO_MAPPER_AUDIT_INTERPRETATION_TEMPLATE_STAGE3 = (
    "**Auto-mapper binding breadth (Stage 3 Beta methodology note).** "
    "The auto-mapper expands each risk-driver pattern across every "
    "activity in the replayed network matching the pattern's prefix rules. "
    "{n_over_bound} of the {n_total} Time=Yes risks ({over_bound_ids}) "
    "are currently bound to between {min_count} and {max_count} "
    "activities, a substantial fraction of the ~{schedule_size}-"
    "activity network. Under additive PERT injection on "
    "the CPM replay engine, broad bindings compound: each risk "
    "effectively perturbs most of the network "
    "simultaneously, producing the Stage 3 Beta P80 of "
    "{stage3_p80_days:.1f} days. The Stage 3 Beta figure is therefore "
    "an auto-mapper artefact arising from the breadth of the current "
    "pattern-based binding, not a real schedule-risk signal. Workshop "
    "validation of the risk-driver-to-activity mappings will narrow "
    "each risk's activity set to its genuinely affected scope; only "
    "after that step does the figure become a meaningful methodological "
    "signal. The per-risk activity counts behind this figure are "
    "exposed in the risk-to-CP linkage table later in this section."
)

# Threshold: an "over-bound" risk is one whose auto-mapper expansion
# touches at least this fraction of the replayed activity network. PRESENT-01 (D-5): the
# denominator is now the run's own activity count, so the separation this floor was
# calibrated against no longer describes it - OVERBIND-01.
# Empirical
# 13 May audit: five of the eight risks each bound to
# <n>-<m> of ~2,025 activities (>23%); the remaining three risks bind
# to ≤94 activities (<5%). The 0.15 floor cleanly separates the two
# populations and is conservative enough to remain stable if a future
# strawman edit shifts a borderline risk.
AUTO_MAPPER_OVER_BIND_FRACTION_FLOOR: float = 0.15


# ----------------------------------------------------------------------------
# SR15, Stage 3 Mode-multiplier retirement (additive _STAGE3 constants)
# ----------------------------------------------------------------------------
# Decision 3 (Director-locked 2026-05-16): new H2 subsection inside the
# "Methodology and caveats" H1, explaining why the Stage 3 full-CPM path
# does not apply Mode multipliers and what that implies for the headline
# figure under current bindings. Three paragraphs; rendered verbatim by
# word_generator.py when ``composed["page7_methodology"]
# ["mode_multipliers_full_cpm_paragraphs"]`` is set (Stage 3 standalone
# composer sets this; Stage 2.5 composer does not). Brief §4.2 amendment
# pattern: additive ``_STAGE3`` constants only; Stage 2.5 commentary
# constants untouched.
#
# IMPORTANT: this text is Director-locked. Do not paraphrase, abbreviate,
# or wordsmith. Verbatim audit lives in
# ``tests/test_sr15_stage3_methodology_section.py``.
#
# Stage 4 F-33 (08/09/2026): paragraphs 2 and 3 of the locked text are the REFERENCE PROJECT's
# (its SR16 collapse figures, its five-of-eight gating collision on 20.C.95.EI.466, Director
# D8.1), and as a module constant they were rendered into every project's standalone report - a
# road project's Stage 3 report said "<pre_sr16_p80>-day P80" and named another
# project's risk. The three
# paragraphs now live byte-identical in that binding's
# ``NARRATIVE_TEMPLATES["stage3_methodology_paragraphs"]`` and are resolved per project by
# :func:`resolve_mode_multipliers_full_cpm_paragraphs`; the module attribute
# ``MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3`` resolves the same way (``__getattr__``). This
# generic fallback keeps paragraph 1 verbatim and states the implication without a figure.
_GENERIC_MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3: list[str] = [
    (
        "**Mode multipliers and the full-CPM approach.** This "
        "deliverable uses the full Critical Path Method (CPM) replay "
        "against the .xer schedule network without applying Mode "
        "multipliers (Series 1.0 / Hybrid 0.5 / Parallel 0.0). The CPM "
        "kernel walks the network each iteration, applies per-iteration "
        "risk impacts at the bound activities, and recomputes the "
        "critical path; float consumption is handled by the kernel "
        "mechanics. Mode multipliers were retained in the Stage 2.5 "
        "deliverable as a practitioner-judgement layer where no CPM "
        "kernel was available; in Stage 3 that layer would double-count "
        "on the CPM mechanics and is not applied."
    ),
    (
        "**Implication for the headline figure.** With Mode multipliers "
        "retired, the per-risk activity scope (the binding of each risk "
        "to schedule activities) and the per-risk injection method "
        "become the dominant input controls. A discrete-event injection "
        "places each risk's delay on its single gating activity; an "
        "additive-days injection spreads it across every bound "
        "activity. Which method the register declares for each risk, "
        "and how many activities each risk binds to, is reported in the "
        "risk-to-CP linkage table later in this section; workshop "
        "validation of those bindings is the gate before the figure is "
        "used for commitment."
    ),
]

_STAGE3_PARAGRAPH_SEPARATOR = "\n\n"


def resolve_mode_multipliers_full_cpm_paragraphs() -> list[str]:
    """The Stage 3 D3 methodology paragraphs for the active project (binding-first).

    A binding supplies them as one string with paragraphs separated by a blank line; a
    binding without the key gets the generic pair above. Always a fresh list.
    """
    from src.sra.cpm.bindings import get_active_binding

    text = get_active_binding().narrative("stage3_methodology_paragraphs")
    if text:
        return [p.strip() for p in text.split(_STAGE3_PARAGRAPH_SEPARATOR) if p.strip()]
    return list(_GENERIC_MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3)


def __getattr__(name: str):
    """``commentary_text.MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3`` resolves per access
    against the active binding (PEP 562), for the reason ``stage3_beta_report.__getattr__``
    gives: a ``from`` import would snapshot one project's text."""
    if name == "MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3":
        return resolve_mode_multipliers_full_cpm_paragraphs()
    if name == "GATING_COLLISION_NOTE_STAGE3":
        return resolve_gating_collision_note()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

#: SR15, heading literal for the new methodology subsection. Rendered by
#: word_generator.py as an H2 inside the "Methodology and caveats" H1.
#: Title-cased and short so it sits cleanly between "Methodology summary"
#: and the standards-references / convergence / DP-review-caveat
#: subsections below.
MODE_MULTIPLIERS_FULL_CPM_HEADING_STAGE3: str = (
    "Mode multipliers and the full-CPM approach"
)

#: SR15, Decision 4 (Director-locked 2026-05-16): one-paragraph footnote
#: rendered immediately under the schedule drivers Table 6 (Page 4) in
#: the Stage 3 standalone docx, explaining that the Mode classification
#: column is retained for reader context but does not affect Stage 3
#: per-iteration impact magnitudes. Stage 2.5 docx is unaffected, Stage
#: 2.5 composer does not set the corresponding composed-dict key.
SCHEDULE_DRIVERS_MODE_COLUMN_FOOTNOTE_STAGE3: str = (
    "Mode classification (Series / Hybrid / Parallel) is shown for "
    "context. Under the Stage 3 full-CPM methodology (post-SR15), Mode "
    "does not affect the per-iteration impact magnitude, the CPM "
    "kernel handles float consumption directly. The Mode column "
    "reflects the strawman classification carried forward from Stage 2.5 "
    "for reporting consistency."
)


# ----------------------------------------------------------------------------
# SR-S3-Beta-18 §2, Action-implications placeholder banner
# ----------------------------------------------------------------------------
# Rendered immediately above the treatment ROI table. The table itself
# now shows "Workshop input required" in the treatment description and
# estimated-reduction columns (replacing the prior hardcoded ~30%
# placeholder). The banner makes the placeholder status visible to a
# skim-reader even before they reach the table.
ACTION_IMPLICATIONS_PLACEHOLDER_BANNER = (
    "**Illustrative only, treatment definitions and effectiveness "
    "factors require workshop input.** Rows are populated from the "
    "strawman Treatments sheet; remaining rows await workshop input. "
    "The methodology supports per-risk treatment descriptions and "
    "effectiveness estimates: populated rows render the workshop "
    "description and the computed reduction (driver value × supplied "
    "effectiveness %); rows without a workshop-supplied effectiveness "
    "value render 'Workshop input required' in the treatment-description "
    "and estimated-reduction columns."
)

ACTION_IMPLICATIONS_PLACEHOLDER_CELL = "Workshop input required"


# ----------------------------------------------------------------------------
# SR-S3-Beta-18 §5, Calendar caveat inline
# ----------------------------------------------------------------------------
# A short, single-sentence note rendered immediately under both the
# near-critical activities table and the risk-to-activity bridge table.
# The full caveat (under "Inputs that drive criticality accuracy") stays
# unchanged; this inline note surfaces the same warning at the two
# places a reader actually inspects activity-level CI numbers and
# decides whether to act on them.
CRITICALITY_CALENDAR_CAVEAT_INLINE = (
    "_Activity floats and CI values use the project-default working "
    "calendar; per-activity calendars (e.g., commissioning shifts, "
    "weather-restricted activities) are not currently modelled. See "
    "*Inputs that drive criticality accuracy* below for the full "
    "caveat._"
)


# ----------------------------------------------------------------------------
# SR-S3-Beta-19 §3, Criticality content split (scaffold)
# ----------------------------------------------------------------------------
#: Caption rendered in place of the criticality density Gantt chart in the
#: main-report shrunk criticality section. SR10.B replaces this with the
#: actual chart image when chart_output_dir is supplied (notebook runs);
#: the placeholder remains for tests / call sites that don't produce
#: chart PNGs.
CRITICALITY_CHART_2_PLACEHOLDER_CAPTION = (
    "_[Criticality density Gantt by phase, Chart 2; placeholder when "
    "chart_output_dir is not supplied to the composer.]_"
)

#: Caption rendered immediately beneath the embedded Chart 2 PNG. The
#: rendered chart shows Mode-independent CI (AACE 65R-11) by RBS Level 1
#: phase × month; the bottom-right inset shows the same view under
#: Mode-conditioned CI for methodology transparency (Decision 1).
CRITICALITY_CHART_2_RENDERED_CAPTION = (
    "_Chart 2, Criticality density Gantt by phase. Cell intensity = mean "
    "CI across activities present in that (phase, month) bin. Primary "
    "view: Mode-independent CI (AACE 65R-11). Bottom-right inset: "
    "Mode-conditioned CI for direct comparison._"
)

#: Captions for the sibling criticality note's placeholder image frames.
#: Each names the chart and its audience role; SR10.B fills the frames.
CRITICALITY_CHART_1_PLACEHOLDER_CAPTION = (
    "_[Top-30 sorted criticality bar chart, Chart 1; populated by "
    "SR10.B.]_"
)
CRITICALITY_CHART_3_PLACEHOLDER_CAPTION = (
    "_[Risk-to-CP linkage, Chart 3; populated by SR10.B.]_"
)
CRITICALITY_CHART_4_PLACEHOLDER_CAPTION = (
    "_[Float histogram with criticality overlay, Chart 4; populated by "
    "SR10.B.]_"
)

#: SR14b.1: caption for the Beta-12 CI distribution chart when it is
#: relocated into the Stage 3 standalone docx's Criticality detail
#: appendix as a distribution-shape complement to the main report's
#: Chart 2 (phase-bunching view). ``_STAGE3`` suffix per the SR14b §3
#: brief amendment for additive Stage 3-only commentary surfaces;
#: leaves all pre-existing Stage 2.5 commentary literals untouched.
CRITICALITY_CI_DISTRIBUTION_CAPTION_STAGE3 = (
    "_Banded view of the criticality index across all activities. Six "
    "bands report how many activities sit at each CI range, "
    "complementing the (phase, month) spatial view in Chart 2 of the "
    "main report. The two views together let the reader see both how "
    "the criticality mass is distributed in shape and where it bunches "
    "in time._"
)

#: Forward-reference line at the end of the main-report shrunk criticality
#: section. SR14b D5 reword: the sibling deliverable retires at SR14b and
#: the full activity-level criticality detail moves into the Stage 3
#: standalone report's appendix. Pre-SR14b text pointed at the
#: ``sra_criticality_note_PROD_*`` companion deliverable; the SR14b
#: reword is the single named exception to the SR14b brief §4.1
#: "commentary_text.py unchanged" rule (Director-signed-off as D5).
CRITICALITY_FORWARD_REFERENCE_TO_NOTE = (
    "Full criticality detail (Charts 1, 3, 4 + 10-row near-critical "
    "table + risk-to-activity bridge) ships in the Stage 3 standalone "
    "report's appendix."
)

#: Purpose-and-audience paragraph at the top of the sibling note.
CRITICALITY_NOTE_PURPOSE_AND_AUDIENCE = (
    "**Purpose.** This note carries the full activity-level criticality "
    "detail referenced by the main report. **Audience.** Project "
    "controls, schedule owner, and planner; the planner uses the "
    "criticality index and float distributions to focus float-management "
    "and treatment-targeting effort on the activities most likely to "
    "drive the finish-date risk."
)

#: Abbreviated audit-trail reference at the end of the sibling note.
CRITICALITY_NOTE_AUDIT_TRAIL_REFERENCE = (
    "_Audit trail: see `sra_final_report_PROD_*` for full register / "
    "strawman / P6 hashes, iteration count, and random seed. This note "
    "shares the same engine run._"
)
