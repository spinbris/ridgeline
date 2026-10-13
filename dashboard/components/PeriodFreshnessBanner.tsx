/**
 * Says when the period on screen is no longer current.
 *
 * Stage 7 part C (B-3). Before this, nothing compared `period_end_date` to today, so the
 * dashboard served last month's numbers as current indefinitely and silently. The classification
 * and the reasoning behind the two thresholds live in `lib/periodFreshness.ts`.
 *
 * **Who sees which signal, ruled 05/09/2026:**
 *
 * - **STALE is shown to everyone.** A whole period has been skipped, so the figures on the page
 *   are out of date as a matter of fact. Hiding that from the client would be the dashboard
 *   asserting something it knows to be wrong.
 * - **LATE is specialist-only.** It says the current period is overdue - a report on the
 *   specialist's own delivery, on a page a client may put in front of their board. It renders in
 *   the Analyst view only.
 *
 * That second one is **placement, not access control**: the PM/Analyst split is a client-side
 * toggle (`AppHeader`) over public static routes, so anyone holding the URL can click across.
 * Enforcing it would need authentication, which is a new surface and not stage 7's. Recorded here
 * rather than implied, because a reader could otherwise take this for a permission boundary.
 */

"use client";

import { usePathname } from "next/navigation";

import { assessFreshness, SLA_WORKING_DAYS } from "@/lib/periodFreshness";
import { roleFromPathname, usePeriodContext } from "@/lib/PeriodContext";

export function PeriodFreshnessBanner() {
  const { status, availablePeriods } = usePeriodContext();
  const pathname = usePathname();

  if (status.kind !== "ready") return null;

  const meta = status.data.meta;
  const freshness = assessFreshness(
    meta.period_end_date,
    meta.previous_period_end_date ?? null,
    new Date(),
  );

  if (freshness.kind === "current") return null;

  // Both signals describe the PROJECT falling behind, not the page. A reader who has
  // deliberately opened an older period from the picker is looking at history on purpose,
  // and telling them "a more recent position exists that this dashboard has not been given"
  // would be false - the dashboard has been given it, and they are standing on it. Raised as
  // a NOTE by the part C re-review: the message is a factual claim made to a client.
  const latest = availablePeriods[availablePeriods.length - 1];
  if (latest !== undefined && status.filename !== latest) return null;

  const isAnalyst = roleFromPathname(pathname) === "analyst";
  if (freshness.kind === "late" && !isAnalyst) return null;

  const stale = freshness.kind === "stale";
  const message = stale
    ? `These figures are from the period ending ${meta.period_end_date}, ` +
      `${freshness.daysSincePeriodEnd} days ago. On this project's observed ` +
      `${freshness.cycleDays}-day cycle a further period is now overdue, so a more recent ` +
      `position exists that this dashboard has not been given.`
    : `This period closed ${meta.period_end_date} and a refreshed dashboard is ` +
      `${freshness.workingDaysOverdue} working day${
        freshness.workingDaysOverdue === 1 ? "" : "s"
      } past the ${SLA_WORKING_DAYS}-working-day turnaround. Visible in the Analyst view only.`;

  return (
    <div
      role="status"
      className="px-6 py-2 text-sm border-b"
      style={
        stale
          ? { backgroundColor: "#fee2e2", color: "#991b1b", borderColor: "#fecaca" }
          : { backgroundColor: "#fef3c7", color: "#92400e", borderColor: "#fde68a" }
      }
    >
      <strong className="font-semibold">{stale ? "Out of date" : "Update overdue"}</strong>{" "}
      {message}
    </div>
  );
}
