/**
 * Top bar: brand title + role toggle + period picker.
 *
 * Per Phase 3.D refactor: role is derived from `usePathname()`
 * rather than from React state. Clicking a toggle button navigates
 * directly to the new role's root via `router.push`. This
 * eliminates the flash-of-wrong-content that the localStorage
 * approach had (SSR-side rendered "pm" before client hydration
 * read localStorage).
 *
 * Pathname being the source of truth means refresh preserves role
 * implicitly. The toggle's visual active state, the page nav, and
 * the role-conditional rendering all read from pathname.
 */

"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import {
  normalisePath,
  roleFromPathname,
  usePeriodContext,
  type Role,
} from "@/lib/PeriodContext";
import { PRODUCT_NAME } from "@/lib/product";

// ROUTE-01: trailing slash matches `trailingSlash: true`, so the toggle
// pushes the canonical URL directly instead of taking a redirect hop.
const ROLE_ROUTES: Record<Role, string> = {
  pm: "/",
  analyst: "/analyst/",
};

// Mirrors PageNav's page list (UX01-T2 header-bar spec: project - page title
// - period date). Kept as a separate small lookup here rather than a shared
// import, to avoid touching PageNav's existing working nav logic.
const PAGE_TITLES: Record<string, string> = {
  "/": "Where we are",
  "/risks": "What's driving risk",
  "/mitigations": "What we could do",
  "/changes": "What changed",
  "/analyst": "Distribution & convergence",
  "/analyst/drivers": "Drivers & sensitivity",
  "/analyst/activities": "Activity-level detail",
  "/analyst/audit": "Methodology audit",
};

/**
 * Last-resort fallback for the brand title when a loaded period predates
 * showcase-P5 and carries no `meta.project_display_name`, AND the build-time
 * `defaultDisplayName` prop was not supplied. The wind project name is never
 * hardcoded here - it arrives from the period data (WS5-C), with the
 * build-time-resolved name (`defaultDisplayName`) covering the
 * pre-hydration / loading window so the SSR header shows the correct
 * per-deployment name.
 */
const DEFAULT_PROJECT_DISPLAY_NAME = PRODUCT_NAME;

export function AppHeader({
  defaultDisplayName,
}: {
  /**
   * Build-time-resolved project display name (from `layout.tsx`), used for
   * the SSR / loading window before the client loads the period data.
   */
  defaultDisplayName?: string;
}) {
  const { status, availablePeriods, selectPeriod } = usePeriodContext();
  const router = useRouter();
  const pathname = usePathname();
  const role = roleFromPathname(pathname);

  const handleToggle = (next: Role) => {
    if (next === role) return;
    router.push(ROLE_ROUTES[next]);
  };

  const currentFilename =
    status.kind === "ready" ? status.filename : "";

  // WS5-C: brand title resolves from the period data (project_display_name).
  // During the SSR / loading window the build-time-resolved name covers it
  // (no flash-of-the engagement on the wind build); the static default is the
  // last resort for a field-less artefact with no build-time name.
  const fallbackName = defaultDisplayName ?? DEFAULT_PROJECT_DISPLAY_NAME;
  const projectDisplayName =
    status.kind === "ready"
      ? status.data.meta.project_display_name ?? fallbackName
      : fallbackName;

  // ROUTE-01: normalise before lookup - PAGE_TITLES keys are slashless
  // and `usePathname()` returns a trailing slash under trailingSlash.
  const pageTitle = PAGE_TITLES[normalisePath(pathname)] ?? "";
  const periodEndDate =
    status.kind === "ready" ? status.data.meta.period_end_date : null;

  return (
    <header
      className="flex items-center justify-between px-6 py-3 text-white print:hidden"
      style={{
        background: "var(--color-header)",
        borderBottom: "3px solid var(--color-accent)",
      }}
    >
      <div>
        <Link href={ROLE_ROUTES[role]} className="block focus:outline-none focus:ring-2 focus:ring-white/40 rounded">
          <h1 className="text-base font-semibold leading-tight">
            {projectDisplayName}
            {pageTitle && (
              <span className="font-normal opacity-70"> - {pageTitle}</span>
            )}
          </h1>
          <p className="text-xs opacity-70 mt-0.5">
            {/* N9: before a project name loads, the title is the product; don't say it twice. */}
            {projectDisplayName === PRODUCT_NAME
              ? "Monthly risk dashboard"
              : `${PRODUCT_NAME} - monthly risk dashboard`}
            {periodEndDate && ` - ${periodEndDate}`}
          </p>
        </Link>
      </div>

      <div className="flex items-center gap-4">
        {/* Period picker */}
        {availablePeriods.length > 0 && (
          <label className="flex items-center gap-2 text-xs">
            <span className="opacity-70 uppercase tracking-wide">
              Period
            </span>
            <select
              className="bg-white/10 text-white text-xs rounded px-2 py-1 border border-white/20 focus:outline-none focus:ring-2 focus:ring-white/40"
              value={currentFilename}
              onChange={(e) => selectPeriod(e.target.value)}
              aria-label="Select period"
            >
              {availablePeriods.map((name) => (
                <option key={name} value={name} className="text-black">
                  {name.replace(/^period_/, "").replace(/\.json$/, "")}
                </option>
              ))}
            </select>
          </label>
        )}

        {/* Role toggle */}
        <div
          className="flex rounded-full overflow-hidden text-xs"
          style={{ background: "rgba(255,255,255,0.1)" }}
          role="group"
          aria-label="View role"
        >
          <RoleButton
            label="PM"
            active={role === "pm"}
            onClick={() => handleToggle("pm")}
          />
          <RoleButton
            label="Analyst"
            active={role === "analyst"}
            onClick={() => handleToggle("analyst")}
          />
        </div>
      </div>
    </header>
  );
}

function RoleButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "px-4 py-1.5 font-medium tracking-wide transition-colors focus:outline-none focus:ring-2 focus:ring-white/40",
        active ? "text-white" : "text-white/60 hover:text-white",
      ].join(" ")}
      style={{
        background: active ? "var(--color-accent)" : "transparent",
      }}
      aria-pressed={active}
      aria-label={`Switch to ${label} view`}
    >
      {label}
    </button>
  );
}
