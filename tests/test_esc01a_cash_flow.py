"""ESC-01 part A: financial-year phasing of cost.

GN4-23/32 wants escalation applied to a financial-year cash flow, and the product had no such
thing. This is that cash flow. It escalates nothing - part B does, and waits on §5.2.

**The fixture cannot exercise the central case, and that is stated rather than worked around.**
The committed wind schedule runs 2026-03-02 to 2026-04-17 - six weeks, entirely inside one
Australian financial year. So the real register can show the plumbing but not multi-year phasing,
and the arithmetic is pinned on constructed windows that span years. A suite that only ran the
fixture would report green while the thing the module exists for went untested.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from src.cash_flow import (
    BASIS_PROFILE,
    BASIS_SCHEDULE,
    UNSCHEDULED_PROFILE,
    activity_windows_from_xer,
    financial_year,
    financial_years_between,
    phase_costs,
    spread_across,
)

REPO = Path(__file__).resolve().parents[1]
WIND_XER = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_schedule.xer"
D = _dt.date


class TestTheFinancialYearBoundary:
    """1 July, and the day either side of it. The convention is Commonwealth (GN4's
    jurisdiction), so the boundary is where an off-by-one would put a whole year's spend in the
    wrong year - and be invisible on a project that happens to sit mid-year."""

    @pytest.mark.parametrize("day, expected", [
        (D(2026, 6, 30), "FY2025-26"),
        (D(2026, 7, 1), "FY2026-27"),
        (D(2026, 12, 31), "FY2026-27"),
        (D(2027, 1, 1), "FY2026-27"),
        (D(2027, 6, 30), "FY2026-27"),
        (D(2027, 7, 1), "FY2027-28"),
    ])
    def test_the_day_lands_in_the_right_year(self, day: _dt.date, expected: str):
        assert financial_year(day) == expected

    def test_a_window_enumerates_every_year_it_touches(self):
        years = financial_years_between(D(2026, 5, 1), D(2028, 8, 1))
        assert years == ["FY2025-26", "FY2026-27", "FY2027-28", "FY2028-29"]

    def test_a_window_inside_one_year_yields_one_year(self):
        assert financial_years_between(D(2026, 8, 1), D(2027, 5, 1)) == ["FY2026-27"]

    def test_a_backwards_window_is_refused_not_silently_reordered(self):
        """Swapped dates are a caller bug. Sorting them would produce a plausible cash flow from
        a wrong input, which is the failure mode this repository keeps finding."""
        with pytest.raises(ValueError, match="ends before it starts"):
            financial_years_between(D(2027, 1, 1), D(2026, 1, 1))


class TestTheSpreadIsWeightedByDays:
    def test_a_window_wholly_inside_one_year_is_not_split(self):
        out = spread_across(1_000_000.0, D(2026, 8, 1), D(2026, 9, 30))
        assert out == {"FY2026-27": 1_000_000.0}

    def test_a_window_straddling_the_boundary_splits_by_days_not_evenly(self):
        """Ten days, of which two fall before 1 July. An even split across the two years would
        put half the money in a year that saw a fifth of the work."""
        out = spread_across(1_000.0, D(2026, 6, 29), D(2026, 7, 8))
        assert out["FY2025-26"] == pytest.approx(1_000.0 * 2 / 10)
        assert out["FY2026-27"] == pytest.approx(1_000.0 * 8 / 10)

    def test_nothing_is_lost_or_created_across_a_multi_year_spread(self):
        """The property that matters most: a cash flow that does not sum to the cost it phased
        is worse than no cash flow, because it looks like an answer."""
        out = spread_across(7_654_321.0, D(2025, 3, 1), D(2028, 11, 30))
        assert sum(out.values()) == pytest.approx(7_654_321.0)
        # Five years, not four: Mar-Jun 2025 is FY2024-25 and Jul-Nov 2028 is FY2028-29, so the
        # window touches a part-year at each end. The Builder first wrote 4 by counting whole
        # years - the sum assertion above is the one that would have caught a real defect.
        assert len(out) == 5

    def test_a_single_day_window_is_a_real_case_not_an_error(self):
        """A milestone payment lands on one day. Dividing by a zero-length window would raise."""
        assert spread_across(500.0, D(2026, 9, 9), D(2026, 9, 9)) == {"FY2026-27": 500.0}


class TestTheRuledPhasingBasis:
    """Director ruling 06/09/2026: schedule-linked cost is phased from its activity; everything
    else is spread on a stated profile, because 71% of priced risks have no activity and the
    Layer-1 base has no WBS join to the schedule at all."""

    AMOUNTS = {"WT-001": 100.0, "WT-002": 100.0, "cost-only": 100.0, "base-bucket": 700.0}
    WINDOWS = {
        "WT-001": (D(2026, 8, 1), D(2026, 8, 31)),
        "WT-002": (D(2027, 8, 1), D(2027, 8, 31)),
    }
    PROGRAMME = (D(2026, 7, 1), D(2028, 6, 30))

    def _phased(self):
        return phase_costs(amounts=self.AMOUNTS, activity_windows=self.WINDOWS,
                           programme_window=self.PROGRAMME)

    def test_scheduled_buckets_land_in_their_activitys_year(self):
        p = self._phased()
        assert p.basis_by_bucket["WT-001"] == BASIS_SCHEDULE
        assert p.basis_by_bucket["WT-002"] == BASIS_SCHEDULE

        # Asserted on the scheduled buckets ALONE, so the profile spread cannot mask the
        # answer. The first version compared the two years in the COMBINED figure with a
        # "> other - 1e9" slack, which is true of any two numbers - a check that could not
        # fail, written into the very suite whose job is catching those.
        only_scheduled = phase_costs(
            amounts={"WT-001": 100.0, "WT-002": 100.0},
            activity_windows=self.WINDOWS, programme_window=self.PROGRAMME)
        assert only_scheduled.by_financial_year == {
            "FY2026-27": pytest.approx(100.0),   # August 2026, from WT-001's activity
            "FY2027-28": pytest.approx(100.0),   # August 2027, from WT-002's
        }

    def test_unscheduled_buckets_fall_to_the_profile_and_SAY_SO(self):
        """The basis is recorded per bucket, because a reader cannot judge escalation applied to
        an assumed profile unless they can see which costs were assumed."""
        p = self._phased()
        assert p.basis_by_bucket["cost-only"] == BASIS_PROFILE
        assert p.basis_by_bucket["base-bucket"] == BASIS_PROFILE
        assert p.unscheduled_profile == UNSCHEDULED_PROFILE

    def test_the_scheduled_share_is_weighted_by_DOLLARS_not_by_bucket_count(self):
        """**The correction the ESC-01 numerics review forced.** This fixture is the defect in
        miniature: two of four buckets are schedule-phased, so counting buckets reports 50%
        derived - but those two carry $200 of $1,000, so the honest figure is 20%. On the real
        register the gap is wider still, because the Layer-1 base is one bucket holding most of
        the money. A disclosure that overstates rigour by an order of magnitude is worse than
        none, because a reader trusts it."""
        p = self._phased()
        assert p.scheduled_share == pytest.approx(0.2)
        assert p.scheduled_share_is_by_value is True

        by_count = sum(1 for b in p.basis_by_bucket.values() if b == BASIS_SCHEDULE)
        assert by_count / len(p.basis_by_bucket) == pytest.approx(0.5), (
            "the count measure no longer diverges from the value measure, so this fixture has "
            "stopped demonstrating why the distinction matters")

    def test_a_hand_built_cash_flow_says_its_share_is_NOT_by_value(self):
        """The fallback is visible rather than silent. A `PhasedCost` assembled without amounts
        can still report a share, but a deliverable must be able to tell which measure it has."""
        from src.cash_flow import PhasedCost

        p = PhasedCost(by_financial_year={"FY2026-27": 1.0},
                       basis_by_bucket={"a": BASIS_SCHEDULE, "b": BASIS_PROFILE})
        assert p.scheduled_share == pytest.approx(0.5)
        assert p.scheduled_share_is_by_value is False

    def test_every_dollar_is_phased_exactly_once(self):
        p = self._phased()
        assert p.total == pytest.approx(sum(self.AMOUNTS.values()))
        assert set(p.basis_by_bucket) == set(self.AMOUNTS)

    def test_the_years_come_out_in_order(self):
        """A cash-flow table out of chronological order is read wrong before it is read at all."""
        years = list(self._phased().by_financial_year)
        assert years == sorted(years)


class TestAgainstTheRealSchedule:
    @pytest.mark.integration
    def test_gating_activities_resolve_to_real_windows(self):
        """The plumbing, on the committed fixture: the register's `Mapping` gating ids must
        actually name activities in the .xer."""
        from src.sra.cpm.xer_reader import parse_xer

        if not WIND_XER.is_file():
            pytest.skip("wind fixture absent")
        tasks = parse_xer(str(WIND_XER))["TASK"]
        windows = activity_windows_from_xer(tasks, {"WT-001": "20.G.001", "WT-002": "10.G.001"})
        assert set(windows) == {"WT-001", "WT-002"}
        for start, end in windows.values():
            assert start <= end

    @pytest.mark.integration
    def test_an_unknown_gating_id_is_skipped_not_guessed(self):
        """A gating id naming no activity must drop the bucket to the profile, visibly - never
        attach it to some other activity's window."""
        from src.sra.cpm.xer_reader import parse_xer

        if not WIND_XER.is_file():
            pytest.skip("wind fixture absent")
        tasks = parse_xer(str(WIND_XER))["TASK"]
        windows = activity_windows_from_xer(tasks, {"WT-999": "NO.SUCH.ACTIVITY"})
        assert windows == {}

    @pytest.mark.integration
    def test_the_fixture_spans_one_financial_year_which_is_why_the_unit_cases_exist(self):
        """Named as a test so the limitation cannot be forgotten. The committed schedule runs
        six weeks; if it ever spans a boundary this reds, and the multi-year cases above stop
        being the only coverage of the module's central behaviour."""
        from src.sra.cpm.xer_reader import parse_xer

        if not WIND_XER.is_file():
            pytest.skip("wind fixture absent")
        tasks = parse_xer(str(WIND_XER))["TASK"]
        start = min(t.date() for t in tasks["early_start_date"] if t is not None)
        end = max(t.date() for t in tasks["early_end_date"] if t is not None)
        assert financial_years_between(start, end) == [financial_year(start)], (
            "the wind schedule now spans a financial-year boundary - good; fold it into the "
            "phasing coverage above rather than leaving the constructed windows as the only "
            "multi-year test")


def test_this_module_escalates_nothing():
    """ESC-01 part A is the cash flow; part B is escalation and waits on §5.2. Asserted on code
    shape, per the guard convention - the docstrings here discuss escalation constantly, so
    matching the word would match this very file."""
    import re

    source = (REPO / "src" / "cash_flow.py").read_text(encoding="utf-8")
    assert not re.search(
        r"def\s+\w*escalat|escalation_\w+\s*=|apply_escalat|escalate\s*\(", source, re.I), (
        "src/cash_flow.py computes escalation; part A is the cash flow only")
