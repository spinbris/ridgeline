/**
 * Shared white-card primitive used across PM + Analyst pages.
 *
 * Single card style; consumers pass an optional title and any
 * children. Matches the mockup's `.card` class.
 */

import type { ReactNode } from "react";

export function Card({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`bg-white rounded-md border p-4 ${className}`}
      style={{ borderColor: "var(--color-card-border)" }}
    >
      {title && <h3 className="text-sm font-semibold mb-3">{title}</h3>}
      {children}
    </section>
  );
}
