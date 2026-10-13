"""SR9-scoped methodology disclaimer paragraphs.

Single-purpose module so future stages (SR10) can have their own
disclaimer modules without bloating defaults.py. Methodology language
is intentionally consistent across runs and is treated as a documented
constant. PM review changes flow into the strawman, not into this module.

Used in both HTML disclaimer block (notebook) and Word doc methodology
section (word_generator). Same function for both consumers.

Version-pin discipline: paragraphs use role-based language ("the project
risk register", "the strawman methodology workbook", "the Variables sheet").
Specific file paths and version numbers ONLY appear in the audit trail
appendix accessor (final_reporting.get_appendix_audit_trail_data).
"""

from __future__ import annotations

from typing import Any, Mapping


#: The paragraphs the page-7 methodology summary carries. Named, not sliced: the list's length
#: depends on the contract and on whether the run has a tail risk, so "the first four" stopped
#: meaning "the methodology statements" the moment either became conditional. Found by the
#: numerics panel at PRESENT-01's review.
METHODOLOGY_SUMMARY_OPENERS: tuple[str, ...] = (
    "Joint sampling mechanism",
    "Schedule classifications",
    "Tail-risk reporting convention",
    "Full-network CPM replay",
)


def methodology_summary(paragraphs: list[str]) -> list[str]:
    """The methodology statements from ``paragraphs``, in the order they appear."""
    return [
        para for para in paragraphs
        if para.startswith(METHODOLOGY_SUMMARY_OPENERS)
    ]


