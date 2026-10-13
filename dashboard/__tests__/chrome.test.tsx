/**
 * RIDGELINE-01 P7: the app's chrome names the product, and stays project-neutral.
 *
 * The header shows the project's name from the period data and the product's name beside it; with
 * no data it falls back to the product, never to a project. The browser tab reads
 * "<project> - Ridgeline", or the product alone when no period carries a name.
 */
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { goldenPeriod } from "./setup";
import { AppFooter } from "@/components/AppFooter";
import { AppHeader } from "@/components/AppHeader";
import { PeriodProvider } from "@/lib/PeriodContext";
import { PRODUCT_LINE, PRODUCT_NAME, TAGLINE } from "@/lib/product";

vi.mock("next/font/google", () => ({ Inter: () => ({ variable: "font-inter" }) }));
vi.mock("@/app/globals.css", () => ({}));

// Round 1: a test that stubs fetch must not leave the stub for the next file's tests.
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the header", () => {
  it("names the project from the data and the product beside it", async () => {
    const project = (goldenPeriod() as any).meta.project_display_name as string;
    render(<PeriodProvider><AppHeader /></PeriodProvider>);

    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(project));
    const header = screen.getByRole("banner");
    expect(header).toHaveTextContent(`${PRODUCT_NAME} - monthly risk dashboard`);
    expect(header).not.toHaveTextContent("QSRA Dashboard");
  });

  it("falls back to the product, not a project, before any data loads", () => {
    vi.stubGlobal("fetch", () => new Promise(() => {}));
    render(<PeriodProvider><AppHeader /></PeriodProvider>);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(PRODUCT_NAME);
    // Round 1, N9: the subtitle does not repeat the product the title already names.
    const header = screen.getByRole("banner");
    expect(header.textContent?.split(PRODUCT_NAME).length).toBe(2);
    expect(header).toHaveTextContent("Monthly risk dashboard");
  });
});

describe("the footer's brand line (round 1, W6)", () => {
  it("shows the tagline and the maker once the period loads", async () => {
    render(<PeriodProvider><AppFooter /></PeriodProvider>);
    await screen.findByText(/Engine run/);
    expect(screen.getByText(PRODUCT_LINE)).toBeVisible();
  });

  it("shows it before any data loads too", () => {
    vi.stubGlobal("fetch", () => new Promise(() => {}));
    render(<PeriodProvider><AppFooter /></PeriodProvider>);
    expect(screen.getByText(PRODUCT_LINE)).toBeVisible();
  });
});

/** A build directory of our own, so the result never depends on what a real build left behind. */
function buildDir(withGolden: boolean): string {
  const root = mkdtempSync(path.join(tmpdir(), "chrome-"));
  if (withGolden) {
    const golden = goldenPeriod() as any;
    const project = "synthetic_wind";
    const file = `period_${String(golden.meta.period_end_date).replace(/-/g, "")}.json`;
    const dir = path.join(root, "public", "data", project);
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(root, "public", "data", "projects.json"), JSON.stringify({ projects: [project] }));
    writeFileSync(path.join(dir, "index.json"), JSON.stringify({ periods: [file] }));
    writeFileSync(path.join(dir, file), JSON.stringify(golden));
  }
  return root;
}

describe("the browser tab", () => {
  it("is the product alone when no period carries a project name", async () => {
    vi.spyOn(process, "cwd").mockReturnValue(buildDir(false));
    const { generateMetadata } = await import("@/app/layout");
    const meta = await generateMetadata();
    expect(meta.title).toBe(PRODUCT_NAME);
    expect(meta.description).toBe(TAGLINE);
  });

  it("is the project, then the product, when the period names one", async () => {
    vi.spyOn(process, "cwd").mockReturnValue(buildDir(true));
    const project = (goldenPeriod() as any).meta.project_display_name as string;
    const { generateMetadata } = await import("@/app/layout");
    const meta = await generateMetadata();
    expect(meta.title).toBe(`${project} - ${PRODUCT_NAME}`);
  });
});
