"""
Tests for recursive temporal cascade (Stage 2).

Covers cascade group amplification, slip accumulation, flag behaviour,
group isolation, and integration with existing static chains.
"""

from tests.conftest import TEST_CALIBRATION_TOLERANCES
import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput
from src.simulation import MonteCarloEngine
from src.sra.methodology_defaults_reader import build_test_methodology_defaults


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: REFRETIRE-01: the chain roles these tests exercise were read from a project binding's
#: legacy chain map, so the tests only ran with that project selected. They are the test's own
#: now - the engine takes them as an argument, and the machinery is what is under test.
TEST_CHAIN_RISK_IDS = {
    "c1_trigger": "R076", "c1_target": "R015",
    "c2_trigger": "R076", "c2_targets": ["R015"],
}


def _make_engine(risks, n_iter=100_000, seed=42, chains=None):
    """Build a minimal engine with given risks and optional chain config."""
    config = SimConfig(n_iter=n_iter, seed=seed)
    buckets = [
        WBSBucket(name=f"B{i}", base_cost=1_000_000, low_var=-0.05,
                  high_var=0.05, distribution="Triangular")
        for i in range(8)
    ]
    if chains is None:
        chains = ChainConfig()
    corr = {f"CG{i:02d}": 0.5 for i in range(1, 11)}
    return MonteCarloEngine(config, buckets, chains, risks, corr, seed=seed,
                            chain_risk_ids=dict(TEST_CHAIN_RISK_IDS))


def _base_risk(**overrides):
    """Create a default risk with overrides."""
    defaults = dict(
        risk_id="R100", description="Test risk", owner="BOP Contractor",
        distribution="Triangular", correlation_group="CG01",
        probability=0.25, opt_cost=100_000, ml_cost=200_000, pess_cost=400_000,
        recurrence_type="", recurrence_param=1.0,
        cascade_group="", ml_days=0.0,
        opt_schedule_days=0.0, pess_schedule_days=0.0,
    )
    defaults.update(overrides)
    return RiskInput(**defaults)


# ---------------------------------------------------------------------------
# TestCascadeGroupBasic
# ---------------------------------------------------------------------------