def get_paragraphs(
    *,
    dual_coded_count: int | None = None,
    tail_risk: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return the methodology disclaimer paragraphs as ordered list.

    Each paragraph is a constant agreed methodology statement. PRESENT-01 (P-3): three of them
    stated facts about one project - a risk count, a named risk with its probability and
    three-point distribution, and two parties' names. Each is now taken from the run or from the
    active project binding, and the tail-risk paragraph is omitted entirely when the run has no
    tail risk to report.

    Parameters
    ----------
    dual_coded_count : int, optional
        How many risks the run flagged as time-impacting. Omitted, paragraph 1 says "the risks"
        rather than claiming a number.
    tail_risk : mapping, optional
        The output of :func:`src.final.executive_summary.pick_tail_risk` for this run. ``None``
        drops paragraph 3, because there is then no tail risk to describe.

    Paragraphs:
      1.  Joint sampling mechanism explanation
      2.  Schedule classification source
      3.  Tail-risk reporting convention (omitted when the run has no tail risk)
      4.  Longest-path subset caveat
      5.  LD layer deferred
      6.  Multi-party views deferred
      7.  Day-rate basis (sourced from Risk Register Variables sheet)
      8.  TOC basis (sourced from Risk Register Variables sheet)
      9.  Strawman version date and provenance (role-based language)
      10. Engine version stamps and run date
    """
    from src.final import contract_terms
    from src.sra.cpm.bindings import get_active_binding

    parties = get_active_binding().party_labels
    dual_coded = (
        f"the {dual_coded_count} risks" if dual_coded_count is not None else "the risks"
    )
    paragraphs = [
        # 1. Joint sampling mechanism
        (
            "Joint sampling mechanism. The integrated Monte Carlo engine shares "
            "a single severity uniform per dual-coded risk per iteration, driving "
            "both the cost dispatch and the schedule PERT draw. This produces "
            f"correlated cost and schedule severities for {dual_coded} flagged "
            "as time-impacting in the project risk register. Cost-only risks use "
            "independent severity uniforms. The mechanism preserves marginal "
            "calibration with the standalone cost and schedule engines while "
            "enabling diversification benefit measurement at the joint percentile."
        ),
        # 2. Methodology source — prod variant drops PM-review/indicative framing.
        (
            "Schedule classifications. Series, Hybrid, and Parallel classifications "
            "for the dual-coded risks reflect the conservative starting-point "
            "informed by current schedule structure. Sensitivity of the headline "
            "to classification choice is bounded and documented in the appendices."
        ),
        # 3. The tail-risk convention - inserted below, because it is the run's risk.
        # 4. What the schedule analysis actually replays.
        # PRESENT-01: this said the analysis ran on a longest-path subset and that full CPM
        # replay was "reserved for future work". Full-network replay has been the production
        # headline since SR15/SR17, so the paragraph described a method the product retains only
        # as a historical comparator. Replacement signed off by the Director 18/09/2026.
        (
            "Full-network CPM replay. The schedule analysis replays the programme's full "
            "activity network on every iteration: each activity's duration is sampled, a "
            "forward and backward pass is run over the whole network, and the finish date is "
            "read from that pass. The critical path is therefore an output of each iteration "
            "rather than a subset fixed in advance, and an activity off the planned critical "
            "path contributes to finish-date slip whenever sampling puts it on the path. The "
            "deterministic critical path quoted in the appendices is the activity set with zero "
            "float under a single zero-risk pass; where chains tie on float, that set is a "
            "superset of any one longest path. Series, Hybrid and Parallel classifications are "
            "carried from the strawman and reported for context; under the full-network replay "
            "they do not multiply a risk's impact, because the network decides how a delay "
            "propagates."
        ),
        # 5. Deferred commercial layers - contract-shaped, inserted below when there are any.
        # 6. Multi-party views deferred - the parties are the binding's, not a literal.
        (
            "Multi-party views deferred. The current deliverable presents "
            f"the {parties.get('whole_project', 'whole-project').lower()} view only. "
            f"{parties.get('contractor', 'Contractor')}, "
            f"{parties.get('owner', 'Owner')}, and "
            f"{parties.get('shared', 'shared')} "
            "stakeholder views are deferred to a later stage pending confirmation "
            "of the risk-share parameters and counterparty allocation rules."
        ),
        # 7. Day-rate basis
        (
            "Day-rate basis. The day rate used to dollarise schedule slip is "
            "sourced from the Risk Register Variables sheet via the strawman "
            "methodology workbook. The same value is used by the standalone "
            "schedule engine, the integrated engine, and the executive summary "
            "so all reported dollar conversions are consistent."
        ),
        # 8. Target-cost basis - contract-shaped, inserted below when the contract has one.
        # 9. Strawman version date and provenance
        (
            "Strawman provenance. The strawman methodology workbook is the single "
            "source of truth for Mode classifications, day rate, commercial reference "
            "values, and run configuration. Its version date appears in the audit trail appendix. "
            "When the strawman is reissued, this deliverable re-runs against the "
            "amended state and supersedes the prior version."
        ),
        # 10. Engine version stamps and run date
        (
            "Engine versioning. The cost Monte Carlo engine, schedule MC engine, "
            "integrated cost+schedule engine, and final composition layer carry "
            "version stamps recorded in the audit trail appendix. The run date "
            "and seed are recorded so the deliverable is reproducible from the "
            "strawman snapshot it was generated against."
        ),
    ]
    # The contract-shaped paragraphs go where the docstring's numbering says, found by the
    # paragraph they follow rather than by index: the list's length depends on what this run and
    # this contract carry, so an index computed against the full list lands in the wrong place.
    # (Found by the numerics panel: insert(7, ...) on a seven-element list appended the
    # target-cost note after the engine-versioning paragraph.)
    for _key, _after in (
        ("deferred_commercial_layers_note", "Full-network CPM replay"),
        ("target_cost_basis_note", "Day-rate basis"),
    ):
        _note = contract_terms.term(_key)
        if _note is None:
            continue
        _at = next(
            (i + 1 for i, _p in enumerate(paragraphs) if _p.startswith(_after)),
            len(paragraphs),
        )
        paragraphs.insert(_at, _note)

    if tail_risk is not None:
        paragraphs.insert(2, (
            f"Tail-risk reporting convention. Risk {tail_risk['tail_risk_id']} fires in "
            f"{tail_risk['tail_risk_prob']:.1%} of iterations and contributes "
            f"{tail_risk['tail_risk_mean_when_fired']:.0f} days when it does. Under "
            "classifications where it is Parallel its schedule contribution is zero regardless "
            "of firing frequency; under classifications where it is Series its tail dominates "
            "the integrated P95 and P99. The deliverable reports it separately in the executive "
            "summary so readers can see the tail behaviour rather than have it averaged into "
            "the headline numbers."
        ))
    return paragraphs
