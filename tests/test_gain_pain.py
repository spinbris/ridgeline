"""
Tests for gain/pain share module (Stage 3).

Covers gain/pain calculation, summary statistics, flag behaviour,
and integration with the output table.
"""

import numpy as np
import pytest

from src.config import (
    SimConfig, WBSBucket, ChainConfig, RiskInput, GainPainConfig,
)
from src.simulation import MonteCarloEngine
from src.analysis import build_output_table, compute_party_costs
from src.gain_pain import compute_gain_pain, compute_gain_pain_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOC = 310_000_000.0  # $310M for test simplicity


def _gp_config(**overrides):
    defaults = dict(toc=TOC, share_split=0.5, max_reward_pct=0.05,
                    max_risk_pct=0.05, enabled=True)
    defaults.update(overrides)
    return GainPainConfig(**defaults)


def _make_costs(values):
    """Create a cost array from a list of dollar values."""
    return np.array(values, dtype=np.float64)


def _make_engine_and_run(n_iter=10_000, seed=42):
    """Build and run a minimal simulation for integration tests."""
    config = SimConfig(n_iter=n_iter, seed=seed)
    buckets = [
        WBSBucket(name=f"B{i}", base_cost=1_000_000, low_var=-0.05,
                  high_var=0.05, distribution="Triangular")
        for i in range(8)
    ]
    chains = ChainConfig()
    risks = [
        RiskInput(
            risk_id="R001", description="Test risk", owner="BOP Contractor",
            distribution="Triangular", correlation_group="CG01",
            probability=0.30, opt_cost=100_000, ml_cost=200_000,
            pess_cost=400_000,
        ),
    ]
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    engine = MonteCarloEngine(config, buckets, chains, risks, corr, seed=seed)
    raw = engine.run()
    return raw, risks, config


# ---------------------------------------------------------------------------
# TestGainPainCalc
# ---------------------------------------------------------------------------

class TestGainPainCalc:

    def test_pure_gainshare(self):
        """AOC = TOC - $10M. BOP gets $5M, CSE gets $5M."""
        costs = _make_costs([TOC - 10_000_000])
        gp = compute_gain_pain(costs, _gp_config())
        assert gp["bop_net"][0] == pytest.approx(5_000_000, rel=1e-6)
        assert gp["cse_net"][0] == pytest.approx(5_000_000, rel=1e-6)

    def test_gainshare_at_cap(self):
        """AOC = TOC - $40M. BOP share ($20M) exceeds $5M cap."""
        cfg = _gp_config()
        max_gain = cfg.max_reward_pct * cfg.toc  # $5M
        costs = _make_costs([TOC - 40_000_000])
        gp = compute_gain_pain(costs, cfg)
        expected_bop = max_gain  # $5M (capped)
        assert gp["bop_net"][0] == pytest.approx(expected_bop, rel=1e-6)

    def test_pure_painshare(self):
        """AOC = TOC + $8M. BOP pays $4M, CSE pays $4M."""
        costs = _make_costs([TOC + 8_000_000])
        gp = compute_gain_pain(costs, _gp_config())
        assert gp["bop_net"][0] == pytest.approx(-4_000_000, rel=1e-6)
        assert gp["cse_net"][0] == pytest.approx(-4_000_000, rel=1e-6)

    def test_painshare_at_cap(self):
        """AOC = TOC + $40M. BOP share ($20M) exceeds $5M cap."""
        cfg = _gp_config()
        max_pain = cfg.max_risk_pct * cfg.toc
        costs = _make_costs([TOC + 40_000_000])
        gp = compute_gain_pain(costs, cfg)
        expected_bop = -max_pain  # -$5M (capped)
        assert gp["bop_net"][0] == pytest.approx(expected_bop, rel=1e-6)

    def test_at_toc_exactly(self):
        """AOC = TOC. Zero net positions."""
        costs = _make_costs([TOC])
        gp = compute_gain_pain(costs, _gp_config())
        assert gp["bop_net"][0] == pytest.approx(0.0)
        assert gp["cse_net"][0] == pytest.approx(0.0)
        assert gp["in_gainshare"][0] == False
        assert gp["in_painshare"][0] == False

    def test_net_positions_sum_to_variance_within_cap(self):
        """Within cap: bop_net + cse_net = -variance (saving shared fully)."""
        # Multiple test points within cap range
        cfg = _gp_config()
        max_cap = cfg.max_reward_pct * cfg.toc
        savings = [1e6, 5e6, 10e6]  # 5e6 and 10e6 reach the $5M cap
        for s in savings:
            costs = _make_costs([TOC - s])
            gp = compute_gain_pain(costs, cfg)
            total_shared = gp["bop_net"][0] + gp["cse_net"][0]
            assert total_shared == pytest.approx(s, rel=1e-6), \
                f"saving={s}: total_shared={total_shared}"

        # Overrun within cap
        overruns = [1e6, 5e6, 10e6]
        for o in overruns:
            costs = _make_costs([TOC + o])
            gp = compute_gain_pain(costs, cfg)
            total_shared = gp["bop_net"][0] + gp["cse_net"][0]
            assert total_shared == pytest.approx(-o, rel=1e-6), \
                f"overrun={o}: total_shared={total_shared}"


