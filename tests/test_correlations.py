"""
Tests for correlation matrix construction and correlated uniform generation.

Validates:
- Equicorrelation matrix properties (PSD, diagonal, off-diagonal)
- Cholesky decomposition succeeds for valid matrices
- Correlated uniforms are in [0, 1]
- Correlation structure: high rho → correlated, zero rho → independent
- Risk group assembly: correct shape, group isolation
- WBS bucket uniforms
- Edge cases: singleton groups, empty inputs, degenerate rho
"""

import numpy as np
import pytest
from dataclasses import dataclass
from src.correlations import (
    build_equicorrelation_matrix,
    generate_correlated_uniforms,
    build_risk_uniform_matrix,
    generate_wbs_uniforms,
)


# Minimal stand-in for RiskInput (only needs correlation_group attribute)
@dataclass
class MockRisk:
    correlation_group: str


# ---------------------------------------------------------------------------
# Equicorrelation matrix
# ---------------------------------------------------------------------------

class TestEquicorrelationMatrix:

    def test_identity_for_n1(self):
        mat = build_equicorrelation_matrix(1, 0.5)
        np.testing.assert_array_equal(mat, [[1.0]])

    def test_diagonal_is_one(self):
        mat = build_equicorrelation_matrix(5, 0.6)
        np.testing.assert_array_equal(np.diag(mat), np.ones(5))

    def test_off_diagonal_is_rho(self):
        mat = build_equicorrelation_matrix(4, 0.7)
        mask = ~np.eye(4, dtype=bool)
        np.testing.assert_array_almost_equal(mat[mask], 0.7)

    def test_positive_semi_definite(self):
        """All eigenvalues must be >= 0."""
        mat = build_equicorrelation_matrix(6, 0.5)
        eigenvalues = np.linalg.eigvalsh(mat)
        assert np.all(eigenvalues >= -1e-10)

    def test_rho_capped_below_one(self):
        """rho=1.0 should be capped to 0.99 for numerical stability."""
        mat = build_equicorrelation_matrix(3, 1.0)
        mask = ~np.eye(3, dtype=bool)
        assert np.all(mat[mask] <= 0.99)

    def test_empty(self):
        mat = build_equicorrelation_matrix(0, 0.5)
        assert mat.shape == (0, 0)


# ---------------------------------------------------------------------------
# Correlated uniform generation
# ---------------------------------------------------------------------------

class TestCorrelatedUniforms:

    def test_output_shape(self):
        rng = np.random.default_rng(42)
        U = generate_correlated_uniforms(1000, 5, 0.5, rng)
        assert U.shape == (1000, 5)

    def test_values_in_unit_interval(self):
        rng = np.random.default_rng(42)
        U = generate_correlated_uniforms(10_000, 4, 0.6, rng)
        assert np.all(U >= 0.0)
        assert np.all(U <= 1.0)

    def test_marginals_approximately_uniform(self):
        """Each column should be approximately U(0,1) — mean ~0.5, std ~0.289."""
        rng = np.random.default_rng(42)
        U = generate_correlated_uniforms(100_000, 3, 0.5, rng)
        for col in range(3):
            assert np.mean(U[:, col]) == pytest.approx(0.5, abs=0.02)
            assert np.std(U[:, col]) == pytest.approx(1 / np.sqrt(12), abs=0.02)

    def test_high_correlation(self):
        """rho=0.9 → Pearson correlation between columns should be ~0.9."""
        rng = np.random.default_rng(42)
        U = generate_correlated_uniforms(100_000, 3, 0.9, rng)
        # Check pairwise correlation of first two columns
        r = np.corrcoef(U[:, 0], U[:, 1])[0, 1]
        # Rank correlation won't be exactly 0.9 due to normal→uniform transform,
        # but should be strongly positive
        assert r > 0.80

    def test_zero_correlation(self):
        """rho=0 → columns should be approximately independent."""
        rng = np.random.default_rng(42)
        U = generate_correlated_uniforms(100_000, 3, 0.0, rng)
        r = np.corrcoef(U[:, 0], U[:, 1])[0, 1]
        assert abs(r) < 0.02

    def test_singleton_returns_uniform(self):
        """Single variable → plain uniform, ignore rho."""
        rng = np.random.default_rng(42)
        U = generate_correlated_uniforms(5000, 1, 0.8, rng)
        assert U.shape == (5000, 1)
        assert np.mean(U) == pytest.approx(0.5, abs=0.03)

    def test_empty_variables(self):
        rng = np.random.default_rng(42)
        U = generate_correlated_uniforms(100, 0, 0.5, rng)
        assert U.shape == (100, 0)

    def test_reproducible_with_seed(self):
        """Same seed → same output."""
        rng1 = np.random.default_rng(123)
        rng2 = np.random.default_rng(123)
        U1 = generate_correlated_uniforms(500, 3, 0.5, rng1)
        U2 = generate_correlated_uniforms(500, 3, 0.5, rng2)
        np.testing.assert_array_equal(U1, U2)


