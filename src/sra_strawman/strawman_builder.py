"""SRA strawman xlsx orchestrator (Brief Section 4 + Section 6).

Reads the earlier reference register / SP12 / P6, runs the register-to-schedule mapper, duration
parser, CP classifier, and day-rate memo, then writes a formula-driven
workbook to the caller's `output_path` with six
sheets:

  Summary                 - two comparators, RBS L1 / Mode breakdowns
  Mapping (tblSRAMapping) - 34 rows, columns A-AI per §4.2
  CP_Classifier_QA        - 1959 activities sorted by Mode
  DayRate_Reconciliation  - derivation + dual-coded gap table
  Workshop_Questions      - 20-30 questions
  Run_Config_Preview      - Option B config snapshot

Returns a summary dict of Python-computed comparator values so the Gate 3
diagnostic can print them (we do not round-trip formula results through
openpyxl because data_only=True is always False for freshly-written files).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.filters import AutoFilter
from openpyxl.worksheet.table import (
    Table, TableColumn, TableFormula, TableStyleInfo,
)

from src.sra_strawman.cp_classifier import (
    MODE_HYBRID,
    MODE_PARALLEL,
    MODE_SERIES,
    classify_schedule,
    is_commercially_binding,
    summarise_counts,
)
from src.sra_strawman.day_rate_memo import (
    build_reconciliation_rows,
    derive_day_rate_context,
    dual_coded_risk_ids,
)
from src.sra_strawman.defaults import (
    BROAD_LINKAGE_CONFIDENCE_DOWNGRADE_THRESHOLD,
    HYBRID_FLOAT_THRESHOLD_DAYS,
    OPTION_B_PROGRAMME_SEASONS,
    PROGRAMME_WORKING_DAYS,
    RECONCILIATION_B_DIVISOR,
)
from src.sra_strawman.duration_parser import derive_for_risk
from src.sra_strawman.p6_reader import read_p6_schedule
from src.sra_strawman.risk_activity_mapper import map_all_risks
from src.sra_strawman.sra_register_reader import read_risks
from src.sra_strawman.workshop_questions import build_questions

# ---------------------------------------------------------------------------
# Column layout for the Mapping sheet (Brief §4.2). 1-indexed for openpyxl.
# ---------------------------------------------------------------------------

MAPPING_COLUMNS: list[tuple[str, str]] = [
    # Column names avoid special characters ($, -, /, parens) because those
    # break Excel's parser when the names are referenced from calculatedColumn
    # formulas inside the Table XML (Excel strips the whole Table on open).
    # Units noted in column-width comments / memo text instead.
    # (header, kind)  kind in {"value", "formula"}
    ("Risk ID", "value"),                           # A
    ("Risk Title", "value"),                        # B
    ("Risk Owner", "value"),                        # C
    ("RBS L1", "value"),                            # D
    ("Time Impact", "value"),                       # E
    ("Dual coded flag", "value"),                   # F
    ("Proposed Activity IDs", "value"),             # G
    ("Activity count linked", "value"),             # H
    ("Min Total Float days", "value"),              # I
    ("Mapping confidence", "value"),                # J
    ("Mode", "value"),                              # K
    ("Series source", "value"),                     # L
    ("Schedule CG", "value"),                       # M
    ("Probability", "value"),                       # N
    ("Opt duration days", "value"),                 # O
    ("ML duration days", "value"),                  # P
    ("Pess duration days", "value"),                # Q
    ("Day rate per day", "value"),                  # R
    ("Reconciliation treatment", "value"),          # S
    ("Duration source tag", "value"),               # T
    ("Reconciliation divisor", "formula"),          # U
    ("Opt adjusted", "formula"),                    # V
    ("ML adjusted", "formula"),                     # W
    ("Pess adjusted", "formula"),                   # X
    ("EV days Simple", "formula"),                  # Y
    ("EV days PERT", "formula"),                    # Z
    ("EMV days Simple", "formula"),                 # AA
    ("EMV days PERT", "formula"),                   # AB
    ("EMV cost of delay Simple", "formula"),        # AC
    ("EMV cost of delay PERT", "formula"),          # AD
    ("Mode multiplier", "formula"),                 # AE
    ("Finish delay days PERT", "formula"),          # AF
    ("Finish delay dollars PERT", "formula"),       # AG
    ("Review comment", "value"),                    # AH
    ("Notes", "value"),                             # AI
]

MAPPING_TABLE_NAME = "tblSRAMapping"

# Derived helpers ---
HEADER_INDEX = {h: i + 1 for i, (h, _) in enumerate(MAPPING_COLUMNS)}


def _col(header: str) -> str:
    """Return Excel column letter for a Mapping table header."""
    return get_column_letter(HEADER_INDEX[header])


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF")
FORMULA_FILL = PatternFill("solid", fgColor="F2F2F2")
STATIC_FILL = PatternFill("solid", fgColor="FFFFFF")
EDITABLE_FILL = PatternFill("solid", fgColor="FFF2CC")  # pale yellow for user-editable
SECTION_FONT = Font(bold=True, size=12)
NOTE_FONT = Font(italic=True, color="595959")

THIN_BORDER = Border(
    left=Side(style="thin", color="BFBFBF"),
    right=Side(style="thin", color="BFBFBF"),
    top=Side(style="thin", color="BFBFBF"),
    bottom=Side(style="thin", color="BFBFBF"),
)

# Column letter ranges by kind (for conditional styling fills).
_VALUE_STATIC_HEADERS = {h for h, k in MAPPING_COLUMNS[:10] if k == "value"}
_CLASSIFIER_HEADERS = {"Mode", "Series source", "Schedule CG"}
_EDITABLE_HEADERS = {
    "Probability", "Opt duration days", "ML duration days",
    "Pess duration days", "Day rate per day", "Reconciliation treatment",
    "Duration source tag",
}
_FORMULA_HEADERS = {h for h, k in MAPPING_COLUMNS if k == "formula"}


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MappingRowContext:
    risks: list[dict]
    mappings: list[Any]
    duration_extracts: list[Any]
    dual_coded_set: set[str]
    default_day_rate: float


def _proposed_activity_description(mapping_obj: Any) -> str:
    """Format the Activity ID linkage for column G."""
    prefixes = mapping_obj.activity_id_prefixes or ()
    patterns = mapping_obj.activity_id_patterns or ()
    parts: list[str] = []
    if prefixes:
        parts.append("prefixes: " + ", ".join(prefixes))
    if patterns:
        parts.append("patterns: " + "+".join(patterns))
    if not parts:
        return mapping_obj.linkage_label or ""
    return f"{mapping_obj.linkage_label} [{'; '.join(parts)}]"


def _time_impact_value(raw: object) -> str:
    """Normalise the earlier reference register's Time Impact cell -> 'Yes'/'No' (default 'No')."""
    if raw is None:
        return "No"
    s = str(raw).strip().lower()
    if s in ("yes", "y", "true", "1"):
        return "Yes"
    return "No"


