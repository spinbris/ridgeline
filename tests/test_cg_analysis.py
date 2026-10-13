"""
Tests for Stage 2 CG analysis functions.

Covers: compute_cg_summary, compute_firing_frequency,
compute_diversification_effect, generate_cg_bar_chart.
"""

import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput
from src.simulation import MonteCarloEngine
from src.analysis import (
    compute_cg_summary, compute_firing_frequency, compute_diversification_effect,
)
from src.charts import generate_cg_bar_chart


# ---------------------------------------------------------------------------
# Fixture: run a simulation with known risks across multiple CG groups
# ---------------------------------------------------------------------------

# TEST FIXTURE — DO NOT USE IN RUN CODE.
# Mirrors what src.openpyxl_reader.read_cg_descriptions would return from a
# register's MC_Params CG block for the three CGs the synthetic _make_sim
# fixture exercises. Run code reads descriptions from the register exclusively
# (Beta-17 SSoT cleanup); the fallback dict in src.defaults was deleted.
_TEST_CG_DESCRIPTIONS = {
    "CG01": "Labour",
    "CG02": "Design",
    "CG03": "Free Issue Equipment",
}


def _make_sim(n_iter=10_000, seed=42):
    """Create a simulation with 6 risks across 3 CG groups."""
    risks = [
        RiskInput("R001", "Risk A", "BOP", "Triangular", "CG01",
                  0.3, 100_000, 500_000, 1_000_000),
        RiskInput("R002", "Risk B", "BOP", "Triangular", "CG01",
                  0.5, 200_000, 800_000, 2_000_000),
        RiskInput("R003", "Risk C", "Shared", "Triangular", "CG02",
                  0.4, 50_000, 300_000, 700_000),
        RiskInput("R004", "Risk D", "Shared", "Triangular", "CG02",
                  0.2, 100_000, 400_000, 900_000),
        RiskInput("R005", "Risk E", "CSE", "Triangular", "CG03",
                  0.6, 500_000, 2_000_000, 5_000_000),
        # Zero-cost risk (should be excluded from firing frequency)
        RiskInput("R006", "Zero cost risk", "BOP", "Triangular", "CG01",
                  0.5, 0, 0, 0),
    ]
    config = SimConfig(n_iter=n_iter, seed=seed, view="L2Only", tic=0.0)
    chains = ChainConfig()
    corr = {"CG01": 0.6, "CG02": 0.5, "CG03": 0.4}
    engine = MonteCarloEngine(config, [], chains, risks, corr, seed=seed, wbs_rho=0.4)
    raw = engine.run()
    return raw, risks, corr


# ---------------------------------------------------------------------------
# compute_cg_summary tests
# ---------------------------------------------------------------------------

class TestCGSummary:

    def test_returns_one_entry_per_group(self):
        raw, risks, corr = _make_sim()
        summary = compute_cg_summary(raw, risks, corr, _TEST_CG_DESCRIPTIONS)
        cg_codes = {d["cg_code"] for d in summary}
        assert cg_codes == {"CG01", "CG02", "CG03"}

    def test_risk_counts(self):
        raw, risks, corr = _make_sim()
        summary = compute_cg_summary(raw, risks, corr, _TEST_CG_DESCRIPTIONS)
        by_cg = {d["cg_code"]: d for d in summary}
        assert by_cg["CG01"]["n_risks"] == 3  # R001, R002, R006
        assert by_cg["CG02"]["n_risks"] == 2
        assert by_cg["CG03"]["n_risks"] == 1

    def test_rho_values(self):
        raw, risks, corr = _make_sim()
        summary = compute_cg_summary(raw, risks, corr, _TEST_CG_DESCRIPTIONS)
        by_cg = {d["cg_code"]: d for d in summary}
        assert by_cg["CG01"]["rho"] == 0.6
        assert by_cg["CG03"]["rho"] == 0.4

    def test_variance_contributions_sum_approximately(self):
        """Leave-one-GROUP-out variance contributions should sum near 100%."""
        raw, risks, corr = _make_sim()
        summary = compute_cg_summary(raw, risks, corr, _TEST_CG_DESCRIPTIONS)
        total_pct = sum(d["pct_of_total_var"] for d in summary)
        # ±10% tolerance for interaction effects
        assert 0.9 <= total_pct <= 1.1, \
            f"Variance sum = {total_pct:.2%}, expected ~100%"

    def test_sorted_by_variance_descending(self):
        raw, risks, corr = _make_sim()
        summary = compute_cg_summary(raw, risks, corr, _TEST_CG_DESCRIPTIONS)
        pcts = [d["pct_of_total_var"] for d in summary]
        assert pcts == sorted(pcts, reverse=True)

    def test_group_emv(self):
        raw, risks, corr = _make_sim()
        summary = compute_cg_summary(raw, risks, corr, _TEST_CG_DESCRIPTIONS)
        by_cg = {d["cg_code"]: d for d in summary}
        # CG01: R001(0.3*500K) + R002(0.5*800K) + R006(0.5*0) = 150K + 400K = 550K
        expected = 0.3 * 500_000 + 0.5 * 800_000 + 0.5 * 0
        assert by_cg["CG01"]["group_emv"] == pytest.approx(expected, rel=1e-6)

    def test_percentiles_positive(self):
        raw, risks, corr = _make_sim()
        summary = compute_cg_summary(raw, risks, corr, _TEST_CG_DESCRIPTIONS)
        for d in summary:
            assert d["group_p50"] >= 0
            assert d["group_p80"] >= d["group_p50"]
            assert d["group_p90"] >= d["group_p80"]

    def test_empty_risks(self):
        from src.config import SimRawResults
        raw = SimRawResults(
            l1_cost=np.zeros(100), l1_buckets=np.zeros((100, 1)),
            ev_costs=np.zeros((100, 0)), n_iter=100, n_risks=0,
        )
        summary = compute_cg_summary(raw, [], {}, {})
        assert summary == []


