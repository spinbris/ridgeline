/**
 * Analyst Page A2 - Drivers & sensitivity.
 *
 * Mockup reference: #analyst-page-2.
 *
 * Sections:
 * - Tornado chart (per-risk sigma_days proxy)
 * - SSI bars (Schedule Sensitivity Index per risk)
 * - Notes panel with brief metric definitions
 *
 * AM10 (WIND-01 A4): the per-risk Mode-divergence pill table was removed -
 * divergence_flag is dropped from the contract (Doc 3 v2.5).
 */

"use client";

import { SSIChart } from "@/components/charts/SSIChart";
import { TornadoChart } from "@/components/charts/TornadoChart";
import { Card } from "@/components/Card";
import { PeriodGate } from "@/components/PeriodGate";
import { usePeriodContext } from "@/lib/PeriodContext";

export default function AnalystA2() {
  return (
    <PeriodGate>
      <AnalystA2Content />
    </PeriodGate>
  );
}

function AnalystA2Content() {
  const { status } = usePeriodContext();
  if (status.kind !== "ready") return null;
  const { risks } = status.data;

  return (
    <main className="px-6 py-6 space-y-5 max-w-7xl mx-auto">
      <header>
        <h2 className="text-xl font-semibold">Drivers & sensitivity</h2>
        <p
          className="text-sm mt-1"
          style={{ color: "var(--color-muted)" }}
        >
          Per-risk sigma proxy (tornado) and Schedule Sensitivity Index
          for the dual-coded risks.
        </p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Tornado: per-risk sigma_days (sample-based, PERT fallback)">
          <TornadoChart risks={risks} />
        </Card>
        <Card title="Schedule Sensitivity Index per risk">
          <SSIChart risks={risks} />
        </Card>
      </div>

      {/* AM10 (WIND-01 A4): the "Mode-divergence per risk" Card was removed -
          divergence_flag is dropped from the contract (Doc 3 v2.5); under the
          pure-MC AM basis the two CIs coincide so the pill was always
          "consistent". The Mode-conditioned / Mode-independent CIs remain on
          the Risks detail page. The DivergenceBadge component is retained for
          the deferred WIND-01b Mode-sensitivity run. */}

      <Card title="Metric definitions">
        <dl
          className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs"
          style={{ color: "var(--color-muted)" }}
        >
          <div>
            <dt
              className="font-semibold mb-1 uppercase tracking-wide text-[10px]"
              style={{ color: "var(--color-body)" }}
            >
              SSI
            </dt>
            <dd>
              Per-activity (finish_std * CI) / project_finish_std,
              aggregated per risk via affected_activity_ids per the
              AACE/PMBOK definition. Higher SSI = higher project
              sensitivity to the risk&apos;s finish-time variance and
              critical-path occupancy.
            </dd>
          </div>
          <div>
            <dt
              className="font-semibold mb-1 uppercase tracking-wide text-[10px]"
              style={{ color: "var(--color-body)" }}
            >
              Tornado sigma
            </dt>
            <dd>
              Primary: a sample-based per-risk sigma (working days), the
              marginal contribution of each risk to project-finish
              standard deviation by leave-one-out (std of finish minus
              std of finish with the risk forced Closed), off the same
              10k-iteration re-runs that produce days-at-risk. It
              responds to per-period status: resolved risks self-zero
              and drop to the bottom. Fallback: the PERT proxy
              probability * (pess - opt) / 6 (model-based, status-blind),
              shown when no sample value exists; the tooltip labels which
              is which. Caveats: non-additive (per-risk sigmas do not sum
              to total project sigma), at the 10k precision floor
              (approximately 0.3 days; small negatives are MC noise and
              the bar is clamped at 0). The chart is filtered to live
              risks (Open / Actioned / Monitor); the full register lives
              on the Risks page. The textbook within-run variance
              decomposition (AACE 57R-09 Tier 3) is not yet implemented;
              it would need engine-side support.
            </dd>
          </div>
        </dl>
      </Card>
    </main>
  );
}