def _build_mapping_row_values(
    risk: dict,
    mapping: Any,
    dur: Any,
    dual_coded_set: set[str],
    default_day_rate: float,
) -> list[Any]:
    """Return the 35 cell values for one row (formulas included as strings)."""
    rid = str(risk.get("risk_id") or "").strip()

    # Static identification (A-J).
    risk_title = (risk.get("description") or "")
    if isinstance(risk_title, str):
        risk_title = risk_title.replace("\n", " ").strip()[:80]
    rbs_l1 = risk.get("rbs_l1")
    time_impact = _time_impact_value(risk.get("time_impact_flag"))
    dual_flag = rid in dual_coded_set

    # Classifier output (K-M).
    mode = mapping.mode
    series_source = mapping.series_source
    schedule_cg = mapping.schedule_cg or rbs_l1

    # Editable inputs (N-T).
    probability = risk.get("probability")
    try:
        probability_val = float(probability) if probability is not None else 0.0
    except (TypeError, ValueError):
        probability_val = 0.0
    opt = float(dur.opt_days or 0.0)
    ml = float(dur.ml_days or 0.0)
    pess = float(dur.pess_days or 0.0)
    day_rate = float(default_day_rate)
    # Reconciliation treatment: read from the risk's Recurrence Type if present.
    # BINOMIAL -> B, otherwise A (Amendment 2 / Steve's 2026-04-21 resolution).
    recur = (risk.get("recurrence_type") or "").strip().upper()
    reconciliation = "B" if recur == "BINOMIAL" else "A"
    duration_tag = dur.tag

    # Formulas (U-AG) reference structured table columns via [@[Column Name]].
    f = _formula_factory()
    row_formulas = f.row_formulas()

    # Annotation (AH-AI). Use None (not '') for blanks - openpyxl writes
    # an empty inlineStr element for '' which some Excel builds reject.
    review_comment = None
    notes = dur.notes or None

    return [
        rid,                                          # A
        risk_title or None,                           # B
        risk.get("risk_owner") or None,               # C
        rbs_l1 or None,                               # D
        time_impact,                                  # E
        "Yes" if dual_flag else "No",                 # F
        _proposed_activity_description(mapping) or None,  # G
        int(mapping.linked_activity_count or 0),      # H
        mapping.min_total_float_days if mapping.min_total_float_days is not None else None,  # I
        mapping.mapping_confidence,                   # J
        mode,                                         # K
        series_source,                                # L
        schedule_cg or None,                          # M
        probability_val,                              # N
        opt,                                          # O
        ml,                                           # P
        pess,                                         # Q
        day_rate,                                     # R
        reconciliation,                               # S
        duration_tag,                                 # T
        row_formulas["Reconciliation divisor"],       # U
        row_formulas["Opt adjusted"],                 # V
        row_formulas["ML adjusted"],                  # W
        row_formulas["Pess adjusted"],                # X
        row_formulas["EV days Simple"],               # Y
        row_formulas["EV days PERT"],                 # Z
        row_formulas["EMV days Simple"],              # AA
        row_formulas["EMV days PERT"],                # AB
        row_formulas["EMV cost of delay Simple"],     # AC
        row_formulas["EMV cost of delay PERT"],       # AD
        row_formulas["Mode multiplier"],              # AE
        row_formulas["Finish delay days PERT"],       # AF
        row_formulas["Finish delay dollars PERT"],    # AG
        review_comment,                               # AH
        notes,                                        # AI
    ]


