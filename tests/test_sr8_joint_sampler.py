"""SR8 - joint_sampler tests.

SNAPSHOTCUT-01 (Director, 11/10/2026): the one test against the retired register and the V8
strawman, which no machine here holds, is retired.
"""

from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import os
from dataclasses import dataclass
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.integrated.joint_sampler import sample_iteration, sample_joint_risk


@dataclass
class _Risk:
    risk_id: str
    distribution: str
    probability: float
    opt_cost: float = 0.0
    ml_cost: float = 0.0
    pess_cost: float = 0.0
    correlation_group: str = "CG13"


def _make_dual_scope() -> pd.DataFrame:
    """Minimal Risk_Scope DataFrame with one dual-coded risk for testing."""
    return pd.DataFrame([
        {
            "risk_id": "DUAL", "time_impact": "Yes",
            "mode_aggregated": "Series",
            "opt_days": 0.0, "ml_days": 10.0, "pess_days": 20.0,
        }
    ])


def test_sample_joint_risk_returns_correct_keys():
    rng = np.random.default_rng(42)
    risk = _Risk("X", "PERT", 1.0, 0, 100, 200)
    out = sample_joint_risk(rng, risk, is_dual_coded=True, mode_multiplier=1.0,
                            u_fire=0.0, opt_d=0, ml_d=10, pess_d=20)
    expected_keys = {"fired", "u_fire", "u_cost_schedule", "u_cost_only",
                     "cost_dollars", "schedule_days_pre_mode", "schedule_days"}
    assert expected_keys.issubset(set(out.keys()))


def test_sample_joint_risk_fired_false_returns_zero_contributions():
    rng = np.random.default_rng(42)
    risk = _Risk("X", "PERT", 0.1, 0, 100, 200)
    # u_fire = 0.5 > probability 0.1 => not fired
    out = sample_joint_risk(rng, risk, is_dual_coded=True, mode_multiplier=1.0,
                            u_fire=0.5, opt_d=0, ml_d=10, pess_d=20)
    assert out["fired"] is False
    assert out["cost_dollars"] == 0.0
    assert out["schedule_days_pre_mode"] == 0.0
    assert out["schedule_days"] == 0.0


def test_sample_joint_risk_dual_coded_uses_shared_uniform():
    """Inject a controlled rng; verify cost and schedule both stem from the
    same severity uniform.
    """
    risk = _Risk("X", "PERT", 1.0, 0, 100, 200)
    # When fired, the first rng.random() draw becomes u_cost_schedule
    rng_a = np.random.default_rng(123)
    rng_b = np.random.default_rng(123)
    out_a = sample_joint_risk(rng_a, risk, is_dual_coded=True, mode_multiplier=1.0,
                              u_fire=0.0, opt_d=0, ml_d=10, pess_d=20)
    out_b = sample_joint_risk(rng_b, risk, is_dual_coded=True, mode_multiplier=1.0,
                              u_fire=0.0, opt_d=0, ml_d=10, pess_d=20)
    # Same rng seed => same u_cost_schedule => same cost AND same schedule_days_pre_mode
    assert out_a["u_cost_schedule"] == out_b["u_cost_schedule"]
    assert out_a["cost_dollars"] == out_b["cost_dollars"]
    assert out_a["schedule_days_pre_mode"] == out_b["schedule_days_pre_mode"]
    assert out_a["fired"] is True
    # Both contributions non-zero (sanity)
    assert out_a["cost_dollars"] > 0
    assert out_a["schedule_days_pre_mode"] > 0


def test_sample_joint_risk_cost_only_no_schedule_contribution():
    rng = np.random.default_rng(42)
    risk = _Risk("X", "PERT", 1.0, 0, 100, 200)
    out = sample_joint_risk(rng, risk, is_dual_coded=False, mode_multiplier=0.0,
                            u_fire=0.0)
    assert out["fired"] is True
    assert out["cost_dollars"] > 0
    assert out["schedule_days_pre_mode"] == 0.0
    assert out["schedule_days"] == 0.0
    assert out["u_cost_schedule"] is None
    assert out["u_cost_only"] is not None


