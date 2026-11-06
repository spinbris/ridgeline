/**
 * ASKSVC-01 stage B: the Ask box. A reader asks a plain-English question about the period on
 * screen and gets an explanation from the shared Ask service.
 *
 * The service, not this component, carries the controls: it fetches the reader manual and the
 * period data itself, and checks every figure in the answer against that data before it returns,
 * withholding any it cannot match. This component sends four strings and shows what comes back,
 * as plain text, with the fixed footer the model never writes.
 *
 * Rendered once, in the layout, so it sits under every page. Off unless `ASK_CONFIG.enabled`.
 */

"use client";

import { useState, type FormEvent } from "react";

import { Card } from "@/components/Card";
import {
  ASK_CONFIG,
  ASK_FOOTER,
  askQuestion,
  periodIdFrom,
  type AskConfig,
  type AskOutcome,
} from "@/lib/askConfig";
import { usePeriodContext } from "@/lib/PeriodContext";

export function AskBox({ config = ASK_CONFIG }: { config?: AskConfig }) {
  const { status } = usePeriodContext();
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<AskOutcome | null>(null);

  if (!config.enabled || status.kind !== "ready") return null;
  const periodId = periodIdFrom(status.filename);
  if (periodId === null) return null;
  const { project } = status;

  async function ask(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    setQuestion(text);
    setAsked(text);
    setBusy(true);
    setOutcome(null);
    // The period is read at the moment of asking, so an answer always names the period it was
    // asked about even if the reader changes the picker while it is on its way.
    const result = await askQuestion(config, project, periodId as string, text);
    setOutcome(result);
    setBusy(false);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(question);
  }

  const over = question.length > config.maxQuestionChars;

  return (
    <div className="px-4 sm:px-6 pb-6 max-w-7xl mx-auto w-full">
      <Card title="Ask about these figures">
        <p className="text-sm mb-3" style={{ color: "var(--color-muted)" }}>
          Ask in plain English about the period on screen. Answers explain the published figures;
          they do not calculate new ones.
        </p>

        <div className="flex flex-wrap gap-2 mb-3" aria-label="Suggested questions">
          {config.starterQuestions.map((q) => (
            <button
              key={q}
              type="button"
              disabled={busy}
              onClick={() => void ask(q)}
              className="text-xs rounded-full border px-3 py-1 text-left disabled:opacity-50"
              style={{ borderColor: "var(--color-card-border)", color: "var(--color-body)" }}
            >
              {q}
            </button>
          ))}
        </div>

        <form onSubmit={onSubmit} className="flex flex-col gap-2 sm:flex-row sm:items-start">
          <label htmlFor="ask-question" className="sr-only">
            Your question
          </label>
          <textarea
            id="ask-question"
            rows={2}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="For example: why is the joint confidence below 80%?"
            className="flex-1 rounded-md border p-2 text-sm"
            style={{ borderColor: over ? "var(--color-fired)" : "var(--color-card-border)" }}
          />
          <button
            type="submit"
            disabled={busy || over || question.trim() === ""}
            className="rounded-md px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            style={{ backgroundColor: "var(--color-accent)" }}
          >
            {busy ? "Asking…" : "Ask"}
          </button>
        </form>
        {over && (
          <p className="text-xs mt-1" style={{ color: "var(--color-fired)" }}>
            Questions are limited to {config.maxQuestionChars} characters.
          </p>
        )}

        {busy && (
          <p role="status" className="text-sm mt-3" style={{ color: "var(--color-muted)" }}>
            Working on it. This usually takes a few seconds.
          </p>
        )}

        {outcome && (
          <div className="mt-4 text-sm" aria-live="polite">
            {asked && (
              <p className="font-semibold mb-2" style={{ color: "var(--color-body)" }}>
                {asked}
              </p>
            )}
            {outcome.kind === "error" ? (
              <p style={{ color: "var(--color-fired)" }}>{outcome.message}</p>
            ) : (
              <>
                {outcome.text.split(/\n{2,}/).map((para, i) => (
                  <p key={i} className="mb-2 whitespace-pre-line">
                    {para}
                  </p>
                ))}
                {outcome.check === "withheld" && (
                  <p className="text-xs mb-2" style={{ color: "var(--color-warn)" }}>
                    A figure was withheld because it could not be matched to the published data.
                    The report has every figure.
                  </p>
                )}
              </>
            )}
            <p className="text-xs mt-2" style={{ color: "var(--color-muted)" }}>
              {ASK_FOOTER}
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}
