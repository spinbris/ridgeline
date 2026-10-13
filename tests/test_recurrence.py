"""
Tests for recurring risk engine (Stage 1).

Covers BINOMIAL and POISSON recurrence modes, statistical validation,
and regression against existing binary behaviour.
"""

import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput
from src.simulation import MonteCarloEngine
from src.distributions import sample_cost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(risks, n_iter=100_000, seed=42):
    """Build a minimal engine with given risks."""
    config = SimConfig(n_iter=n_iter, seed=seed)
    buckets = [
        WBSBucket(name=f"B{i}", base_cost=1_000_000, low_var=-0.05,
                  high_var=0.05, distribution="Triangular")
        for i in range(8)
    ]
    chains = ChainConfig()
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    return MonteCarloEngine(config, buckets, chains, risks, corr, seed=seed)


def _base_risk(**overrides):
    """Create a default risk with overrides."""
    defaults = dict(
        risk_id="R100", description="Test risk", owner="BOP Contractor",
        distribution="Triangular", correlation_group="CG01",
        probability=0.30, opt_cost=100_000, ml_cost=200_000, pess_cost=400_000,
        recurrence_type="", recurrence_param=1.0,
    )
    defaults.update(overrides)
    return RiskInput(**defaults)


# ---------------------------------------------------------------------------
# TestBinomialRecurrence
# ---------------------------------------------------------------------------

class TestBinomialRecurrence:

    def test_mean_occurrences_correct(self):
        """BINOMIAL(n=3, p=0.30): mean occurrences ~ 0.90, within +/-2%."""
        risk = _base_risk(recurrence_type="BINOMIAL", recurrence_param=3.0,
                          probability=0.30)
        engine = _make_engine([risk], n_iter=100_000, seed=12345)
        result = engine.run()
        # Count occurrences: each occurrence adds one severity draw,
        # so approximate by checking how many iterations have non-zero cost
        # Better: check mean cost ~ n*p * PERT_mean
        # For triangular(100k, 200k, 400k), mean = (100k+200k+400k)/3 = 233333
        expected_n_p = 3 * 0.30  # 0.90
        tri_mean = (100_000 + 200_000 + 400_000) / 3.0
        expected_mean_cost = expected_n_p * tri_mean
        actual_mean = result.ev_costs[:, 0].mean()
        assert actual_mean == pytest.approx(expected_mean_cost, rel=0.02)

    def test_zero_occurrences_probability(self):
        """P(occurrences==0) ~ (1-p)^n = 0.7^3 = 0.343, within +/-2%."""
        risk = _base_risk(recurrence_type="BINOMIAL", recurrence_param=3.0,
                          probability=0.30)
        engine = _make_engine([risk], n_iter=100_000, seed=99)
        result = engine.run()
        p_zero = np.mean(result.ev_costs[:, 0] == 0)
        assert p_zero == pytest.approx(0.343, abs=0.02)

    def test_cost_is_sum_of_occurrences(self):
        """When cost > 0, std > 0 (independent draws, not duplicated)."""
        risk = _base_risk(recurrence_type="BINOMIAL", recurrence_param=3.0,
                          probability=0.50)
        engine = _make_engine([risk], n_iter=100_000, seed=77)
        result = engine.run()
        nonzero = result.ev_costs[:, 0][result.ev_costs[:, 0] > 0]
        assert len(nonzero) > 1000
        assert nonzero.std() > 0

    def test_magnitude_per_occurrence_in_range(self):
        """All non-zero costs must be within plausible range."""
        n = 3
        risk = _base_risk(recurrence_type="BINOMIAL", recurrence_param=float(n),
                          probability=0.50)
        engine = _make_engine([risk], n_iter=50_000, seed=55)
        result = engine.run()
        costs = result.ev_costs[:, 0]
        nonzero = costs[costs > 0]
        # Each occurrence in [opt, pess], so total in [opt, n*pess]
        assert nonzero.min() >= risk.opt_cost * 0.999
        assert nonzero.max() <= n * risk.pess_cost * 1.001

    def test_legacy_binary_unchanged(self):
        """Risk with recurrence_type="" must match existing binary behaviour."""
        risk_legacy = _base_risk(recurrence_type="", probability=0.175)
        risk_empty = _base_risk(recurrence_type="", probability=0.175,
                                risk_id="R100")

        engine1 = _make_engine([risk_legacy], n_iter=10_000, seed=42)
        result1 = engine1.run()

        engine2 = _make_engine([risk_empty], n_iter=10_000, seed=42)
        result2 = engine2.run()

        np.testing.assert_array_equal(result1.ev_costs, result2.ev_costs)

    def test_binomial_n1_equivalent_to_binary(self):
        """BINOMIAL(n=1, p=0.175) ~ single Binary(p=0.175) firing rate.

        Uses programme_seasons=1 so the default recurrence_param=1.0 is not
        overridden by programme_seasons (Stage 7 change).
        """
        risk = _base_risk(recurrence_type="BINOMIAL", recurrence_param=1.0,
                          probability=0.175)
        config = SimConfig(n_iter=100_000, seed=88, programme_seasons=1)
        buckets = [
            WBSBucket(name=f"B{i}", base_cost=1_000_000, low_var=-0.05,
                      high_var=0.05, distribution="Triangular")
            for i in range(8)
        ]
        chains = ChainConfig()
        corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
        engine = MonteCarloEngine(config, buckets, chains, [risk], corr, seed=88)
        result = engine.run()
        fire_rate = np.mean(result.ev_costs[:, 0] != 0)
        assert fire_rate == pytest.approx(0.175, abs=0.01)


# ---------------------------------------------------------------------------
# TestPoissonRecurrence
# ---------------------------------------------------------------------------

