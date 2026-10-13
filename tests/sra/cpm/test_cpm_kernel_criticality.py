"""Synthetic-graph tests for SR-S3-Beta-12 criticality output.

Locks the methodology of the activity-level criticality computation
under five hand-constructible scenarios:

* :func:`test_single_path_always_critical` — linear chain; every
  activity is on the critical path in every iteration regardless of
  risk firing. Asserts ``CI = 1.0`` for all activities.
* :func:`test_two_paths_equal_probability` — two parallel paths with
  symmetric high-variance risks; each path's activities are critical
  ~50% of iterations by symmetry. Asserts ``CI ≈ 0.5`` within an MC
  tolerance band.
* :func:`test_no_path_always_critical_with_high_variance` — three
  parallel paths with independent high-variance risks; the CI
  distribution across activities is flat (no band > 50% of activities).
* :func:`test_total_float_streaming_stats_match_full_array` — exercises
  the kernel's :func:`~src.sra.cpm.cpm_kernel.accumulate_batch_stats`
  helper. Streaming sum / sum-of-squares accumulators must agree with
  the full-array reference computation to 1e-6 (Beta-12 §7 Risk 2).
* :func:`test_deterministic_cp_under_zero_risk` — when every risk has
  ``probability=0.0`` (so no Bernoulli firing) and ``opt = ml = pess``
  (so the PERT additive contribution is zero even in the rare numeric
  edge case), every iteration runs against the base durations and the
  deterministic_critical_path returned on the result matches the
  zero-risk forward+backward pass run independently.

All tests construct ``ScheduleGraph`` and ``RiskDriver`` directly — no
file references. The kernel is project-agnostic; the synthetic-graph
tests are the methodology-locking gate for Beta-12 §6 acceptance
criterion 1.
"""

from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import numpy as np
import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.cpm_kernel import (
    CRITICAL_PATH_TOL,
    accumulate_batch_stats,
    run_batch,
)
from src.sra.cpm.cpm_simulation import (
    ScheduleMCConfig,
    run_schedule_mc,
)
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from src.sra.cpm.risk_driver_schema import RiskDriver


# ---------------------------------------------------------------------------
# Synthetic-graph helpers (mirror tests/sra/cpm/test_cpm_simulation.py)
# ---------------------------------------------------------------------------

_DEFAULT_CAL = Calendar()  # 8 working hours per day


def _activity(aid: str, *, duration_hours: float = 80.0) -> Activity:
    return Activity(
        id=aid,
        code=aid,
        name=aid,
        task_type="TT_Task",
        original_duration_hours=duration_hours,
        total_float_hours=None,
        calendar_id=None,
    )


def _make_graph(
    activities: list[Activity],
    links: list[Link],
    *,
    topo_order: list[str] | None = None,
) -> ScheduleGraph:
    acts = {a.id: a for a in activities}
    for link in links:
        if link.pred_id in acts:
            acts[link.pred_id].successor_links.append(link)
        if link.succ_id in acts:
            acts[link.succ_id].predecessor_links.append(link)
    return ScheduleGraph(
        activities=acts,
        links=list(links),
        topo_order=topo_order if topo_order is not None else [a.id for a in activities],
        project_default_calendar=_DEFAULT_CAL,
    )


def _driver(
    risk_id: str,
    *,
    affected: tuple[str, ...],
    opt: float = 0.0,
    ml: float = 0.0,
    pess: float = 0.0,
    probability: float = 0.0,
) -> RiskDriver:
    return RiskDriver(
        risk_id=risk_id,
        affected_activity_ids=affected,
        injection_method="additive_pert_days",
        opt_pert=opt,
        ml_pert=ml,
        pess_pert=pess,
        probability=probability,
        derived_at_run_time=False,
        workshop_validated=True,
    )


# ---------------------------------------------------------------------------
# Test 1 — Single path always critical → CI = 1.0
# ---------------------------------------------------------------------------

