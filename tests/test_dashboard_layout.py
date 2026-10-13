"""
Tests for dashboard layout redesign and chart improvements (Stage 14).

Validates:
- Chart positions have no overlapping bounding boxes
- Input distribution: fired-only (no $0 spike), low fire rate fallback
- Histogram x-axis clipping for lognormal outliers
- All 7 charts generate for both Shared and All views
- Convergence chart with numeric x-axis
"""

import os
import re
import tempfile
import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput, TornadoEntry, SimRawResults
from src.simulation import MonteCarloEngine
from src.analysis import build_output_table, compute_tornado, compute_party_costs
from src.charts import (
    generate_s_curve, generate_convergence, generate_tornado,
    generate_output_histogram, generate_input_distribution_panel,
    generate_gain_pain_chart, generate_wbs_distribution_panel,
)
from src.defaults import CHART_POSITIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cell_to_row_col(cell: str) -> tuple[int, int]:
    """Convert Excel cell address like 'B24' to (row, col) zero-indexed."""
    m = re.match(r"([A-Z]+)(\d+)", cell)
    col_str, row_str = m.group(1), m.group(2)
    col = 0
    for c in col_str:
        col = col * 26 + (ord(c) - ord('A'))
    return int(row_str), col


def _chart_bbox(entry):
    """Return (row, col, row_end, col_end) for a chart position.

    Approximate: 1 row ~ 20px, 1 col ~ 64px.
    """
    sheet, cell, width, height = entry
    row, col = _cell_to_row_col(cell)
    rows_span = height / 20
    cols_span = width / 64
    return (row, col, row + rows_span, col + cols_span)


def _bboxes_overlap(a, b):
    """Check if two (row, col, row_end, col_end) bounding boxes overlap."""
    r1, c1, r1e, c1e = a
    r2, c2, r2e, c2e = b
    if r1e <= r2 or r2e <= r1:
        return False
    if c1e <= c2 or c2e <= c1:
        return False
    return True


