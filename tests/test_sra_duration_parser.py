"""Unit tests for src.sra_strawman.duration_parser.

Covers:
- Week / day phrase extraction
- Event-count * per-event duration patterns
- Negation phrases (no delays / no change)
- Month phrase -> DUMMY (brief §3.4 AMBIGUOUS)
- Ordering anomalies -> DERIVED_LOW_CONFIDENCE
- Empty / missing scenarios -> DUMMY
"""

from __future__ import annotations

from src.sra_strawman.duration_parser import (
    TAG_CONSEQUENCE,
    TAG_DERIVED_LOW,
    TAG_DUMMY,
    derive_for_risk,
    extract_duration_three_point,
)


def test_clean_week_slippage_three_point():
    """R017.1 pattern: 2 / 8 / 16 week slippage."""
    r = extract_duration_three_point(
        "Project will experience a 2 week slippage to the Schedule",
        "Project will experience a 8 week slippage to the Schedule",
        "Project will experience a 16 week slippage to the Schedule",
    )
    assert r.opt_days == 10
    assert r.ml_days == 40
    assert r.pess_days == 80
    assert r.tag == TAG_CONSEQUENCE


def test_days_three_point():
    r = extract_duration_three_point(
        "3 days less", "3 days per annum above", "6 days per annum above"
    )
    assert r.opt_days == 3
    assert r.ml_days == 3
    assert r.pess_days == 6
    # Opt==ML is fine, but Opt <= ML <= Pess holds -> CONSEQUENCE.
    assert r.tag == TAG_CONSEQUENCE


def test_delayed_by_weeks_variant():
    """R016.2 pattern: 'delayed by 4 weeks' / 'delayed by 12 weeks'."""
    r = extract_duration_three_point(
        "no disruptions to Plant deliveries",
        "One (1) disruption - 4 x GTG's are delayed by 4 weeks",
        "One (1) disruption - 4 x GTG's are delayed by 12 weeks",
    )
    assert r.opt_days == 0
    assert r.ml_days == 20
    assert r.pess_days == 60
    assert r.tag == TAG_CONSEQUENCE


def test_event_count_times_per_event():
    """R016.1 pattern: 'Two (2) events ... 4 days each event'."""
    r = extract_duration_three_point(
        "Project will not experience any extreme weather events",
        "Project will experience Two (2) extreme weather event and flooding closing the site for 4 days each event",
        "Project will experience Three (3) extreme weather event and flooding closing the site for 4 days each event",
    )
    # 2 events * 4 days = 8; 3 events * 4 days = 12.
    assert r.opt_days == 0
    assert r.ml_days == 8
    assert r.pess_days == 12
    assert r.tag == TAG_CONSEQUENCE


def test_negation_detected_as_zero():
    r = extract_duration_three_point(
        "No delays to schedule", "3 weeks delay to schedule", "6 weeks delay to schedule"
    )
    assert r.opt_days == 0
    assert r.ml_days == 15
    assert r.pess_days == 30
    assert r.tag == TAG_CONSEQUENCE


def test_month_phrase_flags_dummy():
    """Brief §3.4: 'over 18 months (40% increase) -> AMBIGUOUS / DUMMY'."""
    r = extract_duration_three_point(
        "", "", "18 months increase in completion"
    )
    assert (r.opt_days, r.ml_days, r.pess_days) == (0, 0, 0)
    assert r.tag == TAG_DUMMY


def test_no_duration_phrase_anywhere_is_dummy():
    r = extract_duration_three_point(
        "+5% commodity price", "+10% commodity price", "+20% commodity price"
    )
    assert (r.opt_days, r.ml_days, r.pess_days) == (0, 0, 0)
    assert r.tag == TAG_DUMMY


def test_partial_three_point_fills_with_heuristic():
    """If only one scenario has a duration, fill gaps with half/double PERT."""
    r = extract_duration_three_point("", "5 days", "")
    assert r.ml_days == 5
    assert r.opt_days == 2.5  # half
    assert r.pess_days == 10  # double
    assert r.tag == TAG_DERIVED_LOW


def test_ordering_anomaly_flags_derived_low():
    """Opt > ML reverses the expected order -> DERIVED_LOW_CONFIDENCE."""
    r = extract_duration_three_point(
        "10 day slippage", "3 day slippage", "20 day slippage"
    )
    assert r.opt_days == 10
    assert r.ml_days == 3
    assert r.pess_days == 20
    assert r.tag == TAG_DERIVED_LOW


def test_empty_input_is_dummy():
    r = extract_duration_three_point(None, None, None)
    assert r.tag == TAG_DUMMY
    r2 = extract_duration_three_point("", "", "")
    assert r2.tag == TAG_DUMMY


def test_derive_for_risk_wrapper():
    risk = {
        "optimistic_scenario": "2 week slippage",
        "likely_scenario": "8 week slippage",
        "pessimistic_scenario": "16 week slippage",
    }
    r = derive_for_risk(risk)
    assert r.opt_days == 10
    assert r.ml_days == 40
    assert r.pess_days == 80
    assert r.tag == TAG_CONSEQUENCE
