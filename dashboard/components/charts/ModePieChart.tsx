/**
 * Mode summary - Series / Hybrid / Parallel proportions across the
 * full activity graph (counts from `activities.mode_summary`).
 *
 * Series share dominates the engagement V8/V9 today; Hybrid + Parallel are
 * usually 0. Counts come from the driver build (all in-scope the engagement
 * risks baseline to Series). The AM is Stage 3 only (AM07), so there is
 * no per-risk mode override on the workbook.
 */

"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import type { ModeSummary } from "@/types/period";

const COLORS = {
  series: "var(--color-accent)",
  hybrid: "#d97706", // amber matching the disclosure border
  parallel: "var(--color-closed)",
} as const;

export function ModePieChart({ summary }: { summary: ModeSummary }) {
  const data = [
    {
      name: "Series",
      value: summary.series,
      color: COLORS.series,
    },
    {
      name: "Hybrid",
      value: summary.hybrid,
      color: COLORS.hybrid,
    },
    {
      name: "Parallel",
      value: summary.parallel,
      color: COLORS.parallel,
    },
  ].filter((d) => d.value > 0);

  // Denominator for the pie's own percentages is the risk-linked subset
  // (series + hybrid + parallel), not summary.total (the full schedule
  // network activity count) - those are two different things and mixing
  // them understates the mix. See the caption in analyst/activities/page.tsx.
  const modeClassified = summary.series + summary.hybrid + summary.parallel;

  // Edge case: zero activities across all modes -> nothing to render.
  if (data.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--color-muted)" }}>
        No Mode-classified activities in the engine output for this
        period.
      </p>
    );
  }

  return (
    <div className="flex items-center gap-6">
      <ResponsiveContainer width={200} height={200}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            outerRadius={80}
            dataKey="value"
            isAnimationActive={false}
          >
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.color} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              background: "white",
              border: "1px solid var(--color-card-border)",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value, name) => {
              const v = typeof value === "number" ? value : 0;
              return [`${v.toLocaleString()} activities`, String(name)];
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      <ul className="text-sm space-y-1.5">
        {data.map((d) => (
          <li key={d.name} className="flex items-center gap-2">
            <span
              className="inline-block w-3 h-3 rounded-sm"
              style={{ background: d.color }}
            />
            <span className="font-medium">{d.name}</span>
            <span style={{ color: "var(--color-muted)" }}>
              {d.value.toLocaleString()} (
              {((d.value / modeClassified) * 100).toFixed(1)}%)
            </span>
          </li>
        ))}
        <li
          className="pt-1 mt-1 border-t text-xs"
          style={{
            borderColor: "var(--color-card-border)",
            color: "var(--color-muted)",
          }}
        >
          {modeClassified.toLocaleString()} risk-linked of{" "}
          {summary.total.toLocaleString()} activities total
        </li>
      </ul>
    </div>
  );
}
