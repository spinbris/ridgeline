"""
Tests for L2Only view mode.

When view=L2Only, the model should:
- Set l1_cost to zeros (no TIC baseline)
- Include ALL L2 risks regardless of owner
- Show pure event risk costs from $0
- Produce tornado with only Layer 2 entries (no L1 buckets)
- Charts generate without error
"""

import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput, GainPainConfig
from src.simulation import MonteCarloEngine
from src.analysis import build_output_table, compute_tornado, compute_s_curve, compute_convergence


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_engine(view="L2Only", n_iter=5_000, seed=42):
    """Create engine and run simulation with given view."""
    risks = [
        RiskInput("R001", "BOP risk", "BOP Contractor", "Triangular", "CG01",
                  0.3, 100_000, 200_000, 400_000),
        RiskInput("R002", "Shared risk 1", "Shared", "Triangular", "CG02",
                  0.5, 500_000, 2_000_000, 5_000_000),
        RiskInput("R003", "CSE risk", "Owner", "Binary", "CG03",
                  0.4, 200_000, 1_000_000, 3_000_000),
    ]
    tic = 285_000_000.0
    config = SimConfig(
        n_iter=n_iter, seed=seed, view=view, tic=tic,
        contingency=30_000_000, pool_budget=15_000_000,
    )
    buckets = [WBSBucket("Test", 100_000_000, -0.05, 0.10, "Triangular")]
    chains = ChainConfig()
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    engine = MonteCarloEngine(config, buckets, chains, risks, corr, seed=seed)
    raw = engine.run()
    return raw, risks, config, buckets


def _run_and_build(view="L2Only", n_iter=5_000, seed=42):
    """Run simulation and build output table."""
    raw, risks, config, buckets = _make_engine(view=view, n_iter=n_iter, seed=seed)
    output = build_output_table(raw, risks, config, buckets=buckets)
    lookup = {r[0]: r[1] for r in output}
    return lookup, raw, risks, config, buckets


# ---------------------------------------------------------------------------
# Simulation layer tests
# ---------------------------------------------------------------------------

def test_l2only_l1_cost_is_zeros():
    """L2Only sets l1_cost to all zeros (no TIC baseline)."""
    raw, _, _, _ = _make_engine(view="L2Only")
    assert np.all(raw.l1_cost == 0.0), "l1_cost should be all zeros for L2Only"


def test_l2only_l1_buckets_are_zeros():
    """L2Only sets l1_buckets to all zeros."""
    raw, _, _, _ = _make_engine(view="L2Only")
    assert np.all(raw.l1_buckets == 0.0), "l1_buckets should be all zeros"


def test_l2only_ev_costs_nonzero():
    """L2Only should still simulate L2 event risks."""
    raw, _, _, _ = _make_engine(view="L2Only")
    total_l2 = raw.ev_costs.sum(axis=1)
    assert np.any(total_l2 > 0), "L2 event costs should be non-zero in some iterations"


def test_l2only_includes_all_risks():
    """L2Only includes all 3 risks (BOP, Shared, CSE) — no owner filtering."""
    raw, _, _, _ = _make_engine(view="L2Only")
    assert raw.n_risks == 3, f"Expected 3 risks, got {raw.n_risks}"
    # Each risk should fire in at least some iterations
    for i in range(3):
        assert np.any(raw.ev_costs[:, i] > 0), f"Risk {i} never fired"


# ---------------------------------------------------------------------------
# Analysis layer tests
# ---------------------------------------------------------------------------

def test_l2only_primary_pvalues_are_pure_l2():
    """L2Only P50 should be pure event cost (< $50M), not TIC + pool."""
    lookup, _, _, _, _ = _run_and_build(view="L2Only")
    assert lookup["p50"] < 50_000_000, \
        f"L2Only P50 = ${lookup['p50']/1e6:.1f}M — should be pure L2 cost"
    assert lookup["p50"] >= 0, "L2Only P50 should be >= 0"


def test_l2only_risk_premium_equals_p50():
    """L2Only risk_premium = P50 (no TIC subtraction)."""
    lookup, _, _, _, _ = _run_and_build(view="L2Only")
    assert lookup["risk_premium"] == pytest.approx(lookup["p50"], rel=1e-6)


def test_l2only_l1_pvalues_are_zeros():
    """L2Only l1_p50 etc should be zero."""
    lookup, _, _, _, _ = _run_and_build(view="L2Only")
    assert lookup["l1_p50"] == pytest.approx(0.0, abs=1e-6)
    assert lookup["l1_p90"] == pytest.approx(0.0, abs=1e-6)


def test_l2only_view_label():
    """view_label should be 'Event Risks Only (L2)'."""
    lookup, _, _, _, _ = _run_and_build(view="L2Only")
    assert lookup["view_label"] == "Event Risks Only (L2)"
    assert lookup["view"] == "L2Only"


