"""Native distribution dispatcher for the integrated engine (SR8, SP21).

Reads a risk's distribution_type from V8 register and routes to the existing
sampler functions in src/distributions.py. Reuses the cost engine's calibrated
samplers; does not re-implement any sampling math.

CRITICAL: Honours the V8 distribution_type. R013/R016.1/R067 are Lognormal,
R026.1 is Triangular, the rest of the 8 dual-coded set (R015.1, R016.2,
R017.1, R090) are PERT. Defaulting to PERT for non-PERT risks would diverge
from the cost engine's L2-only standalone and fail marginal calibration.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from src.distributions import (
    lognormal_cost_from_uniform,
    pert_from_uniform,
    triangular_from_uniform,
)


# ----------------------------------------------------------------------------
# Per-distribution single-uniform wrappers
# ----------------------------------------------------------------------------

def _sample_pert(u: float, opt: float, ml: float, pess: float) -> float:
    """PERT scalar wrapper around src/distributions.pert_from_uniform."""
    arr = pert_from_uniform(np.array([float(u)]), opt, ml, pess)
    return float(arr[0])


def _sample_lognormal(u: float, opt: float, ml: float, pess: float) -> float:
    """Lognormal scalar wrapper around src/distributions.lognormal_cost_from_uniform.

    The cost engine's lognormal sampler treats opt/ml/pess as the three-point
    estimate over the cost domain.
    """
    arr = lognormal_cost_from_uniform(np.array([float(u)]), opt, ml, pess)
    return float(arr[0])


def _sample_triangular(u: float, opt: float, ml: float, pess: float) -> float:
    """Triangular scalar wrapper around src/distributions.triangular_from_uniform."""
    arr = triangular_from_uniform(np.array([float(u)]), opt, ml, pess)
    return float(arr[0])


def _sample_binary(u: float, opt: float, ml: float, pess: float) -> float:
    """Binary returns the most-likely value when fired (firing already gated
    upstream by the Bernoulli on probability_<risk>).
    """
    return float(ml)


# ----------------------------------------------------------------------------
# Dispatcher dict - maps V8 distribution_type strings to sampler functions
# ----------------------------------------------------------------------------

DISTRIBUTION_SAMPLERS: dict[str, Callable[[float, float, float, float], float]] = {
    "PERT": _sample_pert,
    "Pert": _sample_pert,
    "Lognormal": _sample_lognormal,
    "LogNormal": _sample_lognormal,
    "Triangular": _sample_triangular,
    "Binary": _sample_binary,
    "Binary/PERT": _sample_pert,
}


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def sample_cost(risk_row: Any, u: float) -> float:
    """Sample one cost contribution for a single risk using its native distribution.

    Parameters
    ----------
    risk_row :
        A RiskInput dataclass (from v5_register_reader) OR a pd.Series-like
        object with attributes/keys: distribution, opt_cost, ml_cost, pess_cost.
    u :
        Single uniform draw in [0, 1].

    Returns
    -------
    float
        Cost contribution in dollars. Negative draws (Triangular with opt < 0
        for opportunity-shaped risks) are passed through unchanged - the cost
        engine treats opportunities as negative threats. The integrated engine
        preserves that behaviour.

    Raises
    ------
    ValueError
        If distribution_type is not in DISTRIBUTION_SAMPLERS. Defensive: V8
        having an unrecognised distribution_type should fail loudly rather
        than silently default to PERT.
    """
    dist_raw = _get_attr(risk_row, "distribution")
    opt = float(_get_attr(risk_row, "opt_cost"))
    ml = float(_get_attr(risk_row, "ml_cost"))
    pess = float(_get_attr(risk_row, "pess_cost"))

    if dist_raw is None:
        raise ValueError(
            f"Risk {_get_attr(risk_row, 'risk_id')!r}: distribution attribute is None"
        )
    dist_key = str(dist_raw).strip()

    sampler = DISTRIBUTION_SAMPLERS.get(dist_key)
    if sampler is None:
        # Try case-insensitive match
        for key, fn in DISTRIBUTION_SAMPLERS.items():
            if key.lower() == dist_key.lower():
                sampler = fn
                break

    if sampler is None:
        raise ValueError(
            f"Unknown distribution_type {dist_key!r} for risk "
            f"{_get_attr(risk_row, 'risk_id')!r}. Valid keys: "
            f"{sorted(set(DISTRIBUTION_SAMPLERS.keys()))}"
        )

    return sampler(float(u), opt, ml, pess)


def _get_attr(obj: Any, name: str) -> Any:
    """Get attribute or dict-style key, returning None if missing.

    Supports both RiskInput dataclasses and pandas Series.
    """
    if hasattr(obj, name):
        return getattr(obj, name)
    try:
        return obj[name]
    except (KeyError, TypeError, IndexError):
        return None
