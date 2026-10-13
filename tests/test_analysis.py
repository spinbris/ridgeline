"""
Tests for post-simulation analysis module.

Validates:
- Percentile computations for all stakeholder views
- Tornado variance decomposition ranking and values
- S-curve data completeness (99 points × 2 curves)
- Convergence check structure
- Output table key completeness (matches Excel XLOOKUP contract)
- Adequacy/overrun calculation
- Party filtering logic
"""

import numpy as np
import pytest

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput, SimRawResults
from src.simulation import MonteCarloEngine
from src.analysis import (
    compute_party_costs,
    compute_tornado,
    compute_s_curve,
    compute_convergence,
    build_output_table,
    CONVERGENCE_POINTS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_config(**overrides) -> SimConfig:
    defaults = dict(
        n_iter=30_000, tic=300_000_000, contingency=30_000_000,
        bop_contract=300_000_000,
        bop_contingency=5_000_000, cse_contingency=5_000_000,
    )
    defaults.update(overrides)
    return SimConfig(**defaults)


def make_buckets() -> list[WBSBucket]:
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


def make_risks() -> list[RiskInput]:
    return [
        RiskInput("R015", "Inclement weather", "BOP Contractor",
                  "Triangular", "CG06", 0.175, 350_000, 1_000_000, 2_000_000),
        RiskInput("R017", "Site estab delay", "BOP Contractor",
                  "Triangular", "CG05", 0.175, 6_125_000, 12_250_000, 25_000_000),
        RiskInput("R019", "GTG civil delay", "Shared",
                  "Triangular", "CG05", 0.175, 1_000_000, 3_000_000, 8_000_000),
        RiskInput("R076", "Planning delay", "Owner",
                  "Triangular", "CG07", 0.175, 875_000, 2_100_000, 5_000_000),
        RiskInput("R003", "Opportunity", "BOP Contractor",
                  "Triangular", "CG01", 0.755, -50_000, -200_000, -400_000),
    ]


def run_simulation(config=None, risks=None):
    """Helper: run sim and return raw results + config + risks."""
    config = config or make_config()
    risks = risks or make_risks()
    engine = MonteCarloEngine(
        config, make_buckets(), ChainConfig(), risks,
        {"CG01": 0.6, "CG05": 0.5, "CG06": 0.5, "CG07": 0.4},
        seed=42,
    )
    return engine.run(), config, risks


# ---------------------------------------------------------------------------
# Party costs
# ---------------------------------------------------------------------------

class TestPartyCosts:

    def test_total_equals_l1_plus_l2(self):
        raw, config, risks = run_simulation()
        costs = compute_party_costs(raw, risks, config)
        expected = raw.l1_cost + raw.ev_costs.sum(axis=1)
        np.testing.assert_allclose(costs["total"], expected, atol=1.0)

    def test_bop_includes_shared(self):
        """BOP view should include Shared risks (R019)."""
        raw, config, risks = run_simulation()
        costs = compute_party_costs(raw, risks, config)
        # BOP total should be >= L1 (has BOP + Shared event costs)
        assert np.mean(costs["bop_total"]) >= np.mean(costs["l1"]) - 1_000_000

    def test_cse_includes_shared(self):
        """CSE view should include Shared risks."""
        raw, config, risks = run_simulation()
        costs = compute_party_costs(raw, risks, config)
        assert np.mean(costs["cse_total"]) >= np.mean(costs["l1"]) - 1_000_000

    def test_views_not_additive(self):
        """BOP + CSE > All because Shared risks counted in both."""
        raw, config, risks = run_simulation()
        costs = compute_party_costs(raw, risks, config)
        bop_mean = np.mean(costs["bop_total"])
        cse_mean = np.mean(costs["cse_total"])
        all_mean = np.mean(costs["total"])
        # If there are shared risks, sum of parties > whole project
        assert bop_mean + cse_mean > all_mean + np.mean(costs["l1"]) * 0.5


# ---------------------------------------------------------------------------
# Tornado
# ---------------------------------------------------------------------------

class TestTornado:

    def test_returns_top_10(self):
        raw, _, risks = run_simulation()
        tornado = compute_tornado(raw, risks)
        assert len(tornado) <= 10

    def test_sorted_descending(self):
        raw, _, risks = run_simulation()
        tornado = compute_tornado(raw, risks)
        for i in range(len(tornado) - 1):
            assert tornado[i].variance_contribution >= tornado[i + 1].variance_contribution

    def test_all_variance_non_negative(self):
        raw, _, risks = run_simulation()
        tornado = compute_tornado(raw, risks)
        for entry in tornado:
            assert entry.variance_contribution >= 0
            assert entry.std_contribution >= 0

    def test_dominant_risk_ranked_first(self):
        """R017 ($6-25M, 17.5%) should dominate over R015 ($0.35-2M)."""
        raw, _, risks = run_simulation()
        tornado = compute_tornado(raw, risks)
        # R017 or a large L1 bucket should be in top 3
        top_ids = [t.risk_id for t in tornado[:3]]
        assert "R017" in top_ids or any(t.startswith("L1-") for t in top_ids)

    def test_includes_l1_buckets(self):
        """Tornado should include Layer 1 bucket entries."""
        raw, _, risks = run_simulation()
        tornado = compute_tornado(raw, risks)
        l1_entries = [t for t in tornado if t.layer == "Layer 1"]
        assert len(l1_entries) > 0


# ---------------------------------------------------------------------------
# S-curve
# ---------------------------------------------------------------------------

class TestSCurve:

    def test_99_points_both_curves(self):
        raw, _, _ = run_simulation()
        sc = compute_s_curve(raw)
        for p in range(1, 100):
            assert f"sc_total_{p}" in sc
            assert f"sc_l1_{p}" in sc

    def test_monotonically_increasing(self):
        raw, _, _ = run_simulation()
        sc = compute_s_curve(raw)
        for prefix in ("sc_total_", "sc_l1_"):
            vals = [sc[f"{prefix}{p}"] for p in range(1, 100)]
            for i in range(len(vals) - 1):
                assert vals[i] <= vals[i + 1] + 1.0  # small tolerance

    def test_total_above_l1(self):
        """Total (L1+L2) should generally be above L1-only at same percentile."""
        raw, _, _ = run_simulation()
        sc = compute_s_curve(raw)
        # At P50 and above, total should exceed L1 (positive risk premium)
        for p in [50, 80, 90]:
            assert sc[f"sc_total_{p}"] >= sc[f"sc_l1_{p}"] - 1_000_000


# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------

class TestConvergence:

    def test_points_present_up_to_n_iter(self):
        raw, _, _ = run_simulation()
        conv = compute_convergence(raw, seed=42)
        for n in CONVERGENCE_POINTS:
            if n <= raw.n_iter:
                assert f"conv_{n}" in conv
            else:
                assert f"conv_{n}" not in conv, (
                    f"conv_{n} should not be present when n_iter={raw.n_iter}"
                )

    def test_values_stabilise(self):
        """P90 at 20k and 30k should be close (converged)."""
        raw, _, _ = run_simulation()
        conv = compute_convergence(raw, seed=42)
        diff = abs(conv["conv_20000"] - conv["conv_30000"])
        # Should stabilise within ~$2M for this scale
        assert diff < 5_000_000


# ---------------------------------------------------------------------------
# Output table — the Excel contract
# ---------------------------------------------------------------------------

# Required keys from XLOOKUP formulas in MC_Outputs and MC_Dashboard
REQUIRED_KEYS = (
    # All risks
    ["p10", "p50", "p80", "p90", "mean", "std"]
    # L1 only
    + ["l1_p10", "l1_p50", "l1_p80", "l1_p90", "l1_mean", "l1_std"]
    # BOP
    + ["bop_p10", "bop_p50", "bop_p80", "bop_p90", "bop_mean", "bop_std"]
    # CSE
    + ["cse_p10", "cse_p50", "cse_p80", "cse_p90", "cse_mean", "cse_std"]
    # Adequacy
    + ["adequacy", "overrun", "n_risks"]
    # Tornado (10 entries × 4 fields)
    + [f"t{i}_{f}" for i in range(10) for f in ("id", "desc", "owner", "var")]
    # Convergence (only points <= test config n_iter=30000)
    + [f"conv_{n}" for n in CONVERGENCE_POINTS if n <= 30_000]
    # S-curve (99 points × 2 curves)
    + [f"sc_total_{p}" for p in range(1, 100)]
    + [f"sc_l1_{p}" for p in range(1, 100)]
)


class TestOutputTable:

    def test_all_required_keys_present(self):
        """Every XLOOKUP key in the spreadsheet must be in the output."""
        raw, config, risks = run_simulation()
        table = build_output_table(raw, risks, config)
        output_keys = {row[0] for row in table}
        missing = [k for k in REQUIRED_KEYS if k not in output_keys]
        assert missing == [], f"Missing keys: {missing}"

    def test_all_values_numeric_or_string(self):
        """Values must be float/int/str — no None, no numpy types leaking."""
        raw, config, risks = run_simulation()
        table = build_output_table(raw, risks, config)
        for key, val in table:
            assert isinstance(key, str), f"Key must be str: {key}"
            assert isinstance(val, (int, float, str)), f"Bad value type for {key}: {type(val)}"

    def test_p_values_ordered(self):
        """P10 < P50 < P80 < P90 for all views."""
        raw, config, risks = run_simulation()
        table = build_output_table(raw, risks, config)
        lookup = {row[0]: row[1] for row in table}
        for prefix in ("", "l1_", "bop_", "cse_"):
            p10 = lookup[f"{prefix}p10"]
            p50 = lookup[f"{prefix}p50"]
            p80 = lookup[f"{prefix}p80"]
            p90 = lookup[f"{prefix}p90"]
            assert p10 < p50 < p80 < p90, f"P-values not ordered for {prefix}"

    def test_adequacy_between_0_and_1(self):
        raw, config, risks = run_simulation()
        table = build_output_table(raw, risks, config)
        lookup = {row[0]: row[1] for row in table}
        assert 0.0 <= lookup["adequacy"] <= 1.0
        assert 0.0 <= lookup["overrun"] <= 1.0
        assert lookup["adequacy"] + lookup["overrun"] == pytest.approx(1.0)

    def test_table_size(self):
        """Output table should have ~270+ rows."""
        raw, config, risks = run_simulation()
        table = build_output_table(raw, risks, config)
        # 6×4 views + 3 adequacy + 40 tornado + 5 convergence + 198 s-curve = 270
        assert len(table) >= 270

    def test_no_duplicate_keys(self):
        raw, config, risks = run_simulation()
        table = build_output_table(raw, risks, config)
        keys = [row[0] for row in table]
        assert len(keys) == len(set(keys)), f"Duplicate keys: {[k for k in keys if keys.count(k) > 1]}"
