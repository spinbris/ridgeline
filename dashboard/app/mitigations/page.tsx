/**
 * PM Page 3 — What we could do.
 *
 * Mockup reference: #pm-page-3.
 *
 * Renders:
 * - A headline summary card: which mitigation is currently "applied"
 *   in the interactive view (Baseline + P80, or a specific mitigation
 *   + its `p80_finish_with_mitigation`)
 * - Mitigation grid: one card per `mitigations[]` entry, sorted by
 *   days_saved_p80 desc (Doc 3 v2.3 rule 5). Each card carries an
 *   Apply / Undo toggle.
 * - Empty state when the mitigations list is empty (template state).
 *
 * Per D3: counterfactuals are pre-computed by the engine; the toggle
 * just switches which value is rendered. Single-mitigation in v1
 * (toggling a second one deselects the first); multi-mitigation is
 * v1.1.
 *
 * Interactive state lives in this component (page-local React state);
 * resets when the user navigates away. Persisting through the period
 * picker is intentional: the same mitigation toggle survives a period
 * change (until the user lands here again with no mitigations to
 * select).
 */

"use client";

import { useState } from "react";

import { PeriodGate } from "@/components/PeriodGate";
import { StatusBadge } from "@/components/StatusBadge";
import {
  formatAud,
  formatLongDate,
} from "@/lib/formatters";
import { usePeriodContext } from "@/lib/PeriodContext";
import type { Mitigation } from "@/types/period";

export default function PmPage3() {
  return (
    <PeriodGate>
      <PmPage3Content />
    </PeriodGate>
  );
}

function PmPage3Content() {
  const { status } = usePeriodContext();
  const [applied, setApplied] = useState<string | null>(null);

  if (status.kind !== "ready") return null;
  const { mitigations, headline } = status.data;
  const appliedMit =
    applied !== null
      ? mitigations.find((m) => m.mitigation_id === applied)
      : null;

  return (
    <main className="px-6 py-6 space-y-5 max-w-7xl mx-auto">
      <header>
        <h2 className="text-xl font-semibold">What we could do</h2>
        <p
          className="text-sm mt-1"
          style={{ color: "var(--color-muted)" }}
        >
          Proposed mitigations ranked by days saved at P80. Toggle Apply
          to see the headline shift.
        </p>
      </header>

      {/* Applied headline summary */}
      <section
        className="rounded-md text-white p-6"
        style={{ background: "var(--color-header)" }}
      >
        <div className="text-xs uppercase tracking-wider opacity-70 mb-2">
          Currently showing
        </div>
        <div className="text-2xl font-bold mb-1">
          {appliedMit
            ? `Mitigation ${appliedMit.mitigation_id} applied`
            : "Baseline (no mitigation applied)"}
        </div>
        <div className="text-sm opacity-85">
          P80:{" "}
          <span className="font-semibold">
            {appliedMit
              ? formatLongDate(appliedMit.p80_finish_with_mitigation)
              : formatLongDate(headline.p80_finish)}
          </span>{" "}
          {appliedMit && (
            <span style={{ color: "var(--color-behind)" }}>
              ({appliedMit.days_saved_p80.toFixed(1)} days saved)
            </span>
          )}
        </div>
      </section>

      {/* Mitigation cards */}
      {mitigations.length === 0 ? (
        <section
          className="bg-white rounded-md border p-6 text-sm"
          style={{
            borderColor: "var(--color-card-border)",
            color: "var(--color-muted)",
          }}
        >
          No mitigations have been proposed for this period. Mitigations
          appear here once they are logged in the status data for the period.
        </section>
      ) : (
        <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {mitigations.map((m) => (
            <MitigationCard
              key={m.mitigation_id}
              mitigation={m}
              applied={applied === m.mitigation_id}
              onApply={() =>
                setApplied((prev) =>
                  prev === m.mitigation_id ? null : m.mitigation_id,
                )
              }
            />
          ))}
        </section>
      )}

      {/* V1 single-mitigation footnote */}
      {mitigations.length > 1 && (
        <p
          className="text-xs"
          style={{ color: "var(--color-muted)" }}
        >
          Mitigations are applied one at a time. Applying a second
          mitigation replaces the first, because the period data does not
          include results for combinations of mitigations.
        </p>
      )}
    </main>
  );
}

function MitigationCard({
  mitigation,
  applied,
  onApply,
}: {
  mitigation: Mitigation;
  applied: boolean;
  onApply: () => void;
}) {
  return (
    <article
      className="bg-white rounded-md border p-4 transition-shadow hover:shadow-md"
      style={{
        borderColor: applied
          ? "var(--color-accent)"
          : "var(--color-card-border)",
        borderWidth: applied ? 2 : 1,
      }}
    >
      <div
        className="text-[11px] font-mono"
        style={{ color: "var(--color-muted)" }}
      >
        {mitigation.mitigation_id}
        {mitigation.risk_id ? ` - ${mitigation.risk_id}` : ""}
      </div>
      <div className="font-medium mt-1 mb-3">
        {mitigation.description ?? "(no description)"}
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs mb-3">
        <Stat
          label="Cost"
          value={
            mitigation.cost_aud !== null
              ? formatAud(mitigation.cost_aud)
              : "n/a"
          }
        />
        <Stat
          label="Lead time"
          value={
            mitigation.lead_time_weeks !== null
              ? `${mitigation.lead_time_weeks} weeks`
              : "n/a"
          }
        />
        <Stat label="Owner" value={mitigation.owner ?? "Unassigned"} />
        <div>
          <div
            className="text-[10px] uppercase tracking-wider"
            style={{ color: "var(--color-muted)" }}
          >
            Status
          </div>
          <div className="mt-1">
            <StatusBadge status={mitigation.status} />
          </div>
        </div>
      </div>

      <div
        className="text-sm rounded p-2 mb-3"
        style={{
          background: "#f0f7f3",
          borderLeft: "3px solid var(--color-closed)",
        }}
      >
        Saves{" "}
        <strong style={{ color: "var(--color-closed)" }}>
          {mitigation.days_saved_p80.toFixed(1)} days
        </strong>{" "}
        at P80 -&gt;{" "}
        <span className="font-medium">
          {formatLongDate(mitigation.p80_finish_with_mitigation)}
        </span>
      </div>

      <button
        type="button"
        onClick={onApply}
        className="w-full py-2 rounded text-xs font-semibold uppercase tracking-wider text-white transition-colors"
        style={{
          background: applied
            ? "var(--color-header)"
            : "var(--color-accent)",
        }}
      >
        {applied ? "Undo" : "Apply mitigation"}
      </button>
    </article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        className="text-[10px] uppercase tracking-wider"
        style={{ color: "var(--color-muted)" }}
      >
        {label}
      </div>
      <div className="font-semibold mt-0.5">{value}</div>
    </div>
  );
}