class TestCascadeGroupBasic:

    def test_cascade_amplifies_downstream(self):
        """Downstream risk fires more often with cascade enabled."""
        risk_a = _base_risk(
            risk_id="R-WS", probability=0.25,
            recurrence_type="BINOMIAL", recurrence_param=3.0,
            cascade_group="TEST-CASCADE", ml_days=28.0,
            opt_schedule_days=14.0, pess_schedule_days=56.0,
        )
        risk_b = _base_risk(
            risk_id="R-COMM", probability=0.20,
            cascade_group="TEST-CASCADE",
        )

        # With cascade
        chains_on = ChainConfig(cascade_enabled=True)
        engine_on = _make_engine([risk_a, risk_b], n_iter=100_000, seed=42,
                                 chains=chains_on)
        result_on = engine_on.run()
        fire_rate_on = np.mean(result_on.ev_costs[:, 1] != 0)

        # Without cascade
        chains_off = ChainConfig(cascade_enabled=False)
        engine_off = _make_engine([risk_a, risk_b], n_iter=100_000, seed=42,
                                  chains=chains_off)
        result_off = engine_off.run()
        fire_rate_off = np.mean(result_off.ev_costs[:, 1] != 0)

        assert fire_rate_on > fire_rate_off
        # At least 5% uplift
        assert (fire_rate_on - fire_rate_off) > 0.05 * fire_rate_off

    def test_zero_slip_no_amplification(self):
        """Risk A with ml_schedule_days=0: no slip, no amplification."""
        risk_a = _base_risk(
            risk_id="R-A", probability=0.50,
            cascade_group="ZERO-SLIP",
            ml_days=0.0, opt_schedule_days=0.0, pess_schedule_days=0.0,
        )
        risk_b = _base_risk(
            risk_id="R-B", probability=0.20,
            cascade_group="ZERO-SLIP",
        )
        chains = ChainConfig(cascade_enabled=True)
        engine = _make_engine([risk_a, risk_b], n_iter=100_000, seed=55,
                              chains=chains)
        result = engine.run()
        fire_rate_b = np.mean(result.ev_costs[:, 1] != 0)
        # With zero slip, multiplier stays 1.0, so firing rate ~ base prob
        assert fire_rate_b == pytest.approx(0.20, abs=0.02)

    def test_slip_accumulates_across_risks(self):
        """Three risks in cascade: slip from 1 and 2 accumulates for 3."""
        risk_1 = _base_risk(
            risk_id="R1", probability=0.95,  # almost always fires
            cascade_group="ACCUM", ml_days=30.0,
            opt_schedule_days=25.0, pess_schedule_days=40.0,
        )
        risk_2 = _base_risk(
            risk_id="R2", probability=0.95,
            cascade_group="ACCUM", ml_days=45.0,
            opt_schedule_days=35.0, pess_schedule_days=60.0,
        )
        risk_3 = _base_risk(
            risk_id="R3", probability=0.10,
            cascade_group="ACCUM",
        )
        chains = ChainConfig(cascade_enabled=True, cascade_slip_rate=1.5)
        engine = _make_engine([risk_1, risk_2, risk_3], n_iter=100_000,
                              seed=77, chains=chains)
        result = engine.run()
        # With ~75 days accumulated slip, multiplier ~ 1 + (75/90)*1.5 = 2.25
        # adjusted_p ~ min(0.10 * 2.25, 0.95) = 0.225
        fire_rate_3 = np.mean(result.ev_costs[:, 2] != 0)
        assert fire_rate_3 > 0.15  # significantly above base 0.10

    def test_multiplier_capped(self):
        """Even with extreme slip_rate, multiplier cannot exceed cap."""
        risk_a = _base_risk(
            risk_id="R-TRIG", probability=0.95,
            cascade_group="CAP-TEST", ml_days=180.0,
            opt_schedule_days=90.0, pess_schedule_days=360.0,
        )
        risk_b = _base_risk(
            risk_id="R-DOWN", probability=0.30,
            cascade_group="CAP-TEST",
        )
        chains = ChainConfig(
            cascade_enabled=True, cascade_slip_rate=10.0, cascade_slip_cap=3.0,
        )
        engine = _make_engine([risk_a, risk_b], n_iter=100_000, seed=88,
                              chains=chains)
        result = engine.run()
        fire_rate = np.mean(result.ev_costs[:, 1] != 0)
        # Max adjusted_p = min(0.30 * 3.0, 0.95) = 0.90
        assert fire_rate <= 0.92  # within sampling noise of 0.90

    def test_cascade_respects_group_isolation(self):
        """Slip in GROUP-A must not affect GROUP-B."""
        risk_a1 = _base_risk(
            risk_id="R-A1", probability=0.95,
            cascade_group="GROUP-A", ml_days=90.0,
            opt_schedule_days=60.0, pess_schedule_days=120.0,
        )
        risk_a2 = _base_risk(
            risk_id="R-A2", probability=0.10,
            cascade_group="GROUP-A",
        )
        risk_b1 = _base_risk(
            risk_id="R-B1", probability=0.10,
            cascade_group="GROUP-B",
        )
        chains = ChainConfig(cascade_enabled=True, cascade_slip_rate=3.0)
        engine = _make_engine([risk_a1, risk_a2, risk_b1], n_iter=100_000,
                              seed=99, chains=chains)
        result = engine.run()
        # GROUP-A slip should amplify R-A2 but NOT R-B1
        fire_a2 = np.mean(result.ev_costs[:, 1] != 0)
        fire_b1 = np.mean(result.ev_costs[:, 2] != 0)
        assert fire_a2 > 0.15  # amplified well above 0.10
        assert fire_b1 == pytest.approx(0.10, abs=0.02)  # unaffected


# ---------------------------------------------------------------------------
# TestCascadeFlag
# ---------------------------------------------------------------------------