def test_single_path_always_critical() -> None:
    """5-activity linear chain a1→a2→a3→a4→a5; one path exists, so every
    activity is on the critical path in every iteration. CI = 1.0 for
    every activity regardless of risk firing.
    """
    acts = [_activity(f"a{i}", duration_hours=80.0) for i in range(1, 6)]
    links = [
        Link(pred_id=f"a{i}", succ_id=f"a{i + 1}", link_type="FS", lag_hours=0.0)
        for i in range(1, 5)
    ]
    graph = _make_graph(acts, links)

    # A risk that fires every iteration with non-trivial PERT magnitude
    # — to confirm CI = 1.0 holds even when activity durations are
    # being perturbed (not a no-op test).
    drivers = {
        "R001": _driver(
            risk_id="R001",
            affected=("a1", "a3", "a5"),
            opt=1.0, ml=2.0, pess=4.0,
            probability=1.0,
        ),
    }
    cfg = ScheduleMCConfig(n_iter=200, batch_size=50, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
    result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)

    for a_id in ("a1", "a2", "a3", "a4", "a5"):
        assert result.criticality_index[a_id] == pytest.approx(1.0), (
            f"{a_id} CI = {result.criticality_index[a_id]} but linear chain "
            f"means every activity must be critical in every iteration"
        )

    # Deterministic CP under zero risk = entire chain.
    assert set(result.deterministic_critical_path) == {
        "a1", "a2", "a3", "a4", "a5"
    }


# ---------------------------------------------------------------------------
# Test 2 — Two parallel paths with symmetric risks → CI ≈ 0.5
# ---------------------------------------------------------------------------

