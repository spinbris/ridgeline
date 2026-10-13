# SR9 v3 amendment - 2026-04-26 - presentation-layer reframe.
"""Tests for src/final/commentary_text.py - narrative templates."""

from __future__ import annotations

from src.final import commentary_text


ORIENTING_KEYS = [
    "DISTRIBUTION_ORIENTING",
    "COST_TORNADO_ORIENTING",
    "SCHEDULE_TORNADO_ORIENTING",
    "MODE_SENSITIVITY_ORIENTING",
    "RISK_MATRIX_ORIENTING",
    "COMPARISON_ORIENTING",
    "WATERFALL_ORIENTING",
    "TREATMENT_ROI_ORIENTING",
]

INTERPRETATION_KEYS = [
    "DISTRIBUTION_INTERPRETATION",
    "COST_TORNADO_INTERPRETATION",
    "SCHEDULE_TORNADO_INTERPRETATION",
    "MODE_SENSITIVITY_INTERPRETATION",
    "RISK_MATRIX_INTERPRETATION",
    "COMPARISON_INTERPRETATION",
    "WATERFALL_INTERPRETATION",
    "TREATMENT_ROI_INTERPRETATION",
]


def test_all_orienting_paragraphs_present():
    for key in ORIENTING_KEYS:
        text = getattr(commentary_text, key, None)
        assert isinstance(text, str), f"{key} missing or not a string"
        assert len(text) > 50, f"{key} should be a substantive paragraph"


def test_all_interpretation_paragraphs_present():
    for key in INTERPRETATION_KEYS:
        text = getattr(commentary_text, key, None)
        assert isinstance(text, str), f"{key} missing or not a string"
        assert len(text) > 50, f"{key} should be a substantive paragraph"


def test_headline_opening_template_formats_with_runtime_values():
    formatted = commentary_text.HEADLINE_OPENING.format(
        mean_days=15.5,
        mean_cost_m=4.37,
        day_rate=100000,
        lower_days=1.78,
        upper_days=19.64,
    )
    assert "15.5" in formatted
    assert "4.37" in formatted
    assert "100,000" in formatted
    assert "1.8" in formatted  # lower_days renders as 1.8
    assert "19.6" in formatted  # upper_days renders as 19.6
    # No leftover format placeholders
    assert "{" not in formatted
    assert "}" not in formatted
