/**
 * Stochastic Gantt: top-N activities with P10/P50/P90 finish bands
 * plus deterministic ES/EF reference markers.
 *
 * Built as a custom SVG component rather than via Recharts because
 * Recharts doesn't have a clean primitive for per-row min/max bands
 * + per-row reference lines (would need `ComposedChart` + per-bar
 * stacks + multiple `ReferenceLine`s with awkward y-offset math).
 * The hand-rolled SVG is ~80 lines and gives us full control over
 * the band + marker visual language.
 *
 * Layout:
 *   activity name | P10 ......... P50 .......... P90
 *                       det ES |---- det EF
 *
 * Per AM02.1 §4.B.2, the engine pre-filters items to non-zero
 * finish-time variance, so collapsed (P10==P90) bands shouldn't
 * appear here in normal operation. Defensive guard renders a thin
 * marker if a degenerate row sneaks through.
 */

"use client";

import type { ActivityItem } from "@/types/period";

interface StochasticGanttProps {
  items: ActivityItem[];
  /** When set, surfaces "Showing X of N slots" beneath the chart. */
  topNRequested?: number;
  height?: number;
}

const ROW_HEIGHT = 28;
const ROW_GAP = 8;
const LABEL_WIDTH = 220;
const LEFT_PADDING = 8;
const RIGHT_PADDING = 16;
const AXIS_HEIGHT = 24;

