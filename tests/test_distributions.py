"""
Tests for distribution sampling functions.

Validates the three inverse-CDF samplers against known properties:
- Boundary values (u=0 → min, u=1 → max, u at mode → mode)
- Statistical properties over large samples
- Opportunity (negative) sign handling
- Degenerate cases (zero range)
- Dispatch function
"""

import numpy as np
import pytest
from src.distributions import (
    triangular_from_uniform,
    pert_from_uniform,
    lognormal_from_uniform,
    sample_cost,
)


# ---------------------------------------------------------------------------
# Triangular distribution
# ---------------------------------------------------------------------------

class TestTriangular:

    def test_boundaries(self):
        """u=0 → lo, u=1 → hi."""
        u = np.array([0.0, 1.0])
        result = triangular_from_uniform(u, opt=100, ml=300, pess=500)
        assert result[0] == pytest.approx(100.0, abs=1.0)
        assert result[1] == pytest.approx(500.0, abs=1.0)

    def test_mode_at_midpoint(self):
        """Symmetric triangular: u=0.5 should give the mode."""
        u = np.array([0.5])
        # Symmetric: opt=0, ml=500, pess=1000 → mode=500, f=0.5
        result = triangular_from_uniform(u, opt=0, ml=500, pess=1000)
        assert result[0] == pytest.approx(500.0, abs=1.0)

    def test_mean_large_sample(self):
        """Mean of triangular(lo, mode, hi) = (lo + mode + hi) / 3."""
        rng = np.random.default_rng(42)
        u = rng.uniform(0, 1, 100_000)
        result = triangular_from_uniform(u, opt=100_000, ml=500_000, pess=1_000_000)
        expected_mean = (100_000 + 500_000 + 1_000_000) / 3.0
        assert np.mean(result) == pytest.approx(expected_mean, rel=0.02)

    def test_all_values_in_range(self):
        """All samples must fall within [opt, pess]."""
        rng = np.random.default_rng(99)
        u = rng.uniform(0, 1, 50_000)
        result = triangular_from_uniform(u, opt=200_000, ml=600_000, pess=900_000)
        assert np.all(result >= 200_000)
        assert np.all(result <= 900_000)

    def test_opportunity_negative(self):
        """Negative ml → all results negative (opportunity = cost reduction)."""
        rng = np.random.default_rng(7)
        u = rng.uniform(0, 1, 10_000)
        result = triangular_from_uniform(u, opt=-50_000, ml=-200_000, pess=-400_000)
        assert np.all(result <= 0), "Opportunity should produce negative values"
        assert np.all(result >= -400_000)
        assert np.all(result <= -50_000)

    def test_degenerate_zero_range(self):
        """opt == ml == pess → constant output."""
        u = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
        result = triangular_from_uniform(u, opt=1_000_000, ml=1_000_000, pess=1_000_000)
        np.testing.assert_array_equal(result, 1_000_000)

    def test_scalar_input(self):
        """Works with scalar u (wrapped to 0-d or 1-element array)."""
        result = triangular_from_uniform(np.array([0.5]), opt=0, ml=100, pess=200)
        assert result.shape == (1,)

    def test_unsorted_inputs(self):
        """opt/ml/pess need not be in ascending order — function sorts."""
        u = np.array([0.5])
        r1 = triangular_from_uniform(u, opt=100, ml=300, pess=500)
        r2 = triangular_from_uniform(u, opt=500, ml=300, pess=100)
        assert r1[0] == pytest.approx(r2[0], abs=1.0)


# ---------------------------------------------------------------------------
# PERT distribution
# ---------------------------------------------------------------------------

class TestPERT:

    def test_boundaries(self):
        """u→0 approaches lo, u→1 approaches hi."""
        u = np.array([1e-9, 1.0 - 1e-9])
        result = pert_from_uniform(u, opt=100_000, ml=400_000, pess=800_000)
        assert result[0] == pytest.approx(100_000, rel=0.05)
        assert result[1] == pytest.approx(800_000, rel=0.05)

    def test_median_near_mode(self):
        """PERT median should be close to mode (within range)."""
        rng = np.random.default_rng(42)
        u = rng.uniform(0, 1, 100_000)
        result = pert_from_uniform(u, opt=100_000, ml=400_000, pess=800_000)
        median = np.median(result)
        # PERT median is between mode and mean; should be reasonably close to mode
        assert 350_000 < median < 500_000

    def test_mean_matches_pert_formula(self):
        """PERT mean = (lo + 4*mode + hi) / 6."""
        rng = np.random.default_rng(42)
        u = rng.uniform(0, 1, 100_000)
        lo, mode, hi = 100_000, 400_000, 800_000
        result = pert_from_uniform(u, opt=lo, ml=mode, pess=hi)
        expected_mean = (lo + 4 * mode + hi) / 6.0
        assert np.mean(result) == pytest.approx(expected_mean, rel=0.03)

    def test_all_values_in_range(self):
        """Samples within [opt, pess]."""
        rng = np.random.default_rng(55)
        u = rng.uniform(0, 1, 50_000)
        result = pert_from_uniform(u, opt=50_000, ml=200_000, pess=500_000)
        assert np.all(result >= 50_000)
        assert np.all(result <= 500_000)

    def test_opportunity_negative(self):
        """Negative ml → negative samples."""
        rng = np.random.default_rng(7)
        u = rng.uniform(0, 1, 10_000)
        result = pert_from_uniform(u, opt=-50_000, ml=-200_000, pess=-400_000)
        assert np.all(result <= 0)

    def test_degenerate(self):
        """Zero range → constant."""
        u = np.array([0.0, 0.5, 1.0])
        result = pert_from_uniform(u, opt=300_000, ml=300_000, pess=300_000)
        np.testing.assert_array_equal(result, 300_000)


