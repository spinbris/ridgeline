"""Duration three-point parser for SP17 SRA Option A.

Extracts (Opt, ML, Pess) duration in working days from the earlier reference register's scenario
narratives. Each Open risk has three explicit scenario text fields
(Optimistic scenario / Likely scenario / Pessimistic scenario). The
parser scans those three fields for duration phrases - weeks or days -
and returns a best-effort three-point with a confidence tag.

Rules (in priority order):

1. Explicit phrase in each scenario ("2 week slippage", "closing the
   site for 4 days") -> CONSEQUENCE.
2. Phrase found in only some scenarios -> fill the gaps by PERT spread
   heuristic (half / equal / double) and tag DERIVED_LOW_CONFIDENCE.
3. "No delays" / "no change" / "no event" style in Opt -> zero days.
4. No phrase found in any scenario -> (0, 0, 0), DUMMY.

Working-day conversions: 1 week = 5 wd; 1 month = 22 wd.

No Risk IDs are referenced anywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.sra_strawman.defaults import WORKING_DAYS_PER_WEEK

# Duration source tags - schema values used as dropdown entries in the
# Mapping sheet (Brief Section 4.3). Not tunable numeric defaults, so
# they live here rather than in defaults.py.
TAG_CONSEQUENCE = "CONSEQUENCE"
TAG_DERIVED_LOW = "DERIVED_LOW_CONFIDENCE"
TAG_DUMMY = "DUMMY"
TAG_DERIVED = "DERIVED"  # reserved for linked-activity duration derivation


# Regex patterns. Case-insensitive, numeric capture supports integers or
# decimals; word-number pairs (Two / Three) handled by replacement.
_NUM = r"(\d+(?:\.\d+)?)"
_WEEK_RE = re.compile(rf"{_NUM}\s*(?:-|\s)?\s*weeks?\b", re.IGNORECASE)
_DAY_RE = re.compile(rf"{_NUM}\s*(?:-|\s)?\s*days?\b", re.IGNORECASE)
# Month phrases flag as AMBIGUOUS / DUMMY per Brief Section 3.4
# ("over 18 months (40% increase) -> flag as AMBIGUOUS and tag as DUMMY").
# Detected, but no authorised month-to-working-day conversion constant.
_MONTH_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:-|\s)?\s*months?\b", re.IGNORECASE)

# Event-shape phrases where a count multiplies a per-event duration.
# e.g. "Two (2) extreme weather event and flooding closing the site for
# 4 days each event" -> 2 events * 4 days = 8 days.
_EVENT_COUNT_RE = re.compile(
    r"(?:(\d+)\s*\(\s*\d+\s*\)|(\d+)\s+(?:events?|extreme|times?|occasions?))",
    re.IGNORECASE,
)
_PER_EVENT_DURATION_RE = re.compile(
    rf"(?:for|of|closing|delayed\s+by|delay(?:ed)?\s+of)\s+{_NUM}\s*(weeks?|days?|months?)\s+(?:each|per)\s+(?:event|occasion)?",
    re.IGNORECASE,
)

# Negation patterns.
_NO_DELAY_PATTERNS = (
    re.compile(
        r"\bno\s+(?:delay|disruption|event|change|slippage|impact|issue"
        r"|downtime|stoppage)s?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:no|not)\s+experience(?:d)?\s+any\b", re.IGNORECASE),
    re.compile(r"will\s+not\s+experience", re.IGNORECASE),
)

# Word-number map for "Two (2)" / "Three (3)" style phrases.
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


@dataclass(frozen=True)
class DurationExtract:
    opt_days: float
    ml_days: float
    pess_days: float
    tag: str
    notes: str


def _text(v: object) -> str:
    if v is None:
        return ""
    return str(v)


def _to_working_days(value: float, unit: str) -> float:
    u = unit.lower().rstrip("s")
    if u == "week":
        return value * WORKING_DAYS_PER_WEEK
    # 'day' or anything unrecognised (month phrases are not handled here;
    # they are flagged as DUMMY at the scenario level).
    return value


def _find_largest_duration(text: str) -> tuple[float | None, str]:
    """Return (duration_in_working_days, unit_word) for the largest
    duration phrase in text, or (None, '') if none."""
    if not text:
        return None, ""
    t = text
    best: tuple[float, str] = (-1.0, "")
    # Only week and day are convertible. See _MONTH_RE note.
    for pat, unit in ((_WEEK_RE, "week"), (_DAY_RE, "day")):
        for m in pat.finditer(t):
            try:
                v = float(m.group(1))
            except ValueError:
                continue
            wd = _to_working_days(v, unit)
            if wd > best[0]:
                best = (wd, unit)
    if best[0] < 0:
        return None, ""
    return best[0], best[1]


def _has_month_phrase(text: str) -> bool:
    return bool(text) and bool(_MONTH_RE.search(text))


def _is_negation(text: str) -> bool:
    if not text:
        return False
    for pat in _NO_DELAY_PATTERNS:
        if pat.search(text):
            return True
    return False


def _find_event_count(text: str) -> int | None:
    """Find an integer event count in 'Two (2) events' / '3 events' patterns."""
    if not text:
        return None
    # Try explicit (N) capture first.
    for m in _EVENT_COUNT_RE.finditer(text):
        n = m.group(1) or m.group(2)
        if n:
            try:
                return int(n)
            except ValueError:
                continue
    # Try word-number + event.
    for word, val in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\s+\(?\d*\)?\s*(?:extreme|events?|occasions?)",
                     text, re.IGNORECASE):
            return val
    return None


def _extract_scenario_days(scenario_text: str) -> float | None:
    """Extract a duration (working days) from one scenario string.

    Priority:
    1. If negation phrase -> 0.
    2. Per-event phrase 'N events ... M weeks each' -> N * M * wd_per_unit.
    3. Largest plain duration phrase.
    4. None if nothing found.
    """
    t = _text(scenario_text).strip()
    if not t:
        return None
    if _is_negation(t):
        return 0.0
    # Per-event: count * per-event duration.
    event_count = _find_event_count(t)
    per_event = _PER_EVENT_DURATION_RE.search(t)
    if event_count is not None and per_event:
        try:
            val = float(per_event.group(1))
            unit = per_event.group(2)
            return event_count * _to_working_days(val, unit)
        except (TypeError, ValueError):
            pass
    # Largest plain phrase.
    wd, _ = _find_largest_duration(t)
    return wd


def extract_duration_three_point(
    optimistic: object,
    likely: object,
    pessimistic: object,
) -> DurationExtract:
    """Extract (Opt, ML, Pess) duration in working days from scenario text.

    Returns DurationExtract with a tag classifying confidence.
    """
    opt = _extract_scenario_days(_text(optimistic))
    ml = _extract_scenario_days(_text(likely))
    pess = _extract_scenario_days(_text(pessimistic))

    # Month phrases are ambiguous - per Brief §3.4 tag as DUMMY if any
    # scenario references months (no authorised conversion).
    if any(_has_month_phrase(_text(t)) for t in (optimistic, likely, pessimistic)):
        return DurationExtract(
            0.0, 0.0, 0.0, TAG_DUMMY,
            "month-phrase in scenario - ambiguous per brief §3.4, flagged DUMMY"
        )

    any_value = any(v is not None for v in (opt, ml, pess))
    all_values = all(v is not None for v in (opt, ml, pess))

    if not any_value:
        return DurationExtract(0.0, 0.0, 0.0, TAG_DUMMY,
                               "no duration phrase found in any scenario")

    if all_values:
        # Full three-point directly from narrative.
        # Sanity: ensure Opt <= ML <= Pess. If reversed, still return as-is
        # but tag as DERIVED_LOW_CONFIDENCE - Steve needs to look.
        if not (opt <= ml <= pess):
            return DurationExtract(
                float(opt), float(ml), float(pess), TAG_DERIVED_LOW,
                "three-point extracted but ordering anomalous"
            )
        return DurationExtract(
            float(opt), float(ml), float(pess), TAG_CONSEQUENCE,
            "three-point extracted from Opt/Likely/Pess scenario text"
        )

    # Partial - fill gaps via half/double PERT spread around whichever we have.
    anchor = next(v for v in (ml, pess, opt) if v is not None)
    filled_opt = opt if opt is not None else max(0.0, anchor / 2.0)
    filled_ml = ml if ml is not None else anchor
    filled_pess = pess if pess is not None else anchor * 2.0
    return DurationExtract(
        float(filled_opt), float(filled_ml), float(filled_pess),
        TAG_DERIVED_LOW,
        "partial three-point; gaps filled by half/double heuristic"
    )


def derive_for_risk(risk: dict) -> DurationExtract:
    """Convenience wrapper: pull the three scenario fields from a risk dict."""
    return extract_duration_three_point(
        risk.get("optimistic_scenario"),
        risk.get("likely_scenario"),
        risk.get("pessimistic_scenario"),
    )