# ---------------------------------------------------------------------------
# compute_firing_frequency tests
# ---------------------------------------------------------------------------

class TestFiringFrequency:

    def test_excludes_zero_cost_risks(self):
        raw, risks, _ = _make_sim()
        freq = compute_firing_frequency(raw, risks)
        ids = [d["risk_id"] for d in freq]
        assert "R006" not in ids  # zero-cost risk excluded
        assert len(freq) == 5     # 5 costed risks

    def test_fire_rate_in_range(self):
        """Non-recurring risk with P=0.3 should fire ~30% of iterations."""
        raw, risks, _ = _make_sim(n_iter=50_000)
        freq = compute_firing_frequency(raw, risks)
        by_id = {d["risk_id"]: d for d in freq}
        r001 = by_id["R001"]
        assert 0.25 <= r001["simulated_fire_rate"] <= 0.35

    def test_fire_rate_ratio(self):
        raw, risks, _ = _make_sim(n_iter=50_000)
        freq = compute_firing_frequency(raw, risks)
        by_id = {d["risk_id"]: d for d in freq}
        # For uncorrelated simple risks, ratio should be near 1.0
        r001 = by_id["R001"]
        assert 0.8 <= r001["fire_rate_ratio"] <= 1.2

    def test_mean_cost_if_fired_positive(self):
        raw, risks, _ = _make_sim()
        freq = compute_firing_frequency(raw, risks)
        for d in freq:
            if d["simulated_fire_rate"] > 0:
                assert d["mean_cost_if_fired"] > 0

    def test_sorted_by_fire_rate_descending(self):
        raw, risks, _ = _make_sim()
        freq = compute_firing_frequency(raw, risks)
        rates = [d["simulated_fire_rate"] for d in freq]
        assert rates == sorted(rates, reverse=True)


# ---------------------------------------------------------------------------
# compute_diversification_effect tests
# ---------------------------------------------------------------------------

class TestDiversificationEffect:

    def test_benefit_non_negative(self):
        raw, risks, _ = _make_sim()
        result = compute_diversification_effect(raw, risks, p_level=80)
        assert result["diversification_benefit"] >= 0

    def test_combined_less_than_sum(self):
        raw, risks, _ = _make_sim()
        result = compute_diversification_effect(raw, risks, p_level=80)
        assert result["combined_p"] <= result["sum_individual_p"]

    def test_pct_between_0_and_1(self):
        raw, risks, _ = _make_sim()
        result = compute_diversification_effect(raw, risks, p_level=80)
        assert 0 <= result["diversification_pct"] <= 1

    def test_different_p_levels(self):
        raw, risks, _ = _make_sim()
        r50 = compute_diversification_effect(raw, risks, p_level=50)
        r90 = compute_diversification_effect(raw, risks, p_level=90)
        assert r90["combined_p"] > r50["combined_p"]

    def test_empty_risks(self):
        from src.config import SimRawResults
        raw = SimRawResults(
            l1_cost=np.zeros(100), l1_buckets=np.zeros((100, 1)),
            ev_costs=np.zeros((100, 0)), n_iter=100, n_risks=0,
        )
        result = compute_diversification_effect(raw, [], p_level=80)
        assert result["diversification_benefit"] == 0.0


# ---------------------------------------------------------------------------
# Chart smoke test
# ---------------------------------------------------------------------------

class TestCGBarChart:

    def test_chart_generates(self, tmp_path):
        raw, risks, corr = _make_sim()
        summary = compute_cg_summary(raw, risks, corr, _TEST_CG_DESCRIPTIONS)
        path = tmp_path / "cg_bar.png"
        generate_cg_bar_chart(summary, path, p_level=80)
        assert path.exists()

    def test_empty_chart(self, tmp_path):
        path = tmp_path / "cg_bar_empty.png"
        generate_cg_bar_chart([], path)
        assert path.exists()
