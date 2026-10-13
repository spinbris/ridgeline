"""SRA-02 S-E P-E2 - the Python comparator function.

Gates ``src.sra.schedule_cross_check.compute_schedule_comparators``: the nil case,
the arithmetic against an independent implementation, the register-constant Mode
that D-12 ruled, and the key contract with the reader.

The discipline this file follows, borrowed from ``test_sra02_sb_schedule_surface``:
the expected EMV-days arithmetic is not restated here as a literal. It is taken from
``src.sra_strawman.strawman_builder._compute_expected_row_outputs``, a separately
written implementation of the same PERT mean, so a drift on either side reds instead
of two copies of one formula agreeing with each other.
"""
from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

from types import SimpleNamespace

import pandas as pd
import pytest

from src.sra.schedule_cross_check import (
    COMPARATOR_KEYS,
    compute_schedule_comparators,
)
from src.sra.strawman_reader import _COMPARATOR_LABELS
from src.sra_strawman.strawman_builder import _compute_expected_row_outputs

#: A grid that is deliberately NOT the {1.0, 0.5, 0.0} default - if the function
#: ignored its parameter and reached for a constant, these values would not appear.
GRID = {"Series": 0.9, "Hybrid": 0.4, "Parallel": 0.1}
DAY_RATE = 12345.0

SCOPE_COLUMNS = ["risk_id", "time_impact", "mode_aggregated",
                 "probability", "opt_days", "ml_days", "pess_days"]


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=SCOPE_COLUMNS)


def _row(rid, mode, p, opt, ml, pess, time_impact="Yes") -> dict:
    return {"risk_id": rid, "time_impact": time_impact, "mode_aggregated": mode,
            "probability": p, "opt_days": opt, "ml_days": ml, "pess_days": pess}


def _builder_emv_pert_days(p, opt, ml, pess) -> float:
    """The same quantity, from the strawman builder's own implementation."""
    out = _compute_expected_row_outputs(
        risk={"probability": p},
        mapping=SimpleNamespace(mode="Series", min_total_float_days=0.0),
        dur=SimpleNamespace(opt_days=opt, ml_days=ml, pess_days=pess),
        day_rate=1.0,
        reconciliation="A",
    )
    return out["emv_pert_days"]


# ---------------------------------------------------------------------------
# 1. The key contract - tied to the reader rather than restated
# ---------------------------------------------------------------------------

def test_comparator_keys_match_the_reader_contract():
    """The four keys are the API between this function and
    ``get_strawman_calibration_target``. Neither side imports the other's literals,
    so this is where a rename on either side reds."""
    assert COMPARATOR_KEYS == tuple(_COMPARATOR_LABELS)


# ---------------------------------------------------------------------------
# 2. The nil case - SRA-01:71 analogue
# ---------------------------------------------------------------------------

def test_empty_frame_gives_zeros_not_none():
    out = compute_schedule_comparators(_frame([]), GRID, DAY_RATE)
    assert set(out) == set(COMPARATOR_KEYS)
    assert all(out[k] == 0.0 for k in COMPARATOR_KEYS), out


def test_frame_with_no_time_yes_rows_gives_zeros():
    """A cost-only register: rows exist, none of them schedule. Distinct from the
    empty frame - this one exercises the filter, not the empty loop."""
    df = _frame([_row("R1", "Series", 0.5, 1, 2, 3, time_impact="No")])
    out = compute_schedule_comparators(df, GRID, DAY_RATE)
    assert all(out[k] == 0.0 for k in COMPARATOR_KEYS), out


# ---------------------------------------------------------------------------
# 3. The arithmetic, against the builder's independent implementation
# ---------------------------------------------------------------------------

def test_single_row_comparator_1_matches_the_builder_pert_arithmetic():
    p, opt, ml, pess = 0.45, 5.0, 12.0, 24.0
    df = _frame([_row("R1", "Series", p, opt, ml, pess)])
    out = compute_schedule_comparators(df, GRID, DAY_RATE)
    assert out["comparator_1_emv_days_pert"] == pytest.approx(
        _builder_emv_pert_days(p, opt, ml, pess), rel=1e-15
    )


def test_comparator_2_applies_the_registers_constant_mode(     ):
    """D-12: Comparator 2 on the consolidated path is the register's constant-Mode
    sum. One row per mode, so each multiplier is exercised separately."""
    p, opt, ml, pess = 0.5, 3.0, 7.0, 16.0
    emv = _builder_emv_pert_days(p, opt, ml, pess)
    for mode, mult in GRID.items():
        df = _frame([_row("R1", mode, p, opt, ml, pess)])
        out = compute_schedule_comparators(df, GRID, DAY_RATE)
        assert out["comparator_2_finish_delay_days_pert"] == pytest.approx(
            emv * mult, rel=1e-15
        ), mode


def test_comparator_2_uses_the_supplied_grid_not_a_constant():
    """The positive control for the D-12 wiring: the same row under two different
    grids must give two different Comparator 2 values. A function that reached for
    ``TEST_MODE_MULTIPLIERS`` instead of its parameter passes every test above and fails
    this one."""
    df = _frame([_row("R1", "Hybrid", 0.5, 3.0, 7.0, 16.0)])
    a = compute_schedule_comparators(df, {"Hybrid": 0.4}, DAY_RATE)
    b = compute_schedule_comparators(df, {"Hybrid": 0.8}, DAY_RATE)
    assert b["comparator_2_finish_delay_days_pert"] == pytest.approx(
        2.0 * a["comparator_2_finish_delay_days_pert"], rel=1e-15
    )


