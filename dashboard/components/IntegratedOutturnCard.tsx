/**
 * The integrated cost-plus-schedule event-risk cost, for one period. Never called an outturn
 * on the page (R-12); the component's name is an identifier and stays (D-4).
 *
 * Stage 7 part B (A-2). SPEC §5 says the two rhythms share one engine, and until contract 1.4
 * the period cycle carried the schedule side only - the whole of stages 3b/3c did not reach the
 * dashboard. This is where it arrives.
 *
 * Three things this card does on purpose:
 *
 * 1. **It shows the arithmetic, not just the total.** The integrated figure IS
 *    `cost + delay_days x day_rate`, and every input is on the card. A reader who is asked to
 *    act on one number should be able to see where it came from without opening the JSON.
 * 2. **It names the conditioning.** The period's pinning applies to BOTH arms (Director,
 *    05/09/2026), so risks closed this period carry no cost. That is a real methodology choice
 *    and it changes the number, so it is stated rather than assumed.
 * 3. **It renders nothing when there is nothing.** The block is optional in 1.4, and when the
 *    arm could not run, `audit.integrated_unavailable` carries the reason - which is shown,
 *    because an absent number with no explanation is the state this repository keeps calling a
 *    defect.
 */

"use client";

import { Card } from "@/components/Card";
import { formatAud } from "@/lib/formatters";
import type { Integrated } from "@/types/period";

function Figure({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div>
      <div
        className="text-xs uppercase tracking-wider"
        style={{ color: "var(--color-muted)" }}
      >
        {label}
      </div>
      <div className={emphasis ? "text-2xl font-bold" : "text-base font-medium"}>
        {value}
      </div>
    </div>
  );
}

export function IntegratedOutturnCard({
  integrated,
  unavailableReason,
}: {
  integrated?: Integrated;
  unavailableReason?: string;
}) {
  if (!integrated) {
    if (!unavailableReason) return null;
    return (
      <Card title="Integrated event-risk cost (cost + schedule)">
        <p className="text-sm" style={{ color: "var(--color-muted)" }}>
          Not available for this period: {unavailableReason}
        </p>
      </Card>
    );
  }

  const p = integrated.pinning;
  const conditioned = p.risks_removed + p.risks_closed + p.risks_reprobabilised;
  // Built by join rather than nested ternaries in the JSX below. The ternary version rendered
  // "priced risks(2 re-probabilised)" - a missing space that only appeared once a period with
  // pinning was actually loaded, because the no-pinning branch never reached it.
  const breakdown = [
    p.risks_removed > 0 ? `${p.risks_removed} removed` : null,
    p.risks_closed > 0 ? `${p.risks_closed} closed` : null,
    p.risks_reprobabilised > 0 ? `${p.risks_reprobabilised} re-probabilised` : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <Card title="Integrated event-risk cost (cost + schedule)">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Figure label="P80 integrated" value={formatAud(integrated.p80_dollars)} emphasis />
        <Figure label="P50" value={formatAud(integrated.p50_dollars)} />
        <Figure label="Mean" value={formatAud(integrated.mean_dollars)} />
        <Figure label="P95" value={formatAud(integrated.p95_dollars)} />
      </div>

      <div
        className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 pt-4 border-t"
        style={{ borderColor: "var(--color-card-border)" }}
      >
        <Figure
          label="Cost marginal (P80)"
          value={formatAud(integrated.cost_marginal.p80_dollars)}
        />
        <Figure
          label="Schedule marginal (P80)"
          value={`${integrated.schedule_marginal.p80_delay_days.toFixed(1)} days x ${formatAud(
            integrated.day_rate,
          )}/day`}
        />
      </div>

      <p className="text-xs mt-4" style={{ color: "var(--color-muted)" }}>
        {integrated.basis}. Delay is measured against a deterministic baseline of{" "}
        {integrated.deterministic_baseline_days.toFixed(0)} working days, over{" "}
        {integrated.iterations.toLocaleString()} iterations.{" "}
        {conditioned > 0 ? (
          <>
            This period&apos;s status conditioned {conditioned} of {p.risks_priced} priced risks
            {breakdown ? ` (${breakdown})` : ""}, so cost and schedule are conditioned the same
            way.
          </>
        ) : (
          <>
            No risk was removed or re-probabilised by this period&apos;s status, so all{" "}
            {p.risks_priced} priced risks carry their register values.
          </>
        )}
      </p>
    </Card>
  );
}
