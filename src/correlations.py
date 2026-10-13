"""
Correlation matrix construction and correlated uniform generation.

Uses Cholesky decomposition to transform independent standard normals
into correlated normals, then applies normal CDF to get correlated
uniforms in [0, 1]. These uniforms feed into the distribution samplers.

Ported from the corr_u function in MC_CodeRef Cell 1 (the cost-model workbook).

Correlation groups (CG01–CG10) tag risks sharing a common economic driver.
Within-group correlation coefficients are read from MC_Params (default 0.5).
Between-group correlation is zero (risks in different groups are independent).
"""

import numpy as np
from scipy import stats


def build_equicorrelation_matrix(n: int, rho: float) -> np.ndarray:
    """Build an n×n equicorrelation matrix.

    All off-diagonal entries are rho, diagonal entries are 1.0.
    Used when all members of a correlation group share the same
    pairwise correlation (the standard construction risk assumption).

    Parameters
    ----------
    n : matrix dimension (number of variables in the group)
    rho : pairwise correlation coefficient (0.0 to 1.0)

    Returns
    -------
    n×n positive semi-definite correlation matrix
    """
    if n <= 0:
        return np.array([]).reshape(0, 0)
    if n == 1:
        return np.array([[1.0]])

    rho = np.clip(rho, 0.0, 0.99)  # cap below 1.0 for numerical stability
    mat = np.full((n, n), rho)
    np.fill_diagonal(mat, 1.0)
    return mat


def generate_correlated_uniforms(
    n_samples: int,
    n_variables: int,
    rho: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate correlated uniform draws via Cholesky decomposition.

    Process:
    1. Build equicorrelation matrix (n_variables × n_variables)
    2. Cholesky decompose: C = L @ L.T
    3. Draw independent standard normals Z (n_samples × n_variables)
    4. Correlated normals: Y = Z @ L.T
    5. Transform to uniforms: U = Phi(Y)

    Falls back to independent uniforms if Cholesky fails.

    Parameters
    ----------
    n_samples : number of simulation iterations
    n_variables : number of correlated variables in this group
    rho : equicorrelation coefficient
    rng : numpy random Generator for reproducibility

    Returns
    -------
    array (n_samples, n_variables) of correlated uniforms in [0, 1]
    """
    if n_variables <= 0:
        return np.array([]).reshape(n_samples, 0)

    if n_variables == 1:
        return rng.uniform(0, 1, (n_samples, 1))

    if rho <= 0.0:
        return rng.uniform(0, 1, (n_samples, n_variables))

    corr_matrix = build_equicorrelation_matrix(n_variables, rho)

    try:
        L = np.linalg.cholesky(corr_matrix)
    except np.linalg.LinAlgError:
        # Matrix not positive definite — fall back to independent
        return rng.uniform(0, 1, (n_samples, n_variables))

    # Independent standard normals → correlated normals → correlated uniforms
    Z = rng.standard_normal((n_samples, n_variables))
    Y = Z @ L.T
    U = stats.norm.cdf(Y)

    return U


def build_risk_uniform_matrix(
    n_iter: int,
    risks: list,
    corr_coefficients: dict,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate the full correlated uniform matrix for all risks.

    Groups risks by their correlation_group attribute, generates
    correlated uniforms per group, and assembles into a single
    (n_iter, n_risks) matrix.

    Risks in singleton groups (only one member) get independent draws.
    Risks in groups not found in corr_coefficients use rho=0.5 default.

    Parameters
    ----------
    n_iter : number of simulation iterations
    risks : list of RiskInput objects (must have .correlation_group attribute)
    corr_coefficients : dict mapping group code to rho (e.g. {"CG01": 0.6})
    rng : numpy random Generator

    Returns
    -------
    array (n_iter, n_risks) of correlated uniforms in [0, 1]
    """
    n_risks = len(risks)
    if n_risks == 0:
        return np.array([]).reshape(n_iter, 0)

    uniforms = np.zeros((n_iter, n_risks))

    # Group risks by correlation group
    groups: dict[str, list[int]] = {}
    for i, risk in enumerate(risks):
        cg = risk.correlation_group
        if cg not in groups:
            groups[cg] = []
        groups[cg].append(i)

    # Generate correlated uniforms per group
    for group_code, member_indices in groups.items():
        n_members = len(member_indices)
        rho = corr_coefficients.get(group_code, 0.5)
        U = generate_correlated_uniforms(n_iter, n_members, rho, rng)
        for j, risk_idx in enumerate(member_indices):
            uniforms[:, risk_idx] = U[:, j]

    return uniforms


def generate_wbs_uniforms(
    n_iter: int,
    n_buckets: int,
    rho: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate correlated uniforms for Layer 1 WBS buckets.

    The 8 WBS buckets share a cross-bucket correlation (rho=0.4 in the
    existing PY() code) reflecting common construction market conditions.

    Parameters
    ----------
    n_iter : number of iterations
    n_buckets : number of WBS buckets (8)
    rho : cross-bucket correlation coefficient
    rng : numpy random Generator

    Returns
    -------
    array (n_iter, n_buckets) of correlated uniforms
    """
    return generate_correlated_uniforms(n_iter, n_buckets, rho, rng)
