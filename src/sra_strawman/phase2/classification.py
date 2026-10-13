"""Phase 2 Task B2 - Mode classification per the Longest Path rule.

Pure functions, easy to unit test.
"""

from __future__ import annotations

HYBRID_FLOAT_THRESHOLD = 10.0


def classify_mode(critical: bool, total_float_days: float | None) -> str:
    """Apply Longest Path classification.

    - Critical = Yes -> Series
    - Critical = No AND Total Float < 10 (includes 0) -> Hybrid
    - Everything else -> Parallel

    Activities with missing total_float are conservatively treated as Parallel
    (since we can't prove they're near-critical). None should be rare in
    the supplied Longest Path file.
    """
    if critical:
        return "Series"
    if total_float_days is None:
        return "Parallel"
    if total_float_days < HYBRID_FLOAT_THRESHOLD:
        return "Hybrid"
    return "Parallel"


def series_source(mode: str) -> str:
    """Map Mode to its source label."""
    if mode == "Series":
        return "LongestPath"
    if mode == "Hybrid":
        return "NearCritical"
    if mode == "Parallel":
        return "ParallelByFloat"
    return ""


def constraint_driven(primary_constraint: str | None) -> bool:
    """True if Primary Constraint is non-empty (after strip)."""
    if primary_constraint is None:
        return False
    return bool(str(primary_constraint).strip())