# ---------------------------------------------------------------------------
# Risk uniform matrix (group assembly)
# ---------------------------------------------------------------------------

class TestRiskUniformMatrix:

    def test_output_shape(self):
        risks = [MockRisk("CG01"), MockRisk("CG01"), MockRisk("CG02")]
        rng = np.random.default_rng(42)
        U = build_risk_uniform_matrix(1000, risks, {"CG01": 0.6, "CG02": 0.5}, rng)
        assert U.shape == (1000, 3)

    def test_within_group_correlated(self):
        """Risks in the same group should be correlated."""
        risks = [MockRisk("CG01")] * 4
        rng = np.random.default_rng(42)
        U = build_risk_uniform_matrix(100_000, risks, {"CG01": 0.8}, rng)
        r = np.corrcoef(U[:, 0], U[:, 1])[0, 1]
        assert r > 0.70

    def test_between_groups_independent(self):
        """Risks in different groups should be approximately independent."""
        risks = [MockRisk("CG01"), MockRisk("CG01"), MockRisk("CG02"), MockRisk("CG02")]
        rng = np.random.default_rng(42)
        U = build_risk_uniform_matrix(100_000, risks, {"CG01": 0.8, "CG02": 0.8}, rng)
        # CG01 member vs CG02 member
        r = np.corrcoef(U[:, 0], U[:, 2])[0, 1]
        assert abs(r) < 0.05

    def test_default_rho_for_unknown_group(self):
        """Groups not in corr_coefficients get rho=0.5 default."""
        risks = [MockRisk("CG99"), MockRisk("CG99")]
        rng = np.random.default_rng(42)
        U = build_risk_uniform_matrix(50_000, risks, {}, rng)  # empty coefficients
        r = np.corrcoef(U[:, 0], U[:, 1])[0, 1]
        # With rho=0.5, expect moderate correlation
        assert 0.30 < r < 0.70

    def test_singleton_group_independent(self):
        """A group with one member gets independent uniform draws."""
        risks = [MockRisk("CG01"), MockRisk("CG02"), MockRisk("CG03")]
        rng = np.random.default_rng(42)
        U = build_risk_uniform_matrix(10_000, risks, {}, rng)
        assert U.shape == (10_000, 3)
        # Each column should look uniform
        for col in range(3):
            assert 0.45 < np.mean(U[:, col]) < 0.55

    def test_empty_risks(self):
        rng = np.random.default_rng(42)
        U = build_risk_uniform_matrix(100, [], {}, rng)
        assert U.shape == (100, 0)

    def test_values_in_unit_interval(self):
        risks = [MockRisk("CG01")] * 5 + [MockRisk("CG02")] * 3
        rng = np.random.default_rng(42)
        U = build_risk_uniform_matrix(10_000, risks, {"CG01": 0.6, "CG02": 0.4}, rng)
        assert np.all(U >= 0.0)
        assert np.all(U <= 1.0)


# ---------------------------------------------------------------------------
# WBS bucket uniforms
# ---------------------------------------------------------------------------

class TestWBSUniforms:

    def test_shape_and_range(self):
        rng = np.random.default_rng(42)
        U = generate_wbs_uniforms(5000, 8, 0.4, rng)
        assert U.shape == (5000, 8)
        assert np.all(U >= 0.0)
        assert np.all(U <= 1.0)

    def test_cross_bucket_correlation(self):
        """WBS buckets should be moderately correlated at rho=0.4."""
        rng = np.random.default_rng(42)
        U = generate_wbs_uniforms(100_000, 8, 0.4, rng)
        r = np.corrcoef(U[:, 0], U[:, 1])[0, 1]
        assert 0.25 < r < 0.55
