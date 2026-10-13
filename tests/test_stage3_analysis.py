"""
Tests for Stage 3: compute_removal_impact, generate_removal_chart,
generate_exposure_curve.
"""

import numpy as np
import pytest

from src.config import SimConfig, ChainConfig, RiskInput, SimRawResults
from src.simulation import MonteCarloEngine
from src.analysis import compute_removal_impact
from src.charts import generate_removal_chart, generate_exposure_curve


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _make_sim(n_iter=10_000, seed=42):
    risks = [
        RiskInput("R001", "High-impact risk", "BOP", "Triangular", "CG01",
                  0.5, 500_000, 2_000_000, 5_000_000),
        RiskInput("R002", "Medium risk", "BOP", "Triangular", "CG02",
                  0.3, 100_000, 500_000, 1_000_000),
        RiskInput("R003", "Low risk", "Shared", "Triangular", "CG03",
                  0.2, 50_000, 200_000, 500_000),
        RiskInput("R004", "Tiny risk", "CSE", "Triangular", "CG01",
                  0.1, 10_000, 50_000, 100_000),
    ]
    config = SimConfig(n_iter=n_iter, seed=seed, view="L2Only", tic=0.0)
    chains = ChainConfig()
    corr = {"CG01": 0.5, "CG02": 0.5, "CG03": 0.5}
    engine = MonteCarloEngine(config, [], chains, risks, corr, seed=seed, wbs_rho=0.4)
    raw = engine.run()
    return raw, risks


# ---------------------------------------------------------------------------
# compute_removal_impact tests
# ---------------------------------------------------------------------------

class TestRemovalImpact:

    def test_returns_top_n_entries(self):
        raw, risks = _make_sim()
        result = compute_removal_impact(raw, risks, top_n=3, p_level=80)
        assert len(result) == 3

    def test_individual_reductions_non_negative(self):
        """Removing a risk should not increase the P-level (within epsilon)."""
        raw, risks = _make_sim()
        result = compute_removal_impact(raw, risks, top_n=3, p_level=80)
        for d in result:
            assert d["reduction"] >= -1e-6, \
                f"Negative reduction for {d['risk_id']}: {d['reduction']}"

    def test_original_p_consistent(self):
        raw, risks = _make_sim()
        result = compute_removal_impact(raw, risks, top_n=3, p_level=80)
        total = raw.ev_costs.sum(axis=1)
        expected_p80 = float(np.percentile(total, 80))
        for d in result:
            assert d["original_p"] == pytest.approx(expected_p80, rel=1e-6)

    def test_removed_p_less_than_original(self):
        raw, risks = _make_sim()
        result = compute_removal_impact(raw, risks, top_n=3, p_level=80)
        for d in result:
            assert d["removed_p"] <= d["original_p"] + 1e-6

    def test_cumulative_reduction_increases(self):
        """Cumulative reduction should generally increase with more removals."""
        raw, risks = _make_sim()
        result = compute_removal_impact(raw, risks, top_n=3, p_level=80)
        cum_reductions = [d["cumulative_reduction"] for d in result]
        # Each cumulative should be >= previous (removing more risks helps)
        for i in range(1, len(cum_reductions)):
            assert cum_reductions[i] >= cum_reductions[i - 1] - 1e-6

    def test_top_n_1(self):
        raw, risks = _make_sim()
        result = compute_removal_impact(raw, risks, top_n=1, p_level=80)
        assert len(result) == 1
        # For top_n=1, cumulative = individual
        assert result[0]["reduction"] == pytest.approx(
            result[0]["cumulative_reduction"], rel=1e-6)

    def test_different_p_levels(self):
        raw, risks = _make_sim()
        r50 = compute_removal_impact(raw, risks, top_n=1, p_level=50)
        r90 = compute_removal_impact(raw, risks, top_n=1, p_level=90)
        assert r90[0]["original_p"] > r50[0]["original_p"]

    def test_empty_risks(self):
        raw = SimRawResults(
            l1_cost=np.zeros(100), l1_buckets=np.zeros((100, 1)),
            ev_costs=np.zeros((100, 0)), n_iter=100, n_risks=0,
        )
        result = compute_removal_impact(raw, [], top_n=3)
        assert result == []


# ---------------------------------------------------------------------------
# Exposure curve data test (uses existing S-curve lookup pattern)
# ---------------------------------------------------------------------------

class TestExposureCurveData:

    def test_monotonically_increasing(self):
        """Higher P-level should always give higher or equal cost."""
        raw, risks = _make_sim()
        total = raw.ev_costs.sum(axis=1)
        p_levels = list(range(1, 100))
        costs = [float(np.percentile(total, p)) for p in p_levels]
        for i in range(1, len(costs)):
            assert costs[i] >= costs[i - 1] - 1e-6, \
                f"Non-monotonic at P{p_levels[i]}: {costs[i]} < {costs[i-1]}"


# ---------------------------------------------------------------------------
# Chart smoke tests
# ---------------------------------------------------------------------------

class TestStage3Charts:

    def test_removal_chart_generates(self, tmp_path):
        raw, risks = _make_sim()
        impact = compute_removal_impact(raw, risks, top_n=3, p_level=80)
        path = tmp_path / "removal.png"
        generate_removal_chart(impact, path, p_level=80)
        assert path.exists()

    def test_removal_chart_empty(self, tmp_path):
        path = tmp_path / "removal_empty.png"
        generate_removal_chart([], path)
        assert path.exists()

    def test_exposure_curve_generates(self, tmp_path):
        raw, risks = _make_sim()
        total = raw.ev_costs.sum(axis=1)
        p_levels = list(range(1, 100))
        costs = [float(np.percentile(total, p)) for p in p_levels]
        path = tmp_path / "exposure.png"
        generate_exposure_curve(p_levels, costs, path)
        assert path.exists()
