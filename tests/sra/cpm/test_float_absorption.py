"""A delay on a floated path does not reach the finish; the same delay on the critical path does.

SHOWCASE-02 D-1(c), signed 19/09/2026 - the commissioned demonstration that a CPM replay
differs from an additive sum.

WHY THIS TEST HAD TO BE BUILT ON A NEW FIXTURE
    S-3 measured the replay-vs-additive gap on both shipped projects at 100,000 iterations
    and found it **exactly zero**, on every iteration (brief §2.6, ledger CPMINERT-01). Not
    small - zero. All 20 drivers across the two projects carry
    ``discrete_event_additive_days`` AND a gating activity with zero total float, so every
    delay is fired at a critical gate and reaches the finish undiminished. Summing is then
    the same arithmetic the CPM performs, and neither fixture can show a difference.

    So the property is asserted here, on ``tests/fixtures/float_absorption/``, built by
    ``scripts/build_float_absorption_fixture.py``. It touches no shipped project's inputs
    and moves no golden.

WHAT IS ASSERTED, AND WHY IT CANNOT GO FLAKY
    The fixture is two parallel paths: FA.CRIT (400 h, zero float) and FA.FLOAT (80 h,
    320 h of float). Both risks draw the same PERT, 5/10/20 **days**, so the largest
    possible delay is 20 days = 160 h - less than half FA.FLOAT's float. The floated risk
    therefore contributes **exactly zero** to the project finish on every iteration, and
    the gap equals the whole of its draw. No iteration count, seed or tail can change that;
    there is no distributional claim here to be flaky about.

THE CONTROL IS THE POINT
    ``test_the_same_delay_on_the_critical_path_is_not_absorbed`` re-gates the floated risk
    onto FA.CRIT and asserts the gap collapses to zero. That is not a contrived negative -
    it is precisely the configuration both shipped projects are in, so the control
    reproduces CPMINERT-01 in three lines and the positive case cannot be passing for some
    unrelated reason.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.sra.cpm.cpm_simulation import ScheduleMCConfig, run_schedule_mc
from src.sra.cpm.deterministic import deterministic_finish_hours
from src.sra.cpm.graph_builder import build_schedule_graph
from src.sra.cpm.risk_driver_schema import RiskDriver
from src.sra.cpm.xer_reader import parse_xer

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "float_absorption" / "float_absorption_schedule.xer"

N_ITER = 2_000
SEED = 42
#: PERT in days. Max 20 d = 160 h, against FA.FLOAT's 320 h of float.
PERT_DAYS = (5.0, 10.0, 20.0)
MODE_MAP = {"Series": 1.0, "Hybrid": 0.5, "Parallel": 0.0}

#: One severity draw per risk id, built once and reused by every run below.
#:
#: This is not a convenience. ``run_schedule_mc`` consumes its rng in driver order, so a
#: run with two drivers gives the FIRST driver different draws than a run with one - the
#: arrays come out as the same numbers shifted along. Comparing a two-risk run against a
#: one-risk run without pinning the uniforms compares different random experiments and
#: reads the difference as a CPM effect. The first draft of this test did exactly that and
#: failed, which is how the trap was found. The alignment contract
#: (``cpm_simulation`` module docstring) is that column ``j`` serves
#: ``iter(risk_drivers.keys())[j]``, so each run stacks the columns it needs in its own
#: driver order and every risk sees the same draw in every run - which is how the
#: integrated engine does it too.
_UNIFORMS: dict[str, np.ndarray] = {
    rid: np.random.default_rng(SEED + i).random(N_ITER)
    for i, rid in enumerate(("R-CRIT", "R-FLOAT", "R-REGATED"))
}


@pytest.fixture(scope="module")
def graph():
    return build_schedule_graph(parse_xer(str(FIXTURE)))


def _id_of(graph, code: str) -> str:
    for a in graph.activities.values():
        if a.code == code:
            return a.id
    raise AssertionError(f"{code} not in fixture: {[a.code for a in graph.activities.values()]}")


def _driver(risk_id: str, activity_id: str) -> RiskDriver:
    opt, ml, pess = PERT_DAYS
    return RiskDriver(
        risk_id=risk_id,
        affected_activity_ids=(activity_id,),
        injection_method="discrete_event_additive_days",
        opt_pert=opt, ml_pert=ml, pess_pert=pess,
        probability=1.0,                    # always fires: the assertion is per-iteration
        gating_activity_id=activity_id,
        gating_relation="member",
        derived_at_run_time=False,
        workshop_validated=True,
    )


def _pinned(drivers) -> tuple[np.ndarray, np.ndarray]:
    """Severity uniforms and an all-fire mask, in this run's driver order."""
    sev = np.stack([_UNIFORMS[rid] for rid in drivers], axis=1)
    return sev, np.ones((N_ITER, len(drivers)), dtype=bool)


def _replay_delay_days(graph, drivers) -> np.ndarray:
    """Per-iteration project-finish delay beyond the zero-risk baseline."""
    cfg = ScheduleMCConfig(
        n_iter=N_ITER, batch_size=N_ITER, seed=SEED, precision="float32",
        apply_mode_multipliers=False,        # the production basis, SR15/SR17
        mode_multipliers=MODE_MAP,
    )
    sev, fire = _pinned(drivers)
    result = run_schedule_mc(
        graph=graph, risk_drivers=drivers, config=cfg,
        severity_uniforms=sev, fire_mask=fire,
    )
    hpd = float(graph.project_default_calendar.working_hours_per_day)
    baseline = deterministic_finish_hours(graph, precision="float32") / hpd
    return np.asarray(result.project_finish_days, dtype=float) - baseline


