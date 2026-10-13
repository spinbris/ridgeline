/**
 * S-curve: cumulative probability of project finish.
 *
 * X-axis: project finish date. Y-axis: cumulative probability 0-1.
 * Data from `distribution.s_curve_points`, which `src.am.json_writer`
 * emits as 21 points evenly spaced in PROBABILITY (0%, 5%, ... 100%) -
 * i.e. the inverse CDF (quantile dates). The distribution's shape lives
 * entirely in the spacing of the DATES, not the probabilities.
 *
 * Because of that, the X-axis MUST be a true time scale (type="number"
 * + scale="time"). If it is rendered as a categorical/band axis, the 21
 * points are placed at equal horizontal spacing, and equal X spacing
 * against the by-construction-even 5% Y steps collapses the curve into a
 * straight diagonal - identical for every period. A time-scaled X-axis
 * restores the real S shape (steep where finish dates cluster, flat in
 * the tails) and makes it respond to the selected "as at" period.
 *
 * The lower half can show a flat segment when many MC iterations
 * produce no-risk-fires outcomes; this is Curiosity 7 from AM02.1
 * smoke testing and is real engine behaviour. Page A1 surfaces the
 * disclosure callout via the Disclosure component.
 */

"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatShortDate } from "@/lib/formatters";
import type { SCurvePoint } from "@/types/period";

/** ISO YYYY-MM-DD -> UTC midnight timestamp (mirrors formatters.parseIsoDate). */
function isoToTs(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/** UTC timestamp -> ISO YYYY-MM-DD (for re-using the ISO-based formatters). */
function tsToIso(ts: number): string {
  return new Date(ts).toISOString().slice(0, 10);
}

export function SCurveChart({ points }: { points: SCurvePoint[] }) {
  const data = points.map((p) => ({
    ts: isoToTs(p.date),
    prob: p.cumulative_prob,
  }));

  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart
        data={data}
        margin={{ top: 12, right: 24, bottom: 12, left: 0 }}
      >
        <CartesianGrid stroke="#f0f2f5" strokeDasharray="3 3" />
        <XAxis
          dataKey="ts"
          type="number"
          scale="time"
          domain={["dataMin", "dataMax"]}
          stroke="var(--color-muted)"
          tick={{ fontSize: 11 }}
          tickLine={false}
          tickFormatter={(ts: number) => formatShortDate(tsToIso(ts))}
        />
        <YAxis
          domain={[0, 1]}
          stroke="var(--color-muted)"
          tick={{ fontSize: 11 }}
          tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
          tickLine={false}
        />
        <Tooltip
          contentStyle={{
            background: "white",
            border: "1px solid var(--color-card-border)",
            borderRadius: 6,
            fontSize: 12,
          }}
          labelFormatter={(ts) =>
            typeof ts === "number" ? formatShortDate(tsToIso(ts)) : ""
          }
          formatter={(value) => {
            const v = typeof value === "number" ? value : 0;
            return [`${(v * 100).toFixed(0)}%`, "Cumulative P"];
          }}
        />
        <Line
          type="monotone"
          dataKey="prob"
          stroke="var(--color-accent)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, fill: "var(--color-accent)" }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
