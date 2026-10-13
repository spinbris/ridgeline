/**
 * PUBLICFACE-01 P4: what a public reader meets in the app.
 *
 * A mitigation whose period data says `proposed` is labelled for what it is, an empty state tells
 * the reader something usable, and no rendered page names an internal document or plan. The pages
 * are rendered against the committed golden, as the render gate does.
 */
import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { routeState } from "./setup";
import { PeriodProvider } from "@/lib/PeriodContext";
import { StatusBadge } from "@/components/StatusBadge";
import MitigationsPage from "@/app/mitigations/page";
import PmPage1 from "@/app/page";
import DriversPage from "@/app/analyst/drivers/page";
import AuditPage from "@/app/analyst/audit/page";
import { StochasticGantt } from "@/components/charts/StochasticGantt";
import ActivitiesPage from "@/app/analyst/activities/page";

const INTERNAL = [
  /\bDoc \d/,
  /\bv\d+(\.\d+)*\b/,
  /\bSR\d+/,
  /\bAM_[A-Za-z]/,
  /queued/i,
  // The class, not the instance (gate 3 round 1, W1).
  /\bAM\d{2}/,
  /§/,
  /stage brief/i,
  /\b(WIND|ROAD|MIT|RSK)-\d/,
];

function internalIn(text: string): string[] {
  return INTERNAL.map((rx) => text.match(rx)?.[0]).filter((m): m is string => !!m);
}

describe("the status badge", () => {
  it.each([
    ["proposed", "Proposed"],
    ["approved", "Approved"],
    ["in progress", "In progress"],
    ["completed", "Completed"],
    ["rejected", "Rejected"],
    ["open", "Open"],
  ])("labels %s for what it is", (status, label) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByText(/unknown/i)).toBeNull();
  });

  it("shows a status it does not know as the data states it, and an empty one as not set", () => {
    const { unmount } = render(<StatusBadge status="paused" />);
    expect(screen.getByText("paused")).toBeInTheDocument();
    unmount();
    render(<StatusBadge status="" />);
    expect(screen.getByText("Not set")).toBeInTheDocument();
  });
});

describe("rendered pages carry no internal reference", () => {
  const pages: [string, string, () => React.ReactNode, RegExp][] = [
    ["/mitigations", "mitigations", () => <MitigationsPage />, /No mitigations have been proposed/],
    ["/", "PM landing", () => <PmPage1 />, /No milestones are listed for this period/],
    ["/analyst/drivers", "drivers", () => <DriversPage />, /not yet implemented/],
    ["/analyst/activities", "activities", () => <ActivitiesPage />, /Activity-level detail/],
    ["/analyst/audit", "audit", () => <AuditPage />, /Calibration gates/],
  ];

  it.each(pages)("%s (%s)", async (pathname, _name, page, anchor) => {
    routeState.pathname = pathname;
    render(<PeriodProvider>{page()}</PeriodProvider>);
    await waitFor(() => expect(document.body.textContent ?? "").toMatch(anchor));
    expect(internalIn(document.body.textContent ?? "")).toEqual([]);
  });
});

describe("the stochastic Gantt's empty state", () => {
  it("explains the top-N list in plain words, with no spec reference", () => {
    render(<StochasticGantt items={[]} topNRequested={10} />);
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/No activities meet the top-N/);
    expect(internalIn(text)).toEqual([]);
  });
});