def test_l2only_shared_pvalues_no_tic():
    """L2Only shared_p50 should NOT include TIC."""
    lookup, _, _, _, _ = _run_and_build(view="L2Only")
    assert lookup["shared_p50"] < 50_000_000, \
        f"shared_p50 = ${lookup['shared_p50']/1e6:.1f}M — should not include TIC"


def test_l2only_s_curve_excludes_tic():
    """L2Only sc_total_50 should be pure L2 cost (< $50M)."""
    lookup, _, _, _, _ = _run_and_build(view="L2Only")
    assert lookup["sc_total_50"] < 50_000_000, \
        f"sc_total_50 = ${lookup['sc_total_50']/1e6:.1f}M — should be pure L2"


def test_l2only_convergence_excludes_tic():
    """L2Only convergence values should be < $50M."""
    lookup, _, _, _, _ = _run_and_build(view="L2Only")
    if "conv_1000" in lookup:
        assert lookup["conv_1000"] < 50_000_000


def test_l2only_adequacy_uses_pool_budget():
    """L2Only with large pool_budget should have adequacy ~ 1.0."""
    raw, risks, _, buckets = _make_engine(view="L2Only")
    config = SimConfig(n_iter=5_000, seed=42, view="L2Only",
                       pool_budget=500_000_000)
    output = build_output_table(raw, risks, config, buckets=buckets)
    lookup = {r[0]: r[1] for r in output}
    assert lookup["adequacy"] == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Tornado tests
# ---------------------------------------------------------------------------

def test_l2only_tornado_no_l1_entries():
    """L2Only tornado should contain no Layer 1 entries."""
    raw, risks, config, buckets = _make_engine(view="L2Only")
    tornado = compute_tornado(raw, risks, buckets=buckets, view="L2Only")
    for entry in tornado:
        assert entry.layer != "Layer 1", \
            f"Found Layer 1 entry in L2Only tornado: {entry.risk_id}"


def test_l2only_tornado_has_l2_entries():
    """L2Only tornado should have Layer 2 entries."""
    raw, risks, config, buckets = _make_engine(view="L2Only")
    tornado = compute_tornado(raw, risks, buckets=buckets, view="L2Only")
    assert len(tornado) > 0, "Tornado should have entries"
    assert all(e.layer == "Layer 2" for e in tornado)


# ---------------------------------------------------------------------------
# Regression: existing views unchanged
# ---------------------------------------------------------------------------

def test_all_view_unchanged():
    """All view should be completely unchanged."""
    lookup, _, _, _, _ = _run_and_build(view="All")
    assert lookup["p50"] > 280_000_000, "All P50 should include TIC"
    assert lookup["risk_premium"] == pytest.approx(
        lookup["p50"] - 285_000_000, rel=1e-6)


def test_shared_view_unchanged():
    """Shared view should be completely unchanged."""
    lookup, _, _, _, _ = _run_and_build(view="Shared")
    assert lookup["p50"] < 50_000_000, "Shared P50 should be pool cost"
    assert lookup["risk_premium"] == pytest.approx(lookup["p50"], rel=1e-6)


# ---------------------------------------------------------------------------
# Chart smoke tests
# ---------------------------------------------------------------------------

def test_l2only_charts_generate(tmp_path):
    """All charts should generate without error for L2Only view."""
    from src.charts import (
        generate_s_curve, generate_tornado, generate_output_histogram,
        generate_convergence, generate_input_distribution_panel,
    )

    lookup, raw, risks, config, buckets = _run_and_build(view="L2Only")

    # S-curve
    sc_data = {k: v for k, v in lookup.items() if k.startswith("sc_")}
    generate_s_curve(sc_data, config, tmp_path / "s_curve.png", view="L2Only")
    assert (tmp_path / "s_curve.png").exists()

    # Tornado
    tornado = compute_tornado(raw, risks, buckets=buckets, view="L2Only")
    generate_tornado(tornado, tmp_path / "tornado.png", view="L2Only")
    assert (tmp_path / "tornado.png").exists()

    # Histogram
    l2_all = raw.ev_costs.sum(axis=1)
    generate_output_histogram(
        l2_all, config, tmp_path / "hist.png", view="L2Only", shared_l2=l2_all)
    assert (tmp_path / "hist.png").exists()

    # Convergence
    conv_data = {k: v for k, v in lookup.items() if k.startswith("conv_")}
    generate_convergence(conv_data, tmp_path / "conv.png", view="L2Only")
    assert (tmp_path / "conv.png").exists()

    # Input distribution panel
    generate_input_distribution_panel(
        raw, risks, tornado, tmp_path / "input_dist.png", top_n=3)
    assert (tmp_path / "input_dist.png").exists()
