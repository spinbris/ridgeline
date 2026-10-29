/**
 * Integrated S-curve: cumulative probability of the integrated event-risk cost (contract 1.5).
 *
 * The cost twin of `SCurveChart`. Data from `integrated.curve_points`, which `src.am.json_writer`
 * emits as 21 points evenly spaced in PROBABILITY, so the X-axis MUST be numeric for the same
 * reason the finish chart's is a time scale: a category axis would draw every period as one
 * straight diagonal. Dollars are the engine's own (cost + delay days x day rate); the app plots
 * them and computes nothing.
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

import { formatAud } from "@/lib/formatters";
import type { IntegratedCurvePoint } from "@/types/period";

/** 7480000 -> "$7.5M", the axis's compact form; the tooltip carries the whole figure. */
function millions(n: number): string {
  return `$${(n / 1e6).toFixed(1)}M`;
}

export function IntegratedSCurveChart({ points }: { points: IntegratedCurvePoint[] }) {
  const data = points.map((p) => ({ dollars: p.dollars, prob: p.cumulative_prob }));

  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data} margin={{ top: 12, right: 24, bottom: 12, left: 0 }}>
        <CartesianGrid stroke="#f0f2f5" strokeDasharray="3 3" />
        <XAxis
          dataKey="dollars"
          type="number"
          domain={["dataMin", "dataMax"]}
          stroke="var(--color-muted)"
          tick={{ fontSize: 11 }}
          tickLine={false}
          tickFormatter={millions}
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
          labelFormatter={(d) => (typeof d === "number" ? formatAud(d) : "")}
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
