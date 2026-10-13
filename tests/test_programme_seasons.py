"""
Tests for programme_seasons parameter.

Validates:
- SimConfig default programme_seasons == 3
- BINOMIAL risks with default recurrence_param use programme_seasons as n
- BINOMIAL risks with explicit recurrence_param are not overridden
- Non-BINOMIAL risks are unaffected by programme_seasons
"""

import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput
from src.simulation import MonteCarloEngine


def _make_engine(risks, programme_seasons=3, n_iter=50_000, seed=42):
    """Helper to create a MonteCarloEngine with minimal setup."""
    config = SimConfig(
        n_iter=n_iter, tic=100_000_000, programme_seasons=programme_seasons,
    )
    buckets = [WBSBucket("Test", 50_000_000, -0.05, 0.10, "Triangular")]
    chains = ChainConfig()
    corr_coefficients = {"CG01": 0.5}
    return MonteCarloEngine(config, buckets, chains, risks, corr_coefficients, seed)


def test_programme_seasons_default():
    """SimConfig() default programme_seasons should be 3."""
    config = SimConfig()
    assert config.programme_seasons == 3


def test_programme_seasons_overrides_binomial_default():
    """BINOMIAL risk with recurrence_param=0 (unset) should use programme_seasons as n."""
    risk = RiskInput(
        risk_id="R999", description="Test seasonal risk",
        owner="BOP Contractor", distribution="Binary",
        correlation_group="CG01", probability=0.3,
        opt_cost=100_000, ml_cost=200_000, pess_cost=300_000,
        recurrence_type="BINOMIAL", recurrence_param=0.0,
    )
    engine = _make_engine([risk], programme_seasons=3, n_iter=50_000, seed=42)
    raw = engine.run()

    # With n=3 and p=0.3, mean occurrences = 0.9 per iteration
    # Mean cost per occurrence ≈ 200k (triangular-ish), so mean total ≈ 180k
    # With n=1 and p=0.3, mean would be ≈ 60k
    # Check that mean is consistent with n=3 (> 100k threshold)
    mean_cost = raw.ev_costs[:, 0].mean()
    # E[cost] = n * p * E[severity] ≈ 3 * 0.3 * 200k = 180k
    assert mean_cost > 100_000, (
        f"Mean cost {mean_cost:.0f} too low — programme_seasons=3 not applied"
    )


def test_programme_seasons_does_not_override_explicit():
    """BINOMIAL risk with explicit recurrence_param=2 should use n=2, not programme_seasons."""
    risk = RiskInput(
        risk_id="R999", description="Test explicit n risk",
        owner="BOP Contractor", distribution="Binary",
        correlation_group="CG01", probability=0.3,
        opt_cost=100_000, ml_cost=200_000, pess_cost=300_000,
        recurrence_type="BINOMIAL", recurrence_param=2.0,
    )
    engine = _make_engine([risk], programme_seasons=5, n_iter=50_000, seed=42)
    raw = engine.run()

    # With n=2 and p=0.3, mean occurrences = 0.6
    # Mean cost ≈ 0.6 * 200k = 120k
    # With n=5, mean would be ≈ 300k
    mean_cost = raw.ev_costs[:, 0].mean()
    # Should be consistent with n=2 (< 200k), not n=5
    assert mean_cost < 200_000, (
        f"Mean cost {mean_cost:.0f} too high — explicit n=2 was overridden by programme_seasons=5"
    )


def test_non_binomial_unaffected():
    """Standard Binary risk should be unaffected by programme_seasons."""
    risk = RiskInput(
        risk_id="R999", description="Test standard risk",
        owner="BOP Contractor", distribution="Binary",
        correlation_group="CG01", probability=0.3,
        opt_cost=100_000, ml_cost=200_000, pess_cost=300_000,
        recurrence_type="",  # standard Bernoulli
    )
    # Run with two different programme_seasons values
    engine_a = _make_engine([risk], programme_seasons=1, n_iter=50_000, seed=42)
    raw_a = engine_a.run()
    engine_b = _make_engine([risk], programme_seasons=10, n_iter=50_000, seed=42)
    raw_b = engine_b.run()

    # Results should be identical (same seed, same non-BINOMIAL logic)
    np.testing.assert_array_equal(raw_a.ev_costs, raw_b.ev_costs)
