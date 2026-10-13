"""
Distribution sampling functions for Monte Carlo simulation.

Supported distribution types (set in MC_Inputs Distribution column):
  - Triangular: three-point (Opt, ML, Pess), linear PDF
  - PERT: three-point, Beta-weighted around mode (lambda=4)
  - Binary: fixed ML cost on fire (Bernoulli gate in simulation.py)
  - Binary/PERT: Bernoulli gate + PERT cost draw on fire
  - Lognormal: right-tailed, ML=median, Opt≈P10, Pess≈P90
"""

import numpy as np
from scipy import stats


def triangular_from_uniform(
    u: np.ndarray, opt: float, ml: float, pess: float
) -> np.ndarray:
    """Sample from a triangular distribution using uniform draws.

    Handles three cases:
    1. Pure threat (opt >= 0, ml > 0): sample from [opt, pess] with mode=ml
    2. Pure opportunity (ml < 0): all values negative
    3. Two-sided (opt < 0, ml >= 0): sample from [opt, pess] with mode=ml

    Parameters
    ----------
    u : array of uniform draws in [0, 1]
    opt : optimistic value (can be negative for upside)
    ml : most-likely value (mode)
    pess : pessimistic value (highest cost impact)

    Returns
    -------
    array of samples, same shape as u
    """
    u = np.asarray(u, dtype=np.float64)

    # Determine the actual lo, mode, hi from the inputs
    if ml < 0:
        # Pure opportunity: sort so lo < mode < hi (all negative or zero)
        lo = min(opt, ml, pess)
        hi = max(opt, ml, pess)
        mode = ml
    else:
        # Threat or two-sided: opt is the lowest (can be negative),
        # pess is the highest
        lo = opt
        mode = ml
        hi = pess

    # Ensure lo <= mode <= hi (defensive — handles reversed inputs)
    lo, hi = min(lo, mode), max(hi, mode)

    # Degenerate case
    if hi == lo:
        return np.full_like(u, mode)

    # Inverse CDF of triangular distribution
    f = (mode - lo) / (hi - lo)
    result = np.where(
        u < f,
        lo + np.sqrt(u * (hi - lo) * (mode - lo)),
        hi - np.sqrt((1.0 - u) * (hi - lo) * (hi - mode)),
    )

    # Clip to valid range (numerical safety)
    result = np.clip(result, lo, hi)

    return result


def pert_from_uniform(
    u: np.ndarray, opt: float, ml: float, pess: float, lam: float = 4.0
) -> np.ndarray:
    """Sample from a PERT distribution using uniform draws.

    PERT is a rescaled Beta distribution. The lambda parameter controls
    how strongly the mode is weighted (default 4.0 = standard PERT).

    Handles three cases:
    1. Pure threat (opt >= 0, ml > 0): sample from [opt, pess] with mode=ml
    2. Pure opportunity (ml < 0): all values negative
    3. Two-sided (opt < 0, ml >= 0): sample from [opt, pess] with mode=ml

    Parameters
    ----------
    u : array of uniform draws in [0, 1]
    opt : optimistic (minimum / most favourable)
    ml : most-likely (mode)
    pess : pessimistic (maximum / worst case)
    lam : PERT lambda parameter (default 4.0)

    Returns
    -------
    array of samples, same shape as u
    """
    u = np.asarray(u, dtype=np.float64)

    # Determine lo, mode, hi
    if ml < 0:
        lo = min(opt, ml, pess)
        hi = max(opt, ml, pess)
        mode = ml
    else:
        lo = opt
        mode = ml
        hi = pess

    # Ensure lo <= mode <= hi (defensive — handles reversed inputs)
    lo, hi = min(lo, mode), max(hi, mode)

    # Degenerate case
    if hi == lo:
        return np.full_like(u, mode)

    # PERT Beta shape parameters
    alpha = max(1.0 + lam * (mode - lo) / (hi - lo), 0.1)
    beta_param = max(1.0 + lam * (hi - mode) / (hi - lo), 0.1)

    # Inverse CDF: Beta -> rescale to [lo, hi]
    u_clipped = np.clip(u, 1e-10, 1.0 - 1e-10)
    result = stats.beta.ppf(u_clipped, alpha, beta_param) * (hi - lo) + lo

    return result


