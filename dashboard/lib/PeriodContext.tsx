/**
 * Period-data context provider.
 *
 * Wraps the app with a single source of truth for:
 * - The currently-selected period (filename + parsed PeriodData)
 * - The list of available periods (from the build-time manifest)
 *
 * Loads asynchronously on first mount. Components render against the
 * `status` discriminator to handle loading / error / ready states.
 *
 * Role (PM vs Analyst) is NOT stored here. Per Phase 3.D refactor,
 * role is derived from `usePathname()` in the components that need
 * it; this eliminates the flash-of-wrong-content that came from the
 * SSR/CSR state mismatch when localStorage said "analyst" but the
 * server pre-rendered with role="pm". URL is the source of truth;
 * pathname survives refresh by definition.
 *
 * The provider is `"use client"` because fetch happens in the
 * browser for the static export (D1).
 *
 * Per AM03 v1.1 §4 "Pure React state management; no Redux or other
 * state library needed for v1 scope."
 */

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useSearchParams } from "next/navigation";

import { loadPeriod, loadPeriodIndex, loadProjectIndex } from "@/lib/loadPeriod";
import type { PeriodData, PeriodIndex } from "@/types/period";

// ---------------------------------------------------------------------------
// Role (URL-derived; helper exported for components)
// ---------------------------------------------------------------------------

export type Role = "pm" | "analyst";

/**
 * Map a pathname to its role. `/analyst...` -> Analyst; everything
 * else -> PM. Pure function; safe to call during render.
 */
export function roleFromPathname(pathname: string): Role {
  return pathname.startsWith("/analyst") ? "analyst" : "pm";
}

/**
 * Strip a trailing slash so a pathname can be compared against, or used to
 * key, a slashless route table. Root "/" is returned unchanged.
 *
 * ROUTE-01: the app runs `trailingSlash: true`, and `usePathname()` returns
 * the slash - measured on a preview deployment, a hard load of
 * `/analyst/drivers/` reports exactly "/analyst/drivers/". Every exact-match
 * comparison against a slashless route therefore fails silently, showing no
 * active nav tab and an empty header page title. Both call sites route
 * through here so the convention lives in one place.
 */
