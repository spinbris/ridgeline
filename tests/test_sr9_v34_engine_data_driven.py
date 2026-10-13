"""SR9 v3.4 - engine data-driven cleanup tests.

Asserts that:
  - EXPECTED_TIME_YES_RISK_IDS is no longer importable from sra_simulation
    (the engine constant has been retired; the strawman is the source of
    truth for which risks simulate).
  - assert_strawman_shape raises with actionable messages on missing or
    mismatched Expected_Time_Yes_Count.
  - build_counterfactual_scenarios derives the scenario list from data
    (4 base scenarios + N flip-to-Series scenarios for N simulating risks).

SNAPSHOTCUT-01 (Director, 11/10/2026): the five tests against the live V8 strawman, which no
machine here holds, are retired, and with them the reference to a frozen shape fixture the tree no longer carries
(SKIPDEAD-01).
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.sra._pre_flight import assert_strawman_shape
from src.sra.sra_simulation import (
    BASE_COUNTERFACTUAL_SCENARIOS,
    build_counterfactual_scenarios,
)


# ---------------------------------------------------------------------------
# Engine constant retirement
# ---------------------------------------------------------------------------

def test_expected_time_yes_risk_ids_no_longer_importable():
    """SR9 v3.4: the engine constant has been retired. Importing it must
    fail with ImportError. The strawman is the source of truth.
    """
    with pytest.raises(ImportError):
        from src.sra.sra_simulation import EXPECTED_TIME_YES_RISK_IDS  # noqa: F401


# ---------------------------------------------------------------------------
# assert_strawman_shape: pre-flight contract
# ---------------------------------------------------------------------------

def _synthetic_risk_scope(n_yes: int) -> pd.DataFrame:
    """Build a minimal risk_scope_df with n_yes Time_Impact=Yes rows."""
    rows = []
    for i in range(n_yes):
        rows.append({"risk_id": f"R{i:03d}", "time_impact": "Yes"})
    rows.append({"risk_id": "R999", "time_impact": "No"})
    return pd.DataFrame(rows)


def test_assert_strawman_shape_passes_when_count_matches():
    df = _synthetic_risk_scope(n_yes=8)
    assert_strawman_shape(df, expected_count=8)  # no exception


def test_assert_strawman_shape_raises_when_expected_count_is_none():
    df = _synthetic_risk_scope(n_yes=8)
    with pytest.raises(RuntimeError, match="Expected_Time_Yes_Count"):
        assert_strawman_shape(df, expected_count=None)


def test_assert_strawman_shape_raises_actionable_message_with_actual_count():
    """Missing-declaration error must suggest the actual count to add."""
    df = _synthetic_risk_scope(n_yes=12)
    with pytest.raises(RuntimeError, match="Value=12"):
        assert_strawman_shape(df, expected_count=None)


def test_assert_strawman_shape_raises_when_count_mismatches():
    df = _synthetic_risk_scope(n_yes=8)
    with pytest.raises(RuntimeError, match="(?i)strawman shape mismatch"):
        assert_strawman_shape(df, expected_count=10)


def test_assert_strawman_shape_mismatch_lists_actual_ids():
    df = _synthetic_risk_scope(n_yes=3)
    with pytest.raises(RuntimeError) as excinfo:
        assert_strawman_shape(df, expected_count=8)
    msg = str(excinfo.value)
    assert "R000" in msg and "R001" in msg and "R002" in msg


def test_assert_strawman_shape_raises_on_missing_time_impact_column():
    df = pd.DataFrame([{"risk_id": "R001"}])
    with pytest.raises(RuntimeError, match="time_impact"):
        assert_strawman_shape(df, expected_count=1)


# ---------------------------------------------------------------------------
# build_counterfactual_scenarios: data-driven scenario list
# ---------------------------------------------------------------------------

def test_build_counterfactual_scenarios_returns_4_plus_n():
    sim_ids = ["R001", "R002", "R003"]
    scenarios = build_counterfactual_scenarios(sim_ids)
    assert len(scenarios) == len(BASE_COUNTERFACTUAL_SCENARIOS) + len(sim_ids)


def test_build_counterfactual_scenarios_flip_ids_consecutive():
    # Beta-15 Item 3: BASE_COUNTERFACTUAL_SCENARIOS expanded to 5 entries
    # (added All Parallel as scenario 5). Flip-to-Series IDs now start
    # at 6 and run consecutively.
    sim_ids = ["R013", "R015.1", "R016.1"]
    scenarios = build_counterfactual_scenarios(sim_ids)
    flip_section = scenarios[len(BASE_COUNTERFACTUAL_SCENARIOS):]
    assert flip_section == [
        (6, "R013 -> Series"),
        (7, "R015.1 -> Series"),
        (8, "R016.1 -> Series"),
    ]
