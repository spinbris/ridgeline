/**
 * Per-page collapsible guidance strip (UX01-T2 scope item 2).
 *
 * Copy sourced verbatim from docs/user_manual/dashboard_guidance_strip_copy.md
 * (UX01-T3 handoff). One entry per page: what the page shows, how to read
 * its key number. Native <details>/<summary>, no client state needed beyond
 * the browser's own disclosure toggle.
 */

"use client";

import { usePathname } from "next/navigation";

import { normalisePath } from "@/lib/PeriodContext";

const GUIDANCE: Record<string, string> = {
  "/": "Shows the headline P80 project finish date and how many days behind the deterministic (risk-free) baseline you are sitting, percentile markers, risk counts, and the P80 trend over prior periods. Key number: P80 finish date, the date you should have 80 percent confidence of meeting.",
  "/risks": "Lists every open risk in priority order by days-at-risk-p80, the impact each risk has on the headline P80 forecast. Key number: days-at-risk-p80, how many days the P80 would move forward if you could eliminate only this one risk while keeping all others as-is.",
  "/mitigations": "Shows the register of proposed mitigations and their estimated impact on the P80 if completed. Key number: days-saved-p80 per mitigation, the estimated P80 improvement if the mitigation is completed.",
  "/changes": "Shows period-over-period movement: the P80 delta, risks that got worse, risks that got better, and new risks added this period. Key number: P80 delta, negative means the forecast moved earlier (less risk), positive means later (more risk).",
  "/analyst": "Shows the S-curve, a frequency histogram of the 100,000 Monte Carlo outcomes, and the percentile table. Key number: the spread from P10 to P90, the wider the spread, the more variance in the schedule.",
  "/analyst/drivers": "A tornado chart ranks risks by their contribution to project-finish variance. Key number: tornado-sample-sigma-days, the marginal contribution of each risk to project-finish standard deviation, measured by conditional resampling; bars do not sum to total variance.",
  "/analyst/activities": "The stochastic Gantt shows each activity's finish-date distribution as a band, the deterministic finish as a diamond marker, and criticality status. Key number: band width, wide bands are candidates for further risk mitigation or crashing.",
  "/analyst/audit": "Records which risks were evaluated, which inputs were applied, and which analytical choices were made, with disclosure of trade-offs in the Methodology Notes section. Key number: iterations, higher iterations mean tighter precision.",
};

export function GuidanceStrip() {
  const pathname = usePathname();
  // ROUTE-01: normalise before lookup - GUIDANCE keys are slashless and
  // `usePathname()` returns a trailing slash under trailingSlash. Without
  // this the strip renders nothing on every route except "/".
  const copy = GUIDANCE[normalisePath(pathname)];
  if (!copy) return null;

  return (
    <details
      className="px-6 py-2 text-xs border-b print:hidden"
      style={{
        borderColor: "var(--color-card-border)",
        color: "var(--color-muted)",
        background: "var(--color-card)",
      }}
    >
      <summary
        className="cursor-pointer font-medium select-none"
        style={{ color: "var(--color-accent-dark)" }}
      >
        What this page shows
      </summary>
      <p className="mt-1 pb-1">{copy}</p>
    </details>
  );
}