export function StochasticGantt({
  items,
  topNRequested,
  height,
}: StochasticGanttProps) {
  const filterAnnotation =
    topNRequested !== undefined && items.length < topNRequested
      ? `Showing ${items.length} of ${topNRequested} top-N slots. ${
          topNRequested - items.length
        } activit${topNRequested - items.length === 1 ? "y" : "ies"} left out because no risk moves them (their P-bands collapse to a single point, which is uninformative).`
      : null;
  if (items.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--color-muted)" }}>
        No activities meet the top-N + non-zero-variance criteria for
        this period. The top-N list leaves out always-critical anchor
        activities, whose P-bands collapse to a single point; if the
        risk register doesn&apos;t currently touch high-CI activities,
        the list may be empty.
      </p>
    );
  }

  const computedHeight =
    height ??
    AXIS_HEIGHT + items.length * (ROW_HEIGHT + ROW_GAP) + 12;

  // Time-axis bounds across all start P10 and finish P90 (plus a
  // small pad). Falls back gracefully if det_es/det_ef are absent
  // (Doc 3 v2.3 allows null).
  const allValues: number[] = [];
  items.forEach((it) => {
    allValues.push(it.p10_start_days, it.p90_finish_days);
    if (it.det_es_days !== null) allValues.push(it.det_es_days);
    if (it.det_ef_days !== null) allValues.push(it.det_ef_days);
  });
  const minDay = Math.min(...allValues);
  const maxDay = Math.max(...allValues);
  const padding = (maxDay - minDay) * 0.05 || 1;
  const lo = Math.max(0, minDay - padding);
  const hi = maxDay + padding;

  return (
    <div className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 800 ${computedHeight}`}
        width="100%"
        height={computedHeight}
        style={{ minWidth: 640 }}
        role="img"
        aria-label="Stochastic Gantt: top activities by criticality with P10/P50/P90 finish bands and deterministic ES/EF markers"
      >
        {(() => {
          const chartLeft = LABEL_WIDTH + LEFT_PADDING;
          const chartRight = 800 - RIGHT_PADDING;
          const chartWidth = chartRight - chartLeft;

          const xFor = (day: number) =>
            chartLeft + ((day - lo) / (hi - lo)) * chartWidth;

          // Axis tick marks every ~5 ticks across the range.
          const tickCount = 5;
          const tickStep = (hi - lo) / (tickCount - 1);
          const ticks = Array.from({ length: tickCount }, (_, i) => lo + i * tickStep);

          return (
            <>
              {/* Time axis at the top */}
              <g>
                <line
                  x1={chartLeft}
                  y1={AXIS_HEIGHT - 4}
                  x2={chartRight}
                  y2={AXIS_HEIGHT - 4}
                  stroke="#e3e6eb"
                />
                {ticks.map((t, i) => (
                  <g key={i}>
                    <line
                      x1={xFor(t)}
                      y1={AXIS_HEIGHT - 4}
                      x2={xFor(t)}
                      y2={AXIS_HEIGHT - 1}
                      stroke="#e3e6eb"
                    />
                    <text
                      x={xFor(t)}
                      y={AXIS_HEIGHT - 8}
                      textAnchor="middle"
                      fontSize="10"
                      fill="var(--color-muted)"
                    >
                      {Math.round(t)}d
                    </text>
                  </g>
                ))}
                <text
                  x={chartLeft - 4}
                  y={AXIS_HEIGHT - 8}
                  textAnchor="end"
                  fontSize="10"
                  fill="var(--color-muted)"
                >
                  Project days
                </text>
              </g>

              {/* Rows */}
              {items.map((it, idx) => {
                const y = AXIS_HEIGHT + idx * (ROW_HEIGHT + ROW_GAP);
                const cy = y + ROW_HEIGHT / 2;

                const x10 = xFor(it.p10_finish_days);
                const x50 = xFor(it.p50_finish_days);
                const x90 = xFor(it.p90_finish_days);
                const bandWidth = Math.max(2, x90 - x10);

                const detEs =
                  it.det_es_days !== null ? xFor(it.det_es_days) : null;
                const detEf =
                  it.det_ef_days !== null ? xFor(it.det_ef_days) : null;

                // Truncate long names with an ellipsis at ~28 chars.
                const labelText =
                  it.name.length > 32
                    ? it.name.slice(0, 30) + "..."
                    : it.name;

                return (
                  <g key={it.activity_id}>
                    {/* Row background guide */}
                    <line
                      x1={chartLeft}
                      y1={cy}
                      x2={chartRight}
                      y2={cy}
                      stroke="#f4f5f7"
                    />

                    {/* Activity label (left column) */}
                    <text
                      x={LABEL_WIDTH}
                      y={cy + 4}
                      textAnchor="end"
                      fontSize="11"
                      fill="var(--color-body)"
                    >
                      {labelText}
                    </text>

                    {/* P10-P90 band */}
                    <rect
                      x={x10}
                      y={cy - 7}
                      width={bandWidth}
                      height={14}
                      fill="var(--color-accent-soft)"
                      stroke="var(--color-accent)"
                      strokeWidth="1"
                      rx="2"
                    />
                    {/* P50 marker */}
                    <line
                      x1={x50}
                      y1={cy - 9}
                      x2={x50}
                      y2={cy + 9}
                      stroke="var(--color-accent)"
                      strokeWidth="2"
                    />

                    {/* Deterministic ES/EF markers (diamonds) */}
                    {detEs !== null && (
                      <polygon
                        points={`${detEs - 4},${cy} ${detEs},${cy - 4} ${detEs + 4},${cy} ${detEs},${cy + 4}`}
                        fill="var(--color-fired)"
                      >
                        <title>Deterministic ES: {it.det_es_days}d</title>
                      </polygon>
                    )}
                    {detEf !== null && (
                      <polygon
                        points={`${detEf - 4},${cy} ${detEf},${cy - 4} ${detEf + 4},${cy} ${detEf},${cy + 4}`}
                        fill="var(--color-closed)"
                      >
                        <title>Deterministic EF: {it.det_ef_days}d</title>
                      </polygon>
                    )}

                    {/* CI badge on the far right */}
                    <text
                      x={chartRight + 4}
                      y={cy + 4}
                      fontSize="10"
                      fill="var(--color-muted)"
                      textAnchor="start"
                    >
                      {(it.criticality_index * 100).toFixed(0)}%
                    </text>
                  </g>
                );
              })}
            </>
          );
        })()}
      </svg>

      {/* Legend */}
      <div
        className="flex flex-wrap items-center gap-4 mt-3 text-xs"
        style={{ color: "var(--color-muted)" }}
      >
        <LegendItem swatch={<BandSwatch />} label="P10 - P90 finish band" />
        <LegendItem
          swatch={
            <span
              className="inline-block w-0.5 h-3"
              style={{ background: "var(--color-accent)" }}
            />
          }
          label="P50 median"
        />
        <LegendItem
          swatch={
            <span
              className="inline-block w-2.5 h-2.5"
              style={{
                background: "var(--color-fired)",
                clipPath: "polygon(50% 0, 100% 50%, 50% 100%, 0 50%)",
              }}
            />
          }
          label="Deterministic ES"
        />
        <LegendItem
          swatch={
            <span
              className="inline-block w-2.5 h-2.5"
              style={{
                background: "var(--color-closed)",
                clipPath: "polygon(50% 0, 100% 50%, 50% 100%, 0 50%)",
              }}
            />
          }
          label="Deterministic EF"
        />
      </div>

      {filterAnnotation && (
        <p
          className="text-xs italic mt-2"
          style={{ color: "var(--color-muted)" }}
        >
          {filterAnnotation}
        </p>
      )}

      {/* Visually-hidden table for screen readers. Mirrors the SVG
          content so non-visual consumers can read every row's values. */}
      <table className="sr-only">
        <caption>
          Stochastic Gantt - top activities by criticality. Each row
          shows P10, P50, P90 finish in working days plus
          deterministic ES and EF.
        </caption>
        <thead>
          <tr>
            <th scope="col">Activity</th>
            <th scope="col">Criticality index</th>
            <th scope="col">P10 finish (days)</th>
            <th scope="col">P50 finish (days)</th>
            <th scope="col">P90 finish (days)</th>
            <th scope="col">Deterministic ES (days)</th>
            <th scope="col">Deterministic EF (days)</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={`sr-${it.activity_id}`}>
              <th scope="row">{it.name}</th>
              <td>{(it.criticality_index * 100).toFixed(1)}%</td>
              <td>{it.p10_finish_days.toFixed(1)}</td>
              <td>{it.p50_finish_days.toFixed(1)}</td>
              <td>{it.p90_finish_days.toFixed(1)}</td>
              <td>{it.det_es_days?.toFixed(1) ?? "n/a"}</td>
              <td>{it.det_ef_days?.toFixed(1) ?? "n/a"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BandSwatch() {
  return (
    <span
      className="inline-block w-6 h-3 rounded-sm"
      style={{
        background: "var(--color-accent-soft)",
        border: "1px solid var(--color-accent)",
      }}
    />
  );
}

function LegendItem({
  swatch,
  label,
}: {
  swatch: React.ReactNode;
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {swatch}
      {label}
    </span>
  );
}
