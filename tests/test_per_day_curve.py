"""
SP18b — Per-day P-curve tests.

Test classes:
  * TestPerDayMatrix           — build_per_day_matrix correctness
  * TestPerDayPercentiles      — per_day_percentiles monotonicity / order
  * TestIntegration            — end-to-end via the cost engine + reconciliation
  * TestChartCaption           — chart contains 'NOT a phased S-curve'
  * TestRegisterPlannedDay     — Planned_Day defaults to 0 when column absent
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import numpy as np
import pytest

from src.per_day_curve import (
    build_per_day_matrix,
    per_day_percentiles,
    compute_per_day_curve,
    build_timed_events,
)
from src.charts import generate_per_day_pcurve
from src.config import RiskInput


# ---------------------------------------------------------------------------
# 1. build_per_day_matrix
# ---------------------------------------------------------------------------

class TestPerDayMatrix:

    def test_single_risk_single_day(self):
        n_iter = 1000
        # Single risk planned at day 100, deterministic $1M every iteration.
        timed_events = np.zeros((n_iter, 1, 2), dtype=np.float64)
        timed_events[:, 0, 0] = 100
        timed_events[:, 0, 1] = 1_000_000.0

        bins = np.arange(0, 5_000_000 + 100_000, 100_000, dtype=np.float64)
        M = build_per_day_matrix(timed_events, n_days=200, cost_bins=bins)

        # Shape: (n_days+1, n_bins)
        assert M.shape == (201, len(bins))
        # Days 0..99 inclusive: cost is 0 → all iterations land in bin 0.
        for d in range(0, 100):
            assert M[d, 0] == n_iter
            assert M[d, 1:].sum() == 0
        # Days 100..200: cost is $1M → all in the bin whose lower edge == 1M.
        target_bin = int(np.searchsorted(bins, 1_000_000, side="right") - 1)
        for d in range(100, 201):
            assert M[d, target_bin] == n_iter

    def test_two_risks_compound(self):
        n_iter = 500
        # Risk A: day 50, $500k. Risk B: day 150, $700k. Both deterministic.
        timed_events = np.zeros((n_iter, 2, 2), dtype=np.float64)
        timed_events[:, 0, 0] = 50
        timed_events[:, 0, 1] = 500_000.0
        timed_events[:, 1, 0] = 150
        timed_events[:, 1, 1] = 700_000.0

        bins = np.arange(0, 5_000_000 + 100_000, 100_000, dtype=np.float64)
        M = build_per_day_matrix(timed_events, n_days=200, cost_bins=bins)

        # Day 100: only risk A has fired → cumcost = $500k.
        bin_500k = int(np.searchsorted(bins, 500_000, side="right") - 1)
        assert M[100, bin_500k] == n_iter
        # Day 200: both fired → cumcost = $1.2M.
        bin_1p2m = int(np.searchsorted(bins, 1_200_000, side="right") - 1)
        assert M[200, bin_1p2m] == n_iter

    def test_iteration_independence(self):
        # Three independent risks, p=0.5 each, fixed cost when fired.
        rng = np.random.default_rng(42)
        n_iter = 1000
        n_risks = 3
        timed_events = np.zeros((n_iter, n_risks, 2), dtype=np.float64)
        timed_events[:, :, 0] = [50, 100, 150]  # planned days
        # Each risk fires with p=0.5; cost = 1M when fired.
        fires = rng.random((n_iter, n_risks)) < 0.5
        timed_events[:, :, 1] = np.where(fires, 1_000_000.0, 0.0)

        bins = np.arange(0, 5_000_000 + 100_000, 100_000, dtype=np.float64)
        M = build_per_day_matrix(timed_events, n_days=200, cost_bins=bins)

        # Each (iter, day) cell increments exactly one bin → row totals == n_iter.
        row_totals = M.sum(axis=1)
        np.testing.assert_array_equal(row_totals, np.full(201, n_iter))


# ---------------------------------------------------------------------------
# 2. per_day_percentiles
# ---------------------------------------------------------------------------

def _build_random_curve(seed: int = 7) -> tuple[np.ndarray, np.ndarray, dict]:
    rng = np.random.default_rng(seed)
    n_iter = 5000
    n_risks = 8
    timed_events = np.zeros((n_iter, n_risks, 2), dtype=np.float64)
    timed_events[:, :, 0] = rng.integers(1, 250, size=n_risks)
    fires = rng.random((n_iter, n_risks)) < 0.5
    costs = rng.lognormal(mean=14.0, sigma=0.8, size=(n_iter, n_risks))
    timed_events[:, :, 1] = np.where(fires, costs, 0.0)
    bins = np.arange(0, 100_000_000 + 100_000, 100_000, dtype=np.float64)
    matrix = build_per_day_matrix(timed_events, n_days=300, cost_bins=bins)
    return timed_events, bins, matrix


class TestPerDayPercentiles:

    def test_monotone_in_day(self):
        _, bins, matrix = _build_random_curve()
        pct = per_day_percentiles(matrix, bins, percentiles=[50.0, 80.0, 90.0])
        # Monotone non-decreasing: cumulative cost only grows.
        # Allow a one-bin (= cost_bin_size) tolerance for interpolation noise
        # at low-count tails near the bin edges.
        bin_size = float(bins[1] - bins[0])
        for key in ("p050", "p080", "p090"):
            diffs = np.diff(pct[key])
            assert np.all(diffs >= -bin_size), (
                f"{key} not monotone non-decreasing within {bin_size:g} tolerance"
            )

    def test_p50_le_p80_le_p90(self):
        _, bins, matrix = _build_random_curve()
        pct = per_day_percentiles(matrix, bins, percentiles=[50.0, 80.0, 90.0])
        assert np.all(pct["p050"] <= pct["p080"] + 1.0)
        assert np.all(pct["p080"] <= pct["p090"] + 1.0)

    def test_interpolation_smoother_than_lower_edge(self):
        # Build the same matrix; compute percentiles two ways and check that the
        # interpolated trajectory's first-difference variance is lower (smoother).
        _, bins, matrix = _build_random_curve()
        pct = per_day_percentiles(matrix, bins, percentiles=[90.0])
        traj_interp = pct["p090"]

        # Lower-edge variant: for each day, find first bin where cdf >= 0.9 and
        # report the bin's lower edge (no interpolation).
        n_bins = len(bins)
        row_totals = matrix.sum(axis=1)
        cdf = np.cumsum(matrix, axis=1)
        traj_lower = np.empty(matrix.shape[0])
        for d in range(matrix.shape[0]):
            total = row_totals[d]
            if total <= 0:
                traj_lower[d] = float(bins[0])
                continue
            target = 0.9 * total
            b = int(np.searchsorted(cdf[d], target, side="left"))
            b = min(b, n_bins - 1)
            traj_lower[d] = float(bins[b])

        # Smooth chart is the whole point: interpolation should reduce step
        # discreteness, so the std of first-differences (a noise/jaggedness
        # proxy) should be lower for the interpolated trajectory.
        std_interp = float(np.std(np.diff(traj_interp)))
        std_lower = float(np.std(np.diff(traj_lower)))
        assert std_interp <= std_lower, (
            f"interpolation should be smoother: std_interp={std_interp:.2f} "
            f"vs std_lower={std_lower:.2f}"
        )


# ---------------------------------------------------------------------------
# 3. Integration — cost engine + per-day curve + reconciliation
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_full_run_produces_curve_with_reconciliation(self):
        # Synthetic 5-risk fixture with explicit Planned_Day spread across the
        # programme. Drive the cost engine directly (no strawman dependency).
        from src.config import SimConfig, ChainConfig
        from src.simulation import MonteCarloEngine

        risks = [
            RiskInput(
                risk_id=f"R{i+1:03d}",
                description=f"synthetic risk {i+1}",
                owner="Shared",
                distribution="PERT",
                correlation_group="CG_UNASSIGNED",
                probability=0.4 + 0.05 * i,
                opt_cost=200_000 * (i + 1),
                ml_cost=500_000 * (i + 1),
                pess_cost=1_500_000 * (i + 1),
                planned_day=50 + 50 * i,
            )
            for i in range(5)
        ]
        config = SimConfig(
            n_iter=20_000, seed=42, view="L2Only",
            tic=0.0, contingency=0.0,
            programme_seasons=3,
            per_day_cost_bin_size=50_000,
            per_day_max_cost=100_000_000,
            programme_days=300,
        )
        chains = ChainConfig()
        engine = MonteCarloEngine(
            config, [], chains, risks,
            corr_coefficients={"CG_UNASSIGNED": 0.0},
            seed=config.seed, wbs_rho=0.0,
        )
        raw = engine.run()
        assert raw.ev_costs.shape == (20_000, 5)

        timed_events = build_timed_events(
            raw.ev_costs,
            [r.planned_day for r in risks],
            fallback_day=config.programme_days // 2,
        )
        assert timed_events.shape == (20_000, 5, 2)

        out = compute_per_day_curve(
            timed_events,
            programme_days=config.programme_days,
            cost_bin_size=config.per_day_cost_bin_size,
            max_cost=config.per_day_max_cost,
        )
        assert out["enabled"] is True
        assert out["p050"].shape == (config.programme_days + 1,)
        assert out["p080"].shape == (config.programme_days + 1,)
        assert out["p090"].shape == (config.programme_days + 1,)

        # Reconciliation: final-day per-day P90 within 1% of total-outturn P90.
        total_p90 = float(np.percentile(raw.ev_costs.sum(axis=1), 90))
        final_p90 = float(out["p090"][-1])
        gap_pct = abs(final_p90 - total_p90) / abs(total_p90)
        assert gap_pct < 0.01, (
            f"final-day per-day P90 ${final_p90/1e6:.3f}M does not reconcile "
            f"with total-outturn P90 ${total_p90/1e6:.3f}M (gap {gap_pct*100:.2f}%)"
        )

    def test_disabled_when_programme_days_zero(self):
        timed_events = np.zeros((10, 1, 2), dtype=np.float64)
        out = compute_per_day_curve(timed_events, programme_days=0)
        assert out["enabled"] is False
        assert "reason" in out


# ---------------------------------------------------------------------------
# 4. Chart caption
# ---------------------------------------------------------------------------

class TestChartCaption:

    def test_chart_caption_present(self):
        # Minimal curve dict good enough to render.
        days = np.arange(0, 11)
        curve = {
            "enabled": True,
            "day_axis": days,
            "p050": np.linspace(0, 5_000_000, 11),
            "p080": np.linspace(0, 8_000_000, 11),
            "p090": np.linspace(0, 9_000_000, 11),
        }
        fig, ax = plt.subplots(figsize=(8, 4.5))
        try:
            generate_per_day_pcurve(curve, output_path=None, fig=fig, ax=ax)
            import matplotlib.text as mtext
            captions = [
                t.get_text() for t in fig.findobj(mtext.Text)
                if isinstance(t.get_text(), str)
            ]
            joined = "\n".join(captions)
            assert "NOT a phased S-curve" in joined, (
                f"Mandatory caption missing 'NOT a phased S-curve'; got: {captions}"
            )
        finally:
            plt.close(fig)


# ---------------------------------------------------------------------------
# 5. Register schema — Planned_Day default behaviour
# ---------------------------------------------------------------------------

class TestRegisterPlannedDay:

    def test_default_zero_when_field_absent(self):
        # RiskInput's planned_day field defaults to 0 (= unspecified).
        risk = RiskInput(
            risk_id="R001", description="x", owner="Shared",
            distribution="PERT", correlation_group="CG01",
            probability=0.5, opt_cost=1.0, ml_cost=2.0, pess_cost=3.0,
        )
        assert risk.planned_day == 0

    def test_explicit_planned_day_set_through(self):
        risk = RiskInput(
            risk_id="R001", description="x", owner="Shared",
            distribution="PERT", correlation_group="CG01",
            probability=0.5, opt_cost=1.0, ml_cost=2.0, pess_cost=3.0,
            planned_day=137,
        )
        assert risk.planned_day == 137

    def test_build_timed_events_fallback_when_planned_day_zero(self, caplog):
        cost_matrix = np.array([[1_000_000.0, 2_000_000.0]])  # 1 iter, 2 risks
        out = build_timed_events(
            cost_matrix, planned_days=[0, 100], fallback_day=150,
            log_fallback=True,
        )
        # Risk 0 has planned_day=0 → reassigned to 150. Risk 1 unchanged.
        assert out[0, 0, 0] == 150
        assert out[0, 1, 0] == 100
        assert out[0, 0, 1] == 1_000_000.0
        assert out[0, 1, 1] == 2_000_000.0
