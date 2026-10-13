"""REG03 S1 - register template scaffolder (the empty, contract-correct input document).

Single home for the register CONTRACT STRUCTURE that BOTH the empty per-project
template AND the CI synthetic-wind fixture share, so the two cannot silently drift
(design brief REG03 section 5). It emits every tab, the ``Grid_*``/``Set_*``/``Out_*``
named-range contract, the three cell-type styling (D2), static dropdowns, the
methodology defaults grid (D1), the P6-ready schedule + activity-binding columns
(inert), a TOC/instructions tab (with the cell-type legend) and a reference tab
carrying the xlwings code + numpy/scipy requirements as text - EMPTY of project data.

The real project register is scaffolded ONCE into the USER's project folder and is
then the human's standalone document; the scaffolder never runs against a live
register again (design brief section 1). The CI fixture builder
(``scripts/build_synthetic_wind_fixture.py``) imports the structure builders here and
adds a synthetic data fill, so the fixture is provably "scaffold structure + fill".

Bit-identity rule (REG03 S1 gate): the shared structure builders reproduce the
pre-REG03 fixture's read-relevant cells and named ranges EXACTLY. The only additive
changes are value-neutral: the three-cell styling, a blank trailing activity-binding
column at col 31, static data-validation dropdowns, and the two new non-read tabs
(TOC, Reference). No engine number can move.

Run:  python tools/register_scaffold.py [OUTPUT.xlsx]  ->  an empty template.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import openpyxl  # noqa: E402
from src.final.product import MAKER  # noqa: E402
from openpyxl.chart import BarChart, Reference  # noqa: E402
from openpyxl.chart.data_source import AxDataSource, StrRef  # noqa: E402
from openpyxl.styles import (  # noqa: E402
    Alignment, Border, Font, PatternFill, Protection, Side,
)
from openpyxl.utils import get_column_letter  # noqa: E402
from openpyxl.formatting.rule import ColorScaleRule, FormulaRule  # noqa: E402
from openpyxl.utils import column_index_from_string  # noqa: E402
from openpyxl.worksheet.table import Table, TableStyleInfo  # noqa: E402
from openpyxl.comments import Comment  # noqa: E402
from openpyxl.workbook.defined_name import DefinedName  # noqa: E402
from openpyxl.workbook.protection import WorkbookProtection  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402

from src.register_field_spec import FILLABLE_SHEETS, note_lines, specs_for  # noqa: E402
from src.v5_register_reader import SEED_LABEL  # noqa: E402
from src.register_contract import (  # noqa: E402  single-source contract constants
    CONTRACT_VERSION, LAYER1_ENABLED_NAME, REQUIRED_NAMED_RANGES,
)

# ---------------------------------------------------------------------------
# House palette (REG-02; read from the RefProject register's theme1.xml). Kept in sync with
# scripts/build_synthetic_wind_fixture.py so the fixture themes identically.
# ---------------------------------------------------------------------------
HDR_FILL = "231EDC"       # accent1 - bold header fill (white text)
TAB_REGISTER = "0A7DFF"   # accent2 - register tab
TAB_ANALYSIS = "5AE6FF"   # accent3 - analysis tab
TAB_REFERENCE = "A5A5A5"  # accent5 grey - reference/TOC tabs
SECTION_TINT = {          # light band fills for the row-3 section labels
    "cost": "DCE9FF", "time": "E4F6FF", "derived": "EAF7EC", "binding": "FDEBD0",
}

# ---------------------------------------------------------------------------
# D2 - the three cell-type convention (Director 19/07/2026, established fresh):
#   input  (user-fill)      = blue font
#   calc   (Excel formula)  = black font (the default; no styling needed)
#   python (model write-back)= amber shaded fill + LOCKED + "written by the model"
# Legend lives on the TOC/instructions tab.
# ---------------------------------------------------------------------------
INPUT_FONT = Font(color="0000CC")                 # blue = user fills this cell
CALC_FONT = Font(color="000000")                  # black = live Excel formula
PYTHON_FILL = PatternFill("solid", fgColor="FCE4B6")  # amber = model write-back
LOCKED = Protection(locked=True)
UNLOCKED = Protection(locked=False)

#: REGUX-01 A-0.4 (Director, 07/09/2026: "layer-1 grids should be scaffolded, fix the TOC
#: contradiction"). The Layer-1 grids ship at their real shape and BLANK. The eight resource
#: columns are the set both real projects (wind, road) adopted unchanged; the WBS rows are
#: placeholders a project renames; one factor capacity bounds Factors, Allocation and the
#: correlation triangle alike, because the three are one shape. Blank, not zero: a zero grid
#: parses silently to a Layer 1 that is on and contributes nothing (characterised 08/09); a blank
#: one the parser refuses by name.
LAYER1_GENERIC_COLS = ("Staff", "Labour", "Plant", "Concrete", "Steel", "General",
                       "Subcontract", "Provisional")
_N_LAYER1_WBS_ROWS = 12
_N_LAYER1_FACTORS = 25
_L1_CORR_HEADER_ROW = 4   # Corr_Mode, PSD_Status, blank, then the Factor header
_NOT_READ_FILL = PatternFill("solid", fgColor="D9D9D9")   # correlation diagonal + upper triangle

# ===========================================================================
# Risk Register contract - the canonical column set (single source of truth)
# ===========================================================================
RISK_REGISTER_SHEET = "Risk Register"
SECTION_HEADER_ROW = 3
HEADER_ROW = 4
DATA_START_ROW = 5

#: Row-3 section band labels: (start_col, end_col, label, tint-key).
RISK_SECTION_BANDS = [
    (14, 19, "Contingent Risk Cost", "cost"),
    (20, 25, "Time (Working Days)", "time"),
    (26, 30, "Analyst / Derived (deterministic Layer 1)", "derived"),
    (31, 31, "Schedule Binding (P6-ready)", "binding"),
]

#: The canonical Risk Register header row (col 1..31). Cols 1-30 are the frozen
#: contract-v2 set (byte-identical to the pre-REG03 fixture); col 31 is the new
#: P6-ready activity-binding INPUT column (inert - blank stays nil-impact).
RISK_HEADERS = [
    "Risk ID", "Risk Status", "Risk Description", "Package",
    "RBS LVL 1", "RBS LVL 2", "MC Include", "Distribution",
    "Correlation Group", "Recurrence Type", "Causes", "Consequences",
    "Existing Controls",
    "Cost Impact", "Probability", "Optimistic ($)", "Most Likely ($)",
    "Pessimistic ($)", "Basis of Estimate",
    "Time Impact", "Probability (Time)", "Optimistic (days)",
    "Most Likely (days)", "Pessimistic (days)", "Basis of Estimate",
    "Mode", "Impact_Basis", "EMV_cost ($)", "EMV_sched_days",
    "EMV_sched_dollars ($)",
    "Schedule Activity ID (P6)",
]
ACTIVITY_BINDING_COL = 31
LAST_RISK_COL = len(RISK_HEADERS)  # 31

#: 1-based column indices used by theming (must track RISK_HEADERS).
COL_MODE = 26
COL_EMV_COST = 28
COL_EMV_SCHED_DAYS = 29
COL_EMV_SCHED_DOLLARS = 30

#: Risk Register INPUT columns (user fills) -> blue font. The COST + TIME
#: three-point + classification cells the analyst enters, plus the new activity
#: binding. The DERIVED EMV cols (28-30) are calc (black; Excel formulas in S2).
_INPUT_COLS = tuple(list(range(4, 28)) + [ACTIVITY_BINDING_COL])  # 4..27, 31

# ===========================================================================
# REG03 S3 - the dynamic settings cascade. The six S1 inline dropdowns become
# named-range lists on a dedicated Lists sheet, plus RBS L1/L2 (S1-deferred),
# Package (WBS) and Factor. Each list is an OFFSET dynamic named range with a
# MAX(...,1) guard so it EXTENDS as the user adds entries AND never resolves to
# a zero-height range (no #REF! on an empty list). Data validation + named-range
# lists are input constraints only - NOT on the engine read path (value-neutral).
# ===========================================================================
LISTS_SHEET = "Lists"

#: Each cascade list: (Lists-sheet column, List_* name, Risk Register dropdown
#: column or None, seed values). Package/Factor seed blank (project-specific).
LIST_SPECS = [
    # REGUX-01 part 3: "Binary/PERT" was a distribution the EMV formula and the sampler both
    # handle and the dropdown did not offer (CiE finding, 07/09). Held equal to the field spec.
    ("A", "List_Distribution", 8, ["PERT", "Triangular", "Lognormal", "Binary", "Binary/PERT"]),
    ("B", "List_MCInclude", 7, ["Yes", "No"]),
    ("C", "List_TimeImpact", 20, ["Yes", "No"]),
    ("D", "List_Recurrence", 10, ["Single", "Recurring", "None"]),
    ("E", "List_Mode", COL_MODE, ["Series", "Hybrid", "Parallel"]),
    ("F", "List_CGCode", 9, list(f"CG{n:02d}" for n in range(1, 14))),
    ("G", "List_RBS_L1", 5, ["Technical", "Commercial", "Management", "External",
                             "Environmental", "Delivery"]),
    ("H", "List_RBS_L2", 6, ["Design", "Construction", "Procurement", "Interface",
                             "Approvals", "Weather", "Ground Conditions",
                             "Commissioning"]),
    ("I", "List_Package", 4, ["Civil", "Structural", "Mechanical", "Electrical",
                              "Piping", "Instrumentation", "Commissioning",
                              "Management"]),   # generic WBS starter - user overwrites
    ("J", "List_Factor", None, ["Labour rate", "Material rate", "Plant rate",
                                "Productivity", "Quantity growth", "FX",
                                "Escalation"]),  # generic Layer-1 factor starter
]
#: The List_* named ranges the cascade emits (for the contract / tests).
LIST_NAMES = tuple(name for _c, name, _dv, _s in LIST_SPECS)

# ===========================================================================
# Methodology contract (D1 - Grid_Methodology only; NOT the SR19 surface)
# ===========================================================================
METHODOLOGY_SHEET = "Methodology"
METHODOLOGY_DEFAULT_CG = 0.5  # neutral per-project default (Director D1)
CG_CODES = tuple(f"CG{n:02d}" for n in range(1, 14))  # CG01..CG13
MODE_MULTIPLIERS_DEFAULT = {"Series": 1.0, "Hybrid": 0.5, "Parallel": 0.0}
#: RS-D parts 2/6: template starting values for the methodology settings rows
#: (label, value, description). Per-project inputs; the engine carries no default.
METHODOLOGY_SETTINGS_DEFAULT = (
    ("Cost_Calibration_Tolerance_Dollars", 50000.0, "Cost cross-check: absolute tolerance ($)"),
    ("Cost_Calibration_Tolerance_Pct", 0.001, "Cost cross-check: relative tolerance (fraction)"),
    ("Schedule_Calibration_Tolerance_Days", 1.0, "Schedule cross-check: absolute tolerance (days)"),
    ("Schedule_Calibration_Tolerance_Pct", 0.05, "Schedule cross-check: relative tolerance (fraction)"),
    # Stage 4 F-30 (Director, 08/09/2026: 2%, "do not hard code"). Two arms' top-3 schedule
    # contributors are consistent when the risks they rank apart at a position are within this
    # fraction of each other in BOTH arms (the stricter reading; the check is order-aware).
    ("Schedule_Top3_Tie_Tolerance_Pct", 0.02,
     "Schedule top-3 cross-check: two contributors the arms rank apart are one tie when within this fraction of each other in BOTH arms"),
    ("Default_Injection_Method", "discrete_event_additive_days",
     "Dual-coded risks with no Injection_Method on the Mapping sheet take this"),
)

# ===========================================================================
# Named-range contract (Surface A only; reproduces the fixture's names EXACTLY)
# ===========================================================================
SETTINGS_SHEET = "Settings"
SIMULATION_SHEET = "Simulation"
MAPPING_SHEET = "Mapping"

# CONTRACT_VERSION + REQUIRED_NAMED_RANGES are imported from src.register_contract
# (the single, Pyodide-clean source shared with the Validate button + tests).

#: sheet-title -> Grid_* name (only names sheets that exist; Layer 1 OFF -> skip).
GRID_NAMES = {
    RISK_REGISTER_SHEET: "Grid_RiskRegister",
    "Layer1_Base": "Grid_Layer1_Base",
    "Layer1_Factors": "Grid_Layer1_Factors",
    "Layer1_Allocation": "Grid_Layer1_Allocation",
    "Layer1_Correlation": "Grid_Layer1_Correlation",
    METHODOLOGY_SHEET: "Grid_Methodology",
    MAPPING_SHEET: "Grid_Mapping",          # SRA-02 S-B (D-A binding surface)
}
MAPPING_HEADERS = ["Risk ID", "Pattern_ID", "Prefix_List", "Activity_Count",
                   "Gating_Activity_ID", "Injection_Method"]  # RS-D-6: per-risk method, optional

#: Names the template EMITS but the contract does not REQUIRE. Adding one of these
#: to ``REQUIRED_NAMED_RANGES`` would fail Validate on every register scaffolded
#: before it - a contract-version bump on the client-number-bearing lane, which
#: SRA-02 D-3 forbids. So ``Grid_Mapping`` is emitted for the SRA engine to bind
#: against, while an older register without it still validates.
EMITTED_ONLY_NAMES = frozenset({"Grid_Mapping"})

# ===========================================================================
# SRA-02 S-B - the schedule surface (four tabs folded in per SRA-01 D-B)
#
# Sheet names and column sets are pinned in SRA02_SA_pinned_contract.md 1.1-1.6,
# read from src/sra/strawman_reader.py itself. Two rules govern this block:
#
#   1. Every header below is the reader's FIRST declared variant (the underscored
#      spelling). tests/test_sra02_sb_schedule_surface.py cross-checks each list
#      against the reader's own dict, so a drift on either side reds.
#   2. The scaffolder does NOT import the reader. It is the standalone /
#      Pyodide-adjacent surface and must stay import-light; the coupling lives in
#      the test, not at runtime.
#
# All four ship headers-only (or labels-only) and read to a well-formed nil, which
# is the SRA-01:71 schedule analogue of the S1 cost nil gate.
# ===========================================================================
PATTERNS_SHEET = "Risk_Activity_Patterns"
ASSIGNMENTS_SHEET = "Risk_Pattern_Assignments"
TREATMENTS_SHEET = "Treatments"

#: NOT "Calibration". ``get_strawman_calibration_target:680`` hard-codes
#: ``wb["Summary"]``, so the reader's literal is the contract and SRA-01:43's
#: "Calibration tab" wording is indicative only. A tab named "Calibration" would be
#: invisible to the only reader that consumes it.
CALIBRATION_SHEET = "Summary"

PATTERN_HEADERS = ["Pattern_ID", "Description", "Prefix_List", "Is_Cost_Only",
                   "Default_Mapping_Confidence", "Reconciliation_Treatment",
                   "Example_Risk_IDs", "Notes"]
ASSIGNMENT_HEADERS = ["Risk_ID", "Pattern_ID", "Assignment_Confidence", "Notes"]
TREATMENT_HEADERS = ["Risk_ID", "Treatment_Description", "Effectiveness_Pct",
                     "Effectiveness_Confidence"]

#: Calibration is the one surface that is NOT header-driven: the reader walks column
#: A and matches ``_normalise``d text (lowercase/strip) against four exact literals,
#: taking column B of the first match. These are the human-readable spellings that
#: normalise onto those literals; the test asserts that mapping rather than trusting
#: it. Order is presentation only - the reader matches by text, not position.
CALIBRATION_LABELS = [
    "Total EMV days (PERT)",
    "Total EMV $ cost-of-delay (PERT)",
    "Aggregate finish-date slippage days (PERT)",
    "Aggregate finish-date slippage $ (PERT)",
]

#: TOC tab-list geometry. The generated list fills from ``_TOC_TABLIST_FIRST_ROW``
#: down, one row per sheet; the legend header sits at ``_TOC_LEGEND_ROW``. Shared by
#: build_toc (which writes the legend) and _generate_toc_tablist (which fills the
#: list and refuses to reach it) so the two cannot drift apart.
_TOC_TABLIST_FIRST_ROW = 5
#: S-B took the inventory from 13 sheets to 17. The historical reservation was
#: rows 5-20 (16 rows), which 17 sheets overruns, so the legend moves down and the
#: reservation widens to 21 rows - four spare rather than the zero that squeezing
#: into the old block would have left.
_TOC_LEGEND_ROW = 26


def _name(wb, nm: str, ref: str) -> None:
    wb.defined_names.add(DefinedName(nm, attr_text=ref))


# ===========================================================================
# Structure builders (shared by the empty template AND the CI fixture)
# ===========================================================================

def write_risk_header_rows(ws) -> None:
    """Row-3 section band labels + row-4 column headers (the contract spine).
    Cols 1-30 are byte-identical to the pre-REG03 fixture; col 31 is additive."""
    for start, _end, label, _tint in RISK_SECTION_BANDS:
        ws.cell(row=SECTION_HEADER_ROW, column=start, value=label)
    for c, h in enumerate(RISK_HEADERS, start=1):
        ws.cell(row=HEADER_ROW, column=c, value=h)


# ===========================================================================
# REG03 S2 - EMV as live Excel formulas (the deterministic cross-check).
# The single source of the EMV arithmetic, shared by the empty template and the
# CI fixture. The distribution-mean dispatch mirrors src/distributions.sample_cost
# (reference: build_synthetic_wind_fixture._cost_distribution_mean); the mode
# multiplier is looked up from Grid_Methodology (single source). Blank inputs ->
# 0 / blank, never #DIV/0! or #N/A (INDEX/MATCH+IFERROR; not XLOOKUP, whose
# headless evaluator support is unreliable). z = 1.2816 = Phi^{-1}(0.90).
# ===========================================================================
DAY_RATE_NAME = "MC_day_rate"       # named range on the MC_Params day_rate cell
DAY_RATE_LABEL = "day_rate ($/wd)"  # its MC_Params col-B label (both builders)
_EMV_Z90 = "1.2816"

# Fixed column letters for the contract (must track RISK_HEADERS).
_C_DIST, _C_PROB_C = "H", "O"
_C_OPT_C, _C_ML_C, _C_PESS_C = "P", "Q", "R"
_C_TIMP, _C_PROB_T = "T", "U"
_C_OPT_D, _C_ML_D, _C_PESS_D = "V", "W", "X"
_C_MODE, _C_EMV_DAYS = "Z", "AC"
#: Methodology lookup vectors (label col A / value col B; 13 CG + 3 mode + slack).
_METH_A, _METH_B = f"{METHODOLOGY_SHEET}!$A$2:$A$20", f"{METHODOLOGY_SHEET}!$B$2:$B$20"


def emv_formula_strings(row: int) -> tuple[str, str, str]:
    """Return the (EMV_cost, EMV_sched_days, EMV_sched_dollars) Excel formula
    strings for Risk Register ``row`` (cols 28/29/30). Distribution-aware and
    blank-safe; reads the Mode multiplier from Grid_Methodology and day_rate from
    the ``MC_day_rate`` named range."""
    r = row
    dist_mean = (
        f'IF(OR(LOWER({_C_DIST}{r})="pert",LOWER({_C_DIST}{r})="binary/pert"),'
        f'({_C_OPT_C}{r}+4*{_C_ML_C}{r}+{_C_PESS_C}{r})/6,'
        f'IF(LOWER({_C_DIST}{r})="binary",{_C_ML_C}{r},'
        f'IF(LOWER({_C_DIST}{r})="lognormal",'
        f'IF({_C_ML_C}{r}<=0,0,IF(OR({_C_PESS_C}{r}<={_C_OPT_C}{r},'
        f'{_C_PESS_C}{r}<=0,{_C_OPT_C}{r}<=0),ABS({_C_ML_C}{r}),'
        f'{_C_ML_C}{r}*EXP((MAX((LN({_C_PESS_C}{r})-LN({_C_OPT_C}{r}))/'
        f'(2*{_EMV_Z90}),0.01)^2)/2))),'
        f'({_C_OPT_C}{r}+{_C_ML_C}{r}+{_C_PESS_C}{r})/3)))'
    )
    emv_cost = f'=IF({_C_PROB_C}{r}="","",{_C_PROB_C}{r}*{dist_mean})'
    mode_mult = f'IFERROR(INDEX({_METH_B},MATCH({_C_MODE}{r},{_METH_A},0)),0)'
    emv_days = (
        f'=IF(OR({_C_TIMP}{r}<>"Yes",{_C_PROB_T}{r}=""),0,'
        f'{_C_PROB_T}{r}*({_C_OPT_D}{r}+4*{_C_ML_D}{r}+{_C_PESS_D}{r})/6*{mode_mult})'
    )
    emv_dollars = f'={_C_EMV_DAYS}{r}*{DAY_RATE_NAME}'
    return emv_cost, emv_days, emv_dollars


def write_emv_formulas(ws, first_row: int, last_row: int) -> None:
    """Write the three EMV formulas into cols 28-30 for each row in the range
    (calc cells - black font, no fill). Value-neutral to the MC (EMV is a
    display/cross-check surface, not an MC input)."""
    for r in range(first_row, last_row + 1):
        for col, formula in zip((28, 29, 30), emv_formula_strings(r)):
            ws.cell(row=r, column=col, value=formula)


def name_day_rate(wb, mc_params_ws) -> None:
    """Name the MC_Params day_rate value cell ``MC_day_rate`` so EMV_sched_dollars
    references it robustly (row-move safe). Both the template and the fixture call
    this on their own MC_Params sheet."""
    title = mc_params_ws.title
    for cell in mc_params_ws["B"]:
        if cell.value == DAY_RATE_LABEL:
            _name(wb, DAY_RATE_NAME, f"'{title}'!$C${cell.row}")
            return
    raise ValueError(f"{DAY_RATE_LABEL!r} label not found on {title} - cannot name MC_day_rate")


def theme_risk_register(ws, n_rows: int) -> None:
    """REG-02 theming, generalised to the 31-col contract. Styles/properties
    ONLY - sets no cell VALUE, so the engine reads byte-identically."""
    header_row, first_data, last_data = HEADER_ROW, DATA_START_ROW, HEADER_ROW + max(n_rows, 0)

    hdr_fill = PatternFill("solid", fgColor=HDR_FILL)
    hdr_font = Font(bold=True, color="FFFFFF", size=10)
    for c in range(1, LAST_RISK_COL + 1):
        cell = ws.cell(row=header_row, column=c)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center", vertical="center",
                                   wrap_text=True)
    ws.row_dimensions[header_row].height = 30

    # Row-3 section bands: light fills + centre-across (no merged cells).
    for start, end, _label, tint in RISK_SECTION_BANDS:
        fill = PatternFill("solid", fgColor=SECTION_TINT[tint])
        for c in range(start, end + 1):
            cell = ws.cell(row=SECTION_HEADER_ROW, column=c)
            cell.fill = fill
            cell.font = Font(bold=True, italic=True, size=9)
            cell.alignment = Alignment(horizontal="centerContinuous")
        sep = Side(style="medium", color=HDR_FILL)
        for rr in range(SECTION_HEADER_ROW, last_data + 1):
            ws.cell(row=rr, column=start).border = Border(left=sep)

    ws.freeze_panes = "D5"
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(LAST_RISK_COL)}{last_data}"
    ws.sheet_properties.tabColor = TAB_REGISTER

    widths = {1: 10, 2: 11, 3: 40, 4: 16, 5: 20, 6: 16, 7: 10, 8: 12, 9: 14,
              10: 14, 11: 30, 12: 30, 13: 30, 19: 26, 25: 16, 26: 11, 27: 18,
              28: 15, 29: 15, 30: 18, 31: 22}
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w
    # 11-13 (Causes / Consequences / Existing Controls) were 13 wide and unwrapped - a filler's
    # sentence vanished off the cell edge (REGUX-01 part 3).
    for c in (3, 11, 12, 13, 19, 25):  # wrap the prose/basis columns
        for rr in range(first_data, last_data + 1):
            ws.cell(row=rr, column=c).alignment = Alignment(
                wrap_text=True, vertical="top")


def resize_layer1_correlation(sheet, factor_names, corr_mode: str | None = None):
    """REG03 S3b: resize the Layer1_Correlation lower-triangle grid to ``factor_names``.

    The Layer1_Correlation sheet is (Corr_Mode row, PSD_Status row, blank, a
    ``Factor``-header row listing the correlated factors, then one lower-triangle row
    per factor). As the Layer-1 factor list grows or shrinks, this re-writes the header
    + triangle to the new factor count, PRESERVING existing pairwise coefficients by
    factor-name match and defaulting new cells (diagonal 1.0, off-diagonal 0.0). The
    ``Corr_Mode`` toggle is left as-is unless ``corr_mode`` is given. A scaffolder
    mechanic on the Layer-1 opt-in shape - NOT a methodology change: for an unchanged
    factor set it reproduces the identical grid, so the Layer-1 read is byte-unchanged
    (value-neutral). Operates in place; returns the sheet.
    """
    names = [str(n) for n in factor_names]

    # Locate the "Factor" header row (below Corr_Mode / PSD_Status).
    header_row = None
    for r in range(1, (sheet.max_row or 0) + 2):
        if str(sheet.cell(row=r, column=1).value or "").strip().lower() == "factor":
            header_row = r
            break
    if header_row is None:
        header_row = (sheet.max_row + 2) if sheet.max_row else 4

    # Read the existing factor order + off-diagonal coefficients (by unordered pair).
    old_names: list[str] = []
    c = 2
    while sheet.cell(row=header_row, column=c).value is not None:
        old_names.append(str(sheet.cell(row=header_row, column=c).value))
        c += 1
    old_coeff: dict = {}
    for i, a in enumerate(old_names):
        for j in range(i):  # strictly lower triangle (off-diagonal)
            v = sheet.cell(row=header_row + 1 + i, column=2 + j).value
            if v is not None:
                old_coeff[frozenset((a, old_names[j]))] = float(v)

    if corr_mode is not None:
        for r in range(1, header_row):
            if str(sheet.cell(row=r, column=1).value or "").strip().lower() == "corr_mode":
                sheet.cell(row=r, column=2, value=corr_mode)
                break

    # Clear the exact old-or-new header + triangle region (no extra trailing rows,
    # so an unchanged factor set leaves the grid byte-identical), then re-write.
    extent = max(len(old_names), len(names))
    for r in range(header_row, header_row + extent + 1):
        for cc in range(1, extent + 2):
            sheet.cell(row=r, column=cc).value = None

    sheet.cell(row=header_row, column=1, value="Factor")
    for j, name in enumerate(names):
        sheet.cell(row=header_row, column=2 + j, value=name)
    for i, a in enumerate(names):
        sheet.cell(row=header_row + 1 + i, column=1, value=a)
        for j in range(i + 1):
            value = 1.0 if j == i else old_coeff.get(frozenset((a, names[j])), 0.0)
            sheet.cell(row=header_row + 1 + i, column=2 + j, value=value)
    return sheet


def _finalize_chart(chart) -> None:
    """Repair the two openpyxl chart defects that make Excel run "file level
    validation and repair" on open (a chart/drawing repair surfaces as the generic
    file-level message, with NO named record - which is why the recovery log looks
    empty). Both are display-only (no engine read); call AFTER ``set_categories``.
    Moved here (REG05-A2) so the shared scaffolder OWNS the chart-repair, and the
    fixture builder imports it - one home, template + fixture cannot drift.

    1. Text categories: ``set_categories()`` ALWAYS emits a ``<numRef>`` (numeric
       reference), but our categories are TEXT (risk names / layer labels). A
       numeric-reference-to-text is a semantic error -> convert to ``<strRef>``.
    2. Axis positions: ``BarChart`` defaults BOTH axes to ``axPos="l"`` regardless
       of orientation - a category and a value axis cannot share the same side, so
       Excel repairs the geometry. Set them per orientation (x = category axis,
       y = value axis): a vertical ``"col"`` chart puts categories on the bottom and
       values on the left; a horizontal ``"bar"`` chart is the transpose."""
    for ser in chart.series:
        cat = getattr(ser, "cat", None)
        if cat is not None and cat.numRef is not None:
            ser.cat = AxDataSource(strRef=StrRef(f=cat.numRef.f))
    if chart.type == "bar":                                    # horizontal bars
        chart.x_axis.axPos, chart.y_axis.axPos = "l", "b"
    else:                                                      # "col" vertical bars
        chart.x_axis.axPos, chart.y_axis.axPos = "b", "l"


def build_layer1_sheets(
    wb, *,
    col_labels=(), row_labels=(), base_m=None,
    factors=(), alloc=None,
    corr_names=(), corr_lower=None, corr_mode="elicited",
    declared_total_m=None, factor_seed=None,
    n_wbs_rows: int = _N_LAYER1_WBS_ROWS, n_factor_rows: int = _N_LAYER1_FACTORS,
):
    """REG05-A2 §3.1: the four register-driven Layer-1 sheets, ONE structure source
    shared by the empty per-project template AND the CI fixtures (design brief §5
    no-drift). Generic structure only; project data is passed in as the FILL.

    Called EMPTY (no data args) -> the grids at their REAL SHAPE and blank (REGUX-01
    A-0.4): ``Layer1_Base`` is ``n_wbs_rows`` placeholder WBS rows x the eight generic
    resource columns with a Declared_Total/Units trailer; ``Layer1_Factors`` is
    ``n_factor_rows`` blank rows; ``Layer1_Allocation`` is those factor rows x the same
    WBS labels; ``Layer1_Correlation`` is an ``n_factor_rows``-square lower triangle under
    a blank name header. Before A-0.4 the empty call emitted header rows only -
    ``Layer1_Allocation`` was one cell - while the TOC gave a three-step procedure to
    fill grids that were not there. Blank rather than zero, because a zero grid parses
    silently to a Layer 1 that is on and contributes nothing; the parser refuses a blank
    one by name. An empty Layer-1 is still a no-op ONLY because ``Set_Layer1_Enabled``
    ships FALSE (§3.2).

    Called with DATA (the fixtures) -> the project's Layer-1, value-identical to the
    pre-A2 fixture output: the append sequence below reproduces the old
    ``_build_layer1_sheets`` exactly. Column/row labels + values are the fill; the
    structure is shared.

    Styling is the builder's, in both branches (A-0.4 moved it here from
    ``_apply_input_classes``, which blued every cell from row 2 down - trailer labels and
    the PSD row included). Blue = an input, and on these four sheets ``apply_protection``
    unlocks BY STYLE, so what is blue is exactly what a person can type in.

    Sheets: ``Layer1_Base`` (WBS rows x cost cols, $M + declared total),
    ``Layer1_Factors`` (name/driver/P10/mode/P90/column-scope), ``Layer1_Allocation``
    (factor x WBS-row 'x' marks), ``Layer1_Correlation`` (mode toggle + PSD flag +
    lower triangle). ``base_m`` is $M (read x 1e6 -> dollars); a ``None`` value is
    written blank. ``factors`` is an iterable of ``(name, driver, opt, ml, p90,
    column_scope_str)``; ``alloc`` maps factor name -> ``"ALL"`` or a list of bound row
    labels; ``corr_lower`` is the lower triangle incl. diagonal for ``corr_names``.
    """
    empty = base_m is None
    if empty:
        col_labels = tuple(col_labels) or LAYER1_GENERIC_COLS
        row_labels = tuple(row_labels) or tuple(
            f"WBS-{i:02d}" for i in range(1, n_wbs_rows + 1))
    n_cols, n_rows = len(col_labels), len(row_labels)

    bs = wb.create_sheet("Layer1_Base")
    bs.append(["WBS Row", *col_labels])
    if empty:
        for rl in row_labels:
            bs.append([rl, *([None] * n_cols)])
    else:
        for rl, vals in zip(row_labels, base_m):
            bs.append([rl, *[None if x is None else float(x) for x in vals]])
    bs.append([])
    bs.append(["Declared_Total ($M)",
               None if declared_total_m is None else float(declared_total_m)])
    bs.append(["Units", "$M (read x 1,000,000 -> dollars)"])
    declared_row = 1 + n_rows + 2

    fsheet = wb.create_sheet("Layer1_Factors")
    fsheet.append(["Factor", "Driver", "Opt_P10", "ML_mode", "P90", "Column_Scope"])
    for (name, driver, opt, ml, p90, col_scope) in factors:
        fsheet.append([name, driver, opt, ml, p90, col_scope])
    n_f = n_factor_rows if empty else len(factors)

    asheet = wb.create_sheet("Layer1_Allocation")
    asheet.append(["Factor", *row_labels])
    if alloc is not None:
        for (name, *_rest) in factors:
            spec = alloc.get(name, [])
            bound = set(row_labels) if spec == "ALL" else set(spec)
            asheet.append([name, *["x" if rl in bound else "" for rl in row_labels]])

    csheet = wb.create_sheet("Layer1_Correlation")
    csheet.append(["Corr_Mode", corr_mode, "(zero | elicited | one)"])
    csheet.append(["PSD_Status", "valid", "(reader recomputes via Corr_flag)"])
    csheet.append([])
    if corr_lower is not None and len(corr_names):
        csheet.append(["Factor", *corr_names])
        for i, cn in enumerate(corr_names):
            row = [corr_lower[i][j] if j <= i else None for j in range(len(corr_names))]
            csheet.append([cn, *row])
        k = len(corr_names)
    elif factor_seed:
        # a seeded identity grid from the List_Factor seed (no current caller passes one).
        csheet.append(["Factor"])
        resize_layer1_correlation(csheet, list(factor_seed), corr_mode=None)
        k = len(factor_seed)
    else:
        # empty template: a bare header (REG05-A2-FIX D2 - seeded names declared factors
        # defined nowhere) over an n_f-square blank triangle.
        csheet.append(["Factor"])
        k = n_f

    _style_layer1(bs, fsheet, asheet, csheet, n_cols=n_cols, n_rows=n_rows, n_f=n_f, k=k,
                  declared_row=declared_row)

    # REG04 Scope B: constrain the factor columns to List_Factor (value-neutral).
    add_list_dropdown(fsheet, "List_Factor", "A2:A100")   # Layer1_Factors factor col
    add_list_dropdown(csheet, "List_Factor", "A5:A100")   # Layer1_Correlation factor col
    return wb


def _style_layer1(bs, fsheet, asheet, csheet, *, n_cols, n_rows, n_f, k, declared_row) -> None:
    """Blue = a person types here, on the four Layer-1 sheets (REGUX-01 A-0.4). On these
    sheets ``apply_protection`` unlocks by style, so this is also the protection map.
    Writing a font materialises the blank grid cells, which is what lets a header-only
    sheet become a form at all (``_unlock`` clamps to the sheet extent)."""
    def blue(ws, r, c):
        ws.cell(row=r, column=c).font = INPUT_FONT

    # Layer1_Base: resource headers (a project may rename them), WBS labels, the $M grid,
    # and the declared total. The trailer labels stay black: they are labels.
    for c in range(2, 2 + n_cols):
        blue(bs, 1, c)
    for r in range(2, 2 + n_rows):
        for c in range(1, 2 + n_cols):
            blue(bs, r, c)
    blue(bs, declared_row, 2)
    bs.column_dimensions["A"].width = 22

    # Layer1_Factors: the whole body. The Table, header treatment and freeze come from
    # style_list_sheet_body in build_template - it is the fifth list-shaped sheet (§5.4).
    for r in range(2, 2 + n_f):
        for c in range(1, 7):
            blue(fsheet, r, c)
    fsheet.column_dimensions["A"].width = 22

    # Layer1_Allocation: the WBS header labels (renamed in step with Layer1_Base - the
    # parser matches the two BY NAME) and the factor x WBS grid.
    for c in range(2, 2 + n_rows):
        blue(asheet, 1, c)
    for r in range(2, 2 + n_f):
        for c in range(1, 2 + n_rows):
            blue(asheet, r, c)
    asheet.column_dimensions["A"].width = 22

    # Layer1_Correlation: the mode toggle, names across the header and down column A, and
    # the coefficients strictly below the diagonal. The diagonal and the upper triangle are
    # never read, so they are locked and greyed rather than left looking typeable.
    blue(csheet, 1, 2)
    hdr = _L1_CORR_HEADER_ROW
    for j in range(k):
        blue(csheet, hdr, 2 + j)
    for i in range(k):
        blue(csheet, hdr + 1 + i, 1)
        for j in range(k):
            if j < i:
                blue(csheet, hdr + 1 + i, 2 + j)
            else:
                csheet.cell(row=hdr + 1 + i, column=2 + j).fill = _NOT_READ_FILL
    csheet.column_dimensions["A"].width = 22


def build_emv_mode_analysis(wb, first_row: int, last_row: int) -> None:
    """REG05-A2 §3.3: the generic, project-parametrised "EMV & Mode Analysis" sheet.

    GENERIC replacement for the fixture's wind-literal version: totals, a ranked-risk
    helper table, and three native charts all reference the Risk Register's EMV
    columns (EMV_cost = ``AB``, EMV_sched_dollars = ``AD``) and Mode column over the
    scaffolded input-row block ``first_row..last_row``, so they recompute from
    whatever the user enters - no hardcoded figures, no wind row count baked in. The
    title (A1) is set from ``Set_ProjectName`` by :func:`apply_finish`. Presentation
    only (never on the engine read path). Unsorted EMV bars (register order); a sorted
    tornado + cosmetic polish are deferred to REG05-B.
    """
    ws = wb.create_sheet("EMV & Mode Analysis")
    ws.sheet_properties.tabColor = TAB_ANALYSIS
    title_font = Font(bold=True, size=13, color=HDR_FILL)
    lbl = Font(bold=True, size=10)
    note_font = Font(italic=True, size=8, color="666666")

    rr = f"'{RISK_REGISTER_SHEET}'"
    c_id = get_column_letter(1)                      # A - Risk ID
    c_mode = get_column_letter(COL_MODE)             # Z - Mode
    c_cost = get_column_letter(COL_EMV_COST)         # AB - EMV_cost ($)
    c_sched = get_column_letter(COL_EMV_SCHED_DOLLARS)  # AD - EMV_sched_dollars ($)
    cost_rng = f"{rr}!{c_cost}{first_row}:{c_cost}{last_row}"
    sched_rng = f"{rr}!{c_sched}{first_row}:{c_sched}{last_row}"
    mode_rng = f"{rr}!{c_mode}{first_row}:{c_mode}{last_row}"

    ws["A1"] = "EMV & Mode Analysis"  # REG05-A1: project name appended by apply_finish
    ws["A1"].font = title_font
    ws["A2"] = ("Deterministic Layer-1 expected values (means) from the register EMV "
                "columns, NOT Monte-Carlo P-levels. Live formulas; refresh on open.")
    ws["A2"].font = note_font

    # --- summary block: totals + Mode counts as live formulas over the register ---
    ws["A4"] = "Layer-1 totals"; ws["A4"].font = lbl
    ws["A5"] = "Total cost EMV ($)"; ws["B5"] = f"=SUM({cost_rng})"
    ws["A6"] = "Total schedule EMV ($)"; ws["B6"] = f"=SUM({sched_rng})"
    ws["A7"] = "Total Layer-1 EMV ($)"; ws["B7"] = "=B5+B6"
    ws["A8"] = "Risks: Series / Hybrid / Parallel"
    ws["B8"] = (f'=COUNTIF({mode_rng},"Series")&" / "&COUNTIF({mode_rng},"Hybrid")'
                f'&" / "&COUNTIF({mode_rng},"Parallel")')

    # --- helper table 1: cost EMV by risk (register order; recomputes per project) ---
    t1 = 11
    ws.cell(row=t1, column=1, value="Risk").font = lbl
    ws.cell(row=t1, column=2, value="Cost EMV ($)").font = lbl
    for k, r in enumerate(range(first_row, last_row + 1)):
        ws.cell(row=t1 + 1 + k, column=1, value=f"={rr}!{c_id}{r}")
        ws.cell(row=t1 + 1 + k, column=2, value=f"={rr}!{c_cost}{r}")
    t1_end = t1 + (last_row - first_row + 1)

    ch1 = BarChart(); ch1.type = "bar"; ch1.title = "Cost EMV by risk (mean $)"
    ch1.y_axis.title = "Cost EMV ($)"; ch1.legend = None
    ch1.add_data(Reference(ws, min_col=2, min_row=t1, max_row=t1_end),
                 titles_from_data=True)
    ch1.set_categories(Reference(ws, min_col=1, min_row=t1 + 1, max_row=t1_end))
    _finalize_chart(ch1)
    ch1.height = 9; ch1.width = 16
    ws.add_chart(ch1, "D4")

    # --- helper table 2: schedule EMV ($) by risk ---
    t2 = t1_end + 3
    ws.cell(row=t2, column=1, value="Risk").font = lbl
    ws.cell(row=t2, column=2, value="Schedule EMV ($)").font = lbl
    for k, r in enumerate(range(first_row, last_row + 1)):
        ws.cell(row=t2 + 1 + k, column=1, value=f"={rr}!{c_id}{r}")
        ws.cell(row=t2 + 1 + k, column=2, value=f"={rr}!{c_sched}{r}")
    t2_end = t2 + (last_row - first_row + 1)

    ch2 = BarChart(); ch2.type = "col"; ch2.title = "Schedule EMV by risk (mean $)"
    ch2.y_axis.title = "Schedule EMV ($)"; ch2.legend = None
    ch2.add_data(Reference(ws, min_col=2, min_row=t2, max_row=t2_end),
                 titles_from_data=True)
    ch2.set_categories(Reference(ws, min_col=1, min_row=t2 + 1, max_row=t2_end))
    _finalize_chart(ch2)
    ch2.height = 9; ch2.width = 16
    ws.add_chart(ch2, "D24")

    # --- helper table 3: cost vs schedule split (from the summary totals) ---
    t3 = t2_end + 3
    ws.cell(row=t3, column=1, value="Layer").font = lbl
    ws.cell(row=t3, column=2, value="EMV ($)").font = lbl
    ws.cell(row=t3 + 1, column=1, value="Cost"); ws.cell(row=t3 + 1, column=2, value="=B5")
    ws.cell(row=t3 + 2, column=1, value="Schedule"); ws.cell(row=t3 + 2, column=2, value="=B6")

    ch3 = BarChart(); ch3.type = "col"; ch3.title = "Layer-1 EMV: cost vs schedule ($)"
    ch3.y_axis.title = "EMV ($)"; ch3.legend = None
    ch3.add_data(Reference(ws, min_col=2, min_row=t3, max_row=t3 + 2),
                 titles_from_data=True)
    ch3.set_categories(Reference(ws, min_col=1, min_row=t3 + 1, max_row=t3 + 2))
    _finalize_chart(ch3)
    ch3.height = 8; ch3.width = 10
    ws.add_chart(ch3, "D44")

    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 22
    for col in ("C", "D"):
        ws.column_dimensions[col].width = 20


def build_lists_sheet(wb, factor_seed=None):
    """REG03 S3a: the dynamic settings cascade source. One column per cascade list
    on a dedicated ``Lists`` sheet, each exposed as an OFFSET dynamic named range
    (``List_*``) that extends as the user adds entries. The ``MAX(COUNTA(...),1)``
    guard keeps the range height >= 1, so an empty list resolves to a single blank
    cell (no ``#REF!``) rather than a zero-height range. Value-neutral: the Lists
    sheet + names are input sources for data validation only, not on the read path.
    Additive-compatible: SRA-02 can add its own list columns + ``List_*`` names later.

    REG04 Scope B: ``factor_seed`` overrides the ``List_Factor`` column - a Layer-1
    project (or the CI fixture) passes its own factor names so the factor dropdown on
    the Layer-1 sheets is consistent; the blank template uses the generic starter.
    """
    ws = wb.create_sheet(LISTS_SHEET)
    ws.sheet_properties.tabColor = TAB_REFERENCE
    ws["A1"] = "Cascade lists - edit here; the Risk Register dropdowns follow."
    hdr_font = Font(bold=True, size=9)
    for col, name, _dvcol, seeds in LIST_SPECS:
        if name == "List_Factor" and factor_seed is not None:
            seeds = list(factor_seed)
        ws[f"{col}2"] = name.replace("List_", "")
        ws[f"{col}2"].font = hdr_font
        for i, value in enumerate(seeds, start=3):
            cell = ws[f"{col}{i}"]
            cell.value = value
            cell.font = INPUT_FONT
        ws.column_dimensions[col].width = 18
        # OFFSET dynamic name over the list body (row 3 down), MAX-guarded.
        ref = (f"OFFSET({LISTS_SHEET}!${col}$3,0,0,"
               f"MAX(COUNTA({LISTS_SHEET}!${col}$3:${col}$1000),1),1)")
        _name(wb, name, ref)
    return ws


def add_list_dropdown(ws, list_name: str, cell_range: str) -> None:
    """Attach a single list-sourced data-validation dropdown (``=list_name``) to a
    cell range on any sheet - e.g. the ``List_Factor`` dropdown on the Layer-1 factor
    columns (REG04 Scope B). Value-neutral (input constraint only)."""
    label = list_name.replace("List_", "")
    dv = DataValidation(type="list", formula1=list_name, allow_blank=True,
                        showDropDown=False)
    dv.errorTitle = f"Invalid {label}"
    dv.error = f"Choose from the {label} cascade list (edit it on the Lists tab)."
    ws.add_data_validation(dv)
    dv.add(cell_range)


def add_dropdowns(ws, first_row: int, last_row: int) -> None:
    """REG03 S3a: attach list-sourced data-validation dropdowns to the Risk
    Register input columns, referencing the ``List_*`` named ranges (the dynamic
    cascade) instead of S1's inline literals. Adds the S1-deferred RBS L1/L2 and
    Package dropdowns. Value-neutral (input constraints only). ``last_row`` is
    inclusive; for an empty template pass a block of blank input rows to pre-arm."""
    if last_row < first_row:
        last_row = first_row
    for _col, name, dvcol, _seeds in LIST_SPECS:
        if dvcol is None:
            continue  # List_Factor has no Risk Register column (Layer-1 surface)
        label = name.replace("List_", "")
        dv = DataValidation(type="list", formula1=name, allow_blank=True,
                            showDropDown=False)
        dv.errorTitle = f"Invalid {label}"
        dv.error = f"Choose a value from the {label} cascade list (edit it on the Lists tab)."
        ws.add_data_validation(dv)
        letter = get_column_letter(dvcol)
        dv.add(f"{letter}{first_row}:{letter}{last_row}")


def style_register_input_cells(ws, first_row: int, last_row: int) -> None:
    """D2 - blue font on the user-fill (input) columns over the data range.
    The derived EMV cols stay black (calc). Value-neutral."""
    if last_row < first_row:
        return
    for rr in range(first_row, last_row + 1):
        for c in _INPUT_COLS:
            ws.cell(row=rr, column=c).font = INPUT_FONT


def build_methodology_sheet(wb, cg_values: dict | None = None,
                            cg_descriptions: dict | None = None):
    """Grid_Methodology surface. THREE columns (REG03 S2b D2): ``CG code / Mode |
    Coefficient / Multiplier | Description``. Each ``CGnn`` row carries a coefficient
    (col B) and a bare description (col C, e.g. "Labour" - no "CGnn -" prefix); the
    three mode rows carry a multiplier and a blank description. With
    ``cg_values``/``cg_descriptions`` None the CG rows carry the neutral 0.5 default
    and blank descriptions (empty template); the CI fixture passes wind values.

    ``resolve_methodology_from_grid`` reads only col A (label) + col B (value) and
    ignores col C, so the description column is bit-safe for the generic Tier-1 cost
    path. ``openpyxl_reader.read_cg_descriptions`` (S2b) reads col C when the grid is
    present, else falls back to the MC_Params col-B scan (the client register).
    """
    cg = {code: (cg_values.get(code, METHODOLOGY_DEFAULT_CG) if cg_values else
                 METHODOLOGY_DEFAULT_CG) for code in CG_CODES}
    desc = cg_descriptions or {}
    ms = wb.create_sheet(METHODOLOGY_SHEET)
    ms["A1"] = "CG code / Mode"
    ms["B1"] = "Coefficient / Multiplier"
    ms["C1"] = "Description"
    r = 2
    for code in sorted(cg):
        ms.cell(row=r, column=1, value=code)
        vc = ms.cell(row=r, column=2, value=cg[code])
        vc.font = INPUT_FONT  # CG coefficient is an input the user may re-elicit
        dc = ms.cell(row=r, column=3, value=(desc.get(code) or None))
        dc.font = INPUT_FONT  # CG description is a per-project input
        r += 1
    for mode in ("Series", "Hybrid", "Parallel"):
        ms.cell(row=r, column=1, value=mode)
        mc = ms.cell(row=r, column=2, value=MODE_MULTIPLIERS_DEFAULT[mode])
        mc.protection = LOCKED  # mode multipliers are locked calc constants
        r += 1
    # RS-D parts 2/6 (D-14, D-18): the register's calibration tolerances and default
    # injection method - the specialist's per-project settings, so INPUT-styled. The
    # engine reads them from here and carries no default.
    for label, value, note in METHODOLOGY_SETTINGS_DEFAULT:
        ms.cell(row=r, column=1, value=label)
        vc = ms.cell(row=r, column=2, value=value)
        vc.font = INPUT_FONT
        nc = ms.cell(row=r, column=3, value=note)
        nc.font = INPUT_FONT
        r += 1
    ms.column_dimensions["A"].width = 18
    ms.column_dimensions["B"].width = 24
    ms.column_dimensions["C"].width = 34
    return ms


def build_settings_and_simulation(wb) -> None:
    """The Tier-1 xlwings I/O sheets (Settings + Simulation) and their
    ``Set_*``/``Out_*`` named ranges. Reproduces ``_build_tier1_io_sheets``'s
    Settings/Simulation content + names EXACTLY (bit-safe), and adds the D2
    amber+locked styling on the ``Out_*`` (model write-back) cells.
    """
    st = wb.create_sheet(SETTINGS_SHEET)
    st["A1"] = "Iterations (interactive default)"; st["B1"] = 25000
    st["A2"] = "Random seed"; st["B2"] = 42
    st["A3"] = "View (owner | shared-pool)"; st["B3"] = "owner"
    st["A4"] = "Risk-ID prefix"; st["B4"] = "WT"
    st["A5"] = "Iterations (100k on-demand button)"; st["B5"] = 100000
    # REG03 S2 rider (2): the contract version (calc constant; Validate checks it).
    st["A6"] = "Contract version"; st["B6"] = CONTRACT_VERSION
    st["B6"].protection = LOCKED
    st["A7"] = "Pyodide runtime pin"; st["B7"] = "314.0.1"  # ratified Q4; do not float
    # REG05-A2 §3.2: the Layer-1 off-signal. Default FALSE so an empty, present
    # Layer-1 reads as OFF (nil impact) - the read boundaries only parse Layer-1
    # when this is TRUE. New Set_* cell at A8/B8, so no existing Set_* cell moves.
    st["A8"] = "Layer 1 enabled (TRUE/FALSE)"; st["B8"] = False
    for r in (1, 2, 3, 4, 5, 8):
        st.cell(row=r, column=2).font = INPUT_FONT  # run settings are user inputs
    st.column_dimensions["A"].width = 34
    st.column_dimensions["B"].width = 16
    _name(wb, "Set_iterations", "Settings!$B$1")
    _name(wb, "Set_seed", "Settings!$B$2")
    _name(wb, "Set_view", "Settings!$B$3")
    _name(wb, "Set_risk_prefix", "Settings!$B$4")
    _name(wb, "Set_iterations_max", "Settings!$B$5")
    _name(wb, "Set_ContractVersion", "Settings!$B$6")
    _name(wb, LAYER1_ENABLED_NAME, "Settings!$B$8")

    sim = wb.create_sheet(SIMULATION_SHEET)
    sim["A1"] = "P-level"; sim["B1"] = "Cost ($)"
    sim["D1"] = "Cum. prob"; sim["E1"] = "Cost ($)"
    sim["G1"] = "Corr_flag"
    sim["G3"] = "P80 CI half-width (25k)"; sim["G4"] = "P80 CI half-width (%)"
    sim["I1"] = "P-level"; sim["J1"] = "rho=0"; sim["K1"] = "elicited"; sim["L1"] = "rho=1"
    # REG03 S2 rider (1): the Validate button writes status + message here.
    sim["N1"] = "Contract validation"
    sim["N1"].font = Font(bold=True, size=10)
    _name(wb, "Out_ptable", "Simulation!$A$2:$B$20")
    _name(wb, "Out_scurve", "Simulation!$D$2:$E$102")
    _name(wb, "Corr_flag", "Simulation!$H$1")
    _name(wb, "Out_conv_halfwidth", "Simulation!$H$3")
    _name(wb, "Out_conv_pct", "Simulation!$H$4")
    _name(wb, "Out_triple", "Simulation!$I$2:$L$20")
    _name(wb, "Out_validation", "Simulation!$N$2:$N$3")  # N2 = PASS/FAIL, N3 = message
    # D2: the model write-back ranges are amber-shaded + locked ("do not edit").
    for coord in ("A2:B20", "D2:E102", "H1", "H3", "H4", "I2:L20", "N2:N3"):
        region = sim[coord]
        rows = region if isinstance(region, tuple) else ((region,),)
        for row in rows:
            for cell in row:
                cell.fill = PYTHON_FILL
                cell.protection = LOCKED
    sim["G6"] = "Amber cells are written by the model (xlwings) - do not edit."
    sim["G6"].font = Font(italic=True, size=8, color="666666")


def finalize_named_ranges(wb) -> None:
    """Size the ``Grid_*`` named ranges to each present sheet's exact extent,
    ``$A$1``-anchored (row-1-aligned; the parser uses absolute Excel rows). Run
    AFTER all data is written. Mirrors ``_build_tier1_io_sheets``'s grid pass;
    absent sheets (Layer 1 OFF on an empty template) are simply skipped.
    """
    for sheet_name, grid_name in GRID_NAMES.items():
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        last = f"{get_column_letter(ws.max_column)}${ws.max_row}"
        _name(wb, grid_name, f"'{sheet_name}'!$A$1:${last}")


def build_mapping_sheet(wb):
    """Empty CPM-binding Mapping sheet (headers only; the fixture fills Time=Yes
    rows). Machine-facing (REG-01 section 3)."""
    mapping = wb.create_sheet(MAPPING_SHEET)
    for c, h in enumerate(MAPPING_HEADERS, start=1):
        mapping.cell(row=1, column=c, value=h)
    return mapping


def _build_header_only_sheet(wb, title: str, headers: list[str]):
    """A machine-facing sheet carrying its header row and nothing else."""
    ws = wb.create_sheet(title)
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
    return ws


def calibration_formula_strings(first_row: int, last_row: int) -> tuple[str, ...]:
    """Return the four ``Summary`` column-B formulas, in ``CALIBRATION_LABELS`` order.

    The deterministic schedule cross-check (SRA-02 S-E). Two independent readings
    of one quantity, both live over the Risk Register input block:

    * Comparator 1 - total EMV days, the PERT mean weighted by Prob_T over the
      Time=Yes rows, with **no** Mode multiplier. Same arithmetic as the days limb
      of :func:`emv_formula_strings` minus its ``mode_mult`` factor.
    * Comparator 2 - aggregate finish-date slippage days, the sum of the register's
      own EMV_sched_days column, i.e. the same PERT means **with** the constant Mode
      multiplier. The Mode weighting (Series/Hybrid/Parallel) is the deterministic
      proxy for how much of each delay reaches the finish date, which is what the
      CPM schedule arm derives properly - so the pair is a cross-check rather than a
      restatement.

    Dollars come off the days via the ``MC_day_rate`` named range in both cases, so
    a project that changes its day rate moves both without a scaffolder edit. An
    empty register evaluates to 0/0/0/0, never an error: the ``Time Impact`` test
    is false on every blank row, and SUM over a blank block is zero.
    """
    rr = f"'{RISK_REGISTER_SHEET}'"
    timp_rng = f"{rr}!{_C_TIMP}{first_row}:{_C_TIMP}{last_row}"
    prob_rng = f"{rr}!{_C_PROB_T}{first_row}:{_C_PROB_T}{last_row}"
    opt_rng = f"{rr}!{_C_OPT_D}{first_row}:{_C_OPT_D}{last_row}"
    ml_rng = f"{rr}!{_C_ML_D}{first_row}:{_C_ML_D}{last_row}"
    pess_rng = f"{rr}!{_C_PESS_D}{first_row}:{_C_PESS_D}{last_row}"
    days_rng = f"{rr}!{_C_EMV_DAYS}{first_row}:{_C_EMV_DAYS}{last_row}"
    # The labels are written from row 1 down, so each comparator's days figure sits
    # in column B of its own label's row; the dollar rows multiply it by the rate.
    row_of = {label: r for r, label in enumerate(CALIBRATION_LABELS, start=1)}
    c1_days_cell = f"B{row_of[CALIBRATION_LABELS[0]]}"
    c2_days_cell = f"B{row_of[CALIBRATION_LABELS[2]]}"
    return (
        f'=SUMPRODUCT(({timp_rng}="Yes")*{prob_rng}*'
        f"({opt_rng}+4*{ml_rng}+{pess_rng})/6)",
        f"={c1_days_cell}*{DAY_RATE_NAME}",
        f"=SUM({days_rng})",
        f"={c2_days_cell}*{DAY_RATE_NAME}",
    )


def build_schedule_surface(wb, first_row: int, last_row: int):
    """SRA-02 S-B: the four workshop-output tabs the SRA engine reads (SRA-01 D-B).

    Three are header-driven and ship their header row only. The fourth,
    ``Summary``, is NOT header-driven - ``get_strawman_calibration_target`` walks
    column A for four literal labels and takes column B of the first match - so it
    ships the labels down column A with the comparator formulas beside them.

    S-E turned those column-B cells from blank workshop inputs into live formulas
    over the register (:func:`calibration_formula_strings`). The labels are
    unchanged, so the reader contract is untouched; what changed is that the
    cross-check is now computed rather than hand-typed. The value cells are
    therefore calc cells, not INPUT cells.

    Every tab reads to a well-formed nil while empty (SRA-01:71). Like ``Mapping``,
    these are machine-facing surfaces the workshop fills, so they carry no seeded
    rows: a scaffolded register must never hand a new project inherited numbers.
    """
    _build_header_only_sheet(wb, PATTERNS_SHEET, PATTERN_HEADERS)
    _build_header_only_sheet(wb, ASSIGNMENTS_SHEET, ASSIGNMENT_HEADERS)
    _build_header_only_sheet(wb, TREATMENTS_SHEET, TREATMENT_HEADERS)

    cal = wb.create_sheet(CALIBRATION_SHEET)
    formulas = calibration_formula_strings(first_row, last_row)
    for r, (label, formula) in enumerate(zip(CALIBRATION_LABELS, formulas), start=1):
        cal.cell(row=r, column=1, value=label)
        cal.cell(row=r, column=2, value=formula)
    cal.column_dimensions["A"].width = 44
    cal.column_dimensions["B"].width = 18
    return cal


def build_mc_params_sheet(wb, values: dict | None = None):
    """MC_Params config sheet. The label set is the contract read by
    ``read_params_v5`` (col-B label scan). ``values`` maps label -> value; when
    None (empty template) the value cells are blank INPUT cells (blue font) the
    user fills. The CI fixture writes its own MC_Params directly (project data).
    """
    mp = wb.create_sheet("MC_Params")
    labels = [
        "Iterations (n)", SEED_LABEL, "Stakeholder view",
        "Reporting P-Level (pct)", "TIC - Total Installed Cost ($)",
        "Cascade enabled", "Cascade slip rate", "Cascade slip cap",
        "Cascade cost scale", "day_rate ($/wd)", "programme_seasons",
        "cp_hybrid_float_threshold_days", "schedule duration (weeks)",
        "expected_time_yes_count",
    ]
    for i, label in enumerate(labels, start=2):
        mp.cell(row=i, column=2, value=label)
        vc = mp.cell(row=i, column=3, value=(values or {}).get(label))
        vc.font = INPUT_FONT
    mp.column_dimensions["B"].width = 40
    mp.column_dimensions["C"].width = 18
    return mp


def build_toc(wb) -> None:
    """TOC / instructions tab, incl. the D2 cell-type legend and the D1
    methodology-default flag. Placed first so it opens on load."""
    ws = wb.create_sheet("TOC & Instructions", 0)
    ws.sheet_properties.tabColor = TAB_REFERENCE
    title = Font(bold=True, size=14, color=HDR_FILL)
    h = Font(bold=True, size=11)
    note = Font(italic=True, size=9, color="666666")

    ws["A1"] = "Cost-QRA Register - project input document"
    ws["A1"].font = title
    ws["A2"] = ("Scaffolded once by tools/register_scaffold.py, then this file is "
                "yours - fill it in, it is standalone. Re-scaffolding is never run "
                "against a live register.")
    ws["A2"].font = note

    # XLSX-01 BLOCK 5: the contract version belongs where a user looks. It lived only on
    # Settings!B6, so a user could not tell whether their register matched the engine they
    # were about to point at it. This is a FORMULA, not a copy of the number: a literal here
    # would be a second source that drifts the first time the contract moves.
    ws["A3"] = "Register contract"
    ws["A3"].font = h
    vc = ws["B3"]
    vc.value = "=Settings!B6"
    vc.font = CALC_FONT
    vc.protection = LOCKED
    ws["C3"] = ("The engine checks this on every run and refuses on any mismatch. "
                "Shown here from Settings!B6, never typed twice.")
    ws["C3"].font = note

    ws["A4"] = "Tabs, in the order you fill them (auto-generated from the sheet inventory)"
    ws["A4"].font = h
    # REG05-A1: the tab-list is generated by apply_finish() over rows
    # _TOC_TABLIST_FIRST_ROW.._TOC_LEGEND_ROW-1 (after all sheets exist); reserved
    # here so the legend/notes below never collide. _generate_toc_tablist raises
    # rather than overwrite the legend if the inventory ever outgrows the block.

    r = _TOC_LEGEND_ROW
    ws.cell(row=r, column=1, value="Cell-type legend").font = h
    r += 1
    legend = [
        ("input", "Blue font, unlocked - you fill this in.", INPUT_FONT, None, None),
        ("calc", "Black font, locked - a live Excel formula (do not overwrite).", CALC_FONT, None, None),
        ("model", "Amber fill - written by the model each run; do not edit.", None, PYTHON_FILL, None),
        ("model-read", "Thin blue border - the Python model reads this cell (may also be an input).",
         None, None, _MACHINE_BORDER),
    ]
    for kind, desc, font, fill, border in legend:
        kc = ws.cell(row=r, column=1, value=kind)
        if font:
            kc.font = font
        if fill:
            kc.fill = fill
        if border:
            kc.border = border
        ws.cell(row=r, column=2, value=desc)
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="Methodology defaults").font = h
    r += 1
    ws.cell(row=r, column=2, value=(
        "The Methodology tab ships with CG coefficients defaulted to 0.5 - "
        "review / elicit per project. Mode multipliers (Series 1.0 / Hybrid 0.5 "
        "/ Parallel 0.0) are locked methodology constants."))

    r += 2
    ws.cell(row=r, column=1, value="Layer 1 - deterministic factor model (optional)").font = h
    r += 1
    ws.cell(row=r, column=2, value=(
        "The four Layer1_* tabs and the EMV & Mode Analysis tab are STANDARD on every "
        "register, but Layer 1 ships OFF: Settings!Set_Layer1_Enabled = FALSE, so the blank "
        "grids have NIL impact and the register reads exactly as a cost-only project. The "
        f"grids ship at their real shape, blank: Layer1_Base is {_N_LAYER1_WBS_ROWS} placeholder "
        f"WBS rows x {len(LAYER1_GENERIC_COLS)} resource columns, in $M; Layer1_Allocation is "
        f"{_N_LAYER1_FACTORS} factor rows x the same WBS columns; Layer1_Correlation is a "
        f"{_N_LAYER1_FACTORS}-factor lower triangle. To use Layer 1: (1) on Layer1_Base rename "
        "the WBS rows you need and type each row's $M by column, then the Declared_Total. A row "
        "with no numbers is ignored, so type 0 for a genuine zero. (2) On Layer1_Allocation "
        "rename the same WBS columns to match Layer1_Base EXACTLY - the model matches the two "
        "by name and refuses a mismatch; unused placeholder columns can stay. List your factors "
        "on Layer1_Factors (pick names from the dropdown) and tick their WBS cells with x. (3) "
        "On Layer1_Correlation type the correlated factor names across row 4 and down column A "
        "in the same order, and the coefficients in the blue lower triangle; grey cells are "
        "never read, and a blank pair means 0. (4) ONLY THEN set Set_Layer1_Enabled = TRUE. "
        "Turning Layer 1 on before the grids are filled is refused with a message naming the "
        "tab. The EMV & Mode Analysis tab (totals + charts) populates from the register EMV "
        "columns whenever the register is filled or a run happens. Leave the flag FALSE to keep "
        "Layer 1 off. A project needing more rows regenerates with "
        "build_template(n_layer1_wbs_rows=, n_layer1_factors=)."))

    r += 2
    ws.cell(row=r, column=1, value="Sheet protection (REG04)").font = h
    r += 1
    ws.cell(row=r, column=2, value=(
        "The machine tabs are protected (no password): input cells are unlocked, "
        "the contract cells + formulas are locked, and the workbook structure is "
        "locked so tabs cannot be deleted/reordered. This guards against accidental "
        "edits - it does NOT stop you deleting a named range, so run Validate "
        "Contract after any structural edit. That is a task-pane item, not a button on "
        "any sheet, and it exists only after activation - see 'Running a simulation' "
        "below. To make deliberate changes, Review > Unprotect Sheet."))

    # XLSX-01 BLOCK 1 + R-8: the run section. The TOC previously had none - a generalist
    # could read it end to end, fill the register, look for a Run button, and never find one
    # or be told that one has to be created first.
    r += 2
    ws.cell(row=r, column=1, value="Running a simulation").font = h
    r += 1
    ws.cell(row=r, column=2, value=(
        "STEP 1 - ACTIVATION, ONCE PER WORKBOOK, AND IT IS A SPECIALIST'S TASK (R-8). "
        "As it ships this workbook holds no code and no buttons: there is nothing to press "
        "and nothing is broken. A risk specialist installs the xlwings Lite add-in, adds "
        "numpy and scipy to its Environment, generates the model script by running "
        "tools/make_qra_xlwings.py in the repository, and pastes the result into the "
        "xlwings Lite editor. The Reference (xlwings) tab carries the requirements and a "
        "readable copy of the entry points. Until this is done, no simulation can run."))
    r += 1
    ws.cell(row=r, column=2, value=(
        "STEP 2 - FILL THE REGISTER. Enter one risk per row on Risk Register from row 5. "
        "Blue cells are yours; the dropdowns are driven by the Lists tab. You can sort "
        "and filter the register with the sheet protected. You cannot INSERT a row: "
        "Excel inserts a whole row and the EMV columns are locked calc cells, so a "
        "41st risk means Review > Unprotect Sheet (a specialist's step) or a register "
        "regenerated at a higher row count. Set the run controls on Settings "
        "(iterations, seed, view). If you are dollarising schedule delay, put the day "
        "rate on MC_Params - it is blank as shipped, and every schedule-dollar figure "
        "stays zero until it is filled."))
    r += 1
    ws.cell(row=r, column=2, value=(
        "STEP 3 - RUN, from the xlwings Lite task pane on the right. These are task-pane "
        "items, NOT buttons on any sheet: 'Run Simulation' (the interactive count from "
        "Settings), 'Run Simulation 100k' (the deliverable count), and 'Validate Contract' "
        "(self-checks the named ranges and the version, writing PASS or FAIL). Results "
        "land on the Simulation tab, which is amber - written by the model, do not edit."))
    r += 1
    ws.cell(row=r, column=2, value=(
        "WITHOUT ACTIVATION you can still do real work: fill the register and read the "
        "live expected-value totals and charts on Summary and EMV & Mode Analysis. Those "
        "are ordinary Excel formulas and need no simulation. What activation adds is the "
        "Monte-Carlo run."))
    r += 1
    ws.cell(row=r, column=2, value=(
        "SPECIALIST TABS. The four Layer1_* tabs are Tier-2: they need an elicited factor "
        "model and are optional (see Layer 1 above). Simulation and Out_* are written by "
        "the model. A generalist needs none of them."))

    # REGUX-01 A-1 (part 3): the README the template lost when it was generalised (F-10), restored
    # here on the front sheet rather than as a nineteenth tab - one front door, not two.
    r += 2
    ws.cell(row=r, column=1, value="Units, basis and formats - read before filling").font = h
    for line in _UNITS_AND_BASIS:
        r += 1
        ws.cell(row=r, column=2, value=line)

    # The project-identity block is written later by build_project_block at _META_START_ROW.
    # These two are written by different functions and had no shared constant between them,
    # which is the coupling _TOC_LEGEND_ROW already exists to prevent one row higher up.
    # Refuse rather than silently overwrite the user's project name.
    if r >= _META_START_ROW:
        raise RuntimeError(
            f"TOC instruction block now reaches row {r}, which collides with the "
            f"project-identity block at _META_START_ROW={_META_START_ROW}. Move "
            f"_META_START_ROW down; do not let the two overwrite each other."
        )

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 90
    ws.column_dimensions["C"].width = 60


def build_reference(wb) -> None:
    """Reference tab: the numpy/scipy + Pyodide requirements and the xlwings
    shell code as TEXT. Convenience copy only - the real pasteable distributable
    is generated by ``tools/make_qra_xlwings.py`` (byte-parity gated), so the two
    cannot silently drift (design brief section 4). openpyxl cannot write the
    xlwings Lite code into the add-in's own storage; it is pasted manually.
    """
    ws = wb.create_sheet("Reference (xlwings)")
    ws.sheet_properties.tabColor = TAB_REFERENCE
    title = Font(bold=True, size=13, color=HDR_FILL)
    h = Font(bold=True, size=11)
    mono = Font(name="Consolas", size=9)
    note = Font(italic=True, size=9, color="666666")

    ws["A1"] = "xlwings Lite - requirements & code (paste-once)"
    ws["A1"].font = title
    ws["A3"] = "Requirements (xlwings Lite -> Environment)"; ws["A3"].font = h
    for i, req in enumerate(("numpy", "scipy",
                             "Pyodide runtime: 314.0.1  (ratified Q4; do not float)"),
                            start=4):
        ws.cell(row=i, column=1, value=req).font = mono

    ws["A8"] = "How to load the model code"; ws["A8"].font = h
    ws["A9"] = ("Generate the pasteable script with  python tools/make_qra_xlwings.py"
                "  ->  dist/qra_xlwings_combined.py, then paste it into the xlwings "
                "Lite editor. That generated file is the source of truth (byte-parity "
                "gated to the repo engine); do not hand-edit. The text below is a "
                "human-readable convenience copy of the @script entry points only.")
    ws["A9"].font = note
    ws.row_dimensions[9].height = 60
    ws["A9"].alignment = Alignment(wrap_text=True, vertical="top")

    # Buttons: each @script appears as a runnable button in the xlwings Lite pane.
    ws["A11"] = "Buttons (xlwings Lite task pane - one per @script)"; ws["A11"].font = h
    buttons = [
        ("Run Simulation", "cost-QRA at the interactive count (Settings B1 / "
                            "Set_iterations, default 25,000)."),
        ("Run Simulation 100k", "cost-QRA at the on-demand 100,000 count "
                                "(Settings B5 / Set_iterations_max) - the deliverable run."),
        ("Validate Contract", "self-check the named-range contract + version + "
                              "methodology; writes PASS/FAIL to Out_validation."),
    ]
    r = 12
    for name, desc in buttons:
        ws.cell(row=r, column=1, value=name).font = Font(bold=True, name="Consolas", size=9)
        ws.cell(row=r, column=2, value=desc).font = note
        r += 1

    r += 1
    ws.cell(row=r, column=1,
            value="src/tier1_xlwings_shell.py (@script source - convenience copy)").font = h
    r += 1
    shell = (REPO_ROOT / "src" / "tier1_xlwings_shell.py").read_text(encoding="utf-8")
    for line in shell.splitlines():
        # Excel caps a cell at 32,767 chars; source lines are far shorter.
        ws.cell(row=r, column=1, value=line).font = mono
        r += 1
    ws.column_dimensions["A"].width = 110
    ws.column_dimensions["B"].width = 80


# ===========================================================================
# REG05-A1 - the client-ready finish (value-neutral). One regenerable pass baked
# into shared helpers so the empty template + the wind fixture cannot drift. Every
# helper sets number formats / styles / conditional formatting / tab colours / page
# setup / core properties / generated text ONLY - it never writes or moves a cell
# value, formula, or named range, so no engine number can move. apply_finish() runs
# BEFORE apply_protection() (protection is the last pass and preserves the finish's
# lock/unlock intent). openpyxl reads the same values from the restyled workbook.
# ===========================================================================

#: Number-format classes, resolved from RISK_HEADERS by header name (never positional).
_NUMFMT_DOLLAR = r"\$#,##0"   # escaped '$' - Excel's file-level validation rejects a
#: bare '$' in a stored format code (reads as an incomplete [$-...] currency-locale token)
#: and repairs the file on open; both Excel and LibreOffice canonicalise to \$#,##0.
_NUMFMT_PCT = "0%"
_NUMFMT_DAYS = "0.0"
_NUMFMT_COEFF = "0.00"
_COST_HEADERS = frozenset({"Optimistic ($)", "Most Likely ($)", "Pessimistic ($)",
                           "EMV_cost ($)", "EMV_sched_dollars ($)"})
_PCT_HEADERS = frozenset({"Probability", "Probability (Time)"})
_DAY_HEADERS = frozenset({"Optimistic (days)", "Most Likely (days)",
                          "Pessimistic (days)", "EMV_sched_days"})

#: Machine-read marker (item 4): an orthogonal thin border layered on the base class
#: for cells the Python model reads (Set_*, methodology coeffs, MC_day_rate, version,
#: the Grid_* input cells) - NOT a fifth colour.
_MACHINE_BORDER = Border(left=Side(style="thin", color="231EDC"),
                         right=Side(style="thin", color="231EDC"),
                         top=Side(style="thin", color="231EDC"),
                         bottom=Side(style="thin", color="231EDC"))

#: Role -> tab colour (item 6). Every sheet gets a colour; no uncoloured tabs.
_TAB_ROLE_COLOUR = {
    RISK_REGISTER_SHEET: TAB_REGISTER,
    "EMV & Mode Analysis": TAB_ANALYSIS,
    METHODOLOGY_SHEET: "8EA9DB", SETTINGS_SHEET: "8EA9DB", "MC_Params": "8EA9DB",
    SIMULATION_SHEET: "FCE4B6",
    MAPPING_SHEET: "A5A5A5", "Reference (xlwings)": "A5A5A5",
    PATTERNS_SHEET: "A5A5A5", ASSIGNMENTS_SHEET: "A5A5A5",
    CALIBRATION_SHEET: "A5A5A5", TREATMENTS_SHEET: "A5A5A5",
    "TOC & Instructions": "A5A5A5", LISTS_SHEET: "A5A5A5",
    "Layer1_Base": "C6E0B4", "Layer1_Factors": "C6E0B4",
    "Layer1_Allocation": "C6E0B4", "Layer1_Correlation": "C6E0B4",
}
_GRIDLINES_OFF = frozenset({"TOC & Instructions", "Reference (xlwings)", LISTS_SHEET})

#: Project-identity metadata block (item 2), placed on TOC & Instructions so no
#: Settings Set_* cell moves. (label, Set_* name, default).
_PROJECT_META = [
    ("Project name", "Set_ProjectName", ""),
    ("Project number", "Set_ProjectNumber", ""),
    ("Client", "Set_Client", ""),
    ("Prepared by", "Set_PreparedBy", ""),
    ("Revision", "Set_Revision", "A"),
    ("Issue date", "Set_IssueDate", ""),
]
#: A compact block low on the TOC, clear of the tab-list, the legend and the instruction
#: notes above it. Moved 44 -> 60 at 3c Part C when the run section (XLSX-01 BLOCK 1) was
#: added: the instructions now end near row 51, and build_toc REFUSES rather than overwrite
#: this block if it ever reaches it. The two are written by different functions, so the
#: guard is the only thing that ties them together.
_META_START_ROW = 60


def build_project_block(wb, project: dict | None = None):
    """Item 2/3.3: a project-identity block on TOC & Instructions (Set_Project*
    input cells) + workbook core properties. Additive; input class (blue, unlocked).
    ``project`` optionally seeds values (else blank for the user)."""
    project = project or {}
    ws = wb["TOC & Instructions"]
    ws.cell(row=_META_START_ROW, column=1, value="Project identity").font = Font(bold=True, size=11)
    for i, (label, name, default) in enumerate(_PROJECT_META, start=_META_START_ROW + 1):
        ws.cell(row=i, column=1, value=label).font = Font(bold=True)
        vc = ws.cell(row=i, column=2, value=project.get(name, default) or None)
        vc.font = INPUT_FONT
        _name(wb, name, f"'{ws.title}'!$B${i}")
    # Core workbook properties from the block.
    props = wb.properties
    props.title = project.get("Set_ProjectName") or "Cost-QRA Register"
    props.creator = project.get("Set_PreparedBy") or MAKER
    props.company = project.get("Set_Client") or ""
    # NB: do NOT set props.revision. Excel treats cp:revision as its numeric save-
    # counter and repairs the file on open if it is non-numeric (e.g. the engineering
    # revision letter "A"); the revision code lives in the Set_Revision cell above.
    return ws


def _apply_number_formats(wb) -> None:
    """Item 1: column-class number formats on the Risk Register + Methodology +
    Layer-1 correlation, resolved from RISK_HEADERS by name. Display-only."""
    rr = wb[RISK_REGISTER_SHEET]
    for c, header in enumerate(RISK_HEADERS, start=1):
        fmt = (_NUMFMT_DOLLAR if header in _COST_HEADERS else
               _NUMFMT_PCT if header in _PCT_HEADERS else
               _NUMFMT_DAYS if header in _DAY_HEADERS else None)
        if fmt is None:
            continue
        for row in rr.iter_rows(min_row=DATA_START_ROW, max_row=rr.max_row,
                                min_col=c, max_col=c):
            for cell in row:
                cell.number_format = fmt
    if METHODOLOGY_SHEET in wb.sheetnames:  # CG coeffs + mode mults -> 0.00
        ms = wb[METHODOLOGY_SHEET]
        for row in ms.iter_rows(min_row=2, max_row=ms.max_row, min_col=2, max_col=2):
            for cell in row:
                if isinstance(cell.value, (int, float)):
                    cell.number_format = _NUMFMT_COEFF
    if "Layer1_Correlation" in wb.sheetnames:
        cs = wb["Layer1_Correlation"]
        for row in cs.iter_rows(min_row=5, max_row=cs.max_row, min_col=2):
            for cell in row:
                if isinstance(cell.value, (int, float)):
                    cell.number_format = _NUMFMT_COEFF
    for label, mp_name in (("MC_day_rate", "MC_day_rate"),):  # day rate -> $#,##0
        if mp_name in wb.defined_names:
            for sh, coord in wb.defined_names[mp_name].destinations:
                wb[sh][coord].number_format = _NUMFMT_DOLLAR


def _mark_machine_read(wb) -> None:
    """Item 4: layer the thin machine-read border on the cells the Python model reads
    (Set_*, methodology coefficients + mode rows, MC_day_rate, version, and the
    Grid_* input cells). Orthogonal to the base class."""
    machine_names = [n for n in wb.defined_names
                     if n.startswith(("Set_", "Grid_")) or n in ("MC_day_rate",)]
    for name in machine_names:
        try:
            for sh, coord in wb.defined_names[name].destinations:
                region = wb[sh][coord]
                cells = ([region] if not isinstance(region, tuple)
                         else [c for row in region for c in row])
                for cell in cells:
                    cell.border = _MACHINE_BORDER
        except Exception:  # noqa: BLE001 - a malformed/absent name never blocks the finish
            continue


def _apply_tab_colours(wb) -> None:
    """Item 6: role tab colours on every sheet; gridlines off on presentation tabs."""
    for ws in wb.worksheets:
        ws.sheet_properties.tabColor = _TAB_ROLE_COLOUR.get(ws.title, "A5A5A5")
        if ws.title in _GRIDLINES_OFF:
            ws.sheet_view.showGridLines = False


def _apply_print_setup(wb) -> None:
    """Item 7: print setup on the key sheets (value-neutral page metadata)."""
    rr = wb[RISK_REGISTER_SHEET]
    rr.page_setup.orientation = "landscape"
    rr.page_setup.fitToWidth = 1
    rr.page_setup.fitToHeight = 0
    rr.sheet_properties.pageSetUpPr.fitToPage = True
    rr.print_title_rows = "3:4"
    rr.print_area = f"A1:{get_column_letter(LAST_RISK_COL)}{rr.max_row}"
    if "TOC & Instructions" in wb.sheetnames:
        wb["TOC & Instructions"].page_setup.orientation = "portrait"
    if "EMV & Mode Analysis" in wb.sheetnames:
        wb["EMV & Mode Analysis"].page_setup.orientation = "landscape"


def _style_correlation_matrix(wb) -> None:
    """Items 8/9: Layer1_Correlation header/label styling + heatmap colour-scale over
    the lower triangle. Formatting-only."""
    if "Layer1_Correlation" not in wb.sheetnames:
        return
    cs = wb["Layer1_Correlation"]
    header_row = next((r for r in range(1, cs.max_row + 1)
                       if str(cs.cell(row=r, column=1).value or "").strip().lower() == "factor"), 4)
    # Count factors from the EXISTING header-row cells (cs[header_row] never
    # materialises cells past the extent - a cs.cell() probe past the data would
    # add an empty column and desync the extent-sized Grid_Layer1_Correlation).
    k = len([c.value for c in cs[header_row][1:] if c.value is not None])
    hdr_fill = PatternFill("solid", fgColor="DDEBF7")
    for c in range(1, 2 + k):  # header row bold + filled
        cell = cs.cell(row=header_row, column=c)
        cell.fill = hdr_fill
        cell.font = Font(bold=True)
    for i in range(k):  # label column bold + filled; diagonal shaded
        cs.cell(row=header_row + 1 + i, column=1).fill = hdr_fill
        cs.cell(row=header_row + 1 + i, column=1).font = Font(bold=True)
        cs.cell(row=header_row + 1 + i, column=2 + i).fill = PatternFill("solid", fgColor="F2F2F2")
    if k >= 2:  # heatmap over the lower triangle
        first, last = header_row + 1, header_row + k
        rng = f"B{first}:{get_column_letter(1 + k)}{last}"
        cs.conditional_formatting.add(rng, ColorScaleRule(
            start_type="num", start_value=0, start_color="FFFFFFFF",
            end_type="num", end_value=1, end_color="FF5B9BD5"))
        cs.print_area = f"A{header_row}:{get_column_letter(1 + k)}{last}"


def _apply_autofilter_widths_blank_cf(wb) -> None:
    """Items 9/10: Risk Register autofilter (already themed) + blank-required-input
    conditional format (MC-included rows missing a distribution or three-point)."""
    rr = wb[RISK_REGISTER_SHEET]
    idx = {h: i + 1 for i, h in enumerate(RISK_HEADERS)}
    mc, dist = idx["MC Include"], idx["Distribution"]
    last = rr.max_row
    dist_col = get_column_letter(dist)
    mc_col = get_column_letter(mc)
    # highlight a blank Distribution on an MC-included row (formula CF, no data written)
    rr.conditional_formatting.add(
        f"{dist_col}{DATA_START_ROW}:{dist_col}{last}",
        FormulaRule(
            formula=[f'AND(${mc_col}{DATA_START_ROW}="Yes",{dist_col}{DATA_START_ROW}="")'],
            # CF dxf fill: set BOTH colours (start->fgColor, end->bgColor) - the
            # canonical openpyxl CF idiom. A solid dxf fill with only fgColor is
            # malformed and triggers Excel's "recover content" repair on open.
            fill=PatternFill(start_color="FFFFC7CE", end_color="FFFFC7CE", fill_type="solid")))


#: Role -> one-line description for the generated TOC tab-list (item 3).
#: REGUX-01 A-1. Modelled on the README sheet of the Tropic Ridge factor model, which the template
#: lost when it was generalised (stage 4 F-10). Every sentence is either a register convention the
#: parsers enforce (see src/register_field_spec.py) or a rule METHODOLOGY.md states; nothing here
#: is a methodology choice of its own.
_UNITS_AND_BASIS = (
    "UNITS. Risk Register costs are dollars ($); time is working days. Probability and "
    "Probability (Time) are FRACTIONS between 0 and 1: 0.45 means 45%, and entering 45 makes the "
    "risk fire on every iteration, silently. Layer-1 base values and Declared_Total are $M.",
    "BASIS. Every figure is contingency at base date, before escalation. Escalation (GN4) is "
    "applied downstream to reach an outturn figure, never in this workbook.",
    "THREE-POINT INPUTS. Optimistic / Most Likely / Pessimistic are read by the Distribution "
    "column. Triangular and PERT treat Optimistic and Pessimistic as absolute bounds. Lognormal "
    "treats them as roughly P10 and P90 with a tail beyond Pessimistic, and Most Likely as the "
    "median. Binary fires the Most Likely value; Binary/PERT draws a PERT when it fires. The "
    "time three-points follow the same rule, in working days.",
    "COMPOSITION. Each iteration fires each risk with MC Include = Yes against its Probability "
    "and sums the sampled costs - MC Include is the switch, not Risk Status. A Time Impact = Yes "
    "risk shares one severity draw between its cost and its delay, so the two move together. "
    "When Layer 1 is on, each base cell is multiplied by (1 + factor) for every factor bound to "
    "it (rows via Layer1_Allocation, columns via Column_Scope) - the factor three-points are "
    "proportional deltas, 0.05 meaning +5% - and the result is added to the event total.",
    "RECORDED, NOT READ. Effectiveness_Confidence, Default_Mapping_Confidence and "
    "Assignment_Confidence are kept for a reviewer and never used by the engine: any scale, or "
    "blank.",
    "WHERE THE REST IS. Each fillable sheet carries its notes above its headers and each "
    "column's format on its header cell (hover). How to run: 'Running a simulation' above. "
    "What the colours mean: the legend above.",
)

#: The order a person fills the workbook in (part 3: the TOC list in fill order). Sheets not named
#: here are appended in inventory order, so a new sheet cannot fall off the list.
_TOC_FILL_ORDER = (
    "MC_Params", LISTS_SHEET, RISK_REGISTER_SHEET, MAPPING_SHEET, PATTERNS_SHEET,
    ASSIGNMENTS_SHEET, TREATMENTS_SHEET, METHODOLOGY_SHEET, SETTINGS_SHEET,
    "Layer1_Base", "Layer1_Factors", "Layer1_Allocation", "Layer1_Correlation",
    CALIBRATION_SHEET, "EMV & Mode Analysis", SIMULATION_SHEET, "Reference (xlwings)",
)
#: Who writes each sheet - the third column of the tab list.
_TOC_KIND = {
    CALIBRATION_SHEET: "calculated", "EMV & Mode Analysis": "calculated",
    SIMULATION_SHEET: "model writes", "Reference (xlwings)": "reference",
}

_TOC_ROLE_DESC = {
    RISK_REGISTER_SHEET: "Event risks - cost + schedule three-point inputs, EMV.",
    METHODOLOGY_SHEET: "CG correlation coefficients + Mode multipliers.",
    SETTINGS_SHEET: "Run settings (iterations/seed/view/prefix); the LIVE run-config surface.",
    SIMULATION_SHEET: "Model write-back: P-curve, S-curve, convergence.",
    MAPPING_SHEET: "P6/CPM binding for schedule (Time=Yes) risks.",
    # "(workshop output)" once sat on all four of these, Summary included - and Summary is four
    # live formulas (stage 4 F-9). The three that ARE typed say so; the one that is not says so.
    PATTERNS_SHEET: "Schedule risk-to-activity patterns - workshop input, you fill this.",
    ASSIGNMENTS_SHEET: "Per-risk pattern assignment - workshop input, you fill this.",
    CALIBRATION_SHEET: "SRA calibration comparators 1 and 2 - CALCULATED from the register, do not type.",
    TREATMENTS_SHEET: "Per-risk treatments + effectiveness - workshop input, you fill this.",
    # XLSX-01 WARN, sharpened into a contradiction by Part C's run section and caught at
    # the Claude-in-Excel read-back: the old text ("Legacy VBA config surface") told a
    # generalist to ignore the tab that STEP 2 sends them to for the day rate, and that
    # MC_day_rate -> MC_Params!$C$11 feeds Summary, the register's AD column and the EMV
    # tab. Following the tab list left every schedule-dollar figure at zero, forever.
    "MC_Params": ("Engine run parameters: day rate, programme seasons, CP threshold, TIC. "
                  "Fill the day rate or schedule-dollar figures stay zero. "
                  "Settings holds iterations/seed/view."),
    LISTS_SHEET: "Cascade lists - edit here; the dropdowns follow.",
    "Reference (xlwings)": "xlwings requirements + @script (paste-once).",
    "EMV & Mode Analysis": "Deterministic Layer-1 EMV + Mode charts.",
    "Layer1_Base": "Layer-1 base estimate matrix.",
    "Layer1_Factors": "Layer-1 risk factors.",
    "Layer1_Allocation": "Layer-1 factor x WBS allocation.",
    "Layer1_Correlation": "Layer-1 factor correlation matrix.",
}


def _generate_toc_tablist(wb) -> None:
    """Item 3: rewrite the TOC tab-list from the actual sheet inventory (order incl.
    Lists/MC_Params/Reference/Layer-1 when present). Fills the reserved rows 5-20."""
    ws = wb["TOC & Instructions"]
    inventory = [sh for sh in wb.worksheets if sh.title != "TOC & Instructions"]
    # Fail closed. SRA-02 S-B took the inventory to 17, which fills rows 5-21 and
    # leaves exactly one spare row before the legend. Silently writing over the
    # legend header is the failure this refuses: the 18th sheet stops the build.
    capacity = _TOC_LEGEND_ROW - _TOC_TABLIST_FIRST_ROW
    if len(inventory) > capacity:
        raise ValueError(
            f"TOC tab-list overflow: {len(inventory)} sheets need "
            f"{len(inventory)} rows from {_TOC_TABLIST_FIRST_ROW}, but only "
            f"{capacity} are reserved before the legend at row {_TOC_LEGEND_ROW}. "
            "Move _TOC_LEGEND_ROW (and the build_toc blocks below it) down."
        )
    for rr in range(_TOC_TABLIST_FIRST_ROW, _TOC_LEGEND_ROW):
        for cc in (1, 2, 3):
            ws.cell(row=rr, column=cc).value = None
    # part 3: in the order a person fills them, with who writes each - a list in build order sent
    # the analyst to Simulation before Mapping and called Summary a workshop output.
    rank = {name: i for i, name in enumerate(_TOC_FILL_ORDER)}
    ordered = sorted(inventory, key=lambda sh: (rank.get(sh.title, len(rank)), inventory.index(sh)))
    r = _TOC_TABLIST_FIRST_ROW
    for sh in ordered:
        ws.cell(row=r, column=1, value=sh.title).font = Font(bold=True)
        ws.cell(row=r, column=2, value=_TOC_ROLE_DESC.get(sh.title, ""))
        ws.cell(row=r, column=3, value=_TOC_KIND.get(sh.title, "you fill")).font = _NOTE_FONT
        r += 1


def _apply_input_classes(wb) -> None:
    """Items 4/5: the single-class-map escapee - blue INPUT class on Risk Register
    cols 1-3 (Risk ID/Status/Description, which S1's style_register_input_cells skips).

    This used to blue every Layer-1 cell from row 2 down as well, which made the trailer
    labels and the PSD row blue-but-locked and could not express a lower triangle. The
    Layer-1 styling is ``build_layer1_sheets``'s own now (REGUX-01 A-0.4)."""
    rr = wb[RISK_REGISTER_SHEET]
    for row in rr.iter_rows(min_row=DATA_START_ROW, max_row=rr.max_row, min_col=1, max_col=3):
        for cell in row:
            cell.font = INPUT_FONT


def apply_finish(wb, project: dict | None = None) -> None:
    """REG05-A1: the value-neutral client-ready finish. Idempotent; sets formatting /
    metadata / generated text only. Call BEFORE apply_protection()."""
    build_project_block(wb, project)
    _generate_toc_tablist(wb)
    # Drive the analysis-sheet title from Set_ProjectName (retire the hardcoded literal).
    if "EMV & Mode Analysis" in wb.sheetnames:
        name = (project or {}).get("Set_ProjectName") or "this project"
        wb["EMV & Mode Analysis"]["A1"] = f"EMV & Mode Analysis - {name}"
    _apply_number_formats(wb)
    _apply_input_classes(wb)      # base input class on the escapees (before matrix styling)
    _apply_tab_colours(wb)
    _apply_print_setup(wb)
    _style_correlation_matrix(wb)  # matrix header/label styling wins over input class
    _apply_autofilter_widths_blank_cf(wb)
    _mark_machine_read(wb)         # machine-read marker LAST (borders layer over base class)


# ===========================================================================
# REG04 - contract hardening (sheet + workbook protection).
# Defense-in-depth against accidental edits / row-insertion into a grid / sheet
# deletion. Protection is EXCEL-RUNTIME ONLY: openpyxl (the engine read, the
# scaffolder, resize_layer1_correlation, the Validate button) reads AND writes cell
# values regardless of the flags, so bit-identity is untouched. Cells default to
# locked=True, so we UNLOCK the input ranges then enable protection; everything else
# locks by default. Out_* stay UNLOCKED (Director ruling 3a, option a) so the xlwings
# @script write-back succeeds on the protected Simulation sheet. NO password (an
# anti-fat-finger guardrail, not a security control). LIMIT: this does NOT prevent
# named-range deletion (Excel keeps names editable) - the Validate button is the
# backstop for that class; stated on the TOC.
# ===========================================================================

#: Per-sheet input ranges to UNLOCK before enabling protection. Sheets absent from
#: this map (Mapping, TOC, Reference, EMV & Mode Analysis) protect fully (machine).
_UNLOCK_RANGES = {
    RISK_REGISTER_SHEET: ["A5:AA1000", "AE5:AE1000"],  # cols 1-27 + 31 (activity);
                                                       # rows 3-4 + EMV cols AB:AD lock
    # Methodology unlocks BY STYLE (_UNLOCK_BY_STYLE) since F-30: the settings rows are inputs
    # a specialist types (the Director's 08/09 ruling on the tie band settles REGUX-01 decision 1
    # the same way for the four tolerances beside it); the mode multipliers stay black and locked.
    SETTINGS_SHEET: ["B1:B5", "B8"],                   # run settings + Layer-1 flag
                                                       # (B6 version / B7 pin lock)
    SIMULATION_SHEET: ["A2:B20", "D2:E102", "H1", "H3:H4", "I2:L20", "N2:N3"],  # Out_*
    # Nine sheets are absent on purpose - the four Layer1_* grids, the four list sheets and Lists:
    # they unlock BY STYLE (_UNLOCK_BY_STYLE). A range cannot express a lower triangle (A-0.4),
    # and it cannot leave a note block above a header locked while the body below is open (part 3).
    # REGUX-01: the six sheets below were absent from this table, so `apply_protection` locked
    # them whole. Four are named deliverables the TOC tells an analyst to fill; `MC_Params!C11`
    # is the day rate the TOC instructs twice; `TOC!B61:B66` is the project identity - the very
    # first thing anyone types, and the first thing that refused.
    "MC_Params": ["C2:C60"],                       # the value column beside the B labels
    "TOC & Instructions": ["B61:B66"],                            # project name/number/client/prepared/rev/date
}
#: REGUX-01 A-0.1, realised on the four Layer-1 sheets: a cell is unlocked if and only if its
#: font is ``INPUT_FONT``. One rule instead of a range table, and the only way to unlock a lower
#: triangle without unlocking the rectangle around it. Not yet every sheet: ``Simulation`` is
#: unlocked amber by design (the write-back cells do not exist until the script runs) and
#: ``Lists`` unlocks its cascade values black, so the biconditional does not hold there;
#: generalising it is A-0.1's owed remainder. Held by tests/test_regux01_layer1_shape.py.
_UNLOCK_BY_STYLE = frozenset(
    ("Layer1_Base", "Layer1_Factors", "Layer1_Allocation", "Layer1_Correlation",
     # part 3: the note block above a list sheet's header must stay locked while the blue body
     # below it opens, and the Lists headroom is exactly the blue cells.
     MAPPING_SHEET, PATTERNS_SHEET, ASSIGNMENTS_SHEET, TREATMENTS_SHEET, LISTS_SHEET,
     METHODOLOGY_SHEET))   # F-30: the settings rows are inputs; the mode multipliers are not
#: Sheets that allow row insertion under protection (the add-risk-row workflow).
# _ALLOW_INSERT_ROWS retired at 3c Part C-2: superseded by _PERMITTED, which states the
# permission in the sense the OOXML flag actually carries. See _permit.


#: Sheets that ship as a header row over blank space, and the last column of that header.
#: They are filled by hand and were **entirely locked** as shipped: `_UNLOCK_RANGES` never
#: named them, so `apply_protection` had nothing to unlock (REGUX-01, CiE finding 1). Styling
#: a body here is not decoration - `_unlock` clamps to the sheet extent, so a header-only
#: sheet clamps to nothing and cannot be unlocked at all until the rows exist.
_LIST_INPUT_SHEETS: dict[str, str] = {
    "Mapping": "F",
    "Risk_Activity_Patterns": "H",
    "Risk_Pattern_Assignments": "D",
    "Treatments": "D",
}


def style_list_sheet_body(ws, last_col_letter: str, n_rows: int, header_row: int = 1) -> None:
    """Make a header-only input sheet read AND behave as a form.

    Part 2a gave these sheets a blue-font body, which made them *fillable* - the blue font is the
    workbook's own "you fill this in" signal, and the protection pass keys off it. The Excel
    verification pass then found that fillable was only half of it: *"they still look like scratch
    sheets: header row is not bold, no fill, no freeze pane, no table, no filter dropdowns, and
    used range still reports just row 1"*. A user landed on an unstyled line of text with no cue
    that the rows below were theirs.

    So this also applies the Risk Register's own header treatment (one visual language, not two),
    freezes the header, and lays a real Excel **Table** over the block. The Table is what makes the
    fill boundary *visible* - Excel does not report these rows as used, because the cells carry
    style and no value - and it is what carries the filter. Its sheet must permit `autoFilter`, or
    the dropdowns render and refuse; that pairing is why REGUX-01 put Tables here rather than in a
    later part.

    ``header_row`` (part 3) is where the header actually sits once a note block has been written
    above it; the readers find it by scanning column A, the Table and the freeze follow it here.
    """
    last_col = column_index_from_string(last_col_letter)
    last_row = header_row + n_rows

    hdr_fill = PatternFill("solid", fgColor=HDR_FILL)
    hdr_font = Font(bold=True, color="FFFFFF", size=10)
    for cc in range(1, last_col + 1):
        cell = ws.cell(row=header_row, column=cc)
        cell.font = hdr_font
        cell.fill = hdr_fill
    for rr in range(header_row + 1, last_row + 1):
        for cc in range(1, last_col + 1):
            ws.cell(row=rr, column=cc).font = INPUT_FONT

    ws.freeze_panes = f"A{header_row + 1}"

    # A Table needs a workbook-unique name with no spaces; the sheet titles already qualify
    # except for the space in "Risk Register", which is not one of these sheets.
    table = Table(displayName=f"tbl{ws.title.replace(' ', '')}",
                  ref=f"A{header_row}:{last_col_letter}{last_row}")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleLight9", showRowStripes=True, showColumnStripes=False,
        showFirstColumn=False, showLastColumn=False)
    ws.add_table(table)


#: The note voice: italic, small, grey - the TOC's own, so a note reads as a note everywhere.
_NOTE_FONT = Font(italic=True, size=9, color="666666")


def write_note_block(ws) -> int:
    """REGUX-01 A-2: what this sheet is for, and every column's format, ABOVE the headers, where
    the eye is - a README the filler has already scrolled past does not help on `Treatments`.

    The lines come from ``src.register_field_spec`` (part 1), the one place a column's meaning is
    stated and the one the drift test holds against the parsers; nothing is worded here. Rows are
    inserted before any Table, validation or name exists on the sheet, and every reader of these
    sheets finds its header by scanning column A (``strawman_reader._find_header_row``, 20 rows),
    which the brief measured before promising this. Returns the header row.
    """
    sheet = ws.title
    lines = [
        f"{_TOC_ROLE_DESC.get(sheet, sheet)} Blue cells are yours. The header row is the "
        f"contract and is locked; hover a header for its format. Units and basis: TOC & Instructions.",
        *note_lines(sheet),
    ]
    n = len(lines) + 1                      # plus one blank spacer row above the header
    ws.insert_rows(1, amount=n)
    for i, line in enumerate(lines, start=1):
        ws.cell(row=i, column=1, value=line).font = _NOTE_FONT
    return n + 1


def _table_header_row(ws) -> int:
    """The row a sheet's (single) Table starts on, from the Table's own ref."""
    (table,) = ws.tables.values()
    return int("".join(ch for ch in table.ref.split(":")[0] if ch.isdigit()))


def _add_header_comments(wb) -> None:
    """REGUX-01 A-3: every specified column's format on its header cell, as a note a filler sees
    by hovering. The Risk Register's header row is the contract (row 4) and cannot take a note
    block above it, so for that sheet this is the per-column guidance; on the list sheets it
    doubles the note block, for the filler who has scrolled the block off the top."""
    for sheet in FILLABLE_SHEETS:
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        hdr_row = HEADER_ROW if sheet == RISK_REGISTER_SHEET else _table_header_row(ws)
        by_text = {str(c.value).strip(): c for c in ws[hdr_row] if c.value is not None}
        for spec in specs_for(sheet):
            cell = by_text.get(spec.column)
            if cell is None:
                raise ValueError(f"{sheet}: the field spec names {spec.column!r}, which is not "
                                 f"in header row {hdr_row}")
            text = spec.guidance
            if spec.legal_values:
                text += f" One of: {', '.join(spec.legal_values)}."
            if spec.blank_means:
                text += f" Blank = {spec.blank_means}."
            note = Comment(text, "register_scaffold")
            note.width, note.height = 420, 170
            cell.comment = note


def _write_register_guidance(ws) -> None:
    """A-2 for the Risk Register. Its header is row 4 by contract (``HEADER_ROW``), so the two
    rows above the section band carry the sheet's note instead of a block."""
    taken = [ref for ref in ("A1", "A2") if ws[ref].value is not None]
    if taken:
        raise ValueError(f"Risk Register {taken} not free for the guidance lines")
    ws["A1"] = ("Blue cells from row 5 are yours; black cells are labels or live formulas. Hover a "
                "column header for its format. Units, basis and the three-point conventions are "
                "on TOC & Instructions.")
    ws["A2"] = ("Probability is a FRACTION (0.45 = 45%). Costs are dollars, time is working days, "
                "both contingency at base date before escalation. Time Impact = Yes rows need a "
                "Mode and a Mapping row.")
    ws["A1"].font = _NOTE_FONT
    ws["A2"].font = _NOTE_FONT


#: REGUX-01 §5.3, ruled 07/09: the sheets nobody fills say so in one line, because silence on an
#: output sheet is what produced F-9 (Summary, labelled "workshop output", is four live formulas).
#: Cells are chosen outside every Out_* range and off the readers' label walks.
_BANNERS = {
    SIMULATION_SHEET: ("A22", "MODEL-WRITTEN - do not type on this sheet. Every cell here is "
                              "overwritten on each run."),
    CALIBRATION_SHEET: ("D1", "CALCULATED - live formulas over the Risk Register (the SRA "
                              "calibration comparators). Do not type; edit the register."),
    "EMV & Mode Analysis": ("A3", "DERIVED - populated from the register's EMV columns whenever "
                                  "it is filled or a run happens. Do not type."),
    "Reference (xlwings)": ("A2", "REFERENCE - the paste-once script and its requirements. "
                                  "Nothing to fill."),
}


def _write_banners(wb) -> None:
    for sheet, (cell, text) in _BANNERS.items():
        if sheet not in wb.sheetnames:
            continue
        c = wb[sheet][cell]
        if c.value is not None:   # a layout change put something live here; never overwrite it
            raise ValueError(f"{sheet}!{cell} is not free for the banner: {c.value!r}")
        c.value = text
        c.font = Font(bold=True, size=9)
        if sheet == SIMULATION_SHEET:
            c.fill = PYTHON_FILL


#: Rows of headroom below the seeded cascade lists (part 3, "Lists headroom"). The unlock used to
#: stop at the foot of each seeded block, so a project could not add a package or a factor.
_LISTS_HEADROOM_LAST_ROW = 60


def _add_headroom_and_freezes(wb) -> None:
    """Part 3's remaining formatting: styled (and therefore unlocked) headroom under every cascade
    list, and frozen header rows / label columns on the matrix sheets."""
    ls = wb[LISTS_SHEET]
    for col, _name, _dv, _seeds in LIST_SPECS:
        for rr in range(3, _LISTS_HEADROOM_LAST_ROW + 1):
            ls[f"{col}{rr}"].font = INPUT_FONT
    ls.freeze_panes = "A3"
    for sheet, pane in (("Layer1_Base", "B2"), ("Layer1_Allocation", "B2"),
                        ("Layer1_Correlation", "B5")):
        if sheet in wb.sheetnames:
            wb[sheet].freeze_panes = pane



def _unlock(ws, rng: str, clamp: bool = True) -> None:
    """Unlock an input range. When ``clamp`` (the default, for grid sheets), clamp to
    the sheet's actual extent so we never materialise cells past the data - which would
    grow the sheet. ``clamp=False`` (Simulation) unlocks the FULL range so the ``@script``
    can write the ``Out_*`` cells even before they exist.

    This used to add "Future rows the user inserts inherit unlocked", which was false twice
    over (3c Part C, Director read-back): the clamp stops the unlock at the data extent, so
    there are no unlocked rows below to inherit from - and it would not matter if there were,
    because a user cannot insert a row here at all while the EMV columns are locked. Measured,
    not reasoned: unlocking 20 and 956 rows below the data changed nothing.

    The other half of the old claim - that unclamping would "desync the row-1-anchored,
    extent-sized ``Grid_*`` ranges" - was also measured and does not hold: ``Grid_RiskRegister``
    stays ``$A$1:$AE$44`` unclamped. The real cost of unclamping is file size (43 KB to 95 KB),
    which is reason enough to keep the clamp, but it is not the reason the docstring gave."""
    from openpyxl.utils.cell import range_boundaries
    c1, r1, c2, r2 = range_boundaries(rng)
    if clamp:
        r2 = min(r2, ws.max_row or r1)
        c2 = min(c2, ws.max_column or c1)
    if r2 < r1 or c2 < c1:
        return
    for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2):
        for cell in row:
            cell.protection = UNLOCKED


