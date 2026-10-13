/**
 * Amber-bordered disclosure callout (mockup .disclosure class).
 *
 * Used on Analyst Page A1 for the Curiosity 7 note about flat
 * S-curve segments under low-firing risk registers.
 */

import type { ReactNode } from "react";

export function Disclosure({
  label = "Note",
  children,
}: {
  label?: string;
  children: ReactNode;
}) {
  return (
    <div
      className="rounded-md p-3 text-xs"
      style={{
        background: "var(--color-disclosure-bg)",
        color: "var(--color-disclosure-fg)",
        borderLeft: "3px solid var(--color-disclosure-border)",
      }}
    >
      <strong style={{ color: "var(--color-disclosure-strong)" }}>
        {label}:
      </strong>{" "}
      {children}
    </div>
  );
}
