"""Financial-year phasing of project cost - ESC-01 part A.

**What this is for.** GN4-23/32 requires escalation to be applied as an index ratio to a
**financial-year cash flow**. The product had no such thing: costs are per-risk and per-WBS, the
schedule is per-activity, and nothing joined them. This module is that join. It computes **when**
cost falls; it does not escalate anything, and deliberately contains no escalation arithmetic -
that is ESC-01 part B and waits on the brief's §5.2.

**The phasing basis, ruled 06/09/2026 by the Director**, after measurement showed the obvious
reading was insufficient:

* Risks that **drive a schedule activity** are phased from that activity's window. On the wind
  register that is **10 of 35 priced risks**.
* Everything else - the other **25 cost-only risks (71%)** and the **whole Layer-1 base**, which
  is the larger number - has no activity to phase from and is spread across the programme window
  on a **stated profile**.

Why the second half exists at all: the schedule's WBS codes are `WF, 10, 20 ... 60` while the
Layer-1 base rows are prose labels (`Turbine supply`, `BOP civils`), and **nothing in the register
or the .xer joins them**. The `Mapping` sheet maps risk to activity, not WBS to WBS. Inventing that
join would have been the Builder deciding what the escalated number means.

**The profile is straight-line, and that is a claim about honesty rather than realism.** A real
project spends on an S-curve. But nobody has elicited that curve for these buckets, and an S-curve
asserts a shape no one supplied, whereas a straight line asserts only "we do not know when within
the programme". The profile is **named in the output** so the deliverable discloses it, and so a
different one can be added as a choice rather than a code change.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Iterable, Mapping

#: The Australian Commonwealth financial year: 1 July to 30 June. Stated rather than assumed,
#: because GN4 is Commonwealth guidance and the convention is jurisdictional - a product used
#: elsewhere would need a different one, and it should be visible where that would have to change.
FY_START_MONTH = 7

#: The profile applied to cost with no activity. See the module docstring.
UNSCHEDULED_PROFILE = "straight-line across the programme window"

#: How a bucket got its dates, carried per bucket so the deliverable can show it.
BASIS_SCHEDULE = "schedule"
BASIS_PROFILE = "programme profile"


def financial_year(day: _dt.date) -> str:
    """`FY2026-27` for any day from 1 July 2026 to 30 June 2027."""
    start = day.year if day.month >= FY_START_MONTH else day.year - 1
    return f"FY{start}-{str(start + 1)[-2:]}"


def financial_years_between(start: _dt.date, end: _dt.date) -> list[str]:
    """Every financial year the window touches, in order, inclusive of both ends."""
    if end < start:
        raise ValueError(f"window ends before it starts: {start} -> {end}")
    years, cursor = [], start
    while cursor <= end:
        fy = financial_year(cursor)
        if fy not in years:
            years.append(fy)
        boundary = _dt.date(
            cursor.year + (1 if cursor.month >= FY_START_MONTH else 0), FY_START_MONTH, 1)
        cursor = boundary
    return years


def _overlap_days(a_start: _dt.date, a_end: _dt.date,
                  b_start: _dt.date, b_end: _dt.date) -> int:
    """Inclusive day count where two windows overlap; 0 when they do not."""
    lo, hi = max(a_start, b_start), min(a_end, b_end)
    return (hi - lo).days + 1 if hi >= lo else 0


def spread_across(amount: float, start: _dt.date, end: _dt.date) -> dict[str, float]:
    """Straight-line spread of ``amount`` over a window, by financial year.

    Weighted by **days of overlap**, so a window that sits mostly in one year puts most of the
    money there. A same-day window puts all of it in that day's year rather than dividing by
    zero - a single-day cost is a real case (a milestone payment), not an edge to guard against.
    """
    if end < start:
        raise ValueError(f"window ends before it starts: {start} -> {end}")
    total_days = (end - start).days + 1
    out: dict[str, float] = {}
    for fy in financial_years_between(start, end):
        fy_start_year = int(fy[2:6])
        fy_start = _dt.date(fy_start_year, FY_START_MONTH, 1)
        fy_end = _dt.date(fy_start_year + 1, FY_START_MONTH, 1) - _dt.timedelta(days=1)
        days = _overlap_days(start, end, fy_start, fy_end)
        if days:
            out[fy] = out.get(fy, 0.0) + amount * days / total_days
    return out


@dataclass(frozen=True)
class PhasedCost:
    """A cash flow, and an account of how each part of it got its dates."""

    by_financial_year: dict[str, float]
    #: bucket name -> BASIS_SCHEDULE or BASIS_PROFILE. The deliverable shows this: a reader who
    #: cannot see which costs were phased from the schedule and which from an assumed profile
    #: cannot judge the escalation that will be applied to them.
    basis_by_bucket: dict[str, str] = field(default_factory=dict)
    #: bucket name -> dollars, so the scheduled share can be weighted by value rather than count.
    amount_by_bucket: dict[str, float] = field(default_factory=dict)
    programme_window: tuple[_dt.date, _dt.date] | None = None
    unscheduled_profile: str = UNSCHEDULED_PROFILE

    @property
    def total(self) -> float:
        return sum(self.by_financial_year.values())

    @property
    def scheduled_share(self) -> float:
        """Fraction **by value** phased from the schedule rather than from the profile.

        Published because it is the honest measure of how much of a cash flow is derived and how
        much is assumed. **Weighted by dollars, not by bucket count**, which is the correction the
        ESC-01 numerics review forced: the Layer-1 base is a single bucket carrying most of the
        money, so counting buckets reported roughly 28% derived on the wind register where the
        dollar figure is a few percent. A disclosure that overstates rigour by an order of
        magnitude is worse than no disclosure, because a reader trusts it.

        Falls back to the count only when no amounts were recorded - a `PhasedCost` built by hand
        in a test - and never silently: `scheduled_share_is_by_value` says which one this is.
        """
        if self.amount_by_bucket:
            total = sum(self.amount_by_bucket.values())
            if total:
                return sum(
                    v for b, v in self.amount_by_bucket.items()
                    if self.basis_by_bucket.get(b) == BASIS_SCHEDULE) / total
        if not self.basis_by_bucket:
            return 0.0
        n = sum(1 for b in self.basis_by_bucket.values() if b == BASIS_SCHEDULE)
        return n / len(self.basis_by_bucket)

    @property
    def scheduled_share_is_by_value(self) -> bool:
        """Whether `scheduled_share` is dollar-weighted. A deliverable quoting the share must say
        which measure it is quoting; the two differ by an order of magnitude on a real register."""
        return bool(self.amount_by_bucket) and bool(sum(self.amount_by_bucket.values()))


def phase_costs(
    *,
    amounts: Mapping[str, float],
    activity_windows: Mapping[str, tuple[_dt.date, _dt.date]],
    programme_window: tuple[_dt.date, _dt.date],
) -> PhasedCost:
    """Phase each named cost bucket into financial years.

    ``amounts`` maps a bucket name to dollars. ``activity_windows`` maps those bucket names that
    drive a schedule activity to that activity's start and end; a bucket absent from it is spread
    across ``programme_window`` on the stated profile.

    The two paths are deliberately the same arithmetic over different windows, so that a bucket
    phased from its activity and one phased from the programme cannot disagree about how a window
    becomes financial years.
    """
    p_start, p_end = programme_window
    by_fy: dict[str, float] = {}
    basis: dict[str, str] = {}

    for bucket, amount in amounts.items():
        window = activity_windows.get(bucket)
        basis[bucket] = BASIS_SCHEDULE if window is not None else BASIS_PROFILE
        start, end = window if window is not None else (p_start, p_end)
        for fy, value in spread_across(float(amount), start, end).items():
            by_fy[fy] = by_fy.get(fy, 0.0) + value

    ordered = {fy: by_fy[fy] for fy in sorted(by_fy)}
    return PhasedCost(
        by_financial_year=ordered,
        basis_by_bucket=basis,
        amount_by_bucket={k: float(v) for k, v in amounts.items()},
        programme_window=(p_start, p_end),
    )


def activity_windows_from_xer(
    task_table, gating_by_bucket: Mapping[str, str]
) -> dict[str, tuple[_dt.date, _dt.date]]:
    """Resolve each bucket's gating activity to its early start/finish window.

    ``gating_by_bucket`` is the register's `Mapping` sheet: risk id -> `Gating_Activity_ID`. A
    gating id that names no activity in the schedule is **skipped, not guessed** - the bucket then
    falls to the programme profile and says so in `basis_by_bucket`, which is visible, rather than
    being silently attached to the wrong window.
    """
    by_code: dict[str, tuple[_dt.date, _dt.date]] = {}
    for row in task_table.itertuples(index=False):
        start, end = getattr(row, "early_start_date", None), getattr(row, "early_end_date", None)
        if start is None or end is None:
            continue
        s = start.date() if hasattr(start, "date") else start
        e = end.date() if hasattr(end, "date") else end
        by_code[str(getattr(row, "task_code"))] = (s, e)

    out: dict[str, tuple[_dt.date, _dt.date]] = {}
    for bucket, activity in gating_by_bucket.items():
        window = by_code.get(str(activity))
        if window is not None:
            out[bucket] = window
    return out
