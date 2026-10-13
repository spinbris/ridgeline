"""
Tests for the core Monte Carlo simulation engine.

Validates:
- Layer 1 WBS variation: shape, centred near TIC, bucket impacts
- Layer 2 event risks: firing rates, magnitude ranges, zero-cost risks
- Event chains: Chain 1 (R076→R015), Chain 2 (R017→R018/R019)
- Full integration: combined L1+L2, reproducibility with seed
- Performance: 100k iterations completes in reasonable time
- Edge cases: no risks, all risks prob=0, all risks prob=1
"""

import time
import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput, SimRawResults
from src.simulation import MonteCarloEngine

# RS-B step 2: this module asserts against the reference project's register
# shape, RBS map, chain identifiers or narrative templates, so it selects that
# binding explicitly rather than inheriting the suite default.
pytestmark = pytest.mark.project("synthetic_wind")


# ---------------------------------------------------------------------------
# Fixtures — realistic RefProject-scale test data
# ---------------------------------------------------------------------------

def make_config(**overrides) -> SimConfig:
    defaults = dict(
        n_iter=10_000, tic=300_000_000, contingency=30_000_000,
        bop_contract=300_000_000,
        bop_contingency=5_000_000, cse_contingency=5_000_000,
    )
    defaults.update(overrides)
    return SimConfig(**defaults)


def make_buckets() -> list[WBSBucket]:
    """8 WBS buckets matching MC_Params."""
    return [
        WBSBucket("Concrete/Civil",    55_000_000, -0.10, 0.20, "Triangular"),
        WBSBucket("Structural Steel",  30_000_000, -0.05, 0.25, "Triangular"),
        WBSBucket("Piping",            35_000_000, -0.05, 0.20, "Triangular"),
        WBSBucket("E&I",               40_000_000, -0.05, 0.20, "Triangular"),
        WBSBucket("Mech/GEV",          60_000_000, -0.03, 0.12, "Triangular"),
        WBSBucket("Turnkey Pkg",       35_000_000, -0.05, 0.15, "Triangular"),
        WBSBucket("Labour Rate",       30_000_000, -0.05, 0.25, "Lognormal"),
        WBSBucket("Labour Prod",       15_000_000, -0.05, 0.15, "PERT"),
    ]


def make_chains() -> ChainConfig:
    return ChainConfig(
        c1_trigger_months=3.0, c1_amplification=2.5,
        c2_trigger_weeks=2.0, c2_cascade_factor=1.5,
    )


def make_corr_coefficients() -> dict[str, float]:
    return {
        "CG01": 0.6, "CG02": 0.5, "CG03": 0.5, "CG04": 0.4, "CG05": 0.5,
        "CG06": 0.5, "CG07": 0.4, "CG08": 0.4, "CG09": 0.4, "CG10": 0.4,
    }


def make_sample_risks() -> list[RiskInput]:
    """A small set of risks covering key scenarios."""
    return [
        RiskInput("R015", "Inclement weather overrun", "BOP Contractor",
                  "Triangular", "CG06", 0.175,
                  350_000, 1_000_000, 2_000_000),
        RiskInput("R017", "Site establishment delay", "BOP Contractor",
                  "Triangular", "CG05", 0.175,
                  6_125_000, 12_250_000, 25_000_000),
        RiskInput("R018", "Turnkey buildings delay", "BOP Contractor",
                  "Triangular", "CG05", 0.175,
                  500_000, 1_500_000, 3_000_000),
        RiskInput("R019", "GTG civil foundations delay", "Shared",
                  "Triangular", "CG05", 0.175,
                  1_000_000, 3_000_000, 8_000_000),
        RiskInput("R076", "Regulatory/planning delay", "Owner",
                  "Triangular", "CG07", 0.175,
                  875_000, 2_100_000, 5_000_000),
        # An opportunity (negative cost)
        RiskInput("R003", "Ground condition de-risk", "BOP Contractor",
                  "Triangular", "CG01", 0.755,
                  -50_000, -200_000, -400_000),
    ]


# ---------------------------------------------------------------------------
# Layer 1 tests
# ---------------------------------------------------------------------------