def test_totals_sum_over_rows_and_comparator_1_ignores_mode():
    """Comparator 1 must be Mode-blind: three rows differing only in Mode contribute
    identically to it, and differently to Comparator 2."""
    p, opt, ml, pess = 0.4, 2.0, 6.0, 14.0
    df = _frame([_row(f"R{i}", mode, p, opt, ml, pess)
                 for i, mode in enumerate(GRID)])
    out = compute_schedule_comparators(df, GRID, DAY_RATE)
    emv = _builder_emv_pert_days(p, opt, ml, pess)
    assert out["comparator_1_emv_days_pert"] == pytest.approx(3 * emv, rel=1e-15)
    assert out["comparator_2_finish_delay_days_pert"] == pytest.approx(
        emv * sum(GRID.values()), rel=1e-15
    )


# ---------------------------------------------------------------------------
# 4. Dollars, and the Excel-mirroring edge cases
# ---------------------------------------------------------------------------

def test_dollars_are_days_times_the_day_rate():
    df = _frame([_row("R1", "Series", 0.45, 5.0, 12.0, 24.0)])
    out = compute_schedule_comparators(df, GRID, DAY_RATE)
    assert out["comparator_1_emv_dollars"] == pytest.approx(
        out["comparator_1_emv_days_pert"] * DAY_RATE, rel=1e-15)
    assert out["comparator_2_finish_delay_dollars"] == pytest.approx(
        out["comparator_2_finish_delay_days_pert"] * DAY_RATE, rel=1e-15)


@pytest.mark.parametrize("mode, label", [
    (None, "None"),
    (float("nan"), "NaN"),
    ("", "empty string"),
    ("   ", "whitespace only"),
    ("Diagonal", "absent from the grid"),
    ("Serie", "near-miss of a defined mode"),
])
def test_unresolvable_mode_on_a_time_yes_row_raises(mode, label):
    """D-14: the Python twin must NOT mirror Excel's ``IFERROR(...,0)`` here.

    Zero in a multiplicative slot annihilates, and because the Excel side zeroes
    too, the two runtimes agree while both being wrong - which blinds the
    reconciliation gate to the whole METHRANGE-01 / F-C class. This is the same
    fail-loud principle ``test_missing_column_raises_rather_than_returning_a_wrong_zero``
    already applies to a missing *column*, applied one level finer to a missing
    *value*: both would otherwise return a Comparator 2 indistinguishable from a
    legitimate all-Parallel register.

    The error must name the risk ID and the offending value, because on a real
    register the whole point is to say which row to go and fix.
    """
    df = _frame([_row("R-BAD", mode, 0.5, 3.0, 7.0, 16.0)])
    with pytest.raises(ValueError, match="R-BAD") as excinfo:
        compute_schedule_comparators(df, GRID, DAY_RATE)
    assert "mode_aggregated" in str(excinfo.value).lower() or "mode" in str(excinfo.value).lower(), (
        f"{label}: error must name the field")


@pytest.mark.parametrize("variant", ["series", "SERIES", "SeRiEs", " Series ", "hybrid"])
def test_case_and_whitespace_variants_of_a_defined_mode_resolve(variant):
    """Excel's ``MATCH`` on text is case-insensitive, so ``hybrid`` finds ``Hybrid``.
    Python must match that or the two runtimes disagree on a register a human would
    call correct - and the raise above must not fire on a mode that IS defined.

    Surrounding whitespace is stripped on the Python side only (Excel's MATCH does
    not trim); that asymmetry is F-6 and is a NOTE, not this fix. Stripping is the
    pre-existing behaviour and is kept.
    """
    expected = GRID["Series"] if variant.strip().lower() == "series" else GRID["Hybrid"]
    df = _frame([_row("R1", variant, 0.5, 3.0, 7.0, 16.0)])
    out = compute_schedule_comparators(df, GRID, DAY_RATE)
    emv = _builder_emv_pert_days(0.5, 3.0, 7.0, 16.0)
    assert out["comparator_2_finish_delay_days_pert"] == pytest.approx(
        emv * expected, rel=1e-15), variant


def test_a_nil_register_never_reaches_the_mode_lookup():
    """The raise must be unreachable when there is nothing to simulate. The Time=Yes
    filter short-circuits before the Mode lookup, so an all-Time=No register with
    unresolvable Modes still returns zeros rather than raising - a cost-only register
    is not a malformed one."""
    df = _frame([
        _row("R1", None, 0.5, 3.0, 7.0, 16.0, time_impact="No"),
        _row("R2", "Diagonal", 0.5, 3.0, 7.0, 16.0, time_impact="No"),
    ])
    out = compute_schedule_comparators(df, GRID, DAY_RATE)
    assert all(out[k] == 0.0 for k in COMPARATOR_KEYS), out


def test_blank_three_point_cells_contribute_zero_not_nan():
    """A half-filled workshop row. Excel treats the blanks as zero; so must this."""
    df = _frame([_row("R1", "Series", None, None, None, None)])
    out = compute_schedule_comparators(df, GRID, DAY_RATE)
    assert all(out[k] == 0.0 for k in COMPARATOR_KEYS), out


def test_missing_column_raises_rather_than_returning_a_wrong_zero():
    """Fail loud. A frame that lost ``mode_aggregated`` would otherwise return a
    Comparator 2 of zero, which is indistinguishable from an all-Parallel register."""
    df = _frame([_row("R1", "Series", 0.5, 3.0, 7.0, 16.0)]).drop(
        columns=["mode_aggregated"])
    with pytest.raises(KeyError, match="mode_aggregated"):
        compute_schedule_comparators(df, GRID, DAY_RATE)
