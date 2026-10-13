"""Tests for src.sra.cpm.calendar (SR-S3-Beta-02).

Calendar arithmetic primitives. Synthetic CALENDAR / NONWORK
DataFrames inline; the live-file build is exercised against the
RefProject .xer (skipped if absent).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.sra.cpm.calendar import Calendar, build_default_calendar
from src.sra.cpm.xer_reader import parse_xer

# Repository root: tests/sra/cpm/test_calendar.py → parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: REFRETIRE-01 (D-2): the committed synthetic schedule, which every machine has. This was the
#: retired project's 22 MB export, so the live-file tests below skipped everywhere.
_LIVE_XER = _REPO_ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_schedule.xer"


# ---------------------------------------------------------------------------
# Calendar — defaults
# ---------------------------------------------------------------------------

class TestCalendarDefaults:
    def test_default_calendar_8h_5d(self) -> None:
        cal = Calendar()
        assert cal.working_hours_per_day == 8.0
        assert cal.working_days_per_week == 5
        assert cal.working_minutes_per_hour == 60.0
        assert cal.work_day_start_hour == 9.0
        assert cal.holidays == frozenset()


# ---------------------------------------------------------------------------
# Calendar — add_working_hours
# ---------------------------------------------------------------------------

class TestAddWorkingHours:
    """Forward arithmetic skipping non-working time.

    Default Calendar: 09:00–17:00, Mon–Fri.
    """

    def test_add_working_hours_within_day(self) -> None:
        """Mon 09:00 + 4h = Mon 13:00."""
        cal = Calendar()
        # 2026-04-27 is a Monday.
        start = datetime(2026, 4, 27, 9, 0)
        result = cal.add_working_hours(start, 4)
        assert result == datetime(2026, 4, 27, 13, 0)

    def test_add_working_hours_across_weekend(self) -> None:
        """Fri 16:00 + 4h = Mon 12:00 (1h Friday + 3h Monday)."""
        cal = Calendar()
        # 2026-04-24 is a Friday; 2026-04-27 is the following Monday.
        start = datetime(2026, 4, 24, 16, 0)
        result = cal.add_working_hours(start, 4)
        assert result == datetime(2026, 4, 27, 12, 0)

    def test_add_working_hours_skip_holidays(self) -> None:
        """Holiday on Tue → Mon 16:00 + 4h = Wed 12:00 (1h Mon + 3h Wed)."""
        # Mark 2026-04-28 (Tuesday) as a holiday.
        cal = Calendar(holidays=frozenset([date(2026, 4, 28)]))
        start = datetime(2026, 4, 27, 16, 0)  # Mon
        result = cal.add_working_hours(start, 4)
        assert result == datetime(2026, 4, 29, 12, 0)  # Wed

    def test_add_zero_hours_returns_input(self) -> None:
        cal = Calendar()
        start = datetime(2026, 4, 27, 14, 0)
        assert cal.add_working_hours(start, 0) == start

    def test_add_negative_hours_raises(self) -> None:
        cal = Calendar()
        with pytest.raises(ValueError, match="non-negative"):
            cal.add_working_hours(datetime(2026, 4, 27, 9, 0), -1)

    def test_add_working_hours_from_outside_window_normalises(self) -> None:
        """Sat anchor + 8h = Mon 17:00 (a full day starting Mon 09:00)."""
        cal = Calendar()
        start = datetime(2026, 4, 25, 12, 0)  # Saturday
        result = cal.add_working_hours(start, 8)
        assert result == datetime(2026, 4, 27, 17, 0)


# ---------------------------------------------------------------------------
# Calendar — diff_working_hours
# ---------------------------------------------------------------------------

class TestDiffWorkingHours:
    def test_diff_working_hours_simple(self) -> None:
        """Mon 09:00 → Mon 17:00 = 8.0."""
        cal = Calendar()
        start = datetime(2026, 4, 27, 9, 0)
        end = datetime(2026, 4, 27, 17, 0)
        assert cal.diff_working_hours(start, end) == pytest.approx(8.0)

    def test_diff_working_hours_across_weekend(self) -> None:
        """Fri 09:00 → Mon 17:00 = 16.0 (Fri full + Mon full; weekend skipped)."""
        cal = Calendar()
        start = datetime(2026, 4, 24, 9, 0)  # Fri
        end = datetime(2026, 4, 27, 17, 0)  # Mon
        assert cal.diff_working_hours(start, end) == pytest.approx(16.0)

    def test_diff_working_hours_negative_for_end_before_start(self) -> None:
        cal = Calendar()
        end = datetime(2026, 4, 27, 9, 0)
        start = datetime(2026, 4, 27, 17, 0)
        assert cal.diff_working_hours(start, end) == pytest.approx(-8.0)

    def test_diff_working_hours_equal(self) -> None:
        cal = Calendar()
        dt = datetime(2026, 4, 27, 14, 0)
        assert cal.diff_working_hours(dt, dt) == 0.0

    def test_diff_working_hours_skip_holiday(self) -> None:
        """Mon → Wed across a Tue holiday returns 16h, not 24h."""
        cal = Calendar(holidays=frozenset([date(2026, 4, 28)]))
        start = datetime(2026, 4, 27, 9, 0)  # Mon
        end = datetime(2026, 4, 29, 17, 0)  # Wed
        assert cal.diff_working_hours(start, end) == pytest.approx(16.0)

    def test_diff_working_hours_partial_day(self) -> None:
        """Mon 11:00 → Mon 14:30 = 3.5h."""
        cal = Calendar()
        start = datetime(2026, 4, 27, 11, 0)
        end = datetime(2026, 4, 27, 14, 30)
        assert cal.diff_working_hours(start, end) == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# Calendar — is_working_time / next_working_time
# ---------------------------------------------------------------------------

class TestWorkingTimePredicates:
    def test_is_working_time_weekday_in_hours(self) -> None:
        cal = Calendar()
        assert cal.is_working_time(datetime(2026, 4, 27, 14, 0)) is True

    def test_is_working_time_weekend(self) -> None:
        cal = Calendar()
        assert cal.is_working_time(datetime(2026, 4, 25, 14, 0)) is False  # Sat

    def test_is_working_time_holiday(self) -> None:
        cal = Calendar(holidays=frozenset([date(2026, 4, 27)]))
        assert cal.is_working_time(datetime(2026, 4, 27, 14, 0)) is False

    def test_is_working_time_before_window(self) -> None:
        cal = Calendar()
        assert cal.is_working_time(datetime(2026, 4, 27, 7, 0)) is False

    def test_is_working_time_at_window_end_excluded(self) -> None:
        """Half-open: 17:00 exactly is not a working time."""
        cal = Calendar()
        assert cal.is_working_time(datetime(2026, 4, 27, 17, 0)) is False

    def test_next_working_time_already_working(self) -> None:
        cal = Calendar()
        dt = datetime(2026, 4, 27, 14, 0)
        assert cal.next_working_time(dt) == dt

    def test_next_working_time_before_window_same_day(self) -> None:
        cal = Calendar()
        result = cal.next_working_time(datetime(2026, 4, 27, 7, 0))
        assert result == datetime(2026, 4, 27, 9, 0)

    def test_next_working_time_after_window_next_day(self) -> None:
        cal = Calendar()
        result = cal.next_working_time(datetime(2026, 4, 27, 18, 0))
        assert result == datetime(2026, 4, 28, 9, 0)

    def test_next_working_time_exactly_at_window_end_advances(self) -> None:
        """17:00 exactly is not in [09:00, 17:00); advance to next working day.

        The half-open-window boundary matters for any CPM kernel caller
        that asks "what comes next" after a finish-of-day timestamp.
        """
        cal = Calendar()
        # 2026-04-27 is a Monday; expected next-working-time is Tuesday 09:00.
        result = cal.next_working_time(datetime(2026, 4, 27, 17, 0))
        assert result == datetime(2026, 4, 28, 9, 0)

    def test_next_working_time_friday_end_jumps_over_weekend(self) -> None:
        """Friday 17:00 → Monday 09:00."""
        cal = Calendar()
        # 2026-04-24 is a Friday; 2026-04-27 is the following Monday.
        result = cal.next_working_time(datetime(2026, 4, 24, 17, 0))
        assert result == datetime(2026, 4, 27, 9, 0)

    def test_next_working_time_weekend_jumps_to_monday(self) -> None:
        cal = Calendar()
        result = cal.next_working_time(datetime(2026, 4, 25, 14, 0))  # Sat
        assert result == datetime(2026, 4, 27, 9, 0)


# ---------------------------------------------------------------------------
# build_default_calendar
# ---------------------------------------------------------------------------

def _calendar_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class TestBuildDefaultCalendar:
    def test_build_default_calendar_picks_default_flag_y(self) -> None:
        df = _calendar_df(
            [
                {
                    "clndr_id": 1,
                    "clndr_name": "Five-day",
                    "default_flag": "N",
                    "day_hr_cnt": 8.0,
                    "week_hr_cnt": 40.0,
                },
                {
                    "clndr_id": 2,
                    "clndr_name": "Seven-day",
                    "default_flag": "Y",
                    "day_hr_cnt": 10.0,
                    "week_hr_cnt": 70.0,
                },
            ]
        )
        cal = build_default_calendar({"CALENDAR": df})
        assert cal.working_hours_per_day == 10.0
        assert cal.working_days_per_week == 7

    def test_build_default_calendar_no_default_flag(self, caplog) -> None:
        """No `default_flag='Y'` → first row wins, with warning."""
        df = _calendar_df(
            [
                {
                    "clndr_id": 1,
                    "clndr_name": "Cal A",
                    "default_flag": "N",
                    "day_hr_cnt": 8.0,
                    "week_hr_cnt": 40.0,
                },
                {
                    "clndr_id": 2,
                    "clndr_name": "Cal B",
                    "default_flag": "N",
                    "day_hr_cnt": 6.0,
                    "week_hr_cnt": 30.0,
                },
            ]
        )
        with caplog.at_level("WARNING"):
            cal = build_default_calendar({"CALENDAR": df})
        assert cal.working_hours_per_day == 8.0
        assert any("default_flag" in rec.message for rec in caplog.records)

    def test_build_default_calendar_multiple_default_flag_first_wins(
        self, caplog
    ) -> None:
        df = _calendar_df(
            [
                {
                    "clndr_id": 1,
                    "clndr_name": "First default",
                    "default_flag": "Y",
                    "day_hr_cnt": 8.0,
                    "week_hr_cnt": 40.0,
                },
                {
                    "clndr_id": 2,
                    "clndr_name": "Second default",
                    "default_flag": "Y",
                    "day_hr_cnt": 7.5,
                    "week_hr_cnt": 37.5,
                },
            ]
        )
        with caplog.at_level("WARNING"):
            cal = build_default_calendar({"CALENDAR": df})
        assert cal.working_hours_per_day == 8.0
        assert any(
            "Multiple CALENDAR rows" in rec.message for rec in caplog.records
        )

    def test_build_default_calendar_missing_table(self, caplog) -> None:
        with caplog.at_level("WARNING"):
            cal = build_default_calendar({})
        assert cal == Calendar()  # hardcoded default
        assert any("CALENDAR" in rec.message for rec in caplog.records)

    def test_build_default_calendar_empty_table(self, caplog) -> None:
        df = pd.DataFrame(columns=[
            "clndr_id", "clndr_name", "default_flag", "day_hr_cnt", "week_hr_cnt"
        ])
        with caplog.at_level("WARNING"):
            cal = build_default_calendar({"CALENDAR": df})
        assert cal == Calendar()

    def test_build_default_calendar_loads_holidays_from_nonwork(self) -> None:
        cal_df = _calendar_df(
            [
                {
                    "clndr_id": 7,
                    "clndr_name": "Project",
                    "default_flag": "Y",
                    "day_hr_cnt": 8.0,
                    "week_hr_cnt": 40.0,
                },
            ]
        )
        nonwork_df = pd.DataFrame(
            [
                {"clndr_id": 7, "nonwork_date": "2026-12-25"},
                {"clndr_id": 7, "nonwork_date": "2026-12-26"},
                # different calendar — should be ignored
                {"clndr_id": 99, "nonwork_date": "2026-01-01"},
            ]
        )
        cal = build_default_calendar({"CALENDAR": cal_df, "NONWORK": nonwork_df})
        assert date(2026, 12, 25) in cal.holidays
        assert date(2026, 12, 26) in cal.holidays
        assert date(2026, 1, 1) not in cal.holidays

    def test_build_default_calendar_no_nonwork_no_holidays(self) -> None:
        cal_df = _calendar_df(
            [
                {
                    "clndr_id": 1,
                    "clndr_name": "Project",
                    "default_flag": "Y",
                    "day_hr_cnt": 8.0,
                    "week_hr_cnt": 40.0,
                },
            ]
        )
        cal = build_default_calendar({"CALENDAR": cal_df})
        assert cal.holidays == frozenset()


# ---------------------------------------------------------------------------
# Live-file: build the calendar from a real .xer
# ---------------------------------------------------------------------------

class TestLiveFileCalendar:
    def test_build_default_calendar_from_a_real_xer(self) -> None:
        tables = parse_xer(_LIVE_XER)
        cal = build_default_calendar(tables)
        # Day-rate sanity: a sensible working-day length.
        assert 4.0 <= cal.working_hours_per_day <= 24.0
        # Days-per-week must be in the human range.
        assert 1 <= cal.working_days_per_week <= 7
        assert cal.working_minutes_per_hour == 60.0