class TestCascadeFlag:

    def test_cascade_off_by_default(self):
        """cascade_enabled=False suppresses cascade logic entirely."""
        risk_a = _base_risk(
            risk_id="R-A", probability=0.50,
            cascade_group="FLAG-TEST", ml_days=60.0,
            opt_schedule_days=30.0, pess_schedule_days=90.0,
        )
        risk_b = _base_risk(
            risk_id="R-B", probability=0.20,
            cascade_group="FLAG-TEST",
        )
        # With cascade_group set but cascade_enabled=False (default)
        engine1 = _make_engine([risk_a, risk_b], n_iter=10_000, seed=42)
        result1 = engine1.run()

        # Same risks but with cascade_group=""
        risk_a2 = _base_risk(
            risk_id="R-A", probability=0.50, ml_days=60.0,
            opt_schedule_days=30.0, pess_schedule_days=90.0,
        )
        risk_b2 = _base_risk(risk_id="R-B", probability=0.20)
        engine2 = _make_engine([risk_a2, risk_b2], n_iter=10_000, seed=42)
        result2 = engine2.run()

        np.testing.assert_array_equal(result1.ev_costs, result2.ev_costs)

    def test_cascade_on_produces_different_results(self):
        """cascade_enabled=True changes results vs disabled."""
        risk_a = _base_risk(
            risk_id="R-WS", probability=0.40,
            recurrence_type="BINOMIAL", recurrence_param=3.0,
            cascade_group="DIFF-TEST", ml_days=28.0,
            opt_schedule_days=14.0, pess_schedule_days=56.0,
        )
        risk_b = _base_risk(
            risk_id="R-COMM", probability=0.20,
            cascade_group="DIFF-TEST",
            opt_cost=500_000, ml_cost=1_500_000, pess_cost=4_000_000,
        )

        chains_off = ChainConfig(cascade_enabled=False)
        engine_off = _make_engine([risk_a, risk_b], n_iter=50_000, seed=42,
                                  chains=chains_off)
        result_off = engine_off.run()

        chains_on = ChainConfig(cascade_enabled=True)
        engine_on = _make_engine([risk_a, risk_b], n_iter=50_000, seed=42,
                                 chains=chains_on)
        result_on = engine_on.run()

        # Arrays should differ
        assert not np.array_equal(result_off.ev_costs, result_on.ev_costs)
        # P90 with cascade should be higher
        total_off = result_off.ev_costs.sum(axis=1)
        total_on = result_on.ev_costs.sum(axis=1)
        p90_off = np.percentile(total_off, 90)
        p90_on = np.percentile(total_on, 90)
        assert p90_on > p90_off

    def test_flag_read_from_chain_config(self):
        """cascade_enabled is an attribute of ChainConfig."""
        chains = ChainConfig()
        assert hasattr(chains, "cascade_enabled")
        assert chains.cascade_enabled is False

    def test_static_chains_still_run(self):
        """Static Chain 1 (R076→R015) still works with cascade addition."""
        r076 = _base_risk(
            risk_id="R076", probability=0.95,
            opt_cost=5_000_000, ml_cost=10_000_000, pess_cost=20_000_000,
        )
        r015 = _base_risk(
            risk_id="R015", probability=0.175,
            opt_cost=1_000_000, ml_cost=3_000_000, pess_cost=8_000_000,
        )
        # No cascade group — just static chains
        chains = ChainConfig(
            c1_trigger_months=3.0, c1_amplification=2.5,
            cascade_enabled=False,
        )
        engine = _make_engine([r076, r015], n_iter=100_000, seed=42,
                              chains=chains)
        result = engine.run()
        # R015 should fire more than base 17.5% due to Chain 1 amplification
        fire_rate_015 = np.mean(result.ev_costs[:, 1] != 0)
        assert fire_rate_015 > 0.20  # amplified above base

    def test_cascade_produces_higher_p90_than_static(self):
        """Cascade raises tail exposure: P90(cascade) > P90(no cascade)."""
        risk_ws = _base_risk(
            risk_id="R-WS", probability=0.25,
            recurrence_type="BINOMIAL", recurrence_param=3.0,
            cascade_group="WS-CASCADE", ml_days=28.0,
            opt_schedule_days=14.0, pess_schedule_days=56.0,
            opt_cost=200_000, ml_cost=500_000, pess_cost=1_200_000,
        )
        risk_comm = _base_risk(
            risk_id="R-COMM", probability=0.20,
            cascade_group="WS-CASCADE",
            opt_cost=500_000, ml_cost=1_500_000, pess_cost=4_000_000,
        )

        # Without cascade
        risk_ws_nc = _base_risk(
            risk_id="R-WS", probability=0.25,
            recurrence_type="BINOMIAL", recurrence_param=3.0,
            opt_cost=200_000, ml_cost=500_000, pess_cost=1_200_000,
            ml_days=28.0,
        )
        risk_comm_nc = _base_risk(
            risk_id="R-COMM", probability=0.20,
            opt_cost=500_000, ml_cost=1_500_000, pess_cost=4_000_000,
        )

        chains_off = ChainConfig(cascade_enabled=False)
        engine_off = _make_engine([risk_ws_nc, risk_comm_nc], n_iter=100_000,
                                  seed=42, chains=chains_off)
        result_off = engine_off.run()

        chains_on = ChainConfig(cascade_enabled=True)
        engine_on = _make_engine([risk_ws, risk_comm], n_iter=100_000,
                                 seed=42, chains=chains_on)
        result_on = engine_on.run()

        total_off = result_off.ev_costs.sum(axis=1)
        total_on = result_on.ev_costs.sum(axis=1)
        p90_off = np.percentile(total_off, 90)
        p90_on = np.percentile(total_on, 90)

        print(f"\n  P90 without cascade: ${p90_off/1e6:.3f}M")
        print(f"  P90 with cascade:    ${p90_on/1e6:.3f}M")
        print(f"  Uplift:              ${(p90_on - p90_off)/1e6:.3f}M "
              f"({(p90_on/p90_off - 1)*100:.1f}%)")

        assert p90_on > p90_off


