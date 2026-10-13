"""QRAXL-01 step 4 - Layer-1 factor model gates.

Fast lane: OFF draws zero rng and is unchanged; ON preserves the Layer-2 draws
and adds the base contribution (single pass); the Beta-PERT percentile fit; the
correlation-sensitivity triple monotonicity; the Corr_flag PSD repair; the
no-double-count guard; validation checks. Slow lane: the pinned seed-42
owner-view result at 100k (the "new owner-view result, reproducible at seed 42"
gate) and the 100k triple.

The authoritative OFF-reproduces-baseline gate is
``tests/test_qraxl01_0_bit_identity.py`` (unchanged, raw ==); the fast OFF test
here is a per-call proxy that the Layer-1 wiring adds zero rng to the default
path.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from src.config import ChainConfig
import src.qra_core as qra_core
from src.layer1_factors import (
    Factor,
    Layer1Config,
    assert_no_double_count,
    correlated_uniforms,
    fit_pert_from_percentiles,
    nearest_psd,
    run_layer1_base,
    validate_layer1,
)
from tests.arch_guard import x86_64_only
from src.layer1_showcase import (
    SHOWCASE_FACTOR_DRIVERS,
    build_showcase_layer1,
    _FACTORS,
)

SEED = 42


def _l2_register() -> list[SimpleNamespace]:
    """Fixed owner-view Layer-2 register (no client data); the Severe weather
    season event is Lognormal (brief 1A)."""
    specs = [
        ("E_weather", 0.35, 3e5, 8e5, 4e6, "Lognormal", "CG01", 40),
        ("E_geotech", 0.20, 2e5, 6e5, 3e6, "Lognormal", "CG02", 120),
        ("E_grid", 0.30, 1e5, 4e5, 1.5e6, "PERT", "CG02", 200),
        ("E_supply", 0.45, 8e4, 2e5, 9e5, "Triangular", "CG01", 60),
        ("E_ehs", 0.25, 5e4, 1.5e5, 7e5, "PERT", "SGL1", 80),
    ]
    return [
        SimpleNamespace(
            risk_id=r, probability=p, opt_cost=o, ml_cost=m, pess_cost=x,
            distribution=d, correlation_group=g, planned_day=day,
        )
        for r, p, o, m, x, d, g, day in specs
    ]


def _common(n_iter: int, layer1=None) -> dict:
    return dict(
        n_iter=n_iter, risks=_l2_register(), cg_coefficients={"CG01": 0.5, "CG02": 0.5},
        dual_lookup={}, chain_risk_ids={}, chain_config=ChainConfig(), seed=SEED,
        layer1=layer1,
    )


# ---------------------------------------------------------------------------
# OFF: zero rng, byte-identical default path
# ---------------------------------------------------------------------------

def test_off_is_zero_rng_and_unchanged() -> None:
    reg = _l2_register()
    base = dict(risks=reg, cg_coefficients={"CG01": 0.5, "CG02": 0.5}, dual_lookup={},
                chain_risk_ids={}, chain_config=ChainConfig(), seed=SEED)
    default = qra_core.run_cost_layer(n_iter=20_000, **base)
    explicit_off = qra_core.run_cost_layer(n_iter=20_000, layer1=None, **base)
    assert np.array_equal(default["cost_dollars_array"], explicit_off["cost_dollars_array"])
    assert default["layer1_enabled"] is False
    assert default["layer1_base_array"] is None


# ---------------------------------------------------------------------------
# ON: single pass - Layer-2 untouched, base added
# ---------------------------------------------------------------------------

def test_on_preserves_l2_and_adds_base() -> None:
    off = qra_core.run_cost_layer(**_common(20_000))
    on = qra_core.run_cost_layer(**_common(20_000, build_showcase_layer1()))
    # Layer-1 draws come strictly AFTER Layer-2/chain/cascade: L2 is untouched.
    assert np.array_equal(off["per_risk_cost_array"], on["per_risk_cost_array"])
    assert np.array_equal(off["schedule_days_array"], on["schedule_days_array"])
    assert np.array_equal(off["timed_events"], on["timed_events"])  # base has no day
    assert on["layer1_enabled"] is True
    # owner cost = L2 event total + base contribution (single pass).
    l2 = on["per_risk_cost_array"].sum(axis=1)
    assert np.allclose(on["cost_dollars_array"], l2 + on["layer1_base_array"], rtol=1e-12, atol=0)


def test_on_reproducible_seed42() -> None:
    a = qra_core.run_cost_layer(**_common(10_000, build_showcase_layer1()))
    b = qra_core.run_cost_layer(**_common(10_000, build_showcase_layer1()))
    assert np.array_equal(a["cost_dollars_array"], b["cost_dollars_array"])
    assert np.array_equal(a["layer1_base_array"], b["layer1_base_array"])


# ---------------------------------------------------------------------------
# Beta-PERT percentile fit (brief section 1 build note)
# ---------------------------------------------------------------------------

def test_pert_percentile_fit_recovers_bounds_and_extends_tail() -> None:
    from scipy import stats
    for f in _FACTORS:
        lo, mode, hi = fit_pert_from_percentiles(f.opt, f.ml, f.p90)
        a = 1.0 + 4.0 * (mode - lo) / (hi - lo)
        b = 1.0 + 4.0 * (hi - mode) / (hi - lo)
        p10 = lo + (hi - lo) * stats.beta.ppf(0.10, a, b)
        p90 = lo + (hi - lo) * stats.beta.ppf(0.90, a, b)
        assert p10 == pytest.approx(f.opt, abs=1e-6), f.name
        assert p90 == pytest.approx(f.p90, abs=1e-6), f.name
        # percentile fit places the true min/max BEYOND the stated bounds
        assert lo < f.opt and hi > f.p90, f.name


# ---------------------------------------------------------------------------
# Correlation: sensitivity triple + PSD Corr_flag
# ---------------------------------------------------------------------------

def _owner_p(mode: str, n_iter: int, p: int) -> float:
    r = qra_core.run_cost_layer(**_common(n_iter, build_showcase_layer1(mode)))
    return float(np.percentile(r["cost_dollars_array"], p))


def test_correlation_sensitivity_triple_monotone() -> None:
    # Systemic upper tail widens with correlation: rho0 <= elicited <= rho1.
    for p in (80, 90):
        z = _owner_p("zero", 50_000, p)
        e = _owner_p("elicited", 50_000, p)
        o = _owner_p("one", 50_000, p)
        assert z <= e <= o, f"P{p}: {z} {e} {o}"
    # the tail spread rho1 - rho0 is materially positive
    assert _owner_p("one", 50_000, 90) - _owner_p("zero", 50_000, 90) > 1e6


def test_corr_flag_valid_for_elicited_and_snaps_nonpsd() -> None:
    # elicited matrix is PSD (Corr_flag valid)
    cfg = build_showcase_layer1("elicited")
    _, diag = correlated_uniforms(
        np.tril(cfg.corr_matrix) + np.tril(cfg.corr_matrix, -1).T, 100, np.random.default_rng(0)
    )
    assert diag["invalid"] is False and diag["min_eig"] > 0
    # a deliberately non-PSD matrix is flagged invalid and snapped to PSD
    bad = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, -0.9], [0.9, -0.9, 1.0]])
    psd = nearest_psd(bad)
    assert psd["invalid"] is True and psd["min_eig"] < 0
    w = np.linalg.eigvalsh(psd["matrix"])
    assert w.min() >= -1e-9  # repaired to PSD


# ---------------------------------------------------------------------------
# No-double-count guard (brief section 4)
# ---------------------------------------------------------------------------

def test_no_double_count_guard() -> None:
    # showcase set does NOT collide with the active event classes (weather
    # Productivity factor was dropped - decision 4)
    events = {"severe_weather", "geotech_surprise", "grid_delay"}
    assert_no_double_count(set(SHOWCASE_FACTOR_DRIVERS), events)  # no raise
    # a deliberately colliding fixture MUST fire
    with pytest.raises(ValueError, match="double-count"):
        assert_no_double_count(
            set(SHOWCASE_FACTOR_DRIVERS) | {"severe_weather"}, {"severe_weather"}
        )


# ---------------------------------------------------------------------------
# Validation / build checks
# ---------------------------------------------------------------------------

def test_showcase_base_sums_to_50m() -> None:
    cfg = build_showcase_layer1()
    assert cfg.base.sum() == pytest.approx(50_000_000.0, abs=1.0)
    validate_layer1(cfg)  # no raise


def test_validate_layer1_raises_on_bad_config() -> None:
    good = build_showcase_layer1()
    # base sum != declared total
    bad_base = Layer1Config(
        base=good.base * 1.1, row_labels=good.row_labels, col_labels=good.col_labels,
        factors=good.factors, corr_names=good.corr_names, corr_matrix=good.corr_matrix,
        declared_total=50_000_000.0,
    )
    with pytest.raises(ValueError, match="declared total"):
        validate_layer1(bad_base)
    # unknown column in a factor scope
    bad_scope = Layer1Config(
        base=good.base, row_labels=good.row_labels, col_labels=good.col_labels,
        factors=(Factor("X", "x", -0.1, 0.0, 0.1, ("NoSuchCol",), ("ALL",)),),
        corr_names=(), corr_matrix=np.zeros((0, 0)),
    )
    with pytest.raises(ValueError, match="unknown column"):
        validate_layer1(bad_scope)
    # corr matrix shape mismatch
    bad_corr = Layer1Config(
        base=good.base, row_labels=good.row_labels, col_labels=good.col_labels,
        factors=good.factors, corr_names=good.corr_names,
        corr_matrix=np.eye(3),  # wrong size (should be 7x7)
    )
    with pytest.raises(ValueError, match="corr matrix shape"):
        validate_layer1(bad_corr)


# ---------------------------------------------------------------------------
# Slow: pinned seed-42 owner-view result at 100k (new owner-view result)
# ---------------------------------------------------------------------------

# RE-BLESSED for this repository's lock, 01/09/2026 (PINNEDULP-01, Director-approved).
# Captured here: CPython 3.12.4, numpy 1.26.4, scipy 1.16.3, pandas 2.3.3, seed 42,
# N=100000, elicited correlation. Raw == reproducibility anchor.
#
# The previous pins were captured on scipy 1.16.2. The move is a scipy PATCH bump -
# 1.16.2 to 1.16.3 - inside SCIPY117-01's own `<1.17` bound, so that bound is not
# tight enough to hold these values and should not be read as if it were.
#
# Six values moved, by -3 to +3 ULP (relative ~1e-16). BOTH MEANS ARE UNCHANGED while
# percentiles and individual samples moved, which is the signature of float ordering
# shifting under a numerical-library patch rather than of a changed model: a mean
# averages ULP noise away, a percentile and a single draw do not.
_PINNED_100K = {
    "base_p80": 55996935.2302684,
    "base_mean": 53047282.15178579,
    "owner_cost_p80": 57213788.19364301,
    "owner_cost_mean": 54116663.19843759,
    "cost_first5": [
        54411202.063912526,
        52116775.134729736,
        53336411.29811651,
        52807186.05413784,
        60793528.88331425,
    ],
}


@pytest.mark.slow
@x86_64_only
def test_owner_view_seed42_pinned_100k() -> None:
    on = qra_core.run_cost_layer(**_common(100_000, build_showcase_layer1("elicited")))
    base = on["layer1_base_array"]
    cost = on["cost_dollars_array"]
    assert float(np.percentile(base, 80)) == _PINNED_100K["base_p80"]
    assert float(np.mean(base)) == _PINNED_100K["base_mean"]
    assert float(np.percentile(cost, 80)) == _PINNED_100K["owner_cost_p80"]
    assert float(np.mean(cost)) == _PINNED_100K["owner_cost_mean"]
    assert [float(x) for x in cost[:5]] == _PINNED_100K["cost_first5"]
    assert on["layer1_corr_diag"]["invalid"] is False


@pytest.mark.slow
def test_triple_monotone_100k() -> None:
    p90 = {m: _owner_p(m, 100_000, 90) for m in ("zero", "elicited", "one")}
    assert p90["zero"] <= p90["elicited"] <= p90["one"]
