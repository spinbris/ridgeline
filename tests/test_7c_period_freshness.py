"""Stage 7 part C (B-3): the staleness thresholds, executed rather than read.

`dashboard/lib/periodFreshness.ts` carries the arithmetic behind the 05/09/2026 ruling - SLA
seven working days, STALE at `period_end + cycle + SLA`, cycle measured from the data. It is
client-facing logic that decides whether a reader is told their figures are out of date, so
asserting it by reading the source would not be worth much.

The dashboard has no test harness (that is D-2, part D, and it needs jsdom or a headless browser
for rendering). But `assessFreshness` is a **pure function**: it needs a JS runtime, not a DOM.
So this compiles that one module with the TypeScript already in `dashboard/node_modules` and runs
the cases in node - a far smaller thing than D-2's harness, and it means the ruling's numbers are
checked now rather than at the end of the stage.

Skips when node is absent, so a fresh clone without `npm install` is not redded by it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DASHBOARD = REPO / "dashboard"
SOURCE = DASHBOARD / "lib" / "periodFreshness.ts"

_NODE = shutil.which("node")
_TSC = DASHBOARD / "node_modules" / "typescript" / "bin" / "tsc"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(_NODE is None, reason="node is not on PATH"),
    pytest.mark.skipif(not _TSC.is_file(), reason="dashboard/node_modules is not installed"),
]


@pytest.fixture(scope="module")
def freshness(tmp_path_factory: pytest.TempPathFactory):
    """Compile the module once and return a callable that evaluates cases in node."""
    out = tmp_path_factory.mktemp("freshness_js")
    compiled = subprocess.run(
        [_NODE, str(_TSC), str(SOURCE), "--outDir", str(out),
         "--module", "commonjs", "--target", "es2020", "--skipLibCheck"],
        capture_output=True, text=True,
    )
    assert compiled.returncode == 0, f"tsc failed:\n{compiled.stdout}\n{compiled.stderr}"
    module = (out / "periodFreshness.js").as_posix()

    def _assess(period_end: str, previous: str | None, now: str):
        script = textwrap.dedent(f"""
            const m = require({json.dumps(module)});
            const [y, mo, d] = {json.dumps(now)}.split("-").map(Number);
            const now = new Date(y, mo - 1, d);
            const r = m.assessFreshness(
                {json.dumps(period_end)}, {json.dumps(previous)}, now);
            process.stdout.write(JSON.stringify(r));
        """)
        # TZ is PINNED. Node inherits the host zone, and `Math.round` over a DST-
        # straddling difference behaves differently either side of a transition - so an
        # unpinned suite proves something about this machine rather than about the code,
        # which is exactly what the repository's lane rules reject. Europe/London is
        # chosen because it HAS DST, so the quarterly cases actually straddle a
        # transition rather than avoiding the question.
        env = {**os.environ, "TZ": "Europe/London"}
        proc = subprocess.run(
            [_NODE, "-e", script], capture_output=True, text=True, env=env)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    def _assess_at(period_end: str, previous: str | None, now: str, hhmm: str):
        hh, mm = hhmm.split(":")
        script = textwrap.dedent(f"""
            const m = require({json.dumps(module)});
            const [y, mo, d] = {json.dumps(now)}.split("-").map(Number);
            const now = new Date(y, mo - 1, d, {int(hh)}, {int(mm)});
            const r = m.assessFreshness(
                {json.dumps(period_end)}, {json.dumps(previous)}, now);
            process.stdout.write(JSON.stringify(r));
        """)
        env = {**os.environ, "TZ": "Europe/London"}
        proc = subprocess.run(
            [_NODE, "-e", script], capture_output=True, text=True, env=env)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    _assess.at = _assess_at  # type: ignore[attr-defined]
    return _assess


@pytest.fixture(scope="module")
def freshness_at(freshness):
    """`freshness`, but with a time of day - so the clock cannot be assumed to be midnight."""
    return freshness.at


class TestTheSlaBoundaryIsPinned:
    """LATE turns on at a specific day, so the tests name that day and its neighbour.

    The first version of this module sampled 5 working days against an SLA of 7, and 11 against
    7 - green under an off-by-one in either direction. The part C review's second blocker was
    exactly that: a suite that samples far from every boundary pins none of them, so its pass is
    not evidence for the arithmetic.

    28 Feb 2026 is a Saturday. Working days from it: Mar 2, 3, 4, 5, 6, 9, 10 is seven, so
    10 March is the last on-time day and 11 March is the first late one.
    """

    def test_the_last_on_time_day_is_current(self, freshness):
        assert freshness("2026-02-28", "2026-01-31", "2026-03-10")["kind"] == "current"

    def test_the_very_next_day_is_late(self, freshness):
        assessed = freshness("2026-02-28", "2026-01-31", "2026-03-11")
        assert assessed["kind"] == "late"
        assert assessed["workingDaysOverdue"] == 1


class TestStaleCannotFireOnACorrectlyRunningEngagement:
    """The part C review's BLOCKER, as a regression test.

    The first version converted the seven-WORKING-day SLA into `ceil(7 * 7/5) = 10` CALENDAR
    days for the STALE comparison while LATE stayed in working days. With a 28-day observed
    cycle (31 Jan -> 28 Feb), a period ending 28 February went stale on **7 April** - a day on
    which the 31 March period was five working days old and comfortably inside its own SLA. The
    dashboard told every viewer a further period was overdue while the specialist was on time.

    The 30 -> 31 day boundary is where it bites, so that is the case pinned here.
    """

    def test_it_is_not_stale_while_the_next_period_is_still_inside_its_sla(self, freshness):
        # 31 Mar 2026 is a Tuesday; its seventh working day is 9 April, so the March period is
        # on time up to and including 9 April. The February period must not be called stale
        # before then - and under the old arithmetic it was, on 7 April.
        for day in ("2026-04-07", "2026-04-08", "2026-04-09"):
            assessed = freshness("2026-02-28", "2026-01-31", day)
            assert assessed["kind"] != "stale", (
                f"stale on {day}, while the 31 March period is still within its SLA")

    def test_it_goes_stale_once_the_next_period_is_ITSELF_late(self, freshness):
        assessed = freshness("2026-02-28", "2026-01-31", "2026-04-10")
        assert assessed["kind"] == "stale"
        assert assessed["cycleDays"] == 28

    def test_a_31_day_cycle_behaves_the_same_way(self, freshness):
        """The other direction: a longer observed cycle must not delay STALE indefinitely."""
        # 31 Jan 2026 -> 28 Feb is 28 days; 31 Dec -> 31 Jan is 31.
        assert freshness("2026-01-31", "2025-12-31", "2026-03-10")["kind"] != "stale"
        assert freshness("2026-01-31", "2025-12-31", "2026-03-20")["kind"] == "stale"


class TestTheCycleIsMeasuredNotDeclared:
    """The contract already carries `previous_period_end_date`, so the gap between the two dates
    IS the cycle. Monthly against quarterly therefore costs no contract change and no config."""

    def test_a_quarterly_engagement_is_not_stale_on_a_monthly_threshold(self, freshness):
        """What a hardcoded 30-day constant would get wrong, every quarter, on a correctly-
        running engagement."""
        assert freshness("2026-03-31", "2025-12-31", "2026-05-01")["kind"] == "late"

    def test_a_quarterly_engagement_still_goes_stale_eventually(self, freshness):
        stale = freshness("2026-03-31", "2025-12-31", "2026-07-20")
        assert stale["kind"] == "stale"
        assert stale["cycleDays"] == 90

    def test_the_first_period_reports_late_but_never_stale(self, freshness):
        """With no previous period there is nothing to measure. Guessing a cycle would put a
        made-up number in front of a client on the first period of an engagement."""
        assert freshness("2026-01-31", None, "2026-06-01")["kind"] == "late"


class TestBothSignalsUseOneUnit:
    """The root cause of the blocker was two units, not one wrong number. This pins the property
    rather than the instance: STALE must never precede the point at which a NEXT period, on the
    observed cycle, would itself be reported late."""

    def test_stale_never_precedes_the_next_periods_own_lateness(self, freshness):
        import datetime as _d

        for period_end, previous in (
            ("2026-02-28", "2026-01-31"),
            ("2026-01-31", "2025-12-31"),
            ("2026-04-30", "2026-03-31"),
            ("2026-09-30", "2026-08-31"),
        ):
            end = _d.date.fromisoformat(period_end)
            cycle = (end - _d.date.fromisoformat(previous)).days
            first_stale = None
            for offset in range(1, 200):
                day = end + _d.timedelta(days=offset)
                if freshness(period_end, previous, day.isoformat())["kind"] == "stale":
                    first_stale = day
                    break
            assert first_stale is not None, f"{period_end} never goes stale"

            # The next period, on the observed cycle plus the month-length allowance, would be
            # reported late from this day onward. STALE must not arrive before it.
            next_due = end + _d.timedelta(days=cycle + 3)
            working = 0
            cursor = next_due
            while working <= 7:
                cursor += _d.timedelta(days=1)
                if cursor.weekday() < 5:
                    working += 1
            assert first_stale >= cursor, (
                f"{period_end}: stale on {first_stale}, before the next period would be late "
                f"({cursor})")


class TestTheClockTimeOfDayCannotMoveTheBadge:
    """The one single-line change to the module the first suite did not catch.

    Production passes a wall-clock `new Date()`, but every test case here builds `now` at local
    midnight - so deleting the `setHours(0, 0, 0, 0)` normalisation inside `workingDaysBetween`
    would leave the suite green while both signals fired a day early for every viewer after
    midnight. Named by the part C re-review.

    These evaluate the SAME calendar day at three times of day and require one answer.
    """

    @pytest.mark.parametrize("hhmm", ["00:30", "12:00", "23:30"])
    def test_the_verdict_does_not_change_within_a_day(self, freshness_at, hhmm: str):
        # 10 March is the last on-time day for a 28 February period end.
        assert freshness_at("2026-02-28", "2026-01-31", "2026-03-10", hhmm)["kind"] == "current"

    @pytest.mark.parametrize("hhmm", ["00:30", "12:00", "23:30"])
    def test_the_first_late_day_is_late_all_day(self, freshness_at, hhmm: str):
        assert freshness_at("2026-02-28", "2026-01-31", "2026-03-11", hhmm)["kind"] == "late"


class TestEdges:
    def test_a_malformed_date_does_not_produce_a_warning(self, freshness):
        """Fail toward silence here, not toward alarm: a badge that fires because a date could
        not be parsed tells the reader something false about their figures."""
        assert freshness("not-a-date", None, "2026-06-01")["kind"] == "current"

    def test_a_future_period_end_is_current(self, freshness):
        assert freshness("2026-12-31", "2026-11-30", "2026-06-01")["kind"] == "current"

    def test_a_zero_length_cycle_cannot_make_everything_stale(self, freshness):
        """Two periods sharing an end date would give a cycle of 0, and a next-due date equal to
        the period end - which without the guard would call every late period stale."""
        assert freshness("2026-02-28", "2026-02-28", "2026-03-20")["kind"] == "late"