# ---------------------------------------------------------------------------
# Lognormal distribution (WBS bucket variation)
# ---------------------------------------------------------------------------

class TestLognormal:

    def test_right_skew(self):
        """Lognormal with asymmetric range should be right-skewed (mean > median)."""
        rng = np.random.default_rng(42)
        u = rng.uniform(0, 1, 100_000)
        result = lognormal_from_uniform(u, low_pct=-0.05, high_pct=0.25)
        assert np.mean(result) > np.median(result)

    def test_mode_near_centre(self):
        """Median should be near the mode of the input range."""
        rng = np.random.default_rng(42)
        u = rng.uniform(0, 1, 100_000)
        result = lognormal_from_uniform(u, low_pct=-0.05, high_pct=0.25)
        mode_pct = (-0.05 + 0.25) / 2.0  # 0.10
        # Median should be in the neighbourhood of the mode
        assert 0.05 < np.median(result) < 0.20

    def test_range_reasonable(self):
        """Most samples within ~2x the input range."""
        rng = np.random.default_rng(42)
        u = rng.uniform(0, 1, 100_000)
        result = lognormal_from_uniform(u, low_pct=-0.05, high_pct=0.25)
        # 95% of samples should be within a reasonable range
        p5, p95 = np.percentile(result, [5, 95])
        assert p5 > -0.15
        assert p95 < 0.50

    def test_degenerate(self):
        """Zero range → constant at mode."""
        u = np.array([0.1, 0.5, 0.9])
        result = lognormal_from_uniform(u, low_pct=0.10, high_pct=0.10)
        np.testing.assert_array_equal(result, 0.10)

    def test_symmetric_range(self):
        """Symmetric range (e.g. -10% to +10%) → roughly symmetric distribution."""
        rng = np.random.default_rng(42)
        u = rng.uniform(0, 1, 100_000)
        result = lognormal_from_uniform(u, low_pct=-0.10, high_pct=0.10)
        # Mean should be near 0
        assert abs(np.mean(result)) < 0.02


# ---------------------------------------------------------------------------
# Dispatch function
# ---------------------------------------------------------------------------

class TestSampleCost:

    def test_dispatch_triangular(self):
        """Default and explicit 'Triangular' both use triangular."""
        u = np.array([0.5])
        r1 = sample_cost(u, 100, 300, 500, "Triangular")
        r2 = triangular_from_uniform(u, 100, 300, 500)
        np.testing.assert_array_equal(r1, r2)

    def test_dispatch_pert(self):
        """'PERT' dispatches to pert_from_uniform."""
        u = np.array([0.5])
        r1 = sample_cost(u, 100, 300, 500, "PERT")
        r2 = pert_from_uniform(u, 100, 300, 500)
        np.testing.assert_array_equal(r1, r2)

    def test_dispatch_binary(self):
        """Binary returns ml regardless of u."""
        u = np.array([0.1, 0.5, 0.9])
        result = sample_cost(u, 0, 250_000, 500_000, "Binary")
        np.testing.assert_array_equal(result, 250_000)

    def test_dispatch_case_insensitive(self):
        """Distribution name matching is case-insensitive."""
        u = np.array([0.5])
        r1 = sample_cost(u, 100, 300, 500, "triangular")
        r2 = sample_cost(u, 100, 300, 500, "TRIANGULAR")
        r3 = sample_cost(u, 100, 300, 500, "  Triangular  ")
        np.testing.assert_array_equal(r1, r2)
        np.testing.assert_array_equal(r1, r3)

    def test_unknown_distribution_defaults_triangular(self):
        """Unknown distribution name falls back to triangular."""
        u = np.array([0.5])
        r1 = sample_cost(u, 100, 300, 500, "Unknown")
        r2 = triangular_from_uniform(u, 100, 300, 500)
        np.testing.assert_array_equal(r1, r2)
