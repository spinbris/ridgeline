/**
 * Test setup for the render gate (D-2).
 *
 * Two things the app needs that jsdom does not provide: Next's navigation hooks, which read a
 * router that does not exist outside the framework, and a `fetch` that serves the COMMITTED
 * GOLDEN rather than the network. The second is the point of the whole harness - the gate is
 * "for that golden JSON, each route renders the values a snapshot test asserts", so the fixture
 * has to be the golden itself and not a copy made for testing.
 */
import "@testing-library/jest-dom/vitest";
import { readFileSync } from "node:fs";
import path from "node:path";
import { vi, beforeEach } from "vitest";

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const GOLDEN = path.join(
  REPO_ROOT, "tests", "golden", "period_json", "wind_synth", "period_20260228.json",
);

/** The committed golden, read fresh so a re-bless is picked up without touching this file. */
export function goldenPeriod(): Record<string, unknown> {
  return JSON.parse(readFileSync(GOLDEN, "utf-8"));
}

/** Route state the tests drive. Mutable so a test can place itself on an Analyst route. */
export const routeState = { pathname: "/", search: "" };

vi.mock("next/navigation", () => ({
  usePathname: () => routeState.pathname,
  useSearchParams: () => new URLSearchParams(routeState.search),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));

beforeEach(() => {
  routeState.pathname = "/";
  routeState.search = "";

  const golden = goldenPeriod();
  const meta = golden.meta as Record<string, unknown>;
  const project = (meta?.project_key as string) ?? "synthetic_wind";
  // DERIVED from the golden's own period end, not retyped: a re-bless to a different period end
  // would otherwise leave the stub serving a filename the app never asks for, and the tests
  // would fail for a reason that had nothing to do with the app.
  const periodFile = `period_${String(meta?.period_end_date).replace(/-/g, "")}.json`;

  // Serves the golden through the SAME paths the app fetches in production - the per-project
  // manifest, the root project list, and the period itself. Anything the app asks for that is
  // not one of those is a 404 rather than a silent empty object, so a wrong URL fails the test
  // instead of rendering an empty page that looks fine.
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    const body =
      url.endsWith("/data/projects.json")
        ? { projects: [project], generated_at: "2026-09-06T00:00:00Z" }
        : url.endsWith(`/data/${project}/index.json`)
          ? { periods: [periodFile], generated_at: "2026-09-06T00:00:00Z" }
          : url.endsWith(`/data/${project}/${periodFile}`)
            ? golden
            : null;

    if (body === null) {
      return new Response("not found", { status: 404 });
    }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
});
