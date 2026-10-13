"""What each register column means — REGUX-01.

**Why this module exists.** Stage 4 stopped at step 2: an analyst generated an empty register and
could not fill it. The formats were never unknown — they were recorded in the code, where no
filler will ever look. `Effectiveness_Pct`'s scale lived in a comment in a report section;
`Injection_Method`'s legal values in a parser constant; `Probability`'s scale only in the
comparison that consumes it.

So this is the **one place** a column's meaning is stated, and everything else reads from it: the
scaffolder writes the workbook's README and its per-sheet note blocks from these specs, and
`tests/test_regux01_field_spec.py` holds them against the parsers that define them. That test is
the point of the module. Correct instructions written once and left to rot are how
`SOFTWARE_USER_GUIDE.md` §3.1 came to describe a workbook that no longer exists; a spec that
cannot drift from its parser is the only version worth writing.

**Adding a column to a fillable sheet without adding a spec fails the suite.** That is deliberate:
a column whose format nobody can state is a column whose format nobody knows.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Sheets a person fills by hand. Everything else is model-written or derived, and gets a
#: do-not-type banner instead of a note block (REGUX-01 §5.3).
FILLABLE_SHEETS = (
    "Risk Register",
    "Mapping",
    "Risk_Activity_Patterns",
    "Risk_Pattern_Assignments",
    "Treatments",
)


@dataclass(frozen=True)
class FieldSpec:
    """One column, and what a person must know to fill it.

    ``consumed_by`` is load-bearing rather than decorative: three columns in this register are
    read into the frame and never used by the engine, and a filler agonising over their scale is
    wasting effort the model will not notice. Saying so is more useful than inventing a scale.
    """

    sheet: str
    column: str
    #: One line, in the workbook's voice. This is what the filler actually reads.
    guidance: str
    #: Enumerated legal values, or None for free/numeric input.
    legal_values: tuple[str, ...] | None = None
    #: What an empty cell means. "" when blank is simply not allowed.
    blank_means: str = ""
    #: The module that consumes it, or the sentinel below when nothing does.
    consumed_by: str = ""


#: For a column read into the frame but never used in a calculation. Named rather than left blank
#: so the distinction survives a careless edit.
NOT_CONSUMED = "not read by the engine — provenance for a human reviewer"


FIELD_SPECS: tuple[FieldSpec, ...] = (
    # ---- Risk Register: the two that cause order-of-magnitude errors -------------------
    FieldSpec(
        sheet="Risk Register", column="Probability",
        guidance=("A FRACTION between 0 and 1, not a percentage. 0.45 means 45%. Entering 45 "
                  "makes the risk fire on every iteration, silently."),
        consumed_by="src/simulation.py (compared against a uniform draw)",
    ),
    FieldSpec(
        sheet="Risk Register", column="Probability (Time)",
        guidance="A fraction between 0 and 1, as for Probability. 0.45 means 45%.",
        consumed_by="src/simulation.py",
    ),
    FieldSpec(
        sheet="Risk Register", column="Distribution",
        guidance=("Chooses how the three-point estimate is read. Triangular and PERT treat "
                  "Optimistic/Pessimistic as ABSOLUTE BOUNDS; Lognormal treats them as roughly "
                  "P10/P90 with a tail beyond Pessimistic, and Most Likely as the median."),
        legal_values=("Triangular", "PERT", "Binary", "Binary/PERT", "Lognormal"),
        consumed_by="src/distributions.py",
    ),
    FieldSpec(
        sheet="Risk Register", column="Optimistic ($)",
        guidance=("Cost if the risk occurs and goes well. Its meaning depends on Distribution: a "
                  "bound under Triangular/PERT, roughly the P10 under Lognormal. This is the "
                  "cost GIVEN the risk occurs — the probability is applied separately."),
        consumed_by="src/distributions.py",
    ),
    FieldSpec(
        sheet="Risk Register", column="Most Likely ($)",
        guidance="The modal cost given the risk occurs. Under Lognormal this is the median.",
        consumed_by="src/distributions.py",
    ),
    FieldSpec(
        sheet="Risk Register", column="Pessimistic ($)",
        guidance=("Cost if the risk occurs and goes badly. A bound under Triangular/PERT; "
                  "roughly the P90 under Lognormal, which samples beyond it."),
        consumed_by="src/distributions.py",
    ),
    FieldSpec(
        sheet="Risk Register", column="Time Impact",
        guidance=("Yes if this risk also delays the schedule. A Yes row must carry a Mode and a "
                  "row on the Mapping sheet, or the schedule arm cannot bind it."),
        legal_values=("Yes", "No"),
        consumed_by="src/sra/strawman_reader.py",
    ),
    FieldSpec(
        sheet="Risk Register", column="Mode",
        guidance=("How the delay combines with others. Required on every Time Impact = Yes row; "
                  "the build fails without it."),
        legal_values=("Series", "Hybrid", "Parallel"),
        consumed_by="src/qra_register_parse.py (Grid_Methodology multipliers)",
    ),
    # ---- Mapping: the schedule binding -------------------------------------------------
    FieldSpec(
        sheet="Mapping", column="Prefix_List",
        guidance=("ONE activity-code prefix, despite the column name — e.g. `20.` to bind every "
                  "activity whose code starts with 20, or a full code to bind exactly one. A "
                  "trailing dot is stripped."),
        blank_means="the risk binds nothing and contributes no delay",
        consumed_by="src/integrated/stage3_config.py, src/am/project_binding.py",
    ),
    FieldSpec(
        sheet="Mapping", column="Injection_Method",
        guidance="How the sampled delay is applied to the bound activities.",
        legal_values=("additive_pert_days", "discrete_event_additive_days",
                      "productivity_multiplicative_factor"),
        blank_means="use the register default, Methodology!Default_Injection_Method",
        consumed_by="src/qra_register_parse.py",
    ),
    FieldSpec(
        sheet="Mapping", column="Gating_Activity_ID",
        guidance=("The single activity this risk gates, as it appears in the schedule. An ID that "
                  "names no activity is SKIPPED, not guessed — the risk then falls back to the "
                  "programme profile with nothing on screen saying so."),
        consumed_by="src/sra/_pre_flight.py",
    ),
    # ---- Treatments: the ambiguity REGUX-01 §5.2 ruled to document, not remove ----------
    FieldSpec(
        sheet="Treatments", column="Effectiveness_Pct",
        guidance=("A PERCENTAGE: enter 30 for 30%. The engine also accepts a 0-1 fraction and "
                  "splits the two at 1.0 — so 1.0 is read as 1%, NOT as fully effective. Enter "
                  "100 for a fully effective treatment."),
        consumed_by="src/final/sections/action_implications.py",
    ),
    FieldSpec(
        sheet="Treatments", column="Effectiveness_Confidence",
        guidance="Free text. Record how firm the effectiveness estimate is, in your own words.",
        consumed_by=NOT_CONSUMED,
    ),
    # ---- The three columns that look like inputs and reach nothing ----------------------
    FieldSpec(
        sheet="Risk_Activity_Patterns", column="Default_Mapping_Confidence",
        guidance=("Free text — any scale you like, or leave it blank. Nothing in the engine reads "
                  "it; it is provenance for whoever reviews the mapping."),
        blank_means="nothing; the engine does not read this column",
        consumed_by=NOT_CONSUMED,
    ),
    FieldSpec(
        sheet="Risk_Pattern_Assignments", column="Assignment_Confidence",
        guidance=("Free text, as for Default_Mapping_Confidence. Read into the frame and never "
                  "used in a calculation."),
        blank_means="nothing; the engine does not read this column",
        consumed_by=NOT_CONSUMED,
    ),
)


def specs_for(sheet: str) -> tuple[FieldSpec, ...]:
    """Every spec on one sheet, in declaration order."""
    return tuple(f for f in FIELD_SPECS if f.sheet == sheet)


def note_lines(sheet: str) -> list[str]:
    """The note block the scaffolder writes above a sheet's headers.

    One line per column, so the guidance sits beside the work rather than in a README the filler
    has already scrolled past.
    """
    lines: list[str] = []
    for spec in specs_for(sheet):
        parts = [f"{spec.column}: {spec.guidance}"]
        if spec.legal_values:
            parts.append(f"One of: {', '.join(spec.legal_values)}.")
        if spec.blank_means:
            parts.append(f"Blank = {spec.blank_means}.")
        lines.append(" ".join(parts))
    return lines
