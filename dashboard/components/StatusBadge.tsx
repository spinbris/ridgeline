/**
 * Status pill matching the mockup's `.badge-*` classes.
 *
 * The mockup defines five risk statuses and three Mode-divergence
 * variants. Both use the same pill shape with palette swap.
 */

"use client";

import { statusBadgeKey } from "@/lib/formatters";

const STATUS_STYLES: Record<
  ReturnType<typeof statusBadgeKey>,
  { bg: string; fg: string; label: string }
> = {
  open: {
    bg: "var(--color-accent-soft)",
    fg: "var(--color-accent)",
    label: "Open",
  },
  actioned: {
    bg: "var(--color-actioned-bg)",
    fg: "var(--color-actioned-fg)",
    label: "Actioned",
  },
  monitor: {
    bg: "var(--color-monitor-bg)",
    fg: "var(--color-monitor-fg)",
    label: "Monitor",
  },
  fired: {
    bg: "var(--color-fired-soft-bg)",
    fg: "var(--color-fired-soft-fg)",
    label: "Fired",
  },
  closed: {
    bg: "var(--color-closed-soft-bg)",
    fg: "var(--color-closed-soft-fg)",
    label: "Closed",
  },
  proposed: {
    bg: "var(--color-accent-soft)",
    fg: "var(--color-accent)",
    label: "Proposed",
  },
  approved: {
    bg: "var(--color-actioned-bg)",
    fg: "var(--color-actioned-fg)",
    label: "Approved",
  },
  in_progress: {
    bg: "var(--color-monitor-bg)",
    fg: "var(--color-monitor-fg)",
    label: "In progress",
  },
  completed: {
    bg: "var(--color-closed-soft-bg)",
    fg: "var(--color-closed-soft-fg)",
    label: "Completed",
  },
  rejected: {
    bg: "#f0f2f5",
    fg: "var(--color-muted)",
    label: "Rejected",
  },
  neutral: {
    bg: "#f0f2f5",
    fg: "var(--color-muted)",
    label: "Not set",
  },
};

export function StatusBadge({ status }: { status: string }) {
  const key = statusBadgeKey(status);
  const style = STATUS_STYLES[key];
  // A status this map does not know is shown as the data states it, never as "Unknown".
  const label = key === "neutral" && status ? status : style.label;
  return (
    <span
      className="inline-block px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide"
      style={{ background: style.bg, color: style.fg }}
    >
      {label}
    </span>
  );
}