# ---------------------------------------------------------------------------
# TestCascadeIntegration
# ---------------------------------------------------------------------------

class TestCascadeIntegration:

    def test_full_run_with_cascade_risks(self):
        """Realistic mini-register with cascade and independent risks."""
        risk_ws = _base_risk(
            risk_id="R-WS", probability=0.25,
            recurrence_type="BINOMIAL", recurrence_param=3.0,
            cascade_group="WS-CASCADE", ml_days=28.0,
            opt_schedule_days=14.0, pess_schedule_days=60.0,
            opt_cost=200_000, ml_cost=500_000, pess_cost=1_200_000,
        )
        risk_comm = _base_risk(
            risk_id="R-COMM", probability=0.20,
            cascade_group="WS-CASCADE",
            opt_cost=500_000, ml_cost=1_500_000, pess_cost=4_000_000,
        )
        risk_geo = _base_risk(
            risk_id="R-GEO", probability=0.15,
            opt_cost=300_000, ml_cost=800_000, pess_cost=2_000_000,
        )

        chains = ChainConfig(cascade_enabled=True)
        engine = _make_engine([risk_ws, risk_comm, risk_geo], n_iter=100_000,
                              seed=42, chains=chains)
        result = engine.run()

        # Shape
        assert result.ev_costs.shape == (100_000, 3)
        # All non-negative
        assert np.all(result.ev_costs >= 0)

        # R-COMM fires more with cascade than base probability
        fire_comm = np.mean(result.ev_costs[:, 1] != 0)
        assert fire_comm > 0.20  # amplified above base

        # R-GEO unaffected
        fire_geo = np.mean(result.ev_costs[:, 2] != 0)
        assert fire_geo == pytest.approx(0.15, abs=0.02)

        # Print P-values
        total = result.ev_costs.sum(axis=1)
        p10 = np.percentile(total, 10)
        p50 = np.percentile(total, 50)
        p90 = np.percentile(total, 90)
        print(f"\n  Integration P10: ${p10/1e6:.3f}M")
        print(f"  Integration P50: ${p50/1e6:.3f}M")
        print(f"  Integration P90: ${p90/1e6:.3f}M")

    def test_no_existing_tests_broken(self):
        """Regression gate: basic engine run with default risks still works."""
        risks = [
            _base_risk(risk_id="R001", probability=0.30),
            _base_risk(risk_id="R002", probability=0.50),
        ]
        engine = _make_engine(risks, n_iter=1_000, seed=1)
        result = engine.run()
        assert result.ev_costs.shape == (1_000, 2)
        assert result.l1_cost.shape == (1_000,)


# ---------------------------------------------------------------------------
# SP18c — Integrated engine cascade activation
# ---------------------------------------------------------------------------

import warnings as _warnings  # noqa: E402

import pandas as pd  # noqa: E402
from tests._fixture_values import FIXTURE_DAY_RATE

from dataclasses import replace  # noqa: E402

# RS-B step 2: this module asserts against the reference project's register
# shape, RBS map, chain identifiers or narrative templates, so it selects that
# binding explicitly rather than inheriting the suite default.
pytestmark = pytest.mark.project("synthetic_wind")


