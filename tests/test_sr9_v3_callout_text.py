# SR9 v3 amendment - 2026-04-26 - presentation-layer reframe.
"""Tests for src/final/callout_text.py - static callout text constants."""

from __future__ import annotations

from src.final import callout_text


def test_why_mc_matters_returns_string():
    body = callout_text.WHY_MC_MATTERS
    assert isinstance(body, str)
    assert len(body) > 100, "callout body should be substantive"
    assert "Monte Carlo" in body or "MC" in body
    assert callout_text.WHY_MC_MATTERS_TITLE


def test_how_ages_well_returns_string():
    body = callout_text.HOW_THIS_AGES_WELL
    assert isinstance(body, str)
    assert len(body) > 100, "callout body should be substantive"
    assert "input" in body.lower() or "PM review" in body
    assert callout_text.HOW_THIS_AGES_WELL_TITLE
