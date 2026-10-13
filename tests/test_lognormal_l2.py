"""
Tests for lognormal_cost_from_uniform() — Layer 2 lognormal distribution.

Validates:
- Median property (u=0.5 → ML)
- P10/P90 anchoring (Opt/Pess)
- Right-tail extension beyond Pess
- All-positive output
- Degenerate cases
- sample_cost() dispatch
- Regression: existing distributions unchanged
- Full simulation integration
"""

import numpy as np
import pytest

from src.distributions import (
    lognormal_cost_from_uniform,
    sample_cost,
    triangular_from_uniform,
)


# ---------------------------------------------------------------------------
# Core lognormal properties
# ---------------------------------------------------------------------------

def test_median_near_ml():
    """u=0.5 (median) should produce values equal to ML."""
    u = np.full(100_000, 0.5)
    result = lognormal_cost_from_uniform(u, 1e6, 4e6, 15e6)
    # All values at u=0.5 should be exactly ML (median of lognormal)
    np.testing.assert_allclose(result, 4e6, rtol=1e-6)


def test_p10_near_opt():
    """u=0.10 should produce values approximately near Opt."""
    u = np.full(100_000, 0.10)
    result = lognormal_cost_from_uniform(u, 1e6, 4e6, 15e6)
    mean_val = np.mean(result)
    assert mean_val == pytest.approx(1e6, rel=0.15), \
        f"P10 value {mean_val:.0f} not near Opt={1e6:.0f}"


def test_p90_near_pess():
    """u=0.90 should produce values approximately near Pess."""
    u = np.full(100_000, 0.90)
    result = lognormal_cost_from_uniform(u, 1e6, 4e6, 15e6)
    mean_val = np.mean(result)
    assert mean_val == pytest.approx(15e6, rel=0.15), \
        f"P90 value {mean_val:.0f} not near Pess={15e6:.0f}"


def test_tail_extends_beyond_pess():
    """P95 and P99 should exceed Pess — the key lognormal property."""
    u = np.array([0.95, 0.99])
    result = lognormal_cost_from_uniform(u, 1e6, 4e6, 15e6)
    assert result[0] > 15e6, f"P95 ({result[0]:.0f}) should exceed Pess (15M)"
    assert result[1] > result[0], f"P99 ({result[1]:.0f}) should exceed P95 ({result[0]:.0f})"


def test_all_positive():
    """Lognormal should never produce negative values."""
    rng = np.random.default_rng(42)
    u = rng.uniform(size=100_000)
    result = lognormal_cost_from_uniform(u, 1e6, 4e6, 15e6)
    assert np.all(result > 0), "Lognormal produced negative values"


def test_degenerate_zero_ml():
    """ml=0 should return all zeros."""
    u = np.array([0.1, 0.5, 0.9])
    result = lognormal_cost_from_uniform(u, 1e6, 0, 15e6)
    np.testing.assert_array_equal(result, 0.0)


# ---------------------------------------------------------------------------
# sample_cost() dispatch
# ---------------------------------------------------------------------------

def test_sample_cost_dispatches_lognormal():
    """sample_cost with 'Lognormal' should match lognormal_cost_from_uniform."""
    u = np.linspace(0.01, 0.99, 1000)
    direct = lognormal_cost_from_uniform(u, 1e6, 4e6, 15e6)
    dispatched = sample_cost(u, 1e6, 4e6, 15e6, "Lognormal")
    np.testing.assert_array_equal(direct, dispatched)


def test_sample_cost_case_insensitive():
    """'lognormal', 'Lognormal', 'LOGNORMAL' all dispatch correctly."""
    u = np.array([0.3, 0.5, 0.7])
    expected = lognormal_cost_from_uniform(u, 1e6, 4e6, 15e6)
    for name in ["lognormal", "Lognormal", "LOGNORMAL", " Lognormal "]:
        result = sample_cost(u, 1e6, 4e6, 15e6, name)
        np.testing.assert_array_equal(result, expected, err_msg=f"Failed for '{name}'")


# ---------------------------------------------------------------------------
# Regression: existing distributions unchanged
# ---------------------------------------------------------------------------

def test_triangular_unchanged():
    """Triangular sampling must not be affected by new Lognormal branch."""
    u = np.linspace(0.01, 0.99, 1000)
    result = sample_cost(u, 100_000, 200_000, 400_000, "Triangular")
    direct = triangular_from_uniform(u, 100_000, 200_000, 400_000)
    np.testing.assert_array_equal(result, direct)


def test_binary_unchanged():
    """Binary sampling must not be affected by new Lognormal branch."""
    u = np.linspace(0.01, 0.99, 10)
    result = sample_cost(u, 100_000, 200_000, 400_000, "Binary")
    np.testing.assert_array_equal(result, 200_000)


# ---------------------------------------------------------------------------
# Full simulation integration
# ---------------------------------------------------------------------------

def test_full_simulation_with_lognormal_risk():
    """Simulation with a Lognormal risk produces correct shape and skew."""
    from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput
    from src.simulation import MonteCarloEngine

    risks = [
        RiskInput("R100", "Normal risk", "BOP Contractor", "Triangular", "CG01",
                  0.5, 100_000, 200_000, 400_000),
        RiskInput("R101", "Lognormal FM risk", "Shared", "Lognormal", "CG02",
                  0.3, 1_000_000, 4_000_000, 15_000_000),
    ]
    config = SimConfig(n_iter=50_000, seed=42, tic=100_000_000)
    buckets = [WBSBucket("Test", 50_000_000, -0.05, 0.10, "Triangular")]
    chains = ChainConfig()
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    engine = MonteCarloEngine(config, buckets, chains, risks, corr, seed=42)
    raw = engine.run()

    assert raw.ev_costs.shape == (50_000, 2)

    # Lognormal risk (index 1): when fired, P90 > ML (right-skewed)
    ln_costs = raw.ev_costs[:, 1]
    fired = ln_costs[ln_costs > 0]
    if len(fired) > 100:
        p50 = np.percentile(fired, 50)
        p90 = np.percentile(fired, 90)
        assert p90 > 4_000_000, f"Fired P90 ({p90:.0f}) should exceed ML (4M)"
        assert p50 == pytest.approx(4_000_000, rel=0.25), \
            f"Fired P50 ({p50:.0f}) should be near ML (4M)"
