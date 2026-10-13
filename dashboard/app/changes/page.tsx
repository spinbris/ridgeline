/**
 * PM Page 4 — What changed.
 *
 * Mockup reference: #pm-page-4.
 *
 * Renders the delta block:
 * - Period 0 (discriminated union member DeltaPeriod0): empty state
 *   explaining no prior data exists.
 * - Subsequent periods: P80 movement summary, two columns of
 *   worse / better risk changes, optional "new this period" list.
 *
 * Type narrowing on `delta.period_0` selects the rendering branch.
 */

"use client";

import { PeriodGate } from "@/components/PeriodGate";
import { formatDaysDelta, formatLongDate } from "@/lib/formatters";
import { usePeriodContext } from "@/lib/PeriodContext";
import type { Delta, DeltaEntry } from "@/types/period";

export default function PmPage4() {
  return (
    <PeriodGate>
      <PmPage4Content />
    </PeriodGate>
  );
}

function PmPage4Content() {
  const { status } = usePeriodContext();
  if (status.kind !== "ready") return null;
  const { delta, meta } = status.data;

  return (
    <main className="px-6 py-6 space-y-5 max-w-7xl mx-auto">
      <header>
        <h2 className="text-xl font-semibold">What changed</h2>
        <p
          className="text-sm mt-1"
          style={{ color: "var(--color-muted)" }}
        >
          {meta.previous_period_end_date
            ? `Movement from previous period (${formatLongDate(
                meta.previous_period_end_date,
              )}).`
            : "First period in the dashboard's history; no prior data for delta."}
        </p>
      </header>

      {isPeriod0(delta) ? (
        <Period0Empty note={delta.note} />
      ) : (
        <SubsequentPeriod delta={delta} />
      )}
    </main>
  );
}

function isPeriod0(delta: Delta): delta is Extract<Delta, { period_0: true }> {
  return delta.period_0 === true;
}

function Period0Empty({ note }: { note: string }) {
  return (
    <section
      className="bg-white rounded-md border p-6"
      style={{ borderColor: "var(--color-card-border)" }}
    >
      <h3 className="text-sm font-semibold mb-2">
        Period 0 - no prior data
      </h3>
      <p
        className="text-sm"
        style={{ color: "var(--color-muted)" }}
      >
        {note}
      </p>
      <p
        className="text-xs mt-3"
        style={{ color: "var(--color-muted)" }}
      >
        Future periods will show: P80 movement, worse / better risk
        changes, and any new risks added since the prior cycle.
      </p>
    </section>
  );
}

function SubsequentPeriod({
  delta,
}: {
  delta: Extract<Delta, { p80_delta_days: number }>;
}) {
  return (
    <>
      <section
        className="bg-white rounded-md p-4 text-sm"
        style={{
          borderLeft: "4px solid var(--color-accent)",
        }}
      >
        <strong>
          P80 forecast moved {formatDaysDelta(delta.p80_delta_days)}
        </strong>{" "}
        ({formatLongDate(delta.p80_previous)} -&gt;{" "}
        {formatLongDate(delta.p80_current)}).{" "}
        <span style={{ color: "var(--color-muted)" }}>
          {delta.net_movement_summary}
        </span>
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <DeltaColumn
          title="Worse this period"
          tone="worse"
          entries={delta.worse}
          emptyMessage="No risks moved adversely this period."
        />
        <DeltaColumn
          title="Better this period"
          tone="better"
          entries={delta.better}
          emptyMessage="No risks improved this period."
        />
      </section>

      {delta.new.length > 0 && (
        <DeltaColumn
          title="New this period"
          tone="worse"
          entries={delta.new}
          emptyMessage="No new risks added."
        />
      )}
    </>
  );
}

function DeltaColumn({
  title,
  tone,
  entries,
  emptyMessage,
}: {
  title: string;
  tone: "worse" | "better";
  entries: DeltaEntry[];
  emptyMessage: string;
}) {
  const accent =
    tone === "worse" ? "var(--color-fired)" : "var(--color-closed)";
  return (
    <section>
      <h3
        className="text-xs uppercase tracking-wider font-semibold mb-2"
        style={{ color: "var(--color-muted)" }}
      >
        {title}
      </h3>
      {entries.length === 0 ? (
        <p
          className="text-sm bg-white rounded-md border p-4"
          style={{
            borderColor: "var(--color-card-border)",
            color: "var(--color-muted)",
          }}
        >
          {emptyMessage}
        </p>
      ) : (
        <ul className="space-y-2">
          {entries.map((entry, i) => (
            <li
              key={`${entry.risk_id}-${i}`}
              className="bg-white rounded-md p-3 text-sm border"
              style={{
                borderColor: "var(--color-card-border)",
                borderLeft: `3px solid ${accent}`,
              }}
            >
              <div>
                <strong>{entry.risk_id}</strong> - {entry.description}
              </div>
              {entry.change_meta && (
                <div
                  className="text-xs mt-1"
                  style={{ color: "var(--color-muted)" }}
                >
                  {entry.change_meta}
                </div>
              )}
              <div
                className="font-semibold mt-1"
                style={{ color: accent }}
              >
                {formatDaysDelta(entry.delta_days)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