def _unlock_by_style(ws) -> None:
    """Unlock exactly the ``INPUT_FONT`` cells of ``ws`` - see ``_UNLOCK_BY_STYLE``. Iterates
    only existing cells, so it never materialises a cell past the data extent."""
    want = INPUT_FONT.color.rgb
    for cell in list(ws._cells.values()):
        colour = cell.font.color.rgb if (cell.font is not None and cell.font.color is not None) else None
        if colour == want:
            cell.protection = UNLOCKED


def _blank_empty_string_cells(wb) -> None:
    """Normalise ``""``-valued cells to ``None`` before save.

    openpyxl 3.1.x writes strings inline; an empty-string cell serialises to the
    malformed ``<c t="inlineStr"></c>`` (a string-typed cell with no ``<is>``
    child), which Excel flags as a file-level error and offers to repair on open.
    Several call sites legitimately write ``""`` (blank source lines in the
    Reference sheet, blank register/Layer-1 cells in the fixture). Blanking them to
    ``None`` yields a valid empty cell (``<c s=".."/>``). Value-neutral: the engine
    read treats ``""`` and ``None`` identically (both = no data). Iterates ONLY
    existing cells (``ws._cells``) so it never materialises a cell past the data
    extent - which would grow the sheet and desync the extent-sized ``Grid_*``
    ranges. Run LAST, after every value write."""
    for ws in wb.worksheets:
        for cell in list(ws._cells.values()):
            if cell.value == "":
                cell.value = None