class _formula_factory:
    """Build the §4.2 formulas using structured references.

    Structured references like `[@[Column Name]]` are valid for any column
    name (no need to escape spaces or special characters).
    """

    def row_formulas(self) -> dict[str, str]:
        return {
            "Reconciliation divisor":
                f'=IF([@[Reconciliation treatment]]="B", {RECONCILIATION_B_DIVISOR}, 1)',
            "Opt adjusted":
                '=[@[Opt duration days]] / [@[Reconciliation divisor]]',
            "ML adjusted":
                '=[@[ML duration days]] / [@[Reconciliation divisor]]',
            "Pess adjusted":
                '=[@[Pess duration days]] / [@[Reconciliation divisor]]',
            "EV days Simple":
                '=([@[Opt adjusted]] + [@[ML adjusted]] + [@[Pess adjusted]]) / 3',
            "EV days PERT":
                '=([@[Opt adjusted]] + 4*[@[ML adjusted]] + [@[Pess adjusted]]) / 6',
            "EMV days Simple":
                '=[@[Probability]] * [@[EV days Simple]]',
            "EMV days PERT":
                '=[@[Probability]] * [@[EV days PERT]]',
            "EMV cost of delay Simple":
                '=[@[EMV days Simple]] * [@[Day rate per day]]',
            "EMV cost of delay PERT":
                '=[@[EMV days PERT]] * [@[Day rate per day]]',
            "Mode multiplier": (
                '=IF([@[Mode]]="Series", 1, '
                'IF([@[Mode]]="Hybrid", '
                'MAX(0, [@[EV days PERT]] - [@[Min Total Float days]]) / '
                'MAX(1, [@[EV days PERT]]), 0))'
            ),
            "Finish delay days PERT":
                '=[@[EMV days PERT]] * [@[Mode multiplier]]',
            "Finish delay dollars PERT":
                '=[@[Finish delay days PERT]] * [@[Day rate per day]]',
        }


# ---------------------------------------------------------------------------
# Python-side expected values (for diagnostic, not read-back from xlsx)
# ---------------------------------------------------------------------------

def _compute_expected_row_outputs(
    risk: dict,
    mapping: Any,
    dur: Any,
    day_rate: float,
    reconciliation: str,
) -> dict[str, float]:
    """Compute the same numbers the xlsx formulas will produce, in Python."""
    divisor = RECONCILIATION_B_DIVISOR if reconciliation == "B" else 1
    opt = float(dur.opt_days or 0.0) / divisor
    ml = float(dur.ml_days or 0.0) / divisor
    pess = float(dur.pess_days or 0.0) / divisor
    ev_simple = (opt + ml + pess) / 3.0
    ev_pert = (opt + 4 * ml + pess) / 6.0
    prob_raw = risk.get("probability")
    try:
        p = float(prob_raw) if prob_raw is not None else 0.0
    except (TypeError, ValueError):
        p = 0.0
    emv_simple = p * ev_simple
    emv_pert = p * ev_pert
    emv_simple_dollars = emv_simple * day_rate
    emv_pert_dollars = emv_pert * day_rate
    mode = mapping.mode
    min_tf = mapping.min_total_float_days if mapping.min_total_float_days is not None else 0.0
    if mode == MODE_SERIES:
        mode_mult = 1.0
    elif mode == MODE_HYBRID:
        denom = max(1.0, ev_pert)
        mode_mult = max(0.0, ev_pert - float(min_tf)) / denom
    else:
        mode_mult = 0.0
    contribution_days = emv_pert * mode_mult
    contribution_dollars = contribution_days * day_rate
    return {
        "ev_simple": ev_simple,
        "ev_pert": ev_pert,
        "emv_simple_days": emv_simple,
        "emv_pert_days": emv_pert,
        "emv_simple_dollars": emv_simple_dollars,
        "emv_pert_dollars": emv_pert_dollars,
        "mode_mult": mode_mult,
        "contribution_days": contribution_days,
        "contribution_dollars": contribution_dollars,
    }


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------

