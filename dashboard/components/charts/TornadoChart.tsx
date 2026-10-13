/**
 * Tornado chart - per-risk sigma_days.
 *
 * Horizontal bars; risks on the Y axis sorted by the chosen sigma
 * descending. AM04 / Doc 3 v2.4: the bar PREFERS the sample-based sigma
 * (`risks[].tornado_sample_sigma_days`, leave-one-out variance reduction)
 * and FALLS BACK to the PERT proxy (`risks[].tornado_sigma_days`) when the
 * sample value is null. The tooltip discloses which is shown per row.
 *
 * Negative sample sigmas (legitimate MC noise at the 10k-iter precision
 * floor) are clamped to 0 for bar LENGTH only; the tooltip shows the raw
 * figure. Resolved risks self-zero in the sample metric, and the chart is
 * additionally filtered to live-status risks (AM04 Section 5A) so it shows
 * only forward-looking drivers; the full register lives on the Risks page.
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

// AM04 Section 5A: render only live-status risks on the drivers charts.
const LIVE_STATUSES = new Set(["open", "actioned", "monitor"]);

export function TornadoChart({ risks }: { risks: Risk[] }) {
  const live = risks.filter((r) => LIVE_STATUSES.has(r.status));
  const data = live
    .map((r) => {
      const isSample = r.tornado_sample_sigma_days !== null;
      const raw = isSample
        ? (r.tornado_sample_sigma_days as number)
        : r.tornado_sigma_days;
      return {
        label: r.risk_id,
        raw: Number(raw.toFixed(2)),
        // Bar length clamped non-negative; raw kept for the tooltip.
        sigma: Number(Math.max(0, raw).toFixed(2)),
        isSample,
        title: r.title,
      };
    })
    .sort((a, b) => b.raw - a.raw);

  // Bound chart height to row count so the bars don't squish.
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
          label={{
            value: "Sigma (days)",
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
          formatter={(_value, _name, item) => {
            const p = item?.payload as
              | { raw?: number; isSample?: boolean }
              | undefined;
            const raw = typeof p?.raw === "number" ? p.raw : 0;
            const source = p?.isSample
              ? "sample-based"
              : "PERT proxy (fallback)";
            return [`${raw.toFixed(2)} days (${source})`, "Sigma"];
          }}
          labelFormatter={(_v, payload) => {
            if (payload?.[0]?.payload?.title) {
              return `${payload[0].payload.label}: ${payload[0].payload.title}`;
            }
            return "";
          }}
        />
        <Bar
          dataKey="sigma"
          fill="var(--color-accent)"
          radius={[0, 3, 3, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
