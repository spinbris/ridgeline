# Active management dashboard

The reading surface for the **active management** half of this product: a Next.js 15
static-export site that consumes the per-period JSON a run writes, and presents it to a PM and to
an analyst.

It is a **consumer, not an engine**. Every number it shows is produced upstream by
`src/am/json_writer.py` and shaped by the period JSON contract
(`types/period.ts` and `lib/loadPeriod.ts` hold it here); the dashboard validates what it is
handed and renders it. It computes nothing of its own.

The deliverable half of the product - the upfront integrated analysis - is the notebook path, and
is described in the repository root's `README.md`.

## Deployments

No client deployment is recorded here. A client's instance - its URL, Vercel project, team and
password - is engagement material and lives with that engagement (SPEC §7). No Vercel project is
linked in this repository's commits (SPEC D-8), and a client's instance is linked locally. A
client's instance runs behind Vercel deployment protection, switched to password protection by the
Director under **Project Settings -> Deployment Protection** (D4).

**The public showcase is the exception.** Tropic Ridge (`synthetic_wind`) is served by the Vercel
project `tropic-ridge-qsra`, which is linked from this directory: locally, in the gitignored
`.vercel/`, and never committed (SHOWCASEAPP-01). Its protection:
- its previews, and its `*.vercel.app` alias, sit behind **Vercel Authentication**;
- its custom domain is public;
- there is no password protection.

Its URL is recorded here once the Director moves the live link to this tree (SHOWCASEAPP-01, at
RELEASE-01 R).

## Local development

```powershell
cd .\dashboard
npm install            # first time only
npm run dev            # http://localhost:3000 (runs scripts/copy-data.js first)
```

`predev` and `prebuild` both invoke `scripts/copy-data.js`, which:

1. Reads `publish.json` - the projects named for publication, written from the project bindings by
   `../scripts/release/write_publish_list.py` - and refuses to build if it names nothing
2. For each named project, copies `../data/<project key>/period_YYYYMMDD.json` into
   `public/data/<project key>/`, with a per-project `index.json` listing its periods; each
   directory in `../data/` it leaves out is named on stderr (`NOT PUBLISHED: ...`)
3. Writes `public/data/projects.json`, the list of projects the app offers, after emptying
   `public/data/` so nothing unnamed stays fetchable (gitignored; regenerated each build)

Static export can't list directory contents at runtime, so the manifests are how the loader finds
projects and periods. The copier reads no period document; it keys on the directory.

## Build for deploy

```powershell
npm run build          # produces dashboard/out/ as a static export
npx serve out          # local smoke; serves on http://localhost:3000 (or 5173 with -l 5173)
```

The exported `out/` directory is what Vercel serves. Static export means no SSR, no API routes, no ISR — everything is pre-rendered at build time and refreshes only via a redeploy.

## Adding a new period, and redeploying

1. `RUN_PERIOD.bat` at the repo root produces the period JSON (`../docs/PLAYBOOK.md` step 7).
2. `PUBLISH_PERIOD.bat <that json> --project <project key>` validates it, files it under
   `../data/<project key>/`, and rebuilds `out/`. It stops at "Built, NOT deployed" and prints the
   exact deploy sequence - the clear, `vercel build`, the build-output guard, `vercel deploy
   --prebuilt` - which its `--deploy` flag runs against a preview. The build carries only the
   projects `publish.json` names; the guard, which asks the project bindings, refuses anything else.)
3. Everything from there - guard, preview, smoke check, production - is
   **`../docs/RELEASE_PROCEDURE_dashboard.md`**, the authoritative deploy process.

Never a plain `vercel deploy`: Vercel's build box has no `data/` (gitignored), so only a local
build uploaded with `--prebuilt` works. There is no live data refresh; a new period appears only
after a rebuild and redeploy.

## Tests

`npm test` runs the render gate (`__tests__/render-gate.test.tsx`), which is the check that the pages render against a real period payload rather than only type-checking. Build verification is `npm run build` (TypeScript strict + ESLint hard-fail). This README claimed "no automated tests for v1" until PUBLIC-01, by which time there were.

## Project layout

```
dashboard/
  app/                                # Next.js App Router pages
    layout.tsx                        # Root: PeriodProvider + AppHeader + PageNav + AppFooter
    page.tsx                          # PM Page 1 (Where we are)
    risks/page.tsx                    # PM Page 2 (What's driving risk)
    mitigations/page.tsx              # PM Page 3 (What we could do)
    changes/page.tsx                  # PM Page 4 (What changed)
    analyst/
      page.tsx                        # Analyst A1 (Distribution & convergence)
      drivers/page.tsx                # Analyst A2 (Drivers & sensitivity)
      activities/page.tsx             # Analyst A3 (Activity-level detail)
      audit/page.tsx                  # Analyst A4 (Methodology audit)
    globals.css                       # Design tokens + sr-only + @media print
  components/                         # Shared UI primitives
    AppHeader, PageNav, AppFooter
    Card, Disclosure, StatusBadge, DivergenceBadge
    PeriodGate                        # Loading/error/ready wrapper
    charts/                           # 5 Recharts + 1 custom SVG (stochastic Gantt)
  lib/
    PeriodContext.tsx                 # Period data context (no role; URL-derived)
    loadPeriod.ts                     # zod-validated JSON loader
    formatters.ts                     # Date/days/percent helpers
  types/period.ts                     # Hand-written types matching Doc 3 v2.3
  scripts/copy-data.js                # Build-time data copy (Node, cross-platform)
  public/data/                        # Gitignored; regenerated by prebuild
  next.config.ts                      # output: "export"
  tsconfig.json, eslint.config.mjs, postcss.config.mjs
```

The deploy process is `../docs/RELEASE_PROCEDURE_dashboard.md`.
