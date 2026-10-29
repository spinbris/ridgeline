/**
 * Analyst Page A1 - Distribution & convergence.
 *
 * Mockup reference: #analyst-page-1.
 *
 * Sections:
 * - S-curve: 21-point cumulative-probability line chart, with the integrated
 *   cost S-curve beside it and the joint confidence level (contract 1.5)
 * - Histogram: 20-bin finish-date distribution
 * - Percentile table: P10-P95 with days_from_start, calendar date,
 *   and delta_vs_det column
 */

"use client";

import { SCurveChart } from "@/components/charts/SCurveChart";
import { IntegratedSCurveChart } from "@/components/charts/IntegratedSCurveChart";
import { JointConfidenceNote } from "@/components/JointConfidenceNote";
import { HistogramChart } from "@/components/charts/HistogramChart";
import { Card } from "@/components/Card";
import { PeriodGate } from "@/components/PeriodGate";
import {
  formatDaysDelta,
  formatLongDate,
} from "@/lib/formatters";
import { usePeriodContext } from "@/lib/PeriodContext";

export default function AnalystA1() {
  return (
    <PeriodGate>
      <AnalystA1Content />
    </PeriodGate>
  );
}

function AnalystA1Content() {
  const { status } = usePeriodContext();
  if (status.kind !== "ready") return null;
  const { distribution, meta, integrated } = status.data;

  return (
    <main className="px-6 py-6 space-y-5 max-w-7xl mx-auto">
      <header>
        <h2 className="text-xl font-semibold">
          Distribution & convergence
        </h2>
        <p
          className="text-sm mt-1"
          style={{ color: "var(--color-muted)" }}
        >
          Full S-curve, histogram, and percentile table from the{" "}
          {meta.iterations.toLocaleString()}-iteration MC.
        </p>
      </header>

      {/* Contract 1.5 (INTSCURVE-01 Part C): the integrated cost S-curve beside the finish
          one, as the report draws them. Absent block, finish curve alone. */}
      <div className={integrated ? "grid gap-5 lg:grid-cols-2" : ""}>
        <Card title="S-curve: cumulative probability of project finish">
          <SCurveChart points={distribution.s_curve_points} />
        </Card>
        {integrated && (
          <Card title="S-curve: integrated event-risk cost (cost + delay cost)">
            <IntegratedSCurveChart points={integrated.curve_points} />
          </Card>
        )}
      </div>

      {integrated && (
        <Card title="Joint confidence: cost and finish together">
          <JointConfidenceNote jcl={integrated.jcl} />
        </Card>
      )}

      <Card title="Histogram: project finish distribution">
        <HistogramChart bins={distribution.histogram_bins} />
      </Card>

      <Card title="Percentile table">
        <table className="w-full text-sm">
          <thead>
            <tr
              className="text-left text-[11px] uppercase tracking-wide font-semibold"
              style={{ color: "var(--color-muted)" }}
            >
              <th className="px-3 py-2">Percentile</th>
              <th className="px-3 py-2 text-right">Days from start</th>
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2 text-right">Delta vs det</th>
            </tr>
          </thead>
          <tbody>
            {distribution.percentile_table.map((r) => (
              <tr
                key={r.percentile}
                className="border-t"
                style={{ borderColor: "var(--color-card-border)" }}
              >
                <td className="px-3 py-2 font-semibold">P{r.percentile}</td>
                <td className="px-3 py-2 text-right tabular">
                  {r.days_from_start.toFixed(1)}
                </td>
                <td className="px-3 py-2">{formatLongDate(r.date)}</td>
                <td className="px-3 py-2 text-right tabular">
                  {formatDaysDelta(r.delta_vs_det)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </main>
  );
}