#: Actions the generalist may take on a protected sheet, per sheet (3c Part C-2, Director
#: 04/09/2026). XLSX-01 BLOCK 4: sorting and filtering were blocked, which made a register
#: the user could not order by package or narrow by status, and the only way to get either
#: was Review > Unprotect Sheet - which turns off every other guard at the same time. So the
#: protection that was meant to defend the contract was the reason a user would remove it.
#:
#: ``autoFilter`` permits USING an existing filter, not creating one; the Risk Register
#: already carries an autofilter over its header row, so unprotecting it is enough.
#:
#: **``insertRows`` is deliberately NOT here, and that is a finding rather than an omission.**
#: It was granted at C-2 and withdrawn the same day, when the Director tried it in Excel and it
#: did nothing. The flag was right (`insertRows="0"` does mean permitted); the sheet cannot
#: honour it. Excel inserts a WHOLE row, and every data row carries locked cells at AB, AC and
#: AD - the EMV formula columns, locked by design as calc cells - plus everything from AF out.
#: An insert would displace them, so Excel refuses. Tested against unlocked headroom of 0, 20
#: and 956 rows below the data: refused in all three, because the obstruction is across the
#: row, not below it. Making it work would mean unlocking the EMV formulas, which is the one
#: thing the protection exists to prevent.
#:
#: So row insertion and this protection model are incompatible, and granting the flag would
#: advertise a capability the workbook does not have - the same defect as the
#: ``_ALLOW_INSERT_ROWS`` constant this dict replaced, in the opposite direction. Adding a row
#: is Review > Unprotect Sheet, which is a specialist's step (R-8), or a regeneration at a
#: higher count.
#:
#: The 40-row cap is NOT here: it is ``build_template``'s ``n_blank_input_rows`` default, and
#: a larger register is a regeneration at a higher count - see docs/run-recipes.md. The
#: shipped default stays 40 so no register grows without someone choosing it.
_PERMITTED: dict[str, tuple[str, ...]] = {
    RISK_REGISTER_SHEET: ("sort", "autoFilter"),
    # REGUX-01 part 2b. The Excel verification pass found sort and filter REFUSED on all four of
    # these: `allowSort` and `allowAutoFilter` were false and there was no Table to use. Both
    # halves were needed - the permission alone permits USING a filter that does not exist, and a
    # Table without the permission renders dropdowns that refuse. `insertRows` is deliberately NOT
    # granted: it fails on the Risk Register because locked EMV columns sit across every row, and
    # although these sheets have no such columns, the precedent is that Excel decides, not the
    # flag. Ask Excel first, then grant it.
    # REGUX-01 A-0.6, 08/09/2026: insertRows GRANTED on the five Table sheets, and only there. The
    # obstruction that defeats it on the Risk Register - locked formula cells across every row - does
    # not exist on these sheets, and Excel was asked before the flag was kept: with the flag, a whole
    # row inserts inside the Table under protection; without it, Excel refuses (both measured by
    # scripts/ask_excel_register.py, whose insert probe expects whatever the sheet's flag says).
    **{sheet: ("sort", "autoFilter", "insertRows") for sheet in _LIST_INPUT_SHEETS},
    # REGUX-01 A-0.4 / §5.4: the fifth list-shaped sheet, given its Table in build_template.
    "Layer1_Factors": ("sort", "autoFilter", "insertRows"),
}


