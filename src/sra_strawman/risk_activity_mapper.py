"""Register-to-schedule risk-activity mapper.

For each Open risk in the earlier reference register, proposes one or more WBS prefixes (or
activity-ID patterns) in the P6 schedule. Uses RBS Level 2 narrative
labels as the primary signal, with narrative-text keyword fallback.
Never keys on Risk ID literals.

For each risk returns:
  - activity_linkage: human-readable description of the linked set
  - activity_id_prefixes: list of Activity-ID prefixes (empty if unmapped)
  - activity_id_patterns: list of Activity-ID substring patterns
  - mapping_confidence: 'High' | 'Medium' | 'Low' | '[NEEDS_REVIEW]'
  - rationale: one-line reason
  - schedule_cg: mirror of RBS Level 1 (per Brief Section 3.3)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.sra_strawman.cp_classifier import (
    MODE_HYBRID,
    MODE_PARALLEL,
    MODE_SERIES,
    classify_activity,
)
from src.sra_strawman.defaults import (
    BROAD_LINKAGE_CONFIDENCE_DOWNGRADE_THRESHOLD,
)

# -----------------------------------------------------------------------
# Mapping rubric. Every entry here is keyed by a REGISTER NARRATIVE TERM
# (RBS L2 label or keyword cluster), NEVER by a Risk ID. Adding or
# removing risks in the earlier reference register does not require a change to this rubric.
#
# Prefixes are matched startswith() against P6's activity_id column.
# In the reference P6 export the register's WBS taxonomy ('20.C.', '40.C.',
# '20.COM.', '10.E.' etc.) is embedded in the Activity ID - NOT in the
# wbs_code column (which is uniformly 'BGP.BoP.' across the whole export).
# Empty list means "no schedule linkage - cost-only risk".
# -----------------------------------------------------------------------


@dataclass(frozen=True)
class MappingRule:
    # RBS L2 labels (lowercased, substring-matched) that activate this rule.
    rbs_l2_terms: tuple[str, ...]
    # Fallback narrative keywords scanned in desc + consequences.
    narrative_keywords: tuple[str, ...]
    # Activity-ID prefixes the risk links to (startswith match on activity_id).
    activity_id_prefixes: tuple[str, ...]
    # Activity-ID substring patterns (ALL must be substrings of activity_id).
    activity_id_patterns: tuple[str, ...]
    # Human-readable linkage description.
    linkage_label: str
    # Default confidence for this rule.
    confidence: str
    # Rationale printed in the output.
    rationale: str


# Each rule is generic to any BOP project, keyed on register narrative.
# Project-specific prefixes come from the P6 export's Activity ID
# taxonomy: '20.C.' (GT civil), '40.C.' (BOP civil), '20.COM.' (GT
# commissioning), '10.E.' (earthworks), '96.' (verification), etc.
MAPPING_RULES: tuple[MappingRule, ...] = (
    MappingRule(
        rbs_l2_terms=("weather impacts",),
        narrative_keywords=("weather", "wet season", "inclement", "la nina", "rain"),
        activity_id_prefixes=("20.C.", "30.C.", "40.C.", "50.C."),
        activity_id_patterns=(),
        linkage_label="Outdoor construction - all site construction WBS",
        confidence="Medium",
        rationale="Weather impacts hit outdoor construction phases broadly",
    ),
    MappingRule(
        rbs_l2_terms=("force majeure",),
        narrative_keywords=("force majeure", "extreme weather event", "flooding"),
        activity_id_prefixes=("20.C.", "30.C.", "40.C."),
        activity_id_patterns=(),
        linkage_label="Construction-phase site (force majeure exposure)",
        confidence="Medium",
        rationale="Force majeure stops all construction, not commissioning",
    ),
    MappingRule(
        rbs_l2_terms=("logistics", "transport disruptions"),
        narrative_keywords=("logistics", "transport", "delivery", "shipping", "gtg"),
        activity_id_prefixes=("20.",),
        activity_id_patterns=(),
        linkage_label="Power Island receipt/handling",
        confidence="Medium",
        rationale="Plant delivery delays land at GT / Power Island scope",
    ),
    MappingRule(
        rbs_l2_terms=("subcontractor impacts",),
        narrative_keywords=("subcontract", "resequencing"),
        activity_id_prefixes=("40.C.",),
        activity_id_patterns=(),
        linkage_label="BOP civil / subcontract scope",
        confidence="Medium",
        rationale="Subcontractor slippage primarily BOP civil package",
    ),
    MappingRule(
        rbs_l2_terms=("productivity shortfalls", "labour availability"),
        narrative_keywords=("productivity", "workforce", "churn", "labour"),
        activity_id_prefixes=("20.C.", "30.C.", "40.C."),
        activity_id_patterns=(),
        linkage_label="Labour-heavy construction WBS",
        confidence="Medium",
        rationale="Labour productivity affects all self-perform construction",
    ),
    MappingRule(
        rbs_l2_terms=("quality issues",),
        narrative_keywords=("defect", "qa", "quality", "rework"),
        activity_id_prefixes=("96.",),
        activity_id_patterns=(),
        linkage_label="Construction Verification (96.*)",
        confidence="Medium",
        rationale="Defect detection and rework sits under verification",
    ),
    MappingRule(
        rbs_l2_terms=("critical path slippage",),
        narrative_keywords=("commissioning", "practical completion", "handover"),
        activity_id_prefixes=("20.COM.", "96.", "98.", "99."),
        activity_id_patterns=(),
        linkage_label="Commissioning and handover chain",
        confidence="Medium",
        rationale="Commissioning/PC slippage traces to 20.COM + verification + closeout",
    ),
    MappingRule(
        rbs_l2_terms=("equipment or plant failure",),
        narrative_keywords=("transformer", "heavy lift", "main transformer"),
        activity_id_prefixes=(),
        activity_id_patterns=("20.COM.", ".EI.310"),
        linkage_label="Serial hot-commissioning chain (20.COM.*.EI.310)",
        confidence="High",
        rationale="Transformer/heavy-lift failures land on the critical commissioning chain",
    ),
    MappingRule(
        rbs_l2_terms=("access restrictions", "safety / whs non-compliance",
                      "environmental compliance breaches"),
        narrative_keywords=("security", "safety", "environmental", "breach"),
        activity_id_prefixes=("20.C.", "30.C.", "40.C."),
        activity_id_patterns=(),
        linkage_label="Sitewide construction (all self-perform)",
        confidence="Low",
        rationale="Sitewide compliance/access incidents affect all concurrent construction",
    ),
    MappingRule(
        rbs_l2_terms=("supplier performance issues",),
        narrative_keywords=("vendor equipment fails", "dlp", "defects liability"),
        activity_id_prefixes=("20.COM.",),
        activity_id_patterns=(),
        linkage_label="Commissioning + DLP scope",
        confidence="Low",
        rationale="Vendor-supplied equipment failures surface during commissioning/DLP",
    ),
    MappingRule(
        rbs_l2_terms=("material availability",),
        narrative_keywords=("material", "sand", "fill", "concrete", "batching"),
        activity_id_prefixes=("20.C.", "40.C."),
        activity_id_patterns=(),
        linkage_label="Civil / foundations / piling",
        confidence="Medium",
        rationale="Raw-materials shortages hit concrete and civil scope",
    ),
    MappingRule(
        rbs_l2_terms=("design development",),
        narrative_keywords=("design development", "detailed design"),
        activity_id_prefixes=("20.", "40."),
        activity_id_patterns=(),
        linkage_label="Design phase (Power Island + BOP)",
        confidence="Low",
        rationale="Design development affects both GT and BOP scopes",
    ),
    MappingRule(
        rbs_l2_terms=("scope gaps", "scope issues"),
        narrative_keywords=("scope gap", "turnkey", "vendor", "rfq"),
        activity_id_prefixes=("20.", "40."),
        activity_id_patterns=(),
        linkage_label="Package/scope boundary (Power Island + BOP)",
        confidence="Low",
        rationale="Scope gaps tend to sit at contract package boundaries",
    ),
    # Cost-only rules - no schedule linkage.
    MappingRule(
        rbs_l2_terms=("cost escalation", "budget overruns"),
        narrative_keywords=("escalation", "commodities", "tariffs", "market rates"),
        activity_id_prefixes=(),
        activity_id_patterns=(),
        linkage_label="Cost-only - no direct schedule impact",
        confidence="Medium",
        rationale="Cost escalation affects $ not days; no schedule linkage",
    ),
)


NEEDS_REVIEW_CONFIDENCE = "[NEEDS_REVIEW]"


@dataclass(frozen=True)
class RiskMapping:
    risk_id: str
    rbs_l1: str | None
    linkage_label: str
    activity_id_prefixes: tuple[str, ...]
    activity_id_patterns: tuple[str, ...]
    mapping_confidence: str
    rationale: str
    linked_activity_count: int
    min_total_float_days: float | None
    mode: str
    series_source: str
    schedule_cg: str | None


def _match_rule(risk: dict) -> MappingRule | None:
    """Return the first rule whose RBS L2 term or narrative keyword matches."""
    rbs_l2 = (risk.get("rbs_l2") or "").strip().lower()
    desc = (risk.get("description") or "").lower()
    cons = (risk.get("consequences") or "").lower()
    blob = f"{desc} {cons}"

    # First pass: RBS L2 exact/substring.
    for rule in MAPPING_RULES:
        for term in rule.rbs_l2_terms:
            if term in rbs_l2:
                return rule

    # Second pass: narrative keyword fallback.
    for rule in MAPPING_RULES:
        for kw in rule.narrative_keywords:
            if kw in blob:
                return rule

    return None


def _find_linked_activities(
    activities: list[dict],
    activity_id_prefixes: Iterable[str],
    activity_id_patterns: Iterable[str],
) -> list[dict]:
    """Return activities whose activity_id starts with any given prefix,
    OR contains ALL of the given substring patterns."""
    prefixes = tuple(p for p in activity_id_prefixes if p)
    patterns = tuple(p for p in activity_id_patterns if p)
    if not prefixes and not patterns:
        return []
    out: list[dict] = []
    for act in activities:
        if act.get("is_wbs_summary"):
            continue
        aid = (act.get("activity_id") or "").strip()
        if prefixes and any(aid.startswith(p) for p in prefixes):
            out.append(act)
            continue
        if patterns and all(p in aid for p in patterns):
            out.append(act)
    return out


def _derive_mode(linked: list[dict]) -> tuple[str, str, float | None]:
    """Aggregate activity-level classifications to a risk-level Mode.

    Rule (Brief §3.3): most-conservative.
      any Series -> Series
      else any Hybrid -> Hybrid
      else -> Parallel
    series_source = that of the dominant activity (first seen of the winning mode).
    Returns (mode, series_source, min_total_float_days).
    """
    if not linked:
        return (MODE_PARALLEL, "ParallelByFloat", None)

    modes_seen: list[tuple[str, str]] = []
    floats: list[float] = []
    for act in linked:
        c = classify_activity(act)
        modes_seen.append((c.mode, c.series_source))
        tf = act.get("total_float_days")
        if tf is not None:
            floats.append(float(tf))

    for pref in (MODE_SERIES, MODE_HYBRID, MODE_PARALLEL):
        for mode, src in modes_seen:
            if mode == pref:
                return (mode, src, min(floats) if floats else None)

    return (MODE_PARALLEL, "ParallelByFloat", min(floats) if floats else None)


def map_risk(risk: dict, activities: list[dict]) -> RiskMapping:
    """Produce a RiskMapping for one risk dict from the register."""
    rule = _match_rule(risk)
    if rule is None:
        return RiskMapping(
            risk_id=str(risk.get("risk_id") or ""),
            rbs_l1=risk.get("rbs_l1"),
            linkage_label="[UNMAPPED - to review]",
            activity_id_prefixes=(),
            activity_id_patterns=(),
            mapping_confidence=NEEDS_REVIEW_CONFIDENCE,
            rationale="No RBS L2 term or narrative keyword matched the rubric",
            linked_activity_count=0,
            min_total_float_days=None,
            mode=NEEDS_REVIEW_CONFIDENCE,
            series_source=NEEDS_REVIEW_CONFIDENCE,
            schedule_cg=risk.get("rbs_l1"),
        )

    linked = _find_linked_activities(
        activities, rule.activity_id_prefixes, rule.activity_id_patterns
    )
    if not rule.activity_id_prefixes and not rule.activity_id_patterns:
        # Cost-only rule.
        return RiskMapping(
            risk_id=str(risk.get("risk_id") or ""),
            rbs_l1=risk.get("rbs_l1"),
            linkage_label=rule.linkage_label,
            activity_id_prefixes=(),
            activity_id_patterns=(),
            mapping_confidence=rule.confidence,
            rationale=rule.rationale,
            linked_activity_count=0,
            min_total_float_days=None,
            mode=MODE_PARALLEL,
            series_source="ParallelByFloat",
            schedule_cg=risk.get("rbs_l1"),
        )

    mode, src, min_tf = _derive_mode(linked)
    confidence = rule.confidence
    if len(linked) > BROAD_LINKAGE_CONFIDENCE_DOWNGRADE_THRESHOLD:
        confidence = "Low"
    return RiskMapping(
        risk_id=str(risk.get("risk_id") or ""),
        rbs_l1=risk.get("rbs_l1"),
        linkage_label=rule.linkage_label,
        activity_id_prefixes=tuple(rule.activity_id_prefixes),
        activity_id_patterns=tuple(rule.activity_id_patterns),
        mapping_confidence=confidence,
        rationale=rule.rationale,
        linked_activity_count=len(linked),
        min_total_float_days=min_tf,
        mode=mode,
        series_source=src,
        schedule_cg=risk.get("rbs_l1"),
    )


def map_all_risks(risks: list[dict], activities: list[dict]) -> list[RiskMapping]:
    """Apply map_risk to every risk in the list."""
    return [map_risk(r, activities) for r in risks]