def test_two_paths_equal_probability() -> None:
    """Two parallel paths from `start` to `end`, equal nominal durations,
    independent symmetric high-variance risks on each path. By symmetry,
    each path's activities are critical in ~50% of iterations.

    Tolerance band: ±0.10 (i.e. CI ∈ [0.40, 0.60]) at 5,000 iterations.
    Wide enough to absorb MC noise without masking a real asymmetry.
    """
    # start (zero-duration) → p1a → p1b → end (zero-duration)
    # start (zero-duration) → p2a → p2b → end (zero-duration)
    acts = [
        _activity("start", duration_hours=0.0),
        _activity("p1a", duration_hours=80.0),
        _activity("p1b", duration_hours=80.0),
        _activity("p2a", duration_hours=80.0),
        _activity("p2b", duration_hours=80.0),
        _activity("end", duration_hours=0.0),
    ]
    links = [
        Link(pred_id="start", succ_id="p1a", link_type="FS", lag_hours=0.0),
        Link(pred_id="p1a", succ_id="p1b", link_type="FS", lag_hours=0.0),
        Link(pred_id="p1b", succ_id="end", link_type="FS", lag_hours=0.0),
        Link(pred_id="start", succ_id="p2a", link_type="FS", lag_hours=0.0),
        Link(pred_id="p2a", succ_id="p2b", link_type="FS", lag_hours=0.0),
        Link(pred_id="p2b", succ_id="end", link_type="FS", lag_hours=0.0),
    ]
    graph = _make_graph(
        acts, links,
        topo_order=["start", "p1a", "p1b", "p2a", "p2b", "end"],
    )

    # Symmetric high-variance risks on each path. probability=1.0 so
    # the risks fire on every iteration; the only randomness is the
    # PERT severity sample, which is independent across the two risks.
    drivers = {
        "R_path1": _driver(
            risk_id="R_path1",
            affected=("p1a", "p1b"),
            opt=0.0, ml=5.0, pess=20.0,
            probability=1.0,
        ),
        "R_path2": _driver(
            risk_id="R_path2",
            affected=("p2a", "p2b"),
            opt=0.0, ml=5.0, pess=20.0,
            probability=1.0,
        ),
    }
    cfg = ScheduleMCConfig(n_iter=5000, batch_size=1000, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
    result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)

    # Each path's activities should be critical ~50% of the time.
    for a_id in ("p1a", "p1b", "p2a", "p2b"):
        assert 0.40 <= result.criticality_index[a_id] <= 0.60, (
            f"{a_id} CI = {result.criticality_index[a_id]:.3f} outside "
            f"[0.40, 0.60] — symmetry violated or MC tolerance too tight"
        )

    # Sum of CI across the two p1 activities ≈ 1.0 + sum across p2 ≈ 1.0
    # holds when the path-crossover events are mutually exclusive
    # (one path strictly longer than the other in every iteration).
    p1_ci = (
        result.criticality_index["p1a"] + result.criticality_index["p1b"]
    )
    p2_ci = (
        result.criticality_index["p2a"] + result.criticality_index["p2b"]
    )
    assert p1_ci == pytest.approx(p2_ci, abs=0.10)

    # start and end have slack=0 by definition (zero-duration sinks).
    assert result.criticality_index["start"] == pytest.approx(1.0)
    assert result.criticality_index["end"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Test 3 — Three parallel paths with high variance → flat CI distribution
# ---------------------------------------------------------------------------

def test_no_path_always_critical_with_high_variance() -> None:
    """Three parallel paths with independent high-variance PERT risks.
    No single path always wins; no path-activity reaches the always-90%+
    band; no path-activity sits in the never-<10% band. The path
    activities sit in the shifty middle bands (rarely / near / often)
    rather than at either extreme.

    This is the "shifty critical path" pattern — exactly the case where
    the deterministic critical path under-reports schedule risk because
    contingency is doing more work than the deterministic chain alone
    suggests. Beta-12 §3.3 distribution-shape classifier.
    """
    acts = [_activity("start", duration_hours=0.0)]
    for path_idx in (1, 2, 3):
        for step in ("a", "b"):
            acts.append(_activity(f"p{path_idx}{step}", duration_hours=80.0))
    acts.append(_activity("end", duration_hours=0.0))

    links: list[Link] = []
    topo_order = ["start"]
    for path_idx in (1, 2, 3):
        a, b = f"p{path_idx}a", f"p{path_idx}b"
        links.append(Link(pred_id="start", succ_id=a, link_type="FS", lag_hours=0.0))
        links.append(Link(pred_id=a, succ_id=b, link_type="FS", lag_hours=0.0))
        links.append(Link(pred_id=b, succ_id="end", link_type="FS", lag_hours=0.0))
        topo_order.extend([a, b])
    topo_order.append("end")

    graph = _make_graph(acts, links, topo_order=topo_order)

    drivers = {
        f"R_path{idx}": _driver(
            risk_id=f"R_path{idx}",
            affected=(f"p{idx}a", f"p{idx}b"),
            opt=0.0, ml=5.0, pess=20.0,
            probability=1.0,
        )
        for idx in (1, 2, 3)
    }
    cfg = ScheduleMCConfig(n_iter=3000, batch_size=1000, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
    result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)

    # No path-activity reaches the always (90%+) band — three paths
    # share criticality, so no single path dominates.
    path_activity_ids = [
        f"p{idx}{step}" for idx in (1, 2, 3) for step in ("a", "b")
    ]
    for a_id in path_activity_ids:
        ci = result.criticality_index[a_id]
        assert ci < 0.90, (
            f"{a_id} CI = {ci:.3f} reached the always-90%+ band; "
            f"three balanced paths should not produce a single dominant chain"
        )
        assert ci > 0.10, (
            f"{a_id} CI = {ci:.3f} sits in the never-<10% band; "
            f"three balanced paths means every path is plausibly critical"
        )

    # By symmetry, the per-path mean CI should be roughly 1/3.
    p1_mean = (
        result.criticality_index["p1a"] + result.criticality_index["p1b"]
    ) / 2.0
    p2_mean = (
        result.criticality_index["p2a"] + result.criticality_index["p2b"]
    ) / 2.0
    p3_mean = (
        result.criticality_index["p3a"] + result.criticality_index["p3b"]
    ) / 2.0
    for path_idx, mean_ci in enumerate((p1_mean, p2_mean, p3_mean), start=1):
        assert 0.20 <= mean_ci <= 0.50, (
            f"path {path_idx} mean CI = {mean_ci:.3f} outside [0.20, 0.50]; "
            f"three symmetric paths should produce ~1/3 each within MC tolerance"
        )

    # Sum of per-path mean CIs across the three paths ≈ 1.0
    # (path-criticality is mutually exclusive with high-variance risks).
    assert (p1_mean + p2_mean + p3_mean) == pytest.approx(1.0, abs=0.05)


# ---------------------------------------------------------------------------
# Test 4 — Streaming float stats match full-array reference (1e-6)
# ---------------------------------------------------------------------------

def test_total_float_streaming_stats_match_full_array() -> None:
    """The kernel's accumulate_batch_stats helper must produce the same
    per-activity sum / sum-of-squares as a full-array reference.

    Constructs a small synthetic 4-activity graph with a known duration
    matrix, runs the kernel once for the full set of iterations, then
    reduces both:

      reference:  slack.sum(axis=0)                  (full array)
      streaming:  sum across batches of slack[batch].sum(axis=0)

    Asserts agreement to absolute tolerance 1e-6 in float64 — equivalent
    to "no drift from naive associativity". The orchestrator's
    `_run_one_batch` routes through `accumulate_batch_stats` (commit 5a
    consolidation per code-review Finding 1), so this precision check
    covers the production path. The catastrophic-cancellation edge case
    (very large mean, tiny std) is mitigated by the float64 promotion
    inside `accumulate_batch_stats`; it is not separately exercised
    here, since constant-float synthetic graphs do not produce that
    scenario and the high-variance graph in `test_two_paths_equal_probability`
    holds the float-mean low.
    """
    acts = [_activity(f"a{i}", duration_hours=80.0) for i in range(1, 5)]
    links = [
        Link(pred_id=f"a{i}", succ_id=f"a{i + 1}", link_type="FS", lag_hours=0.0)
        for i in range(1, 4)
    ]
    graph = _make_graph(acts, links)

    rng = np.random.default_rng(seed=42)
    n_iter = 1000
    n_act = 4
    # Random per-iteration durations across all four activities. Wide
    # band so slack varies materially and the variance test is
    # informative (a constant slack would trivially pass).
    durations = rng.uniform(40.0, 120.0, size=(n_iter, n_act)).astype(np.float64)

    # Full-batch kernel run.
    full_out = run_batch(
        durations=durations,
        graph=graph,
        calendar=_DEFAULT_CAL,
        precision="float64",
    )
    slack_full = full_out["slack"]  # shape (n_iter, n_act), float64

    # Reference reductions.
    ref_sum = slack_full.sum(axis=0)
    ref_sum_sq = np.square(slack_full).sum(axis=0)
    ref_cp_count = full_out["on_critical_path"].sum(axis=0).astype(np.int64)

    # Streaming reductions via the kernel helper, called over chunks.
    ci_counts = np.zeros(n_act, dtype=np.int64)
    tf_sum = np.zeros(n_act, dtype=np.float64)
    tf_sum_sq = np.zeros(n_act, dtype=np.float64)
    chunk = 137  # deliberately not a divisor of n_iter
    for start in range(0, n_iter, chunk):
        end = min(start + chunk, n_iter)
        chunk_out = run_batch(
            durations=durations[start:end, :],
            graph=graph,
            calendar=_DEFAULT_CAL,
            precision="float64",
        )
        accumulate_batch_stats(
            chunk_out,
            ci_counts=ci_counts,
            total_float_sum=tf_sum,
            total_float_sum_sq=tf_sum_sq,
        )

    np.testing.assert_allclose(tf_sum, ref_sum, atol=1e-6)
    np.testing.assert_allclose(tf_sum_sq, ref_sum_sq, atol=1e-6)
    np.testing.assert_array_equal(ci_counts, ref_cp_count)

    # Mean / std reconstruction matches the reference too. The orchestrator
    # uses this exact computation; confirming it here closes the loop.
    n = float(n_iter)
    mean = tf_sum / n
    var = np.maximum(0.0, tf_sum_sq / n - np.square(mean))
    std = np.sqrt(var)
    np.testing.assert_allclose(mean, slack_full.mean(axis=0), atol=1e-6)
    np.testing.assert_allclose(std, slack_full.std(axis=0), atol=1e-6)


# ---------------------------------------------------------------------------
# Test 5 — Deterministic CP under zero risk
# ---------------------------------------------------------------------------

def test_deterministic_cp_under_zero_risk() -> None:
    """When every risk has probability=0.0 and PERT params opt=ml=pess=0,
    no risk fires and the kernel runs every iteration on the base
    durations. The deterministic_critical_path field must equal the
    activities flagged on the critical path under a single zero-risk
    forward+backward pass on base_durations.

    Setup: a diamond graph where the longer branch is the critical path:

         start (0h)
         /        \\
       short(40h) long(80h)
         \\        /
            end (0h)

    Critical path: start → long → end. Activity `short` has slack 40h.
    """
    acts = [
        _activity("start", duration_hours=0.0),
        _activity("short", duration_hours=40.0),
        _activity("long", duration_hours=80.0),
        _activity("end", duration_hours=0.0),
    ]
    links = [
        Link(pred_id="start", succ_id="short", link_type="FS", lag_hours=0.0),
        Link(pred_id="start", succ_id="long", link_type="FS", lag_hours=0.0),
        Link(pred_id="short", succ_id="end", link_type="FS", lag_hours=0.0),
        Link(pred_id="long", succ_id="end", link_type="FS", lag_hours=0.0),
    ]
    graph = _make_graph(
        acts, links, topo_order=["start", "short", "long", "end"],
    )

    # All risks frozen — probability=0 means Bernoulli never fires;
    # opt=ml=pess=0 means even if the PERT severity were sampled the
    # additive contribution would be zero. Safer than relying on the
    # Bernoulli alone in case of future engine-side changes.
    drivers = {
        "R001": _driver(
            risk_id="R001",
            affected=("short",),
            opt=0.0, ml=0.0, pess=0.0,
            probability=0.0,
        ),
    }
    cfg = ScheduleMCConfig(n_iter=500, batch_size=100, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
    result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)

    # Deterministic CP is `long` chain.
    assert set(result.deterministic_critical_path) == {"start", "long", "end"}
    assert "short" not in result.deterministic_critical_path

    # And under zero-firing risks, the same set is critical in every
    # iteration. CI = 1.0 for the deterministic CP set, < 1.0 for short.
    for a_id in ("start", "long", "end"):
        assert result.criticality_index[a_id] == pytest.approx(1.0)
    assert result.criticality_index["short"] == pytest.approx(0.0)

    # Cross-check the deterministic CP against an independent run_batch
    # call on base_durations alone. This is the methodology-locking
    # cross-check: the orchestrator and a manual zero-risk pass agree.
    base_durations = np.array(
        [a.original_duration_hours for a in acts], dtype=np.float32
    )
    det_out = run_batch(
        durations=base_durations[None, :],
        graph=graph,
        calendar=_DEFAULT_CAL,
        precision="float32",
    )
    det_cp_mask = det_out["on_critical_path"][0]
    expected_det_cp = {
        a.id for a, on_cp in zip(acts, det_cp_mask) if bool(on_cp)
    }
    assert set(result.deterministic_critical_path) == expected_det_cp


# ---------------------------------------------------------------------------
# Bonus — total_float_mean / total_float_std are populated and finite
# ---------------------------------------------------------------------------

def test_total_float_arrays_populated_and_finite() -> None:
    """Smoke test confirming the two new ScheduleMCResult fields are
    populated with arrays of the correct shape and contain only finite
    values for a typical run. Variance floor (Beta-12 §3.1 commit 4
    note) suppresses tiny negatives in the constant-float case.
    """
    acts = [_activity(f"a{i}", duration_hours=80.0) for i in range(1, 6)]
    links = [
        Link(pred_id=f"a{i}", succ_id=f"a{i + 1}", link_type="FS", lag_hours=0.0)
        for i in range(1, 5)
    ]
    graph = _make_graph(acts, links)
    drivers = {
        "R001": _driver(
            risk_id="R001",
            affected=("a1",),
            opt=1.0, ml=2.0, pess=4.0,
            probability=0.5,
        ),
    }
    cfg = ScheduleMCConfig(n_iter=500, batch_size=100, seed=42, mode_multipliers=TEST_MODE_MULTIPLIERS)
    result = run_schedule_mc(graph=graph, risk_drivers=drivers, config=cfg)

    assert result.total_float_mean_hours.shape == (5,)
    assert result.total_float_std_hours.shape == (5,)
    assert np.all(np.isfinite(result.total_float_mean_hours))
    assert np.all(np.isfinite(result.total_float_std_hours))
    # Std ≥ 0 by construction.
    assert np.all(result.total_float_std_hours >= 0.0)
    # On a linear chain every activity's slack is 0 in every iteration
    # (every activity is on the critical path), so the float mean
    # should be at the CRITICAL_PATH_TOL or below for all.
    assert np.all(result.total_float_mean_hours <= CRITICAL_PATH_TOL + 1.0)
