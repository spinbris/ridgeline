"""QRAXL-01 step 4 - Layer-1 GN3A factor composition (engine methods).

A systemic-driver cost layer that composes over a WBS x cost-category base
matrix. Each factor is a proportional delta sampled ONCE per iteration by the
engine's Beta-PERT (``src.distributions.pert_from_uniform``); correlated factors
share a Cholesky Gaussian-copula draw (the engine's correlation method, as in
``src.correlations``). The per-iteration base contribution is added to the
Layer-2 event total in the SAME iteration (single pass), never as two models
with P-values added.

DELIBERATE METHODOLOGY (brief section 5, FLAG A): this is the ENGINE's
re-expression of the RF-01 factor STRUCTURE, not a numeric port of it. RF-01
uses fitted triangular + Iman-Conover rank correlation; this module uses
Beta-PERT + Cholesky Gaussian copula on purpose ("no rf_core, no Trigen, no
Iman-Conover"). The Layer-1-ON result is therefore a NEW owner-view result, not
bit-comparable to the RF-01 prototype.

Pyodide-clean: imports only numpy, scipy.stats, and src.distributions - stays
inside qra_core's clean import closure. Dimension-agnostic: factor count, base
rows/columns and correlated-set membership are all data, discovered at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import stats

from src.distributions import pert_from_uniform

_ALL = "ALL"  # column-scope / row-scope sentinel meaning "every column/row"


# ----------------------------------------------------------------------------
# Data model (all inputs are data - swap per project)
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Factor:
    """One systemic Layer-1 driver.

    ``opt`` / ``p90`` are read as P10 / P90 PERCENTILES of the proportional
    delta (not absolute min/max); ``ml`` is the mode. The multiplier applied to
    a bound cell is ``1 + delta``. ``driver`` is the classification used by the
    no-double-count guard against the Layer-2 event set.
    """

    name: str
    driver: str
    opt: float          # P10 delta
    ml: float           # mode delta (typically 0.0)
    p90: float          # P90 delta
    col_scope: tuple[str, ...]   # (_ALL,) => all columns, else a subset
    rows: tuple[str, ...]        # (_ALL,) => all rows, else a subset


@dataclass
class Layer1Config:
    """Runtime-discovered Layer-1 spec. ``base`` is in DOLLARS (not $M) so the
    composed contribution adds directly to the Layer-2 event cost array."""

    base: np.ndarray                 # (nR, nC) float64, dollars
    row_labels: tuple[str, ...]
    col_labels: tuple[str, ...]
    factors: tuple[Factor, ...]
    corr_names: tuple[str, ...]      # subset of factor names, matrix order
    corr_matrix: np.ndarray          # (k, k) symmetric (lower triangle is mirrored)
    corr_mode: str = "elicited"      # "zero" | "elicited" | "one"
    declared_total: float | None = None  # dollars; build-check target


# ----------------------------------------------------------------------------
# Beta-PERT fit from P10/P90 percentiles (brief section 1 build note)
# ----------------------------------------------------------------------------

def fit_pert_from_percentiles(
    opt: float, ml: float, p90: float, lam: float = 4.0
) -> tuple[float, float, float]:
    """Return (lo, mode, hi) for a PERT whose P10==opt, P90==p90, mode==ml.

    A percentile fit places the true min/max BEYOND the stated bounds, giving
    more tail than reading opt/p90 as min/max. 1D bisection on the mode's
    fractional position ``r = (mode-lo)/(hi-lo)`` using the standard PERT->Beta
    shape (alpha=1+lam*r, beta=1+lam*(1-r)); Beta quantiles from
    ``scipy.stats.beta.ppf`` (engine method, Pyodide-clean).
    """
    if opt == ml == p90:
        return (ml, ml, ml)
    if not (opt < ml < p90) and not (opt <= ml <= p90):
        raise ValueError(f"factor bounds not ordered: opt={opt} ml={ml} p90={p90}")

    def beta_q(r: float, q: float) -> float:
        a = 1.0 + lam * r
        b = 1.0 + lam * (1.0 - r)
        return float(stats.beta.ppf(q, a, b))

    # P_q = mode + W*(beta_q - r); ratio removes W:
    #   (beta_10 - r)/(beta_90 - r) = (opt-mode)/(p90-mode)
    target = (opt - ml) / (p90 - ml)

    def resid(r: float) -> float:
        return (beta_q(r, 0.10) - r) / (beta_q(r, 0.90) - r) - target

    lo_r, hi_r = 1e-6, 1.0 - 1e-6
    f_lo = resid(lo_r)
    for _ in range(200):
        mid = 0.5 * (lo_r + hi_r)
        f_mid = resid(mid)
        if f_lo * f_mid <= 0:
            hi_r = mid
        else:
            lo_r, f_lo = mid, f_mid
    r = 0.5 * (lo_r + hi_r)
    # Recover the width from whichever anchor carries it. Normally the low one:
    # opt-mode and (b10-r) share sign. But a ONE-SIDED factor - P10 equal to the
    # mode, i.e. "this can overrun but will not underrun" - drives the solver to the
    # r where beta_q(r, 0.10) == r, and the low anchor becomes 0/0: both sides vanish
    # whatever the width, so it constrains nothing. The HIGH anchor still does, and
    # is exact rather than a fallback. PERT1SIDE-01, found by ROAD-01: the shape is
    # ordinary elicitation and the department's own road model (RFM3) uses it for
    # five of its factors, but the only Layer-1 dataset that existed - wind - has
    # none, so the case raised ZeroDivisionError from the day Layer 1 was written.
    # The ordering guard above already ADMITS opt == ml; only the body could not.
    if opt == ml:
        width = (p90 - ml) / (beta_q(r, 0.90) - r)
    else:
        width = (opt - ml) / (beta_q(r, 0.10) - r)
    lo = ml - r * width
    hi = ml + (1.0 - r) * width
    return (float(lo), float(ml), float(hi))


# ----------------------------------------------------------------------------
# Correlation: nearest-PSD repair + Cholesky Gaussian-copula uniforms
# ----------------------------------------------------------------------------

def nearest_psd(corr: np.ndarray) -> dict[str, Any]:
    """Symmetrise, eigenvalue-floor to the nearest PSD, renormalise unit diag.

    Returns the repaired matrix plus the Corr_flag diagnostics: ``invalid``
    (any eigenvalue < -1e-8, the standing Corr_flag), ``min_eig``, the largest
    off-diagonal adjustment and the worst-moved index pair.
    """
    c0 = (corr + corr.T) / 2.0
    w, v = np.linalg.eigh(c0)
    min_eig = float(w.min())
    invalid = bool((w < -1e-8).any())
    c = c0
    if (w < 1e-8).any():
        w = np.clip(w, 1e-8, None)
        c = v @ np.diag(w) @ v.T
        d = np.sqrt(np.diag(c))
        c = c / np.outer(d, d)
    diff = np.abs(np.triu(c - c0, 1))
    if diff.size:
        p, q = np.unravel_index(int(np.argmax(diff)), diff.shape)
        max_adjust = float(diff[p, q])
        worst_pair = (int(p), int(q))
    else:
        max_adjust, worst_pair = 0.0, (0, 0)
    return {
        "matrix": c,
        "invalid": invalid,
        "min_eig": min_eig,
        "max_adjust": max_adjust,
        "worst_pair": worst_pair,
    }


def _resolve_corr_matrix(cfg: Layer1Config) -> np.ndarray:
    """Apply the sensitivity mode to the elicited matrix (brief section 3).

    zero -> identity (independence); elicited -> mirrored lower triangle;
    one -> 0.999 off-diagonal (perfect-correlation bound; exactly 1 is singular,
    matching the GN3A rho=1 sensitivity case).
    """
    k = len(cfg.corr_names)
    mode = cfg.corr_mode
    if mode == "zero":
        return np.eye(k)
    if mode == "one":
        c = np.full((k, k), 0.999)
        np.fill_diagonal(c, 1.0)
        return c
    if mode == "elicited":
        c = np.asarray(cfg.corr_matrix, dtype=float)
        c = np.tril(c) + np.tril(c, -1).T   # mirror the elicited lower triangle
        np.fill_diagonal(c, 1.0)
        return c
    raise ValueError(f"unknown corr_mode {mode!r} (zero|elicited|one)")


def correlated_uniforms(
    corr: np.ndarray, n_iter: int, rng: np.random.Generator
) -> tuple[np.ndarray, dict[str, Any]]:
    """(n_iter, k) correlated U(0,1) via Cholesky Gaussian copula: U=Phi(Z @ L.T).

    The engine's correlation method (as in src.correlations.generate_correlated
    _uniforms), generalised to an arbitrary PSD-repaired matrix.
    """
    psd = nearest_psd(corr)
    c = psd["matrix"]
    k = c.shape[0]
    if k == 0:
        return np.zeros((n_iter, 0)), psd
    L = np.linalg.cholesky(c)
    z = rng.standard_normal((n_iter, k))
    y = z @ L.T
    u = stats.norm.cdf(y)
    return u, psd


# ----------------------------------------------------------------------------
# Composition
# ----------------------------------------------------------------------------

def _cell_masks(cfg: Layer1Config) -> list[np.ndarray]:
    """Boolean (nR, nC) mask per factor: cell (r,c) is bound iff the factor's
    row scope covers r AND its column scope covers c."""
    row_ix = {r: i for i, r in enumerate(cfg.row_labels)}
    col_ix = {c: j for j, c in enumerate(cfg.col_labels)}
    n_r, n_c = cfg.base.shape
    masks = []
    for f in cfg.factors:
        m = np.zeros((n_r, n_c), dtype=bool)
        rows = range(n_r) if (_ALL in f.rows) else [row_ix[r] for r in f.rows]
        cols = range(n_c) if (_ALL in f.col_scope) else [col_ix[c] for c in f.col_scope]
        for ri in rows:
            for ci in cols:
                m[ri, ci] = True
        masks.append(m)
    return masks


def run_layer1_base(
    n_iter: int, cfg: Layer1Config, rng: np.random.Generator
) -> dict[str, Any]:
    """Compose the per-iteration Layer-1 base contribution (dollars).

    Draw order (deterministic for seed reproducibility): the correlated block
    first (one ``standard_normal((n_iter, k))``), then each independent factor's
    uniform in factor-definition order. Returns ``base_array`` (n_iter,), the
    correlation diagnostics, and per-factor mean multipliers (attribution).
    """
    validate_layer1(cfg)
    masks = _cell_masks(cfg)
    corr_set = set(cfg.corr_names)

    # 1. correlated block (in corr_names order), then independents in def order.
    corr_matrix = _resolve_corr_matrix(cfg)
    u_corr, corr_diag = correlated_uniforms(corr_matrix, n_iter, rng)
    corr_pos = {name: i for i, name in enumerate(cfg.corr_names)}

    mults: dict[str, np.ndarray] = {}
    factor_mean_mult: dict[str, float] = {}
    for f in cfg.factors:
        if f.name in corr_set:
            u = u_corr[:, corr_pos[f.name]]
        else:
            u = rng.random(n_iter)
        lo, mode, hi = fit_pert_from_percentiles(f.opt, f.ml, f.p90)
        delta = pert_from_uniform(u, lo, mode, hi)
        mult = 1.0 + delta
        mults[f.name] = mult
        factor_mean_mult[f.name] = float(mult.mean())

    # 2. cell multiplier = product of every factor bound to that cell.
    n_r, n_c = cfg.base.shape
    cell_mult = np.ones((n_iter, n_r, n_c), dtype=np.float64)
    for f, mask in zip(cfg.factors, masks):
        if not mask.any():
            continue
        cell_mult[:, mask] *= mults[f.name][:, None]

    # 3. base contribution = sum over cells of base_cell * cell_multiplier.
    base_array = np.tensordot(cell_mult, cfg.base, axes=([1, 2], [0, 1]))

    return {
        "base_array": base_array,
        "corr_diag": corr_diag,
        "corr_mode": cfg.corr_mode,
        "factor_mean_mult": factor_mean_mult,
        "base_total": float(cfg.base.sum()),
    }


# ----------------------------------------------------------------------------
# Guards / validation (brief sections 2, 4, 5)
# ----------------------------------------------------------------------------

def validate_layer1(cfg: Layer1Config) -> None:
    """Runtime build checks - raise loudly, never silently default."""
    n_r, n_c = cfg.base.shape
    if (n_r, n_c) != (len(cfg.row_labels), len(cfg.col_labels)):
        raise ValueError(
            f"base shape {cfg.base.shape} != labels "
            f"({len(cfg.row_labels)}, {len(cfg.col_labels)})"
        )
    names = [f.name for f in cfg.factors]
    if len(names) != len(set(names)):
        raise ValueError("duplicate factor name in Layer-1 set")
    valid_cols = set(cfg.col_labels)
    valid_rows = set(cfg.row_labels)
    for f in cfg.factors:
        if not (f.opt <= f.ml <= f.p90):
            raise ValueError(f"factor {f.name}: bounds not ordered")
        if _ALL not in f.col_scope and not set(f.col_scope) <= valid_cols:
            raise ValueError(f"factor {f.name}: unknown column in scope {f.col_scope}")
        if _ALL not in f.rows and not set(f.rows) <= valid_rows:
            raise ValueError(f"factor {f.name}: unknown row in scope {f.rows}")
        if len(f.rows) == 0 or len(f.col_scope) == 0:
            raise ValueError(f"factor {f.name}: empty scope - bind rows/cols or remove it")
    if len(cfg.corr_names) != len(set(cfg.corr_names)):
        raise ValueError("duplicate name in corr set")
    if not set(cfg.corr_names) <= set(names):
        raise ValueError("corr set references an undefined factor")
    k = len(cfg.corr_names)
    if cfg.corr_matrix.shape != (k, k):
        raise ValueError(
            f"corr matrix shape {cfg.corr_matrix.shape} != ({k}, {k})"
        )
    if cfg.declared_total is not None:
        if abs(float(cfg.base.sum()) - cfg.declared_total) > 1e-6 * max(1.0, abs(cfg.declared_total)):
            raise ValueError(
                f"base sum {cfg.base.sum()} != declared total {cfg.declared_total}"
            )


def assert_no_double_count(
    active_factor_drivers: set[str], active_event_classifications: set[str]
) -> None:
    """No active factor's driver may collide with an active event's class
    (brief section 4). Raises on any overlap - the guard that must fire on a
    deliberately colliding fixture before Layer 1 goes live on a real project."""
    collision = active_factor_drivers & active_event_classifications
    if collision:
        raise ValueError(
            "Layer-1 double-count: factor driver(s) collide with active event "
            f"classification(s): {sorted(collision)}. Resolve before enabling "
            "Layer 1 (a factor and an event must not both own the same driver)."
        )
