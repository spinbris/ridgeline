"""Tests for src.sra.cpm.graph_builder (SR-S3-Beta-02).

Two test classes:

* **Synthetic-graph** — DataFrames constructed inline. These are the
  reusability gate per Beta-00.3: the builder must work on any XER, not
  just RefProject's.
* **Live-file** — the RefProject .xer (skipped if absent). Confirms the
  end-to-end ``parse_xer → build_schedule_graph`` pipeline against the
  real schedule.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.sra.cpm.calendar import Calendar
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from src.sra.cpm.graph_builder import build_schedule_graph
from src.sra.cpm.xer_reader import parse_xer

# Repository root: tests/sra/cpm/test_graph_builder.py → parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: REFRETIRE-01 (D-2): the committed synthetic schedule, which every machine has. This was the
#: retired project's 22 MB export, so the live-file tests below skipped everywhere.
_LIVE_XER = _REPO_ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_schedule.xer"


# ---------------------------------------------------------------------------
# Synthetic-table builders (inline; no RefProject file references)
# ---------------------------------------------------------------------------

def _calendar_table(
    *,
    clndr_id: int = 1000,
    default_flag: str = "Y",
    day_hr: float = 8.0,
    week_hr: float = 40.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "clndr_id": clndr_id,
                "clndr_name": "Standard",
                "default_flag": default_flag,
                "day_hr_cnt": np.float32(day_hr),
                "week_hr_cnt": np.float32(week_hr),
            }
        ]
    )


def _task_table(rows: list[dict]) -> pd.DataFrame:
    """Build a TASK DataFrame from row dicts; missing fields filled with defaults."""
    defaults = {
        "task_id": pd.NA,
        "task_code": "",
        "task_name": "",
        "task_type": "TT_Task",
        "target_drtn_hr_cnt": np.float32(8.0),
        "total_float_hr_cnt": np.float32(0.0),
        "clndr_id": pd.NA,
    }
    full = [{**defaults, **r} for r in rows]
    df = pd.DataFrame(full)
    # Mimic xer_reader's typing: task_id / clndr_id as Int64.
    df["task_id"] = df["task_id"].astype("Int64")
    df["clndr_id"] = df["clndr_id"].astype("Int64")
    return df


def _taskpred_table(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "task_pred_id": pd.NA,
        "task_id": pd.NA,
        "pred_task_id": pd.NA,
        "pred_type": "PR_FS",
        "lag_hr_cnt": np.float32(0.0),
    }
    full = [{**defaults, **r} for r in rows]
    if not full:
        df = pd.DataFrame(
            {
                "task_pred_id": pd.array([], dtype="Int64"),
                "task_id": pd.array([], dtype="Int64"),
                "pred_task_id": pd.array([], dtype="Int64"),
                "pred_type": pd.array([], dtype=object),
                "lag_hr_cnt": pd.array([], dtype="float32"),
            }
        )
        return df
    df = pd.DataFrame(full)
    df["task_id"] = df["task_id"].astype("Int64")
    df["pred_task_id"] = df["pred_task_id"].astype("Int64")
    return df


def _simple_chain(n: int = 3) -> dict[str, pd.DataFrame]:
    """N activities in a linear FS chain with zero lag."""
    tasks = [
        {
            "task_id": i,
            "task_code": f"A{i:03d}",
            "task_name": f"Task {i}",
            "target_drtn_hr_cnt": np.float32(8.0 * i),
            "clndr_id": 1000,
        }
        for i in range(1, n + 1)
    ]
    preds = [
        {"task_pred_id": i, "task_id": i + 1, "pred_task_id": i, "pred_type": "PR_FS"}
        for i in range(1, n)
    ]
    return {
        "TASK": _task_table(tasks),
        "TASKPRED": _taskpred_table(preds),
        "CALENDAR": _calendar_table(),
    }


# ---------------------------------------------------------------------------
# Synthetic tests
# ---------------------------------------------------------------------------

class TestSyntheticGraphBuilder:
    """Reusability gate: builder works on any XER, not just RefProject's."""

    def test_build_simple_chain(self) -> None:
        tables = _simple_chain(3)
        graph = build_schedule_graph(tables)

        assert isinstance(graph, ScheduleGraph)
        assert set(graph.activities.keys()) == {"1", "2", "3"}
        # FS chain → topo order is 1, 2, 3.
        assert graph.topo_order == ["1", "2", "3"]
        # 2 links: 1→2 and 2→3.
        assert len(graph.links) == 2
        assert all(link.link_type == "FS" for link in graph.links)
        assert all(link.lag_hours == 0.0 for link in graph.links)
        # Calendar built from the synthetic CALENDAR table.
        assert isinstance(graph.project_default_calendar, Calendar)
        assert graph.project_default_calendar.working_hours_per_day == 8.0

    def test_build_with_lag_all_four_link_types(self) -> None:
        """Exercise FS, SS, FF, SF each with non-zero lag."""
        tasks = [
            {"task_id": 1, "task_code": "A", "target_drtn_hr_cnt": np.float32(8.0)},
            {"task_id": 2, "task_code": "B", "target_drtn_hr_cnt": np.float32(8.0)},
            {"task_id": 3, "task_code": "C", "target_drtn_hr_cnt": np.float32(8.0)},
            {"task_id": 4, "task_code": "D", "target_drtn_hr_cnt": np.float32(8.0)},
            {"task_id": 5, "task_code": "E", "target_drtn_hr_cnt": np.float32(8.0)},
        ]
        preds = [
            {"task_pred_id": 1, "task_id": 2, "pred_task_id": 1,
             "pred_type": "PR_FS", "lag_hr_cnt": np.float32(4.0)},
            {"task_pred_id": 2, "task_id": 3, "pred_task_id": 2,
             "pred_type": "PR_SS", "lag_hr_cnt": np.float32(2.0)},
            {"task_pred_id": 3, "task_id": 4, "pred_task_id": 3,
             "pred_type": "PR_FF", "lag_hr_cnt": np.float32(-1.0)},
            {"task_pred_id": 4, "task_id": 5, "pred_task_id": 4,
             "pred_type": "PR_SF", "lag_hr_cnt": np.float32(0.0)},
        ]
        tables = {
            "TASK": _task_table(tasks),
            "TASKPRED": _taskpred_table(preds),
            "CALENDAR": _calendar_table(),
        }
        graph = build_schedule_graph(tables)
        observed_types = {link.link_type for link in graph.links}
        assert observed_types == {"FS", "SS", "FF", "SF"}
        # Lag values preserved; check by type.
        by_type = {link.link_type: link for link in graph.links}
        assert by_type["FS"].lag_hours == pytest.approx(4.0)
        assert by_type["SS"].lag_hours == pytest.approx(2.0)
        assert by_type["FF"].lag_hours == pytest.approx(-1.0)
        assert by_type["SF"].lag_hours == pytest.approx(0.0)

    def test_cycle_detection_raises(self) -> None:
        """A→B→A cycle: ValueError lists both ids."""
        tasks = [
            {"task_id": 1, "task_code": "A"},
            {"task_id": 2, "task_code": "B"},
        ]
        preds = [
            {"task_pred_id": 1, "task_id": 2, "pred_task_id": 1, "pred_type": "PR_FS"},
            {"task_pred_id": 2, "task_id": 1, "pred_task_id": 2, "pred_type": "PR_FS"},
        ]
        tables = {
            "TASK": _task_table(tasks),
            "TASKPRED": _taskpred_table(preds),
            "CALENDAR": _calendar_table(),
        }
        with pytest.raises(ValueError, match="cycle") as excinfo:
            build_schedule_graph(tables)
        msg = str(excinfo.value)
        assert "1" in msg and "2" in msg

    def test_self_loop_raises(self) -> None:
        """A→A: ValueError naming the offending id."""
        tasks = [{"task_id": 7, "task_code": "Solo"}]
        preds = [
            {"task_pred_id": 1, "task_id": 7, "pred_task_id": 7, "pred_type": "PR_FS"}
        ]
        tables = {
            "TASK": _task_table(tasks),
            "TASKPRED": _taskpred_table(preds),
            "CALENDAR": _calendar_table(),
        }
        with pytest.raises(ValueError, match=r"self-loop"):
            build_schedule_graph(tables)

    def test_orphan_predecessor_raises(self) -> None:
        """TASKPRED references a pred_task_id missing from TASK → KeyError."""
        tasks = [
            {"task_id": 1, "task_code": "A"},
            {"task_id": 2, "task_code": "B"},
        ]
        preds = [
            {"task_pred_id": 1, "task_id": 2, "pred_task_id": 999,
             "pred_type": "PR_FS"}
        ]
        tables = {
            "TASK": _task_table(tasks),
            "TASKPRED": _taskpred_table(preds),
            "CALENDAR": _calendar_table(),
        }
        with pytest.raises(KeyError, match="999"):
            build_schedule_graph(tables)

    def test_topo_order_stable_under_input_permutation(self) -> None:
        """Same activities + links in different row order → equivalent topo order."""
        tables_a = _simple_chain(4)
        # Permute TASK and TASKPRED rows.
        tables_b = {
            "TASK": tables_a["TASK"].iloc[[3, 1, 0, 2]].reset_index(drop=True),
            "TASKPRED": tables_a["TASKPRED"]
            .iloc[[2, 0, 1]]
            .reset_index(drop=True),
            "CALENDAR": tables_a["CALENDAR"],
        }
        ga = build_schedule_graph(tables_a)
        gb = build_schedule_graph(tables_b)
        # Both must be valid topological orders of the same chain.
        # For an FS chain, every valid topo order has each predecessor
        # appearing before its successor.
        for graph in (ga, gb):
            position = {aid: i for i, aid in enumerate(graph.topo_order)}
            for link in graph.links:
                assert position[link.pred_id] < position[link.succ_id]
        # Same activity set.
        assert set(ga.activities) == set(gb.activities)

    def test_milestone_zero_duration(self) -> None:
        tasks = [
            {"task_id": 1, "task_code": "A", "task_type": "TT_Task",
             "target_drtn_hr_cnt": np.float32(8.0)},
            {"task_id": 2, "task_code": "FIN", "task_type": "TT_FinMile",
             "target_drtn_hr_cnt": np.float32(0.0)},
        ]
        preds = [
            {"task_pred_id": 1, "task_id": 2, "pred_task_id": 1, "pred_type": "PR_FS"}
        ]
        tables = {
            "TASK": _task_table(tasks),
            "TASKPRED": _taskpred_table(preds),
            "CALENDAR": _calendar_table(),
        }
        graph = build_schedule_graph(tables)
        finmile = graph.activities["2"]
        assert finmile.task_type == "TT_FinMile"
        assert finmile.original_duration_hours == 0.0

    def test_invalid_pred_type_raises(self) -> None:
        tasks = [
            {"task_id": 1, "task_code": "A"},
            {"task_id": 2, "task_code": "B"},
        ]
        preds = [
            {"task_pred_id": 1, "task_id": 2, "pred_task_id": 1, "pred_type": "PR_XX"}
        ]
        tables = {
            "TASK": _task_table(tasks),
            "TASKPRED": _taskpred_table(preds),
            "CALENDAR": _calendar_table(),
        }
        with pytest.raises(ValueError, match="PR_XX"):
            build_schedule_graph(tables)

    def test_explicit_calendar_override(self) -> None:
        """Passing a Calendar bypasses build_default_calendar."""
        explicit = Calendar(working_hours_per_day=10.0, working_days_per_week=6)
        tables = _simple_chain(2)
        graph = build_schedule_graph(tables, calendar=explicit)
        assert graph.project_default_calendar is explicit

    def test_missing_required_column_raises(self) -> None:
        tables = _simple_chain(2)
        # Drop the lag_hr_cnt column from TASKPRED.
        tables["TASKPRED"] = tables["TASKPRED"].drop(columns=["lag_hr_cnt"])
        with pytest.raises(ValueError, match="lag_hr_cnt"):
            build_schedule_graph(tables)

    def test_total_float_none_for_milestone(self) -> None:
        """Milestone with NaN total_float_hr_cnt → Activity.total_float_hours is None."""
        tasks = [
            {"task_id": 1, "task_code": "MILE", "task_type": "TT_Mile",
             "target_drtn_hr_cnt": np.float32(0.0),
             "total_float_hr_cnt": np.nan},
        ]
        tables = {
            "TASK": _task_table(tasks),
            "TASKPRED": _taskpred_table([]),
            "CALENDAR": _calendar_table(),
        }
        graph = build_schedule_graph(tables)
        assert graph.activities["1"].total_float_hours is None

    def test_links_distributed_to_pred_and_succ(self) -> None:
        tables = _simple_chain(3)
        graph = build_schedule_graph(tables)
        # Activity 1: 0 predecessors, 1 successor (→2).
        assert len(graph.activities["1"].predecessor_links) == 0
        assert len(graph.activities["1"].successor_links) == 1
        # Activity 2: 1 predecessor (←1), 1 successor (→3).
        assert len(graph.activities["2"].predecessor_links) == 1
        assert len(graph.activities["2"].successor_links) == 1
        # Activity 3: 1 predecessor, 0 successors.
        assert len(graph.activities["3"].predecessor_links) == 1
        assert len(graph.activities["3"].successor_links) == 0


