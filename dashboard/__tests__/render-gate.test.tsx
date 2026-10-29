/**
 * SPEC §3 limb 4's **app-render gate** (stage 7 part D, D-2).
 *
 * "For that golden JSON, each route renders the values a snapshot test asserts."
 *
 * The values asserted here are read FROM the golden at run time, never retyped. A test carrying
 * its own copy of a number stops being a gate the moment the golden is legitimately re-blessed:
 * it either reds for the wrong reason or, worse, is updated to match and no longer checks
 * anything. Everything below asks the same question - does what the reader sees agree with what
 * the engine emitted?
 */
import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { goldenPeriod, routeState } from "./setup";
import { PeriodProvider } from "@/lib/PeriodContext";
import { AppFooter } from "@/components/AppFooter";
import { IntegratedOutturnCard } from "@/components/IntegratedOutturnCard";
import { PeriodFreshnessBanner } from "@/components/PeriodFreshnessBanner";
import PmPage1 from "@/app/page";
import AnalystA1 from "@/app/analyst/page";
import { JointConfidenceNote } from "@/components/JointConfidenceNote";
import { formatAud, formatLongDate, formatPercent } from "@/lib/formatters";
import type { Integrated } from "@/types/period";

function renderInProvider(ui: React.ReactNode) {
  return render(<PeriodProvider>{ui}</PeriodProvider>);
}

/**
 * The app's OWN rendering of a date, so the assertion compares the whole string.
 *
 * The first version compared only the day of month, which is tautological: the rendered string
 * ends in "2026", so any P80 falling on the 2nd, 6th, 20th or 26th would match whatever date the
 * app displayed. Using `formatLongDate` - the app's own pure function - asks the real question
 * without the test forming a second opinion about how a date should look.
 */
function asRendered(iso: string): string {
  return formatLongDate(iso);
}

describe("the PM landing route, against the committed golden", () => {
  it("renders the golden's own P80 finish date", async () => {
    const golden = goldenPeriod() as any;
    renderInProvider(<PmPage1 />);

    await waitFor(() => expect(screen.getByText(/Where we are/)).toBeInTheDocument());

    // The headline figure the whole page exists to show. Read from the golden, so a re-bless
    // that legitimately moves it keeps this test meaningful instead of making it a liar.
    // Scoped to the primary-number element rather than searched page-wide: the day number
    // appears in the percentile row too, and a page-wide match found several. Asserting on the
    // element that IS the headline is the stricter question anyway - is the big number right?
    const p80 = golden.headline.p80_finish as string;
    const primary = document.querySelector(".text-4xl");
    expect(primary, "the headline element is gone").toBeTruthy();
    expect(primary!.textContent?.trim()).toBe(asRendered(p80));
  });

  it("renders the golden's open-risk count", async () => {
    const golden = goldenPeriod() as any;
    renderInProvider(<PmPage1 />);

    const label = await screen.findByText(/OPEN RISKS/i);

    // The contract field is `open_risks_count`. The first version read `open_risks`, which does
    // not exist, and `??` fell through to `risks.length` - equal on this golden, so it passed
    // while asserting the wrong thing. A page-wide text match was the other half of the problem:
    // at a count of 0 it would have matched the fired and closed cells instead.
    const open = golden.headline.open_risks_count;
    expect(open, "the golden has no headline.open_risks_count").toBeTypeOf("number");
    expect(label.parentElement?.textContent).toContain(String(open));
  });
});

