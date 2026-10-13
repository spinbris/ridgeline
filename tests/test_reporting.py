"""Tests for src/reporting.py — Stage A EMV credibility bridge."""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import beta as sp_beta

from src.config import RiskInput
from src.reporting import compute_emv_table, compute_emv_bridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_risk(rid, prob, opt, ml, pess, owner="Shared", cg="CG01", desc=""):
    return RiskInput(
        risk_id=rid,
        description=desc or f"Test risk {rid}",
        owner=owner,
        distribution="PERT",
        correlation_group=cg,
        probability=prob,
        opt_cost=opt,
        ml_cost=ml,
        pess_cost=pess,
    )


def _pert_sim_arrays(test_risks, n_iter=100_000, seed=42):
    """Generate synthetic ev_costs using PERT + Bernoulli gate."""
    rng = np.random.default_rng(seed)
    ev_costs = np.zeros((n_iter, len(test_risks)))
    for col, r in enumerate(test_risks):
        fires = rng.random(n_iter) < r.probability
        opt, ml, pess = r.opt_cost, r.ml_cost, r.pess_cost
        span = pess - opt
        if span > 0:
            a_param = 1.0 + 4.0 * (ml - opt) / span
            b_param = 1.0 + 4.0 * (pess - ml) / span
            samples = opt + span * sp_beta.rvs(
                a_param, b_param, size=n_iter, random_state=rng
            )
        else:
            samples = np.full(n_iter, ml)
        ev_costs[:, col] = np.where(fires, samples, 0.0)
    return ev_costs


# ---------------------------------------------------------------------------
# compute_emv_table tests
# ---------------------------------------------------------------------------

class TestComputeEmvTable:

    def test_pert_accuracy(self):
        """MC_Mean within 2% of EMV_PERT for unchained, non-binomial PERT risks."""
        risks = [
            _make_risk("R_T01", 0.50, 0, 100_000, 300_000),
            _make_risk("R_T02", 0.25, 50_000, 200_000, 500_000),
            _make_risk("R_T03", 0.10, 0, 1_000_000, 2_000_000),
        ]
        risk_ids = [r.risk_id for r in risks]
        ev_costs = _pert_sim_arrays(risks, n_iter=100_000, seed=42)

        result = compute_emv_table(risks, ev_costs, risk_ids)

        for _, row in result.iterrows():
            emv_pert = row["EMV_PERT"]
            mc_mean = row["MC_Mean"]
            if emv_pert > 0:
                rel_error = abs(mc_mean - emv_pert) / emv_pert
                assert rel_error < 0.02, (
                    f"{row['RiskID']}: MC_Mean {mc_mean:.0f} vs EMV_PERT "
                    f"{emv_pert:.0f} — relative error {rel_error:.1%} exceeds 2%"
                )

    def test_sorted_descending(self):
        """Output rows are sorted by EMV_Simple descending."""
        risks = [
            _make_risk("R_LO", 0.10, 0, 10_000, 20_000),
            _make_risk("R_HI", 0.80, 0, 500_000, 1_000_000),
        ]
        risk_ids = [r.risk_id for r in risks]
        ev_costs = np.zeros((100, 2))
        result = compute_emv_table(risks, ev_costs, risk_ids)
        assert result.iloc[0]["RiskID"] == "R_HI"

    def test_opportunity_negative_ml(self):
        """Negative ML_Cost (opportunity) flows through with negative EMV."""
        risks = [
            _make_risk("R_OPP", 0.50, -200_000, -100_000, 0),
        ]
        risk_ids = ["R_OPP"]
        ev_costs = np.full((100, 1), -50_000.0)
        result = compute_emv_table(risks, ev_costs, risk_ids)
        assert result.iloc[0]["EMV_Simple"] < 0

    def test_zero_probability(self):
        """Risks with Prob=0 produce EMV=0 and are included."""
        risks = [_make_risk("R_ZERO", 0.0, 0, 100_000, 200_000)]
        risk_ids = ["R_ZERO"]
        ev_costs = np.zeros((100, 1))
        result = compute_emv_table(risks, ev_costs, risk_ids)
        assert len(result) == 1
        assert result.iloc[0]["EMV_Simple"] == 0.0
        assert result.iloc[0]["EMV_PERT"] == 0.0

    def test_title_truncation(self):
        """Full descriptions are passed through without truncation."""
        long_desc = "A" * 80
        risks = [_make_risk("R_LONG", 0.5, 0, 100_000, 200_000, desc=long_desc)]
        risk_ids = ["R_LONG"]
        ev_costs = np.zeros((10, 1))
        result = compute_emv_table(risks, ev_costs, risk_ids)
        assert len(result.iloc[0]["Title"]) == 80

    def test_missing_risk_id_in_sim_arrays(self):
        """Risk in risks list but not in risk_ids gets MC_Mean=0."""
        risks = [_make_risk("R_MISSING", 0.5, 0, 100_000, 200_000)]
        risk_ids = []  # empty — no matching column
        ev_costs = np.zeros((10, 0))
        result = compute_emv_table(risks, ev_costs, risk_ids)
        assert result.iloc[0]["MC_Mean"] == 0.0

    def test_delta_pct_zero_emv(self):
        """Delta_Pct is 0 when EMV_PERT is 0 (no divide-by-zero)."""
        risks = [_make_risk("R_Z", 0.0, 0, 100_000, 200_000)]
        risk_ids = ["R_Z"]
        ev_costs = np.zeros((10, 1))
        result = compute_emv_table(risks, ev_costs, risk_ids)
        assert result.iloc[0]["Delta_Pct"] == 0.0

    def test_output_columns(self):
        """Output DataFrame has all expected columns."""
        risks = [_make_risk("R_COL", 0.5, 0, 100_000, 200_000)]
        risk_ids = ["R_COL"]
        ev_costs = np.zeros((10, 1))
        result = compute_emv_table(risks, ev_costs, risk_ids)
        expected = {"RiskID", "Title", "Owner", "CG_Group", "Prob_Pct",
                    "EMV_Simple", "EMV_PERT", "MC_Mean", "Delta_PERT_to_MC",
                    "Delta_Pct"}
        assert set(result.columns) == expected


