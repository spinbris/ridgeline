"""Phase 2 Task C4 - prefix-based pattern matching for P6 activities.

Pure helper that populates tblP6Processed col Z.

Rule per brief: an activity matches a pattern if its Activity_ID startswith ANY
of the pattern's prefixes. Cost-only patterns produce no matches. Pattern_IDs
are returned semicolon-separated in deterministic Pattern_ID order
(lexicographic on the zero-padded P01..P14 string == numerical order).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PatternRow:
    """Slim record loaded from tblRiskPatterns for matching purposes."""

    pattern_id: str  # 'P01', ..., 'P14'
    prefixes: tuple[str, ...]
    is_cost_only: bool


def parse_prefix_list(raw: object) -> list[str]:
    """Split a semicolon-separated prefix list into a clean list (drops blanks)."""
    if raw is None:
        return []
    return [p.strip() for p in str(raw).split(";") if p.strip()]


def match_patterns_for_activity(
    activity_id: object,
    patterns: list[PatternRow],
) -> str:
    """Return semicolon-separated matched Pattern_IDs (or empty string)."""
    if activity_id is None:
        return ""
    aid = str(activity_id).strip()
    if not aid:
        return ""

    matched: list[str] = []
    for pat in patterns:
        if pat.is_cost_only:
            continue
        if not pat.prefixes:
            continue
        for prefix in pat.prefixes:
            if not prefix:
                continue
            if aid.startswith(prefix):
                matched.append(pat.pattern_id)
                break
    matched.sort()
    return ";".join(matched)
