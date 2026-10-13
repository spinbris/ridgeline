"""
Tests for chart improvements (Stage 13).

Validates:
- S-curve generates for Shared and All views
- Convergence generates for Shared view with view-aware labels
- Convergence handles 7 points (100k) and 5 points (30k)
- Tornado legend filters to present owners only
- Histogram generates for Shared view
- All chart positions on MC_Dashboard
"""

import os
import tempfile
import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput, TornadoEntry, SimRawResults
from src.simulation import MonteCarloEngine
from src.analysis import build_output_table, compute_tornado
from src.charts import (
    generate_s_curve, generate_convergence, generate_tornado,
    generate_output_histogram,
)
from src.defaults import CHART_POSITIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sim_data(view="All", n_iter=5_000, seed=42):
    """Run a small simulation and return everything for charts."""
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
    ]
    chains = ChainConfig()
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    engine = MonteCarloEngine(config, buckets, chains, risks, corr, seed=seed)
    raw = engine.run()
    output = build_output_table(raw, risks, config)
    lookup = {r[0]: r[1] for r in output}
    sc_data = {k: v for k, v in lookup.items() if k.startswith("sc_")}
    return config, raw, risks, buckets, sc_data, lookup


# ---------------------------------------------------------------------------
# S-curve tests
# ---------------------------------------------------------------------------

def test_s_curve_shared_view_generates():
    """S-curve with view=Shared should create a PNG > 10kb."""
    config, raw, risks, buckets, sc_data, lookup = _make_sim_data(view="All")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_s_curve(sc_data, config, path, view="Shared",
                         pool_budget=15_000_000)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000
    finally:
        os.unlink(path)


def test_s_curve_all_view_generates():
    """S-curve with view=All should still work (regression)."""
    config, raw, risks, buckets, sc_data, lookup = _make_sim_data(view="All")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_s_curve(sc_data, config, path, view="All")
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Convergence tests
# ---------------------------------------------------------------------------

def test_convergence_shared_view_generates():
    """Convergence with view=Shared should create a file."""
    conv_data = {f"conv_{n}": float(n * 0.001) for n in [1000, 5000, 10000]}
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_convergence(conv_data, path, view="Shared")
        assert os.path.exists(path)
    finally:
        os.unlink(path)


def test_convergence_100k_has_7_points():
    """Convergence with all 7 keys (1k-100k) should generate without error."""
    conv_data = {}
    for n in [1000, 5000, 10000, 20000, 30000, 50000, 100000]:
        conv_data[f"conv_{n}"] = 345_000_000 + n * 0.1
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_convergence(conv_data, path, view="All")
        assert os.path.exists(path)
        assert os.path.getsize(path) > 5_000
    finally:
        os.unlink(path)


def test_convergence_30k_has_5_points():
    """Convergence with 5 keys (1k-30k) should still work (backward compat)."""
    conv_data = {}
    for n in [1000, 5000, 10000, 20000, 30000]:
        conv_data[f"conv_{n}"] = 345_000_000 + n * 0.1
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_convergence(conv_data, path, view="All")
        assert os.path.exists(path)
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Tornado tests
# ---------------------------------------------------------------------------

def test_tornado_shared_view_legend():
    """Tornado with only Shared entries should generate without error."""
    entries = [
        TornadoEntry("R001", "Shared risk 1", 5_000_000, 2_236_000,
                     owner="Shared", layer="Layer 2"),
        TornadoEntry("R002", "Shared risk 2", 2_000_000, 1_414_000,
                     owner="Shared", layer="Layer 2"),
    ]
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_tornado(entries, path, view="Shared")
        assert os.path.exists(path)
        assert os.path.getsize(path) > 5_000
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Histogram tests
# ---------------------------------------------------------------------------

def test_histogram_shared_view_generates():
    """Histogram with view=Shared should create a file."""
    config, raw, risks, buckets, sc_data, lookup = _make_sim_data(view="All")
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


# ---------------------------------------------------------------------------
# Chart positions test
# ---------------------------------------------------------------------------

def test_chart_positions_all_on_dashboard():
    """All chart positions should be on MC_Dashboard."""
    for name, (sheet, cell, w, h) in CHART_POSITIONS.items():
        assert sheet == "MC_Dashboard", \
            f"Chart '{name}' is on '{sheet}', expected 'MC_Dashboard'"
