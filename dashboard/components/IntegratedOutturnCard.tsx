/**
 * The risk contingency (the integrated cost-plus-schedule event-risk cost), for one period, as
 * the home page's "How the number is made up" expander. Called "risk contingency" on the page
 * and never an outturn (R-12); the component's name is an identifier and stays (D-4).
 *
 * Stage 7 part B (A-2). SPEC §5 says the two rhythms share one engine, and until contract 1.4
 * the period cycle carried the schedule side only - the whole of stages 3b/3c did not reach the
 * dashboard. This is where it arrives. INTVIEW-01 stage 1 moved the headline figure up into the
 * first home tile and turned this card into the explanation beneath it.
 *
 * Three things this card does on purpose:
 *
 * 1. **It shows the arithmetic, not just the total.** The integrated figure IS
 *    `cost + delay_days x day_rate`, and every input is on the card. A reader who is asked to
 *    act on one number should be able to see where it came from without opening the JSON.
 * 2. **It names the conditioning.** The period's pinning applies to BOTH arms (Director,
 *    05/09/2026), so risks closed this period carry no cost. That is a real methodology choice
 *    and it changes the number, so it is stated rather than assumed.
 * 3. **It is never blank.** The block is optional in 1.4, and when the arm could not run,
 *    `audit.integrated_unavailable` carries the reason - which is shown. With no reason either,
 *    it says so (INTVIEW-01 property 8): an absent number with no explanation is the state this
 *    repository keeps calling a defect.
 *
 * INTVIEW-01 stage 2 (contract 1.6, property 8): the build-up comes from `integrated.build_up`,
 * each part at its own P80 and the allowance for not every risk at once, so the rows reconcile
 * to the contingency without the app adding anything up. Then "What counts where" and the day
 * rate as the engine states it.
 */

"use client";

import { formatAud } from "@/lib/formatters";
import type { BuildUpRow, DayRateDerivation, Integrated } from "@/types/period";

/** Shared with the home page's first tile, so the two absent states cannot drift apart. */
export const NO_REASON_TEXT =
  "Not available this period. The run recorded no reason; ask your risk analyst to check the period run.";

export function unavailableText(reason?: string): string {
  return reason ? `Not available this period: ${reason}` : NO_REASON_TEXT;
}

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

function Expander({ children }: { children: React.ReactNode }) {
  return (
    <details
      open
      className="bg-white rounded-md border p-4 group"
      style={{ borderColor: "var(--color-card-border)" }}
    >
      <summary className="text-sm font-semibold cursor-pointer select-none">
        How the number is made up
      </summary>
      <div className="mt-3">{children}</div>
    </details>
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
    return (
      <Expander>
        <p className="text-sm" style={{ color: "var(--color-muted)" }}>
          {unavailableText(unavailableReason)}
        </p>
      </Expander>
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

  const p80 = integrated.build_up.find((r) => r.p_level === 80);

  return (
    <Expander>
      {p80 && <BuildUp row={p80} />}

      <div
        className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 pt-4 border-t"
        style={{ borderColor: "var(--color-card-border)" }}
      >
        <Figure label="P80 risk contingency" value={formatAud(integrated.p80_dollars)} emphasis />
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

      <p className="text-sm mt-4" data-testid="what-counts-where">
        <strong>What counts where.</strong> {integrated.what_counts_where}
      </p>
      <DayRate derivation={integrated.day_rate_derivation} />

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
    </Expander>
  );
}

/** One build-up row: label left, the engine's figure right. */
function BuildUpLine({
  label,
  value,
  total = false,
  testId,
}: {
  label: string;
  value: string;
  total?: boolean;
  testId?: string;
}) {
  return (
    <div
      className={`flex flex-wrap justify-between gap-x-4 py-1.5 text-sm ${total ? "border-t font-semibold" : ""}`}
      style={total ? { borderColor: "var(--color-card-border)" } : undefined}
    >
      <span>{label}</span>
      <span className="tabular" data-testid={testId}>
        {value}
      </span>
    </div>
  );
}

/**
 * The P80 build-up. Each part is at its own P80, so they do not add exactly: the allowance row
 * is the engine's `diversification_dollars` (standalone sum less joint), shown with its sign.
 */
function BuildUp({ row }: { row: BuildUpRow }) {
  const div = row.diversification_dollars;
  return (
    <div data-testid="build-up">
      <p className="text-sm mb-2" style={{ color: "var(--color-muted)" }}>
        Each part at its own P80. They do not add exactly, because not every risk happens in the
        same outcome.
      </p>
      <BuildUpLine label="Risk events (cost)" value={formatAud(row.event_cost_dollars)} />
      <BuildUpLine
        label={`Delay: site running costs x ${row.delay_days.toFixed(1)} days late`}
        value={formatAud(row.delay_cost_dollars)}
      />
      <BuildUpLine
        label="Allowance: not every risk at once"
        value={div >= 0 ? `- ${formatAud(div)}` : `+ ${formatAud(-div)}`}
      />
      <BuildUpLine
        label="= Risk contingency P80"
        value={formatAud(row.joint_contingency_dollars)}
        total
        testId="build-up-p80"
      />
    </div>
  );
}

/** The day rate as stated, and the derivation when the register supports one. */
function DayRate({ derivation }: { derivation: DayRateDerivation }) {
  const d = derivation;
  return (
    <p className="text-sm mt-2" style={{ color: "var(--color-muted)" }} data-testid="day-rate">
      Delay cost is the finish delay that survives float, times {formatAud(d.day_rate_used)} per
      working day (site running costs).{" "}
      {d.day_rate_derived !== null && d.avg_prelims_weekly !== null && (
        <>
          From the register: {formatAud(d.avg_prelims_weekly)} prelims a week over{" "}
          {d.schedule_duration_weeks} weeks and {d.programme_working_days.toFixed(0)} working days
          gives {formatAud(d.day_rate_derived)}.{" "}
        </>
      )}
      {d.gap_flagged && <strong style={{ color: "var(--color-fired)" }}>Check the rate. </strong>}
      {d.note}
    </p>
  );
}
