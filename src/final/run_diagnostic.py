"""The per-run one-page diagnostic (REPORT01 F-G).

GAP01 F-G: the predecessor line wrote a one-page per-run summary - verdict, headline,
drivers, audit trail - and here that required opening the docx or reading JSON. The old
user guide promised it, which is how the claim survived into guide v1.1.

`scripts/sr9_diagnostic.py` **did** write one, in this format, and was never absent from
the tree. What it was, was unreachable and stale: no caller, a cache path that had
diverged from the deliverable's, artefact names from retired standalone drivers, and no
Stage 3 awareness at all - so it printed the superseded Stage 2.5 headline. Its format
is kept here and everything it asserted about the world is re-derived from the run.

Plain text on purpose: greppable, diffable, and readable with no tooling on a machine
that has none. No PDF (D-12).

Data in, string out. The deliverable calls :func:`format_run_diagnostic` with what it
already holds in memory, so the one-pager cannot disagree with the manifest beside it.

**DIAGFIX-01 (14/09/2026): every reading below is by the name the run actually uses.** The
first version read ``checks``, ``random_seed``, ``{"sha256": ...}``, the first numeric driver
column and the cross-validation verdict alone - shapes its tests were built in, and the
deliverable hands it none of them. Five lines were wrong on every real page.
"""
from __future__ import annotations

from typing import Any

_RULE = "=" * 78
_THIN = "-" * 78

#: The banner a failed run puts at the top. D-11 writes every artefact and fails after,
#: so this file exists on a failed run and has to say so in the first thing a reader sees.
#: It says the run failed, not that cross-validation did: a run whose four checks pass and
#: whose Stage 3 pair was not written fails too (DIAGFIX-01 F-5).
FAIL_BANNER = (
    "*** THIS RUN FAILED ITS GATE - IT IS NOT A VALID DELIVERABLE ***"
)
PASS_BANNER = "Cross-validation: PASS"

#: The four checks ``cross_validate_reports`` ANDs into ``all_pass``, by the keys it returns,
#: in the order the user guide's §8.3 numbers them. A key renamed there reads as missing here,
#: and the §6a outputs test, which compares a real run with this page, goes red.
GATE_CHECKS: tuple[tuple[str, str], ...] = (
    ("1 cost calibration", "cost_passes_calibration"),
    ("2 schedule", "schedule_passes_calibration"),
    ("3 top-3 cost drivers", "top_3_cost_contributors_consistent"),
    ("4 top-3 schedule drivers", "top_3_schedule_contributors_consistent"),
)

#: What check 2 compared, by the ``schedule_check_basis`` the cross-validator records.
_CHECK_2_BASIS = {
    "stage3_cross_surface": "Stage 3 cross-surface",
    "stage25_sr5_legacy": "Stage 2.5 calibration (legacy basis)",
}

#: The column each drivers table is ranked by, in the section builders' own spelling, used when
#: the section does not name its own. The cost section does (``value_column_header``), and that
#: is read first; the schedule section does not, so its name is held against the builder's
#: source by a stage-lane test rather than trusted.
RANKING_COLUMNS = {
    "page3_cost_drivers": ("P80 contribution ($M)", "Mean contribution ($M)"),
    "page4_schedule_drivers": ("Probability x mean impact (days)",),
}


def _fmt_dollars(value: Any) -> str:
    try:
        return f"${float(value) / 1e6:,.3f}M"
    except (TypeError, ValueError):
        return "(not available)"


def _headline_lines(composed: dict[str, Any]) -> list[str]:
    """The Stage 3 headline, which is the product's headline (STAGE3HEADLINE-01).

    Not ``headline_contingency_range_p80``: that is the Stage 2.5 comparator, and it is
    what the unwired predecessor of this file printed.
    """
    es = composed.get("executive_summary", {}) or {}
    h = es.get("headline_stage3")
    if not h:
        reason = es.get("headline_stage3_absent_reason", "no reason recorded")
        return [f"  Stage 3 headline: NOT PRESENT ({reason})"]

    lines = []
    p_level = h.get("p_level")
    lines.append(
        f"  Headline (P{p_level}):      {_fmt_dollars(h.get('headline_dollars'))}")
    for p in h.get("p_levels", ()):
        key = f"p{p}_dollars"
        if key in h:
            lines.append(f"    P{p}:{'':<16}{_fmt_dollars(h[key])}")
    if "mean_dollars" in h:
        lines.append(f"    Mean:{'':<14}{_fmt_dollars(h['mean_dollars'])}")
    basis = h.get("basis")
    if basis:
        lines.append(f"  Basis: {basis}")
    return lines


def _driver_lines(composed: dict[str, Any], key: str, label: str, n: int = 3) -> list[str]:
    """The top drivers, each with the measure its table is ranked by - chosen by column name.

    The first version took the first numeric-looking column. For the cost table that happened
    to be the ranking column; for the schedule table it was ``Probability`` (F-4).
    """
    section = composed.get(key, {}) or {}
    rows = section.get("drivers_table") or []
    if not rows:
        return [f"  {label}: (none reported)"]
    own = section.get("value_column_header")
    candidates = ((own,) if own else ()) + RANKING_COLUMNS[key]
    column = next((c for c in candidates if c in rows[0]), None)
    if column is None:
        return [f"  {label}: the drivers table carries no ranking column "
                f"({' or '.join(RANKING_COLUMNS[key])}); not printed"]
    out = [f"  {label}, by {column}:"]
    for row in rows[:n]:
        rid = row.get("Risk", "?")
        title = str(row.get("Title", ""))[:44]
        out.append(f"    {rid:<12} {title:<46} {row.get(column)}")
    return out


