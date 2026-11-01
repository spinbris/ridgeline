/**
 * The home page's "Contingency position" panel (INTVIEW-01 stage 2b, property 13).
 *
 * Two phases, read from `contingency.phase` and never inferred here:
 *
 * - **Recommended** (before commitment). The project has not committed a budget, so there is no
 *   held figure to compare. The panel reads "Recommended at P80" and the joint chance is labelled
 *   a target, so a missing entry never reads as funded.
 * - **Held** (from the commitment date). Held against required at P80, the shortfall or headroom,
 *   pending draws shown apart, and the chance of meeting both a budget of base plus HELD and the
 *   P80 date, beside the tile 4 figure against base plus RECOMMENDED. Then the ledger to date.
 *
 * Every figure is the engine's; the app formats and labels. Illustrative held figures (the
 * Tropic Ridge showcase) carry a tag saying so.
 */

"use client";

import {
  formatAud,
  formatAudMillions,
  formatPercent,
  formatShortDate,
} from "@/lib/formatters";
import type { Contingency, IntegratedJcl } from "@/types/period";

export function ContingencyPosition({
  contingency,
  jcl,
}: {
  contingency: Contingency;
  jcl?: IntegratedJcl;
}) {
  const c = contingency;
  return (
    <section
      className="bg-white rounded-md border p-4"
      style={{ borderColor: "var(--color-card-border)" }}
      data-testid="contingency-position"
      data-phase={c.phase}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Contingency position</h3>
        {c.illustrative && (
          <span
            className="text-xs font-semibold rounded px-2 py-0.5"
            style={{ background: "var(--color-fired-soft-bg)", color: "var(--color-fired-soft-fg)" }}
            data-testid="contingency-illustrative"
          >
            Illustrative held figures (showcase)
          </span>
        )}
      </div>
      {c.phase === "held" && c.held_dollars !== null && c.shortfall_dollars !== null ? (
        <HeldPhase c={c} jcl={jcl} />
      ) : (
        <RecommendedPhase c={c} jcl={jcl} />
      )}
    </section>
  );
}

function Figure({
  label,
  value,
  testId,
  tone,
}: {
  label: string;
  value: string;
  testId?: string;
  tone?: string;
}) {
  return (
    <div>
      <div className="text-sm" style={{ color: "var(--color-muted)" }}>
        {label}
      </div>
      <div
        className="text-xl font-bold tabular"
        style={tone ? { color: tone } : undefined}
        data-testid={testId}
      >
        {value}
      </div>
    </div>
  );
}

function RecommendedPhase({ c, jcl }: { c: Contingency; jcl?: IntegratedJcl }) {
  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-3">
        <Figure label={c.label} value={formatAudMillions(c.required_p80_dollars)} testId="contingency-required" />
        <Figure label="Held" value="Not committed yet" testId="contingency-held" />
        <Figure
          label="Target: chance of meeting both budget and date"
          value={jcl ? formatPercent(jcl.jcl, 0) : "Not available"}
        />
      </div>
      <p className="text-sm mt-3" style={{ color: "var(--color-muted)" }}>
        No budget has been committed yet, so this is the contingency recommended at P80, not an
        amount held. From the commitment date the status workbook records the opening amount, and
        this panel shows held against required each period.
      </p>
    </>
  );
}

function HeldPhase({ c, jcl }: { c: Contingency; jcl?: IntegratedJcl }) {
  const short = c.shortfall_dollars! > 0;
  const gap = Math.abs(c.shortfall_dollars!);
  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mt-3">
        <Figure label="Held" value={formatAudMillions(c.held_dollars!)} testId="contingency-held" />
        <Figure
          label="Required (P80)"
          value={formatAudMillions(c.required_p80_dollars)}
          testId="contingency-required"
        />
        <Figure
          label={short ? "Shortfall" : "Headroom"}
          value={`${short ? "▼" : "▲"} ${formatAudMillions(gap)}`}
          testId="contingency-gap"
          tone={short ? "var(--color-fired)" : "var(--color-closed)"}
        />
        <Figure
          label="Chance of meeting both budget and date"
          value={c.jcl_against_held !== null ? formatPercent(c.jcl_against_held, 0) : "Not available"}
          testId="contingency-jcl-held"
        />
      </div>
      <p className="text-sm mt-3" style={{ color: "var(--color-muted)" }}>
        Held is the {formatAudMillions(c.opening_held_dollars!)} committed on{" "}
        {formatShortDate(c.commitment_date!)}, less {formatAudMillions(c.approved_draws_dollars!)}{" "}
        of approved draws, plus {formatAudMillions(c.releases_dollars!)} released. Required is this
        period&apos;s re-run P80.
        {c.pending_draws_dollars! > 0 && (
          <>
            {" "}
            A further {formatAudMillions(c.pending_draws_dollars!)} of draws is pending and not
            yet taken off held.
          </>
        )}
      </p>
      <p className="text-sm mt-1" style={{ color: "var(--color-muted)" }}>
        The joint chance here uses a budget of base plus held
        {c.cost_confidence_against_held !== null &&
          ` (budget alone ${formatPercent(c.cost_confidence_against_held, 0)})`}
        {jcl && `; tile 4's ${formatPercent(jcl.jcl, 0)} uses base plus the recommended P80`}.
      </p>
      {c.movements.length > 0 && (
        <div className="overflow-x-auto mt-3">
          <table className="w-full text-sm" data-testid="contingency-movements">
            <caption className="sr-only">Contingency draws and releases since commitment</caption>
            <thead>
              <tr className="text-left text-xs uppercase" style={{ color: "var(--color-muted)" }}>
                <th className="py-1 pr-3 font-semibold">Date</th>
                <th className="py-1 pr-3 font-semibold">Movement</th>
                <th className="py-1 pr-3 font-semibold">Risk</th>
                <th className="py-1 pr-3 font-semibold text-right">Amount</th>
                <th className="py-1 font-semibold">Note</th>
              </tr>
            </thead>
            <tbody>
              {c.movements.map((m, i) => (
                <tr key={i} className="border-t" style={{ borderColor: "var(--color-card-border)" }}>
                  <td className="py-1 pr-3 whitespace-nowrap">{formatShortDate(m.date)}</td>
                  <td className="py-1 pr-3 whitespace-nowrap">
                    {m.type}
                    {m.status === "Pending" ? " (pending)" : ""}
                  </td>
                  <td className="py-1 pr-3">{m.risk_id ?? "—"}</td>
                  <td className="py-1 pr-3 text-right tabular whitespace-nowrap">
                    {m.type === "Draw" ? "−" : "+"}
                    {formatAud(m.amount_dollars)}
                  </td>
                  <td className="py-1" style={{ color: "var(--color-muted)" }}>
                    {m.note ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
