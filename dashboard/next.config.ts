import type { NextConfig } from "next";

/**
 * AM03 Phase 3 dashboard configuration.
 *
 * D1: static export. The dashboard ships as static files; the
 * monthly JSON cadence and one-client-audience design make
 * server-side rendering unnecessary. Vercel serves the static
 * `out/` directory behind password protection.
 *
 * D2: data lives at `public/data/` (copied from `../data/` at
 * build time by `scripts/copy-data.js`, hooked as the `prebuild`
 * npm script). The dashboard never reaches outside its own
 * directory at runtime.
 *
 * Adding a new period requires a rebuild and redeploy. No ISR,
 * no live data refresh in v1.
 */
const nextConfig: NextConfig = {
  output: "export",
  // ROUTE-01: emit `<route>/index.html` rather than `<route>.html`, so
  // every route resolves by plain directory-index lookup and needs no
  // rewrite map. The alternative (`cleanUrls` in vercel.json) generates
  // an `overrides` map that `vercel build` writes with WINDOWS path
  // separators for nested routes - "analyst\\drivers" - which match
  // nothing on Vercel's Linux runtime, so those routes 404. Confirmed in
  // CLI 54.5.1 and 59.1.3. See docs/RELEASE_PROCEDURE_dashboard.md.
  trailingSlash: true,
  // Static export requires unoptimized images; Vercel serves the
  // exported assets as-is rather than running the image optimizer.
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
