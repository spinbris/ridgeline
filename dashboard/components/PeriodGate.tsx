/**
 * Wraps a page in a loading / error / ready gate.
 *
 * Returns the children only when PeriodContext is in the `ready`
 * state. Loading shows a skeleton; error shows a readable failure
 * card with the validation message verbatim.
 */

"use client";

import type { ReactNode } from "react";

import { usePeriodContext } from "@/lib/PeriodContext";

export function PeriodGate({ children }: { children: ReactNode }) {
  const { status } = usePeriodContext();

  if (status.kind === "loading") {
    return (
      <main className="px-6 py-10">
        <div
          className="max-w-md mx-auto bg-white rounded-md p-6 border"
          style={{ borderColor: "var(--color-card-border)" }}
        >
          <p style={{ color: "var(--color-muted)" }}>
            Loading period data...
          </p>
        </div>
      </main>
    );
  }

  if (status.kind === "error") {
    return (
      <main className="px-6 py-10">
        <div
          className="max-w-2xl mx-auto bg-white rounded-md p-6 border"
          style={{
            borderColor: "var(--color-fired)",
            borderLeftWidth: "4px",
          }}
        >
          <h2 className="text-base font-semibold mb-2" style={{ color: "var(--color-fired)" }}>
            Failed to load period data
          </h2>
          <pre className="text-xs whitespace-pre-wrap" style={{ color: "var(--color-muted)" }}>
            {status.message}
          </pre>
          <p className="text-xs mt-3" style={{ color: "var(--color-muted)" }}>
            Confirm `npm run prebuild` has copied period_YYYYMMDD.json
            files into public/data/ and that they validate against the
            period data contract.
          </p>
        </div>
      </main>
    );
  }

  return <>{children}</>;
}
