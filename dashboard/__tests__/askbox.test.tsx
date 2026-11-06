/**
 * ASKSVC-01 stage B: the Ask box, and the showcase line that replaces the out-of-date banner.
 *
 * The Ask service is never called: `fetch` serves the golden period as `setup.ts` does, and the
 * service URL is answered here. Live answers are the evaluation set's job, on request only.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { goldenPeriod, routeState } from "./setup";
import { AppFooter } from "@/components/AppFooter";
import { AskBox } from "@/components/AskBox";
import { PeriodFreshnessBanner } from "@/components/PeriodFreshnessBanner";
import { ASK_CONFIG, ASK_FOOTER, periodIdFrom, plainText, type AskConfig } from "@/lib/askConfig";
import { formatLongDate } from "@/lib/formatters";
import { PeriodProvider } from "@/lib/PeriodContext";

const ON: AskConfig = { ...ASK_CONFIG, enabled: true, serviceUrl: "https://ask.test/api/ask" };
const EVAL_SET = path.resolve(__dirname, "..", "..", "docs", "ask", "eval_set.json");

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Wrap the golden-serving fetch: answer the service URL, optionally flag the manifest. */
function serve(opts: { reply?: unknown; status?: number; showcase?: boolean } = {}) {
  const served = globalThis.fetch;
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === ON.serviceUrl) {
      calls.push({ url, body: JSON.parse(String(init?.body)) });
      return new Response(JSON.stringify(opts.reply ?? {}), { status: opts.status ?? 200 });
    }
    const res = await served(input);
    if (opts.showcase && url.endsWith("/index.json") && res.ok) {
      const index = await res.json();
      return new Response(JSON.stringify({ ...index, showcase: true }), { status: 200 });
    }
    return res;
  });
  return calls;
}

function renderBox(config: AskConfig = ON) {
  return render(
    <PeriodProvider>
      <AppFooter />
      <AskBox config={config} />
    </PeriodProvider>,
  );
}

describe("the Ask box", () => {
  it("renders nothing when switched off", async () => {
    expect(ASK_CONFIG.enabled).toBe(true); // switched on after the graded eval, 04/11/2026
    renderBox({ ...ASK_CONFIG, enabled: false });
    await screen.findByText(/Engine run/);
    expect(screen.queryByText("Ask about these figures")).toBeNull();
  });

  it("sends only app, project, period id and question", async () => {
    const calls = serve({ reply: { answer: "It covers risk events.", check: "pass" } });
    renderBox();
    fireEvent.click(await screen.findByRole("button", { name: ON.starterQuestions[0] }));
    await screen.findByText("It covers risk events.");
    const golden = goldenPeriod() as any;
    expect(calls).toHaveLength(1);
    expect(calls[0].body).toEqual({
      app: "outturn",
      project: golden.meta.project_key,
      period_id: golden.meta.period_end_date.replace(/-/g, ""),
      question: ON.starterQuestions[0],
    });
    expect(screen.getByText(ASK_FOOTER)).toBeVisible();
  });

  it("shows markdown as plain text", async () => {
    serve({ reply: { answer: "The **P80** is in `integrated.p80_dollars`.", check: "pass" } });
    renderBox();
    fireEvent.change(await screen.findByLabelText("Your question"), { target: { value: "What?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("The P80 is in integrated.p80_dollars.");
  });

  it("says plainly when a figure was withheld", async () => {
    serve({ reply: { answer: "It is [figure withheld].", check: "withheld" } });
    renderBox();
    fireEvent.click(await screen.findByRole("button", { name: ON.starterQuestions[1] }));
    await screen.findByText(/A figure was withheld/);
  });

  it("turns a service failure or rate limit into a message, not a crash", async () => {
    serve({ reply: { error: "origin not allowed" }, status: 403 });
    renderBox();
    fireEvent.click(await screen.findByRole("button", { name: ON.starterQuestions[2] }));
    await screen.findByText(/could not answer just now/);
  });

  it("names the rate limit", async () => {
    serve({ status: 429 });
    renderBox();
    fireEvent.click(await screen.findByRole("button", { name: ON.starterQuestions[3] }));
    await screen.findByText(/Too many questions/);
  });

  it("stops a question over the service's limit before it is sent", async () => {
    const calls = serve();
    renderBox();
    fireEvent.change(await screen.findByLabelText("Your question"), {
      target: { value: "x".repeat(ON.maxQuestionChars + 1) },
    });
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(screen.getByText(/limited to 500 characters/)).toBeVisible();
    expect(calls).toHaveLength(0);
  });

  it("offers exactly the evaluation set's starter questions, in order", () => {
    const set = JSON.parse(readFileSync(EVAL_SET, "utf-8"));
    const starters = set.cases.filter((c: any) => c.starter).map((c: any) => c.question);
    expect(ASK_CONFIG.starterQuestions).toEqual(starters);
  });
});

describe("its helpers", () => {
  it("reads the period id from the filename", () => {
    expect(periodIdFrom("period_20260531.json")).toBe("20260531");
    expect(periodIdFrom("index.json")).toBeNull();
  });

  it("strips bold, code, headings and bullets", () => {
    expect(plainText("## Heading\n- **one** and `two`\n* three")).toBe("Heading\n• one and two\n• three");
  });
});

describe("the showcase line (ASKSVC-01 stage B item 7)", () => {
  it("replaces the out-of-date warning with a neutral example-project line", async () => {
    // Far in the future, so a live project would be STALE or LATE by now.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.parse("2030-01-01T00:00:00Z"));
    serve({ showcase: true });
    try {
      routeState.pathname = "/analyst";
      render(<PeriodProvider><PeriodFreshnessBanner /></PeriodProvider>);
      const line = await screen.findByRole("status");
      const end = (goldenPeriod() as any).meta.period_end_date;
      expect(line.textContent).toMatch(/Example project/);
      expect(line.textContent).toContain(formatLongDate(end));
      expect(line.textContent).not.toMatch(/Out of date|Update overdue/);
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves a live project's warning as it was", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.parse("2030-01-01T00:00:00Z"));
    serve();
    try {
      routeState.pathname = "/analyst";
      render(<PeriodProvider><PeriodFreshnessBanner /></PeriodProvider>);
      await waitFor(() => expect(screen.getByRole("status").textContent).toMatch(/Update overdue|Out of date/));
    } finally {
      vi.useRealTimers();
    }
  });
});

