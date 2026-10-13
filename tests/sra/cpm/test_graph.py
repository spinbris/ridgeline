"""Tests for src.sra.cpm.graph (SR-S3-Beta-02).

The graph data model is project-agnostic; every test in this file
constructs its inputs inline. No RefProject file references — the
reusability invariant per Beta-00.3.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.graph import Activity, Link, ScheduleGraph


# ---------------------------------------------------------------------------
# Link
# ---------------------------------------------------------------------------

class TestLink:
    """Link: immutable, validates link_type and id strings."""

    def test_link_dataclass_immutable(self) -> None:
        """Link is frozen; field assignment raises."""
        link = Link(pred_id="A", succ_id="B", link_type="FS", lag_hours=0.0)
        with pytest.raises(FrozenInstanceError):
            link.lag_hours = 1.0  # type: ignore[misc]

    def test_link_invalid_type_raises(self) -> None:
        """Unknown link_type (e.g., "PR_XX") raises ValueError on construction."""
        with pytest.raises(ValueError, match="link_type"):
            Link(pred_id="A", succ_id="B", link_type="PR_XX", lag_hours=0.0)  # type: ignore[arg-type]

    def test_link_empty_pred_id_raises(self) -> None:
        with pytest.raises(ValueError, match="pred_id"):
            Link(pred_id="", succ_id="B", link_type="FS", lag_hours=0.0)

    def test_link_empty_succ_id_raises(self) -> None:
        with pytest.raises(ValueError, match="succ_id"):
            Link(pred_id="A", succ_id="", link_type="FS", lag_hours=0.0)

    def test_link_all_four_types_accepted(self) -> None:
        for t in ("FS", "SS", "FF", "SF"):
            link = Link(pred_id="A", succ_id="B", link_type=t, lag_hours=0.0)  # type: ignore[arg-type]
            assert link.link_type == t


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------

class TestActivity:
    """Activity: default link lists, optional total_float_hours."""

    def test_activity_default_links_empty(self) -> None:
        a = Activity(
            id="1",
            code="A100",
            name="First",
            task_type="TT_Task",
            original_duration_hours=80.0,
            total_float_hours=0.0,
            calendar_id="1000",
        )
        assert a.predecessor_links == []
        assert a.successor_links == []

    def test_activity_total_float_can_be_none(self) -> None:
        a = Activity(
            id="2",
            code="A200",
            name="Mile",
            task_type="TT_Mile",
            original_duration_hours=0.0,
            total_float_hours=None,
            calendar_id=None,
        )
        assert a.total_float_hours is None

    def test_activity_independent_link_lists(self) -> None:
        """Two activities have independent default lists (no shared mutable default)."""
        a = Activity(
            id="1",
            code="A",
            name="A",
            task_type="TT_Task",
            original_duration_hours=0.0,
            total_float_hours=0.0,
            calendar_id=None,
        )
        b = Activity(
            id="2",
            code="B",
            name="B",
            task_type="TT_Task",
            original_duration_hours=0.0,
            total_float_hours=0.0,
            calendar_id=None,
        )
        a.successor_links.append(
            Link(pred_id="1", succ_id="2", link_type="FS", lag_hours=0.0)
        )
        assert b.successor_links == []  # not aliased


# ---------------------------------------------------------------------------
# ScheduleGraph
# ---------------------------------------------------------------------------

def _activity(aid: str, **overrides: object) -> Activity:
    """Construct a simple Activity with sensible defaults for tests."""
    base = dict(
        id=aid,
        code=f"A{aid}",
        name=f"Task {aid}",
        task_type="TT_Task",
        original_duration_hours=8.0,
        total_float_hours=0.0,
        calendar_id="1000",
    )
    base.update(overrides)
    return Activity(**base)  # type: ignore[arg-type]


class TestScheduleGraph:
    """ScheduleGraph: integrity validation in __post_init__."""

    def test_schedule_graph_round_trips_topo_order(self) -> None:
        activities = {"1": _activity("1"), "2": _activity("2")}
        link = Link(pred_id="1", succ_id="2", link_type="FS", lag_hours=0.0)
        graph = ScheduleGraph(
            activities=activities,
            links=[link],
            topo_order=["1", "2"],
            project_default_calendar=Calendar(),
        )
        assert sorted(graph.topo_order) == sorted(activities.keys())
        assert len(graph.topo_order) == len(activities)

    def test_schedule_graph_links_consistent_with_activities(self) -> None:
        """Every Link's pred_id and succ_id must resolve in activities."""
        activities = {"1": _activity("1"), "2": _activity("2")}
        bad_link = Link(pred_id="1", succ_id="999", link_type="FS", lag_hours=0.0)
        with pytest.raises(ValueError, match="999"):
            ScheduleGraph(
                activities=activities,
                links=[bad_link],
                topo_order=["1", "2"],
                project_default_calendar=Calendar(),
            )

    def test_schedule_graph_topo_order_length_mismatch_raises(self) -> None:
        activities = {"1": _activity("1"), "2": _activity("2")}
        with pytest.raises(ValueError, match="topo_order length"):
            ScheduleGraph(
                activities=activities,
                links=[],
                topo_order=["1"],  # missing "2"
                project_default_calendar=Calendar(),
            )

    def test_schedule_graph_topo_order_unknown_id_raises(self) -> None:
        activities = {"1": _activity("1"), "2": _activity("2")}
        with pytest.raises(ValueError, match="unknown"):
            ScheduleGraph(
                activities=activities,
                links=[],
                topo_order=["1", "3"],  # "3" not in activities
                project_default_calendar=Calendar(),
            )

    def test_schedule_graph_empty_is_valid(self) -> None:
        graph = ScheduleGraph(
            activities={},
            links=[],
            topo_order=[],
            project_default_calendar=Calendar(),
        )
        assert graph.topo_order == []
        assert graph.activities == {}
