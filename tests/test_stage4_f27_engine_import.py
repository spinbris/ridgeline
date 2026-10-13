"""Stage 4 F-27 (D-2, first-rank): the deliverable path must run a third project without the engine
asking its binding for a value the path never uses.

Found on 08/09/2026 running the Kestrel Highway register through RUN_FINAL.bat: `MonteCarloEngine`
imported `WBS_CROSS_BUCKET_RHO` from `src.defaults` in its constructor, before reading its arguments.
That name resolves through the active binding's `headless_config`, which the road binding omits on
purpose (supplying values nothing asks for puts un-elicited numbers on the record). The deliverable
passes `buckets=[]`, so the value would never have been used - and the run halted anyway, with an
error whose own remedy named the path that had just failed.

The fix resolves the value where it is used, in the Layer-1 bucket draw, which `run()` never reaches
when there are no buckets. Bit-identity: when buckets exist the same value is resolved from the same
place; the random stream is untouched either way.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.config import ChainConfig, RiskInput, SimConfig
from src.simulation import MonteCarloEngine

_RISK = RiskInput(
    risk_id="KH-001", description="a risk", owner="", distribution="PERT",
    correlation_group="CG01", probability=0.4, opt_cost=100.0, ml_cost=200.0, pess_cost=500.0,
    ml_days=0.0, mc_include=True, basis="", recurrence_type="", opt_schedule_days=0.0,
    pess_schedule_days=0.0, cause="", consequence="", existing_controls="", risk_status="Open",
    direction="Threat", rbs_l1="", rbs_l2="", planned_day=0,
)


@pytest.fixture
def road_active(monkeypatch):
    """The road binding active: no headless_config, by design."""
    from src.am.project_binding import activate_project
    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    activate_project("synthetic_road")
    yield


def _engine(**kw):
    return MonteCarloEngine(
        config=SimConfig(n_iter=200, seed=7, view="owner"),
        buckets=[], chains=ChainConfig(), risks=[_RISK],
        corr_coefficients={"CG01": 0.5}, seed=7, **kw,
    )


def test_a_project_with_no_headless_config_runs_the_no_bucket_path(road_active):
    """Red before the fix: ValueError from src.defaults at construction. The deliverable path
    passes no buckets, so nothing here should ask the binding for the bucket correlation."""
    res = _engine().run()
    assert res.ev_costs.shape == (200, 1)
    # with no buckets the Layer-1 total is TIC and nothing else, every iteration
    assert res.l1_buckets.shape == (200, 0)
    assert np.array_equal(res.l1_cost, np.full(200, SimConfig().tic))


def test_a_project_with_no_headless_config_still_refuses_when_buckets_need_the_value(road_active):
    """The fail-loud behaviour is kept where it has something to catch: a project that DOES run
    Layer-1 buckets without declaring the correlation is refused, by name, at the draw."""
    from src.config import WBSBucket
    buckets = [WBSBucket(name=n, base_cost=1e6, low_var=-0.1, high_var=0.2, distribution="pert")
               for n in ("B1", "B2")]   # two: the correlated draw is the only reader of the value
    with pytest.raises(ValueError, match="wbs_cross_bucket_rho"):
        MonteCarloEngine(
            config=SimConfig(n_iter=50, seed=7, view="owner"),
            buckets=buckets, chains=ChainConfig(), risks=[_RISK],
            corr_coefficients={"CG01": 0.5}, seed=7,
        ).run()


def test_an_explicit_rho_is_used_without_touching_the_binding(road_active):
    from src.config import WBSBucket
    bucket = WBSBucket(name="B1", base_cost=1e6, low_var=-0.1, high_var=0.2, distribution="pert")
    res = MonteCarloEngine(
        config=SimConfig(n_iter=50, seed=7, view="owner"),
        buckets=[bucket], chains=ChainConfig(), risks=[_RISK],
        corr_coefficients={"CG01": 0.5}, seed=7, wbs_rho=0.3,
    ).run()
    assert res.l1_buckets.shape == (50, 1)