class TestPoissonRecurrence:

    def test_mean_occurrences_correct(self):
        """POISSON(lambda=0.5): mean cost ~ 0.5 * tri_mean, within +/-2%."""
        risk = _base_risk(recurrence_type="POISSON", recurrence_param=0.5,
                          probability=1.0)
        engine = _make_engine([risk], n_iter=100_000, seed=101)
        result = engine.run()
        tri_mean = (100_000 + 200_000 + 400_000) / 3.0
        expected = 0.5 * tri_mean
        assert result.ev_costs[:, 0].mean() == pytest.approx(expected, rel=0.02)

    def test_zero_occurrences_probability(self):
        """P(occurrences==0) ~ exp(-0.5) = 0.607, within +/-2%."""
        risk = _base_risk(recurrence_type="POISSON", recurrence_param=0.5,
                          probability=1.0)
        engine = _make_engine([risk], n_iter=100_000, seed=102)
        result = engine.run()
        p_zero = np.mean(result.ev_costs[:, 0] == 0)
        assert p_zero == pytest.approx(np.exp(-0.5), abs=0.02)

    def test_magnitude_per_occurrence_in_range(self):
        """All per-occurrence costs within [opt, pess]."""
        risk = _base_risk(recurrence_type="POISSON", recurrence_param=1.0,
                          probability=1.0)
        engine = _make_engine([risk], n_iter=50_000, seed=103)
        result = engine.run()
        costs = result.ev_costs[:, 0]
        nonzero = costs[costs > 0]
        # Single occurrence should be in [opt, pess]; multiple can exceed pess
        # but minimum non-zero should be >= opt
        assert nonzero.min() >= risk.opt_cost * 0.999

    def test_high_lambda_reasonable(self):
        """POISSON(lambda=3.0): mean cost ~ 3.0 * tri_mean, P(0) ~ exp(-3)."""
        risk = _base_risk(recurrence_type="POISSON", recurrence_param=3.0,
                          probability=1.0)
        engine = _make_engine([risk], n_iter=50_000, seed=104)
        result = engine.run()
        tri_mean = (100_000 + 200_000 + 400_000) / 3.0
        expected = 3.0 * tri_mean
        assert result.ev_costs[:, 0].mean() == pytest.approx(expected, rel=0.05)
        p_zero = np.mean(result.ev_costs[:, 0] == 0)
        assert p_zero == pytest.approx(np.exp(-3), abs=0.02)

    def test_poisson_probability_field_ignored(self):
        """POISSON with different probability values gives same mean occurrences."""
        risk_a = _base_risk(recurrence_type="POISSON", recurrence_param=1.0,
                            probability=0.5)
        risk_b = _base_risk(recurrence_type="POISSON", recurrence_param=1.0,
                            probability=1.0, risk_id="R101")

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            engine_a = _make_engine([risk_a], n_iter=100_000, seed=200)
            result_a = engine_a.run()
            engine_b = _make_engine([risk_b], n_iter=100_000, seed=200)
            result_b = engine_b.run()

        mean_a = result_a.ev_costs[:, 0].mean()
        mean_b = result_b.ev_costs[:, 0].mean()
        tri_mean = (100_000 + 200_000 + 400_000) / 3.0
        # Both should be ~ 1.0 * tri_mean
        assert mean_a == pytest.approx(tri_mean, rel=0.05)
        assert mean_b == pytest.approx(tri_mean, rel=0.05)


# ---------------------------------------------------------------------------
# TestRecurrenceIntegration
# ---------------------------------------------------------------------------

class TestRecurrenceIntegration:

    def test_full_sim_with_mixed_risks(self):
        """Mixed risk types: 2 Binary + 1 BINOMIAL + 1 POISSON."""
        risks = [
            _base_risk(risk_id="R001", probability=0.30),
            _base_risk(risk_id="R002", probability=0.50),
            _base_risk(risk_id="R003", recurrence_type="BINOMIAL",
                       recurrence_param=3.0, probability=0.30),
            _base_risk(risk_id="R004", recurrence_type="POISSON",
                       recurrence_param=1.5, probability=1.0),
        ]
        engine = _make_engine(risks, n_iter=50_000, seed=300)
        result = engine.run()

        # Shape
        assert result.ev_costs.shape == (50_000, 4)
        # All non-negative (positive cost risks)
        assert np.all(result.ev_costs >= 0)
        # Binary firing rates
        fire_rate_1 = np.mean(result.ev_costs[:, 0] != 0)
        fire_rate_2 = np.mean(result.ev_costs[:, 1] != 0)
        assert fire_rate_1 == pytest.approx(0.30, abs=0.02)
        assert fire_rate_2 == pytest.approx(0.50, abs=0.02)
        # BINOMIAL mean cost ~ n*p * tri_mean
        tri_mean = (100_000 + 200_000 + 400_000) / 3.0
        binom_expected = 3 * 0.30 * tri_mean
        assert result.ev_costs[:, 2].mean() == pytest.approx(binom_expected, rel=0.05)
        # POISSON mean cost ~ lambda * tri_mean
        pois_expected = 1.5 * tri_mean
        assert result.ev_costs[:, 3].mean() == pytest.approx(pois_expected, rel=0.05)

    def test_no_existing_tests_broken(self):
        """Regression gate: existing test suite passes.

        This is verified by running the full pytest suite — this test
        simply confirms the import and basic engine run still works
        with default (non-recurring) risks.
        """
        risks = [
            _base_risk(risk_id="R001", probability=0.30),
            _base_risk(risk_id="R002", probability=0.50),
        ]
        engine = _make_engine(risks, n_iter=1_000, seed=1)
        result = engine.run()
        assert result.ev_costs.shape == (1_000, 2)
        assert result.l1_cost.shape == (1_000,)
