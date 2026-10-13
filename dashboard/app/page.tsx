/**
 * PM Page 1 — Where we are.
 *
 * Mockup reference: #pm-page-1 in
 * ../mockup/the original dashboard mockup (archived).
 *
 * Sections (top to bottom):
 * - Headline P80 finish date as the dominant primary number, with
 *   the deterministic-baseline delta callout
 * - Number row: P10, P50, Mean, P80, P90, P95 with days-behind-plan
 *   sublabels
 * - Stat row: open / fired / closed risk counts with status-colored
 *   values
 * - Card: near-critical milestones in the next 30 days (empty state
 *   for v1 per Doc 3 - milestone WBS codes not populated)
 * - Card: P80 forecast trend over last 5 periods (single point at
 *   period 0; multi-point as periods accumulate)
 */

"use client";

import { IntegratedOutturnCard } from "@/components/IntegratedOutturnCard";
import { PeriodGate } from "@/components/PeriodGate";
import {
  formatDaysDelta,
  formatLongDate,
  formatShortDate,
} from "@/lib/formatters";
import { usePeriodContext } from "@/lib/PeriodContext";

export default function PmPage1() {
  return (
    <PeriodGate>
      <PmPage1Content />
    </PeriodGate>
  );
}

function PmPage1Content() {
  const { status } = usePeriodContext();
  if (status.kind !== "ready") return null;
  const { headline, trend, integrated, audit } = status.data;
  const m = status.data.meta;

  return (
    <main className="px-6 py-6 space-y-5 max-w-7xl mx-auto">
      <header>
        <h2 className="text-xl font-semibold">Where we are</h2>
        <p
          className="text-sm mt-1"
          style={{ color: "var(--color-muted)" }}
        >
          Headline forecast versus deterministic baseline. Period end{" "}
          {formatLongDate(m.period_end_date)}.
        </p>
      </header>

      {/* Headline P80 — primary number */}
      <section
        className="rounded-md text-white p-6"
        style={{ background: "var(--color-header)" }}
      >
        <div
          className="text-xs uppercase tracking-wider opacity-70 mb-2"
          aria-label="metric label"
        >
          P80 forecast project finish
        </div>
        <div className="text-4xl font-bold mb-1">
          {formatLongDate(headline.p80_finish)}
        </div>
        <div
          className="text-sm opacity-85"
          style={{
            color:
              headline.p80_days_behind_plan > 0
                ? "var(--color-behind)"
                : "rgba(255,255,255,0.85)",
          }}
        >
          {formatDaysDelta(headline.p80_days_behind_plan)} vs deterministic
          baseline ({formatLongDate(headline.deterministic_finish)})
        </div>
      </section>

      {/* Number row — P10..P95 + Mean. P10 / Mean / P95 days-behind
          are absent from Doc 3 v2.3 (only P50 / P80 / P90 are carried);
          per AM03 §3 SOP "no hardcoded business logic: numbers come
          from the JSON" we leave their sublabels blank rather than
          computing client-side. Engine-side spec extension is the
          v1.1 path if these become operationally important. */}
      <section className="grid grid-cols-3 md:grid-cols-6 gap-3">
        <NumberCell
          label="P10"
          value={formatShortDate(headline.p10_finish)}
        />
        <NumberCell
          label="P50"
          value={formatShortDate(headline.p50_finish)}
          subValue={formatDaysDelta(headline.p50_days_behind_plan)}
        />
        <NumberCell
          label="Mean"
          value={formatShortDate(headline.mean_finish)}
        />
        <NumberCell
          label="P80"
          value={formatShortDate(headline.p80_finish)}
          subValue={formatDaysDelta(headline.p80_days_behind_plan)}
          highlight
        />
        <NumberCell
          label="P90"
          value={formatShortDate(headline.p90_finish)}
          subValue={formatDaysDelta(headline.p90_days_behind_plan)}
        />
        <NumberCell
          label="P95"
          value={formatShortDate(headline.p95_finish)}
        />
      </section>

      {/* Stat row — open / fired / closed counts */}
      <section className="grid grid-cols-3 gap-3">
        <StatCell
          label="Open risks"
          value={headline.open_risks_count}
          tone="open"
        />
        <StatCell
          label="Fired this period"
          value={headline.fired_this_period_count}
          tone="fired"
        />
        <StatCell
          label="Closed this period"
          value={headline.closed_this_period_count}
          tone="closed"
        />
      </section>

      {/* Integrated event-risk cost (contract 1.4, stage 7 part B). Placed below the schedule
          headline rather than above it: the period cycle's primary question is still
          "when does this finish", and the integrated figure answers a second one. */}
      <IntegratedOutturnCard
        integrated={integrated}
        unavailableReason={audit.integrated_unavailable}
      />

      {/* Near-critical milestones */}
      <Card title="Near-critical milestones (next 30 days)">
        {headline.near_critical_milestones_30d.length === 0 ? (
          <p
            className="text-sm py-2"
            style={{ color: "var(--color-muted)" }}
          >
            No milestones are listed for this period.
          </p>
        ) : (
          <ul className="space-y-1 text-sm">
            {headline.near_critical_milestones_30d.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        )}
      </Card>

      {/* Trend strip */}
      <Card title={`P80 forecast trend (last ${trend.periods.length} period${trend.periods.length === 1 ? "" : "s"})`}>
        {trend.periods.length === 1 ? (
          <div className="py-2">
            <p
              className="text-sm"
              style={{ color: "var(--color-muted)" }}
            >
              Period 0: single data point at{" "}
              <span
                className="font-semibold"
                style={{ color: "var(--color-body)" }}
              >
                {formatLongDate(trend.periods[0].p80_finish)}
              </span>
              . The trend strip populates as future periods are run.
            </p>
          </div>
        ) : (
          <ul className="grid grid-cols-1 md:grid-cols-5 gap-3 text-sm">
            {trend.periods.map((p) => (
              <li
                key={p.period_end}
                className="bg-white border rounded p-3"
                style={{ borderColor: "var(--color-card-border)" }}
              >
                <div
                  className="text-[10px] uppercase tracking-wider"
                  style={{ color: "var(--color-muted)" }}
                >
                  {formatShortDate(p.period_end)}
                </div>
                <div className="font-semibold">
                  {formatShortDate(p.p80_finish)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Local primitives
// ---------------------------------------------------------------------------

function NumberCell({
  label,
  value,
  subValue,
  highlight = false,
}: {
  label: string;
  value: string;
  subValue?: string;
  highlight?: boolean;
}) {
  return (
    <div
      className="bg-white rounded-md border p-3 text-center"
      style={{
        borderColor: highlight
          ? "var(--color-accent)"
          : "var(--color-card-border)",
        borderWidth: highlight ? 2 : 1,
      }}
    >
      <div
        className="text-[10px] uppercase tracking-wider font-semibold"
        style={{ color: "var(--color-muted)" }}
      >
        {label}
      </div>
      <div className="text-base font-semibold mt-1">{value}</div>
      <div
        className="text-[11px] mt-0.5 min-h-[1em]"
        style={{ color: "var(--color-muted)" }}
      >
        {subValue ?? ""}
      </div>
    </div>
  );
}

function StatCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "open" | "fired" | "closed";
}) {
  const toneColor =
    tone === "open"
      ? "var(--color-accent)"
      : tone === "fired"
        ? "var(--color-fired)"
        : "var(--color-closed)";
  return (
    <div
      className="bg-white rounded-md border p-4"
      style={{ borderColor: "var(--color-card-border)" }}
    >
      <div
        className="text-xs uppercase tracking-wider font-semibold"
        style={{ color: "var(--color-muted)" }}
      >
        {label}
      </div>
      <div
        className="text-2xl font-bold mt-2 tabular"
        style={{ color: toneColor }}
      >
        {value}
      </div>
    </div>
  );
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className="bg-white rounded-md border p-4"
      style={{ borderColor: "var(--color-card-border)" }}
    >
      <h3 className="text-sm font-semibold mb-3">{title}</h3>
      {children}
    </section>
  );
}

