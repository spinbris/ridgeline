/**
 * Analyst Page A4 - Methodology audit.
 *
 * Mockup reference: #analyst-page-4.
 *
 * Sections:
 * - audit.config block (engine, iterations, sampling method, seed,
 *   cp_rule, p_level_reporting, cl_mode)
 * - audit.calibration_gates table (empty in v1; show empty state)
 * - audit.methodology_notes - one card per note. AM02.1 emits 5
 *   notes; the page renders them all with topic, method tag, and
 *   text body.
 * - Stage brief + reviewer fields
 */

"use client";

import { Card } from "@/components/Card";
import { PeriodGate } from "@/components/PeriodGate";
import { titleCase } from "@/lib/formatters";
import { usePeriodContext } from "@/lib/PeriodContext";

export default function AnalystA4() {
  return (
    <PeriodGate>
      <AnalystA4Content />
    </PeriodGate>
  );
}

function AnalystA4Content() {
  const { status } = usePeriodContext();
  if (status.kind !== "ready") return null;
  const { audit } = status.data;

  return (
    <main className="px-6 py-6 space-y-5 max-w-7xl mx-auto">
      <header>
        <h2 className="text-xl font-semibold">Methodology audit</h2>
        <p
          className="text-sm mt-1"
          style={{ color: "var(--color-muted)" }}
        >
          Engine configuration, calibration gates, methodology notes,
          and the run type for this period&apos;s run.
        </p>
      </header>

      <Card title="Engine configuration">
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          <Stat label="Engine" value={audit.config.engine} />
          <Stat
            label="Iterations"
            value={audit.config.iterations.toLocaleString()}
          />
          <Stat label="Sampling method" value={audit.config.sampling_method} />
          <Stat label="Seed" value={String(audit.config.seed)} />
          <Stat label="Critical-path rule" value={audit.config.cp_rule} />
          <Stat
            label="P-level reporting"
            value={`P${audit.config.p_level_reporting}`}
          />
          <Stat label="Criticality mode" value={audit.config.cl_mode} />
          <Stat label="Run type" value={audit.stage_brief} />
        </dl>
      </Card>

      <Card title="Calibration gates">
        {audit.calibration_gates.length === 0 ? (
          <p
            className="text-sm"
            style={{ color: "var(--color-muted)" }}
          >
            No calibration gates are recorded for this period.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr
                className="text-left text-[11px] uppercase tracking-wide font-semibold"
                style={{ color: "var(--color-muted)" }}
              >
                <th className="px-3 py-2">Check</th>
                <th className="px-3 py-2">Target</th>
                <th className="px-3 py-2">Actual</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {audit.calibration_gates.map((g, i) => (
                <tr
                  key={i}
                  className="border-t"
                  style={{ borderColor: "var(--color-card-border)" }}
                >
                  <td className="px-3 py-2">{g.check}</td>
                  <td className="px-3 py-2">{g.target}</td>
                  <td className="px-3 py-2 tabular">{g.actual}</td>
                  <td className="px-3 py-2 capitalize">{g.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <section className="space-y-3">
        <h3 className="text-sm font-semibold">
          Methodology notes ({audit.methodology_notes.length})
        </h3>
        {audit.methodology_notes.map((note) => (
          <article
            key={note.topic}
            className="bg-white rounded-md p-4"
            style={{ borderLeft: "3px solid var(--color-accent)" }}
          >
            <header className="flex items-center gap-2 mb-2">
              <h4
                className="text-sm font-semibold"
                style={{ color: "var(--color-accent)" }}
              >
                {titleCase(note.topic)}
              </h4>
              <span
                className="inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide"
                style={{
                  background: "var(--color-accent-soft)",
                  color: "var(--color-accent)",
                }}
              >
                {note.method}
              </span>
            </header>
            <p
              className="text-xs leading-relaxed"
              style={{ color: "var(--color-muted)" }}
            >
              {note.text}
            </p>
            {note.queued_for_v1_1 && (
              <p
                className="text-[11px] mt-2 italic"
                style={{ color: "var(--color-muted)" }}
              >
                Planned refinement: {note.queued_for_v1_1}
              </p>
            )}
          </article>
        ))}
      </section>

      <Card title="Reviewer">
        <div className="text-sm grid grid-cols-1 md:grid-cols-2 gap-3">
          <Stat label="Reviewer" value={audit.reviewer ?? "Not assigned"} />
          <Stat
            label="Reviewer approved date"
            value={audit.reviewer_approved_date ?? "-"}
          />
        </div>
      </Card>
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
      <div className="text-sm font-medium mt-1">{value}</div>
    </div>
  );
}