def _make_dual_scope_df(risk_ids, mode="Series", probability_time=0.5,
                       opt_days=2.0, ml_days=10.0, pess_days=30.0):
    """Build a minimal Risk_Scope DataFrame for the integrated engine."""
    return pd.DataFrame({
        "risk_id": list(risk_ids),
        "time_impact": ["Yes"] * len(risk_ids),
        "probability_time": [probability_time] * len(risk_ids),
        "mode_aggregated": [mode] * len(risk_ids),
        "opt_days": [opt_days] * len(risk_ids),
        "ml_days": [ml_days] * len(risk_ids),
        "pess_days": [pess_days] * len(risk_ids),
    })


def _integrated_config(n_iter=2_000, seed=42, **kwargs):
    """Build an IntegratedConfig for cascade tests with safe defaults."""
    from pathlib import Path

    from src.integrated.integrated_simulation import IntegratedConfig
    kwargs = {**TEST_CALIBRATION_TOLERANCES, **kwargs}  # RS-D-2: required fields; a test may override
    cfg = IntegratedConfig(
        register_path=Path("nonexistent_register.xlsx"),
        p6_path=Path("nonexistent_p6.xer"),
        strawman_path=Path("nonexistent_strawman.xlsx"),
        iterations=n_iter,
        random_seed=seed,
        **kwargs,
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
    )
    return cfg


def _cascade_risks(n=2, group="GROUP_A", seed_offset=0):
    """Two-risk cascade group with deterministic schedule impact."""
    risks = []
    for i in range(n):
        risks.append(_base_risk(
            risk_id=f"RC{i+1+seed_offset:02d}",
            description=f"cascade risk {i+1}",
            distribution="PERT",
            correlation_group="CG01",
            probability=0.6,
            opt_cost=200_000, ml_cost=500_000, pess_cost=1_000_000,
            cascade_group=group,
            ml_days=20.0,
            opt_schedule_days=10.0,
            pess_schedule_days=40.0,
        ))
    return risks


class TestCascadeIntegratedEngine:

    def test_integrated_cascade_off_matches_no_cascade(self):
        # cascade_enabled=False ⇒ no cascade activity ⇒ output identical to a
        # run with cascade-related fields absent on the risks.
        from src.integrated.integrated_simulation import run_integrated_simulation
        risks = _cascade_risks(2, group="GA")
        scope_df = _make_dual_scope_df([r.risk_id for r in risks])
        cfg = _integrated_config(cascade_enabled=False)
        result = run_integrated_simulation(cfg, risks, scope_df)
        assert "cascade_audit" in result
        assert result["cascade_audit"] == []
        assert result["cascade_n_groups"] == 0  # disabled ⇒ kernel not invoked

    def test_integrated_cascade_on_changes_p90(self):
        from src.integrated.integrated_simulation import run_integrated_simulation
        risks = _cascade_risks(2, group="GA")
        scope_df = _make_dual_scope_df([r.risk_id for r in risks])
        cfg_off = _integrated_config(cascade_enabled=False)
        cfg_on = _integrated_config(cascade_enabled=True)
        out_off = run_integrated_simulation(cfg_off, risks, scope_df)
        out_on = run_integrated_simulation(cfg_on, risks, scope_df)
        p90_off = float(np.percentile(out_off["cost_dollars_array"], 90))
        p90_on = float(np.percentile(out_on["cost_dollars_array"], 90))
        # With one cascade group containing two dual-coded risks the second
        # risk gets resampled with elevated P and scaled cost on iterations
        # where the first fires. P90 must move upward.
        assert p90_on > p90_off, (
            f"Cascade-on P90 {p90_on:.0f} should exceed cascade-off P90 {p90_off:.0f}"
        )

    def test_audit_log_populated(self):
        from src.integrated.integrated_simulation import run_integrated_simulation
        risks = _cascade_risks(2, group="GB")
        scope_df = _make_dual_scope_df([r.risk_id for r in risks])
        cfg = _integrated_config(n_iter=5_000, cascade_enabled=True)
        out = run_integrated_simulation(cfg, risks, scope_df)
        audit = out["cascade_audit"]
        assert len(audit) > 0, "cascade_audit must be populated when cascade fires"
        assert len(audit) <= cfg.cascade_audit_sample_cap
        # Documented keys
        for ev in audit:
            for key in ("parent", "child", "iteration", "running_slip_days",
                        "p_before", "p_after", "cost_scale", "fired",
                        "cascade_group"):
                assert key in ev, f"audit event missing key {key!r}: {ev}"

    def test_overlap_warnings_field_default_empty(self):
        from src.integrated.integrated_simulation import run_integrated_simulation
        risks = _cascade_risks(2, group="GC")
        scope_df = _make_dual_scope_df([r.risk_id for r in risks])
        cfg = _integrated_config(cascade_enabled=True)
        out = run_integrated_simulation(cfg, risks, scope_df)
        # Integrated engine doesn't yet consume Risk_Network_Edges; the
        # detector is called with edges=[] so the result is empty by design.
        assert out["overlap_warnings"] == []