def test_sample_joint_risk_lognormal_dispatched_correctly():
    """R013-shape risk: distribution=Lognormal. Cost sampler must NOT be PERT."""
    rng = np.random.default_rng(42)
    risk_lognormal = _Risk("X", "Lognormal", 1.0, 80_000, 225_000, 2_827_881)
    risk_pert = _Risk("X", "PERT", 1.0, 80_000, 225_000, 2_827_881)
    # Same u, different distributions => different cost
    rng_a = np.random.default_rng(7)
    rng_b = np.random.default_rng(7)
    out_lognormal = sample_joint_risk(rng_a, risk_lognormal, is_dual_coded=True,
                                       mode_multiplier=1.0, u_fire=0.0,
                                       opt_d=0, ml_d=10, pess_d=20)
    out_pert = sample_joint_risk(rng_b, risk_pert, is_dual_coded=True,
                                  mode_multiplier=1.0, u_fire=0.0,
                                  opt_d=0, ml_d=10, pess_d=20)
    # Same shared u => same schedule, but different cost because of distribution
    assert out_lognormal["schedule_days_pre_mode"] == out_pert["schedule_days_pre_mode"]
    assert out_lognormal["cost_dollars"] != out_pert["cost_dollars"]


def test_sample_joint_risk_triangular_dispatched_correctly():
    rng = np.random.default_rng(42)
    risk_tri = _Risk("X", "Triangular", 1.0, -2_000_000, 4_000_000, 9_000_000)
    out = sample_joint_risk(rng, risk_tri, is_dual_coded=True, mode_multiplier=1.0,
                            u_fire=0.0, opt_d=0, ml_d=10, pess_d=20)
    assert out["fired"] is True
    assert -2_000_000 <= out["cost_dollars"] <= 9_000_000


def test_sample_joint_risk_does_not_apply_chain_logic():
    """sample_joint_risk has no chain_config parameter; chains are post-pass."""
    import inspect
    sig = inspect.signature(sample_joint_risk)
    params = set(sig.parameters.keys())
    # Verify no chain-related parameters in the signature
    for p in params:
        assert "chain" not in p.lower(), (
            f"sample_joint_risk should have no chain parameters; found {p!r}"
        )


def test_sample_iteration_aggregates_correctly():
    rng = np.random.default_rng(42)
    risks = [
        _Risk("DUAL", "PERT", 1.0, 0, 1000, 2000, "CG01"),
        _Risk("CO1", "PERT", 1.0, 0, 500, 1000, "CG02"),
    ]
    risk_scope = _make_dual_scope()
    fire_row = np.array([0.0, 0.0])
    out = sample_iteration(rng, risks, risk_scope, fire_row, mode_multipliers=TEST_MODE_MULTIPLIERS)
    # both fire, total_cost is sum of per-risk
    assert out["per_risk_fired"]["DUAL"] is True
    assert out["per_risk_fired"]["CO1"] is True
    assert out["total_cost_dollars"] == out["per_risk_cost"]["DUAL"] + out["per_risk_cost"]["CO1"]
    assert out["total_schedule_days"] == out["per_risk_schedule"]["DUAL"]


def test_sample_iteration_seed_determinism():
    risks = [
        _Risk("DUAL", "PERT", 1.0, 0, 1000, 2000, "CG01"),
        _Risk("CO1", "PERT", 1.0, 0, 500, 1000, "CG02"),
    ]
    risk_scope = _make_dual_scope()
    fire_row = np.array([0.0, 0.0])
    a = sample_iteration(np.random.default_rng(99), risks, risk_scope, fire_row, mode_multipliers=TEST_MODE_MULTIPLIERS)
    b = sample_iteration(np.random.default_rng(99), risks, risk_scope, fire_row, mode_multipliers=TEST_MODE_MULTIPLIERS)
    assert a["total_cost_dollars"] == b["total_cost_dollars"]
    assert a["total_schedule_days"] == b["total_schedule_days"]
