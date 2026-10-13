/**
 * Small presentational formatters.
 *
 * Date strings in the JSON are always YYYY-MM-DD (Doc 3 v2.3 rule 1).
 * The dashboard renders them as "DD Mon YYYY" or "DD Mon" depending
 * on context (mockup convention: short form in number cells, full
 * form in the headline).
 *
 * All formatters are pure: input -> output, no side effects.
 */

const MONTH_SHORT = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/**
 * Parse a YYYY-MM-DD string into a UTC Date. Treats the string as
 * date-only (no timezone shift); we use UTC accessors to read it
 * back so the rendered day matches the JSON exactly regardless of
 * the user's locale.
 */
function parseIsoDate(iso: string): Date {
  // Defensive: split-and-construct is safer than new Date(iso) which
  // may apply timezone shifts at midnight UTC.
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

/** "2027-03-14" -> "14 Mar 2027" */
export function formatLongDate(iso: string): string {
  if (!iso) return "";
  const date = parseIsoDate(iso);
  return `${date.getUTCDate()} ${MONTH_SHORT[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

/** "2027-03-14" -> "14 Mar" (year omitted; used in the number row) */
export function formatShortDate(iso: string): string {
  if (!iso) return "";
  const date = parseIsoDate(iso);
  return `${date.getUTCDate()} ${MONTH_SHORT[date.getUTCMonth()]}`;
}

/** signed-day delta: 21 -> "+21 days", -4 -> "-4 days", 0 -> "no change" */
export function formatDaysDelta(days: number): string {
  if (days === 0) return "no change";
  const sign = days > 0 ? "+" : "";
  const label = Math.abs(days) === 1 ? "day" : "days";
  return `${sign}${days} ${label}`;
}

/** 0.175 -> "17.5%" */
export function formatPercent(p: number, digits = 1): string {
  return `${(p * 100).toFixed(digits)}%`;
}

/** 12345.67 -> "$12,345.67"; 180000 -> "$180,000" */
export function formatAud(n: number): string {
  return n.toLocaleString("en-AU", {
    style: "currency",
    currency: "AUD",
    maximumFractionDigits: 0,
  });
}

/** "Open" -> badge-class suffix "open"; mitigation statuses have their own keys. */
export function statusBadgeKey(
  status: string,
):
  | "open"
  | "actioned"
  | "monitor"
  | "fired"
  | "closed"
  | "proposed"
  | "approved"
  | "in_progress"
  | "completed"
  | "rejected"
  | "neutral" {
  const s = (status ?? "").toLowerCase();
  if (s === "proposed") return "proposed";
  if (s === "approved") return "approved";
  if (s === "in progress") return "in_progress";
  if (s === "completed") return "completed";
  if (s === "rejected") return "rejected";
  if (s === "open") return "open";
  if (s === "actioned") return "actioned";
  if (s === "monitor") return "monitor";
  if (s === "fired") return "fired";
  if (s === "closed") return "closed";
  return "neutral";
}

/** "consistent" -> "Consistent" (title-case for display) */
export function titleCase(s: string): string {
  if (!s) return "";
  return s
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
