"""
Tests for Shared view P-value fix.

When view=Shared, primary P-values should show pure pool costs ($0-$15M),
not TIC + pool ($285M+). Tests verify analysis.py produces correct values
for both Shared and All views.
"""

import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput, GainPainConfig
from src.simulation import MonteCarloEngine
from src.analysis import build_output_table


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run_and_build(view="All", pool_budget=15_000_000.0, n_iter=10_000, seed=42):
    """Run simulation and build output table with given view."""
    risks = [
        RiskInput("R001", "BOP risk", "BOP Contractor", "Binary", "CG01",
                  0.3, 100_000, 200_000, 400_000),
        RiskInput("R002", "Shared risk 1", "Shared", "Binary", "CG02",
                  0.5, 500_000, 2_000_000, 5_000_000),
        RiskInput("R003", "Shared risk 2", "Shared", "Binary", "CG03",
                  0.3, 200_000, 1_000_000, 3_000_000),
    ]
    tic = 285_000_000.0
    config = SimConfig(
        n_iter=n_iter, seed=seed, view=view, tic=tic,
        contingency=30_000_000, pool_budget=pool_budget,
    )
    buckets = [WBSBucket("Test", 100_000_000, -0.05, 0.10, "Triangular")]
    chains = ChainConfig()
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    engine = MonteCarloEngine(config, buckets, chains, risks, corr, seed=seed)
    raw = engine.run()
    output = build_output_table(raw, risks, config)
    lookup = {r[0]: r[1] for r in output}
    return lookup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_shared_view_primary_pvalues_are_pure_l2():
    """Shared view P50 should be pure pool cost (< $50M), not TIC + pool."""
    lookup = _run_and_build(view="Shared")
    assert lookup["p50"] < 50_000_000, \
        f"Shared P50 = ${lookup['p50']/1e6:.1f}M — should be pool cost, not TIC+pool"
    assert lookup["p50"] >= 0, "Shared P50 should be >= 0"


def test_all_view_primary_pvalues_include_tic():
    """All view P50 should include TIC ($285M+)."""
    lookup = _run_and_build(view="All")
    assert lookup["p50"] > 280_000_000, \
        f"All P50 = ${lookup['p50']/1e6:.1f}M — should include TIC ($285M)"


def test_shared_view_adequacy_uses_pool_budget():
    """Shared view with large pool_budget should have adequacy ~ 1.0."""
    lookup = _run_and_build(view="Shared", pool_budget=100_000_000)
    assert lookup["adequacy"] == pytest.approx(1.0, abs=0.01)


def test_shared_view_adequacy_with_small_pool():
    """Shared view with zero pool_budget should have adequacy < 1.0."""
    lookup = _run_and_build(view="Shared", pool_budget=0)
    assert lookup["adequacy"] < 1.0


def test_shared_view_risk_premium_is_pool_p50():
    """Shared view risk_premium should equal P50 (not P50 - TIC)."""
    lookup = _run_and_build(view="Shared")
    assert lookup["risk_premium"] == pytest.approx(lookup["p50"], rel=1e-6)


def test_shared_view_convergence_excludes_tic():
    """Shared view convergence P90 should be < $50M (pool cost, not TIC+)."""
    lookup = _run_and_build(view="Shared")
    conv_key = "conv_1000"
    if conv_key in lookup:
        assert lookup[conv_key] < 50_000_000, \
            f"Shared conv_1000 = ${lookup[conv_key]/1e6:.1f}M — should be pool P90, not TIC+"


def test_shared_view_s_curve_excludes_tic():
    """Shared view sc_total_50 should be < $50M (pool median)."""
    lookup = _run_and_build(view="Shared")
    assert lookup["sc_total_50"] < 50_000_000, \
        f"Shared sc_total_50 = ${lookup['sc_total_50']/1e6:.1f}M — should be pool median"


def test_all_view_unchanged():
    """All view should be completely unchanged (regression check)."""
    lookup = _run_and_build(view="All")
    # P50 includes TIC
    assert lookup["p50"] > 280_000_000
    # Risk premium is P50 - TIC
    assert lookup["risk_premium"] == pytest.approx(
        lookup["p50"] - 285_000_000, rel=1e-6)
    # Adequacy is a valid probability
    assert 0 <= lookup["adequacy"] <= 1
    # Convergence includes TIC
    if "conv_1000" in lookup:
        assert lookup["conv_1000"] > 280_000_000
    # S-curve includes TIC
    assert lookup["sc_total_50"] > 280_000_000
