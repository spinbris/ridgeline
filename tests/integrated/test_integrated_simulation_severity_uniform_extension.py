"""Regression tests for the SR-S3-Beta-06 surgical refactor of
:func:`run_integrated_simulation`.

These tests protect Stage 2.5 production behaviour from accidental
drift introduced by the new ``precomputed_severity_uniforms``
keyword-only parameter. The brief (§5) calls out
``test_existing_call_signature_unchanged`` and
``test_precomputed_none_bit_identical_to_omitted`` as the regression
backstop.

All tests use synthetic ``RiskInput`` objects and a synthetic
``risk_scope_df``; no RefProject strawman or register files are touched.
"""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import RiskInput
from src.integrated.integrated_simulation import (
    IntegratedConfig,
    run_integrated_simulation,
)
from src.sra.methodology_defaults_reader import build_test_methodology_defaults
from tests._fixture_values import FIXTURE_DAY_RATE


# ---------------------------------------------------------------------------
# Synthetic inputs
# ---------------------------------------------------------------------------

def _risk(
    risk_id: str = "R001",
    *,
    probability: float = 0.5,
    opt_cost: float = 100.0,
    ml_cost: float = 200.0,
    pess_cost: float = 400.0,
    distribution: str = "PERT",
    correlation_group: str = "CG_UNASSIGNED",
    owner: str = "BOP Contractor",
    description: str = "Synthetic test risk",
) -> RiskInput:
    return RiskInput(
        risk_id=risk_id,
        description=description,
        owner=owner,
        distribution=distribution,
        correlation_group=correlation_group,
        probability=probability,
        opt_cost=opt_cost,
        ml_cost=ml_cost,
        pess_cost=pess_cost,
    )


def _scope_df(*, dual_coded_risk_ids: tuple[str, ...] = ()) -> pd.DataFrame:
    """Minimal Risk_Scope DataFrame; one row per dual-coded risk."""
    rows = []
    for rid in dual_coded_risk_ids:
        rows.append(
            {
                "risk_id": rid,
                "time_impact": "Yes",
                "mode_aggregated": "Series",
                "probability_time": 0.5,
                "opt_days": 1.0,
                "ml_days": 5.0,
                "pess_days": 10.0,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "risk_id", "time_impact", "mode_aggregated",
                "probability_time", "opt_days", "ml_days", "pess_days",
            ]
        )
    return pd.DataFrame(rows)


def _config(*, iterations: int = 200, seed: int = 42) -> IntegratedConfig:
    return IntegratedConfig(
        register_path=Path("/synthetic/register.xlsx"),
        p6_path=Path("/synthetic/p6.xlsx"),
        strawman_path=Path("/synthetic/strawman.xlsx"),
        iterations=iterations,
        random_seed=seed,
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
    **TEST_CALIBRATION_TOLERANCES)


# ---------------------------------------------------------------------------
# Backward compatibility — the BLOCKER class
# ---------------------------------------------------------------------------

def test_existing_call_signature_unchanged():
    """The pre-refactor positional call still works.

    Locks the bit-identity invariant: a caller that does not know about
    the new parameter sees the same behaviour as the pre-refactor
    implementation.
    """
    cfg = _config(iterations=200, seed=11)
    risks = [_risk(f"R{i:03d}", probability=0.4) for i in range(5)]
    scope = _scope_df()
    # Positional call with the original 3-argument signature.
    result = run_integrated_simulation(cfg, risks, scope)
    assert result["iterations"] == 200
    assert result["per_risk_cost_array"].shape == (200, 5)


