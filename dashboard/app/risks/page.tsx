/**
 * PM Page 2 — What's driving risk.
 *
 * Mockup reference: #pm-page-2.
 *
 * Single risk table sorted by `days_at_risk_p80` descending (the
 * JSON arrives pre-sorted per Doc 3 v2.3 rule 4; we display in
 * received order). Columns: Risk ID, title, owner, status badge,
 * probability, days_at_risk_p80, EMV impact, mode.
 *
 * Click a row to expand a detail panel showing the AM02.1-added
 * fields: context, ssi, cruciality_proxy_p80, tornado_sigma_days,
 * criticality_conditioned + criticality_independent (AM10: divergence_flag
 * removed from the contract, Doc 3 v2.5).
 */

"use client";

import { useState } from "react";

import { PeriodGate } from "@/components/PeriodGate";
import { StatusBadge } from "@/components/StatusBadge";
import { formatPercent } from "@/lib/formatters";
import { usePeriodContext } from "@/lib/PeriodContext";
import type { Risk } from "@/types/period";

export default function PmPage2() {
  return (
    <PeriodGate>
      <PmPage2Content />
    </PeriodGate>
  );
}

function PmPage2Content() {
  const { status } = usePeriodContext();
  const [expanded, setExpanded] = useState<string | null>(null);

  if (status.kind !== "ready") return null;
  const risks = status.data.risks;

  return (
    <main className="px-6 py-6 space-y-5 max-w-7xl mx-auto">
      <header>
        <h2 className="text-xl font-semibold">What&apos;s driving risk</h2>
        <p
          className="text-sm mt-1"
          style={{ color: "var(--color-muted)" }}
        >
          Risks ranked by days_at_risk_p80 (impact on the headline
          forecast). Click a row for detail.
        </p>
      </header>

      <section
        className="bg-white rounded-md border overflow-hidden"
        style={{ borderColor: "var(--color-card-border)" }}
      >
        <table className="w-full text-sm">
          <thead>
            <tr
              className="text-left text-[11px] uppercase tracking-wide font-semibold"
              style={{
                background: "#fafbfc",
                color: "var(--color-muted)",
              }}
            >
              <th className="px-3 py-2.5">Risk ID</th>
              <th className="px-3 py-2.5">Title</th>
              <th className="px-3 py-2.5">Owner</th>
              <th className="px-3 py-2.5">Status</th>
              <th className="px-3 py-2.5 text-right">Probability</th>
              <th className="px-3 py-2.5 text-right">
                Days @ Risk (P80)
              </th>
              <th className="px-3 py-2.5 text-right">EMV impact</th>
              <th className="px-3 py-2.5">Mode</th>
            </tr>
          </thead>
          <tbody>
            {risks.map((r) => (
              <RiskRow
                key={r.risk_id}
                risk={r}
                expanded={expanded === r.risk_id}
                onToggle={() =>
                  setExpanded((prev) => (prev === r.risk_id ? null : r.risk_id))
                }
              />
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}

function RiskRow({
  risk,
  expanded,
  onToggle,
}: {
  risk: Risk;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        className="border-t cursor-pointer hover:bg-[#fafbfc] transition-colors focus-within:outline-2 focus-within:outline-[var(--color-accent)]"
        style={{ borderColor: "var(--color-card-border)" }}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
        tabIndex={0}
        role="button"
        aria-expanded={expanded}
        aria-label={`Toggle details for risk ${risk.risk_id}: ${risk.title}`}
      >
        <td className="px-3 py-2.5 font-mono text-xs">{risk.risk_id}</td>
        <td className="px-3 py-2.5">{risk.title}</td>
        <td className="px-3 py-2.5">{risk.owner}</td>
        <td className="px-3 py-2.5">
          <StatusBadge status={risk.status} />
        </td>
        <td className="px-3 py-2.5 text-right tabular">
          {formatPercent(risk.probability)}
        </td>
        <td className="px-3 py-2.5 text-right tabular font-semibold">
          {risk.days_at_risk_p80.toFixed(1)}
        </td>
        <td className="px-3 py-2.5 text-right tabular">
          {risk.impact_days_emv.toFixed(1)}d
        </td>
        <td className="px-3 py-2.5">{risk.mode}</td>
      </tr>
      {expanded && (
        <tr
          className="border-t"
          style={{
            borderColor: "var(--color-card-border)",
            background: "#fafbfc",
          }}
        >
          <td colSpan={8} className="px-3 py-4">
            <RiskDetail risk={risk} />
          </td>
        </tr>
      )}
    </>
  );
}

function RiskDetail({ risk }: { risk: Risk }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
      <div>
        <DetailLabel>Context</DetailLabel>
        <p className="text-sm mt-1">
          {risk.context.trim() || (
            <em style={{ color: "var(--color-muted)" }}>
              No context recorded for this period.
            </em>
          )}
        </p>
      </div>
      <div className="space-y-2">
        <Stat
          label="SSI (schedule sensitivity index)"
          value={risk.ssi.toFixed(4)}
        />
        <Stat
          label="Cruciality proxy (P80)"
          value={formatPercent(risk.cruciality_proxy_p80)}
        />
        <Stat
          label="Tornado sigma (days)"
          value={risk.tornado_sigma_days.toFixed(2)}
        />
        <Stat
          label="Criticality (Mode-conditioned)"
          value={
            risk.criticality_conditioned !== null
              ? risk.criticality_conditioned.toFixed(3)
              : "n/a"
          }
        />
        <Stat
          label="Criticality (Mode-independent)"
          value={
            risk.criticality_independent !== null
              ? risk.criticality_independent.toFixed(3)
              : "n/a (engine ran Mode-conditioned only)"
          }
        />
        {/* AM10 (WIND-01 A4): "Mode-divergence flag" Stat removed -
            divergence_flag dropped from the contract (Doc 3 v2.5). */}
        {risk.cg_code && (
          <Stat label="CG correlation code" value={risk.cg_code} />
        )}
      </div>
    </div>
  );
}

function DetailLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-[10px] uppercase tracking-wider font-semibold"
      style={{ color: "var(--color-muted)" }}
    >
      {children}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-baseline gap-3">
      <span
        className="text-[11px]"
        style={{ color: "var(--color-muted)" }}
      >
        {label}
      </span>
      <span className="tabular text-sm font-medium">{value}</span>
    </div>
  );
}
