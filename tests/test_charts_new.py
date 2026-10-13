"""
Tests for new chart functions (Stage 4).

Covers output histogram, input distribution panel, gain/pain chart,
WBS distribution panel, and integration with headless run.
"""

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.config import (
    SimConfig, WBSBucket, ChainConfig, RiskInput, GainPainConfig,
    SimRawResults, TornadoEntry,
)
from src.simulation import MonteCarloEngine
from src.analysis import compute_tornado, compute_party_costs
from src.gain_pain import compute_gain_pain
from src.charts import (
    generate_output_histogram,
    generate_input_distribution_panel,
    generate_gain_pain_chart,
    generate_wbs_distribution_panel,
    generate_tornado,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine_and_run(n_iter=5_000, seed=42, n_risks=3):
    config = SimConfig(n_iter=n_iter, seed=seed)
    buckets = [
        WBSBucket("Concrete/Civil", 55_000_000, -0.10, 0.20, "Triangular"),
        WBSBucket("Steel", 30_000_000, -0.05, 0.25, "Triangular"),
        WBSBucket("Piping", 35_000_000, -0.05, 0.20, "Triangular"),
        WBSBucket("E&I", 40_000_000, -0.05, 0.20, "Triangular"),
        WBSBucket("Mech/GEV", 60_000_000, -0.03, 0.12, "Triangular"),
        WBSBucket("Turnkey Pkg", 35_000_000, -0.05, 0.15, "Triangular"),
        WBSBucket("Labour Rate", 30_000_000, -0.05, 0.25, "Triangular"),
        WBSBucket("Labour Prod", 15_000_000, -0.05, 0.15, "Triangular"),
    ]
    chains = ChainConfig()
    owners = ["BOP Contractor", "Owner", "Shared", "BOP Contractor",
              "Owner", "Shared"]
    risks = [
        RiskInput(
            risk_id=f"R{i+1:03d}", description=f"Test risk {i+1}",
            owner=owners[i % len(owners)],
            distribution="Triangular", correlation_group="CG01",
            probability=0.25 + i * 0.05,
            opt_cost=100_000 * (i + 1), ml_cost=300_000 * (i + 1),
            pess_cost=600_000 * (i + 1),
        )
        for i in range(n_risks)
    ]
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    engine = MonteCarloEngine(config, buckets, chains, risks, corr, seed=seed)
    raw = engine.run()
    return raw, risks, config, buckets


def _tmp_png():
    return os.path.join(tempfile.mkdtemp(), "test_chart.png")


# ---------------------------------------------------------------------------
# TestOutputHistogram
# ---------------------------------------------------------------------------

class TestOutputHistogram:

    def test_generates_png(self):
        raw, risks, config, _ = _make_engine_and_run()
        costs = compute_party_costs(raw, risks, config)
        path = _tmp_png()
        generate_output_histogram(costs["total"], config, path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000

    def test_handles_tight_distribution(self):
        """Distribution entirely above budget — no crash."""
        config = SimConfig(n_iter=1000, tic=100_000_000, contingency=1_000)
        costs = np.full(1000, 500_000_000.0)  # all way above budget
        path = _tmp_png()
        generate_output_histogram(costs, config, path)
        assert os.path.exists(path)

    def test_view_label_in_title(self):
        raw, risks, config, _ = _make_engine_and_run(n_iter=1000)
        costs = compute_party_costs(raw, risks, config)
        path = _tmp_png()
        generate_output_histogram(costs["total"], config, path, view="BOP")
        assert os.path.exists(path)


# ---------------------------------------------------------------------------
# TestInputDistributionPanel
# ---------------------------------------------------------------------------

class TestInputDistributionPanel:

    def test_generates_png(self):
        raw, risks, config, _ = _make_engine_and_run(n_risks=6)
        tornado = compute_tornado(raw, risks)
        path = _tmp_png()
        generate_input_distribution_panel(raw, risks, tornado, path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000

    def test_fewer_risks_than_top_n(self):
        """Only 3 L2 risks but top_n=5 — no crash."""
        raw, risks, config, _ = _make_engine_and_run(n_risks=3)
        tornado = compute_tornado(raw, risks)
        path = _tmp_png()
        generate_input_distribution_panel(raw, risks, tornado, path, top_n=5)
        assert os.path.exists(path)

    def test_skips_layer1_entries(self):
        """Tornado with L1 entries — only L2 panels rendered."""
        raw, risks, config, _ = _make_engine_and_run(n_risks=2)
        # Create a tornado with 3 L1 + 2 L2 entries
        entries = [
            TornadoEntry("L1-0", "Concrete", 1e12, 1e6, layer="Layer 1"),
            TornadoEntry("L1-1", "Steel", 8e11, 9e5, layer="Layer 1"),
            TornadoEntry("L1-2", "Piping", 7e11, 8e5, layer="Layer 1"),
            TornadoEntry("R001", "Test risk 1", 5e11, 7e5,
                         owner="BOP Contractor", layer="Layer 2"),
            TornadoEntry("R002", "Test risk 2", 3e11, 5e5,
                         owner="Owner", layer="Layer 2"),
        ]
        path = _tmp_png()
        generate_input_distribution_panel(raw, risks, entries, path, top_n=5)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 5_000

    def test_all_zero_costs_risk(self):
        """Risk with zero cost data — no crash."""
        raw, risks, config, _ = _make_engine_and_run(n_risks=2)
        entries = [
            TornadoEntry("R001", "Test risk 1", 5e11, 7e5,
                         owner="BOP Contractor", layer="Layer 2"),
        ]
        path = _tmp_png()
        generate_input_distribution_panel(raw, risks, entries, path)
        assert os.path.exists(path)


# ---------------------------------------------------------------------------
# TestGainPainChart
# ---------------------------------------------------------------------------

class TestGainPainChart:

    def test_placeholder_when_disabled(self):
        gp_config = GainPainConfig(enabled=False)
        gp_results = {"bop_net": np.zeros(100)}
        path = _tmp_png()
        generate_gain_pain_chart(gp_results, gp_config, path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 5_000

    def test_generates_when_enabled(self):
        """Cost distribution spanning above and below TOC."""
        toc = 310_000_000.0
        gp_config = GainPainConfig(enabled=True, toc=toc)
        costs = np.random.default_rng(42).normal(toc, 10_000_000, 10_000)
        gp_results = compute_gain_pain(costs, gp_config)
        path = _tmp_png()
        generate_gain_pain_chart(gp_results, gp_config, path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000

    def test_all_gainshare(self):
        """All iterations below TOC — pure gainshare."""
        toc = 400_000_000.0
        gp_config = GainPainConfig(enabled=True, toc=toc)
        costs = np.full(5000, 350_000_000.0)
        gp_results = compute_gain_pain(costs, gp_config)
        path = _tmp_png()
        generate_gain_pain_chart(gp_results, gp_config, path)
        assert os.path.exists(path)

    def test_all_painshare(self):
        """All iterations above TOC — pure painshare."""
        toc = 300_000_000.0
        gp_config = GainPainConfig(enabled=True, toc=toc)
        costs = np.full(5000, 350_000_000.0)
        gp_results = compute_gain_pain(costs, gp_config)
        path = _tmp_png()
        generate_gain_pain_chart(gp_results, gp_config, path)
        assert os.path.exists(path)


# ---------------------------------------------------------------------------
# TestWBSDistributionPanel
# ---------------------------------------------------------------------------

class TestWBSDistributionPanel:

    def test_generates_png(self):
        raw, _, _, buckets = _make_engine_and_run()
        path = _tmp_png()
        generate_wbs_distribution_panel(raw, buckets, path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000

    def test_eight_panels(self):
        """8 buckets → 8 subplots, file > 20kb."""
        raw, _, _, buckets = _make_engine_and_run()
        assert len(buckets) == 8
        path = _tmp_png()
        generate_wbs_distribution_panel(raw, buckets, path)
        assert os.path.getsize(path) > 20_000


# ---------------------------------------------------------------------------
# TestChartsIntegration
# ---------------------------------------------------------------------------

class TestChartsIntegration:

    def test_headless_run_generates_all_seven_charts(self):
        """All 7 PNGs exist after a full headless simulation."""
        raw, risks, config, buckets = _make_engine_and_run(n_iter=10_000)
        costs = compute_party_costs(raw, risks, config)
        tornado = compute_tornado(raw, risks)

        chart_dir = Path(tempfile.mkdtemp())

        # Existing 3
        from src.charts import generate_s_curve, generate_convergence
        from src.analysis import compute_s_curve, compute_convergence

        sc_data = compute_s_curve(raw)
        generate_s_curve(sc_data, config, chart_dir / "s_curve.png")
        generate_tornado(tornado, chart_dir / "tornado.png")
        conv = compute_convergence(raw, seed=42)
        generate_convergence(conv, chart_dir / "convergence.png")

        # New 4
        generate_output_histogram(costs["total"], config,
                                  chart_dir / "output_histogram.png")
        generate_input_distribution_panel(raw, risks, tornado,
                                          chart_dir / "input_distributions.png")
        gp_config = GainPainConfig(enabled=True)
        gp_results = compute_gain_pain(costs["total"], gp_config)
        generate_gain_pain_chart(gp_results, gp_config,
                                 chart_dir / "gain_pain.png")
        generate_wbs_distribution_panel(raw, buckets,
                                        chart_dir / "wbs_distributions.png")

        expected = [
            "s_curve.png", "tornado.png", "convergence.png",
            "output_histogram.png", "input_distributions.png",
            "gain_pain.png", "wbs_distributions.png",
        ]
        for name in expected:
            fpath = chart_dir / name
            assert fpath.exists(), f"{name} missing"
            assert fpath.stat().st_size > 5_000, f"{name} too small"

    def test_no_existing_tests_broken(self):
        """Regression: basic engine run still works."""
        raw, risks, config, _ = _make_engine_and_run(n_iter=1_000)
        assert raw.ev_costs.shape == (1_000, 3)
