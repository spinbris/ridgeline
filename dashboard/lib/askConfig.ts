/**
 * ASKSVC-01 stage B: the Ask box's configuration.
 *
 * The box is OFF until `enabled` is true here. That is deliberate sequencing, not a feature flag
 * left lying around: the first deploy publishes the reader manual (the Ask service reads it from
 * this site), the evaluation set is then run and graded against that deploy, and only then is the
 * box switched on, here and in the service's pack, together.
 *
 * Dashboard lock D1 is amended for exactly this: the app stays a static
 * export with no API routes, and makes one client fetch to the external service named below.
 * The browser sends app, project, period id and question, never any figures or context.
 */

export interface AskConfig {
  enabled: boolean;
  /** The shared Ask service's endpoint. Its own allowlist names this site's origin. */
  serviceUrl: string;
  /** This app's pack in the service. */
  app: string;
  /** The service refuses longer questions; the box stops the reader first. */
  maxQuestionChars: number;
  /**
   * Offered as one-tap questions. Exactly the `starter: true` cases of `docs/ask/eval_set.json`,
   * in that order, so every starter has been graded (held by `__tests__/askbox.test.tsx`).
   */
  starterQuestions: string[];
}

export const ASK_CONFIG: AskConfig = {
  enabled: true, // switched on 04/11/2026 after the graded eval (22 of 22 passed the number check)
  serviceUrl: "https://ask-service-navy.vercel.app/api/ask",
  app: "outturn",
  maxQuestionChars: 500,
  starterQuestions: [
    "What is the risk contingency at P80, and what does it cover?",
    "When is the project likely to finish?",
    "What changed since last month?",
    "Which risks are driving the most delay?",
    "What is the chance of finishing on budget and on time?",
    "Do we hold enough contingency?",
  ],
};

/** The fixed footer. Added by the app, never by the model. */
export const ASK_FOOTER = "AI explanation. The certified figures are in the report.";

/** "period_20260531.json" -> "20260531"; null for anything else. */
export function periodIdFrom(filename: string): string | null {
  const m = /^period_(\d{8})\.json$/.exec(filename);
  return m ? m[1] : null;
}

/**
 * Plain text from a model answer. The prompt asks for plain text; this is the belt to that
 * braces, because a stray `**` or backtick reads as noise to a non-specialist.
 */
export function plainText(answer: string): string {
  return answer
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```\w*\n?/g, ""))
    .replace(/`([^`]*)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?=[^*\w]|$)/g, "$1$2")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*[-*]\s+/gm, "• ")
    .trim();
}

export type AskOutcome =
  | { kind: "answer"; text: string; check: "pass" | "withheld" | "failed" }
  | { kind: "error"; message: string };

/** One question to the service. Never throws: every failure is a message for the reader. */
export async function askQuestion(
  config: AskConfig,
  project: string,
  periodId: string,
  question: string,
  fetcher: typeof fetch = fetch,
): Promise<AskOutcome> {
  let res: Response;
  try {
    res = await fetcher(config.serviceUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ app: config.app, project, period_id: periodId, question }),
    });
  } catch {
    return { kind: "error", message: "The Ask service could not be reached. Try again shortly." };
  }
  if (res.status === 429) {
    return { kind: "error", message: "Too many questions from this connection. Try again in an hour." };
  }
  let body: { answer?: unknown; check?: unknown; error?: unknown } = {};
  try {
    body = await res.json();
  } catch {
    // fall through to the generic message
  }
  if (!res.ok || typeof body.answer !== "string") {
    return { kind: "error", message: "The Ask service could not answer just now. The report has every figure." };
  }
  const check = body.check === "pass" || body.check === "withheld" ? body.check : "failed";
  return { kind: "answer", text: plainText(body.answer), check };
}
