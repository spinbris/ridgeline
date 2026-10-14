/**
 * REPORTPAGE-01 property 7: the home page links to the full technical report, and the link lands.
 *
 * The report is a static file in public/report/, which `next build` copies into out/ verbatim, so
 * the file under public/ is what the build serves at the link's target.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { existsSync } from "node:fs";
import path from "node:path";

import { PeriodProvider } from "@/lib/PeriodContext";
import PmPage1 from "@/app/page";

const PUBLIC = path.resolve(__dirname, "..", "public");

describe("the full technical report link", () => {
  it("is on the home page and its target exists in the build", async () => {
    render(
      <PeriodProvider>
        <PmPage1 />
      </PeriodProvider>,
    );
    const link = await screen.findByRole("link", { name: "Full technical report" });
    const href = link.getAttribute("href");
    expect(href).toBe("/report/");
    // trailingSlash: true serves `<route>/` from `<route>/index.html`.
    const target = path.join(PUBLIC, href!, "index.html");
    expect(existsSync(target), `no file at public${href}index.html`).toBe(true);
  });
});
