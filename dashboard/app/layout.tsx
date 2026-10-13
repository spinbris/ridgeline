import { promises as fs } from "node:fs";
import path from "node:path";

import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { Suspense } from "react";

import { AppFooter } from "@/components/AppFooter";
import { AppHeader } from "@/components/AppHeader";
import { PeriodFreshnessBanner } from "@/components/PeriodFreshnessBanner";
import { GuidanceStrip } from "@/components/GuidanceStrip";
import { PageNav } from "@/components/PageNav";
import { PeriodProvider } from "@/lib/PeriodContext";
import { PRODUCT_NAME, TAGLINE } from "@/lib/product";

import "./globals.css";

/**
 * Page-chrome defaults for a period that predates showcase-P5 and carries
 * no `meta.project_display_name` (the frozen inaugural artefact). The
 * project name is never hardcoded - it is resolved from the period data
 * below (WS5-C). These defaults are deliberately project-neutral, so a
 * field-less period renders generic chrome rather than naming a project.
 */
/**
 * next/font self-hosts the font files at build time (no runtime fetch to
 * Google), which is what makes it safe under `output: "export"` (D1).
 * The generated CSS variable, not the bare family name, drives
 * globals.css so the static export still resolves the font correctly.
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

// RIDGELINE-01 P7: the product's name is chrome, not a project's, so it may stand here.
const DEFAULT_TITLE = PRODUCT_NAME;
const DEFAULT_DESCRIPTION = TAGLINE;

/**
 * Read the latest period's project display name from the build-time data
 * copy (`public/data/`), so the static export bakes the project's own name
 * into `<title>` / meta description. Resolves from data, not a hardcode.
 * Any failure (no data yet, malformed file) falls back to the neutral
 * defaults above so the build never breaks on chrome resolution.
 */
async function resolveProjectDisplayName(): Promise<string | null> {
  try {
    const dataDir = path.join(process.cwd(), "public", "data");
    // Part C (B-2) moved periods under data/<project>/, so the root index.json this used to
    // read no longer exists and every keyed build silently fell back to the neutral default -
    // the header lost the project's own name. Found by the part C review (W5) after the
    // Builder saw "QSRA Dashboard" in a live check and did not chase it.
    //
    // The same project `resolveProject` defaults to for a request with no ?project=, which
    // means SKIPPING the pre-part-C flat layout: "_unkeyed" sorts before every lowercase key,
    // so taking projects[0] blindly baked the OLD flat period's name into <title> while the
    // page rendered the keyed one. That is the W3 symptom reappearing at build time, and the
    // first version of this comment claimed to match resolveProject while doing the opposite.
    // Found by the part C re-review.
    const manifest = JSON.parse(
      await fs.readFile(path.join(dataDir, "projects.json"), "utf-8"),
    ) as { projects?: string[] };
    const all = manifest.projects ?? [];
    const project = all.find((p) => p !== "_unkeyed") ?? all[0];
    if (!project) return null;

    const projectDir = path.join(dataDir, project);
    const index = JSON.parse(
      await fs.readFile(path.join(projectDir, "index.json"), "utf-8"),
    ) as { periods?: string[] };
    const periods = (index.periods ?? [])
      .filter((n) => /^period_\d{8}\.json$/.test(n))
      .sort();
    if (periods.length === 0) return null;
    const latest = periods[periods.length - 1];
    const period = JSON.parse(
      await fs.readFile(path.join(projectDir, latest), "utf-8"),
    ) as { meta?: { project_display_name?: string } };
    return period.meta?.project_display_name ?? null;
  } catch {
    return null;
  }
}

export async function generateMetadata(): Promise<Metadata> {
  const displayName = await resolveProjectDisplayName();
  if (!displayName) {
    return { title: DEFAULT_TITLE, description: DEFAULT_DESCRIPTION };
  }
  return {
    title: `${displayName} - ${PRODUCT_NAME}`,
    description: `${PRODUCT_NAME} monthly risk dashboard for ${displayName}`,
  };
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Resolve the project name at build time so the server-rendered header
  // shows the correct per-deployment name (no flash of the wrong project
  // name before the client loads the period data). Falls back to the
  // neutral default for the field-less inaugural artefact.
  const buildTimeDisplayName =
    (await resolveProjectDisplayName()) ?? DEFAULT_TITLE;
  return (
    <html lang="en" className={inter.variable}>
      <body className="antialiased">
        {/*
          Suspense is REQUIRED, not stylistic. `PeriodProvider` reads `useSearchParams()` for
          part C's `?project=` selection, and Next refuses to prerender a client component that
          does so outside a boundary - `npm run build` fails outright with "useSearchParams()
          should be wrapped in a suspense boundary". The static export cannot know the query
          string at build time, so the subtree is client-rendered and this is the boundary that
          says so.

          The fallback is deliberately empty: the provider's own `loading` state already drives
          every page's skeleton, and a second spinner here would flash before it.
        */}
        <Suspense fallback={null}>
        <PeriodProvider>
          <div className="flex flex-col min-h-screen">
            <AppHeader defaultDisplayName={buildTimeDisplayName} />
            <PageNav />
            <GuidanceStrip />
            <PeriodFreshnessBanner />
            <div className="flex-1">{children}</div>
            <AppFooter />
          </div>
        </PeriodProvider>
        </Suspense>
      </body>
    </html>
  );
}
