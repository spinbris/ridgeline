"""Tests for Binary/PERT hybrid distribution support."""
import numpy as np
import pytest
from src.distributions import sample_cost, pert_from_uniform


class TestBinaryPert:
    """Binary/PERT routes to PERT cost sampling."""

    def test_binary_pert_routes_to_pert(self):
        """Binary/PERT should produce same output as PERT for same inputs."""
        u = np.linspace(0.01, 0.99, 1000)
        opt, ml, pess = 100_000, 500_000, 2_000_000

        result_bp = sample_cost(u, opt, ml, pess, "Binary/PERT")
        result_pert = sample_cost(u, opt, ml, pess, "PERT")

        np.testing.assert_array_equal(result_bp, result_pert)

    def test_binary_pert_case_insensitive(self):
        """Distribution name matching should be case-insensitive."""
        u = np.array([0.5])
        opt, ml, pess = 100_000, 500_000, 2_000_000

        r1 = sample_cost(u, opt, ml, pess, "Binary/PERT")
        r2 = sample_cost(u, opt, ml, pess, "binary/pert")
        r3 = sample_cost(u, opt, ml, pess, "BINARY/PERT")

        np.testing.assert_array_equal(r1, r2)
        np.testing.assert_array_equal(r1, r3)

    def test_binary_pert_produces_range(self):
        """Binary/PERT should produce values across the Opt-Pess range."""
        u = np.linspace(0.01, 0.99, 10_000)
        opt, ml, pess = 100_000, 500_000, 2_000_000

        result = sample_cost(u, opt, ml, pess, "Binary/PERT")

        assert result.min() >= opt * 0.99  # near opt
        assert result.max() <= pess * 1.01  # near pess
        assert result.std() > 0  # not constant

    def test_binary_stays_fixed(self):
        """Pure Binary should still return fixed ML (regression)."""
        u = np.linspace(0.01, 0.99, 1000)
        opt, ml, pess = 100_000, 500_000, 2_000_000

        result = sample_cost(u, opt, ml, pess, "Binary")

        np.testing.assert_array_equal(result, np.full(1000, ml))

    def test_binary_pert_not_fixed(self):
        """Binary/PERT should NOT return fixed ML — that's the whole point."""
        u = np.linspace(0.01, 0.99, 1000)
        opt, ml, pess = 100_000, 500_000, 2_000_000

        result = sample_cost(u, opt, ml, pess, "Binary/PERT")

        # Should have variation — not all equal to ML
        assert not np.all(result == ml), \
            "Binary/PERT returned fixed ML — should draw from PERT range"

    def test_binary_pert_with_binomial_recurrence(self):
        """Binary/PERT should work correctly with BINOMIAL recurring risks.

        The magnitude pool uses sample_cost() which must produce PERT draws,
        not fixed ML, when distribution is Binary/PERT.
        """
        rng = np.random.default_rng(42)
        n_iter = 10_000
        max_n = 3
        prob = 0.3
        opt, ml, pess = 100_000, 500_000, 2_000_000

        occurrences = rng.binomial(n=max_n, p=prob, size=n_iter)
        pool_u = rng.uniform(size=n_iter * max_n)

        # Binary/PERT should produce variable costs
        mag_pool = sample_cost(pool_u, opt, ml, pess, "Binary/PERT")
        mag_pool = mag_pool.reshape(n_iter, max_n)

        mask = np.arange(max_n)[None, :] < occurrences[:, None]
        total_costs = (mag_pool * mask).sum(axis=1)

        fired_costs = total_costs[total_costs > 0]
        assert len(fired_costs) > 0
        assert fired_costs.std() > 0, "Costs should vary with Binary/PERT"

    def test_pert_still_works(self):
        """Pure PERT distribution should be unaffected (regression)."""
        u = np.linspace(0.01, 0.99, 1000)
        opt, ml, pess = 100_000, 500_000, 2_000_000

        result = sample_cost(u, opt, ml, pess, "PERT")

        assert result.min() >= opt * 0.99
        assert result.max() <= pess * 1.01
        assert result.std() > 0
