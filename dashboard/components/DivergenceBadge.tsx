/**
 * Pill displaying the per-risk Mode-divergence flag.
 *
 * AM10 (WIND-01 A4): DORMANT / unrendered. The `divergence_flag` field was
 * removed from the JSON contract (Doc 3 v2.5) and no page imports this
 * component now - under the pure-MC AM basis the flag was structurally
 * constant "consistent". Retained (not deleted) as the revival surface for
 * the deferred WIND-01b Mode-sensitivity (apply=True) run, mirroring
 * ModePieChart.tsx. Do not delete without retiring WIND-01b.
 *
 * Values map per AM02.1 §3.A.3 divergence_flag rule:
 * - "consistent" -> neutral grey
 * - "mode_amplifies" -> red (mode multiplier inflates CI)
 * - "mode_suppresses" -> green (mode multiplier dampens CI)
 *
 * Doc 3 v2.3 documents the +/-0.05 threshold used at the engine.
 */

"use client";

import type { DivergenceFlag } from "@/types/period";

const STYLES: Record<
  DivergenceFlag,
  { bg: string; fg: string; label: string }
> = {
  consistent: {
    bg: "#f0f2f5",
    fg: "var(--color-muted)",
    label: "Consistent",
  },
  mode_amplifies: {
    bg: "var(--color-fired-soft-bg)",
    fg: "var(--color-fired-soft-fg)",
    label: "Mode amplifies",
  },
  mode_suppresses: {
    bg: "var(--color-closed-soft-bg)",
    fg: "var(--color-closed-soft-fg)",
    label: "Mode suppresses",
  },
};

export function DivergenceBadge({ flag }: { flag: DivergenceFlag }) {
  const style = STYLES[flag];
  return (
    <span
      className="inline-block px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide"
      style={{ background: style.bg, color: style.fg }}
    >
      {style.label}
    </span>
  );
}