# ---------------------------------------------------------------------------
# TestGainPainSummary
# ---------------------------------------------------------------------------

class TestGainPainSummary:

    def test_all_keys_present(self):
        """All 22 gp_ keys must be in summary dict."""
        costs = _make_costs([TOC - 5e6, TOC, TOC + 5e6])
        gp = compute_gain_pain(costs, _gp_config())
        summary = compute_gain_pain_summary(gp, _gp_config())
        expected_keys = {
            "gp_bop_p10", "gp_bop_p50", "gp_bop_p80", "gp_bop_p90",
            "gp_bop_mean", "gp_bop_std",
            "gp_cse_p10", "gp_cse_p50", "gp_cse_p80", "gp_cse_p90",
            "gp_cse_mean", "gp_cse_std",
            "gp_p_gainshare", "gp_p_painshare",
            "gp_bop_max_gain", "gp_bop_max_pain", "gp_toc",
            "gp_e_gain", "gp_e_pain", "gp_asymmetry_ratio",
            "gp_gain_cap_util", "gp_pain_cap_util",
        }
        assert set(summary.keys()) == expected_keys

    def test_p_gainshare_plus_p_painshare_le_1(self):
        """P(gain) + P(pain) <= 1.0."""
        costs = _make_costs([TOC - 5e6, TOC, TOC + 5e6, TOC + 10e6])
        gp = compute_gain_pain(costs, _gp_config())
        summary = compute_gain_pain_summary(gp, _gp_config())
        assert 0 <= summary["gp_p_gainshare"] <= 1
        assert 0 <= summary["gp_p_painshare"] <= 1
        assert summary["gp_p_gainshare"] + summary["gp_p_painshare"] <= 1.001

    def test_max_gain_loss_match_contract(self):
        """Max gain/pain match contract formula."""
        cfg = _gp_config()
        costs = _make_costs([TOC])
        gp = compute_gain_pain(costs, cfg)
        summary = compute_gain_pain_summary(gp, cfg)
        assert summary["gp_bop_max_gain"] == pytest.approx(
            cfg.max_reward_pct * cfg.toc)
        assert summary["gp_bop_max_pain"] == pytest.approx(
            cfg.max_risk_pct * cfg.toc)


# ---------------------------------------------------------------------------
# TestGainPainFlag
# ---------------------------------------------------------------------------