def _write_mapping_sheet(
    wb: Workbook,
    risks: list[dict],
    mappings: list[Any],
    duration_extracts: list[Any],
    dual_coded_set: set[str],
    default_day_rate: float,
) -> list[list[Any]]:
    """Write the Mapping sheet with tblSRAMapping. Returns row values written."""
    ws = wb.create_sheet("Mapping")
    # Header row.
    for col_idx, (header, _) in enumerate(MAPPING_COLUMNS, start=1):
        c = ws.cell(row=1, column=col_idx, value=header)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        c.border = THIN_BORDER

    # Data rows.
    row_values: list[list[Any]] = []
    for i, (risk, mapping, dur) in enumerate(
        zip(risks, mappings, duration_extracts), start=2
    ):
        vals = _build_mapping_row_values(
            risk, mapping, dur, dual_coded_set, default_day_rate
        )
        row_values.append(vals)
        for col_idx, v in enumerate(vals, start=1):
            ws.cell(row=i, column=col_idx, value=v)

    # Apply cell fills by column type for visual cue (editable vs formula vs static).
    for (header, kind), col_idx in zip(MAPPING_COLUMNS, range(1, len(MAPPING_COLUMNS) + 1)):
        if header in _EDITABLE_HEADERS:
            fill = EDITABLE_FILL
        elif kind == "formula":
            fill = FORMULA_FILL
        else:
            fill = STATIC_FILL
        for r in range(2, 2 + len(row_values)):
            cell = ws.cell(row=r, column=col_idx)
            cell.fill = fill
            cell.border = THIN_BORDER

    # Column widths.
    widths = {
        "Risk ID": 10, "Risk Title": 42, "Risk Owner": 18, "RBS L1": 28,
        "Time Impact": 10, "Dual coded flag": 10,
        "Proposed Activity IDs": 50, "Activity count linked": 10,
        "Min Total Float days": 10, "Mapping confidence": 12,
        "Mode": 10, "Series source": 14, "Schedule CG": 28,
        "Probability": 10, "Opt duration days": 10, "ML duration days": 10,
        "Pess duration days": 10, "Day rate per day": 14,
        "Reconciliation treatment": 14, "Duration source tag": 20,
        "Reconciliation divisor": 10, "Opt adjusted": 10, "ML adjusted": 10,
        "Pess adjusted": 10, "EV days Simple": 10, "EV days PERT": 10,
        "EMV days Simple": 10, "EMV days PERT": 10,
        "EMV cost of delay Simple": 14, "EMV cost of delay PERT": 14,
        "Mode multiplier": 10,
        "Finish delay days PERT": 16,
        "Finish delay dollars PERT": 16,
        "Review comment": 30, "Notes": 60,
    }
    for header, col_idx in HEADER_INDEX.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = widths.get(header, 14)

    # Freeze panes at B2 so Risk ID stays visible.
    ws.freeze_panes = "B2"

    # Create Excel Table over the data range. Explicitly build tableColumns
    # with calculatedColumnFormula for every formula-column - without this,
    # Excel strips the <f> tags from each cell on open with the warning
    # "Removed Records: Formula from /xl/worksheets/sheetN.xml" because the
    # cells have structured references but the Table doesn't declare them
    # as calculated columns.
    last_col = get_column_letter(len(MAPPING_COLUMNS))
    last_row = 1 + len(row_values)
    table_ref = f"A1:{last_col}{last_row}"
    row_formulas = _formula_factory().row_formulas()
    table_columns = []
    for i, (header, _) in enumerate(MAPPING_COLUMNS, start=1):
        tc = TableColumn(id=i, name=header)
        f = row_formulas.get(header)
        if f:
            # OOXML expects calculatedColumnFormula WITHOUT the leading '='.
            tc.calculatedColumnFormula = TableFormula(
                attr_text=f[1:] if f.startswith("=") else f
            )
        table_columns.append(tc)
    tbl = Table(
        displayName=MAPPING_TABLE_NAME,
        ref=table_ref,
        tableColumns=table_columns,
        # When tableColumns is passed explicitly, openpyxl does NOT auto-create
        # the autoFilter - we must attach one manually or Excel rejects the
        # table ("Removed Records: Table from /xl/tables/tableN.xml").
        autoFilter=AutoFilter(ref=table_ref),
    )
    tbl.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showFirstColumn=False,
        showLastColumn=False, showRowStripes=True, showColumnStripes=False,
    )
    ws.add_table(tbl)

    # Data validations.
    _add_mapping_validations(ws, last_row)

    return row_values


def _add_mapping_validations(ws, last_row: int) -> None:
    """Add dropdowns for Mode / Reconciliation / Duration source tag / Confidence."""
    mode_col = _col("Mode")
    recon_col = _col("Reconciliation treatment")
    tag_col = _col("Duration source tag")
    conf_col = _col("Mapping confidence")

    validations = [
        (mode_col, '"Series,Hybrid,Parallel,[NEEDS_REVIEW]"'),
        (recon_col, '"A,B,C"'),
        (tag_col, '"CONSEQUENCE,DERIVED_LOW_CONFIDENCE,DUMMY,DERIVED"'),
        (conf_col, '"High,Medium,Low,[NEEDS_REVIEW]"'),
    ]
    for col_letter, formula in validations:
        dv = DataValidation(
            type="list", formula1=formula, allow_blank=True, showDropDown=False,
        )
        dv.add(f"{col_letter}2:{col_letter}{last_row}")
        ws.add_data_validation(dv)


