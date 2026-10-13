"""Working-time calendar (project-agnostic, beta-simplified).

This module provides :class:`Calendar`, a working-time calendar with
arithmetic primitives (``add_working_hours``, ``diff_working_hours``,
``is_working_time``, ``next_working_time``), and
:func:`build_default_calendar`, which constructs the project-default
calendar from a parsed XER's ``CALENDAR`` (and optional ``NONWORK``)
tables.

Beta simplification (per SR-S3-Beta-00.5)
-----------------------------------------
A single project-default calendar is in force during the beta phase.
Per-activity calendar resolution (each activity reading
``TASK.clndr_id``) and full per-day working-pattern variation are
**deferred to SR-S3-Prod**. The XER ``CALENDAR.clndr_data`` blob
encodes per-day working-pattern variation and per-calendar exception
lists; **the full ``clndr_data`` blob parser is out of scope for
Beta-02** (it's the ``calendar`` field in the kernel module map; full
parser lands in SR-S3-Prod). Beta-02 reads only ``day_hr_cnt``,
``week_hr_cnt``, and ``default_flag`` from the ``CALENDAR`` table, plus
``nonwork_date`` and ``clndr_id`` from ``NONWORK`` if present.

Working-window convention
-------------------------
The working window each working day runs from ``work_day_start_hour``
(default ``9.0`` → 09:00) for ``working_hours_per_day`` hours
(default ``8.0`` → ending at 17:00). Half-open: a datetime is "in
working time" iff ``work_day_start <= dt < work_day_end``.

Weekends are days whose ``weekday()`` is ``>= working_days_per_week``
(default 5 → Saturday/Sunday excluded). Holidays are explicit dates in
the ``holidays`` frozenset and are excluded regardless of weekday.

This module is project-agnostic — no project paths, file names, or
project codes appear here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Calendar:
    """Working-time calendar.

    Attributes
    ----------
    working_hours_per_day : float
        Default 8.0. From ``CALENDAR.day_hr_cnt`` for the project-default
        row.
    working_days_per_week : int
        Default 5. Derived from ``CALENDAR.week_hr_cnt / day_hr_cnt`` and
        rounded.
    holidays : frozenset[date]
        Empty by default during beta. Populated from ``NONWORK`` rows
        whose ``clndr_id`` matches the project-default calendar's id.
    working_minutes_per_hour : float
        Default 60.0. Allows the rare case where one "working hour"
        counts as fewer elapsed minutes (e.g., scheduled breaks). For a
        configured value ``m``, the conversion is
        ``working_hours = elapsed_minutes / m``.
    work_day_start_hour : float
        Default 9.0 (i.e. 09:00). Anchors the daily working window;
        the window ends at ``work_day_start_hour + working_hours_per_day``.

    Notes
    -----
    Frozen so :class:`Calendar` instances are hashable and safe to share
    across :class:`~src.sra.cpm.graph.ScheduleGraph` instances.
    """

    working_hours_per_day: float = 8.0
    working_days_per_week: int = 5
    holidays: frozenset = field(default_factory=frozenset)
    working_minutes_per_hour: float = 60.0
    work_day_start_hour: float = 9.0

    # ------------------------------------------------------------------
    # Public arithmetic
    # ------------------------------------------------------------------

    def is_working_time(self, dt: datetime) -> bool:
        """True if ``dt`` falls inside a working day and within working hours.

        The working window is half-open: ``[start, end)``. A datetime
        exactly at the day's end time (e.g. 17:00 with default settings)
        is **not** considered working time.
        """
        if not self._is_working_day(dt.date()):
            return False
        work_start, work_end = self._work_window(dt.date())
        return work_start <= dt < work_end

    def next_working_time(self, dt: datetime) -> datetime:
        """The next working datetime at or after ``dt``.

        If ``dt`` is already inside a working window, returns ``dt``
        unchanged. Otherwise advances forward to the start of the next
        working window (skipping weekends and holidays).

        Boundary cases worth being explicit about:

        * ``dt`` exactly at the day's working-window end (e.g. 17:00 with
          default settings) is **not** "in working time" because the
          window is half-open; this method advances to the next working
          day's start. The CPM kernel uses :meth:`add_working_hours`
          rather than this method for finish-time arithmetic, so this
          boundary rarely matters during forward-pass CPM.
        * ``dt`` strictly before the day's working-window start on a
          working day snaps forward to that day's start.
        """
        if self.is_working_time(dt):
            return dt

        # If today is a working day and dt is before the window opens,
        # snap forward to the window's start.
        if self._is_working_day(dt.date()):
            work_start, _ = self._work_window(dt.date())
            if dt < work_start:
                return work_start

        # Otherwise advance to the next working day's start.
        next_date = dt.date() + timedelta(days=1)
        while not self._is_working_day(next_date):
            next_date += timedelta(days=1)
        return self._work_window(next_date)[0]

    def add_working_hours(self, start: datetime, hours: float) -> datetime:
        """Add ``hours`` working hours to ``start``, skipping non-working time.

        Parameters
        ----------
        start : datetime
            Anchor datetime. If not currently in working time, the cursor
            advances to the next working time before measuring.
        hours : float
            Working hours to add. Must be non-negative; the kernel only
            walks forward through CPM topo order, so negative offsets
            are not supported.

        Raises
        ------
        ValueError
            If ``hours`` is negative.
        """
        if hours < 0:
            raise ValueError(
                f"Calendar.add_working_hours: hours must be non-negative, got {hours}"
            )
        if hours == 0:
            return start

        cursor = self.next_working_time(start)
        # Working-hours → elapsed-minutes conversion accounts for
        # working_minutes_per_hour (default 60 → identity).
        remaining_minutes = hours * self.working_minutes_per_hour

        # Floating-point tolerance: 1 microsecond worth of minutes.
        eps_minutes = 1e-9

        while remaining_minutes > eps_minutes:
            _, day_end = self._work_window(cursor.date())
            available_minutes = (day_end - cursor).total_seconds() / 60.0
            if remaining_minutes <= available_minutes + eps_minutes:
                return cursor + timedelta(minutes=remaining_minutes)
            remaining_minutes -= available_minutes
            next_date = cursor.date() + timedelta(days=1)
            while not self._is_working_day(next_date):
                next_date += timedelta(days=1)
            cursor = self._work_window(next_date)[0]

        return cursor

    def diff_working_hours(self, start: datetime, end: datetime) -> float:
        """Working hours between ``start`` and ``end``.

        Result is non-negative when ``end >= start``; the sign flips
        symmetrically when ``end < start``. Datetimes outside working
        windows contribute zero — the function measures only the overlap
        between ``[start, end)`` and the configured working windows.

        For the default 60.0 ``working_minutes_per_hour`` this returns
        elapsed working hours; for other values, returns
        ``elapsed_working_minutes / working_minutes_per_hour``.
        """
        if start == end:
            return 0.0
        if start > end:
            return -self.diff_working_hours(end, start)

        total_minutes = 0.0
        current_date = start.date()
        end_date = end.date()
        while current_date <= end_date:
            if self._is_working_day(current_date):
                day_start, day_end = self._work_window(current_date)
                window_start = max(start, day_start)
                window_end = min(end, day_end)
                if window_end > window_start:
                    total_minutes += (window_end - window_start).total_seconds() / 60.0
            current_date += timedelta(days=1)

        return total_minutes / self.working_minutes_per_hour

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _is_working_day(self, d: date) -> bool:
        if d.weekday() >= self.working_days_per_week:
            return False
        if d in self.holidays:
            return False
        return True

    def _work_window(self, d: date) -> tuple[datetime, datetime]:
        """Half-open ``[start, end)`` working window for ``d``."""
        midnight = datetime.combine(d, time(0))
        start_dt = midnight + timedelta(hours=self.work_day_start_hour)
        end_dt = midnight + timedelta(
            hours=self.work_day_start_hour + self.working_hours_per_day
        )
        return start_dt, end_dt


# ----------------------------------------------------------------------
# Builder
# ----------------------------------------------------------------------

#: NONWORK date column candidates, in priority order. Different XER
#: exporters use slightly different field names for the holiday date;
#: the first match wins.
_NONWORK_DATE_COLUMNS: tuple[str, ...] = ("nonwork_date", "start_date", "date")


def build_default_calendar(tables: dict[str, pd.DataFrame]) -> Calendar:
    """Build the project-default :class:`Calendar` from XER tables.

    Selection rule
    --------------
    The row in ``CALENDAR`` with ``default_flag == 'Y'`` is the project
    default. If more than one row has ``default_flag == 'Y'``, the first
    encountered wins (with a warning logged listing all candidates). If
    none has the flag set, the first ``CALENDAR`` row is used (with a
    warning). If ``CALENDAR`` is missing or empty, falls back to the
    hardcoded :class:`Calendar` defaults (8h/day, 5d/week, no holidays)
    and logs a warning.

    Holidays
    --------
    If a ``NONWORK`` table is present, rows whose ``clndr_id`` matches
    the chosen calendar's id contribute their dates to
    :attr:`Calendar.holidays`. Rows for other calendars are ignored
    during beta.

    Parameters
    ----------
    tables : dict[str, pandas.DataFrame]
        Output of :func:`src.sra.cpm.xer_reader.parse_xer`.

    Returns
    -------
    Calendar
        Populated calendar instance.
    """
    calendar_df = tables.get("CALENDAR")
    if calendar_df is None or calendar_df.empty:
        logger.warning(
            "CALENDAR table missing or empty; using default Calendar "
            "(8h/day, 5d/week, no holidays)"
        )
        return Calendar()

    default_mask = calendar_df["default_flag"].astype(str).str.upper().str.strip() == "Y"
    default_rows = calendar_df[default_mask]

    if len(default_rows) > 1:
        names = list(default_rows.get("clndr_name", pd.Series(dtype=str)).astype(str))
        logger.warning(
            "Multiple CALENDAR rows have default_flag='Y' (%d candidates: %s); "
            "first wins",
            len(default_rows),
            names,
        )
        chosen = default_rows.iloc[0]
    elif len(default_rows) == 1:
        chosen = default_rows.iloc[0]
    else:
        logger.warning(
            "No CALENDAR row has default_flag='Y'; falling back to first row"
        )
        chosen = calendar_df.iloc[0]

    day_hr = _safe_positive_float(chosen.get("day_hr_cnt"), default=8.0)
    week_hr = _safe_positive_float(chosen.get("week_hr_cnt"), default=day_hr * 5.0)
    days_per_week = max(1, min(7, int(round(week_hr / day_hr)))) if day_hr > 0 else 5

    holidays = _holidays_for_calendar(tables, chosen.get("clndr_id"))

    return Calendar(
        working_hours_per_day=day_hr,
        working_days_per_week=days_per_week,
        holidays=holidays,
    )


def _safe_positive_float(value: object, *, default: float) -> float:
    """Coerce ``value`` to a positive float; fall back to ``default`` otherwise."""
    if value is None or pd.isna(value):
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f <= 0:
        return default
    return f


def _holidays_for_calendar(
    tables: dict[str, pd.DataFrame], clndr_id: object
) -> frozenset:
    """Extract ``NONWORK`` dates for the chosen calendar id.

    Returns an empty frozenset if the ``NONWORK`` table is absent or
    contributes no dates.
    """
    nonwork_df = tables.get("NONWORK")
    if nonwork_df is None or nonwork_df.empty:
        return frozenset()
    if clndr_id is None or pd.isna(clndr_id):
        return frozenset()
    if "clndr_id" not in nonwork_df.columns:
        return frozenset()

    relevant = nonwork_df[nonwork_df["clndr_id"] == clndr_id]
    if relevant.empty:
        return frozenset()

    date_col = next(
        (c for c in _NONWORK_DATE_COLUMNS if c in relevant.columns), None
    )
    if date_col is None:
        return frozenset()

    parsed = pd.to_datetime(relevant[date_col], errors="coerce").dropna()
    if parsed.empty:
        return frozenset()
    return frozenset(parsed.dt.date.tolist())
