"""
Tests for view-aware chart generation (S-curve, histogram, WBS panel fix).

Validates:
- S-curve generates for Shared and All views without error
- Histogram generates for Shared and All views without error
- WBS panel axes bug is fixed (no IndexError with various bucket counts)
"""

import os
import tempfile
import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput, SimRawResults
from src.simulation import MonteCarloEngine
from src.analysis import build_output_table, compute_tornado
from src.charts import (
    generate_s_curve, generate_output_histogram,
    generate_wbs_distribution_panel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sim_data(view="All", n_iter=5_000, seed=42):
    """Run a small simulation and return everything needed for charts."""
    risks = [
        RiskInput("R001", "BOP risk", "BOP Contractor", "Binary", "CG01",
                  0.3, 100_000, 200_000, 400_000),
        RiskInput("R002", "Shared risk", "Shared", "Binary", "CG02",
                  0.5, 200_000, 500_000, 1_000_000),
    ]
    config = SimConfig(
        n_iter=n_iter, seed=seed, view=view, tic=100_000_000,
        contingency=10_000_000, pool_budget=15_000_000,
    )
    buckets = [
        WBSBucket("Bucket A", 30_000_000, -0.05, 0.10, "Triangular"),
        WBSBucket("Bucket B", 20_000_000, -0.03, 0.08, "Triangular"),
    ]
    chains = ChainConfig()
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    engine = MonteCarloEngine(config, buckets, chains, risks, corr, seed=seed)
    raw = engine.run()
    output = build_output_table(raw, risks, config)
    lookup = {r[0]: r[1] for r in output}
    sc_data = {k: v for k, v in lookup.items() if k.startswith("sc_")}
    tornado = compute_tornado(raw, risks, buckets=buckets)
    return config, raw, risks, buckets, sc_data, lookup, tornado


# ---------------------------------------------------------------------------
# S-curve tests
# ---------------------------------------------------------------------------

def test_s_curve_shared_view_creates_file():
    """S-curve with view=Shared and pool_budget should create a PNG."""
    config, raw, risks, buckets, sc_data, lookup, _ = _make_sim_data(view="All")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_s_curve(sc_data, config, path, view="Shared",
                         pool_budget=15_000_000)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000  # > 10KB
    finally:
        os.unlink(path)


def test_s_curve_shared_uses_pool_data():
    """S-curve with view=Shared should not error (pool data present)."""
    config, raw, risks, buckets, sc_data, lookup, _ = _make_sim_data(view="All")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        # Should not raise
        generate_s_curve(sc_data, config, path, view="Shared",
                         pool_budget=15_000_000)
    finally:
        os.unlink(path)


def test_s_curve_all_view_unchanged():
    """S-curve with view=All should still work (regression)."""
    config, raw, risks, buckets, sc_data, lookup, _ = _make_sim_data(view="All")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_s_curve(sc_data, config, path, view="All")
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Histogram tests
# ---------------------------------------------------------------------------

def test_histogram_shared_view_creates_file():
    """Histogram with view=Shared and shared_l2 should create a PNG."""
    config, raw, risks, buckets, sc_data, lookup, _ = _make_sim_data(view="All")
    from src.analysis import compute_party_costs
    costs = compute_party_costs(raw, risks, config)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_output_histogram(
            costs["total"], config, path, view="Shared",
            pool_budget=15_000_000, shared_l2=costs["shared_l2"],
        )
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000
    finally:
        os.unlink(path)


def test_histogram_all_view_unchanged():
    """Histogram with view=All should still work (regression)."""
    config, raw, risks, buckets, sc_data, lookup, _ = _make_sim_data(view="All")
    from src.analysis import compute_party_costs
    costs = compute_party_costs(raw, risks, config)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_output_histogram(costs["total"], config, path, view="All")
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# WBS panel bug fix test
# ---------------------------------------------------------------------------

def test_wbs_panel_bug_fixed():
    """WBS panel with 5 buckets should not raise IndexError."""
    n_iter = 1_000
    buckets = [
        WBSBucket(f"Bucket {i}", 10_000_000 * (i + 1), -0.05, 0.10, "Triangular")
        for i in range(5)
    ]
    config = SimConfig(n_iter=n_iter, seed=42, tic=150_000_000)
    chains = ChainConfig()
    risks = []
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    engine = MonteCarloEngine(config, buckets, chains, risks, corr, seed=42)
    raw = engine.run()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        # This would raise IndexError before the fix (axes[k] instead of axes[plot_idx])
        generate_wbs_distribution_panel(raw, buckets, path)
        assert os.path.exists(path)
    finally:
        os.unlink(path)