def _permit(ws, *actions: str) -> None:
    """Allow ``actions`` on an otherwise protected sheet.

    **The flag sense is inverted, and reading it backwards is a real defect this repo has
    already made.** In OOXML ``sheetProtection@sort="1"`` means sorting is LOCKED, and
    openpyxl's ``SheetProtection`` defaults every one of these to ``True``. The previous code
    read ``ws.protection.insertRows = True`` for the one sheet meant to permit insertion -
    setting the value that forbids it, to what it already was, so the branch was inert and
    said the opposite of what it did (found at 3c Part C while measuring XLSX-01 BLOCK 4).

    Permitting is therefore setting the flag to ``False``, and this function exists so that
    is written once, with the reason, instead of at each call site.
    """
    for action in actions:
        if not hasattr(ws.protection, action):
            raise AttributeError(
                f"{action!r} is not a SheetProtection flag; a typo here would silently "
                f"permit nothing")
        setattr(ws.protection, action, False)


def apply_protection(wb) -> None:
    """REG04 Scope A: unlock the input ranges, then enable sheet protection on every
    sheet + workbook-structure protection. Run LAST (after all cells exist). No
    password. Value-neutral (Excel-runtime only, plus ``""``->``None`` blank
    normalisation so Excel does not repair empty inline-string cells on open)."""
    _blank_empty_string_cells(wb)
    for ws in wb.worksheets:
        # Simulation's Out_* write-back cells must unlock over their FULL named-range
        # extent (they don't exist until the script writes them); every other sheet
        # clamps to its data extent to keep the extent-sized Grid_* ranges in sync.
        clamp = ws.title != SIMULATION_SHEET
        for rng in _UNLOCK_RANGES.get(ws.title, []):
            _unlock(ws, rng, clamp=clamp)
        if ws.title in _UNLOCK_BY_STYLE:
            _unlock_by_style(ws)
        ws.protection.sheet = True
        _permit(ws, *_PERMITTED.get(ws.title, ()))
    wb.security = WorkbookProtection(lockStructure=True)