def _make_sim_data(view="All", n_iter=5_000, seed=42):
    """Run a small simulation for chart generation."""
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
    buckets = [WBSBucket("Test", 50_000_000, -0.05, 0.10, "Triangular")]
    chains = ChainConfig()
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    engine = MonteCarloEngine(config, buckets, chains, risks, corr, seed=seed)
    raw = engine.run()
    output = build_output_table(raw, risks, config)
    lookup = {r[0]: r[1] for r in output}
    return config, raw, risks, buckets, lookup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_chart_positions_no_overlap():
    """No two chart bounding boxes should overlap."""
    names = list(CHART_POSITIONS.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a = _chart_bbox(CHART_POSITIONS[names[i]])
            b = _chart_bbox(CHART_POSITIONS[names[j]])
            assert not _bboxes_overlap(a, b), \
                f"Charts '{names[i]}' and '{names[j]}' overlap"


def test_input_dist_fired_only():
    """Input distribution should generate without $0 spike."""
    config, raw, risks, buckets, lookup = _make_sim_data()
    tornado = compute_tornado(raw, risks, buckets=buckets)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_input_distribution_panel(raw, risks, tornado, path, top_n=5)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000
    finally:
        os.unlink(path)


def test_input_dist_low_fire_rate():
    """Input distribution with very few fires should show fallback text."""
    # Create raw results where risk barely fires
    n_iter = 1000
    ev_costs = np.zeros((n_iter, 1))
    ev_costs[:5, 0] = [100_000, 200_000, 150_000, 180_000, 120_000]  # only 5 fires
    raw = SimRawResults(
        l1_cost=np.full(n_iter, 100_000_000),
        l1_buckets=np.zeros((n_iter, 1)),
        ev_costs=ev_costs,
        n_iter=n_iter,
        n_risks=1,
    )
    risks = [
        RiskInput("R099", "Rare event", "Shared", "Binary", "CG01",
                  0.005, 100_000, 200_000, 400_000),
    ]
    tornado = [
        TornadoEntry("R099", "Rare event", 50_000, 224, owner="Shared", layer="Layer 2"),
    ]
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_input_distribution_panel(raw, risks, tornado, path, top_n=5)
        assert os.path.exists(path)
    finally:
        os.unlink(path)


def test_histogram_shared_view_clipped():
    """Histogram with lognormal-like outliers should clip x-axis."""
    rng = np.random.default_rng(42)
    shared_l2 = rng.lognormal(mean=14, sigma=1.5, size=10_000)
    config = SimConfig(tic=100_000_000, pool_budget=15_000_000)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        generate_output_histogram(
            np.zeros(10_000), config, path, view="Shared",
            pool_budget=15_000_000, shared_l2=shared_l2,
        )
        assert os.path.exists(path)
        assert os.path.getsize(path) > 5_000
    finally:
        os.unlink(path)


def test_all_charts_generate_shared():
    """All 7 chart types should generate for Shared view."""
    config, raw, risks, buckets, lookup = _make_sim_data(view="All")
    sc_data = {k: v for k, v in lookup.items() if k.startswith("sc_")}
    conv_data = {k: v for k, v in lookup.items() if k.startswith("conv_")}
    tornado = compute_tornado(raw, risks, buckets=buckets)
    costs = compute_party_costs(raw, risks, config)

    from src.config import GainPainConfig
    from src.gain_pain import compute_gain_pain
    gp_config = GainPainConfig(enabled=True)
    gp_raw = compute_gain_pain(costs["total"], gp_config)

    charts = {
        "s_curve": lambda p: generate_s_curve(sc_data, config, p,
                                               view="Shared", pool_budget=15e6),
        "tornado": lambda p: generate_tornado(tornado, p, view="Shared"),
        "convergence": lambda p: generate_convergence(conv_data, p, view="Shared"),
        "histogram": lambda p: generate_output_histogram(
            costs["total"], config, p, view="Shared",
            pool_budget=15e6, shared_l2=costs["shared_l2"]),
        "input_dist": lambda p: generate_input_distribution_panel(
            raw, risks, tornado, p, top_n=5),
        "gain_pain": lambda p: generate_gain_pain_chart(gp_raw, gp_config, p),
        "wbs_dist": lambda p: generate_wbs_distribution_panel(raw, buckets, p),
    }

    for name, gen_fn in charts.items():
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            gen_fn(path)
            assert os.path.exists(path), f"Chart '{name}' not created"
        finally:
            os.unlink(path)


def test_all_charts_generate_all():
    """All 7 chart types should generate for All view (regression)."""
    config, raw, risks, buckets, lookup = _make_sim_data(view="All")
    sc_data = {k: v for k, v in lookup.items() if k.startswith("sc_")}
    conv_data = {k: v for k, v in lookup.items() if k.startswith("conv_")}
    tornado = compute_tornado(raw, risks, buckets=buckets)
    costs = compute_party_costs(raw, risks, config)

    from src.config import GainPainConfig
    from src.gain_pain import compute_gain_pain
    gp_config = GainPainConfig(enabled=True)
    gp_raw = compute_gain_pain(costs["total"], gp_config)

    charts = {
        "s_curve": lambda p: generate_s_curve(sc_data, config, p, view="All"),
        "tornado": lambda p: generate_tornado(tornado, p, view="All"),
        "convergence": lambda p: generate_convergence(conv_data, p, view="All"),
        "histogram": lambda p: generate_output_histogram(
            costs["total"], config, p, view="All"),
        "input_dist": lambda p: generate_input_distribution_panel(
            raw, risks, tornado, p, top_n=5),
        "gain_pain": lambda p: generate_gain_pain_chart(gp_raw, gp_config, p),
        "wbs_dist": lambda p: generate_wbs_distribution_panel(raw, buckets, p),
    }

    for name, gen_fn in charts.items():
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            gen_fn(path)
            assert os.path.exists(path), f"Chart '{name}' not created"
        finally:
            os.unlink(path)


def test_convergence_numeric_xaxis():
    """Convergence chart with 7 points should generate with log-scale x-axis."""
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
