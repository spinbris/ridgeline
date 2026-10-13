"""Showcase-P2 WS2-C — XER writer round-trip + validation tests."""
from __future__ import annotations

import pandas as pd
import pytest

from src.sra.cpm.xer_reader import parse_xer, validate_xer_tables
from src.sra.cpm.xer_writer import tables_to_xer_text, write_xer


def _minimal_valid_tables() -> dict[str, list[dict]]:
    """A 4-table schedule carrying every reader-required column.

    Two tasks linked by one FS predecessor, one default calendar, a
    two-level PROJWBS. Enough to pass validate_xer_tables and parse back.
    """
    calendar = [
        {
            "clndr_id": 1, "clndr_name": "Standard", "default_flag": "Y",
            "clndr_data": "(0||CalendarData())", "day_hr_cnt": 8.0,
            "week_hr_cnt": 40.0, "month_hr_cnt": 172.0, "year_hr_cnt": 2000.0,
        },
    ]
    projwbs = [
        {"wbs_id": 100, "proj_id": 1, "parent_wbs_id": None,
         "wbs_short_name": "WP", "wbs_name": "Wind Project", "seq_num": 1},
        {"wbs_id": 110, "proj_id": 1, "parent_wbs_id": 100,
         "wbs_short_name": "10", "wbs_name": "Civil Works", "seq_num": 2},
    ]
    task = [
        {
            "task_id": 1001, "proj_id": 1, "wbs_id": 110, "clndr_id": 1,
            "task_code": "10.A.001", "task_name": "Mobilise", "task_type": "TT_Task",
            "target_drtn_hr_cnt": 80.0, "total_float_hr_cnt": 0.0,
            "free_float_hr_cnt": 0.0,
            "early_start_date": pd.Timestamp("2026-02-02 08:00"),
            "early_end_date": pd.Timestamp("2026-02-13 16:00"),
            "late_start_date": pd.Timestamp("2026-02-02 08:00"),
            "late_end_date": pd.Timestamp("2026-02-13 16:00"),
            "target_start_date": pd.Timestamp("2026-02-02 08:00"),
            "target_end_date": pd.Timestamp("2026-02-13 16:00"),
            "cstr_date": None, "cstr_type": "", "driving_path_flag": "Y",
        },
        {
            "task_id": 1002, "proj_id": 1, "wbs_id": 110, "clndr_id": 1,
            "task_code": "10.A.002", "task_name": "Foundations", "task_type": "TT_Task",
            "target_drtn_hr_cnt": 160.0, "total_float_hr_cnt": 0.0,
            "free_float_hr_cnt": 0.0,
            "early_start_date": pd.Timestamp("2026-02-16 08:00"),
            "early_end_date": pd.Timestamp("2026-03-13 16:00"),
            "late_start_date": pd.Timestamp("2026-02-16 08:00"),
            "late_end_date": pd.Timestamp("2026-03-13 16:00"),
            "target_start_date": pd.Timestamp("2026-02-16 08:00"),
            "target_end_date": pd.Timestamp("2026-03-13 16:00"),
            "cstr_date": None, "cstr_type": "", "driving_path_flag": "Y",
        },
    ]
    taskpred = [
        {"task_pred_id": 5001, "task_id": 1002, "pred_task_id": 1001,
         "pred_type": "PR_FS", "lag_hr_cnt": 0.0},
    ]
    return {"CALENDAR": calendar, "PROJWBS": projwbs, "TASK": task, "TASKPRED": taskpred}


def test_write_xer_round_trips_through_reader(tmp_path):
    out = write_xer(_minimal_valid_tables(), tmp_path / "wind.xer")
    assert out.exists()
    parsed = parse_xer(out)
    validate_xer_tables(parsed)  # must not raise
    assert set(parsed) >= {"TASK", "TASKPRED", "CALENDAR", "PROJWBS"}
    assert len(parsed["TASK"]) == 2
    assert len(parsed["TASKPRED"]) == 1


def test_round_trip_preserves_values(tmp_path):
    out = write_xer(_minimal_valid_tables(), tmp_path / "wind.xer")
    parsed = parse_xer(out)
    task = parsed["TASK"].set_index("task_id")
    # int id, string code, float hours, datetime all survive.
    assert task.loc[1001, "task_code"] == "10.A.001"
    assert float(task.loc[1001, "target_drtn_hr_cnt"]) == 80.0
    assert pd.api.types.is_datetime64_any_dtype(parsed["TASK"]["early_start_date"])
    assert str(parsed["TASK"].loc[0, "early_start_date"]).startswith("2026-02-02")


def test_header_line_is_ermhdr(tmp_path):
    text = tables_to_xer_text(_minimal_valid_tables())
    assert text.splitlines()[0].startswith("ERMHDR")
    assert text.rstrip().splitlines()[-1] == "%E"


def test_validate_catches_missing_required_table(tmp_path):
    tables = _minimal_valid_tables()
    del tables["CALENDAR"]  # CALENDAR is parse-time required
    with pytest.raises(ValueError):
        write_xer(tables, tmp_path / "bad.xer")


def test_validate_catches_missing_required_column(tmp_path):
    tables = _minimal_valid_tables()
    # Drop a required TASK column from every row.
    for row in tables["TASK"]:
        del row["total_float_hr_cnt"]
    with pytest.raises(ValueError):
        write_xer(tables, tmp_path / "bad.xer")


def test_tab_in_cell_rejected(tmp_path):
    tables = _minimal_valid_tables()
    tables["TASK"][0]["task_name"] = "Bad\tName"
    with pytest.raises(ValueError):
        tables_to_xer_text(tables)