export function normalisePath(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

export type LoadStatus =
  | { kind: "loading" }
  | {
      kind: "ready";
      data: PeriodData;
      index: PeriodIndex;
      filename: string;
      project: string;
    }
  | { kind: "error"; message: string };

export interface PeriodContextValue {
  status: LoadStatus;
  selectPeriod: (filename: string) => Promise<void>;
  availablePeriods: string[]; // sorted ascending; empty until loaded
  /** Every project this build carries, sorted. Empty until loaded. */
  availableProjects: string[];
  /** The project currently shown, or null before the first load resolves. */
  project: string | null;
}

const PeriodContext = createContext<PeriodContextValue | null>(null);

/**
 * The query parameter that says which project a page is showing.
 *
 * Stage 7 part C, B-2, ruled 05/09/2026. The deciding property is that the link is
 * **shareable**: a PM sending their board a figure must be able to send a URL that shows the
 * right project. A selector alone cannot promise that - the recipient sees whichever project
 * they last picked. A path segment would be cleaner still, and is closed: it would move all
 * eight routes under `app/[project]/` and need `generateStaticParams`, making a new project a
 * rebuild rather than a data drop.
 */
export const PROJECT_PARAM = "project";

/** What `copy-data.js` calls periods still sitting in the pre-part-C flat layout. */
export const UNKEYED_PROJECT = "_unkeyed";

/**
 * Resolve which project to show, from the URL against what the build actually carries.
 *
 * Falls back rather than erroring when the parameter is absent, which is the single-project
 * case and must keep working untouched - part C must not make an existing install worse. An
 * UNKNOWN project is a different matter and is surfaced: silently showing project A's numbers
 * because the URL named a project that does not exist is the failure the whole key exists to
 * prevent.
 */
export function resolveProject(
  requested: string | null,
  available: string[],
): { project: string | null; error: string | null } {
  if (available.length === 0) {
    return { project: null, error: "No projects found in this build." };
  }
  if (requested === null) {
    // A REAL project wins the default over the pre-part-C flat layout. "_unkeyed" sorts
    // before every lowercase key, so on a checkout holding both, the bare shareable link
    // would otherwise render the OLD flat period as though it were current - the single
    // most misleading thing this feature could do. Part C review W3.
    const keyed = available.filter((p) => p !== UNKEYED_PROJECT);
    return { project: (keyed[0] ?? available[0]), error: null };
  }
  if (available.includes(requested)) return { project: requested, error: null };
  return {
    project: null,
    error:
      `This dashboard carries no project "${requested}". ` +
      `Available: ${available.join(", ")}. ` +
      `Check the ?${PROJECT_PARAM}= value in the link you followed.`,
  };
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function PeriodProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<LoadStatus>({ kind: "loading" });
  const [availableProjects, setAvailableProjects] = useState<string[]>([]);
  // Mirrors `status` so `selectPeriod` can read the CURRENT project without capturing it in
  // a closure. Without this, a period selected while a project change is in flight would be
  // fetched from the old project's directory and rendered under the new project's name.
  const statusRef = useRef<LoadStatus>({ kind: "loading" });
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  // Read on each render rather than captured once: the picker changes the query string, and a
  // captured value would leave the page showing the previous project's numbers under the new
  // project's URL - the exact mismatch this feature exists to make impossible.
  const searchParams = useSearchParams();
  const requestedProject = searchParams.get(PROJECT_PARAM);

  // Initial load: discover projects, resolve which one, then its periods + the latest.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const projects = await loadProjectIndex();
        if (cancelled) return;
        setAvailableProjects(projects);

        const { project, error } = resolveProject(requestedProject, projects);
        if (project === null) {
          setStatus({ kind: "error", message: error ?? "No project selected." });
          return;
        }

        const index = await loadPeriodIndex(project);
        if (cancelled) return;
        if (index.periods.length === 0) {
          setStatus({
            kind: "error",
            message:
              `No period_YYYYMMDD.json files found for project "${project}". ` +
              `Run RUN_PERIOD.bat at the repo root and rebuild.`,
          });
          return;
        }
        const sorted = [...index.periods].sort();
        const latest = sorted[sorted.length - 1];
        const data = await loadPeriod(project, latest);
        if (cancelled) return;
        setStatus({ kind: "ready", data, index, filename: latest, project });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : String(err);
        setStatus({ kind: "error", message });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [requestedProject]);

  const selectPeriod = useCallback(
    async (filename: string) => {
      // Read the project off the CURRENT status rather than from the closure, so a period
      // selected while a project change is in flight cannot be fetched from the old project's
      // directory and then displayed under the new one's name.
      try {
        const current = statusRef.current;
        if (current.kind !== "ready") return;
        const data = await loadPeriod(current.project, filename);
        setStatus((prev) =>
          prev.kind === "ready" && prev.project === current.project
            ? { kind: "ready", data, index: prev.index, filename, project: prev.project }
            : prev,
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setStatus({ kind: "error", message });
      }
    },
    [],
  );

  const availablePeriods = useMemo(
    () =>
      status.kind === "ready" ? [...status.index.periods].sort() : [],
    [status],
  );

  const value = useMemo<PeriodContextValue>(
    () => ({
      status,
      selectPeriod,
      availablePeriods,
      availableProjects,
      project: status.kind === "ready" ? status.project : null,
    }),
    [status, selectPeriod, availablePeriods, availableProjects],
  );

  return (
    <PeriodContext.Provider value={value}>{children}</PeriodContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function usePeriodContext(): PeriodContextValue {
  const ctx = useContext(PeriodContext);
  if (!ctx) {
    throw new Error(
      "usePeriodContext must be called inside <PeriodProvider>",
    );
  }
  return ctx;
}

/**
 * Convenience hook for components that should only render when data
 * is loaded. Returns `null` while loading or on error; consumers
 * decide how to render those states (typically via <PeriodGate>).
 */
export function usePeriodData(): PeriodData | null {
  const { status } = usePeriodContext();
  return status.kind === "ready" ? status.data : null;
}