def _write_summary_sheet(
    wb: Workbook,
    expected_totals: dict[str, float],
    classifier_counts: dict[str, int],
    rbs_l1_breakdown: dict[str, dict[str, float]],
    mode_breakdown: dict[str, dict[str, float]],
    n_rows: int,
    sp12_prelims: float,
    day_rate: float,
    dual_coded_count: int,
    assumptions: list[str],
) -> None:
    """Write the Summary sheet with formula-driven comparators and breakdowns."""
    ws = wb.create_sheet("Summary", 0)  # insert at position 0 (first sheet)

    def write(row: int, label: str, formula_or_value: Any = None,
              *, bold: bool = False, italic: bool = False,
              fmt: str | None = None) -> None:
        ws.cell(row=row, column=1, value=label)
        if bold:
            ws.cell(row=row, column=1).font = SECTION_FONT
        if italic:
            ws.cell(row=row, column=1).font = NOTE_FONT
        if formula_or_value is not None:
            c = ws.cell(row=row, column=2, value=formula_or_value)
            if fmt:
                c.number_format = fmt

    r = 1
    write(r, "SRA Strawman - Summary", bold=True); r += 1
    write(r, f"Mapping table: {MAPPING_TABLE_NAME} on sheet Mapping "
             f"({n_rows} Open risks)", italic=True); r += 2

    # --- Section 1: comparators ---
    write(r, "Comparator 1 - Upper-bound EMV schedule (naive sum)", bold=True); r += 1
    write(r, "  Total EMV days (Simple)",
          f"=SUMPRODUCT({MAPPING_TABLE_NAME}[EMV days Simple])",
          fmt="#,##0.0")
    r += 1
    write(r, "  Total EMV days (PERT)",
          f"=SUMPRODUCT({MAPPING_TABLE_NAME}[EMV days PERT])",
          fmt="#,##0.0")
    r += 1
    write(r, "  Total EMV $ cost-of-delay (PERT)",
          f"=SUMPRODUCT({MAPPING_TABLE_NAME}[EMV cost of delay PERT])",
          fmt='"$"#,##0')
    r += 2

    write(r, "Comparator 2 - Finish-date slippage (Mode-weighted)", bold=True); r += 1
    write(r, "  Aggregate finish-date slippage days (PERT)",
          f"=SUMPRODUCT({MAPPING_TABLE_NAME}[Finish delay days PERT])",
          fmt="#,##0.0")
    r += 1
    write(r, "  Aggregate finish-date slippage $ (PERT)",
          f"=SUMPRODUCT({MAPPING_TABLE_NAME}[Finish delay dollars PERT])",
          fmt='"$"#,##0')
    r += 2

    write(r, "Explanation", bold=True); r += 1
    notes = [
        "Comparator 1 sums every risk's expected schedule impact ignoring",
        "critical path - the upper bound on aggregate delay. Comparator 2",
        "is Mode-weighted and represents expected contribution to whole-",
        "project finish-date slippage. Option B's MC Mean days should",
        "reconcile against Comparator 2 within 10% for the engine to be",
        "considered calibrated.",
    ]
    for line in notes:
        write(r, "  " + line, italic=True); r += 1
    r += 1

    # --- Section 2: RBS L1 breakdown ---
    write(r, "Breakdown by RBS L1 Schedule Correlation Group", bold=True); r += 1
    headers = ["RBS L1", "Risk count", "EMV days PERT",
               "Finish-delay days", "Finish-delay $"]
    for ci, h in enumerate(headers, start=1):
        c = ws.cell(row=r, column=ci, value=h)
        c.font = Font(bold=True)
    r += 1
    for rbs_l1 in sorted(rbs_l1_breakdown.keys()):
        stats = rbs_l1_breakdown[rbs_l1]
        ws.cell(row=r, column=1, value=rbs_l1)
        # Formulas on the live table for count / sums, filtered by RBS L1.
        # Using COUNTIFS / SUMIFS against structured refs for live behavior.
        col_rbs = f"{MAPPING_TABLE_NAME}[RBS L1]"
        col_emv_pert = f"{MAPPING_TABLE_NAME}[EMV days PERT]"
        col_fin_days = f"{MAPPING_TABLE_NAME}[Finish delay days PERT]"
        col_fin_dol = f"{MAPPING_TABLE_NAME}[Finish delay dollars PERT]"
        ws.cell(row=r, column=2,
                value=f'=COUNTIFS({col_rbs}, A{r})').number_format = "0"
        ws.cell(row=r, column=3,
                value=f'=SUMIFS({col_emv_pert}, {col_rbs}, A{r})').number_format = "#,##0.0"
        ws.cell(row=r, column=4,
                value=f'=SUMIFS({col_fin_days}, {col_rbs}, A{r})').number_format = "#,##0.0"
        ws.cell(row=r, column=5,
                value=f'=SUMIFS({col_fin_dol}, {col_rbs}, A{r})').number_format = '"$"#,##0'
        r += 1
    r += 1

    # --- Section 3: Mode breakdown ---
    write(r, "Breakdown by Mode", bold=True); r += 1
    headers = ["Mode", "Risk count", "EMV days PERT",
               "Finish-delay days", "% of Comparator 2"]
    for ci, h in enumerate(headers, start=1):
        c = ws.cell(row=r, column=ci, value=h)
        c.font = Font(bold=True)
    r += 1
    for mode in (MODE_SERIES, MODE_HYBRID, MODE_PARALLEL, "[NEEDS_REVIEW]"):
        ws.cell(row=r, column=1, value=mode)
        col_mode = f"{MAPPING_TABLE_NAME}[Mode]"
        col_emv_pert = f"{MAPPING_TABLE_NAME}[EMV days PERT]"
        col_fin_days = f"{MAPPING_TABLE_NAME}[Finish delay days PERT]"
        ws.cell(row=r, column=2,
                value=f'=COUNTIFS({col_mode}, A{r})').number_format = "0"
        ws.cell(row=r, column=3,
                value=f'=SUMIFS({col_emv_pert}, {col_mode}, A{r})').number_format = "#,##0.0"
        ws.cell(row=r, column=4,
                value=f'=SUMIFS({col_fin_days}, {col_mode}, A{r})').number_format = "#,##0.0"
        total_ref = f"SUMPRODUCT({col_fin_days})"
        ws.cell(row=r, column=5,
                value=f'=IFERROR(SUMIFS({col_fin_days}, {col_mode}, A{r}) / {total_ref}, 0)'
                ).number_format = "0.0%"
        r += 1
    r += 1

    # --- Section 4: Classifier QA (static values) ---
    write(r, "CP Classifier QA (Option Z hybrid, across whole P6 export)",
          bold=True); r += 1
    rows_static = [
        ("Total P6 activities (excl. WBS summaries)",
         classifier_counts.get("total", 0)),
        ("P6 Critical=Yes", classifier_counts.get("p6_critical_yes", 0)),
        ("Zero-float activities", classifier_counts.get("zero_float", 0)),
        (f"Mode = Series (Option Z) - target {200}-{300}",
         classifier_counts.get(MODE_SERIES, 0)),
        ("Mode = Hybrid (Option Z)", classifier_counts.get(MODE_HYBRID, 0)),
        ("Mode = Parallel (Option Z)", classifier_counts.get(MODE_PARALLEL, 0)),
        ("CSE-KML- milestones (commercially binding)",
         classifier_counts.get("cse_kml_count", 0)),
    ]
    for lbl, val in rows_static:
        ws.cell(row=r, column=1, value=lbl)
        ws.cell(row=r, column=2, value=val)
        r += 1
    r += 1

    # --- Section 5: Derivation references ---
    write(r, "Day-rate derivation", bold=True); r += 1
    write(r, "  SP12 Preliminaries total",
          sp12_prelims, fmt='"$"#,##0'); r += 1
    write(r, "  Programme working days",
          PROGRAMME_WORKING_DAYS, fmt="0"); r += 1
    write(r, "  Derived site-running rate ($/working day)",
          day_rate, fmt='"$"#,##0'); r += 1
    write(r, "  Dual-coded risks detected (see DayRate_Reconciliation)",
          dual_coded_count, fmt="0"); r += 2

    # --- Section 6: Assumptions & Open Questions ---
    write(r, "Assumptions & Open Questions (from Gate 2 pause, 2026-04-22)",
          bold=True); r += 1
    for line in assumptions:
        write(r, "  - " + line, italic=True); r += 1

    # Styling: first column wide, second column narrow-ish.
    ws.column_dimensions["A"].width = 60
    ws.column_dimensions["B"].width = 22
    for col in ("C", "D", "E"):
        ws.column_dimensions[col].width = 18


