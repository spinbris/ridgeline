/**
 * PM Page 1 - How much and when (INTVIEW-01 stage 1).
 *
 * The home page leads with the integrated result. Sections (top to bottom):
 * - Heading, period end, and the full technical report link
 * - Four tiles: risk contingency P80 (primary), finish P80, since last period, and on budget
 *   and on time (the JCL on the report's basis, INTVIEW-01 stage 2)
 * - "How the number is made up" expander (the integrated card, open by default)
 * - P80 forecast trend; the contingency position (stage 2b: recommended, or held against
 *   required from commitment); risk counts; near-critical milestones
 *
 * Every figure is read from the period JSON (contract 1.6) and only formatted here; the app adds
 * nothing up. The six-cell P10..P95 date row left this page: those dates stay on the analyst
 * percentile table. The full JCL sentence and frontier stay on the analyst distribution page.
 */

"use client";

import Link from "next/link";

import {
  IntegratedOutturnCard,
  unavailableText,
} from "@/components/IntegratedOutturnCard";
import { ContingencyPosition } from "@/components/ContingencyPosition";
import { PeriodGate } from "@/components/PeriodGate";
import {
  formatAudMillions,
  formatAudMillionsDelta,
  formatDaysDelta,
  formatLongDate,
  formatPercent,
  formatShortDate,
} from "@/lib/formatters";
import { usePeriodContext } from "@/lib/PeriodContext";
import type { Delta, Headline, Integrated, IntegratedJcl } from "@/types/period";

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
  const { headline, trend, integrated, audit, delta } = status.data;
  const m = status.data.meta;

  return (
    <main className="px-4 sm:px-6 py-6 space-y-5 max-w-7xl mx-auto">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">How much and when</h2>
          <p
            className="text-sm mt-1"
            style={{ color: "var(--color-muted)" }}
          >
            Period end {formatLongDate(m.period_end_date)}.
          </p>
        </div>
        {/* REPORTPAGE-01: a plain anchor, not next/link. The report is a static file in
            public/report/, outside the app router, so client-side navigation would miss it.
            Styled as a call to action (REPORTLINK-01); its accessible name stays the label alone. */}
        <a
          href="/report/"
          className="inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
          style={{ background: "var(--color-accent)" }}
        >
          Full technical report
          <span aria-hidden="true">→</span>
        </a>
      </header>

      {/* The four tiles. One column on a phone, two from md, four from xl. */}
      <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        <ContingencyTile
          integrated={integrated}
          unavailableReason={audit.integrated_unavailable}
        />
        <FinishTile headline={headline} />
        <SinceLastPeriodTile delta={delta} previousPeriodEnd={m.previous_period_end_date} />
        <OnBudgetAndOnTimeTile jcl={integrated?.jcl} />
      </section>

      {/* The integrated card, relabelled, as the explanation of tile 1. Rendered only with a
          block to explain: when there is none, tile 1 already carries the reason. */}
      {integrated && <IntegratedOutturnCard integrated={integrated} />}

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
              {trend.periods[0].contingency_p80_dollars !== null && (
                <>
                  , risk contingency P80{" "}
                  <span className="font-semibold" style={{ color: "var(--color-body)" }}>
                    {formatAudMillions(trend.periods[0].contingency_p80_dollars)}
                  </span>
                </>
              )}
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
                {p.contingency_p80_dollars !== null && (
                  <div className="text-xs tabular" style={{ color: "var(--color-muted)" }}>
                    {formatAudMillions(p.contingency_p80_dollars)} contingency
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Stage 2b: held against required from commitment; "Recommended at P80" before it. */}
      {status.data.contingency && (
        <ContingencyPosition contingency={status.data.contingency} jcl={integrated?.jcl} />
      )}

      {/* Stat row - open / fired / closed counts */}
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
    </main>
  );
}

// ---------------------------------------------------------------------------
// Tiles
// ---------------------------------------------------------------------------

function TileLabel({ children, light = false }: { children: React.ReactNode; light?: boolean }) {
  return (
    <div
      className={`text-xs uppercase tracking-wider font-semibold mb-2 ${light ? "opacity-70" : ""}`}
      style={light ? undefined : { color: "var(--color-muted)" }}
    >
      {children}
    </div>
  );
}

/** Tile 1, the primary tile. Never blank (property 8). */
function ContingencyTile({
  integrated,
  unavailableReason,
}: {
  integrated?: Integrated;
  unavailableReason?: string;
}) {
  return (
    <section
      className="rounded-md text-white p-5"
      style={{ background: "var(--color-header)" }}
      data-testid="tile-contingency"
    >
      <TileLabel light>Risk contingency (P80)</TileLabel>
      {integrated ? (
        <>
          <div className="text-4xl font-bold mb-1 tabular" data-testid="contingency-p80">
            {formatAudMillions(integrated.p80_dollars)}
          </div>
          <div className="text-sm opacity-85">
            P50 {formatAudMillions(integrated.p50_dollars)} · P90{" "}
            {formatAudMillions(integrated.p90_dollars)}
          </div>
          <p className="text-xs opacity-70 mt-3">
            Allowance for risk events plus delay, enough in 8 of 10 outcomes. Excludes the base
            estimate.
          </p>
        </>
      ) : (
        <p className="text-sm opacity-85">{unavailableText(unavailableReason)}</p>
      )}
    </section>
  );
}

