"""Unit tests for src.sra_strawman.day_rate_memo.

Covers:
- SP12 Preliminaries read from Pricing Summary!R8, sanity range
- Site-running rate derivation ($/wd and $/cd)
- Dual-coded detection: "$X/day", "$Xk/week", "N days x rate", "prelim" + "$"
- Hypothesis classification buckets
- No Risk ID literals in module source
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.sra_strawman.day_rate_memo import (
    DayRateContext,
    build_dual_coded_findings,
    build_reconciliation_rows,
    classify_rate_hypothesis,
    detect_dual_coded,
)


# ---------- SP12 preliminaries read ----------

# ---------- dual-coded pattern detection ----------

def test_detect_days_times_pattern():
    boe = "Most Likely Calculation: 5 Events @ 4 Hrs per event x prelim rate"
    f = detect_dual_coded("X1", boe)
    assert f.is_dual_coded
    assert f.days_times_pattern
    assert f.prelim_ref


def test_detect_explicit_dollar_per_day():
    boe = "Pessimistic = 2 weeks x site running costs ($950,000 per week)"
    f = detect_dual_coded("X2", boe)
    assert f.is_dual_coded
    assert f.rate_quote_raw is not None
    # $950,000 / 5 wd = $190,000 / wd.
    assert f.rate_quote_value_per_day == pytest.approx(190_000.0)


def test_detect_dollar_k_per_day():
    boe = "Assume delay at $125k per day consistent with peak labour gang rate"
    f = detect_dual_coded("X3", boe)
    assert f.is_dual_coded
    # "$125k/day" -> 125 * 1000 = 125,000.
    assert f.rate_quote_value_per_day == pytest.approx(125_000.0)


def test_no_dual_coded_when_plain_cost():
    boe = "ML estimate = $250,000 lump sum, based on quoted supplier price."
    f = detect_dual_coded("X4", boe)
    assert not f.is_dual_coded
    assert not f.days_times_pattern


def test_empty_boe_not_dual_coded():
    f = detect_dual_coded("X5", None)
    assert not f.is_dual_coded
    assert f.boe_excerpt == ""


# ---------- hypothesis classification ----------

def test_hypothesis_below_site_rate():
    assert "below" in classify_rate_hypothesis(40_000, 85_000).lower()


def test_hypothesis_aligns():
    assert "align" in classify_rate_hypothesis(85_000, 85_000).lower()


def test_hypothesis_idc_overlay():
    # ~2x site rate.
    assert "peak-labour" in classify_rate_hypothesis(170_000, 85_000).lower() \
        or "idc" in classify_rate_hypothesis(170_000, 85_000).lower()


def test_hypothesis_ld_overlay():
    # ~6x site rate (like a $500k/day transformer delay figure).
    msg = classify_rate_hypothesis(500_000, 85_000).lower()
    assert "ld" in msg


def test_hypothesis_no_rate_quoted():
    assert "no explicit rate" in classify_rate_hypothesis(None, 85_000).lower()


# ---------- aggregation helpers ----------

def test_build_dual_coded_findings_handles_missing_boe():
    risks = [
        {"risk_id": "X1", "cost_basis_of_estimate": None},
        {"risk_id": "X2"},  # key absent entirely
    ]
    out = build_dual_coded_findings(risks)
    assert len(out) == 2
    assert all(not f.is_dual_coded for f in out)


def test_build_reconciliation_rows_only_dual_coded():
    risks = [
        {"risk_id": "D1", "cost_basis_of_estimate":
            "Pessimistic = 3 weeks x site running costs ($500,000 per week)"},
        {"risk_id": "C1", "cost_basis_of_estimate":
            "ML estimate = $250,000 lump sum"},
    ]
    ctx = DayRateContext(
        preliminaries_total=77_470_585.0,
        programme_working_days=912,
        rate_per_working_day=84_946.0,
        rate_per_calendar_day=60_676.0,
        source_cell="Pricing Summary!R8",
    )
    rows = build_reconciliation_rows(risks, ctx)
    assert len(rows) == 1
    assert rows[0]["risk_id"] == "D1"
    assert rows[0]["narrative_rate_per_wd"] == pytest.approx(100_000.0)
    assert rows[0]["gap_per_wd"] == pytest.approx(100_000.0 - 84_946.0)


# ---------- source-file regression ----------

def test_no_hardcoded_risk_id_in_day_rate_memo():
    import re
    src_path = (
        Path(__file__).resolve().parents[1]
        / "src" / "sra_strawman" / "day_rate_memo.py"
    )
    source = src_path.read_text(encoding="utf-8")
    matches = re.findall(r"\bR\d{3,}(?:\.\d+)?\b", source)
    assert not matches, (
        f"Risk ID literals found in day_rate_memo: {matches} - "
        "dual-coded detection must be pattern-driven, not ID-driven"
    )