def _write_classifier_qa_sheet(wb: Workbook, classified: list[dict]) -> None:
    """Write the CP_Classifier_QA sheet (values only, sorted by Mode)."""
    ws = wb.create_sheet("CP_Classifier_QA")
    headers = [
        "Activity ID", "Activity Name", "Total Float (days)",
        "Start constrained", "Finish constrained", "P6 Critical flag",
        "Commercially binding keyword", "Mode (Option Z)", "Series source",
    ]
    for ci, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=ci, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = Alignment(wrap_text=True)

    # Sort Series first, then Hybrid, then Parallel.
    order = {MODE_SERIES: 0, MODE_HYBRID: 1, MODE_PARALLEL: 2}
    srt = sorted(classified, key=lambda a: (order.get(a.get("mode"), 9),
                                            a.get("activity_id") or ""))
    for i, act in enumerate(srt, start=2):
        binding = is_commercially_binding(
            act.get("activity_id"), act.get("activity_name")
        )
        ws.cell(row=i, column=1, value=act.get("activity_id") or None)
        ws.cell(row=i, column=2, value=act.get("activity_name") or None)
        ws.cell(row=i, column=3, value=act.get("total_float_days"))
        ws.cell(row=i, column=4,
                value="Yes" if act.get("start_is_constrained") else "No")
        ws.cell(row=i, column=5,
                value="Yes" if act.get("finish_is_constrained") else "No")
        ws.cell(row=i, column=6,
                value="Yes" if act.get("p6_critical_flag") else "No")
        ws.cell(row=i, column=7, value="Yes" if binding else "No")
        ws.cell(row=i, column=8, value=act.get("mode"))
        ws.cell(row=i, column=9, value=act.get("series_source"))

    widths = [18, 60, 12, 10, 10, 10, 14, 14, 16]
    for ci, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = "A2"