def _run_verdict(cross_validation: dict[str, Any],
                 provenance: dict[str, Any]) -> tuple[bool, str | None]:
    """The run's verdict, and a note when it had to be read from somewhere narrower.

    The exit gate reads the provenance's ``cross_validation_all_pass``, which is the four checks
    and the Stage 3 standalone pair having been written. The first version read the
    cross-validation result alone, so a run failing only on its Stage 3 pair printed PASS (F-5).
    A provenance from before that field existed falls back, and the page says so.
    """
    if "cross_validation_all_pass" in provenance:
        return bool(provenance["cross_validation_all_pass"]), None
    return (bool(cross_validation.get("all_pass", False)),
            "Verdict read from the cross-validation result: this run's provenance records no "
            "overall verdict.")


def _gate_lines(cross_validation: dict[str, Any], provenance: dict[str, Any],
                passed: bool, verdict_note: str | None) -> list[str]:
    """The four checks the verdict is made of, and anything else that failed the run.

    The first version read a ``checks`` key the cross-validator never returns and printed only
    "Overall" (F-1). A failed verdict that no line explains says so, because that is what a
    fifth check added to ``all_pass`` would otherwise look like (P-1).
    """
    lines: list[str] = []
    any_named_failure = False
    for label, key in GATE_CHECKS:
        if key == "schedule_passes_calibration":
            basis = cross_validation.get("schedule_check_basis")
            label = f"{label} ({_CHECK_2_BASIS.get(basis, basis or 'basis not recorded')})"
        if key not in cross_validation:
            lines.append(f"  ?     {label} - not in the cross-validation result")
            continue
        ok = bool(cross_validation[key])
        any_named_failure |= not ok
        lines.append(f"  {'PASS' if ok else 'FAIL'}  {label}")
    stage3_error = provenance.get("stage3_standalone_error")
    if stage3_error:
        any_named_failure = True
        lines.append(f"  FAIL  Stage 3 standalone pair not written: {stage3_error}")
    if not passed and not any_named_failure:
        lines.append("  FAIL outside the checks listed here - see cv_result.interpretation "
                     "in metadata.json")
    lines.append(f"  Overall: {'PASS' if passed else 'FAIL'}")
    if verdict_note:
        lines.append(f"  {verdict_note}")
    return lines


def _digest(digest: Any) -> str:
    """``{method, value}`` since PROVCRLF01. Anything else is said to be unrecognised rather
    than printed as a Python repr or guessed at (F-3)."""
    if isinstance(digest, dict) and set(digest) >= {"method", "value"}:
        return f"{digest['value']} ({digest['method']})"
    return "(unrecognised digest shape - see provenance.json)"


def format_run_diagnostic(
    *,
    composed: dict[str, Any],
    cross_validation: dict[str, Any],
    provenance: dict[str, Any],
    artefacts: list[Any] | None = None,
) -> str:
    """Render the one-page run diagnostic.

    ``provenance`` is the manifest dict the deliverable builds, so the audit trail here
    and the manifest beside it come from one source rather than two that can drift.
    """
    passed, verdict_note = _run_verdict(cross_validation, provenance)
    lines: list[str] = [_RULE]
    lines.append("RUN DIAGNOSTIC")
    lines.append(_RULE)
    lines.append(FAIL_BANNER if not passed else PASS_BANNER)
    lines.append("")

    lines.append(f"Project:        {provenance.get('project', '(unknown)')}")
    lines.append(f"Run date:       {provenance.get('run_date', '(unknown)')}")
    lines.append(f"Timestamp:      {provenance.get('timestamp', '(unknown)')}")
    lines.append(f"Run token:      {provenance.get('run_token') or '(none)'}")
    lines.append("")

    lines.append(_THIN)
    lines.append("HEADLINE")
    lines.append(_THIN)
    lines.extend(_headline_lines(composed))
    lines.append("")

    lines.append(_THIN)
    lines.append("TOP DRIVERS")
    lines.append(_THIN)
    lines.extend(_driver_lines(composed, "page3_cost_drivers", "Cost"))
    lines.extend(_driver_lines(composed, "page4_schedule_drivers", "Schedule"))
    lines.append("")

    lines.append(_THIN)
    lines.append("GATE")
    lines.append(_THIN)
    lines.extend(_gate_lines(cross_validation, provenance, passed, verdict_note))
    lines.append("")

    lines.append(_THIN)
    lines.append("PROVENANCE")
    lines.append(_THIN)
    lines.append(f"  Engine commit:  {provenance.get('engine_sha', '(unknown)')}")
    dirty = provenance.get("engine_tree_dirty")
    lines.append(
        f"  Engine tree:    {'DIRTY - not a reproducible run' if dirty else 'clean'}")
    lines.append(f"  Iterations:     {(provenance.get('params') or {}).get('iterations', '?')}")
    lines.append(f"  Seed:           {(provenance.get('params') or {}).get('seed', '(not recorded)')}")
    for name, digest in (provenance.get("input_sha256") or {}).items():
        lines.append(f"  {name + ':':<15} {_digest(digest)}")
    lines.append("")

    lines.append(_THIN)
    lines.append("ARTEFACTS")
    lines.append(_THIN)
    for path in (artefacts or provenance.get("artefacts") or []):
        lines.append(f"  {path}")
    lines.append("")
    lines.append(_RULE)
    if not passed:
        lines.append(FAIL_BANNER)
        lines.append(_RULE)
    return "\n".join(lines) + "\n"
