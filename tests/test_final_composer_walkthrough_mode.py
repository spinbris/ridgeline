"""Beta-19b item 4 — single-iteration walkthrough Mode source unit tests.

Locks the contract:
- run_single_scenario_transparency reads Mode from the strawman's
  `mode_aggregated` column by default (engine alignment).
- contribution_days = drawn_duration × mode_multiplier for fired risks.
- TOTAL row's contribution equals the sum of per-row contributions.
- mode_override kwarg still works for callers that need historical
  DUMMY_REALISTIC behaviour.
"""
from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import math
from pathlib import Path

import pandas as pd
import pytest

from src.sra.sra_config import SRAConfig

from tests._fixture_values import FIXTURE_DAY_RATE
from src.sra.sra_simulation import (
    DUMMY_REALISTIC_MODE_OVERRIDE,
    run_single_scenario_transparency,
)


def _make_synthetic_risk_scope(mode_value: str = "Hybrid") -> pd.DataFrame:
    """Two-risk synthetic Risk_Scope for the walkthrough.

    Both risks Time_Impact=Yes with deterministic-ish PERT durations.
    Probability set to 1.0 so the walkthrough always fires both rows
    regardless of seed (avoids flaky tests).
    """
    return pd.DataFrame([
        {
            "risk_id": "R001",
            "time_impact": "Yes",
            "mode_aggregated": mode_value,
            "probability": 1.0,
            "opt_days": 10.0,
            "ml_days": 12.0,
            "pess_days": 20.0,
        },
        {
            "risk_id": "R002",
            "time_impact": "Yes",
            "mode_aggregated": mode_value,
            "probability": 1.0,
            "opt_days": 5.0,
            "ml_days": 8.0,
            "pess_days": 30.0,
        },
    ])


def _make_cfg(strawman_path: Path) -> SRAConfig:
    return SRAConfig(
        register_path=Path("inputs"),
        p6_path=Path("inputs"),
        strawman_path=strawman_path,
        iterations=1,
        random_seed=42,
        day_rate=FIXTURE_DAY_RATE,
    mode_multipliers=TEST_MODE_MULTIPLIERS)


def test_walkthrough_reads_mode_from_strawman_when_no_override(
    tmp_path: Path,
) -> None:
    """Beta-19b item 4: with no mode_override kwarg, Mode column matches
    the strawman's mode_aggregated value verbatim."""
    risk_scope = _make_synthetic_risk_scope(mode_value="Hybrid")
    cfg = _make_cfg(tmp_path / "unused.xlsx")

    df = run_single_scenario_transparency(cfg, risk_scope, seed=7)

    body = df[df["risk_id"] != "TOTAL"]
    assert set(body["mode"]) == {"Hybrid"}
    expected_mult = TEST_MODE_MULTIPLIERS["Hybrid"]
    for mult in body["mode_multiplier"]:
        assert math.isclose(float(mult), expected_mult)


def test_walkthrough_contribution_equals_drawn_times_multiplier(
    tmp_path: Path,
) -> None:
    """contribution_days = drawn_duration × mode_multiplier (when fired)."""
    risk_scope = _make_synthetic_risk_scope(mode_value="Series")
    cfg = _make_cfg(tmp_path / "unused.xlsx")

    df = run_single_scenario_transparency(cfg, risk_scope, seed=11)

    body = df[df["risk_id"] != "TOTAL"]
    for _, row in body.iterrows():
        if row["fired"] == "Yes":
            expected = (
                float(row["drawn_duration_days"]) * float(row["mode_multiplier"])
            )
            assert math.isclose(
                float(row["contribution_days"]), expected, abs_tol=1e-9,
            )
        else:
            assert math.isclose(float(row["contribution_days"]), 0.0)


def test_walkthrough_total_row_sums_to_per_row_contributions(
    tmp_path: Path,
) -> None:
    """The TOTAL row's contribution_days equals the sum of body rows'
    contribution_days values. This is the integrity check the brief calls
    out — the walkthrough must reconcile."""
    risk_scope = _make_synthetic_risk_scope(mode_value="Hybrid")
    cfg = _make_cfg(tmp_path / "unused.xlsx")

    df = run_single_scenario_transparency(cfg, risk_scope, seed=13)

    body = df[df["risk_id"] != "TOTAL"]
    total_row = df[df["risk_id"] == "TOTAL"].iloc[0]
    body_sum = float(body["contribution_days"].sum())
    assert math.isclose(
        float(total_row["contribution_days"]), body_sum, abs_tol=1e-9,
    )


def test_walkthrough_mode_override_still_works(tmp_path: Path) -> None:
    """Legacy callers can still pass mode_override to inject scenario
    overrides (matches the engine's mode_override semantics)."""
    risk_scope = _make_synthetic_risk_scope(mode_value="Hybrid")
    cfg = _make_cfg(tmp_path / "unused.xlsx")

    df = run_single_scenario_transparency(
        cfg, risk_scope, seed=7,
        mode_override={"R001": "Parallel", "R002": "Series"},
    )

    by_id = df.set_index("risk_id")
    assert by_id.loc["R001"]["mode"] == "Parallel"
    assert by_id.loc["R002"]["mode"] == "Series"
    assert math.isclose(
        float(by_id.loc["R001"]["mode_multiplier"]),
        TEST_MODE_MULTIPLIERS["Parallel"],
    )
    assert math.isclose(
        float(by_id.loc["R002"]["mode_multiplier"]),
        TEST_MODE_MULTIPLIERS["Series"],
    )


def test_dummy_realistic_override_still_available_to_callers() -> None:
    """DUMMY_REALISTIC_MODE_OVERRIDE is still importable and is a dict."""
    assert isinstance(DUMMY_REALISTIC_MODE_OVERRIDE, dict)
    # Sanity: at least one R-prefix key.
    assert any(k.startswith("R") for k in DUMMY_REALISTIC_MODE_OVERRIDE)