def _write_day_rate_sheet(
    wb: Workbook,
    ctx,
    reconciliation_rows: list[dict],
) -> None:
    """Write the DayRate_Reconciliation sheet."""
    ws = wb.create_sheet("DayRate_Reconciliation")

    r = 1
    ws.cell(row=r, column=1, value="Day-rate derivation").font = SECTION_FONT
    r += 1
    ws.cell(row=r, column=1, value="Preliminaries total (from SP12)")
    c = ws.cell(row=r, column=2, value=ctx.preliminaries_total)
    c.number_format = '"$"#,##0'
    ws.cell(row=r, column=3, value=f"Source: {ctx.source_cell}").font = NOTE_FONT
    r += 1
    ws.cell(row=r, column=1, value="Programme working days (from P6)")
    ws.cell(row=r, column=2, value=ctx.programme_working_days)
    r += 1
    ws.cell(row=r, column=1, value="Site-running rate ($/working day)")
    c = ws.cell(row=r, column=2, value="=B2/B3")
    c.number_format = '"$"#,##0'
    r += 1
    ws.cell(row=r, column=1, value="Site-running rate ($/calendar day)")
    c = ws.cell(row=r, column=2, value="=B2/(B3*7/5)")
    c.number_format = '"$"#,##0'
    r += 2

    ws.cell(row=r, column=1,
            value="Dual-coded risks - narrative rate vs derived site rate").font = SECTION_FONT
    r += 1
    headers = [
        "Risk ID", "BOE excerpt", "Narrative rate (raw)",
        "Narrative rate ($/wd)", "Derived rate ($/wd)",
        "Gap ($/wd)", "Hypothesis",
    ]
    for ci, h in enumerate(headers, start=1):
        c = ws.cell(row=r, column=ci, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    r += 1
    for row in reconciliation_rows:
        ws.cell(row=r, column=1, value=row["risk_id"])
        ws.cell(row=r, column=2, value=row["boe_excerpt"])
        ws.cell(row=r, column=3, value=row["narrative_rate_raw"] or None)
        c = ws.cell(row=r, column=4, value=row["narrative_rate_per_wd"])
        c.number_format = '"$"#,##0'
        c = ws.cell(row=r, column=5, value=row["derived_rate_per_wd"])
        c.number_format = '"$"#,##0'
        c = ws.cell(row=r, column=6, value=row["gap_per_wd"])
        c.number_format = '"$"#,##0;"$"-#,##0'
        ws.cell(row=r, column=7, value=row["hypothesis"])
        r += 1

    widths = [12, 60, 24, 14, 14, 14, 42]
    for ci, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w


def _write_workshop_sheet(wb: Workbook, questions: list[Any]) -> None:
    ws = wb.create_sheet("Workshop_Questions")
    headers = ["#", "Category", "Question", "Owner", "Answer type",
               "Impact if unresolved", "Priority"]
    for ci, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=ci, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    for i, q in enumerate(questions, start=2):
        ws.cell(row=i, column=1, value=q.number)
        ws.cell(row=i, column=2, value=q.category)
        ws.cell(row=i, column=3, value=q.question)
        ws.cell(row=i, column=4, value=q.owner)
        ws.cell(row=i, column=5, value=q.answer_type)
        ws.cell(row=i, column=6, value=q.impact_if_unresolved)
        ws.cell(row=i, column=7, value=q.priority)
    widths = [4, 16, 70, 14, 14, 60, 14]
    for ci, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = "A2"


def _write_run_config_sheet(wb: Workbook, day_rate: float) -> None:
    ws = wb.create_sheet("Run_Config_Preview")
    pairs: list[tuple[str, Any]] = [
        ("programme_seasons", OPTION_B_PROGRAMME_SEASONS),
        ("cascading", "OFF"),
        ("chains", "OFF"),
        ("correlation_source", "register CG codes (CG01-CG13)"),
        ("iterations", 100_000),
        ("P-level_reporting", 80),
        ("Reconciliation_default", "B (applies where Recurrence Type = BINOMIAL)"),
        ("CP_rule", "Option_Z_Hybrid"),
        ("CP_hybrid_float_threshold_days", HYBRID_FLOAT_THRESHOLD_DAYS),
        ("Day_rate_default ($/wd)", round(day_rate)),
        ("LD_layer_status", "OFF (deferred - pending BOP Contract extract)"),
        ("Broad-linkage confidence downgrade threshold (activities)",
         BROAD_LINKAGE_CONFIDENCE_DOWNGRADE_THRESHOLD),
    ]
    for ci, h in enumerate(("Parameter", "Value"), start=1):
        c = ws.cell(row=1, column=ci, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    for i, (k, v) in enumerate(pairs, start=2):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v)
    ws.column_dimensions["A"].width = 55
    ws.column_dimensions["B"].width = 45


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

@dataclass
class BuildResult:
    output_path: Path
    n_risks: int
    n_activities: int
    classifier_counts: dict[str, int]
    expected_totals: dict[str, float]
    dual_coded_ids: list[str]
    rbs_l1_breakdown: dict[str, dict[str, float]]
    mode_breakdown: dict[str, dict[str, float]]
    day_rate_per_wd: float
    sp12_prelims: float


def build_strawman(
    v7_path: str | Path,
    p6_path: str | Path,
    sp12_path: str | Path,
    output_path: str | Path,
) -> BuildResult:
    """Run the full orchestration and produce the strawman xlsx.

    Inputs are read; no input file is modified. Output directory is
    created if missing.
    """
    risks = read_risks(v7_path, open_only=True)
    all_activities = read_p6_schedule(p6_path)
    activities_only = [a for a in all_activities if not a.get("is_wbs_summary")]
    classified = classify_schedule(all_activities)  # already filters summaries

    mappings = map_all_risks(risks, all_activities)
    duration_extracts = [derive_for_risk(r) for r in risks]
    ctx = derive_day_rate_context(sp12_path)
    dual_ids_list = dual_coded_risk_ids(risks)
    dual_coded_set = set(dual_ids_list)
    reconciliation_rows = build_reconciliation_rows(risks, ctx)
    questions = build_questions()

    # Python-side expected totals (for Gate 3 diagnostic and Summary §4).
    expected_emv_simple_days = 0.0
    expected_emv_pert_days = 0.0
    expected_emv_pert_dollars = 0.0
    expected_finish_days = 0.0
    expected_finish_dollars = 0.0
    rbs_l1_breakdown: dict[str, dict[str, float]] = {}
    mode_breakdown: dict[str, dict[str, float]] = {
        MODE_SERIES: {"count": 0, "emv_pert_days": 0.0, "finish_days": 0.0},
        MODE_HYBRID: {"count": 0, "emv_pert_days": 0.0, "finish_days": 0.0},
        MODE_PARALLEL: {"count": 0, "emv_pert_days": 0.0, "finish_days": 0.0},
        "[NEEDS_REVIEW]": {"count": 0, "emv_pert_days": 0.0, "finish_days": 0.0},
    }
    for risk, mapping, dur in zip(risks, mappings, duration_extracts):
        recur = (risk.get("recurrence_type") or "").strip().upper()
        reconciliation = "B" if recur == "BINOMIAL" else "A"
        out = _compute_expected_row_outputs(
            risk, mapping, dur, ctx.rate_per_working_day, reconciliation
        )
        expected_emv_simple_days += out["emv_simple_days"]
        expected_emv_pert_days += out["emv_pert_days"]
        expected_emv_pert_dollars += out["emv_pert_dollars"]
        expected_finish_days += out["contribution_days"]
        expected_finish_dollars += out["contribution_dollars"]

        rbs_l1 = (risk.get("rbs_l1") or "").strip() or "(blank)"
        b = rbs_l1_breakdown.setdefault(
            rbs_l1, {"count": 0, "emv_pert_days": 0.0,
                     "finish_days": 0.0, "finish_dollars": 0.0},
        )
        b["count"] += 1
        b["emv_pert_days"] += out["emv_pert_days"]
        b["finish_days"] += out["contribution_days"]
        b["finish_dollars"] += out["contribution_dollars"]

        mode_key = mapping.mode if mapping.mode in mode_breakdown else "[NEEDS_REVIEW]"
        m = mode_breakdown[mode_key]
        m["count"] += 1
        m["emv_pert_days"] += out["emv_pert_days"]
        m["finish_days"] += out["contribution_days"]

    expected_totals = {
        "comparator_1_emv_simple_days": expected_emv_simple_days,
        "comparator_1_emv_pert_days": expected_emv_pert_days,
        "comparator_1_emv_pert_dollars": expected_emv_pert_dollars,
        "comparator_2_finish_days": expected_finish_days,
        "comparator_2_finish_dollars": expected_finish_dollars,
    }

    # Classifier counts.
    counts = summarise_counts(classified)
    counts["p6_critical_yes"] = sum(
        1 for a in activities_only if a.get("p6_critical_flag")
    )
    counts["zero_float"] = sum(
        1 for a in activities_only if a.get("total_float_days") == 0
    )
    counts["cse_kml_count"] = sum(
        1 for a in activities_only
        if (a.get("activity_id") or "").startswith("CSE-KML-")
    )

    # Assumptions block (Steve's Gate 2 direction).
    assumptions = [
        'Mode aggregation = most-conservative (any-Series-in-linkage -> Series).',
        f'Mapping confidence auto-downgraded to "Low" where linked activity '
        f'count > {BROAD_LINKAGE_CONFIDENCE_DOWNGRADE_THRESHOLD}.',
        'Reconciliation treatment default = A for all rows (the earlier reference register has zero',
        'BINOMIAL risks under seasons=1; when seasons=N-years, BINOMIAL rows',
        'flip to B automatically).',
        'Day-rate column default = derived site-running rate; editable per row.',
        'All duration inputs are DUMMY / CONSEQUENCE / DERIVED_LOW_CONFIDENCE -',
        'no contingency number should be derived from this strawman.',
    ]

    # --- Write xlsx ---
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    # Drop the default sheet - we create Summary as the first inserted sheet.
    default = wb.active
    wb.remove(default)

    # Order: Summary first, then Mapping, then the rest.
    _write_mapping_sheet(
        wb, risks, mappings, duration_extracts, dual_coded_set,
        ctx.rate_per_working_day,
    )
    _write_summary_sheet(
        wb, expected_totals, counts, rbs_l1_breakdown, mode_breakdown,
        n_rows=len(risks),
        sp12_prelims=ctx.preliminaries_total,
        day_rate=ctx.rate_per_working_day,
        dual_coded_count=len(dual_ids_list),
        assumptions=assumptions,
    )
    _write_classifier_qa_sheet(wb, classified)
    _write_day_rate_sheet(wb, ctx, reconciliation_rows)
    _write_workshop_sheet(wb, questions)
    _write_run_config_sheet(wb, ctx.rate_per_working_day)

    # Re-order so Summary is first.
    order = ["Summary", "Mapping", "CP_Classifier_QA",
             "DayRate_Reconciliation", "Workshop_Questions", "Run_Config_Preview"]
    wb._sheets = [wb[name] for name in order]

    wb.save(out)

    return BuildResult(
        output_path=out,
        n_risks=len(risks),
        n_activities=len(activities_only),
        classifier_counts=counts,
        expected_totals=expected_totals,
        dual_coded_ids=dual_ids_list,
        rbs_l1_breakdown=rbs_l1_breakdown,
        mode_breakdown=mode_breakdown,
        day_rate_per_wd=ctx.rate_per_working_day,
        sp12_prelims=ctx.preliminaries_total,
    )