class TestCascadeModeInteraction:

    def test_option_A_default_uses_mode_multiplied_days(self):
        # With Mode=Hybrid (multiplier 0.5), Option A propagates 0.5×ml_days
        # of slip. Compared to Option B (raw days), the cascade effect on the
        # downstream P90 should be smaller.
        from src.integrated.integrated_simulation import run_integrated_simulation
        risks = _cascade_risks(2, group="MA")
        scope_df = _make_dual_scope_df(
            [r.risk_id for r in risks], mode="Hybrid",
        )
        cfg_a = _integrated_config(cascade_enabled=True, cascade_use_raw_days=False)
        cfg_b = _integrated_config(cascade_enabled=True, cascade_use_raw_days=True)
        out_a = run_integrated_simulation(cfg_a, risks, scope_df)
        out_b = run_integrated_simulation(cfg_b, risks, scope_df)
        p90_a = float(np.percentile(out_a["cost_dollars_array"], 90))
        p90_b = float(np.percentile(out_b["cost_dollars_array"], 90))
        # Option B (raw days) propagates more slip ⇒ larger downstream P90.
        # Allow a small tolerance because the cascade kernel uses fresh
        # uniforms whose per-iteration realisations differ between runs.
        assert p90_b >= p90_a - 5_000.0

    def test_option_B_flag_propagates_raw_days(self):
        from src.integrated.integrated_simulation import run_integrated_simulation
        risks = _cascade_risks(2, group="MB")
        scope_df = _make_dual_scope_df([r.risk_id for r in risks], mode="Hybrid")
        cfg_b = _integrated_config(cascade_enabled=True, cascade_use_raw_days=True)
        out_b = run_integrated_simulation(cfg_b, risks, scope_df)
        # Audit log echoes the cascade_use_raw_days flag back via the result
        assert out_b["cascade_use_raw_days"] is True

    def test_mode_unchanged_for_non_cascade_risks(self):
        # Risk without cascade_group must see Mode-multiplied schedule impact
        # regardless of cascade_use_raw_days. The flag governs cascade
        # propagation, not schedule-axis reporting in general.
        from src.integrated.integrated_simulation import run_integrated_simulation
        # Single dual-coded risk, no cascade group, Mode=Parallel (multiplier 0)
        risks = [_base_risk(
            risk_id="R900", probability=1.0,
            opt_cost=100_000, ml_cost=200_000, pess_cost=300_000,
            ml_days=20.0, opt_schedule_days=10.0, pess_schedule_days=40.0,
            cascade_group="",
        )]
        scope_df = _make_dual_scope_df(["R900"], mode="Parallel")
        cfg = _integrated_config(cascade_enabled=True, cascade_use_raw_days=True)
        out = run_integrated_simulation(cfg, risks, scope_df)
        # Parallel ⇒ Mode multiplier 0 ⇒ schedule_array all zeros despite
        # cascade_use_raw_days=True (the flag only governs cascade slip
        # propagation, not the schedule arm's Mode multiplier).
        assert np.all(out["per_risk_schedule_array"] == 0.0)


