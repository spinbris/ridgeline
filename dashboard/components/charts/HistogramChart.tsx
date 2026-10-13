/**
 * Histogram of project finish dates.
 *
 * Each bin is a date range emitted by the engine. Vertical bars,
 * bin start labelled on X-axis. Data from `distribution.histogram_bins`
 * (20 bins from the JSON writer).
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

import { formatShortDate } from "@/lib/formatters";
import type { HistogramBin } from "@/types/period";

export function HistogramChart({ bins }: { bins: HistogramBin[] }) {
  const data = bins.map((b) => ({
    label: formatShortDate(b.date_range_start),
    count: b.count,
    range: `${formatShortDate(b.date_range_start)} - ${formatShortDate(b.date_range_end)}`,
  }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart
        data={data}
        margin={{ top: 12, right: 12, bottom: 12, left: 0 }}
      >
        <CartesianGrid stroke="#f0f2f5" strokeDasharray="3 3" />
        <XAxis
          dataKey="label"
          stroke="var(--color-muted)"
          tick={{ fontSize: 10 }}
          tickLine={false}
          angle={-30}
          textAnchor="end"
          height={50}
        />
        <YAxis
          stroke="var(--color-muted)"
          tick={{ fontSize: 11 }}
          tickLine={false}
        />
        <Tooltip
          contentStyle={{
            background: "white",
            border: "1px solid var(--color-card-border)",
            borderRadius: 6,
            fontSize: 12,
          }}
          labelFormatter={(_v, payload) => {
            if (payload?.[0]?.payload?.range) return payload[0].payload.range;
            return "";
          }}
          formatter={(value) => {
            const v = typeof value === "number" ? value : 0;
            return [`${v.toLocaleString()} iterations`, "Count"];
          }}
        />
        <Bar
          dataKey="count"
          fill="var(--color-accent)"
          radius={[2, 2, 0, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