class TestLayer1:

    def test_output_shape(self):
        config = make_config(n_iter=1000)
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), [], {}, seed=42,
        )
        result = engine.run()
        assert result.l1_cost.shape == (1000,)
        assert result.l1_buckets.shape == (1000, 8)

    def test_mean_near_tic(self):
        """L1 cost mean should be near TIC (slightly above due to right-skew)."""
        config = make_config(n_iter=50_000)
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), [], {}, seed=42,
        )
        result = engine.run()
        mean = np.mean(result.l1_cost)
        # Distributions are right-skewed (e.g. -10% to +20%), so mean is above TIC.
        # Mean variation ~$29M on $300M TIC (~10%) is expected. Allow up to 12%.
        assert abs(mean - config.tic) / config.tic < 0.12

    def test_variation_reasonable(self):
        """L1 std should be on the order of millions, not zero or billions."""
        config = make_config(n_iter=30_000)
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), [], {}, seed=42,
        )
        result = engine.run()
        std = np.std(result.l1_cost)
        # Expect std in the $5M–$30M range for $300M TIC with ±5-25% variation
        assert 2_000_000 < std < 50_000_000

    def test_buckets_sum_to_variation(self):
        """Sum of bucket variations should equal l1_cost - TIC."""
        config = make_config(n_iter=5000)
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), [], {}, seed=42,
        )
        result = engine.run()
        bucket_sum = result.l1_buckets.sum(axis=1)
        variation = result.l1_cost - config.tic
        np.testing.assert_allclose(bucket_sum, variation, atol=1.0)


# ---------------------------------------------------------------------------
# Layer 2 tests
# ---------------------------------------------------------------------------

class TestLayer2:

    def test_output_shape(self):
        config = make_config(n_iter=5000)
        risks = make_sample_risks()
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks,
            make_corr_coefficients(), seed=42,
        )
        result = engine.run()
        assert result.ev_costs.shape == (5000, len(risks))

    def test_firing_rate_approximate(self):
        """Risks with prob=0.175 should fire ~17.5% of iterations."""
        config = make_config(n_iter=100_000)
        risks = [RiskInput("R099", "Test risk", "BOP Contractor",
                           "Triangular", "CG01", 0.175,
                           100_000, 500_000, 1_000_000)]
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks,
            make_corr_coefficients(), seed=42,
        )
        result = engine.run()
        fired = np.sum(result.ev_costs[:, 0] != 0) / config.n_iter
        assert fired == pytest.approx(0.175, abs=0.015)

    def test_magnitude_in_range(self):
        """Fired events should have costs within [opt, pess]."""
        config = make_config(n_iter=50_000)
        risks = [RiskInput("R099", "Test", "BOP Contractor",
                           "Triangular", "CG01", 0.50,
                           100_000, 500_000, 1_000_000)]
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks,
            make_corr_coefficients(), seed=42,
        )
        result = engine.run()
        fired_costs = result.ev_costs[:, 0][result.ev_costs[:, 0] != 0]
        assert len(fired_costs) > 0
        assert np.all(fired_costs >= 100_000)
        assert np.all(fired_costs <= 1_000_000)

    def test_opportunity_negative_costs(self):
        """Opportunity risk should produce negative (beneficial) costs."""
        config = make_config(n_iter=50_000)
        risks = [RiskInput("R003", "Opportunity", "BOP Contractor",
                           "Triangular", "CG01", 0.755,
                           -50_000, -200_000, -400_000)]
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks,
            make_corr_coefficients(), seed=42,
        )
        result = engine.run()
        fired_costs = result.ev_costs[:, 0][result.ev_costs[:, 0] != 0]
        assert len(fired_costs) > 0
        assert np.all(fired_costs <= 0), "Opportunity should be negative"

    def test_zero_probability_never_fires(self):
        """Risk with prob=0 should never fire."""
        config = make_config(n_iter=10_000)
        risks = [RiskInput("R099", "Zero prob", "BOP Contractor",
                           "Triangular", "CG01", 0.0,
                           100_000, 500_000, 1_000_000)]
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks, {}, seed=42,
        )
        result = engine.run()
        assert np.all(result.ev_costs[:, 0] == 0)

    def test_certain_event_always_fires(self):
        """Risk with prob=1.0 should fire every iteration."""
        config = make_config(n_iter=10_000)
        risks = [RiskInput("R099", "Certain", "BOP Contractor",
                           "Triangular", "CG01", 1.0,
                           100_000, 500_000, 1_000_000)]
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks, {}, seed=42,
        )
        result = engine.run()
        assert np.all(result.ev_costs[:, 0] != 0)

    def test_no_risks(self):
        """Empty risk list → ev_costs has zero columns."""
        config = make_config(n_iter=1000)
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), [], {}, seed=42,
        )
        result = engine.run()
        assert result.ev_costs.shape == (1000, 0)
        assert result.n_risks == 0