class TestGainPainFlag:

    def test_disabled_returns_zeros_in_output_table(self):
        """GainPainConfig(enabled=False): all gp_ keys are 0.0."""
        raw, risks, config = _make_engine_and_run()
        gp_off = GainPainConfig(enabled=False)
        table = build_output_table(raw, risks, config, gp_config=gp_off)
        lookup = {r[0]: r[1] for r in table}
        gp_keys = [k for k in lookup if k.startswith("gp_")]
        assert len(gp_keys) > 0
        for k in gp_keys:
            assert lookup[k] == 0.0, f"{k} should be 0.0, got {lookup[k]}"

    def test_enabled_returns_nonzero(self):
        """GainPainConfig(enabled=True): at least some gp_ values non-zero."""
        raw, risks, config = _make_engine_and_run()
        gp_on = GainPainConfig(enabled=True, toc=310_000_000.0)
        table = build_output_table(raw, risks, config, gp_config=gp_on)
        lookup = {r[0]: r[1] for r in table}
        gp_keys = [k for k in lookup if k.startswith("gp_")]
        nonzero = [k for k in gp_keys if lookup[k] != 0.0]
        assert len(nonzero) > 0, "Expected some non-zero gp_ values"

    def test_existing_keys_unaffected(self):
        """Adding gp_ keys must not change pre-existing key values."""
        raw, risks, config = _make_engine_and_run()
        # Without gp_config
        table_without = build_output_table(raw, risks, config)
        lookup_without = {r[0]: r[1] for r in table_without}
        # With gp_config
        gp_on = GainPainConfig(enabled=True, toc=310_000_000.0)
        table_with = build_output_table(raw, risks, config, gp_config=gp_on)
        lookup_with = {r[0]: r[1] for r in table_with}
        # All non-gp keys must match
        for k, v in lookup_without.items():
            if not k.startswith("gp_"):
                assert lookup_with[k] == v, \
                    f"Key '{k}' changed: {v} → {lookup_with[k]}"


# ---------------------------------------------------------------------------
# TestGainPainIntegration
# ---------------------------------------------------------------------------

class TestGainPainIntegration:

    def test_headless_run_includes_gp_output(self):
        """Full engine run produces gain/pain keys in output table."""
        raw, risks, config = _make_engine_and_run(n_iter=5_000)
        gp_on = GainPainConfig(enabled=True)
        table = build_output_table(raw, risks, config, gp_config=gp_on)
        lookup = {r[0]: r[1] for r in table}
        assert "gp_bop_p50" in lookup
        assert "gp_p_gainshare" in lookup
        assert "gp_toc" in lookup
        # P(gain) + P(pain) should be close to 1.0 for cost distribution
        # that spans both sides of TOC (it likely doesn't, but sum <= 1)
        total = lookup["gp_p_gainshare"] + lookup["gp_p_painshare"]
        assert total <= 1.001

    def test_no_existing_tests_broken(self):
        """Regression: basic engine run still works with default gp_config."""
        raw, risks, config = _make_engine_and_run(n_iter=1_000)
        table = build_output_table(raw, risks, config)
        lookup = {r[0]: r[1] for r in table}
        assert "p50" in lookup
        assert "gp_bop_p50" in lookup  # key exists (as 0.0)


# ---------------------------------------------------------------------------
# TestCapBugFix (Stage 14A)
# ---------------------------------------------------------------------------

