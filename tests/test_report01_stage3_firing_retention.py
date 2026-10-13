"""REPORT01 F-B: the Stage 3 arms retain their firing record.

GAP01 F-B: nothing in the report shows the simulation did what the register asked. The
brief's first draft said both arms already retained a firing matrix; verification found
that true of the Stage 2.5 comparator and the standalone schedule MC, and **false of the
headline**. Stage 3's cost arm had one that the composer adapter dropped, and its
schedule arm - the CPM replay - computed `fires` in `sample_risk_deltas` and discarded
it.

Director 12/09/2026: retain on both Stage 3 arms, prove bit-identical.

Two Bernoullis, not one. The Stage 3 cost arm fires on the register's `Probability`, the
schedule arm on `Probability (Time)`; they share severity uniforms, not fire draws. Every
fixture here therefore gives the two arms **different** probabilities, because a fixture
where they agree cannot tell a correct implementation from one reading a single column
for both.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.cpm_simulation import ScheduleMCConfig, run_schedule_mc
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from src.sra.cpm.risk_driver_schema import RiskDriver
from src.sra.cpm.risk_injection import sample_risk_deltas
from tests.conftest import TEST_MODE_MULTIPLIERS

_CAL = Calendar()  # 8 working hours per day


def _graph(n_act: int = 3) -> ScheduleGraph:
    acts = [
        Activity(id=f"a{i}", code=f"a{i}", name=f"a{i}", task_type="TT_Task",
                 original_duration_hours=80.0, total_float_hours=0.0, calendar_id=None)
        for i in range(1, n_act + 1)
    ]
    links = [
        Link(pred_id=f"a{i}", succ_id=f"a{i+1}", link_type="FS", lag_hours=0.0)
        for i in range(1, n_act)
    ]
    return ScheduleGraph(
        activities={a.id: a for a in acts}, links=links,
        topo_order=[a.id for a in acts], project_default_calendar=_CAL,
    )


def _driver(rid: str, probability: float, affected=("a1",)) -> RiskDriver:
    return RiskDriver(
        risk_id=rid, affected_activity_ids=affected,
        injection_method="additive_pert_days",  # type: ignore[arg-type]
        opt_pert=1.0, ml_pert=2.0, pess_pert=4.0, probability=probability,
        derived_at_run_time=True, workshop_validated=False,
    )


#: Deliberately distinct probabilities, so a mask read off the wrong driver is visible.
_PROBS = {"R001": 0.25, "R002": 0.60, "R003": 0.90}


def _drivers() -> dict[str, RiskDriver]:
    return {rid: _driver(rid, p) for rid, p in _PROBS.items()}


# ---------------------------------------------------------------------------
# sample_risk_deltas: the capture itself
# ---------------------------------------------------------------------------

def test_fires_out_is_populated_one_mask_per_driver():
    fires: dict[str, np.ndarray] = {}
    sample_risk_deltas(
        _drivers(), _graph(), n_iter=500, rng=np.random.default_rng(1),
        mode_multipliers=TEST_MODE_MULTIPLIERS, fires_out=fires,
    )
    assert set(fires) == set(_PROBS)
    for rid, mask in fires.items():
        assert mask.shape == (500,), rid
        assert mask.dtype == np.bool_, rid


def test_the_mask_matches_where_the_deltas_actually_landed():
    """The mask must describe the run it came from, not merely look plausible.

    A mask generated from a second, independent draw would have the right shape and
    roughly the right rate and be entirely wrong. Every iteration where a lone driver
    contributed a non-zero delta must be an iteration its mask calls fired.
    """
    fires: dict[str, np.ndarray] = {}
    drivers = {"R002": _driver("R002", 0.6)}
    deltas = sample_risk_deltas(
        drivers, _graph(), n_iter=2_000, rng=np.random.default_rng(7),
        mode_multipliers=TEST_MODE_MULTIPLIERS, fires_out=fires,
    )
    nonzero = deltas[:, 0] != 0
    assert nonzero.any(), "fixture produced no deltas at all"
    np.testing.assert_array_equal(nonzero, fires["R002"])


def test_asking_for_the_mask_does_not_change_the_deltas():
    """Bit-identity at the smallest scale: the capture is read-only."""
    kw = dict(mode_multipliers=TEST_MODE_MULTIPLIERS)
    without = sample_risk_deltas(
        _drivers(), _graph(), n_iter=1_000, rng=np.random.default_rng(42), **kw)
    with_capture = sample_risk_deltas(
        _drivers(), _graph(), n_iter=1_000, rng=np.random.default_rng(42),
        fires_out={}, **kw)
    assert without.tobytes() == with_capture.tobytes()


def test_each_driver_gets_its_own_probability_not_a_shared_one():
    """The three fixture probabilities are far apart; a shared draw would collapse them."""
    fires: dict[str, np.ndarray] = {}
    sample_risk_deltas(
        _drivers(), _graph(), n_iter=40_000, rng=np.random.default_rng(3),
        mode_multipliers=TEST_MODE_MULTIPLIERS, fires_out=fires,
    )
    for rid, p in _PROBS.items():
        realised = fires[rid].mean()
        # 4 sigma on a binomial proportion at n=40k is under 0.01 for any p.
        assert abs(realised - p) < 0.01, f"{rid}: elicited {p}, realised {realised}"


def test_a_driver_that_reaches_no_activity_still_reports_its_firing():
    """Zero-expansion drivers are in the register and must be in the record.

    The engine draws their Bernoulli anyway (to keep the rng stream stable across graph
    revisions). Omitting them would make a rule that expanded to nothing indistinguishable
    from one that never fired.
    """
    fires: dict[str, np.ndarray] = {}
    drivers = {"R001": _driver("R001", 0.5, affected=()),
               "R002": _driver("R002", 0.5, affected=("a1",))}
    sample_risk_deltas(
        drivers, _graph(), n_iter=1_000, rng=np.random.default_rng(11),
        mode_multipliers=TEST_MODE_MULTIPLIERS, fires_out=fires,
    )
    assert set(fires) == {"R001", "R002"}
    assert fires["R001"].any(), "the zero-expansion driver reported no firing at all"


# ---------------------------------------------------------------------------
# run_schedule_mc: the run-level array, stitched across batches
# ---------------------------------------------------------------------------

def _run(n_iter: int, batch_size: int):
    return run_schedule_mc(
        graph=_graph(), risk_drivers=_drivers(),
        config=ScheduleMCConfig(
            n_iter=n_iter, batch_size=batch_size, seed=42, precision="float64",
            mode_multipliers=TEST_MODE_MULTIPLIERS),
    )


def test_result_carries_a_run_level_firing_array_aligned_to_risk_ids():
    res = _run(600, 600)
    assert res.risk_fired_array.shape == (600, len(_PROBS))
    assert res.risk_fired_array.dtype == np.bool_
    for i, rid in enumerate(res.risk_ids):
        realised = res.risk_fired_array[:, i].mean()
        nearest = min(_PROBS, key=lambda k: abs(_PROBS[k] - realised))
        assert nearest == rid, (
            f"column {i} is labelled {rid} (p={_PROBS[rid]}) but fired at {realised:.3f}, "
            f"which matches {nearest} - the columns are misaligned with risk_ids")


@pytest.mark.parametrize("batch_size", [100, 250, 700, 3_000])
def test_every_batch_writes_its_slice_of_the_firing_record(batch_size):
    """The mask is stitched from per-batch pieces; no slice may go unwritten.

    NOT an equality check across batch sizes. The engine spawns one sub-generator per
    batch, so batch size legitimately changes every number the run produces - measured
    12/09/2026: at n=700 the mean project finish moves 111.40 / 110.96 / 110.08 hours
    across batch sizes of 700 / 250 / 100, and that predates this change. What must hold
    for any batch size is that the record is complete and describes its own run.

    An off-by-one in the slice assignment leaves a band of False that a whole-column
    rate check would barely register, so both limbs below look for the band directly.
    """
    n_iter = 3_000
    res = _run(n_iter, batch_size)
    arr = res.risk_fired_array
    assert arr.shape == (n_iter, len(_PROBS))

    for i, rid in enumerate(res.risk_ids):
        col = arr[:, i]
        realised = col.mean()
        # 5 sigma on a binomial proportion at n=3,000 is under 0.05 for any p; a batch
        # that never wrote would drag a p=0.9 column far outside this.
        assert abs(realised - _PROBS[rid]) < 0.05, (
            f"batch_size={batch_size}, {rid}: elicited {_PROBS[rid]}, "
            f"realised {realised:.4f} - a batch may not have written its slice")

    # The p=0.9 driver: the longest run of consecutive non-fires must be far shorter
    # than one batch. An unwritten batch shows up here as a gap of exactly batch length.
    col = arr[:, list(res.risk_ids).index("R003")]
    longest, run = 0, 0
    for v in col:
        run = 0 if v else run + 1
        longest = max(longest, run)
    assert longest < min(batch_size, n_iter), (
        f"batch_size={batch_size}: a {longest}-iteration gap at p=0.9 is a batch "
        f"that never wrote its mask")
