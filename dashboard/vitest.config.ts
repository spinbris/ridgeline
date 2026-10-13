/**
 * The app's first test harness (stage 7 part D, D-2).
 *
 * SPEC §3 limb 4 defines the app half as two linked gates. Part A built the first - a fixed
 * register, `.xer` and seed produce a period JSON identical to a committed golden. This is the
 * second: **for that same golden, each route renders the values a snapshot test asserts.**
 *
 * The two are linked on purpose, and the link is the golden. A render test against a fixture
 * invented for it would drift from what the engine emits, and then agree with nothing.
 *
 * **Why jsdom rather than asserting the built HTML.** Part A tried the cheaper thing and recorded
 * why it cannot work: every page's content sits behind `PeriodGate` / `PeriodProvider`, which
 * render `null` until data loads client-side, so the static export carries none of it. The
 * strings live only in a JS chunk, where matching them proves the source compiled and nothing
 * about what a reader sees. A DOM that actually runs the client is the smallest thing that
 * answers the question.
 */
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  // An INLINE PostCSS config, which stops Vite discovering postcss.config.mjs at all. The
  // app's config loads Tailwind v4's plugin, which Vite cannot consume - the run fails
  // before a single test executes. Styling is not what the render gate asserts (it reads
  // text and roles), so the plugin list is empty rather than a second real config being
  // maintained beside the app's, which would then drift from it.
  css: { postcss: { plugins: [] } },
  resolve: {
    // Mirrors tsconfig's `paths`. Drift fails loudly at import rather than silently, so
    // there is no separate check - the earlier version of this comment claimed one existed
    // in a file that does not, which is a control asserted rather than installed.
    alias: { "@": path.resolve(__dirname, ".") },
  },
  test: {
    environment: "jsdom",
    include: ["__tests__/**/*.test.tsx"],
    globals: true,
    setupFiles: ["./__tests__/setup.ts"],
  },
});