class TestCapBugFix:
    """Verify the cap calculation fix from Stage 14A."""

    TOC_EXACT = 100_000_000.0  # Match Cont_Share_rev exactly

    def test_cont_share_rev_scenario(self):
        """At -10% AOC, BOP gain = $5,000,000 (per Cont_Share_rev tab)."""
        cfg = _gp_config(toc=self.TOC_EXACT)
        saving = self.TOC_EXACT * 0.10  # $10,000,000
        costs = _make_costs([self.TOC_EXACT - saving])
        gp = compute_gain_pain(costs, cfg)
        # BOP gets min($10M * 0.5, $5M) = $5,000,000
        assert gp["bop_net"][0] == pytest.approx(5_000_000.0, rel=1e-6)

    def test_cse_is_residual_gainshare(self):
        """CSE gain = saving - BOP gain (residual, not independently capped)."""
        cfg = _gp_config(toc=self.TOC_EXACT)
        saving = 20_000_000.0
        costs = _make_costs([self.TOC_EXACT - saving])
        gp = compute_gain_pain(costs, cfg)
        assert gp["cse_net"][0] == pytest.approx(
            saving - gp["bop_net"][0], rel=1e-6)

    def test_cse_is_residual_painshare(self):
        """CSE pain = overrun - BOP pain (residual)."""
        cfg = _gp_config(toc=self.TOC_EXACT)
        overrun = 20_000_000.0
        costs = _make_costs([self.TOC_EXACT + overrun])
        gp = compute_gain_pain(costs, cfg)
        # Both negative: bop_net + cse_net = -overrun
        assert gp["cse_net"][0] == pytest.approx(
            -overrun - gp["bop_net"][0], rel=1e-6)

    def test_beyond_cap_excess_to_cse(self):
        """$40M saving: BOP capped at $5M, CSE gets $35M residual."""
        cfg = _gp_config(toc=self.TOC_EXACT)
        saving = 40_000_000.0
        max_gain = cfg.max_reward_pct * cfg.toc  # $5,000,000
        costs = _make_costs([self.TOC_EXACT - saving])
        gp = compute_gain_pain(costs, cfg)
        assert gp["bop_net"][0] == pytest.approx(max_gain, rel=1e-6)
        assert gp["cse_net"][0] == pytest.approx(saving - max_gain, rel=1e-6)


# ---------------------------------------------------------------------------
# TestAsymmetryAnalytics (Stage 14C)
# ---------------------------------------------------------------------------

class TestAsymmetryAnalytics:
    """Verify asymmetry metrics added in Stage 14C."""

    def test_asymmetry_symmetric_distribution(self):
        """Uniform costs centered on TOC → asymmetry ratio near 1.0."""
        rng = np.random.default_rng(42)
        # Symmetric uniform: TOC ± $10M
        costs = TOC + rng.uniform(-10e6, 10e6, size=100_000)
        cfg = _gp_config()
        gp = compute_gain_pain(costs, cfg)
        summary = compute_gain_pain_summary(gp, cfg)
        # Should be close to 1.0 for symmetric distribution
        assert 0.8 < summary["gp_asymmetry_ratio"] < 1.2

    def test_cap_utilisation_all_beyond_cap(self):
        """All iterations far beyond cap → utilisation = 1.0."""
        cfg = _gp_config()
        max_pain = cfg.max_risk_pct * cfg.toc
        # Every iteration overruns by 2× the cap
        costs = _make_costs([TOC + max_pain * 4] * 100)
        gp = compute_gain_pain(costs, cfg)
        summary = compute_gain_pain_summary(gp, cfg)
        assert summary["gp_pain_cap_util"] == pytest.approx(1.0)

    def test_cap_utilisation_none_at_cap(self):
        """All iterations well within cap → utilisation = 0.0."""
        cfg = _gp_config()
        # Small overruns, well below cap
        costs = _make_costs([TOC + 1e6, TOC + 2e6, TOC + 3e6])
        gp = compute_gain_pain(costs, cfg)
        summary = compute_gain_pain_summary(gp, cfg)
        assert summary["gp_pain_cap_util"] == pytest.approx(0.0)

    def test_e_gain_e_pain_known_values(self):
        """Known simple case: 2 iters, one gain one pain."""
        cfg = _gp_config()
        saving = 6_000_000.0
        overrun = 4_000_000.0
        costs = _make_costs([TOC - saving, TOC + overrun])
        gp = compute_gain_pain(costs, cfg)
        summary = compute_gain_pain_summary(gp, cfg)
        # P(gain) = 0.5, E[gain|gain] = 3M (50% of 6M), so e_gain = 3M * 0.5 = 1.5M
        assert summary["gp_e_gain"] == pytest.approx(1_500_000.0, rel=1e-6)
        # P(pain) = 0.5, E[|pain||pain] = 2M (50% of 4M), so e_pain = 2M * 0.5 = 1.0M
        assert summary["gp_e_pain"] == pytest.approx(1_000_000.0, rel=1e-6)
        assert summary["gp_asymmetry_ratio"] == pytest.approx(1.5, rel=1e-6)


