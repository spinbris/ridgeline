"""
Tests for RBS Level 1 analysis functions.

Covers: compute_rbs_l1_summary, compute_rbs_l1_diversification.
"""

import numpy as np
import pytest

from src.config import SimConfig, ChainConfig, RiskInput, SimRawResults
from src.simulation import MonteCarloEngine
from src.analysis import (
    compute_rbs_l1_summary, compute_rbs_l1_diversification,
    compute_rbs_l1_p80_contribution,
)


# ---------------------------------------------------------------------------
# Fixture: risks span multiple RBS L1 categories AND multiple CG groups —
# the two dimensions are orthogonal, mirroring the real register.
# ---------------------------------------------------------------------------

def _make_sim(n_iter=10_000, seed=42, with_blank_rbs=False):
    risks = [
        RiskInput("R001", "Risk A", "BOP", "Triangular", "CG01",
                  0.3, 100_000, 500_000, 1_000_000,
                  rbs_l1="_4.External_Risks"),
        RiskInput("R002", "Risk B", "BOP", "Triangular", "CG01",
                  0.5, 200_000, 800_000, 2_000_000,
                  rbs_l1="_6.Operational_Risks"),
        RiskInput("R003", "Risk C", "Shared", "Triangular", "CG02",
                  0.4, 50_000, 300_000, 700_000,
                  rbs_l1="_4.External_Risks"),
        RiskInput("R004", "Risk D", "Shared", "Triangular", "CG02",
                  0.2, 100_000, 400_000, 900_000,
                  rbs_l1="_6.Operational_Risks"),
        RiskInput("R005", "Risk E", "CSE", "Triangular", "CG03",
                  0.6, 500_000, 2_000_000, 5_000_000,
                  rbs_l1="_3.Technical_Risks"),
    ]
    if with_blank_rbs:
        risks.append(RiskInput("R006", "No category", "BOP", "Triangular", "CG01",
                               0.5, 10_000, 50_000, 100_000, rbs_l1=""))
    config = SimConfig(n_iter=n_iter, seed=seed, view="L2Only", tic=0.0)
    chains = ChainConfig()
    corr = {"CG01": 0.6, "CG02": 0.5, "CG03": 0.4}
    engine = MonteCarloEngine(config, [], chains, risks, corr, seed=seed, wbs_rho=0.4)
    raw = engine.run()
    return raw, risks


# ---------------------------------------------------------------------------
# compute_rbs_l1_summary
# ---------------------------------------------------------------------------

class TestRBSL1Summary:

    def test_returns_one_entry_per_category(self):
        raw, risks = _make_sim()
        summary = compute_rbs_l1_summary(raw, risks)
        labels = {d["rbs_l1"] for d in summary}
        assert labels == {
            "_4.External_Risks", "_6.Operational_Risks", "_3.Technical_Risks",
        }

    def test_risk_counts(self):
        raw, risks = _make_sim()
        summary = compute_rbs_l1_summary(raw, risks)
        by_label = {d["rbs_l1"]: d for d in summary}
        assert by_label["_4.External_Risks"]["n_risks"] == 2
        assert by_label["_6.Operational_Risks"]["n_risks"] == 2
        assert by_label["_3.Technical_Risks"]["n_risks"] == 1

    def test_sorted_by_variance_descending(self):
        raw, risks = _make_sim()
        summary = compute_rbs_l1_summary(raw, risks)
        pcts = [d["pct_of_total_var"] for d in summary]
        assert pcts == sorted(pcts, reverse=True)

    def test_percentiles_monotonic(self):
        raw, risks = _make_sim()
        summary = compute_rbs_l1_summary(raw, risks)
        for d in summary:
            assert d["group_p50"] >= 0
            assert d["group_p80"] >= d["group_p50"]
            assert d["group_p90"] >= d["group_p80"]

    def test_group_mean_sums_to_portfolio_mean(self):
        """Sum of per-group means must equal portfolio mean exactly —
        expectation is linear across groups regardless of correlation."""
        raw, risks = _make_sim()
        summary = compute_rbs_l1_summary(raw, risks)
        portfolio_mean = float(raw.ev_costs.sum(axis=1).mean())
        group_mean_total = sum(d["group_mean"] for d in summary)
        assert group_mean_total == pytest.approx(portfolio_mean, rel=1e-9)

    def test_blank_rbs_bucketed_as_uncategorised(self):
        raw, risks = _make_sim(with_blank_rbs=True)
        summary = compute_rbs_l1_summary(raw, risks)
        labels = {d["rbs_l1"] for d in summary}
        assert "(Uncategorised)" in labels

    def test_group_emv(self):
        raw, risks = _make_sim()
        summary = compute_rbs_l1_summary(raw, risks)
        by_label = {d["rbs_l1"]: d for d in summary}
        # External: R001(0.3*500K) + R003(0.4*300K) = 150K + 120K = 270K
        expected = 0.3 * 500_000 + 0.4 * 300_000
        assert by_label["_4.External_Risks"]["group_emv"] == pytest.approx(
            expected, rel=1e-6)

    def test_empty_risks(self):
        raw = SimRawResults(
            l1_cost=np.zeros(100), l1_buckets=np.zeros((100, 1)),
            ev_costs=np.zeros((100, 0)), n_iter=100, n_risks=0,
        )
        assert compute_rbs_l1_summary(raw, []) == []


