/**
 * Is the period on screen current, late, or stale?
 *
 * Stage 7 part C (B-3), ruled 05/09/2026. Until now nothing compared `period_end_date` to today,
 * so a dashboard served last month's numbers as current indefinitely and silently.
 *
 * **Two signals, not one - which is the whole of the ruling.** The first draft of the brief
 * offered SPEC §5's "about seven working days from period end to a refreshed dashboard" as a
 * staleness threshold. It is not: that is the **production SLA**, how long making a period takes
 * after the period closes. §5's cadence is **monthly**, so a period published nine days after
 * period end is on time, and a "stale" badge at the SLA would fire on every correctly-running
 * month and be learned as noise. A warning that fires on the normal case is not a warning.
 *
 *   LATE  = `period_end + SLA` has passed with nothing newer published.
 *   STALE = `period_end + one cycle + SLA` has passed - a whole period has been skipped.
 *
 * **The cycle is measured, not declared.** The contract already carries `period_end_date` and
 * `previous_period_end_date`, so the gap between them IS the observed cycle length: monthly
 * against quarterly costs no contract change and no configuration. Only the SLA is a genuine
 * constant. With no previous period there is nothing to measure, so STALE cannot be computed and
 * is not guessed - the first period of a project reports LATE only.
 *
 * **LATE is specialist-only** (ruled): it is a report on the specialist's own delivery, on a page
 * the client may show their board. `AppFooter` places it in the Analyst view. That is placement,
 * not access control - the PM/Analyst split is a client-side toggle over public static routes -
 * and the running record says so rather than implying otherwise.
 */

/** SPEC §5: about seven working days from period end to a refreshed dashboard. */
export const SLA_WORKING_DAYS = 7;

/**
 * Slack on the ESTIMATED date of the next period end, in calendar days.
 *
 * The cycle is measured from one prior interval, and calendar months vary from 28 to 31 days.
 * A January-to-February gap therefore measures 28 and under-estimates the February-to-March gap
 * by three, so an estimate with no allowance predicts the next period's due date up to three
 * days early - and STALE, which is shown to the CLIENT and says a further period is overdue,
 * would fire while the specialist is still inside their SLA.
 *
 * Erring late is the safe direction for this signal: a stale badge a few days late tells nobody
 * anything false, while one a few days early tells a client their specialist is behind when
 * they are not. Three days is the largest month-length difference, so it is exactly the error
 * being covered rather than a round number chosen for comfort.
 */
export const MONTH_LENGTH_SLACK_DAYS = 3;

export type Freshness =
  | { kind: "current" }
  | { kind: "late"; workingDaysOverdue: number }
  | { kind: "stale"; daysSincePeriodEnd: number; cycleDays: number };

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/**
 * Working days between two dates, counting Mon-Fri and ignoring public holidays.
 *
 * Holidays are deliberately not modelled: they are jurisdiction-specific, the engine does not
 * carry a calendar for them, and inventing one here would put a second, silently different
 * calendar beside the schedule engine's. The effect is that both signals can fire up to a few
 * days early around a holiday period.
 */
export function workingDaysBetween(from: Date, to: Date): number {
  if (to <= from) return 0;
  let count = 0;
  const cursor = new Date(from.getTime());
  cursor.setHours(0, 0, 0, 0);
  const end = new Date(to.getTime());
  end.setHours(0, 0, 0, 0);
  while (cursor < end) {
    cursor.setDate(cursor.getDate() + 1);
    const day = cursor.getDay();
    if (day !== 0 && day !== 6) count += 1;
  }
  return count;
}

function parseIsoDate(iso: string): Date | null {
  // Parsed as LOCAL midnight, not UTC. `new Date("2026-02-28")` is UTC midnight, which in a
  // timezone behind UTC is the previous local day - so a period would read as a day older than
  // it is, and near a threshold that flips the badge.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Calendar days added to a date, via date arithmetic so DST cannot shift the result. */
function addDays(from: Date, days: number): Date {
  const d = new Date(from.getTime());
  d.setDate(d.getDate() + days);
  d.setHours(0, 0, 0, 0);
  return d;
}

/**
 * Classify the displayed period against today.
 *
 * `now` is injected rather than read from the clock so the thresholds are testable at all: a
 * function that calls `new Date()` internally can only be tested on the day the test runs.
 *
 * **Both signals are measured in WORKING days, against the SAME SLA.** The first version
 * expressed STALE in calendar days - converting the seven-working-day SLA to `ceil(7 * 7/5) = 10`
 * calendar days - while LATE used working days. Mixing the two units made STALE fire *before*
 * LATE would have on the same project: with a 28-day observed cycle, a period ending 28
 * February went stale on 7 April, when the 31 March period was five working days old and well
 * inside its SLA. The dashboard told every viewer a further period was overdue while the
 * specialist was on time - the exact fire-on-a-correct-month defect the two-signal ruling exists
 * to remove. Found by the part C numerics review.
 *
 * STALE now asks one question in the same terms LATE does: **is the NEXT period itself overdue?**
 */
export function assessFreshness(
  periodEndDate: string,
  previousPeriodEndDate: string | null,
  now: Date,
): Freshness {
  const end = parseIsoDate(periodEndDate);
  if (end === null) return { kind: "current" };

  const overdue = workingDaysBetween(end, now) - SLA_WORKING_DAYS;
  if (overdue <= 0) return { kind: "current" };

  const previous = previousPeriodEndDate ? parseIsoDate(previousPeriodEndDate) : null;
  if (previous !== null) {
    const cycleDays = Math.round((end.getTime() - previous.getTime()) / MS_PER_DAY);
    if (cycleDays > 0) {
      // When the next period was due, estimated from the observed cycle and allowed to be a
      // few days later than the estimate (see MONTH_LENGTH_SLACK_DAYS).
      const nextDue = addDays(end, cycleDays + MONTH_LENGTH_SLACK_DAYS);
      // The same test LATE applies, one period forward: a whole period has been skipped only
      // once that next period is ITSELF past its SLA.
      if (workingDaysBetween(nextDue, now) > SLA_WORKING_DAYS) {
        const daysSince = Math.round((now.getTime() - end.getTime()) / MS_PER_DAY);
        return { kind: "stale", daysSincePeriodEnd: daysSince, cycleDays };
      }
    }
  }

  return { kind: "late", workingDaysOverdue: overdue };
}