# ===========================================================================
# The empty template assembler
# ===========================================================================

def build_template(path: Path, *, prefix: str = "RSK",
                   n_blank_input_rows: int = 40,
                   n_layer1_wbs_rows: int = _N_LAYER1_WBS_ROWS,
                   n_layer1_factors: int = _N_LAYER1_FACTORS) -> Path:
    """Emit an EMPTY, contract-correct register template to ``path``.

    Structure + names + styling + dropdowns + methodology defaults + P6-ready
    columns + TOC + reference; NO project data. Layer 1 ships OFF, and its four grids
    ship at their real shape, blank (REGUX-01 A-0.4 - before it they were header rows
    only, and the TOC's fill procedure could not be followed at step 1). Reads to a nil
    result (zero risks), never a crash.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = RISK_REGISTER_SHEET

    write_risk_header_rows(ws)
    theme_risk_register(ws, n_blank_input_rows)
    last_input = DATA_START_ROW + n_blank_input_rows - 1
    # S3a: the cascade Lists sheet + List_* names must exist before the dropdowns
    # that reference them.
    build_lists_sheet(wb)
    add_dropdowns(ws, DATA_START_ROW, last_input)
    style_register_input_cells(ws, DATA_START_ROW, last_input)
    # S2: live EMV formulas pre-filled down the input block (blank rows -> 0/blank).
    write_emv_formulas(ws, DATA_START_ROW, last_input)
    # A default Set_risk_prefix follows the caller's prefix on the empty template.
    build_mapping_sheet(wb)
    # SRA-02 S-B: the four schedule/workshop tabs. S-E: Summary's value cells are
    # live formulas over the same input block the EMV columns cover.
    build_schedule_surface(wb, DATA_START_ROW, last_input)
    mc = build_mc_params_sheet(wb, values=None)
    # REG05-A2 §3.3: the generic analysis sheet + §3.1 present-but-empty Layer-1
    # (Set_Layer1_Enabled ships FALSE, so the empty Layer-1 is a read no-op).
    # REG05-A2-FIX D2: ship Layer1_Correlation BARE (no seeded factors) so all four
    # Layer-1 tabs come out empty-and-consistent - a seeded correlation declared 7
    # factors defined nowhere, throwing on flag TRUE with no user input. The
    # List_Factor dropdowns stay (build_layer1_sheets adds them) so the user still
    # picks factors from the cascade when filling.
    build_emv_mode_analysis(wb, DATA_START_ROW, last_input)
    build_layer1_sheets(wb, n_wbs_rows=n_layer1_wbs_rows, n_factor_rows=n_layer1_factors)
    build_methodology_sheet(wb, cg_values=None)   # CG defaults 0.5
    build_settings_and_simulation(wb)   # incl. Set_Layer1_Enabled = FALSE
    name_day_rate(wb, mc)   # MC_day_rate -> EMV_sched_dollars references it
    if prefix:
        wb[SETTINGS_SHEET]["B4"] = prefix
    build_toc(wb)
    build_reference(wb)
    # REGUX-01: give the header-only input sheets a body BEFORE names and protection. They are
    # filled by hand and shipped entirely locked, because `_unlock` clamps to the sheet extent
    # and a header row clamps to nothing. Styling first materialises the rows, so the unlock
    # ranges added alongside actually reach them.
    for _sheet, _last_col in _LIST_INPUT_SHEETS.items():
        if _sheet in wb.sheetnames:
            _hdr = write_note_block(wb[_sheet])        # part 3, A-2: the notes above the header
            style_list_sheet_body(wb[_sheet], _last_col, n_blank_input_rows, header_row=_hdr)
    # REGUX-01 A-0.4 / §5.4: Layer1_Factors is the fifth list-shaped sheet. Its body is
    # already blue from build_layer1_sheets; this lays the Table over it and treats the header.
    style_list_sheet_body(wb["Layer1_Factors"], "F", n_layer1_factors)
    # part 3: A-3 on every header (hover), A-2 for the Risk Register (its header is the contract),
    # §5.3 banners on the sheets nobody fills, and the remaining formatting.
    _add_header_comments(wb)
    _write_register_guidance(ws)
    _write_banners(wb)
    _add_headroom_and_freezes(wb)
    finalize_named_ranges(wb)   # Grid_RiskRegister + Grid_Methodology + Grid_Layer1_*
    apply_finish(wb, project=None)  # REG05-A1: value-neutral client-ready finish
    apply_protection(wb)        # REG04: harden LAST (after all cells + names exist)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out = Path(argv[0]) if argv else (REPO_ROOT / "templates" / "register_template.xlsx")
    build_template(out)
    print(f"wrote empty register template -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