# ---------------------------------------------------------------------------
# Live-file tests (a real .xer, committed)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_tables() -> dict:
    return parse_xer(_LIVE_XER)


@pytest.fixture(scope="module")
def live_graph(live_tables: dict) -> ScheduleGraph:
    """Build the ScheduleGraph from the committed .xer once per module."""
    return build_schedule_graph(live_tables)


class TestLiveFileGraph:
    """REFRETIRE-01 (D-2): the row counts these asserted were the retired export's own. What
    the checks are for is the relationship between what was parsed and what was built, which
    holds for any schedule and is asserted against the parsed tables rather than a literal."""

    def test_every_task_row_becomes_an_activity(
        self, live_tables: dict, live_graph: ScheduleGraph
    ) -> None:
        assert len(live_graph.activities) == len(live_tables["TASK"])
        assert len(live_graph.topo_order) == len(live_tables["TASK"])

    def test_links_are_the_taskpred_rows_less_exact_duplicates(
        self, live_tables: dict, live_graph: ScheduleGraph
    ) -> None:
        # Deduplication is on the exact tuple (pred_id, succ_id, link_type, lag_hours); a
        # canonical P6 export carries no exact duplicates, so the counts match. A future
        # export that does emit duplicates is an export bug, and this surfaces it.
        assert len(live_graph.links) == len(live_tables["TASKPRED"])

    def test_the_graph_is_acyclic_and_complete(self, live_graph: ScheduleGraph) -> None:
        # If a graph came back, the topo sort succeeded — assert the order is a permutation
        # of the activity ids.
        assert set(live_graph.topo_order) == set(live_graph.activities.keys())

    def test_link_types_are_canonical(self, live_graph: ScheduleGraph) -> None:
        observed = {link.link_type for link in live_graph.links}
        canonical = {"FS", "SS", "FF", "SF"}
        assert observed <= canonical
        # FS is dominant in any sensible CPM schedule.
        assert "FS" in observed

    @pytest.mark.wallclock  # measures the box, not the code: reds under -n auto
    def test_build_within_time_budget(self) -> None:
        """build_schedule_graph completes in < 5s on the live file."""
        tables = parse_xer(_LIVE_XER)
        t0 = time.perf_counter()
        build_schedule_graph(tables)
        elapsed = time.perf_counter() - t0
        # Per brief §7 risk row: budget < 5s.
        assert elapsed < 5.0, f"build_schedule_graph took {elapsed:.2f}s (budget 5s)"
