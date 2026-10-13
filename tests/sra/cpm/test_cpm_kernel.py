"""Tests for src.sra.cpm.cpm_kernel (SR-S3-Beta-03).

Four focused test classes:

* :class:`TestForwardPass` — focused tests for the forward pass.
* :class:`TestBackwardPass` — focused tests for the backward pass.
* :class:`TestSlackAndCriticalPath` — slack arithmetic + tolerance.
* :class:`TestRunBatch` — convenience-wrapper contract (keys, dtypes,
  precision plumbing, calendar fallback, shape validation).

The Validation Gate 1 hand-worked test class previously lived here as
``TestValidationGate1``; SR-S3-Beta-07 promoted it into its own file
at :mod:`tests.sra.cpm.test_kernel_handworked` per Build Plan §6
acceptance criterion 1.

All tests construct ``ScheduleGraph`` and ``Calendar`` instances
directly — no RefProject file references. The kernel is project-agnostic
and the synthetic-graph tests are the reusability gate per Beta-00.3.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.cpm_kernel import (
    CRITICAL_PATH_TOL,
    backward_pass,
    compute_slack,
    forward_pass,
    run_batch,
)
from src.sra.cpm.graph import Activity, Link, ScheduleGraph

# ---------------------------------------------------------------------------
# Helpers — synthetic ScheduleGraph builders for tests
# ---------------------------------------------------------------------------

_DEFAULT_CALENDAR = Calendar()


def _make_graph(
    activity_durations: dict[str, float],
    links: list[tuple[str, str, str, float]],
    *,
    topo_order: list[str] | None = None,
    calendar: Calendar | None = None,
) -> ScheduleGraph:
    """Build a synthetic ScheduleGraph for tests.

    Parameters
    ----------
    activity_durations : dict[str, float]
        Activity id → duration in working hours.
    links : list[tuple[str, str, str, float]]
        ``(pred_id, succ_id, link_type, lag_hours)`` tuples.
    topo_order : list[str] | None
        If ``None``, uses ``activity_durations.keys()`` insertion
        order. Tests that rely on a specific column ordering should
        pass it explicitly.
    """
    if topo_order is None:
        topo_order = list(activity_durations.keys())

    activities: dict[str, Activity] = {
        aid: Activity(
            id=aid,
            code=aid,
            name=aid,
            task_type="TT_Task",
            original_duration_hours=dur,
            total_float_hours=None,
            calendar_id=None,
        )
        for aid, dur in activity_durations.items()
    }

    link_objs: list[Link] = []
    for pred_id, succ_id, link_type, lag in links:
        link = Link(
            pred_id=pred_id,
            succ_id=succ_id,
            link_type=link_type,  # type: ignore[arg-type]
            lag_hours=lag,
        )
        link_objs.append(link)
        activities[pred_id].successor_links.append(link)
        activities[succ_id].predecessor_links.append(link)

    return ScheduleGraph(
        activities=activities,
        links=link_objs,
        topo_order=list(topo_order),
        project_default_calendar=calendar or _DEFAULT_CALENDAR,
    )


def _durations_array(
    graph: ScheduleGraph,
    per_activity_dur: dict[str, float],
    *,
    batch_n: int = 1,
    dtype: np.dtype = np.float64,
) -> np.ndarray:
    """Build a ``(batch_n, n_act)`` durations array aligned to topo order."""
    cols = [per_activity_dur[aid] for aid in graph.topo_order]
    return np.tile(np.array(cols, dtype=dtype), (batch_n, 1))


# TestValidationGate1 moved to test_kernel_handworked.py at Beta-07.


# ---------------------------------------------------------------------------
# Forward pass
# ---------------------------------------------------------------------------

class TestForwardPass:
    """Direct, focused tests on forward_pass (one concern per test)."""

    def test_forward_single_activity(self) -> None:
        graph = _make_graph({"A": 8.0}, [])
        durations = _durations_array(graph, {"A": 8.0})
        ES, EF = forward_pass(durations, graph, _DEFAULT_CALENDAR, precision="float64")
        assert ES[0, 0] == 0.0
        assert EF[0, 0] == 8.0

    def test_forward_simple_chain_FS(self) -> None:
        graph = _make_graph(
            {"A": 8.0, "B": 12.0, "C": 16.0},
            [("A", "B", "FS", 0.0), ("B", "C", "FS", 0.0)],
        )
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0, "C": 16.0})
        ES, EF = forward_pass(durations, graph, _DEFAULT_CALENDAR, precision="float64")
        assert list(ES[0]) == [0.0, 8.0, 20.0]
        assert list(EF[0]) == [8.0, 20.0, 36.0]

    def test_forward_FS_with_positive_lag(self) -> None:
        graph = _make_graph(
            {"A": 8.0, "B": 12.0}, [("A", "B", "FS", 4.0)]
        )
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0})
        ES, EF = forward_pass(durations, graph, _DEFAULT_CALENDAR, precision="float64")
        # ES[B] = EF[A] + 4 = 12; EF[B] = 24.
        assert ES[0, 1] == 12.0
        assert EF[0, 1] == 24.0

    def test_forward_FS_with_negative_lag_floors_at_project_start(self) -> None:
        """A lead would push ES negative; project_start floor pulls it back to 0."""
        graph = _make_graph(
            {"A": 8.0, "B": 12.0}, [("A", "B", "FS", -16.0)]
        )
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0})
        ES, EF = forward_pass(durations, graph, _DEFAULT_CALENDAR, precision="float64")
        # Without the floor: ES[B] = 8 - 16 = -8. With floor: 0.
        assert ES[0, 1] == 0.0
        assert EF[0, 1] == 12.0

    def test_forward_FS_with_negative_lag_meaningful_lead(self) -> None:
        """Lead of -4h on a longer chain leaves ES strictly positive."""
        graph = _make_graph(
            {"A": 16.0, "B": 12.0}, [("A", "B", "FS", -4.0)]
        )
        durations = _durations_array(graph, {"A": 16.0, "B": 12.0})
        ES, EF = forward_pass(durations, graph, _DEFAULT_CALENDAR, precision="float64")
        # ES[B] = EF[A] - 4 = 16 - 4 = 12.
        assert ES[0, 1] == 12.0
        assert EF[0, 1] == 24.0

    def test_forward_max_over_two_predecessors(self) -> None:
        graph = _make_graph(
            {"A": 10.0, "B": 6.0, "C": 4.0},
            [("A", "C", "FS", 0.0), ("B", "C", "FS", 0.0)],
            topo_order=["A", "B", "C"],
        )
        durations = _durations_array(graph, {"A": 10.0, "B": 6.0, "C": 4.0})
        ES, EF = forward_pass(durations, graph, _DEFAULT_CALENDAR, precision="float64")
        # ES[C] = max(EF[A], EF[B]) = max(10, 6) = 10.
        assert ES[0, 2] == 10.0
        assert EF[0, 2] == 14.0

    def test_forward_disconnected_graph_anchors_at_zero(self) -> None:
        graph = _make_graph(
            {"A": 8.0, "B": 12.0, "C": 4.0}, []  # zero links → all roots
        )
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0, "C": 4.0})
        ES, EF = forward_pass(durations, graph, _DEFAULT_CALENDAR, precision="float64")
        np.testing.assert_array_equal(ES[0], [0.0, 0.0, 0.0])
        np.testing.assert_array_equal(EF[0], [8.0, 12.0, 4.0])

    def test_forward_explicit_project_start(self) -> None:
        """project_start floors every ES, not just roots."""
        graph = _make_graph(
            {"A": 8.0, "B": 12.0}, [("A", "B", "FS", 0.0)]
        )
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0})
        ES, EF = forward_pass(
            durations, graph, _DEFAULT_CALENDAR, precision="float64", project_start=100.0
        )
        # Both ES values floor at 100; A still anchors there, B inherits via FS.
        assert ES[0, 0] == 100.0
        assert EF[0, 0] == 108.0
        assert ES[0, 1] == 108.0
        assert EF[0, 1] == 120.0

    def test_forward_per_iteration_independence(self) -> None:
        """Two iterations with different durations produce independent CPM."""
        graph = _make_graph(
            {"A": 8.0, "B": 12.0}, [("A", "B", "FS", 0.0)]
        )
        # Row 0: A=8, B=12 → EF=[8, 20]. Row 1: A=4, B=6 → EF=[4, 10].
        durations = np.array([[8.0, 12.0], [4.0, 6.0]], dtype=np.float64)
        ES, EF = forward_pass(durations, graph, _DEFAULT_CALENDAR, precision="float64")
        assert list(ES[0]) == [0.0, 8.0]
        assert list(EF[0]) == [8.0, 20.0]
        assert list(ES[1]) == [0.0, 4.0]
        assert list(EF[1]) == [4.0, 10.0]


# ---------------------------------------------------------------------------
# Backward pass
# ---------------------------------------------------------------------------

class TestBackwardPass:
    """Direct, focused tests on backward_pass."""

    def test_backward_single_activity(self) -> None:
        graph = _make_graph({"A": 8.0}, [])
        durations = _durations_array(graph, {"A": 8.0})
        project_finish = np.array([8.0], dtype=np.float64)
        LS, LF = backward_pass(
            durations, graph, _DEFAULT_CALENDAR, project_finish, precision="float64"
        )
        assert LF[0, 0] == 8.0
        assert LS[0, 0] == 0.0

    def test_backward_simple_chain_FS(self) -> None:
        graph = _make_graph(
            {"A": 8.0, "B": 12.0, "C": 16.0},
            [("A", "B", "FS", 0.0), ("B", "C", "FS", 0.0)],
        )
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0, "C": 16.0})
        project_finish = np.array([36.0], dtype=np.float64)
        LS, LF = backward_pass(
            durations, graph, _DEFAULT_CALENDAR, project_finish, precision="float64"
        )
        # All-critical chain → LS == ES, LF == EF.
        assert list(LS[0]) == [0.0, 8.0, 20.0]
        assert list(LF[0]) == [8.0, 20.0, 36.0]

    def test_backward_min_over_two_successors(self) -> None:
        """Predecessor takes the *earlier* (more constraining) implied finish."""
        # A → B (long), A → C (short). C constrains A more tightly than B.
        graph = _make_graph(
            {"A": 4.0, "B": 20.0, "C": 6.0},
            [("A", "B", "FS", 0.0), ("A", "C", "FS", 0.0)],
            topo_order=["A", "B", "C"],
        )
        durations = _durations_array(graph, {"A": 4.0, "B": 20.0, "C": 6.0})
        # project_finish = max(EF) = max(4, 24, 10) = 24.
        project_finish = np.array([24.0], dtype=np.float64)
        LS, LF = backward_pass(
            durations, graph, _DEFAULT_CALENDAR, project_finish, precision="float64"
        )
        # LF[B] = 24, LS[B] = 4.
        # LF[C] = 24, LS[C] = 18.
        # LF[A] = min(LS[B], LS[C]) = min(4, 18) = 4.
        assert LF[0, 1] == 24.0
        assert LF[0, 2] == 24.0
        assert LF[0, 0] == 4.0

    def test_backward_disconnected_graph_anchors_at_project_finish(self) -> None:
        graph = _make_graph(
            {"A": 8.0, "B": 12.0, "C": 4.0}, []
        )
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0, "C": 4.0})
        project_finish = np.array([20.0], dtype=np.float64)
        LS, LF = backward_pass(
            durations, graph, _DEFAULT_CALENDAR, project_finish, precision="float64"
        )
        np.testing.assert_array_equal(LF[0], [20.0, 20.0, 20.0])
        np.testing.assert_array_equal(LS[0], [12.0, 8.0, 16.0])

    def test_backward_uses_provided_project_finish(self) -> None:
        """An explicit project_finish overrides any natural EF.max."""
        graph = _make_graph(
            {"A": 8.0, "B": 12.0}, [("A", "B", "FS", 0.0)]
        )
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0})
        # Caller-supplied deadline of 30 (vs. natural EF.max = 20) → 10 hours of total slack.
        project_finish = np.array([30.0], dtype=np.float64)
        LS, LF = backward_pass(
            durations, graph, _DEFAULT_CALENDAR, project_finish, precision="float64"
        )
        assert LF[0, 1] == 30.0
        assert LS[0, 1] == 18.0
        assert LF[0, 0] == 18.0
        assert LS[0, 0] == 10.0

    def test_backward_per_iteration_project_finish(self) -> None:
        """Each iteration has its own project_finish; LS/LF respect it independently."""
        graph = _make_graph(
            {"A": 8.0, "B": 12.0}, [("A", "B", "FS", 0.0)]
        )
        durations = np.array([[8.0, 12.0], [8.0, 12.0]], dtype=np.float64)
        project_finish = np.array([20.0, 30.0], dtype=np.float64)
        LS, LF = backward_pass(
            durations, graph, _DEFAULT_CALENDAR, project_finish, precision="float64"
        )
        assert LF[0, 1] == 20.0 and LF[1, 1] == 30.0
        assert LS[0, 0] == 0.0 and LS[1, 0] == 10.0


# ---------------------------------------------------------------------------
# Slack and critical-path
# ---------------------------------------------------------------------------

class TestSlackAndCriticalPath:
    """compute_slack arithmetic + on_critical_path tolerance handling."""

    def test_slack_zero_on_critical_chain(self) -> None:
        graph = _make_graph(
            {"A": 8.0, "B": 12.0}, [("A", "B", "FS", 0.0)]
        )
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0})
        result = run_batch(durations, graph, precision="float64")
        np.testing.assert_array_equal(result["slack"][0], [0.0, 0.0])
        assert all(result["on_critical_path"][0])

    def test_slack_positive_off_critical_path(self) -> None:
        # A → B (long), A → C (short, parallel). C has slack.
        graph = _make_graph(
            {"A": 4.0, "B": 20.0, "C": 6.0},
            [("A", "B", "FS", 0.0), ("A", "C", "FS", 0.0)],
            topo_order=["A", "B", "C"],
        )
        durations = _durations_array(graph, {"A": 4.0, "B": 20.0, "C": 6.0})
        result = run_batch(durations, graph, precision="float64")
        # ES[A]=0, ES[B]=4, ES[C]=4. EF=[4, 24, 10]. project_finish=24.
        # LS[A]=0, LS[B]=4, LS[C]=18. Slack = [0, 0, 14].
        np.testing.assert_array_equal(result["slack"][0], [0.0, 0.0, 14.0])
        assert list(result["on_critical_path"][0]) == [True, True, False]

    def test_critical_path_mask_uses_tolerance(self) -> None:
        """slack of 5e-4 on-CP; slack of 5e-3 off-CP (tol = 1e-3)."""
        # Build a synthetic ES/LS pair to test compute_slack + tolerance directly.
        ES = np.zeros((1, 4), dtype=np.float64)
        LS = np.array([[0.0, 5e-4, 1e-3, 5e-3]], dtype=np.float64)
        EF = np.zeros_like(ES)  # not consulted by compute_slack
        LF = np.zeros_like(ES)
        slack = compute_slack(ES, LS, EF, LF)
        on_cp = slack <= CRITICAL_PATH_TOL
        # 0, 5e-4, 1e-3 are <= tol; 5e-3 is not.
        assert list(on_cp[0]) == [True, True, True, False]

    def test_compute_slack_is_LS_minus_ES(self) -> None:
        """compute_slack is arithmetic only — equals LS - ES."""
        ES = np.array([[1.0, 2.0, 3.0]], dtype=np.float64)
        LS = np.array([[1.0, 5.0, 3.0]], dtype=np.float64)
        EF = np.array([[10.0, 10.0, 10.0]], dtype=np.float64)
        LF = np.array([[10.0, 10.0, 10.0]], dtype=np.float64)
        slack = compute_slack(ES, LS, EF, LF)
        np.testing.assert_array_equal(slack, [[0.0, 3.0, 0.0]])


# ---------------------------------------------------------------------------
# run_batch wrapper
# ---------------------------------------------------------------------------

class TestRunBatch:
    """Convenience-wrapper contract: keys, dtypes, calendar fallback, shapes."""

    def _trivial_graph(self) -> ScheduleGraph:
        return _make_graph({"A": 8.0, "B": 12.0}, [("A", "B", "FS", 0.0)])

    def test_run_batch_returns_all_keys(self) -> None:
        graph = self._trivial_graph()
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0})
        result = run_batch(durations, graph, precision="float64")
        expected_keys = {
            "ES", "EF", "LS", "LF", "slack", "on_critical_path", "project_finish"
        }
        assert set(result.keys()) == expected_keys

    def test_run_batch_default_precision_float32(self) -> None:
        graph = self._trivial_graph()
        durations = _durations_array(
            graph, {"A": 8.0, "B": 12.0}, dtype=np.float32
        )
        result = run_batch(durations, graph)  # default precision='float32'
        assert result["ES"].dtype == np.float32
        assert result["EF"].dtype == np.float32
        assert result["LS"].dtype == np.float32
        assert result["LF"].dtype == np.float32
        assert result["slack"].dtype == np.float32
        assert result["project_finish"].dtype == np.float32
        # on_critical_path is always bool regardless of precision.
        assert result["on_critical_path"].dtype == np.bool_

    def test_run_batch_explicit_float64(self) -> None:
        graph = self._trivial_graph()
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0})
        result = run_batch(durations, graph, precision="float64")
        assert result["ES"].dtype == np.float64
        assert result["EF"].dtype == np.float64
        assert result["LS"].dtype == np.float64
        assert result["LF"].dtype == np.float64
        assert result["slack"].dtype == np.float64
        assert result["project_finish"].dtype == np.float64

    def test_run_batch_batch_size_one(self) -> None:
        """Degenerate single-iteration batch must round-trip."""
        graph = self._trivial_graph()
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0}, batch_n=1)
        result = run_batch(durations, graph, precision="float64")
        assert result["ES"].shape == (1, 2)
        assert result["project_finish"].shape == (1,)
        assert result["project_finish"][0] == 20.0

    def test_run_batch_falls_back_to_graph_default_calendar(self) -> None:
        """Passing calendar=None defaults to graph.project_default_calendar."""
        graph = self._trivial_graph()
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0})
        # No calendar argument; should not raise.
        result = run_batch(durations, graph, precision="float64")
        assert result["project_finish"][0] == 20.0

    def test_run_batch_project_finish_equals_EF_max(self) -> None:
        """project_finish is per-iteration EF.max(axis=1)."""
        graph = _make_graph(
            {"A": 8.0, "B": 12.0, "C": 4.0}, []
        )  # disconnected → EF.max = max of durations
        durations = np.array(
            [[8.0, 12.0, 4.0], [2.0, 30.0, 1.0]], dtype=np.float64
        )
        result = run_batch(durations, graph, precision="float64")
        np.testing.assert_array_equal(result["project_finish"], [12.0, 30.0])

    def test_run_batch_durations_shape_validation_n_act_mismatch(self) -> None:
        """durations.shape[1] must equal len(graph.topo_order)."""
        graph = self._trivial_graph()  # n_act = 2
        durations = np.zeros((1, 3), dtype=np.float64)  # 3 columns, mismatched
        with pytest.raises(ValueError, match="does not match len"):
            run_batch(durations, graph, precision="float64")

    def test_run_batch_durations_shape_validation_not_2d(self) -> None:
        graph = self._trivial_graph()
        durations = np.zeros((2,), dtype=np.float64)  # 1-D
        with pytest.raises(ValueError, match="must be 2-D"):
            run_batch(durations, graph, precision="float64")

    def test_run_batch_invalid_precision_raises(self) -> None:
        graph = self._trivial_graph()
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0})
        with pytest.raises(ValueError, match="precision"):
            run_batch(durations, graph, precision="float16")  # type: ignore[arg-type]

    def test_run_batch_does_not_mutate_input_durations(self) -> None:
        """The kernel must not write into the caller's durations array."""
        graph = self._trivial_graph()
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0})
        original = durations.copy()
        run_batch(durations, graph, precision="float64")
        np.testing.assert_array_equal(durations, original)

    def test_backward_pass_project_finish_shape_validation(self) -> None:
        """project_finish must be 1-D with length batch_n."""
        graph = self._trivial_graph()
        durations = _durations_array(graph, {"A": 8.0, "B": 12.0}, batch_n=2)
        # Wrong length: 3 elements vs batch_n=2.
        bad_pf = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        with pytest.raises(ValueError, match="project_finish shape"):
            backward_pass(
                durations, graph, _DEFAULT_CALENDAR, bad_pf, precision="float64"
            )
