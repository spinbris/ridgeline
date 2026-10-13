"""Workshop questions generator (Brief Section 4.7 + Section 5.6).

Builds the 20-30 question list for the Workshop_Questions sheet and the
standalone workshop docx. Questions are categorised by owner (Estimator /
PM / Commercial / Director / Other) and by workshop priority (Must /
Should / Nice).

A small set of questions are parameterised from the mapping outputs so
that the workshop list is live rather than static - e.g. "we mapped N
risks to WBS branch X; is that the right scope?" with N from the actual
build.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


OWNER_ESTIMATOR = "Estimator"
OWNER_PM = "PM"
OWNER_COMMERCIAL = "Commercial"
OWNER_DIRECTOR = "Director"
OWNER_OTHER = "Other"

PRIORITY_MUST = "Must"
PRIORITY_SHOULD = "Should"
PRIORITY_NICE = "Nice to have"

ANSWER_NUMBER = "Number"
ANSWER_YES_NO = "Yes/No"
ANSWER_TEXT = "Text"
ANSWER_SELECTION = "Selection"


@dataclass(frozen=True)
class WorkshopQuestion:
    number: int
    category: str
    question: str
    owner: str
    answer_type: str
    impact_if_unresolved: str
    priority: str


def _base_questions() -> list[tuple[str, str, str, str, str, str]]:
    """Returns (category, question, owner, answer_type, impact, priority)."""
    return [
        # --- Mapping validation ---
        (
            "Mapping",
            "Are the WBS prefix linkages proposed for sitewide risks "
            "(weather, labour productivity, force majeure) appropriate, "
            "or should they be tightened to sub-scopes?",
            OWNER_PM,
            ANSWER_TEXT,
            "Broad linkages inflate Mode=Series counts and may overstate schedule exposure",
            PRIORITY_MUST,
        ),
        (
            "Mapping",
            "For risks flagged [UNMAPPED] or [NEEDS_REVIEW], can you "
            "propose an Activity ID or WBS prefix, or should they remain "
            "unlinked (cost-only) for the strawman?",
            OWNER_PM,
            ANSWER_TEXT,
            "Unmapped risks carry zero schedule contribution; may under-count impact",
            PRIORITY_MUST,
        ),
        (
            "Mapping",
            "Which Activity IDs in the 20.COM.*.EI.310 hot-commissioning "
            "chain are the strongest candidates for transformer / main-"
            "equipment delay risks?",
            OWNER_PM,
            ANSWER_TEXT,
            "Mode calibration for long-lead equipment risks depends on this",
            PRIORITY_SHOULD,
        ),
        (
            "Mapping",
            "Do any risks in the register actually belong to multiple "
            "Schedule Correlation Groups rather than a single RBS L1 group?",
            OWNER_PM,
            ANSWER_YES_NO,
            "Option B correlation matrix depends on one CG per risk",
            PRIORITY_SHOULD,
        ),
        # --- Duration / consequence ---
        (
            "Duration",
            "Where the register narrative gives a single figure "
            "('4 days delay'), is the default PERT spread of half / equal / "
            "double appropriate, or do you have a tighter range?",
            OWNER_ESTIMATOR,
            ANSWER_TEXT,
            "Direct driver of EMV days and cost-of-delay",
            PRIORITY_MUST,
        ),
        (
            "Duration",
            "Where the narrative gives a month-denominated phrase "
            "('18 months', '40% increase'), should we treat it as schedule "
            "impact at all, or is this purely a cost-side effect?",
            OWNER_ESTIMATOR,
            ANSWER_SELECTION,
            "DUMMY-tagged rows currently contribute zero days - may undercount",
            PRIORITY_MUST,
        ),
        (
            "Duration",
            "For risks where the scenario text is silent on time "
            "(DUMMY tag), is that because the risk is cost-only, or "
            "because the duration is TBD pending this workshop?",
            OWNER_ESTIMATOR,
            ANSWER_SELECTION,
            "Distinguishes 'genuinely cost-only' from 'missing data'",
            PRIORITY_MUST,
        ),
        # --- Day-rate reconciliation ---
        (
            "Day-rate",
            "Is the derived site-running rate ($Prelims / 912 wd) the "
            "right governing figure for cost-of-delay, or should it be "
            "the higher peak-labour + IDC stacked rate?",
            OWNER_DIRECTOR,
            ANSWER_SELECTION,
            "Sets the EMV $ cost-of-delay column - directly affects headline figures",
            PRIORITY_MUST,
        ),
        (
            "Day-rate",
            "For risks whose BOE narrative quotes a different $/day rate "
            "to the derived site rate, which rate governs for schedule-"
            "driven EMV?",
            OWNER_ESTIMATOR,
            ANSWER_TEXT,
            "Per-risk day-rate override may be warranted for some dual-coded items",
            PRIORITY_SHOULD,
        ),
        (
            "Day-rate",
            "For the 3+ dual-coded risks (cost ML built from days x rate), "
            "should cost figures be zeroed in the post-workshop register "
            "update, with SRA carrying the schedule EMV?",
            OWNER_DIRECTOR,
            ANSWER_YES_NO,
            "Prevents double-counting of cost impact in integrated reporting",
            PRIORITY_MUST,
        ),
        # --- Critical-path classifier ---
        (
            "Critical path",
            "Is the Option Z hybrid classifier (asterisked zero-float "
            "milestones with commercial keywords = Series/CommitCon; "
            "float 0-20 wd = Hybrid; >20 wd = Parallel) defensible for "
            "the BOP schedule, or should we adopt a different rule?",
            OWNER_DIRECTOR,
            ANSWER_SELECTION,
            "Determines what counts as 'critical' across 1959 activities",
            PRIORITY_MUST,
        ),
        (
            "Critical path",
            "The CSE-KML-* milestone family is treated as Series/CommitCon "
            "(commercially binding). Are there other activity-ID prefixes "
            "or activity names that should get the same treatment?",
            OWNER_COMMERCIAL,
            ANSWER_TEXT,
            "Misclassified binding milestones distort Series count",
            PRIORITY_SHOULD,
        ),
        (
            "Critical path",
            "Should soft-pinned (asterisked zero-float but not commercially "
            "binding) activities be treated as Hybrid, or elevated to "
            "Series because the constraint itself is programme intent?",
            OWNER_PM,
            ANSWER_SELECTION,
            "Drives Mode for ~20-30 activities currently tagged SoftPin",
            PRIORITY_SHOULD,
        ),
        # --- Mode aggregation ---
        (
            "Mode aggregation",
            "The strawman uses 'most-conservative' Mode aggregation "
            "(any Series in the linked set -> Series). Is that the right "
            "rule, or should it be majority / proportion-of-Series-"
            "activities?",
            OWNER_DIRECTOR,
            ANSWER_SELECTION,
            "Every broad-scope risk currently resolves to Series; relaxing this reduces aggregate EMV",
            PRIORITY_MUST,
        ),
        # --- Reconciliation / seasons ---
        (
            "Seasons",
            "When programme_seasons flips from 1 to 3 (multi-year exposure), "
            "which risks should be tagged BINOMIAL (recurrence by year) "
            "versus remaining Single?",
            OWNER_PM,
            ANSWER_TEXT,
            "Amendment 2 Reconciliation B only activates for BINOMIAL risks",
            PRIORITY_MUST,
        ),
        (
            "Seasons",
            "For BINOMIAL risks, should the Reconciliation B divide-by-3 "
            "(treatment B) apply uniformly, or should per-risk treatment C "
            "be used post-workshop?",
            OWNER_DIRECTOR,
            ANSWER_SELECTION,
            "Post-workshop refactor hinges on this decision",
            PRIORITY_SHOULD,
        ),
        # --- LD / commercial ---
        (
            "LD",
            "What is the LD rate (AUD/day), LD cap (% of contract value), "
            "and earliest trigger date in the BOP Contract?",
            OWNER_COMMERCIAL,
            ANSWER_NUMBER,
            "LD exposure layer deferred pending these figures; can't be added to Option B without them",
            PRIORITY_MUST,
        ),
        (
            "LD",
            "What are the LD grounds for EOT / relief? Specifically: does "
            "force majeure, extreme weather, or utility connection delay "
            "entitle EOT with or without delay damages?",
            OWNER_COMMERCIAL,
            ANSWER_TEXT,
            "Determines whether weather / force majeure risks map to LD exposure",
            PRIORITY_MUST,
        ),
        (
            "LD",
            "Are there any interim / milestone LDs in addition to the "
            "final completion LD? If so, what are the rates and caps?",
            OWNER_COMMERCIAL,
            ANSWER_TEXT,
            "Milestone LDs change which risks carry LD exposure",
            PRIORITY_SHOULD,
        ),
        # --- Constraint identification ---
        (
            "Constraints",
            "Are any of the asterisked constraint dates in the P6 schedule "
            "negotiated contract dates (hard), versus planning intent (soft)?",
            OWNER_PM,
            ANSWER_TEXT,
            "Reclassifies SoftPin activities as Series/CommitCon if hard-pinned",
            PRIORITY_SHOULD,
        ),
        (
            "Constraints",
            "Is the 29-May-2026 start and 04-Feb-2029 finish firm, or are "
            "they the current baseline only?",
            OWNER_PM,
            ANSWER_SELECTION,
            "Programme dates drive Reconciliation B applicability for seasonal risks",
            PRIORITY_NICE,
        ),
        # --- Scope / package boundaries ---
        (
            "Scope",
            "Are there known package-boundary scope gaps (APA gas "
            "connection, OWS items, BOP/Turnkey split) that aren't "
            "represented as specific risks in the current register?",
            OWNER_PM,
            ANSWER_TEXT,
            "Missing scope risks go uncaptured in both cost and schedule MC",
            PRIORITY_SHOULD,
        ),
        (
            "Scope",
            "For Procurement & Supply Chain risks, are there long-lead "
            "items beyond the transformers that deserve bespoke linkage?",
            OWNER_PM,
            ANSWER_TEXT,
            "Refines mappings for Procurement CG",
            PRIORITY_SHOULD,
        ),
        # --- Governance ---
        (
            "Governance",
            "Is the programme_seasons = 3 assumption correct for Option B, "
            "or should it be higher (e.g. if wet-season sensitivity extends "
            "commissioning into a 4th year)?",
            OWNER_DIRECTOR,
            ANSWER_NUMBER,
            "Affects Reconciliation B divisor",
            PRIORITY_NICE,
        ),
        (
            "Governance",
            "Are the 3 exclusions (no LD figures, no contingency number, "
            "no cost-side refactor) acceptable for the Option A client "
            "package, or do any need to be brought into scope?",
            OWNER_DIRECTOR,
            ANSWER_SELECTION,
            "Scope lock before Option B",
            PRIORITY_MUST,
        ),
    ]


def build_questions(
    extras: Iterable[tuple[str, str, str, str, str, str]] | None = None,
) -> list[WorkshopQuestion]:
    """Return numbered WorkshopQuestion objects (base list + optional extras)."""
    items = list(_base_questions())
    if extras:
        items.extend(extras)
    out: list[WorkshopQuestion] = []
    for i, (cat, q, owner, ans, impact, pri) in enumerate(items, start=1):
        out.append(
            WorkshopQuestion(
                number=i,
                category=cat,
                question=q,
                owner=owner,
                answer_type=ans,
                impact_if_unresolved=impact,
                priority=pri,
            )
        )
    return out


def questions_by_owner(questions: list[WorkshopQuestion]) -> dict[str, list[WorkshopQuestion]]:
    """Group the question list by owner for the memo §5.6 breakdown."""
    out: dict[str, list[WorkshopQuestion]] = {}
    for q in questions:
        out.setdefault(q.owner, []).append(q)
    return out
