"""Phase 2 Task C4 - unit tests for prefix-based pattern matching.

Brief mandates 5+ tests covering: exact match, multi-prefix pattern, no match,
cost-only pattern skipped, activity ID shorter than prefix.
"""

from __future__ import annotations

import pytest

from src.sra_strawman.phase2.matched_patterns import (
    PatternRow,
    match_patterns_for_activity,
    parse_prefix_list,
)


@pytest.fixture
def patterns() -> list[PatternRow]:
    """Mini fixture mirroring real Phase 2 patterns."""
    return [
        PatternRow("P01", ("20.C.", "30.C.", "40.C."), False),
        PatternRow("P04", ("20.",), False),
        PatternRow("P09", ("20.COM.",), False),
        PatternRow("P10", (), True),
        PatternRow("P13", (), True),
        PatternRow("P14", ("20.COM.", "96.", "98.", "99."), False),
    ]


def test_exact_prefix_match(patterns):
    assert match_patterns_for_activity("20.C.", patterns) == "P01;P04"


def test_multi_prefix_pattern_only_matches_once(patterns):
    """An activity that hits two of P01's three prefixes still appears once."""
    assert match_patterns_for_activity("30.C.0010", patterns) == "P01"


def test_no_match_returns_empty_string(patterns):
    assert match_patterns_for_activity("70.X.999", patterns) == ""


def test_cost_only_pattern_skipped(patterns):
    """P10 and P13 are cost-only - neither has prefixes, but even if they did
    they should be excluded from matching."""
    spiked = patterns + [PatternRow("P99", ("20.",), is_cost_only=True)]
    matched = match_patterns_for_activity("20.AAA", spiked)
    assert "P99" not in matched
    assert matched == "P04"


def test_activity_id_shorter_than_prefix(patterns):
    """If activity_id is shorter than any candidate prefix, only shorter prefixes can match."""
    assert match_patterns_for_activity("20", patterns) == ""
    assert match_patterns_for_activity("96", patterns) == ""
    assert match_patterns_for_activity("96.", patterns) == "P14"


def test_deterministic_order_lexicographic(patterns):
    """20.COM.X.EI.310 hits P04 (20.), P09 (20.COM.), P14 (20.COM.) - results must be sorted."""
    out = match_patterns_for_activity("20.COM.A.EI.310", patterns)
    assert out == "P04;P09;P14"
    parts = out.split(";")
    assert parts == sorted(parts)


def test_none_and_blank_inputs(patterns):
    assert match_patterns_for_activity(None, patterns) == ""
    assert match_patterns_for_activity("", patterns) == ""
    assert match_patterns_for_activity("   ", patterns) == ""


def test_no_patterns_returns_empty():
    assert match_patterns_for_activity("20.C.123", []) == ""


def test_pattern_with_empty_prefix_string_does_not_universal_match():
    """A pattern with prefixes containing '' should NOT match every activity."""
    bad = [PatternRow("PXX", ("",), False)]
    assert match_patterns_for_activity("anything", bad) == ""


def test_parse_prefix_list_handles_semicolons_and_whitespace():
    assert parse_prefix_list("20.C.; 30.C. ;40.C.") == ["20.C.", "30.C.", "40.C."]
    assert parse_prefix_list("") == []
    assert parse_prefix_list(None) == []
    assert parse_prefix_list(";;;") == []
    assert parse_prefix_list("only_one") == ["only_one"]