# ---------------------------------------------------------------------------
# compute_emv_bridge tests
# ---------------------------------------------------------------------------

class TestComputeEmvBridge:

    def _sample_df(self):
        return pd.DataFrame({
            "RiskID": ["R1", "R2"],
            "EMV_Simple": [50_000.0, 30_000.0],
            "EMV_PERT": [55_000.0, 35_000.0],
            "MC_Mean": [60_000.0, 40_000.0],
        })

    def test_reconciliation(self):
        """emv_simple + shape + uplift = mc_mean within $1."""
        df = self._sample_df()
        mc_mean = 100_000.0
        bridge = compute_emv_bridge(df, mc_mean)
        total = (bridge["emv_simple_total"]
                 + bridge["segment_distribution_shape"]
                 + bridge["segment_modelling_uplift"])
        assert abs(total - mc_mean) < 1.0

    def test_stage_a_combined_label(self):
        """Without mean_nil_corr, uplift label is 'Correlation and chaining'."""
        df = self._sample_df()
        bridge = compute_emv_bridge(df, 100_000.0)
        assert bridge["combined_uplift_label"] == "Correlation and chaining"
        assert bridge["segment_correlation_premium"] is None
        assert bridge["segment_chaining_other"] is None

    def test_stage_c_split(self):
        """With mean_nil_corr, uplift splits into correlation + chaining."""
        df = self._sample_df()
        mc_mean = 100_000.0
        mean_nil = 92_000.0
        bridge = compute_emv_bridge(df, mc_mean, mean_nil_corr=mean_nil)
        assert bridge["combined_uplift_label"] is None
        assert bridge["segment_correlation_premium"] == mean_nil - bridge["emv_pert_total"]
        assert bridge["segment_chaining_other"] == mc_mean - mean_nil

    def test_opportunity_reduces_totals(self):
        """Negative EMV rows reduce totals."""
        df = pd.DataFrame({
            "RiskID": ["R1", "R_OPP"],
            "EMV_Simple": [100_000.0, -20_000.0],
            "EMV_PERT": [110_000.0, -22_000.0],
            "MC_Mean": [120_000.0, -18_000.0],
        })
        bridge = compute_emv_bridge(df, 90_000.0)
        assert bridge["emv_simple_total"] == 80_000.0

    def test_mc_mean_echoed(self):
        """mc_mean is echoed in the output."""
        df = self._sample_df()
        bridge = compute_emv_bridge(df, 123_456.0)
        assert bridge["mc_mean"] == 123_456.0