# ---------------------------------------------------------------------------
# compute_rbs_l1_diversification
# ---------------------------------------------------------------------------

class TestRBSL1Diversification:

    def test_benefit_non_negative_on_dense_fixture(self):
        # Fixture is deliberately dense (high probability, meaningful costs)
        # so the usual diversification case holds. Super-additivity can and
        # does occur on real sparse event-risk registers — see docstring.
        raw, risks = _make_sim()
        result = compute_rbs_l1_diversification(raw, risks, p_level=80)
        assert result["diversification_benefit"] >= 0

    def test_combined_matches_portfolio_percentile(self):
        raw, risks = _make_sim()
        result = compute_rbs_l1_diversification(raw, risks, p_level=80)
        expected = float(np.percentile(raw.ev_costs.sum(axis=1), 80))
        assert result["combined_p"] == pytest.approx(expected, rel=1e-9)

    def test_sum_individual_strictly_greater_for_uncorrelated_groups(self):
        """RBS L1 categories cut across CG groups, so the category totals are
        not perfectly co-moving — diversification benefit should be > 0."""
        raw, risks = _make_sim(n_iter=30_000)
        result = compute_rbs_l1_diversification(raw, risks, p_level=80)
        assert result["sum_individual_p"] > result["combined_p"]

    def test_pct_between_0_and_1(self):
        raw, risks = _make_sim()
        result = compute_rbs_l1_diversification(raw, risks, p_level=80)
        assert 0 <= result["diversification_pct"] <= 1

    def test_higher_p_level_higher_combined(self):
        raw, risks = _make_sim()
        r50 = compute_rbs_l1_diversification(raw, risks, p_level=50)
        r90 = compute_rbs_l1_diversification(raw, risks, p_level=90)
        assert r90["combined_p"] > r50["combined_p"]

    def test_empty_risks(self):
        raw = SimRawResults(
            l1_cost=np.zeros(100), l1_buckets=np.zeros((100, 1)),
            ev_costs=np.zeros((100, 0)), n_iter=100, n_risks=0,
        )
        result = compute_rbs_l1_diversification(raw, [], p_level=80)
        assert result["diversification_benefit"] == 0.0


# ---------------------------------------------------------------------------
# compute_rbs_l1_p80_contribution (Euler / component decomposition)
# ---------------------------------------------------------------------------

class TestRBSL1Contribution:

    def test_contributions_reconcile_to_portfolio_p80(self):
        raw, risks = _make_sim(n_iter=100_000)
        rows, summary = compute_rbs_l1_p80_contribution(raw, risks, p_level=80)
        assert summary["portfolio_p80"] > 0
        # Within 1% per spec (band-width tolerance, typically well under 0.5%)
        assert abs(summary["reconciliation_gap_pct"]) < 0.01

    def test_shares_sum_to_100(self):
        raw, risks = _make_sim(n_iter=100_000)
        rows, _ = compute_rbs_l1_p80_contribution(raw, risks, p_level=80)
        share_sum = sum(r["share_pct"] for r in rows)
        assert share_sum == pytest.approx(100.0, abs=0.01)

    def test_unassigned_row_absent_when_all_categorised(self):
        raw, risks = _make_sim()
        rows, _ = compute_rbs_l1_p80_contribution(raw, risks, p_level=80)
        labels = [r["rbs_l1"] for r in rows]
        assert "(Unassigned)" not in labels

    def test_unassigned_row_present_when_blank(self):
        raw, risks = _make_sim(with_blank_rbs=True)
        rows, _ = compute_rbs_l1_p80_contribution(raw, risks, p_level=80)
        labels = [r["rbs_l1"] for r in rows]
        assert "(Unassigned)" in labels

    def test_unassigned_row_placed_last(self):
        raw, risks = _make_sim(with_blank_rbs=True)
        rows, _ = compute_rbs_l1_p80_contribution(raw, risks, p_level=80)
        labels = [r["rbs_l1"] for r in rows]
        assert labels[-1] == "(Unassigned)"

    def test_assigned_rows_sorted_by_contribution_desc(self):
        raw, risks = _make_sim(with_blank_rbs=True)
        rows, _ = compute_rbs_l1_p80_contribution(raw, risks, p_level=80)
        assigned = [r for r in rows if r["rbs_l1"] != "(Unassigned)"]
        contribs = [r["contribution"] for r in assigned]
        assert contribs == sorted(contribs, reverse=True)

    def test_band_size_adequate_for_100k(self):
        raw, risks = _make_sim(n_iter=100_000)
        _, summary = compute_rbs_l1_p80_contribution(
            raw, risks, p_level=80, band_halfwidth=1.0)
        # 100k iter * 2pp band ≈ 2000 samples; guardrail is 200
        assert summary["band_n_iterations"] > 200

    def test_empty_risks(self):
        raw = SimRawResults(
            l1_cost=np.zeros(100), l1_buckets=np.zeros((100, 1)),
            ev_costs=np.zeros((100, 0)), n_iter=100, n_risks=0,
        )
        rows, summary = compute_rbs_l1_p80_contribution(raw, [], p_level=80)
        assert rows == []
        assert summary["sum_of_contributions"] == 0.0

    def test_n_risks_populated(self):
        raw, risks = _make_sim()
        rows, _ = compute_rbs_l1_p80_contribution(raw, risks, p_level=80)
        # Every returned row has n_risks matching the category membership
        total_n = sum(r["n_risks"] for r in rows)
        assert total_n == len(risks)