describe("the integrated outturn card (part B, A-2)", () => {
  it("renders the golden's integrated P80, not a number of its own", () => {
    const golden = goldenPeriod() as any;
    const integrated = golden.integrated as Integrated;
    expect(integrated, "the golden carries no integrated block").toBeTruthy();

    render(<IntegratedOutturnCard integrated={integrated} />);

    // Rendered through the app's own currency formatter, so assert on the digits rather than on
    // a formatting guess - the test must not encode a second opinion about how money looks.
    const rendered = screen.getByText(/P80 INTEGRATED/i).parentElement?.textContent ?? "";
    const digits = rendered.replace(/[^0-9]/g, "");
    expect(digits).toContain(String(Math.round(integrated.p80_dollars)).slice(0, 4));
  });

  it("states the conditioning rather than leaving the reader to assume it", () => {
    const golden = goldenPeriod() as any;
    render(<IntegratedOutturnCard integrated={golden.integrated as Integrated} />);
    // A LITERAL on purpose (gate 3 round 1, W2 / N4): reading the string back from the golden cannot
    // fail on wording, so it checked that the card renders its own input and nothing else. The wording
    // is a statement about the method (Director, 02/10/2026); a change to it is deliberate.
    expect(
      screen.getByText(
        /cost \+ dollarised schedule delay, with risk states pinned from the status workbook on both arms/,
      ),
    ).toBeInTheDocument();
  });

  it("explains an absent block instead of rendering nothing", () => {
    render(<IntegratedOutturnCard unavailableReason="the register supplies no day rate" />);
    expect(screen.getByText(/no day rate/)).toBeInTheDocument();
  });

  it("renders nothing at all when there is neither a block nor a reason", () => {
    const { container } = render(<IntegratedOutturnCard />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("the integrated S-curve and JCL (contract 1.5, INTSCURVE-01 Part C)", () => {
  it("draws the integrated S-curve beside the finish one on the Analyst route", async () => {
    routeState.pathname = "/analyst";
    renderInProvider(<AnalystA1 />);
    await waitFor(() =>
      expect(screen.getByText(/cumulative probability of project finish/)).toBeInTheDocument());
    expect(screen.getByText(/S-curve: integrated event-risk cost/)).toBeInTheDocument();
    expect(screen.getByTestId("jcl-note")).toBeInTheDocument();
  });

  it("carries the engine's 21 curve points, on the finish curve's probabilities", () => {
    const golden = goldenPeriod() as any;
    const pts = (golden.integrated as Integrated).curve_points;
    const finish = golden.distribution.s_curve_points as { cumulative_prob: number }[];
    expect(pts.map((p) => p.cumulative_prob)).toEqual(finish.map((p) => p.cumulative_prob));
  });

  it("states the golden's JCL, its budget and its finish, not numbers of its own", () => {
    const jcl = (goldenPeriod() as any).integrated.jcl as Integrated["jcl"];
    render(<JointConfidenceNote jcl={jcl} />);
    const text = screen.getByTestId("jcl-note").textContent ?? "";
    expect(text).toContain(formatPercent(jcl.jcl, 0));
    expect(text).toContain(formatAud(jcl.cost_target_dollars));
    expect(text).toContain(formatLongDate(jcl.finish_target_date));
    // A literal on purpose, as the conditioning sentence above: it is a statement of method.
    expect(text).toMatch(/sampled jointly/);
    expect(text).toMatch(/leaves out delay cost/);
  });
});

describe("the provenance footer (part A, D-3)", () => {
  it("shows the golden's engine SHA, short", async () => {
    const golden = goldenPeriod() as any;
    renderInProvider(<AppFooter />);
    const sha = golden.meta.engine_sha as string;
    expect(await screen.findByText(sha.slice(0, 8))).toBeInTheDocument();
  });

  it("does not warn about uncommitted changes on a clean-tree golden", async () => {
    const golden = goldenPeriod() as any;
    expect(golden.meta.engine_tree_dirty).toBe(false);
    renderInProvider(<AppFooter />);
    await screen.findByText(/Engine run/);
    expect(screen.queryByText(/uncommitted changes/)).toBeNull();
  });
});

describe("the freshness banner (part C, B-3)", () => {
  beforeEach(() => {
    routeState.pathname = "/";
  });

  /**
   * The golden is the FIRST period of the wind engagement, so it carries no
   * `previous_period_end_date`. That means no cycle can be measured, so it can never be STALE -
   * only LATE. Which makes it exactly the right fixture for the property that was actually
   * ruled: **LATE is specialist-only.**
   *
   * The first version of these tests asserted a stale banner on the PM route and failed. The
   * harness was right and the test was wrong - and that is the point of building it, because
   * nothing before this could have told me.
   */
  it("says nothing to a PM about a period that is merely late", async () => {
    // Rendered ALONGSIDE the footer, and the footer is awaited first. The previous version
    // waited for the absence of a "Loading" string this component never renders, so it resolved
    // on the first synchronous pass - before the stubbed fetch had even settled - and would have
    // passed on a crashed load, a deleted component, or a banner that DID wrongly show LATE to a
    // PM. It was the only assertion carrying the client-facing role ruling, and it gated
    // nothing. Named by the part D review.
    renderInProvider(
      <>
        <AppFooter />
        <PeriodFreshnessBanner />
      </>,
    );
    await screen.findByText(/Engine run/);  // the provider has genuinely loaded by here

    expect(screen.queryByRole("status")).toBeNull();
  });

  it("tells the specialist, on the Analyst route", async () => {
    routeState.pathname = "/analyst";
    renderInProvider(<PeriodFreshnessBanner />);
    const banner = await screen.findByRole("status");
    expect(banner.textContent).toMatch(/Update overdue/);
    expect(banner.textContent).toMatch(/Analyst view only/);
  });

  it("names the SLA from the constant, so the message cannot drift from the rule", async () => {
    routeState.pathname = "/analyst";
    renderInProvider(<PeriodFreshnessBanner />);
    const banner = await screen.findByRole("status");
    expect(banner.textContent).toMatch(/7-working-day turnaround/);
  });

  /**
   * PRERELEASE-01 P1. A visitor to the public showcase sees STALE (accepted, SHOWCASESTALE-01),
   * and a synthetic showcase has no engagement, so the message speaks of a project. The golden
   * has no previous period, so it is given one a cycle before its own period end, and the clock
   * is set well past the next one. Both are derived from the golden, so a re-bless to another
   * period end moves them with it, and the test does not depend on today's date.
   */
  it("speaks of a project, not an engagement, when STALE", async () => {
    const CYCLE_DAYS = 31;
    const DAY_MS = 86_400_000;
    const end = Date.parse(`${(goldenPeriod() as any).meta.period_end_date}T00:00:00Z`);
    const previous = new Date(end - CYCLE_DAYS * DAY_MS).toISOString().slice(0, 10);
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(end + 4 * CYCLE_DAYS * DAY_MS);
    const served = globalThis.fetch;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const res = await served(input);
      if (!String(input).match(/period_\d{8}\.json$/) || !res.ok) return res;
      const period = await res.json();
      period.meta.previous_period_end_date = previous;
      return new Response(JSON.stringify(period), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    try {
      renderInProvider(<PeriodFreshnessBanner />);
      const banner = await screen.findByRole("status");
      expect(banner.textContent).toMatch(/Out of date/);
      expect(banner.textContent).toMatch(
        new RegExp(`On this project's observed ${CYCLE_DAYS}-day cycle`),
      );
      expect(banner.textContent).not.toMatch(/engagement/i);
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });
});
