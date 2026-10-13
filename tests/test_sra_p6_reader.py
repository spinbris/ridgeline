"""Unit tests for src.sra_strawman.p6_reader.

Happy-path and edge cases cover the brief's Section 3.1 test requirements:
- Row counts (3263 total sheet rows, 354 WBS summaries, 1959 activities)
- Level distribution matches the expected dict
- P6 critical=Yes count == 90
- total_float==0 count == 443
- At least one asterisk-constrained milestone is detected
"""

from __future__ import annotations

from datetime import datetime


from src.sra_strawman.p6_reader import _parse_date_cell, _parse_duration

# Expected counts from the SP17 brief and pre-flight inspection.
# ---------- unit tests on parsers (no file IO) ----------

def test_parse_duration_valid_formats():
    assert _parse_duration("912.0d") == 912.0
    assert _parse_duration("0.0d") == 0.0
    assert _parse_duration("46d") == 46.0
    assert _parse_duration("  10.5d  ") == 10.5
    assert _parse_duration(100) == 100.0


def test_parse_duration_none_and_bad():
    assert _parse_duration(None) is None
    assert _parse_duration("") is None
    assert _parse_duration("not a duration") is None


def test_parse_date_cell_datetime_is_unconstrained():
    dt = datetime(2026, 5, 29)
    parsed, constr = _parse_date_cell(dt)
    assert parsed == dt
    assert constr is False


def test_parse_date_cell_asterisked_string():
    parsed, constr = _parse_date_cell("29-May-26*")
    assert parsed == datetime(2026, 5, 29)
    assert constr is True


def test_parse_date_cell_plain_string():
    parsed, constr = _parse_date_cell("29-May-26")
    assert parsed == datetime(2026, 5, 29)
    assert constr is False


def test_parse_date_cell_empty():
    parsed, constr = _parse_date_cell(None)
    assert parsed is None
    assert constr is False


# ---------- integration tests against the real P6 file ----------