def lognormal_from_uniform(
    u: np.ndarray, low_pct: float, high_pct: float
) -> np.ndarray:
    """Sample a percentage variation from a lognormal distribution.

    Used for Layer 1 WBS bucket variation where the distribution is
    right-skewed (e.g. labour rates: -5% to +25%).

    The mode of the percentage is (low + high) / 2. The lognormal is
    parameterised so that the mode maps to the median and the range
    maps to approximately +/- 2 sigma.

    Parameters
    ----------
    u : array of uniform draws in [0, 1]
    low_pct : lower bound as decimal (e.g. -0.05 for -5%)
    high_pct : upper bound as decimal (e.g. 0.25 for +25%)

    Returns
    -------
    array of percentage variations (e.g. 0.12 means +12%)
    """
    u = np.asarray(u, dtype=np.float64)

    mode = (low_pct + high_pct) / 2.0
    sigma = (high_pct - low_pct) / 4.0

    if sigma <= 0:
        return np.full_like(u, mode)

    # Lognormal parameterisation: log(1 + mode) centres the distribution
    mu_ln = np.log(1.0 + mode) - 0.5 * sigma ** 2
    u_clipped = np.clip(u, 1e-6, 1.0 - 1e-6)
    result = np.exp(stats.norm.ppf(u_clipped) * sigma + mu_ln) - 1.0

    return result


def lognormal_cost_from_uniform(
    u: np.ndarray, opt: float, ml: float, pess: float
) -> np.ndarray:
    """Sample from a lognormal distribution using Opt/ML/Pess as dollar costs.

    For catastrophic event risks (force majeure, pandemic, geopolitical)
    where the right tail matters commercially (P90/P95 carry weight in
    contingency sizing and lender presentations).

    Parameterisation:
      - ML maps to the median (P50) of the lognormal
      - Opt maps approximately to the P10
      - Pess maps approximately to the P90
      - The distribution extends beyond Pess (unlike Triangular which truncates)

    The lognormal is parameterised via:
      mu = ln(ML)
      sigma = (ln(Pess) - ln(Opt)) / (2 * 1.2816)
        where 1.2816 = Phi^{-1}(0.90) — maps Opt->P10 and Pess->P90

    Parameters
    ----------
    u : array of uniform draws in [0, 1]
    opt : optimistic cost impact ($) — must be > 0
    ml : most-likely cost impact ($) — must be > 0
    pess : pessimistic cost impact ($) — must be > 0

    Returns
    -------
    array of cost samples ($), same shape as u
    """
    u = np.asarray(u, dtype=np.float64)

    # Handle degenerate cases
    if ml <= 0:
        return np.full_like(u, 0.0)
    if pess <= opt or pess <= 0 or opt <= 0:
        return np.full_like(u, abs(ml))

    # Parameterisation: ML = median, Opt ~ P10, Pess ~ P90
    mu = np.log(abs(ml))
    # sigma from Opt/Pess spread: ln(Pess/Opt) covers ~80% of the distribution
    # P10 to P90 = 2 * z_0.90 * sigma where z_0.90 = 1.2816
    sigma = (np.log(abs(pess)) - np.log(abs(opt))) / (2 * 1.2816)
    sigma = max(sigma, 0.01)  # floor to avoid degenerate distribution

    u_clipped = np.clip(u, 1e-10, 1.0 - 1e-10)
    result = np.exp(stats.norm.ppf(u_clipped) * sigma + mu)

    return result


def sample_cost(
    u: np.ndarray, opt: float, ml: float, pess: float, distribution: str
) -> np.ndarray:
    """Dispatch to the correct distribution sampler.

    Parameters
    ----------
    u : uniform draws
    opt, ml, pess : three-point estimate
    distribution : "Triangular", "PERT", "Binary", "Binary/PERT", or "Lognormal"

    Returns
    -------
    array of cost samples
    """
    dist = distribution.strip().lower()

    if dist in ("pert", "binary/pert"):
        return pert_from_uniform(u, opt, ml, pess)
    elif dist == "binary":
        # Binary: either ml or 0 (firing already handled by probability)
        return np.full_like(u, ml, dtype=np.float64)
    elif dist == "lognormal":
        return lognormal_cost_from_uniform(u, opt, ml, pess)
    else:
        # Default to triangular
        return triangular_from_uniform(u, opt, ml, pess)
