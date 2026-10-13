/**
 * Per-role page nav (4 tabs).
 *
 * Role derived from `usePathname()` (URL is the source of truth per
 * Phase 3.D refactor). Active tab highlighted by comparing pathname to
 * each href with trailing slashes normalised away on BOTH sides - see
 * `samePath`. ROUTE-01 moved the app to `trailingSlash: true`, and an
 * exact `===` comparison would silently stop matching under it.
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { normalisePath, roleFromPathname } from "@/lib/PeriodContext";

const PM_PAGES: { href: string; label: string }[] = [
  { href: "/", label: "1. Where we are" },
  { href: "/risks/", label: "2. What's driving risk" },
  { href: "/mitigations/", label: "3. What we could do" },
  { href: "/changes/", label: "4. What changed" },
];

const ANALYST_PAGES: { href: string; label: string }[] = [
  { href: "/analyst/", label: "A1. Distribution & convergence" },
  { href: "/analyst/drivers/", label: "A2. Drivers & sensitivity" },
  { href: "/analyst/activities/", label: "A3. Activity-level detail" },
  { href: "/analyst/audit/", label: "A4. Methodology audit" },
];

export function PageNav() {
  const pathname = usePathname();
  const role = roleFromPathname(pathname);
  const pages = role === "pm" ? PM_PAGES : ANALYST_PAGES;

  return (
    <nav
      className="flex gap-1 px-6 py-3 bg-white border-b print:hidden"
      style={{ borderColor: "var(--color-card-border)" }}
      aria-label="Page navigation"
    >
      {pages.map((p) => {
        const active = normalisePath(pathname) === normalisePath(p.href);
        return (
          <Link
            key={p.href}
            href={p.href}
            className="px-4 py-2 text-sm rounded transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]/40"
            style={{
              background: active ? "var(--color-accent)" : "transparent",
              color: active ? "white" : "var(--color-body)",
              fontWeight: active ? 600 : 500,
            }}
            aria-current={active ? "page" : undefined}
          >
            {p.label}
          </Link>
        );
      })}
    </nav>
  );
}
