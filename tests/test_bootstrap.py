"""
SP18a / SP18a.1 — Block-bootstrap confidence intervals on convergence.

Test classes:
  * TestBootstrapBasic         — bootstrap_percentile_ci correctness
  * TestBootstrapConvergence   — bootstrap_convergence + back-compat keys
  * TestChartCaption           — chart includes the mandatory MC-error caption
  * TestNBlocksScaling         — SP18a.1 _scale_n_blocks helper (floor/ceiling)
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import numpy as np
import pytest

from src.bootstrap import (
    bootstrap_percentile_ci, bootstrap_convergence, _scale_n_blocks,
)
from src.analysis import compute_convergence
from src.charts import generate_convergence
from src.config import SimRawResults


# ---------------------------------------------------------------------------
# 1. bootstrap_percentile_ci
# ---------------------------------------------------------------------------

class TestBootstrapBasic:

    def test_bootstrap_recovers_known_percentile(self):
        sample = np.random.default_rng(0).normal(loc=100, scale=15, size=30_000)
        out = bootstrap_percentile_ci(
            sample, percentile=90.0, n_blocks=100, n_resamples=500, seed=42,
        )
        assert abs(out["point"] - float(np.percentile(sample, 90))) < 1e-6
        assert out["p025"] < out["point"] < out["p975"]
        assert out["ci95_width"] > 0
        assert out["ci95_width"] == out["p975"] - out["p025"]
        assert out["n_iter"] == 30_000
        assert out["percentile"] == 90.0
        # Audit-trail seed is recorded
        assert "seed" in out

    def test_ci_narrows_with_more_iterations(self):
        # SP18a.1: with iteration-scaled n_blocks, CI(30k) / CI(5k) should be
        # appreciably below 0.5 (close to the 1/sqrt(6) ≈ 0.41 theoretical
        # limit for IID samples).
        sample = np.random.default_rng(1).normal(loc=100, scale=15, size=30_000)
        boot = bootstrap_convergence(
            sample, percentile=90.0,
            iter_grid=[5_000, 30_000],
            n_resamples=500, seed=42,
        )
        widths = boot["ci95_width"]
        ratio = float(widths[1] / widths[0])
        assert ratio < 0.5, (
            f"CI did not narrow enough under SP18a.1 scaling: ratio={ratio:.3f}"
        )

    def test_seed_reproducibility(self):
        sample = np.random.default_rng(2).normal(loc=10, scale=2, size=10_000)
        a = bootstrap_percentile_ci(
            sample, percentile=90.0, n_blocks=50, n_resamples=200, seed=123,
        )
        b = bootstrap_percentile_ci(
            sample, percentile=90.0, n_blocks=50, n_resamples=200, seed=123,
        )
        assert a["p025"] == b["p025"]
        assert a["p500"] == b["p500"]
        assert a["p975"] == b["p975"]

    def test_robust_to_small_sample(self):
        sample = np.linspace(0, 1, 50)
        # n_blocks=100 is impossible (sample has only 50 elements / 5 max blocks)
        out = bootstrap_percentile_ci(
            sample, percentile=90.0, n_blocks=100, n_resamples=50, seed=42,
        )
        # Function did not raise; n_blocks was downscaled to fit.
        assert out["n_blocks"] <= 50 // 10
        assert out["n_blocks"] >= 1
        # Point estimate matches exact percentile
        assert abs(out["point"] - float(np.percentile(sample, 90))) < 1e-6


# ---------------------------------------------------------------------------
# 2. bootstrap_convergence
# ---------------------------------------------------------------------------

class TestBootstrapConvergence:

    def test_grid_returns_all_keys(self):
        sample = np.random.default_rng(3).normal(loc=50, scale=5, size=30_000)
        out = bootstrap_convergence(
            sample,
            seed=42,
            percentile=90.0,
            iter_grid=[1000, 5000, 10000, 20000, 30000],
            n_blocks=100,
            n_resamples=200,
        )
        for key in ("iter_grid", "point", "p025", "p500", "p975",
                    "ci95_width", "n_blocks", "percentile",
                    "n_resamples", "seed"):
            assert key in out, f"missing key {key!r}"
        assert len(out["iter_grid"]) == 5
        assert len(out["point"]) == 5
        assert len(out["p025"]) == 5
        assert len(out["p975"]) == 5
        # SP18a.1: n_blocks is now an array of length len(iter_grid)
        assert len(out["n_blocks"]) == 5
        # Last entry's point estimate matches np.percentile of full sample
        assert abs(float(out["point"][-1]) - float(np.percentile(sample, 90))) < 1e-6

    def test_back_compat_keys_preserved(self):
        rng = np.random.default_rng(4)
        n_iter = 30_000
        n_risks = 3
        l1 = rng.normal(loc=300_000_000, scale=10_000_000, size=n_iter)
        l1_buckets = np.zeros((n_iter, 1))
        ev = rng.normal(loc=2_000_000, scale=500_000, size=(n_iter, n_risks))
        raw = SimRawResults(
            l1_cost=l1, l1_buckets=l1_buckets, ev_costs=ev,
            n_iter=n_iter, n_risks=n_risks,
        )
        out = compute_convergence(raw, view="All", n_resamples=100, seed=42)
        for n in (1000, 5000, 10000, 20000, 30000):
            assert f"conv_{n}" in out
            assert isinstance(out[f"conv_{n}"], float)
        assert "bootstrap" in out
        boot = out["bootstrap"]
        assert isinstance(boot, dict)
        for key in ("iter_grid", "point", "p025", "p975", "p500",
                    "ci95_width", "percentile", "seed"):
            assert key in boot, f"bootstrap dict missing {key!r}"
        # conv_30000 point estimate == bootstrap point at the last grid index
        last_idx = boot["iter_grid"].index(30000)
        assert abs(out["conv_30000"] - float(boot["point"][last_idx])) < 1e-9


# ---------------------------------------------------------------------------
# 3. Chart caption — mandatory acceptance criterion
# ---------------------------------------------------------------------------

class TestChartCaption:

    def test_chart_includes_ci_caption(self):
        sample = np.random.default_rng(5).normal(loc=300_000_000, scale=10_000_000, size=30_000)
        boot = bootstrap_convergence(
            sample,
            seed=42,
            percentile=90.0,
            iter_grid=[1000, 5000, 10000, 20000, 30000],
            n_blocks=100,
            n_resamples=200,
        )
        conv_data = {f"conv_{int(k)}": float(p) for k, p in zip(boot["iter_grid"], boot["point"])}
        conv_data["bootstrap"] = boot

        fig, ax = plt.subplots(figsize=(8, 4.5))
        try:
            generate_convergence(conv_data, output_path=None, view="All", fig=fig, ax=ax)
            # Walk fig.findobj() for matplotlib.text.Text instances and assert
            # that at least one carries the mandatory caption phrasing.
            import matplotlib.text as mtext
            captions = [
                t.get_text() for t in fig.findobj(mtext.Text)
                if isinstance(t.get_text(), str)
            ]
            joined = "\n".join(captions)
            assert "Monte-Carlo error" in joined, (
                f"Expected 'Monte-Carlo error' in chart text; got: {captions}"
            )
            assert "not project-cost" in joined, (
                f"Expected 'not project-cost' in chart text; got: {captions}"
            )
        finally:
            plt.close(fig)


# ---------------------------------------------------------------------------
# 4. SP18a.1 — n_blocks scaling rule
# ---------------------------------------------------------------------------

class TestNBlocksScaling:

    def test_scaling_at_grid_points(self):
        assert _scale_n_blocks(1000) == 50
        assert _scale_n_blocks(5000) == 50
        assert _scale_n_blocks(10000) == 100
        assert _scale_n_blocks(20000) == 200
        assert _scale_n_blocks(30000) == 300

    def test_floor_and_ceiling(self):
        assert _scale_n_blocks(100) == 50          # floor
        assert _scale_n_blocks(100_000) == 500     # ceiling
        assert _scale_n_blocks(1_000_000) == 500   # ceiling holds far above
