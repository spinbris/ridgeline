/**
 * Analyst Page A3 - Activity-level detail.
 *
 * Mockup reference: #analyst-page-3.
 *
 * Sections:
 * - Stochastic Gantt: top-N activities with P10/P50/P90 bands +
 *   det ES/EF markers (AM02.1 §4.B.2 non-zero variance filter
 *   applied upstream)
 * - CP stats panel: 8 scalar metrics on activity-level criticality
 * - p_band_derivation_method readout
 *
 * WIND-01: the Mode-summary pie chart is removed. Mode (Series / Hybrid /
 * Parallel) is a Tier-2.5 register classification; under the pure-MC
 * (AACE 65R-11, apply_mode_multipliers=False) headline it does not act on
 * the result, so it is not shown. The ModePieChart component is retained
 * for the deferred WIND-01b Mode-sensitivity side-analysis, its natural
 * home. The activity criticality view is the Stochastic Gantt above.
 */

"use client";

import { StochasticGantt } from "@/components/charts/StochasticGantt";
import { Card } from "@/components/Card";
import { PeriodGate } from "@/components/PeriodGate";
import { usePeriodContext } from "@/lib/PeriodContext";

const METHOD_LABELS: Record<string, string> = {
  A: "Method A - direct per-iteration percentiles (not yet available)",
  B: "Method B - lognormal moment-fit from per-activity Mean and std",
  C: "Method C - PERT-equivalent fallback from deterministic ES/EF + CI",
};

export default function AnalystA3() {
  return (
    <PeriodGate>
      <AnalystA3Content />
    </PeriodGate>
  );
}

function AnalystA3Content() {
  const { status } = usePeriodContext();
  if (status.kind !== "ready") return null;
  const { activities } = status.data;
  const stats = activities.cp_stats;
  const methodLabel =
    METHOD_LABELS[activities.p_band_derivation_method] ??
    activities.p_band_derivation_method;

  return (
    <main className="px-6 py-6 space-y-5 max-w-7xl mx-auto">
      <header>
        <h2 className="text-xl font-semibold">Activity-level detail</h2>
        <p
          className="text-sm mt-1"
          style={{ color: "var(--color-muted)" }}
        >
          Top-{activities.top_n_by_ci} activities by criticality index
          (activities that no risk moves are left out). P-band
          derivation: {methodLabel}.
        </p>
      </header>

      <Card title="Stochastic Gantt - top activities by criticality">
        <StochasticGantt
          items={activities.items}
          topNRequested={activities.top_n_by_ci}
        />
      </Card>

      <div className="grid grid-cols-1 gap-4">
        <Card title="Critical-path statistics">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <Stat
              label="Activities on det CP"
              value={stats.activities_on_det_cp.toLocaleString()}
            />
            <Stat
              label="Activities CI > 50%"
              value={stats.activities_ci_gt_50.toLocaleString()}
            />
            <Stat
              label="Activities CI > 80%"
              value={stats.activities_ci_gt_80.toLocaleString()}
            />
            <Stat
              label="Stochastic CP additions"
              value={stats.stochastic_cp_additions.toLocaleString()}
            />
            <Stat
              label="Longest path P80"
              value={`${stats.longest_path_p80_days.toFixed(1)}d`}
            />
            <Stat
              label="Zero-float activities"
              value={stats.zero_float_activities.toLocaleString()}
            />
            <Stat
              label="Mean activity float"
              value={`${stats.mean_activity_float_days.toFixed(1)}d`}
            />
            <Stat
              label="Float sigma"
              value={`${stats.float_sigma_days.toFixed(1)}d`}
            />
          </dl>
        </Card>
      </div>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="bg-white rounded-md border p-3"
      style={{ borderColor: "var(--color-card-border)" }}
    >
      <div
        className="text-[10px] uppercase tracking-wider font-semibold"
        style={{ color: "var(--color-muted)" }}
      >
        {label}
      </div>
      <div className="text-lg font-bold mt-1 tabular">{value}</div>
    </div>
  );
}