def test_the_fixture_is_the_shape_this_test_depends_on(graph):
    """A fixture that quietly lost its float would make every assertion below vacuous."""
    acts = {a.code: a for a in graph.activities.values()}
    assert set(acts) == {"FA.START", "FA.CRIT", "FA.FLOAT", "FA.END"}
    assert acts["FA.CRIT"].total_float_hours == 0.0
    assert acts["FA.FLOAT"].total_float_hours == 320.0
    hpd = float(graph.project_default_calendar.working_hours_per_day)
    assert max(PERT_DAYS) * hpd < acts["FA.FLOAT"].total_float_hours, (
        "the largest possible delay must fit inside FA.FLOAT's float, or this test "
        "becomes a distributional claim instead of a per-iteration one"
    )


def test_a_delay_on_a_floated_path_never_reaches_the_finish(graph):
    """The commissioned property: replay < additive, by the whole of the floated draw."""
    crit, flt = _id_of(graph, "FA.CRIT"), _id_of(graph, "FA.FLOAT")

    both = _replay_delay_days(graph, {
        "R-CRIT": _driver("R-CRIT", crit), "R-FLOAT": _driver("R-FLOAT", flt)})
    crit_only = _replay_delay_days(graph, {"R-CRIT": _driver("R-CRIT", crit)})
    float_only = _replay_delay_days(graph, {"R-FLOAT": _driver("R-FLOAT", flt)})

    # The floated risk, alone, moves the finish not at all.
    assert np.allclose(float_only, 0.0, atol=1e-3), (
        f"FA.FLOAT carries 320 h of float and the largest draw is "
        f"{max(PERT_DAYS) * 8:.0f} h, so it cannot reach the finish - "
        f"max observed delay {float_only.max():.4f} d")

    # Adding it to the critical risk changes nothing the CPM can see.
    assert np.allclose(both, crit_only, atol=1e-3), (
        f"adding a fully-absorbed risk moved the replay by up to "
        f"{np.abs(both - crit_only).max():.4f} d")

    # But an additive sum counts it in full, so the two bases genuinely diverge.
    drivers_both = {"R-CRIT": _driver("R-CRIT", crit), "R-FLOAT": _driver("R-FLOAT", flt)}
    additive = _injected_days(graph, drivers_both)
    gap = additive - both
    assert gap.min() > 0.0, (
        f"the additive sum must exceed the replay on every iteration - "
        f"smallest gap {gap.min():.4f} d")
    assert gap.mean() > 1.0, (
        f"the demonstration is supposed to be material, not marginal - "
        f"mean gap {gap.mean():.3f} d")
    # And the gap IS the absorbed risk, not some residue: it equals that risk's own draw.
    float_draw = _injected_days(graph, {"R-FLOAT": _driver("R-FLOAT", flt)})
    assert np.allclose(gap, float_draw, atol=1e-2), (
        f"the gap should be exactly the floated risk's draw; worst difference "
        f"{np.abs(gap - float_draw).max():.4f} d")


def _injected_days(graph, drivers) -> np.ndarray:
    """What an additive sum counts: the delays the kernel injected, on the same draws."""
    from src.sra.cpm.risk_injection import sample_risk_deltas
    sev, fire = _pinned(drivers)
    deltas = sample_risk_deltas(
        drivers, graph, N_ITER, np.random.default_rng(SEED),
        severity_uniform=sev, precision="float32",
        mode_multiplier_override=1.0, mode_multipliers=MODE_MAP,
        fire_mask=fire,
    )
    hpd = float(graph.project_default_calendar.working_hours_per_day)
    return np.asarray(deltas, dtype=float).sum(axis=1) / hpd


def test_the_same_delay_on_the_critical_path_is_not_absorbed(graph):
    """The control, and it reproduces CPMINERT-01.

    Re-gate the floated risk onto the critical path - the configuration every driver on
    both shipped projects is in - and the gap collapses to zero. This is what makes the
    positive case above evidence rather than coincidence.
    """
    crit = _id_of(graph, "FA.CRIT")
    one = _replay_delay_days(graph, {"R-CRIT": _driver("R-CRIT", crit)})
    two = _replay_delay_days(graph, {
        "R-CRIT": _driver("R-CRIT", crit), "R-REGATED": _driver("R-REGATED", crit)})

    # Two risks on the critical path add; nothing is absorbed. With the uniforms pinned
    # this is a paired comparison, so it must hold on EVERY iteration, not merely usually.
    assert (two > one).all(), (
        f"a second critical-path risk must extend the finish on every iteration - "
        f"it did not on {int((two <= one).sum())} of {N_ITER}")

    # And it adds in full: the replay equals the additive sum, which is CPMINERT-01.
    additive = _injected_days(graph, {
        "R-CRIT": _driver("R-CRIT", crit), "R-REGATED": _driver("R-REGATED", crit)})
    assert np.allclose(two, additive, atol=1e-2), (
        f"on the critical path the replay IS the additive sum - that is the "
        f"configuration both shipped projects are in (CPMINERT-01); worst difference "
        f"{np.abs(two - additive).max():.4f} d")
