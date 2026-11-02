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
import { render, screen, waitFor, within } from "@testing-library/react";

import { goldenPeriod, routeState } from "./setup";
import { PeriodProvider } from "@/lib/PeriodContext";
import { AppFooter } from "@/components/AppFooter";
import { IntegratedOutturnCard, NO_REASON_TEXT } from "@/components/IntegratedOutturnCard";
import { PeriodFreshnessBanner } from "@/components/PeriodFreshnessBanner";
import PmPage1 from "@/app/page";
import AnalystA1 from "@/app/analyst/page";
import { JointConfidenceNote } from "@/components/JointConfidenceNote";
import {
  formatAud,
  formatAudMillions,
  formatAudMillionsDelta,
  formatDaysDelta,
  formatLongDate,
  formatPercent,
  formatShortDate,
} from "@/lib/formatters";
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

    await waitFor(() => expect(screen.getByText(/How much and when/)).toBeInTheDocument());

    // Scoped to the finish tile's figure rather than searched page-wide: the date appears in
    // the trend strip too. INTVIEW-01 made it the second tile; the question is unchanged - is the
    // finish figure right?
    const p80 = golden.headline.p80_finish as string;
    expect(screen.getByTestId("finish-p80").textContent?.trim()).toBe(asRendered(p80));
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