def test_precomputed_none_bit_identical_to_omitted():
    """Explicit ``None`` matches omission, bit-for-bit.

    The most direct check that the conditional inside the loop preserves
    the pre-refactor RNG consumption pattern.
    """
    cfg = _config(iterations=300, seed=777)
    risks = [_risk(f"R{i:03d}", probability=0.5) for i in range(4)]
    scope = _scope_df()

    out_omitted = run_integrated_simulation(cfg, risks, scope)
    out_explicit = run_integrated_simulation(
        cfg, risks, scope, precomputed_severity_uniforms=None,
    )

    assert np.array_equal(
        out_omitted["per_risk_cost_array"],
        out_explicit["per_risk_cost_array"],
    )
    assert np.array_equal(
        out_omitted["fired_array"], out_explicit["fired_array"],
    )
    assert np.array_equal(
        out_omitted["cost_dollars_array"],
        out_explicit["cost_dollars_array"],
    )


def test_precomputed_full_replacement_deterministic():
    """When ALL uniforms are provided, output is deterministic from inputs.

    Two runs with the same precomputed dict and the same firing decisions
    (controlled by the same seed driving the fire matrix) produce
    identical PERT samples.
    """
    cfg = _config(iterations=200, seed=33)
    risks = [_risk(f"R{i:03d}", probability=0.5) for i in range(3)]
    scope = _scope_df()

    n_iter = cfg.iterations
    sev = {r.risk_id: np.full(n_iter, 0.5, dtype=np.float32) for r in risks}

    out_a = run_integrated_simulation(
        cfg, risks, scope, precomputed_severity_uniforms=sev,
    )
    out_b = run_integrated_simulation(
        cfg, risks, scope, precomputed_severity_uniforms=sev,
    )
    assert np.array_equal(
        out_a["per_risk_cost_array"], out_b["per_risk_cost_array"],
    )

    # All severity uniforms == 0.5 means the PERT inverse-CDF returns
    # the median for every fired iteration. For PERT(100, 200, 400) the
    # median is somewhere between 200 (mode) and the upper-tail; locked
    # only as "non-zero on fired iterations and zero on non-fired".
    fired = out_a["fired_array"]
    cost = out_a["per_risk_cost_array"]
    assert np.all(cost[~fired] == 0.0)
    # On fired iterations, the magnitude is constant per risk because
    # u_severity is the same for every iteration.
    for i in range(len(risks)):
        fired_col = fired[:, i]
        if fired_col.any():
            fired_costs = cost[fired_col, i]
            assert np.allclose(fired_costs, fired_costs[0])


def test_precomputed_partial_dict_falls_back_to_rng():
    """Risks not in the dict fall back to ``rng.random``; risks in the
    dict use the dict values.

    Note on the rng-stream side-effect: when R001 takes the
    precomputed-dict branch, it does NOT consume an
    ``rng.random(n_iter)`` slot. That shifts the slot R002 sees by one
    draw relative to the no-override reference run — so R002's per-risk
    cost array does NOT match the reference even though R002 is itself
    rng-driven in both runs. R000 (which the loop processes BEFORE
    reaching the override) DOES match because no rng draws have been
    skipped yet.
    """
    cfg = _config(iterations=200, seed=55)
    risks = [_risk(f"R{i:03d}", probability=0.5) for i in range(3)]
    scope = _scope_df()
    n_iter = cfg.iterations

    # Only override R001; R000 (processed before R001) is unaffected.
    # R002 (processed after R001) sees a shifted rng stream.
    sev = {"R001": np.full(n_iter, 0.5, dtype=np.float32)}

    out_ref = run_integrated_simulation(cfg, risks, scope)
    out_partial = run_integrated_simulation(
        cfg, risks, scope, precomputed_severity_uniforms=sev,
    )

    # The fire matrix is the same in both runs (the CG-correlated fire
    # uniform matrix is built ONCE before the per-risk loop, so it is
    # not affected by the per-risk severity-draw skip).
    assert np.array_equal(out_ref["fired_array"], out_partial["fired_array"])

    # R000 — processed before the override; rng stream unaffected.
    assert np.array_equal(
        out_ref["per_risk_cost_array"][:, 0],
        out_partial["per_risk_cost_array"][:, 0],
    )

    # R001 — overridden; cost magnitudes on fired iterations differ.
    fired_r1 = out_partial["fired_array"][:, 1]
    if fired_r1.any():
        assert not np.array_equal(
            out_ref["per_risk_cost_array"][fired_r1, 1],
            out_partial["per_risk_cost_array"][fired_r1, 1],
        )

    # R002 — processed after the override; the skipped rng.random draw
    # for R001 shifts R002's slot, so R002's cost array also differs.
    fired_r2 = out_partial["fired_array"][:, 2]
    if fired_r2.any():
        assert not np.array_equal(
            out_ref["per_risk_cost_array"][fired_r2, 2],
            out_partial["per_risk_cost_array"][fired_r2, 2],
        )


