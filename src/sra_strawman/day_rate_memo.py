"""Day-rate derivation and reconciliation (Brief Section 3.5).

Derives the site-running rate from SP12 Preliminaries / P6 programme
working days. Scans each Open risk's Contingent Basis-of-Estimate text
for two things:

  1. days-x-rate patterns that flag the risk as "dual-coded" - cost ML
     built from a duration figure times a rate (rather than a stand-alone
     cost estimate). These are the risks listed for post-workshop cost
     refactor.
  2. explicit dollar-per-day or dollar-per-week rate quotes in the
     narrative, so the DayRate_Reconciliation sheet can compare them
     against the derived site-running rate.

No Risk ID literals appear here - dual-coded status is derived entirely
from narrative pattern matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

from src.sra_strawman.defaults import (
    CALENDAR_PER_WORKING_DAY_RATIO,
    PROGRAMME_WORKING_DAYS,
)

SP12_PRELIM_SHEET = "Pricing Summary"
SP12_PRELIM_CELL = "R8"

# Patterns that signal a days-x-rate cost build.
_RE_RATE_QUOTE = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:k\b)?\s*(?:/|per)\s*(day|wd|working\s*day|week|wk|hour|hr)",
    re.IGNORECASE,
)
_RE_DURATION_TOKEN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:weeks?|days?|wd|wks?|hrs?|hours?)\b",
    re.IGNORECASE,
)
# Multiplication symbol (x, *, or unicode ×). The regex class relies on
# word boundaries so "Approx" / "Fix" don't trigger on the letter x.
_RE_MULTIPLIER_SYMBOL = re.compile(r"(?:\s[x×]\s|\*|\b[x×]\s)", re.IGNORECASE)
_RE_PRELIM_REF = re.compile(r"\b(prelim|site\s*running)", re.IGNORECASE)


@dataclass(frozen=True)
class DayRateContext:
    preliminaries_total: float
    programme_working_days: int
    rate_per_working_day: float
    rate_per_calendar_day: float
    source_cell: str  # e.g. "Pricing Summary!R8"


@dataclass(frozen=True)
class DualCodedFinding:
    risk_id: str
    is_dual_coded: bool
    boe_excerpt: str
    rate_quote_raw: str | None  # the matched "$X/day" text, if any
    rate_quote_value_per_day: float | None  # normalised to $/day
    days_times_pattern: bool  # True if a "N days x ..." pattern was seen
    prelim_ref: bool  # True if narrative references "prelim" or "site running"


def read_sp12_preliminaries(path: str | Path) -> tuple[float, str]:
    """Read the Preliminaries total from SP12 at Pricing Summary!R8.

    Returns (value, source_cell_str). Raises if the cell is blank or
    outside the sanity range recorded in pre-flight Check 3.0.5.
    """
    wb = load_workbook(str(path), read_only=True, data_only=True)
    if SP12_PRELIM_SHEET not in wb.sheetnames:
        wb.close()
        raise ValueError(
            f"Sheet {SP12_PRELIM_SHEET!r} not found. Sheets: {wb.sheetnames}"
        )
    sht = wb[SP12_PRELIM_SHEET]
    val = sht[SP12_PRELIM_CELL].value
    wb.close()
    if val is None:
        raise ValueError(f"{SP12_PRELIM_SHEET}!{SP12_PRELIM_CELL} is blank")
    try:
        f = float(val)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{SP12_PRELIM_SHEET}!{SP12_PRELIM_CELL} is not numeric: {val!r}"
        ) from exc
    # Pre-flight Check 3.0.5 sanity range.
    if not (70_000_000.0 <= f <= 85_000_000.0):
        raise ValueError(
            f"{SP12_PRELIM_SHEET}!{SP12_PRELIM_CELL} = {f:,.0f} is outside "
            f"pre-flight sanity range $70M-$85M"
        )
    return f, f"{SP12_PRELIM_SHEET}!{SP12_PRELIM_CELL}"


def derive_day_rate_context(sp12_path: str | Path) -> DayRateContext:
    """Compose a DayRateContext from SP12 + programme working days."""
    prelim, source = read_sp12_preliminaries(sp12_path)
    per_wd = prelim / PROGRAMME_WORKING_DAYS
    per_cd = prelim / (PROGRAMME_WORKING_DAYS * CALENDAR_PER_WORKING_DAY_RATIO)
    return DayRateContext(
        preliminaries_total=prelim,
        programme_working_days=PROGRAMME_WORKING_DAYS,
        rate_per_working_day=per_wd,
        rate_per_calendar_day=per_cd,
        source_cell=source,
    )


def _normalise_rate_quote(amount_str: str, unit: str) -> float:
    """Normalise an extracted "$X/unit" quote to $/day.
    week -> /5, day/wd -> as-is, hr -> x8 (nominal 8hr day).
    """
    raw = amount_str.replace(",", "")
    amt = float(raw)
    # Handle "$125k/day" form: regex captures the "125" and we sniff for "k"
    # after the amount. Simpler: tolerate "k" already stripped at boundary.
    unit_l = unit.lower().strip()
    if unit_l in ("week", "wk", "weeks"):
        return amt / 5.0
    if unit_l.startswith("wee") or unit_l == "wk" or unit_l == "wks":
        return amt / 5.0
    if unit_l in ("hour", "hr", "hrs", "hours"):
        return amt * 8.0
    # day / wd / working day
    return amt


def detect_dual_coded(risk_id: str, boe_text: str | None) -> DualCodedFinding:
    """Scan one risk's Contingent BOE narrative for dual-coded patterns."""
    text = (boe_text or "").strip()
    rate_quote_raw: str | None = None
    rate_quote_value: float | None = None
    # Days-x-rate signal: a duration token AND a multiplier symbol in the text.
    # This is more tolerant than requiring them to be adjacent - narratives
    # such as "4 Hrs per event x prelim rate" separate them with 1-3 words.
    days_times = bool(
        _RE_DURATION_TOKEN.search(text) and _RE_MULTIPLIER_SYMBOL.search(text)
    )
    prelim_ref = bool(_RE_PRELIM_REF.search(text))

    m = _RE_RATE_QUOTE.search(text)
    if m:
        # Preserve original match plus any "$Xk" form: re-check for 'k' suffix.
        rate_quote_raw = m.group(0)
        amt_str = m.group(1)
        unit = m.group(2)
        value = _normalise_rate_quote(amt_str, unit)
        # Detect "$125k/day" - look back 3 chars for "k" after the amount.
        span_start, span_end = m.span()
        # Search for a trailing 'k' attached to the amount, before the '/'.
        amt_end = m.start(1) + len(amt_str)
        trailing = text[amt_end:amt_end + 2].lower().strip()
        if trailing.startswith("k"):
            value *= 1000.0
        rate_quote_value = value

    is_dual = days_times or bool(m) or (prelim_ref and "$" in text)
    excerpt = text.replace("\n", " ")[:200]
    return DualCodedFinding(
        risk_id=risk_id,
        is_dual_coded=is_dual,
        boe_excerpt=excerpt,
        rate_quote_raw=rate_quote_raw,
        rate_quote_value_per_day=rate_quote_value,
        days_times_pattern=days_times,
        prelim_ref=prelim_ref,
    )


