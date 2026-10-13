"""The shipped projects' CPM replay is still arithmetically identical to an additive sum.

SHOWCASE-02 S-3 / ledger **CPMINERT-01**. The brief's §2.6 reports a measured zero at
100,000 iterations on both shipped projects. This is what makes that number a result
something re-derives rather than a figure quoted in a document.

WHY THIS TEST WANTS TO FAIL ONE DAY
    It asserts a finding, not a requirement. CPMINERT-01's owed work includes binding a
    risk where the float actually is (D-1 option (d), deliberately deferred out of
    SHOWCASE-02). The day someone does that, this test goes **red** - correctly. Its
    failure message says so, so that whoever sees it updates CPMINERT-01 and §2.6 rather
    than "fixing" the test. A finding with no guard quietly stops being true; a finding
    with a guard announces when it does.

WHY `slow`
    It runs the Stage 3 engine against the real registers, schedules and strawmen, which
    is the slow class `pytest.ini` names. The mechanism it depends on is covered in the fast
    lane by `tests/sra/cpm/test_float_absorption.py`, which proves on a purpose-built
    fixture that a delay at a zero-float gate reaches the finish undiminished while the
    same delay behind float does not. So the cheap check runs every stage and this one runs
    at the increment.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.measure_replay_vs_additive import SHIPPED, measure  # noqa: E402

#: Enough to exercise every driver many times over; the finding is per-iteration and
#: structural, so it does not need iteration count to show itself. §2.6's headline numbers
#: come from the script at 100,000.
N_ITER = 1_000
#: The seed §2.6's measurement was taken at; the script has no default (SEEDZERO-01).
SEED = 42


@pytest.fixture(scope="module", params=SHIPPED)
def measured(request):
    return measure(request.param, N_ITER, SEED)


@pytest.mark.slow
def test_the_measurement_is_internally_valid(measured):
    """additive >= replay per iteration, or the reproduction is wrong and nothing below
    means anything. A delay can extend a finish by at most its own magnitude."""
    assert measured["violations"] == 0, (
        f"{measured['project']}: additive < replay on {measured['violations']} iterations "
        f"(worst {measured['worst_violation']:.4f} d) - the additive side is not being "
        f"reproduced on the replay's basis, so no gap it reports can be trusted")


@pytest.mark.slow
def test_every_driver_still_gates_on_a_zero_float_activity(measured):
    """The cause, asserted directly - and the thing most likely to change first."""
    assert measured["n_gates_zero_float"] == measured["n_drivers"], (
        f"{measured['project']}: {measured['n_drivers'] - measured['n_gates_zero_float']} "
        f"of {measured['n_drivers']} drivers now gate on an activity WITH float. That is "
        f"CPMINERT-01's owed work happening - update the row and the SHOWCASE-02 brief's "
        f"§2.6, do not relax this assertion")


@pytest.mark.slow
def test_the_replay_is_still_the_additive_sum(measured):
    """CPMINERT-01 itself: zero gap, on every iteration, on both shipped projects."""
    absorbed = measured["additive"] - measured["replay"]
    worst = float(np.abs(absorbed).max())
    assert worst <= 0.01, (
        f"{measured['project']}: the CPM network now absorbs up to {worst:.3f} days, so "
        f"the replay is no longer arithmetically identical to an additive sum. If that is "
        f"deliberate, CPMINERT-01 is closing and the brief's §2.6 needs re-measuring")


@pytest.mark.slow
def test_the_mode_scaled_sum_is_a_different_basis_and_not_the_comparator(measured):
    """The trap the script exists to avoid, asserted so it cannot creep back.

    ``per_risk_schedule_array.sum(axis=1)`` is Mode-scaled and is NOT the additive
    comparator. Both shipped projects are mixed-Mode, so it sits materially below the
    replay - and a future edit that quietly swapped it in as the comparator would report a
    large negative "gap" and read as a CPM effect. That is the shape STAGE3HEADLINE-01
    shipped once (CPMATTRIB-01).
    """
    mode_scaled_p80 = float(np.percentile(measured["mode_scaled"], 80))
    replay_p80 = float(np.percentile(measured["replay"], 80))
    assert mode_scaled_p80 < replay_p80 * 0.95, (
        f"{measured['project']}: the Mode-scaled sum ({mode_scaled_p80:.2f} d) is supposed "
        f"to sit well below the unscaled replay ({replay_p80:.2f} d) because Parallel "
        f"risks are zeroed and Hybrid halved. If these have converged, the Mode "
        f"classifications or the basis have changed and this measurement needs rereading")