class TestOverlapDetection:

    def test_no_overlap_returns_empty(self):
        from src.integrated.cascade_integrated import detect_chain_cascade_overlap
        risks = [
            _base_risk(risk_id="RA", cascade_group="GX"),
            _base_risk(risk_id="RB", cascade_group=""),
        ]
        edges = [{"parent_id": "RA", "child_id": "RB", "effect_type": "magnitude_shift",
                  "magnitude": 1.5}]
        out = detect_chain_cascade_overlap(risks, edges)
        assert out == []

    def test_overlap_warns_by_default(self, caplog):
        from src.integrated.cascade_integrated import detect_chain_cascade_overlap
        risks = [
            _base_risk(risk_id="RA", cascade_group="GZ"),
            _base_risk(risk_id="RB", cascade_group="GZ"),
        ]
        edges = [{"parent_id": "RA", "child_id": "RB", "effect_type": "magnitude",
                  "magnitude": 1.2}]
        out = detect_chain_cascade_overlap(risks, edges, strict=False)
        assert len(out) == 1
        assert out[0]["parent_id"] == "RA"
        assert out[0]["child_id"] == "RB"
        assert out[0]["cascade_group"] == "GZ"
        assert out[0]["severity"] == "warning"

    def test_overlap_raises_in_strict_mode(self):
        from src.integrated.cascade_integrated import detect_chain_cascade_overlap
        risks = [
            _base_risk(risk_id="RA", cascade_group="GZ"),
            _base_risk(risk_id="RB", cascade_group="GZ"),
        ]
        edges = [{"parent_id": "RA", "child_id": "RB", "effect_type": "magnitude",
                  "magnitude": 1.2}]
        with pytest.raises(RuntimeError, match="overlap"):
            detect_chain_cascade_overlap(risks, edges, strict=True)

    def test_overlap_detector_is_project_agnostic(self):
        # Synthetic risk IDs (no R076/R015/R017 etc); detector should still find.
        from src.integrated.cascade_integrated import detect_chain_cascade_overlap
        risks = [
            _base_risk(risk_id="ALPHA", cascade_group="GROUP_X"),
            _base_risk(risk_id="BETA", cascade_group="GROUP_X"),
        ]
        edges = [{"parent_id": "ALPHA", "child_id": "BETA", "effect_type": "x", "magnitude": 1.0}]
        out = detect_chain_cascade_overlap(risks, edges)
        assert len(out) == 1
        assert out[0]["parent_id"] == "ALPHA"


class TestLegacyChainDeprecation:

    def test_warning_when_legacy_id_present(self, monkeypatch):
        import src.defaults as defaults
        from src.integrated.cascade_integrated import (
            emit_legacy_chain_deprecation_warning,
        )
        # The ids come from the active project's binding; this test supplies its own rather
        # than requiring a project that declares a legacy chain (REFRETIRE-01).
        monkeypatch.setattr(defaults, "get_chain_risk_ids",
                            lambda: dict(TEST_CHAIN_RISK_IDS))
        risks = [_base_risk(risk_id="R076"), _base_risk(risk_id="OTHER")]
        with _warnings.catch_warnings(record=True) as w:
            _warnings.simplefilter("always")
            found = emit_legacy_chain_deprecation_warning(risks)
        assert "R076" in found
        assert any(issubclass(item.category, DeprecationWarning) for item in w)
        assert any("Static hardcoded chains" in str(item.message)
                   and "SP19" in str(item.message) for item in w)

    def test_no_warning_when_legacy_id_absent(self):
        # V8 case: none of R076/R015/R017/R018/R019 in the open set.
        from src.integrated.cascade_integrated import (
            emit_legacy_chain_deprecation_warning,
        )
        risks = [
            _base_risk(risk_id="R013"), _base_risk(risk_id="R028"),
            _base_risk(risk_id="R067"),
        ]
        with _warnings.catch_warnings(record=True) as w:
            _warnings.simplefilter("always")
            found = emit_legacy_chain_deprecation_warning(risks)
        assert found == []
        assert not any(issubclass(item.category, DeprecationWarning) for item in w)


class TestRegression:

    def test_existing_cost_only_cascade_unchanged(self):
        """Cost-only engine cascade behaviour must NOT regress under SP18c.

        The shared kernel _cascade_kernel.py was added to back the integrated
        engine, but MonteCarloEngine still calls its own ``_apply_cascade_groups``
        method (Stage 2 implementation, untouched by SP18c). This test runs a
        small fixture through the cost-only cascade and asserts shape +
        non-negativity, consistent with the existing TestCascadeFlag /
        TestCascadeIntegration suites.
        """
        risks = _cascade_risks(2, group="REG_A")
        chains = ChainConfig(cascade_enabled=True)
        engine = _make_engine(risks, n_iter=1_000, seed=42, chains=chains)
        result = engine.run()
        assert result.ev_costs.shape == (1_000, 2)
        # Cascade can produce zero rows where the upstream didn't fire — but
        # cost columns must remain non-negative.
        assert np.all(result.ev_costs >= 0)