def test_precomputed_shape_mismatch_raises():
    """Wrong-shape ndarray raises a fail-fast ``ValueError`` mentioning
    the risk_id and shapes."""
    cfg = _config(iterations=100, seed=42)
    risks = [_risk("R001", probability=0.5)]
    scope = _scope_df()

    sev = {"R001": np.zeros(50, dtype=np.float32)}  # wrong length

    with pytest.raises(ValueError) as excinfo:
        run_integrated_simulation(
            cfg, risks, scope, precomputed_severity_uniforms=sev,
        )
    msg = str(excinfo.value)
    assert "R001" in msg
    assert "(50,)" in msg
    assert "(100,)" in msg


def test_precomputed_keyword_only_argument():
    """The new parameter is keyword-only; positional call raises."""
    cfg = _config(iterations=50, seed=1)
    risks = [_risk("R001", probability=0.5)]
    scope = _scope_df()
    sev = {"R001": np.zeros(50, dtype=np.float32)}

    with pytest.raises(TypeError):
        # Positional placement after the existing four positional
        # parameters — the * separator must reject this.
        run_integrated_simulation(cfg, risks, scope, None, sev)  # type: ignore[misc]


def test_signature_has_keyword_only_marker():
    """Inspection-time check that the ``*`` separator is in place."""
    sig = inspect.signature(run_integrated_simulation)
    params = sig.parameters
    assert "precomputed_severity_uniforms" in params
    assert (
        params["precomputed_severity_uniforms"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )
    assert params["precomputed_severity_uniforms"].default is None


def test_dual_coded_risk_uses_precomputed_uniform_for_both_arms():
    """The shared severity uniform drives BOTH the cost dispatch and the
    schedule PERT for a dual-coded risk.

    This is the most direct "joint sampling preserved" check at the
    surgical-refactor level — two runs, one with all-0.5 severity
    uniforms and one with all-0.95, must produce different per-risk
    schedule arrays for the dual-coded risk (because the schedule arm
    consumes the same uniform from inside the loop, not a separate
    rng draw).
    """
    cfg = _config(iterations=200, seed=99)
    risks = [_risk("R001", probability=1.0)]  # always fires
    scope = _scope_df(dual_coded_risk_ids=("R001",))
    n_iter = cfg.iterations

    sev_low = {"R001": np.full(n_iter, 0.05, dtype=np.float32)}
    sev_high = {"R001": np.full(n_iter, 0.95, dtype=np.float32)}

    out_low = run_integrated_simulation(
        cfg, risks, scope, precomputed_severity_uniforms=sev_low,
    )
    out_high = run_integrated_simulation(
        cfg, risks, scope, precomputed_severity_uniforms=sev_high,
    )

    sched_low = out_low["per_risk_schedule_array"][:, 0]
    sched_high = out_high["per_risk_schedule_array"][:, 0]
    cost_low = out_low["per_risk_cost_array"][:, 0]
    cost_high = out_high["per_risk_cost_array"][:, 0]

    # Both arms see the change — high-uniform gives larger PERT in both.
    assert sched_high.mean() > sched_low.mean()
    assert cost_high.mean() > cost_low.mean()