/** Serve the golden with `mutate` applied, through the same fetch stub setup.ts installs. */
function serveGoldenWith(mutate: (period: any) => void) {
  const served = globalThis.fetch;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const res = await served(input);
    if (!String(input).match(/period_\d{8}\.json$/) || !res.ok) return res;
    const period = await res.json();
    mutate(period);
    return new Response(JSON.stringify(period), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
}

describe("the home tiles (INTVIEW-01 stage 1)", () => {
  it("leads with the golden's risk contingency P80, read from the JSON", async () => {
    const integrated = (goldenPeriod() as any).integrated as Integrated;
    renderInProvider(<PmPage1 />);
    const figure = await screen.findByTestId("contingency-p80");
    // The app's own formatter, so the test holds no second opinion about how money looks.
    expect(figure.textContent?.trim()).toBe(formatAudMillions(integrated.p80_dollars));
    const tile = screen.getByTestId("tile-contingency").textContent ?? "";
    expect(tile).toContain(formatAudMillions(integrated.p50_dollars));
    expect(tile).toContain(formatAudMillions(integrated.p90_dollars));
    expect(tile).toMatch(/enough in 8 of 10 outcomes\. Excludes the base estimate\./);
  });

  it("puts the contingency tile first, ahead of the finish", async () => {
    renderInProvider(<PmPage1 />);
    const first = await screen.findByTestId("tile-contingency");
    const finish = screen.getByTestId("tile-finish");
    expect(first.compareDocumentPosition(finish) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says first period on period 0", async () => {
    expect((goldenPeriod() as any).delta.period_0).toBe(true);
    renderInProvider(<PmPage1 />);
    const tile = await screen.findByTestId("tile-since-last");
    expect(tile.textContent).toMatch(/First period: nothing to compare yet\./);
    // Outside the framework next/link drops the trailing slash `trailingSlash: true` adds.
    expect(within(tile).getByRole("link", { name: "What changed" }).getAttribute("href"))
      .toMatch(/^\/changes\/?$/);
  });

  it("shows the finish movement in days, and no dollars when the prior carried none", async () => {
    serveGoldenWith((p) => {
      p.delta = {
        period_0: false, p80_delta_days: 12, p80_delta_dollars: null, p80_previous: "2026-06-18",
        p80_current: p.headline.p80_finish, worse: [], better: [], new: [],
        net_movement_summary: "",
      };
    });
    try {
      renderInProvider(<PmPage1 />);
      const tile = await screen.findByTestId("tile-since-last");
      expect(tile.textContent).toContain(formatDaysDelta(12));
      expect(tile.textContent).not.toMatch(/\$/);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("adds the contingency movement in dollars when the engine supplies it (1.6)", async () => {
    serveGoldenWith((p) => {
      p.delta = {
        period_0: false, p80_delta_days: 12, p80_delta_dollars: 875398.11,
        p80_previous: "2026-06-18", p80_current: p.headline.p80_finish, worse: [], better: [],
        new: [], net_movement_summary: "",
      };
    });
    try {
      renderInProvider(<PmPage1 />);
      const figure = await screen.findByTestId("since-last-movement");
      expect(figure.textContent).toContain(formatAudMillionsDelta(875398.11));
      expect(figure.textContent).toContain(formatDaysDelta(12));
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("is never blank: no block and no reason says so", async () => {
    serveGoldenWith((p) => {
      delete p.integrated;
      delete p.audit.integrated_unavailable;
    });
    try {
      renderInProvider(<PmPage1 />);
      const tile = await screen.findByTestId("tile-contingency");
      expect(tile.textContent).toContain(NO_REASON_TEXT);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("shows the golden's JCL as tile 4, on the report's basis (INTVIEW-01 stage 2)", async () => {
    const jcl = (goldenPeriod() as any).integrated.jcl as Integrated["jcl"];
    expect(jcl.base_drawn, "the golden's JCL drew no base").toBe(true);
    renderInProvider(<PmPage1 />);
    const tile = await screen.findByTestId("tile-on-budget");
    expect(screen.getByTestId("on-budget-jcl").textContent?.trim()).toBe(
      formatPercent(jcl.jcl, 0));
    expect(tile.textContent).toContain(formatAudMillions(jcl.cost_target_dollars));
    expect(tile.textContent).toContain(`Budget alone ${formatPercent(jcl.cost_confidence, 0)}`);
    expect(tile.textContent).toContain(`date alone ${formatPercent(jcl.finish_confidence, 0)}`);
    // The four tiles in the wireframe's order.
    const finish = screen.getByTestId("tile-finish");
    expect(finish.compareDocumentPosition(tile) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps tile 4 from going blank when the period has no integrated block", async () => {
    serveGoldenWith((p) => {
      delete p.integrated;
      delete p.contingency;
    });
    try {
      renderInProvider(<PmPage1 />);
      const tile = await screen.findByTestId("tile-on-budget");
      expect(tile.textContent).toMatch(/Not available this period/);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("shows no analyst JCL sentence and no six-cell date row on the home page", async () => {
    const golden = goldenPeriod() as any;
    renderInProvider(<PmPage1 />);
    await screen.findByTestId("tile-contingency");
    expect(screen.queryByTestId("jcl-note")).toBeNull();
    // P10, mean and P95 finish dates live on the analyst percentile table now.
    // (The expander's P95 is dollars, so the date row is checked by its dates, not its labels.)
    expect(screen.queryByText(/^P10$/)).toBeNull();
    const text = document.body.textContent ?? "";
    for (const iso of [golden.headline.p10_finish, golden.headline.mean_finish,
      golden.headline.p95_finish]) {
      expect(text).not.toContain(formatShortDate(iso));
    }
  });

  it("says risk contingency, never integrated event-risk cost or outturn", async () => {
    renderInProvider(<PmPage1 />);
    await screen.findByTestId("tile-contingency");
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/risk contingency/i);
    expect(text).not.toMatch(/integrated event-risk cost/i);
    expect(text).not.toMatch(/outturn/i);
  });
});

describe("the contingency position (INTVIEW-01 stage 2b)", () => {
  it("reads Recommended at P80 before commitment, at the golden's own P80", async () => {
    const golden = goldenPeriod() as any;
    renderInProvider(<PmPage1 />);
    const panel = await screen.findByTestId("contingency-position");
    expect(panel.getAttribute("data-phase")).toBe("recommended");
    expect(golden.contingency.phase).toBe("recommended");
    expect(panel.textContent).toContain("Recommended at P80");
    expect(within(panel).getByTestId("contingency-required").textContent).toBe(
      formatAudMillions(golden.contingency.required_p80_dollars),
    );
    expect(within(panel).getByTestId("contingency-held").textContent).toBe("Not committed yet");
    expect(panel.textContent).toContain("Target");
  });

  it("shows held against required from commitment, every figure the engine's", async () => {
    serveGoldenWith((p) => {
      p.contingency = {
        ...p.contingency,
        phase: "held",
        label: "Held against required at P80",
        held_dollars: 6_770_000,
        commitment_date: "2026-03-16",
        opening_held_dollars: 7_500_000,
        approved_draws_dollars: 730_000,
        pending_draws_dollars: 600_000,
        releases_dollars: 0,
        shortfall_dollars: p.contingency.required_p80_dollars - 6_770_000,
        jcl_against_held: 0.393,
        cost_confidence_against_held: 0.4555,
        movements: [
          { date: "2026-04-28", type: "Draw", amount_dollars: 600_000, status: "Pending",
            risk_id: "WT-021", note: "Grid redesign" },
        ],
        illustrative: true,
      };
    });
    try {
      renderInProvider(<PmPage1 />);
      const panel = await screen.findByTestId("contingency-position");
      expect(panel.getAttribute("data-phase")).toBe("held");
      expect(within(panel).getByTestId("contingency-held").textContent).toBe(
        formatAudMillions(6_770_000),
      );
      expect(within(panel).getByTestId("contingency-jcl-held").textContent).toBe(
        formatPercent(0.393, 0),
      );
      expect(within(panel).getByTestId("contingency-gap").textContent).toContain("▼");
      expect(panel.textContent).toContain("Shortfall");
      expect(panel.textContent).toContain(`A further ${formatAudMillions(600_000)} of draws is pending`);
      expect(within(panel).getByTestId("contingency-illustrative")).toBeInTheDocument();
      expect(within(panel).getByTestId("contingency-movements").textContent).toContain("WT-021");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("says headroom, not shortfall, when held exceeds required", async () => {
    serveGoldenWith((p) => {
      p.contingency = {
        ...p.contingency, phase: "held", label: "Held against required at P80",
        held_dollars: 9_000_000, commitment_date: "2026-03-16", opening_held_dollars: 9_000_000,
        approved_draws_dollars: 0, pending_draws_dollars: 0, releases_dollars: 0,
        shortfall_dollars: p.contingency.required_p80_dollars - 9_000_000,
        jcl_against_held: 0.6, cost_confidence_against_held: 0.7, movements: [],
      };
    });
    try {
      renderInProvider(<PmPage1 />);
      const panel = await screen.findByTestId("contingency-position");
      expect(panel.textContent).toContain("Headroom");
      expect(panel.textContent).not.toContain("pending");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("the integrated card, as the home expander (part B, A-2; INTVIEW-01)", () => {
  it("renders the golden's integrated P80, not a number of its own", () => {
    const golden = goldenPeriod() as any;
    const integrated = golden.integrated as Integrated;
    expect(integrated, "the golden carries no integrated block").toBeTruthy();

    render(<IntegratedOutturnCard integrated={integrated} />);

    // Rendered through the app's own currency formatter, so assert on the digits rather than on
    // a formatting guess - the test must not encode a second opinion about how money looks.
    const rendered = screen.getByText(/P80 RISK CONTINGENCY/i).parentElement?.textContent ?? "";
    const digits = rendered.replace(/[^0-9]/g, "");
    expect(digits).toContain(String(Math.round(integrated.p80_dollars)).slice(0, 4));
  });

  it("is titled How the number is made up, and open by default", () => {
    const { container } = render(
      <IntegratedOutturnCard integrated={(goldenPeriod() as any).integrated as Integrated} />,
    );
    expect(screen.getByText("How the number is made up")).toBeInTheDocument();
    expect(container.querySelector("details")?.open).toBe(true);
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

  it("builds up to the golden's P80 from the engine's own rows (1.6)", () => {
    const integrated = (goldenPeriod() as any).integrated as Integrated;
    render(<IntegratedOutturnCard integrated={integrated} />);
    // The render gate the brief names: the expander's P80 row IS integrated.p80_dollars.
    expect(screen.getByTestId("build-up-p80").textContent?.trim()).toBe(
      formatAud(integrated.p80_dollars));
    const p80 = integrated.build_up.find((r) => r.p_level === 80)!;
    const text = screen.getByTestId("build-up").textContent ?? "";
    expect(text).toContain(formatAud(p80.event_cost_dollars));
    expect(text).toContain(formatAud(p80.delay_cost_dollars));
    expect(text).toContain(formatAud(Math.abs(p80.diversification_dollars)));
  });

  it("says what counts where, and the day rate as the engine states it (1.6)", () => {
    const integrated = (goldenPeriod() as any).integrated as Integrated;
    render(<IntegratedOutturnCard integrated={integrated} />);
    expect(screen.getByTestId("what-counts-where").textContent).toContain(
      integrated.what_counts_where);
    // A literal on purpose: the convention the Director agreed 28/10/2026, stated by the engine.
    expect(screen.getByTestId("what-counts-where").textContent).toMatch(
      /crane stood down waiting on wind/);
    const rate = screen.getByTestId("day-rate").textContent ?? "";
    expect(rate).toContain(formatAud(integrated.day_rate_derivation.day_rate_used));
    expect(rate).toContain(integrated.day_rate_derivation.note);
  });

  it("explains an absent block instead of rendering nothing", () => {
    render(<IntegratedOutturnCard unavailableReason="the register supplies no day rate" />);
    expect(screen.getByText(/no day rate/)).toBeInTheDocument();
  });

  it("is never blank, even with neither a block nor a reason (INTVIEW-01 property 8)", () => {
    render(<IntegratedOutturnCard />);
    expect(screen.getByText(NO_REASON_TEXT)).toBeInTheDocument();
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
    expect(text).toMatch(/includes delay cost/);
  });
});

describe("the contract version (1.6, INTVIEW-01 stage 2)", () => {
  it("refuses a 1.5 period with the version message, not a list of missing fields", async () => {
    serveGoldenWith((p) => {
      p.schema_version = "1.5";
      delete p.contingency;
      delete p.integrated.build_up;
    });
    try {
      renderInProvider(<PmPage1 />);
      expect(await screen.findByText(/declares period-JSON contract 1\.5/)).toBeInTheDocument();
      expect(document.body.textContent).toMatch(/written against 1\.6/);
      expect(document.body.textContent).not.toMatch(/failed period data validation/);
    } finally {
      vi.unstubAllGlobals();
    }
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
