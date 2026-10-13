"""Option Z hybrid critical-path classifier.

Implements Amendment 1 of the SP17 SRA Option A brief:

    1. total_float == 0:
         if start/finish constrained (asterisked):
             if commercially binding -> Series / CommitCon
             else                    -> Hybrid / SoftPin
         else (logic-driven zero-float) -> Series / LogicZero
    2. 0 < total_float <= threshold -> Hybrid / NearCritical
    3. total_float > threshold     -> Parallel / ParallelByFloat

Keywords and ID prefixes that flag a commercially-binding milestone are
held in module-level constants so they can be reviewed / extended per
project without touching the logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.sra_strawman.defaults import HYBRID_FLOAT_THRESHOLD_DAYS

# Re-exported under the original name to preserve the call-site default.
DEFAULT_HYBRID_FLOAT_THRESHOLD_DAYS: float = HYBRID_FLOAT_THRESHOLD_DAYS

# Activity-ID prefixes reserved for the client's contractual milestone set.
# Typically these are the owner's Key Milestones.
COMMERCIAL_MILESTONE_ID_PREFIXES: tuple[str, ...] = ("CSE-KML-",)

# Activity-name keywords (case-insensitive substring match) that flag a
# contractual / commercial-operation milestone.
COMMERCIAL_MILESTONE_KEYWORDS: tuple[str, ...] = (
    "COD",
    "Commercial Operation",
    "Ready for First Fire",
    "Ready for Hot Commissioning",
    "Practical Completion",
    "Takeover",
)

# Legal classifier outputs.
MODE_SERIES = "Series"
MODE_HYBRID = "Hybrid"
MODE_PARALLEL = "Parallel"

SOURCE_COMMITCON = "CommitCon"
SOURCE_LOGICZERO = "LogicZero"
SOURCE_NEARCRITICAL = "NearCritical"
SOURCE_SOFTPIN = "SoftPin"
SOURCE_PARALLELBYFLOAT = "ParallelByFloat"


@dataclass(frozen=True)
class Classification:
    mode: str
    series_source: str


def is_commercially_binding(activity_id: str | None, activity_name: str | None) -> bool:
    """Return True if the activity is a contractual milestone.

    Rule 1: activity_id prefix is in COMMERCIAL_MILESTONE_ID_PREFIXES.
    Rule 2: activity_name contains any of COMMERCIAL_MILESTONE_KEYWORDS
            (case-insensitive substring).
    """
    if activity_id:
        aid = activity_id.strip()
        for prefix in COMMERCIAL_MILESTONE_ID_PREFIXES:
            if aid.startswith(prefix):
                return True
    if activity_name:
        name_upper = activity_name.upper()
        for kw in COMMERCIAL_MILESTONE_KEYWORDS:
            if kw.upper() in name_upper:
                return True
    return False


def classify_activity(
    activity: dict,
    hybrid_float_threshold_days: float = DEFAULT_HYBRID_FLOAT_THRESHOLD_DAYS,
) -> Classification:
    """Classify a single activity dict per the Option Z hybrid rule."""
    total_float = activity.get("total_float_days")
    if total_float is None:
        # Unparseable or missing float -> cannot classify; treat as Parallel.
        return Classification(MODE_PARALLEL, SOURCE_PARALLELBYFLOAT)

    # Zero-float branch.
    if total_float == 0:
        start_c = bool(activity.get("start_is_constrained"))
        finish_c = bool(activity.get("finish_is_constrained"))
        if start_c or finish_c:
            if is_commercially_binding(
                activity.get("activity_id"), activity.get("activity_name")
            ):
                return Classification(MODE_SERIES, SOURCE_COMMITCON)
            return Classification(MODE_HYBRID, SOURCE_SOFTPIN)
        return Classification(MODE_SERIES, SOURCE_LOGICZERO)

    if total_float <= hybrid_float_threshold_days:
        return Classification(MODE_HYBRID, SOURCE_NEARCRITICAL)

    return Classification(MODE_PARALLEL, SOURCE_PARALLELBYFLOAT)


def classify_schedule(
    activities: list[dict],
    hybrid_float_threshold_days: float = DEFAULT_HYBRID_FLOAT_THRESHOLD_DAYS,
    include_wbs_summaries: bool = False,
) -> list[dict]:
    """Annotate each activity with `mode` and `series_source` keys.

    Parameters
    ----------
    activities : list[dict]
        Rows from p6_reader.read_p6_schedule (or .activity_rows).
    include_wbs_summaries : bool
        If False (default), WBS summary rows are skipped. Summaries are
        rollups of their children and classifying them is meaningless.
    """
    out: list[dict] = []
    for act in activities:
        if act.get("is_wbs_summary") and not include_wbs_summaries:
            continue
        c = classify_activity(act, hybrid_float_threshold_days)
        out.append({**act, "mode": c.mode, "series_source": c.series_source})
    return out


def summarise_counts(classified: list[dict]) -> dict[str, int]:
    """Return a terse count summary {mode: n, ..., 'total': n, ...}."""
    counts: dict[str, int] = {}
    for row in classified:
        counts[row["mode"]] = counts.get(row["mode"], 0) + 1
        key = f"source:{row['series_source']}"
        counts[key] = counts.get(key, 0) + 1
    counts["total"] = len(classified)
    return counts
