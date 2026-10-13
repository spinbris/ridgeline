"""Phase 2 Task C1 - Mapping column G pattern parser.

Three templates supported in col G prose:

1. ``<prose> [prefixes: a, b, c]`` -> regular prefix pattern.
2. ``Cost-only - no direct schedule impact`` -> cost-only marker.
3. ``<prose> [patterns: <wildcard>]`` -> wildcard. R067 is the only known
   instance. Per Steve's C1 resolution, R067 is treated as cost-only-equivalent
   for Phase 2 (its Time Impact = No so EMV output = 0 regardless).
   Any OTHER ``[patterns: ...]`` instance should still STOP for review.

Anything not matching one of the three templates is a parse failure.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

PREFIX_RE = re.compile(r"\[prefixes:\s*([^\]]+)\]", re.IGNORECASE)
WILDCARD_RE = re.compile(r"\[patterns:\s*([^\]]+)\]", re.IGNORECASE)
COST_ONLY_TEXT = "Cost-only - no direct schedule impact"

R067_PATTERN_PROSE = "Serial hot-commissioning chain (20.COM.*.EI.310) [patterns: 20.COM.+.EI.310]"
R067_OVERRIDE_DESCRIPTION = (
    "R067 heavy-lift E&I commissioning - practical prefix substitute for "
    "wildcard 20.COM.*.EI.310, pending SP9 regex support"
)
R067_OVERRIDE_NOTES = (
    "C1 decision revised 23 April 2026 after confirming R067 Time Impact = Yes "
    "in V8 Risk_Register. Original wildcard pattern 20.COM.*.EI.310 approximated "
    "by prefix 20.COM. (broader than R067's actual scope but conservative-default "
    "per brief). Full regex-based narrow pattern deferred to SP9."
)
R067_PRACTICAL_PREFIXES = ["20.COM."]


@dataclass
class ParsedPattern:
    """One distinct pattern extracted from Mapping col G."""

    raw_prose: str
    description: str
    prefixes: list[str] = field(default_factory=list)
    is_cost_only: bool = False
    notes: str = ""
    parse_kind: str = ""  # 'prefixes' | 'cost_only' | 'wildcard_r067'


@dataclass
class ParseFailure:
    risk_id: str
    raw_prose: str
    reason: str


def parse_one(prose: str) -> ParsedPattern | None:
    """Return ParsedPattern or None if prose doesn't fit any known template."""
    if prose is None:
        return None
    text = prose.strip()
    if not text:
        return None

    if text == COST_ONLY_TEXT:
        return ParsedPattern(
            raw_prose=text,
            description=text,
            prefixes=[],
            is_cost_only=True,
            notes="",
            parse_kind="cost_only",
        )

    if text == R067_PATTERN_PROSE:
        return ParsedPattern(
            raw_prose=text,
            description=R067_OVERRIDE_DESCRIPTION,
            prefixes=list(R067_PRACTICAL_PREFIXES),
            is_cost_only=False,
            notes=R067_OVERRIDE_NOTES,
            parse_kind="wildcard_r067_revised",
        )

    m = PREFIX_RE.search(text)
    if m:
        raw_list = m.group(1)
        prefixes = [p.strip() for p in raw_list.split(",") if p.strip()]
        if not prefixes:
            return None
        return ParsedPattern(
            raw_prose=text,
            description=text,
            prefixes=prefixes,
            is_cost_only=False,
            notes="",
            parse_kind="prefixes",
        )

    return None


def extract_patterns(
    rows: list[tuple[str, str]],
) -> tuple[list[ParsedPattern], list[ParseFailure]]:
    """rows = [(risk_id, col_g_prose), ...].

    Returns (unique patterns in first-appearance order, list of parse failures).
    """
    seen: dict[str, ParsedPattern] = {}
    failures: list[ParseFailure] = []
    for risk_id, prose in rows:
        prose_str = "" if prose is None else str(prose).strip()
        if not prose_str:
            failures.append(
                ParseFailure(
                    risk_id=risk_id,
                    raw_prose="",
                    reason="empty col G prose",
                )
            )
            continue
        if prose_str in seen:
            continue
        parsed = parse_one(prose_str)
        if parsed is None:
            wc = WILDCARD_RE.search(prose_str)
            reason = (
                "wildcard pattern other than R067's known case"
                if wc
                else "prose does not match [prefixes: ...] template, "
                "is not Cost-only, and is not the R067 wildcard"
            )
            failures.append(
                ParseFailure(risk_id=risk_id, raw_prose=prose_str, reason=reason)
            )
            continue
        seen[prose_str] = parsed
    return list(seen.values()), failures


CONFIDENCE_PRIORITY = {"Low": 0, "Medium": 1, "High": 2}


def mode_with_tiebreak(values: list[str]) -> tuple[str, bool]:
    """Mode with conservative-lower tiebreak (Low > Medium > High when tied).

    Returns (chosen_value, was_tied). Empty input -> ("", False).
    Unknown values are passed through but rank last in tiebreak.
    """
    cleaned = [v for v in values if v]
    if not cleaned:
        return ("", False)
    counts = Counter(cleaned)
    max_count = max(counts.values())
    contenders = [v for v, c in counts.items() if c == max_count]
    if len(contenders) == 1:
        return (contenders[0], False)
    contenders.sort(key=lambda v: CONFIDENCE_PRIORITY.get(v, 99))
    return (contenders[0], True)