def classify_rate_hypothesis(
    narrative_rate_per_day: float | None,
    derived_rate_per_day: float,
) -> str:
    """Return a one-line hypothesis about the gap between narrative and derived rates."""
    if narrative_rate_per_day is None:
        return "Days-x-rate pattern detected but no explicit rate quoted"
    ratio = narrative_rate_per_day / max(derived_rate_per_day, 1.0)
    if ratio < 0.8:
        return "Narrative rate below site-running rate - likely excludes prelims"
    if ratio <= 1.2:
        return "Narrative rate aligns with derived site-running rate"
    if ratio <= 3.0:
        return "Gap consistent with peak-labour / IDC overlay on site rate"
    return "Gap consistent with LD + peak-labour + IDC stacked on site rate"


def build_dual_coded_findings(risks: list[dict]) -> list[DualCodedFinding]:
    """Apply detect_dual_coded across the risk register."""
    out: list[DualCodedFinding] = []
    for r in risks:
        rid = str(r.get("risk_id") or "").strip()
        boe = r.get("cost_basis_of_estimate")
        out.append(detect_dual_coded(rid, boe if isinstance(boe, str) else None))
    return out


def build_reconciliation_rows(
    risks: list[dict],
    ctx: DayRateContext,
) -> list[dict]:
    """Build rows for the DayRate_Reconciliation comparison table.

    One row per dual-coded risk, with the narrative rate, derived rate,
    gap, and hypothesis.
    """
    findings = build_dual_coded_findings(risks)
    rows: list[dict] = []
    for f in findings:
        if not f.is_dual_coded:
            continue
        narrative = f.rate_quote_value_per_day
        gap = None if narrative is None else narrative - ctx.rate_per_working_day
        rows.append(
            {
                "risk_id": f.risk_id,
                "boe_excerpt": f.boe_excerpt,
                "narrative_rate_per_wd": narrative,
                "narrative_rate_raw": f.rate_quote_raw,
                "derived_rate_per_wd": ctx.rate_per_working_day,
                "gap_per_wd": gap,
                "hypothesis": classify_rate_hypothesis(
                    narrative, ctx.rate_per_working_day
                ),
                "days_times_pattern": f.days_times_pattern,
                "prelim_reference": f.prelim_ref,
            }
        )
    return rows


def dual_coded_risk_ids(risks: list[dict]) -> list[str]:
    """Return the list of risk IDs flagged as dual-coded."""
    return [f.risk_id for f in build_dual_coded_findings(risks) if f.is_dual_coded]
