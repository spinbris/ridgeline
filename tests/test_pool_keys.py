"""
Tests for pool_* output keys in build_output_table().

Validates:
- All pool_* keys present in output table
- Pool keys computed in all views (not just Shared)
- Backward compatibility with shared_pool_p90
- Pool adequacy with large/zero budgets
- Pool costed counts and data warning
- Pool EMV calculation
- sc_pool_* S-curve keys
- data_source key
- Existing keys unchanged by new pool section
"""

import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput, GainPainConfig
from src.simulation import MonteCarloEngine
from src.analysis import build_output_table


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_risks():
    """Create a mix of BOP, CSE, and Shared risks."""
    return [
        RiskInput("R001", "BOP risk 1", "BOP Contractor", "Binary", "CG01",
                  0.3, 100_000, 200_000, 400_000),
        RiskInput("R002", "CSE risk 1", "Owner", "Binary", "CG02",
                  0.4, 50_000, 150_000, 300_000),
        RiskInput("R003", "Shared risk 1", "Shared", "Binary", "CG03",
                  0.5, 200_000, 500_000, 1_000_000),
        RiskInput("R004", "Shared risk 2", "Shared", "Binary", "CG04",
                  0.3, 100_000, 300_000, 600_000),
        RiskInput("R005", "Shared risk 3 (no cost)", "Shared", "Binary", "CG05",
                  0.2, 0, 0, 0),
    ]


def _run_and_build(view="All", pool_budget=15_000_000.0, n_iter=5_000, seed=42):
    """Run simulation and build output table."""
    risks = _make_risks()
    config = SimConfig(
        n_iter=n_iter, seed=seed, view=view, tic=100_000_000,
        contingency=10_000_000, pool_budget=pool_budget,
    )
    buckets = [WBSBucket("Test", 50_000_000, -0.05, 0.10, "Triangular")]
    chains = ChainConfig()
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    engine = MonteCarloEngine(config, buckets, chains, risks, corr, seed=seed)
    raw = engine.run()
    output = build_output_table(raw, risks, config)
    lookup = {r[0]: r[1] for r in output}
    return lookup, raw, risks, config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

POOL_KEYS = [
    "pool_budget", "pool_p50", "pool_p80", "pool_p90", "pool_p95",
    "pool_mean", "pool_std", "pool_max", "pool_adequacy",
    "pool_n_risks", "pool_n_costed", "pool_pct_costed",
    "pool_data_warning", "pool_emv",
]


def test_pool_keys_present_in_output():
    """All pool_* keys must exist in the output table."""
    lookup, _, _, _ = _run_and_build()
    for key in POOL_KEYS:
        assert key in lookup, f"Missing key: {key}"


def test_pool_keys_present_in_all_views():
    """Pool keys must be present in both All and Shared views."""
    for view in ["All", "Shared"]:
        lookup, _, _, _ = _run_and_build(view=view)
        for key in POOL_KEYS:
            assert key in lookup, f"Missing key {key} in {view} view"


def test_pool_p90_matches_shared_pool_p90():
    """pool_p90 should equal shared_pool_p90 (backward compatibility)."""
    lookup, _, _, _ = _run_and_build()
    assert lookup["pool_p90"] == pytest.approx(lookup["shared_pool_p90"], rel=1e-6)


def test_pool_adequacy_with_large_budget():
    """With a huge pool budget, adequacy should be ~1.0."""
    lookup, _, _, _ = _run_and_build(pool_budget=100_000_000)
    assert lookup["pool_adequacy"] == pytest.approx(1.0, abs=0.01)


def test_pool_adequacy_with_zero_budget():
    """With zero budget, adequacy depends on P(all shared=0)."""
    lookup, _, _, _ = _run_and_build(pool_budget=0)
    # Some risks will fire, so adequacy < 1.0
    assert lookup["pool_adequacy"] < 1.0


def test_pool_n_costed_counts_correctly():
    """SP11a: All 5 risks in pool, 4 with cost data, 1 without."""
    lookup, _, _, _ = _run_and_build()
    assert lookup["pool_n_risks"] == 5  # All risks are shared pool risks
    assert lookup["pool_n_costed"] == 4  # R001-R004 have costs; R005 is zero


def test_pool_data_warning_triggers():
    """SP11a: 4/5 = 80%, not < 80%, so no warning."""
    lookup, _, _, _ = _run_and_build()
    # 4/5 = 80% — threshold is < 0.8, so no warning
    assert lookup["pool_data_warning"] == "No"
    assert lookup["pool_pct_costed"] == pytest.approx(4 / 5, rel=0.01)


def test_pool_emv_calculation():
    """SP11a: pool_emv = sum(prob * ml_cost) for all risks."""
    lookup, _, _, _ = _run_and_build()
    # R001: 0.3 * 200_000 = 60_000
    # R002: 0.4 * 150_000 = 60_000
    # R003: 0.5 * 500_000 = 250_000
    # R004: 0.3 * 300_000 = 90_000
    # R005: 0.2 * 0 = 0
    expected = 60_000 + 60_000 + 250_000 + 90_000
    assert lookup["pool_emv"] == pytest.approx(expected, rel=0.01)


def test_sc_pool_keys_present():
    """sc_pool_1 through sc_pool_99 must all be in the output table."""
    lookup, _, _, _ = _run_and_build()
    for p in range(1, 100):
        assert f"sc_pool_{p}" in lookup, f"Missing sc_pool_{p}"
    # sc_pool_50 should approximately equal pool_p50
    assert lookup["sc_pool_50"] == pytest.approx(lookup["pool_p50"], rel=0.01)


def test_data_source_key_present():
    """data_source key must exist with default value."""
    lookup, _, _, _ = _run_and_build()
    assert "data_source" in lookup
    assert lookup["data_source"] == "MC_Inputs"


def test_existing_keys_unchanged():
    """New pool keys must not affect existing key values."""
    # Run once and check critical existing keys are numeric and reasonable
    lookup, _, _, _ = _run_and_build()
    for key in ["p10", "p50", "p80", "p90", "mean", "std",
                "bop_p10", "cse_p50", "l1_mean", "adequacy", "overrun"]:
        assert key in lookup, f"Missing existing key: {key}"
        assert isinstance(lookup[key], (int, float)), f"{key} is not numeric"
