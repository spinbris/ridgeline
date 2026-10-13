/**
 * SSI (Schedule Sensitivity Index) horizontal bar chart.
 *
 * Per-risk SSI = sum over affected activities of (finish_std * CI) /
 * project_finish_std. AM02.1 §3.A.3 implementation; per the
 * `per_risk_tornado_sigma` methodology note, this is the canonical
 * metric from AACE/PMBOK while tornado_sigma is a PERT proxy.
 */

"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Risk } from "@/types/period";

// AM04 Section 5A: render only live-status risks on the drivers charts
// (Director decision 2026-06-10: apply the same filter as the tornado).
// Fired / Closed rows are absent here but remain in risks[] and on the
// Risks register page.
const LIVE_STATUSES = new Set(["open", "actioned", "monitor"]);

export function SSIChart({ risks }: { risks: Risk[] }) {
  const sorted = [...risks]
    .filter((r) => LIVE_STATUSES.has(r.status))
    .sort((a, b) => b.ssi - a.ssi);
  const data = sorted.map((r) => ({
    label: r.risk_id,
    ssi: Number(r.ssi.toFixed(4)),
    title: r.title,
  }));
  const height = Math.max(220, data.length * 32);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        layout="vertical"
        data={data}
        margin={{ top: 8, right: 24, bottom: 8, left: 12 }}
      >
        <CartesianGrid stroke="#f0f2f5" strokeDasharray="3 3" />
        <XAxis
          type="number"
          stroke="var(--color-muted)"
          tick={{ fontSize: 11 }}
          tickLine={false}
          tickFormatter={(v: number) => v.toFixed(2)}
          label={{
            value: "SSI",
            position: "insideBottomRight",
            offset: -4,
            fill: "var(--color-muted)",
            fontSize: 11,
          }}
        />
        <YAxis
          type="category"
          dataKey="label"
          stroke="var(--color-muted)"
          tick={{ fontSize: 11 }}
          tickLine={false}
          width={70}
        />
        <Tooltip
          contentStyle={{
            background: "white",
            border: "1px solid var(--color-card-border)",
            borderRadius: 6,
            fontSize: 12,
          }}
          formatter={(value) => {
            const v = typeof value === "number" ? value : 0;
            return [v.toFixed(4), "SSI"];
          }}
          labelFormatter={(_v, payload) => {
            if (payload?.[0]?.payload?.title) {
              return `${payload[0].payload.label}: ${payload[0].payload.title}`;
            }
            return "";
          }}
        />
        <Bar
          dataKey="ssi"
          fill="var(--color-closed)"
          radius={[0, 3, 3, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