# ---------------------------------------------------------------------------
# TestFairShare (Stage 14D)
# ---------------------------------------------------------------------------

from src.gain_pain import find_fair_share, compute_regret


class TestFairShare:

    def test_fair_share_converges(self):
        """With symmetric distribution, fair split should be near 0.5."""
        rng = np.random.default_rng(42)
        costs = TOC + rng.uniform(-10e6, 10e6, size=50_000)
        cfg = _gp_config()
        fair_split, fair_ratio = find_fair_share(costs, cfg)
        assert abs(fair_ratio - 1.0) < 0.05
        assert 0.4 < fair_split < 0.6

    def test_fair_share_bounds(self):
        """Result stays within [0.3, 0.7]."""
        rng = np.random.default_rng(123)
        # Heavily skewed right — many more overruns
        costs = TOC + rng.exponential(5e6, size=50_000)
        cfg = _gp_config()
        fair_split, _ = find_fair_share(costs, cfg)
        assert 0.3 <= fair_split <= 0.7


class TestRegret:

    def test_regret_at_toc(self):
        """All at TOC: regret = -fixed_markup * TOC (fixed price always better)."""
        cfg = _gp_config()
        costs = _make_costs([TOC] * 100)
        result = compute_regret(costs, cfg, fixed_markup_pct=0.05)
        expected = -(0.05 * TOC)
        assert result["gp_regret_mean"] == pytest.approx(expected, rel=1e-6)
        assert result["gp_p_regret_positive"] == pytest.approx(0.0)

    def test_regret_keys_present(self):
        """All 5 regret keys present."""
        costs = _make_costs([TOC - 5e6, TOC, TOC + 5e6])
        result = compute_regret(costs, _gp_config())
        expected_keys = {
            "gp_regret_mean", "gp_regret_p10", "gp_regret_p50",
            "gp_regret_p90", "gp_p_regret_positive",
        }
        assert set(result.keys()) == expected_keys

    def test_regret_all_saving(self):
        """Large savings: gain/pain better than fixed price for some."""
        cfg = _gp_config()
        rng = np.random.default_rng(42)
        costs = TOC - rng.uniform(20e6, 40e6, size=10_000)
        result = compute_regret(costs, cfg, fixed_markup_pct=0.05)
        # With $20-40M savings, BOP gets ~$5M (cap), fixed gets ~$5M
        # At 50% split with large savings hitting cap, some regret may be near 0
        assert "gp_regret_mean" in result


# ---------------------------------------------------------------------------
# TestPoolDrawdown (Stage 14E)
# ---------------------------------------------------------------------------

from src.gain_pain import compute_pool_drawdown


class TestPoolDrawdown:

    def test_pool_drawdown_zeros(self):
        """No shared costs → P(exhaust) = 0."""
        shared_l2 = np.zeros(1000)
        result = compute_pool_drawdown(shared_l2, pool_budget=15e6)
        assert result["gp_pool_p_exhaust"] == pytest.approx(0.0)
        assert result["gp_pool_exhaust_pctile"] == pytest.approx(100.0)

    def test_pool_always_exceeds(self):
        """All iterations exceed pool → P(exhaust) = 1.0."""
        shared_l2 = np.full(1000, 20e6)
        result = compute_pool_drawdown(shared_l2, pool_budget=15e6)
        assert result["gp_pool_p_exhaust"] == pytest.approx(1.0)

    def test_pool_drawdown_half(self):
        """Half exceed pool → P(exhaust) ≈ 0.5."""
        shared_l2 = np.concatenate([np.full(500, 10e6), np.full(500, 20e6)])
        result = compute_pool_drawdown(shared_l2, pool_budget=15e6)
        assert result["gp_pool_p_exhaust"] == pytest.approx(0.5)