# ---------------------------------------------------------------------------
# Event chain tests
# ---------------------------------------------------------------------------

#: REFRETIRE-01: the chain roles these two tests exercise were read from a project binding's
#: legacy chain map, so they only ran with that project selected. The engine takes the map as an
#: argument; the tests declare their own, and the chain machinery is what is under test.
TEST_CHAIN_RISK_IDS = {
    "c1_trigger": "R076", "c1_target": "R015",
    "c2_trigger": "R017", "c2_targets": ["R018", "R019"],
}


class TestChain1:
    """Chain 1: a trigger risk amplifies its target."""

    def test_chain_amplifies_weather(self):
        """When R076 fires heavily, R015 should fire more often than baseline."""
        config = make_config(n_iter=100_000)
        risks = [
            RiskInput("R076", "Planning delay", "Owner",
                      "Triangular", "CG07", 0.80,  # high prob to trigger often
                      875_000, 2_100_000, 5_000_000),
            RiskInput("R015", "Weather overrun", "BOP Contractor",
                      "Triangular", "CG06", 0.10,  # low baseline
                      350_000, 1_000_000, 2_000_000),
        ]
        chains = ChainConfig(
            c1_trigger_months=1.0,  # low threshold to trigger easily
            c1_amplification=2.5,
            c2_trigger_weeks=2.0, c2_cascade_factor=1.5,
        )
        engine = MonteCarloEngine(
            config, make_buckets(), chains, risks,
            make_corr_coefficients(), seed=42,
            chain_risk_ids=dict(TEST_CHAIN_RISK_IDS),
        )
        result = engine.run()

        # Weather firing rate should be above baseline 10%
        weather_fired = np.sum(result.ev_costs[:, 1] != 0) / config.n_iter
        assert weather_fired > 0.12, (
            f"Chain should amplify weather firing rate above 10%, got {weather_fired:.3f}"
        )

    def test_no_chain_without_trigger_risk(self):
        """If R076 not in risk list, chain does nothing."""
        config = make_config(n_iter=10_000)
        risks = [
            RiskInput("R015", "Weather", "BOP Contractor",
                      "Triangular", "CG06", 0.175,
                      350_000, 1_000_000, 2_000_000),
        ]
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks, {}, seed=42,
        )
        result = engine.run()
        fired = np.sum(result.ev_costs[:, 0] != 0) / config.n_iter
        # Should be close to baseline 17.5%
        assert fired == pytest.approx(0.175, abs=0.02)