function FinishTile({ headline }: { headline: Headline }) {
  const behind = headline.p80_days_behind_plan;
  return (
    <section
      className="bg-white rounded-md border p-5"
      style={{ borderColor: "var(--color-card-border)" }}
      data-testid="tile-finish"
    >
      <TileLabel>Finish (P80)</TileLabel>
      <div className="text-2xl font-bold mb-1" data-testid="finish-p80">
        {formatLongDate(headline.p80_finish)}
      </div>
      <div
        className="text-sm"
        style={{ color: behind > 0 ? "var(--color-fired)" : "var(--color-muted)" }}
      >
        {behind === 0
          ? "On plan"
          : `${Math.abs(behind)} day${Math.abs(behind) === 1 ? "" : "s"} ${behind > 0 ? "behind" : "ahead of"} plan`}{" "}
        ({formatLongDate(headline.deterministic_finish)})
      </div>
      <div className="text-sm mt-1" style={{ color: "var(--color-muted)" }}>
        P50 {formatLongDate(headline.p50_finish)} · P90 {formatLongDate(headline.p90_finish)}
      </div>
    </section>
  );
}

function SinceLastPeriodTile({
  delta,
  previousPeriodEnd,
}: {
  delta: Delta;
  previousPeriodEnd: string | null;
}) {
  return (
    <section
      className="bg-white rounded-md border p-5"
      style={{ borderColor: "var(--color-card-border)" }}
      data-testid="tile-since-last"
    >
      <TileLabel>Since last period</TileLabel>
      {delta.period_0 ? (
        <p className="text-sm" style={{ color: "var(--color-muted)" }}>
          First period: nothing to compare yet.
        </p>
      ) : delta.p80_delta_dollars !== null ? (
        <>
          <div className="text-2xl font-bold mb-1" data-testid="since-last-movement">
            {formatAudMillionsDelta(delta.p80_delta_dollars)} ·{" "}
            {formatDaysDelta(delta.p80_delta_days)}
          </div>
          <div className="text-sm" style={{ color: "var(--color-muted)" }}>
            Contingency P80 and finish P80
            {previousPeriodEnd ? `, against ${formatLongDate(previousPeriodEnd)}` : ""}.
          </div>
        </>
      ) : (
        <>
          <div className="text-2xl font-bold mb-1" data-testid="since-last-movement">
            {formatDaysDelta(delta.p80_delta_days)}
          </div>
          <div className="text-sm" style={{ color: "var(--color-muted)" }}>
            Movement in the P80 finish. The previous period carried no contingency figure to
            compare.
          </div>
        </>
      )}
      <Link
        href="/changes/"
        className="inline-block text-sm font-medium mt-3 underline"
        style={{ color: "var(--color-accent-dark)" }}
      >
        What changed
      </Link>
    </section>
  );
}

/**
 * Tile 4 (INTVIEW-01 stage 2): the JCL on the report's basis, in the wireframe's words. Every
 * figure is `integrated.jcl`'s. Never blank: with no integrated block it says why it is empty.
 */
function OnBudgetAndOnTimeTile({ jcl }: { jcl?: IntegratedJcl }) {
  return (
    <section
      className="bg-white rounded-md border p-5"
      style={{ borderColor: "var(--color-card-border)" }}
      data-testid="tile-on-budget"
    >
      <TileLabel>On budget and on time</TileLabel>
      {jcl ? (
        <>
          <div className="text-2xl font-bold mb-1 tabular" data-testid="on-budget-jcl">
            {formatPercent(jcl.jcl, 0)}
          </div>
          <div className="text-sm" style={{ color: "var(--color-muted)" }}>
            Chance of finishing within {formatAudMillions(jcl.cost_target_dollars)}{" "}
            {jcl.base_drawn
              ? `(base plus P${jcl.p_level} contingency)`
              : `(the P${jcl.p_level} contingency; no base estimate drawn)`}{" "}
            and by the P80 date.
          </div>
          <div className="text-sm mt-2" style={{ color: "var(--color-muted)" }}>
            Budget alone {formatPercent(jcl.cost_confidence, 0)}, date alone{" "}
            {formatPercent(jcl.finish_confidence, 0)}. Delay cost is judged through the date, so
            it is not counted twice.
          </div>
          <Link
            href="/analyst/"
            className="inline-block text-sm font-medium mt-3 underline"
            style={{ color: "var(--color-accent-dark)" }}
          >
            How this is worked out
          </Link>
        </>
      ) : (
        <p className="text-sm" style={{ color: "var(--color-muted)" }}>
          Not available this period: it needs the risk contingency, which this period does not
          carry.
        </p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Local primitives
// ---------------------------------------------------------------------------

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