class TestChain2:
    """Chain 2: R017 site estab → R018/R019 cascade."""

    def test_chain_amplifies_downstream(self):
        """When R017 fires heavily, R018/R019 should fire more often."""
        config = make_config(n_iter=100_000)
        risks = [
            RiskInput("R017", "Site estab delay", "BOP Contractor",
                      "Triangular", "CG05", 0.80,  # high prob
                      6_125_000, 12_250_000, 25_000_000),
            RiskInput("R018", "Turnkey buildings", "BOP Contractor",
                      "Triangular", "CG05", 0.10,  # low baseline
                      500_000, 1_500_000, 3_000_000),
            RiskInput("R019", "GTG civil delay", "Shared",
                      "Triangular", "CG05", 0.10,  # low baseline
                      1_000_000, 3_000_000, 8_000_000),
        ]
        chains = ChainConfig(
            c1_trigger_months=3.0, c1_amplification=2.5,
            c2_trigger_weeks=0.5,  # low threshold
            c2_cascade_factor=1.5,
        )
        engine = MonteCarloEngine(
            config, make_buckets(), chains, risks,
            make_corr_coefficients(), seed=42,
            chain_risk_ids=dict(TEST_CHAIN_RISK_IDS),
        )
        result = engine.run()

        r018_fired = np.sum(result.ev_costs[:, 1] != 0) / config.n_iter
        r019_fired = np.sum(result.ev_costs[:, 2] != 0) / config.n_iter
        assert r018_fired > 0.12, f"R018 should be amplified, got {r018_fired:.3f}"
        assert r019_fired > 0.12, f"R019 should be amplified, got {r019_fired:.3f}"

    def test_no_chain_when_r017_absent(self):
        """Without R017, R018 fires at baseline rate."""
        config = make_config(n_iter=50_000)
        risks = [
            RiskInput("R018", "Turnkey buildings", "BOP Contractor",
                      "Triangular", "CG05", 0.175,
                      500_000, 1_500_000, 3_000_000),
        ]
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks, {}, seed=42,
        )
        result = engine.run()
        fired = np.sum(result.ev_costs[:, 0] != 0) / config.n_iter
        assert fired == pytest.approx(0.175, abs=0.02)


# ---------------------------------------------------------------------------
# Full integration
# ---------------------------------------------------------------------------

class TestFullSimulation:

    def test_combined_output_shape(self):
        config = make_config(n_iter=5000)
        risks = make_sample_risks()
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks,
            make_corr_coefficients(), seed=42,
        )
        result = engine.run()
        assert result.l1_cost.shape == (5000,)
        assert result.l1_buckets.shape == (5000, 8)
        assert result.ev_costs.shape == (5000, len(risks))
        assert result.n_iter == 5000
        assert result.n_risks == len(risks)

    def test_total_cost_reasonable(self):
        """Total outturn (L1 + L2) should be above TIC on average."""
        config = make_config(n_iter=30_000)
        risks = make_sample_risks()
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks,
            make_corr_coefficients(), seed=42,
        )
        result = engine.run()
        total = result.l1_cost + result.ev_costs.sum(axis=1)
        # Mean total should be above TIC (positive risk premium)
        assert np.mean(total) > config.tic

    def test_reproducible_with_seed(self):
        """Same seed → identical results."""
        config = make_config(n_iter=5000)
        risks = make_sample_risks()

        engine1 = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks,
            make_corr_coefficients(), seed=123,
        )
        r1 = engine1.run()

        engine2 = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks,
            make_corr_coefficients(), seed=123,
        )
        r2 = engine2.run()

        np.testing.assert_array_equal(r1.l1_cost, r2.l1_cost)
        np.testing.assert_array_equal(r1.ev_costs, r2.ev_costs)

    def test_different_seeds_differ(self):
        """Different seeds → different results."""
        config = make_config(n_iter=1000)
        risks = make_sample_risks()

        engine1 = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks,
            make_corr_coefficients(), seed=1,
        )
        r1 = engine1.run()

        engine2 = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks,
            make_corr_coefficients(), seed=2,
        )
        r2 = engine2.run()

        assert not np.array_equal(r1.l1_cost, r2.l1_cost)


class TestPerformance:

    @pytest.mark.wallclock  # measures the box, not the code: reds under -n auto
    def test_100k_iterations_under_15_seconds(self):
        """100k iterations should complete in reasonable time."""
        config = make_config(n_iter=100_000)
        risks = make_sample_risks()
        engine = MonteCarloEngine(
            config, make_buckets(), make_chains(), risks,
            make_corr_coefficients(), seed=42,
        )

        start = time.time()
        result = engine.run()
        elapsed = time.time() - start

        assert result.n_iter == 100_000
        assert elapsed < 15.0, f"100k iterations took {elapsed:.1f}s (target: <15s)"
        print(f"\n  100k iterations completed in {elapsed:.2f}s")
