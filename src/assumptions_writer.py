"""
MC_Assumptions sheet writer — documents all parameters used by the simulation.

Its only caller was `main.py --assumptions-only`, which retired at REFRETIRE-01
(`78cf33e`); nothing in this repository calls it now (RESIDUE-01).
NOT called during a normal MC run — must not slow the simulation.

Writes two things each call:
  1. Overwrites MC_Assumptions tab with current parameter values
  2. Adds a new dated snapshot tab MC_Assumptions_YYYYMMDD_HHMM
"""

from datetime import datetime
from pathlib import Path
from copy import copy

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from src.config import SimConfig, ChainConfig, GainPainConfig
from src.openpyxl_reader import _read_cg_descriptions_from_open_wb


# ---------------------------------------------------------------------------
# Colours and styles
# ---------------------------------------------------------------------------

_GREY_FILL = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
_NAVY_FILL = PatternFill(start_color="002060", end_color="002060", fill_type="solid")
_STEEL_FILL = PatternFill(start_color="B4C6E7", end_color="B4C6E7", fill_type="solid")
_YELLOW_FILL = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
_WHITE_FILL = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

_WHITE_BOLD = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
_BOLD = Font(name="Calibri", size=10, bold=True)
_NORMAL = Font(name="Calibri", size=10)
_META_FONT = Font(name="Calibri", size=9, italic=True)

_WRAP = Alignment(wrap_text=True, vertical="top")
_WRAP_RIGHT = Alignment(wrap_text=True, vertical="top", horizontal="right")
_THIN_BORDER = Border(
    bottom=Side(style="thin", color="D9D9D9"),
)

_COL_WIDTHS = {"A": 22, "B": 34, "C": 26, "D": 16, "E": 55, "F": 12}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val, default=0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s in ("", "#REF!", "#N/A", "#VALUE!", "nan", "None"):
        return default
    try:
        return float(s.replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return default


def _safe_str(val, default="") -> str:
    if val is None:
        return default
    s = str(val).strip()
    if s in ("#REF!", "#N/A", "nan", "None"):
        return default
    return s


def _read_named(wb, name: str, fallback_cell: str):
    """Read a named range from openpyxl workbook, falling back to cell address."""
    # Try defined names
    try:
        defn = wb.defined_names[name]
        if defn is not None:
            for title, coord in defn.destinations:
                sht = wb[title]
                # Multi-cell range
                if ":" in coord:
                    vals = []
                    for row in sht[coord]:
                        for cell in row:
                            vals.append(cell.value)
                    return vals
                return sht[coord].value
    except (KeyError, AttributeError):
        pass
    # Fallback to cell address
    if "!" in fallback_cell:
        sheet_name, addr = fallback_cell.split("!", 1)
        try:
            return wb[sheet_name][addr].value
        except (KeyError, Exception):
            return None
    return None


def _format_value(val) -> str:
    """Format a value for display in column D."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, float):
        if abs(val) >= 1_000_000:
            return f"${val:,.0f}"
        if abs(val) >= 1:
            return f"{val:,.2f}"
        return f"{val}"
    return str(val)


# ---------------------------------------------------------------------------
# CG group names — register-sourced (Beta-17 SSoT cleanup, 12 May)
#
# The hardcoded CG_NAMES dict (10 entries: Civil market, Labour market, ...)
# was deleted under the no-fallback policy. CG descriptions used in the
# assumptions sheet's row labels now come from the register's MC_Params CG
# block via :func:`src.openpyxl_reader.read_cg_descriptions` (openpyxl path)
# or via the inline xlwings reader below (xlwings path — workbook is already
# open in Excel; can't be re-opened via openpyxl). A CG present in the
# workbook's coefficient block but absent from the description block
# renders an empty name in the assumptions sheet — register-authoring gap
# is visible to the reader, never silently filled.
# ---------------------------------------------------------------------------


def _read_cg_descriptions_xlw(sht) -> dict[str, str]:
    """xlwings counterpart of :func:`src.openpyxl_reader.read_cg_descriptions`.

    Walks MC_Params column B via xlwings, parses the
    ``CG{NN}[separator description]`` format, returns
    ``{CG_ID: description}``. Used by the assumptions writer's xlwings
    path where the workbook is already open in Excel and cannot be
    re-opened via openpyxl. Mirrors the parsing rules of the
    openpyxl reader (same regex pattern, same row-agnostic scan).
    """
    import re
    pattern = re.compile(r"^\s*(CG\d{2})\b\s*[-–—:]?\s*(.*?)\s*$")
    descriptions: dict[str, str] = {}
    # Bounded scan; mirrors the openpyxl reader's row range.
    for r in range(1, 200):
        try:
            value = sht.range((r, 2)).value
        except Exception:
            break
        if value is None:
            continue
        m = pattern.match(str(value))
        if not m:
            continue
        descriptions[m.group(1).upper()] = m.group(2).strip()
    return descriptions


# ---------------------------------------------------------------------------
# Build parameter rows
# ---------------------------------------------------------------------------

def _build_rows(wb, config: SimConfig, chains: ChainConfig) -> list[dict]:
    """Build the parameter inventory as a list of row dicts.

    Each dict has keys: group, parameter, source, value, description.
    Group header rows have group set and all others empty.
    """
    rows = []

    def _group_header(name):
        rows.append({"_header": True, "group": name})

    def _row(group, param, source, value, desc):
        rows.append({
            "_header": False,
            "group": group,
            "parameter": param,
            "source": source,
            "value": value,
            "description": desc,
        })

    # Helper: try named range via openpyxl, show source accordingly
    dc_defaults = SimConfig.__dataclass_fields__
    ch_defaults = ChainConfig.__dataclass_fields__

    def _sourced(named_range, fallback, config_field, config_obj=config,
                 defaults_map=dc_defaults, is_bool=False):
        wb_val = _read_named(wb, named_range, fallback)
        if wb_val is not None:
            if is_bool:
                return named_range, bool(_safe_float(wb_val, 0))
            elif isinstance(wb_val, str):
                return named_range, _safe_str(wb_val)
            else:
                return named_range, _safe_float(wb_val)
        if config_field in defaults_map:
            return "Python Default", defaults_map[config_field].default
        return "Python Default", getattr(config_obj, config_field, "N/A")

    # --- Group 1: Simulation Control ---
    _group_header("Simulation Control")
    src, val = _sourced("mc_n_iter", "MC_Params!C4", "n_iter")
    _row("Simulation Control", "Iterations", src,
         int(val) if isinstance(val, float) else val,
         "Number of Monte Carlo iterations per run")
    src, val = _sourced("mc_seed", "MC_Params!C5", "seed")
    _row("Simulation Control", "Random seed", src,
         int(val) if isinstance(val, float) else val,
         "Random seed (0 = fresh random each run)")
    src, val = _sourced("mc_view", "MC_Params!C6", "view")
    _row("Simulation Control", "Stakeholder view", src,
         val, "Filter: All, BOP, CSE, or Shared")
    src, val = _sourced("mc_reporting_p", "MC_Params!C7", "reporting_p_level")
    _row("Simulation Control", "Reporting P-level", src,
         int(val) if isinstance(val, float) else val,
         "P-level for contribution table (50, 80, or 90)")

    # --- Group 2: Base Cost and Budget ---
    _group_header("Base Cost and Budget")
    src, val = _sourced("mc_tic", "MC_Params!C13", "tic")
    _row("Base Cost and Budget", "TIC (Target Indicative Cost)", src,
         val, "Base estimate before contingency ($)")
    src, val = _sourced("mc_contingency", "MC_Params!C14", "contingency")
    _row("Base Cost and Budget", "Risk pool budget", src,
         val, "Contingency reserve ($). Same cell read as config.contingency "
         "and config.pool_budget — documented once, dual use")
    src, val = _sourced("mc_bop_contract", "MC_Params!C9", "bop_contract")
    _row("Base Cost and Budget", "BOP contract price", src,
         val, "BOP Contractor lump sum price ($)")
    src, val = _sourced("mc_bop_cont", "MC_Params!C10", "bop_contingency")
    _row("Base Cost and Budget", "BOP contingency", src,
         val, "BOP Contractor contingency reserve ($)")
    src, val = _sourced("mc_cse_cont", "MC_Params!C11", "cse_contingency")
    _row("Base Cost and Budget", "CSE contingency", src,
         val, "Owner contingency reserve ($)")

    # --- Group 3: Programme and Recurrence ---
    _group_header("Programme and Recurrence")
    src, val = _sourced("mc_programme_seasons", "MC_Params!C99", "programme_seasons")
    _row("Programme and Recurrence", "Programme seasons", src,
         int(val) if isinstance(val, float) else val,
         "Number of seasonal exposure windows (wet seasons). Default n for "
         "BINOMIAL recurring risks that don't specify their own max_occ")

    # --- Group 4: Event Chain Parameters ---
    _group_header("Event Chain Parameters")
    chain_params = [
        ("Chain 1 trigger (months)", "mc_c1_trigger", "MC_Params!C35",
         "c1_trigger_months", False,
         "Planning delay duration threshold to trigger Chain 1 (months)"),
        ("Chain 1 amplifier", "mc_c1_amp", "MC_Params!C36",
         "c1_amplification", False,
         "Probability multiplier applied to weather risk when Chain 1 fires"),
        ("Chain 2 trigger (weeks)", "mc_c2_trigger", "MC_Params!C37",
         "c2_trigger_weeks", False,
         "Site establishment delay threshold to trigger Chain 2 (weeks)"),
        ("Chain 2 amplifier", "mc_c2_factor", "MC_Params!C38",
         "c2_cascade_factor", False,
         "Probability multiplier applied to downstream risks when Chain 2 fires"),
        ("Cascade enabled", "mc_cascade_on", "MC_Params!C39",
         "cascade_enabled", True,
         "Recursive temporal cascade ON/OFF (OFF by default until agreed)"),
        ("Cascade slip rate", "mc_cascade_slip", "MC_Params!C40",
         "cascade_slip_rate", False,
         "Probability multiplier per 90 days accumulated slip"),
        ("Cascade slip cap", "mc_cascade_cap", "MC_Params!C41",
         "cascade_slip_cap", False,
         "Maximum probability multiplier from cascade"),
        ("Cascade cost scale", "mc_cascade_cost", "MC_Params!C42",
         "cascade_cost_scale_rate", False,
         "Extra cost multiplier per 180 days accumulated slip"),
    ]
    for param, named_range, fallback, config_field, is_bool, desc in chain_params:
        src, val = _sourced(named_range, fallback, config_field,
                            config_obj=chains, defaults_map=ch_defaults,
                            is_bool=is_bool)
        _row("Event Chain Parameters", param, src, val, desc)

    # --- Group 5: Correlation Coefficients ---
    _group_header("Correlation Coefficients")
    cg_raw = _read_named(wb, "mc_cg_coeffs", "MC_Params!C46:C55")
    cg_from_wb = cg_raw is not None
    if not cg_from_wb:
        cg_raw = [0.5] * 10
    if not isinstance(cg_raw, list):
        cg_raw = [cg_raw]
    # Beta-17 SSoT: read CG descriptions from MC_Params column B (same
    # workbook). _read_cg_descriptions_from_open_wb is a thin wrapper over
    # the openpyxl reader's parsing helper that takes an already-open
    # workbook to avoid re-opening the file we just opened.
    cg_descriptions = _read_cg_descriptions_from_open_wb(wb)
    for i in range(min(len(cg_raw), 10)):
        code = f"CG{i+1:02d}"
        name = cg_descriptions.get(code, "")
        val = _safe_float(cg_raw[i], 0.5)
        src = f"mc_cg_coeffs[{i}]" if cg_from_wb else "Python Default"
        _row("Correlation Coefficients", f"{code} — {name}", src,
             val, f"Pairwise correlation within {code} group (0-1)")

    wbs_rho_raw = _read_named(wb, "mc_wbs_rho", "MC_Params!C44")
    src = "mc_wbs_rho" if wbs_rho_raw is not None else "Python Default"
    _row("Correlation Coefficients", "WBS cross-bucket rho", src,
         _safe_float(wbs_rho_raw, 0.4),
         "Pairwise correlation between all Layer 1 WBS buckets (0-1)")

    # --- Group 6: Filter Labels ---
    _group_header("Filter Labels")
    src, val = _sourced("mc_party_a", "MC_Params!C58", "party_a_name")
    _row("Filter Labels", "Party A label", src, val,
         "Owner label for BOP Contractor risks")
    src, val = _sourced("mc_party_b", "MC_Params!C59", "party_b_name")
    _row("Filter Labels", "Party B label", src, val,
         "Owner label for Owner risks")
    src, val = _sourced("mc_shared_label", "MC_Params!C60", "shared_label")
    _row("Filter Labels", "Shared label", src, val,
         "Owner label for Shared risk pool risks")

    # --- Group 7: Gain/Pain Configuration ---
    _group_header("Gain/Pain Configuration")
    gp_share = _read_named(wb, "mc_shared_pct", "MC_Params!C8")
    src = "mc_shared_pct" if gp_share is not None else "Python Default"
    _row("Gain/Pain Configuration", "TOC gain/pain share (BOP)", src,
         _safe_float(gp_share, 0.5),
         "BOP share of TOC gainshare/painshare. Used by GainPainConfig.share_split "
         "only — not applied in risk cost simulation")

    # --- Group 8: Engine Constants ---
    _group_header("Engine Constants")
    _row("Engine Constants", "PERT lambda", "distributions.py",
         4.0, "Lambda parameter for PERT Beta distribution weighting")
    _row("Engine Constants", "Correlation method", "correlations.py",
         "Cholesky", "Method for generating correlated uniform draws")
    _row("Engine Constants", "Max probability cap", "simulation.py",
         0.95, "Maximum probability after chain/cascade amplification")

    return rows


# ---------------------------------------------------------------------------
# Write sheet
# ---------------------------------------------------------------------------

def _write_sheet(
    sht,
    rows: list[dict],
    wb_path: str,
    timestamp: datetime,
    prev_snapshot: dict[str, str] | None,
):
    """Write parameter rows to an openpyxl worksheet."""

    # Column widths
    for col_letter, width in _COL_WIDTHS.items():
        sht.column_dimensions[col_letter].width = width

    # --- Row 1: Metadata ---
    meta_items = [
        ("Model file:", str(Path(wb_path).name)),
        ("Path:", str(wb_path)),
        ("Timestamp:", timestamp.strftime("%Y-%m-%d %H:%M:%S")),
    ]
    for col_idx, (label, value) in enumerate(meta_items):
        cell_label = sht.cell(row=1, column=col_idx * 2 + 1, value=label)
        cell_label.font = _META_FONT
        cell_label.fill = _GREY_FILL
        cell_value = sht.cell(row=1, column=col_idx * 2 + 2, value=value)
        cell_value.font = _META_FONT
        cell_value.fill = _GREY_FILL
    # Fill remaining metadata cells
    for c in range(len(meta_items) * 2 + 1, 7):
        sht.cell(row=1, column=c).fill = _GREY_FILL

    # Row 2: blank separator

    # --- Row 3: Column headers ---
    headers = ["Group", "Parameter", "Source", "Value", "Description", "Changed"]
    for col_idx, header in enumerate(headers, 1):
        cell = sht.cell(row=3, column=col_idx, value=header)
        cell.font = _WHITE_BOLD
        cell.fill = _NAVY_FILL
        cell.alignment = _WRAP

    # Freeze panes at row 4
    sht.freeze_panes = "A4"

    # --- Data rows from row 4 ---
    current_row = 4
    data_row_idx = 0  # for alternating colours

    # Center Across Selection alignment for openpyxl
    _CENTER_ACROSS = Alignment(horizontal="centerContinuous", wrap_text=True, vertical="top")

    for row_data in rows:
        if row_data.get("_header"):
            # Group header row — center across A-F, bold, steel blue
            cell = sht.cell(row=current_row, column=1, value=row_data["group"])
            cell.font = _BOLD
            cell.fill = _STEEL_FILL
            cell.alignment = _CENTER_ACROSS
            for col in range(2, 7):
                c = sht.cell(row=current_row, column=col)
                c.fill = _STEEL_FILL
                c.alignment = _CENTER_ACROSS
            current_row += 1
            data_row_idx = 0
            continue

        # Data row
        group = row_data["group"]
        param = row_data["parameter"]
        source = row_data["source"]
        value = row_data["value"]
        desc = row_data["description"]

        # Changed column logic
        changed = ""
        if prev_snapshot is not None:
            prev_val = prev_snapshot.get(source)
            if prev_val is None:
                changed = "New"
            elif prev_val != _format_value(value):
                changed = "Yes"
            else:
                changed = "No"

        # Determine fill — yellow highlight for Python Default sources
        is_python_default = (source == "Python Default")
        if is_python_default:
            fill = _YELLOW_FILL
        elif data_row_idx % 2 == 0:
            fill = _WHITE_FILL
        else:
            fill = _GREY_FILL

        values = [group, param, source, _format_value(value), desc, changed]
        for col_idx, val in enumerate(values, 1):
            cell = sht.cell(row=current_row, column=col_idx, value=val)
            cell.font = _NORMAL
            cell.fill = fill
            cell.border = _THIN_BORDER
            # Column D: right-align numerics
            if col_idx == 4 and isinstance(value, (int, float)):
                cell.alignment = _WRAP_RIGHT
            else:
                cell.alignment = _WRAP

        current_row += 1
        data_row_idx += 1


def _read_previous_snapshot(wb) -> dict[str, str] | None:
    """Find the most recent MC_Assumptions_YYYYMMDD_HHMM tab and read its values.

    Returns dict mapping Source (col C) → Value (col D), or None if no snapshot.
    """
    snapshot_tabs = []
    for name in wb.sheetnames:
        if name.startswith("MC_Assumptions_") and len(name) > len("MC_Assumptions_"):
            snapshot_tabs.append(name)

    if not snapshot_tabs:
        return None

    # Sort by name (timestamp format ensures lexicographic = chronological)
    snapshot_tabs.sort()
    latest = snapshot_tabs[-1]
    sht = wb[latest]

    prev = {}
    for row in sht.iter_rows(min_row=4, max_col=6, values_only=True):
        if row is None or len(row) < 4:
            continue
        source = row[2]  # Column C
        value = row[3]   # Column D
        if source and str(source).strip():
            prev[str(source).strip()] = str(value).strip() if value else ""

    return prev


def _copy_sheet(wb, source_name: str, target_name: str):
    """Copy a worksheet within the workbook."""
    source = wb[source_name]
    target = wb.copy_worksheet(source)
    target.title = target_name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_assumptions(
    wb_path: str | Path,
    config: SimConfig,
    chains: ChainConfig,
) -> None:
    """Write MC_Assumptions sheet documenting all simulation parameters.

    Not called during normal MC runs — invoked via --assumptions-only flag.
    Overwrites in place if the sheet exists; creates it after MC_Params if not.
    Uses openpyxl (workbook must not be open in Excel).
    """
    wb_path = str(wb_path)
    timestamp = datetime.now()

    # Open workbook (keep VBA macros)
    wb = openpyxl.load_workbook(wb_path, keep_vba=True)

    # Build parameter rows
    rows = _build_rows(wb, config, chains)

    # --- Write MC_Assumptions tab ---
    tab_name = "MC_Assumptions"
    if tab_name in wb.sheetnames:
        del wb[tab_name]

    if "MC_Params" in wb.sheetnames:
        params_idx = wb.sheetnames.index("MC_Params")
        sht = wb.create_sheet(tab_name, params_idx + 1)
    else:
        sht = wb.create_sheet(tab_name)

    _write_sheet(sht, rows, wb_path, timestamp, None)

    # Tab colour: navy
    sht.sheet_properties.tabColor = "002060"

    # Save
    wb.save(wb_path)
    wb.close()


# ---------------------------------------------------------------------------
# xlwings writer — for VBA button (workbook already open in Excel)
# ---------------------------------------------------------------------------

def _rgb_to_ole(r: int, g: int, b: int) -> int:
    """Convert RGB to OLE colour integer for xlwings .api calls."""
    return r + (g << 8) + (b << 16)


def _read_named_xlw(wb, name: str, fallback: str):
    """Read a named range from an xlwings workbook, with cell fallback.

    Same logic as reader._named() but returns raw value.
    """
    try:
        rng = wb.names[name].refers_to_range
        val = rng.value
        if isinstance(val, list) and val and isinstance(val[0], list):
            val = [row[0] for row in val]
        return val
    except Exception:
        sheet_name, cell = fallback.split("!") if "!" in fallback else ("MC_Params", fallback)
        try:
            return wb.sheets[sheet_name].range(cell).value
        except Exception:
            return None


def _read_prev_snapshot_xlw(wb) -> dict[str, str] | None:
    """Find most recent snapshot tab and read Source→Value pairs via xlwings."""
    snapshot_tabs = [s.name for s in wb.sheets
                     if s.name.startswith("MC_Assumptions_")]
    if not snapshot_tabs:
        return None
    snapshot_tabs.sort()
    sht = wb.sheets[snapshot_tabs[-1]]

    # Read data from row 4 onwards, cols A-F
    last_row = sht.range("C4").end("down").row
    if last_row <= 4:
        return None
    data = sht.range(f"C4:D{last_row}").value
    if data is None:
        return None
    if not isinstance(data[0], list):
        data = [data]

    prev = {}
    for row in data:
        source = row[0]
        value = row[1]
        if source and str(source).strip():
            prev[str(source).strip()] = str(value).strip() if value else ""
    return prev


def _read_prev_snapshot_xlw_from_sheet(sht) -> dict[str, str] | None:
    """Read Source→Value pairs from an existing MC_Assumptions sheet via xlwings.

    Called before clearing the sheet so we can populate the Changed column.
    """
    try:
        last_row = sht.range("C4").end("down").row
        if last_row <= 4:
            return None
        data = sht.range(f"C4:D{last_row}").value
        if data is None:
            return None
        if not isinstance(data[0], list):
            data = [data]
        prev = {}
        for row in data:
            source = row[0]
            value = row[1]
            if source and str(source).strip():
                prev[str(source).strip()] = str(value).strip() if value else ""
        return prev if prev else None
    except Exception:
        return None


def _build_rows_xlw(wb, config: SimConfig, chains: ChainConfig) -> list[dict]:
    """Build parameter rows using xlwings named range reads.

    Same structure as _build_rows() but reads from live workbook via xlwings.
    """
    rows = []

    def _group_header(name):
        rows.append({"_header": True, "group": name})

    def _row(group, param, source, value, desc):
        rows.append({
            "_header": False,
            "group": group,
            "parameter": param,
            "source": source,
            "value": value,
            "description": desc,
        })

    # Helper: try named range, show source as range name or "Python Default"
    dc_defaults = SimConfig.__dataclass_fields__
    ch_defaults = ChainConfig.__dataclass_fields__

    def _sourced(named_range, fallback, config_field, config_obj=config,
                 defaults_map=dc_defaults, is_bool=False):
        """Try to read named range; return (source_label, value).

        If named range has a value: source = range name, value = workbook value.
        If not found: source = "Python Default", value = dataclass default.
        """
        wb_val = _read_named_xlw(wb, named_range, fallback)
        if wb_val is not None:
            if is_bool:
                return named_range, bool(_safe_float(wb_val, 0))
            elif isinstance(wb_val, str):
                return named_range, _safe_str(wb_val)
            else:
                return named_range, _safe_float(wb_val)
        # Fell back to Python default
        if config_field in defaults_map:
            return "Python Default", defaults_map[config_field].default
        return "Python Default", getattr(config_obj, config_field, "N/A")

    # --- Group 1: Simulation Control ---
    _group_header("Simulation Control")

    src, val = _sourced("mc_n_iter", "MC_Params!C4", "n_iter")
    _row("Simulation Control", "Iterations", src,
         int(val) if isinstance(val, float) else val,
         "Number of Monte Carlo iterations per run")

    src, val = _sourced("mc_seed", "MC_Params!C5", "seed")
    _row("Simulation Control", "Random seed", src,
         int(val) if isinstance(val, float) else val,
         "Random seed (0 = fresh random each run)")

    src, val = _sourced("mc_view", "MC_Params!C6", "view")
    _row("Simulation Control", "Stakeholder view", src,
         val, "Filter: All, BOP, CSE, or Shared")

    src, val = _sourced("mc_reporting_p", "MC_Params!C7", "reporting_p_level")
    _row("Simulation Control", "Reporting P-level", src,
         int(val) if isinstance(val, float) else val,
         "P-level for contribution table (50, 80, or 90)")

    # --- Group 2: Base Cost and Budget ---
    _group_header("Base Cost and Budget")

    src, val = _sourced("mc_tic", "MC_Params!C13", "tic")
    _row("Base Cost and Budget", "TIC (Target Indicative Cost)", src,
         val, "Base estimate before contingency ($)")

    src, val = _sourced("mc_contingency", "MC_Params!C14", "contingency")
    _row("Base Cost and Budget", "Risk pool budget", src,
         val, "Contingency reserve ($). Same cell read as config.contingency "
         "and config.pool_budget — documented once, dual use")

    src, val = _sourced("mc_bop_contract", "MC_Params!C9", "bop_contract")
    _row("Base Cost and Budget", "BOP contract price", src,
         val, "BOP Contractor lump sum price ($)")

    src, val = _sourced("mc_bop_cont", "MC_Params!C10", "bop_contingency")
    _row("Base Cost and Budget", "BOP contingency", src,
         val, "BOP Contractor contingency reserve ($)")

    src, val = _sourced("mc_cse_cont", "MC_Params!C11", "cse_contingency")
    _row("Base Cost and Budget", "CSE contingency", src,
         val, "Owner contingency reserve ($)")

    # --- Group 3: Programme and Recurrence ---
    _group_header("Programme and Recurrence")

    src, val = _sourced("mc_programme_seasons", "MC_Params!C99", "programme_seasons")
    _row("Programme and Recurrence", "Programme seasons", src,
         int(val) if isinstance(val, float) else val,
         "Number of seasonal exposure windows (wet seasons). Default n for "
         "BINOMIAL recurring risks that don't specify their own max_occ")

    # --- Group 4: Event Chain Parameters ---
    _group_header("Event Chain Parameters")
    chain_params = [
        ("Chain 1 trigger (months)", "mc_c1_trigger", "MC_Params!C35",
         "c1_trigger_months", False,
         "Planning delay duration threshold to trigger Chain 1 (months)"),
        ("Chain 1 amplifier", "mc_c1_amp", "MC_Params!C36",
         "c1_amplification", False,
         "Probability multiplier applied to weather risk when Chain 1 fires"),
        ("Chain 2 trigger (weeks)", "mc_c2_trigger", "MC_Params!C37",
         "c2_trigger_weeks", False,
         "Site establishment delay threshold to trigger Chain 2 (weeks)"),
        ("Chain 2 amplifier", "mc_c2_factor", "MC_Params!C38",
         "c2_cascade_factor", False,
         "Probability multiplier applied to downstream risks when Chain 2 fires"),
        ("Cascade enabled", "mc_cascade_on", "MC_Params!C39",
         "cascade_enabled", True,
         "Recursive temporal cascade ON/OFF (OFF by default until agreed)"),
        ("Cascade slip rate", "mc_cascade_slip", "MC_Params!C40",
         "cascade_slip_rate", False,
         "Probability multiplier per 90 days accumulated slip"),
        ("Cascade slip cap", "mc_cascade_cap", "MC_Params!C41",
         "cascade_slip_cap", False,
         "Maximum probability multiplier from cascade"),
        ("Cascade cost scale", "mc_cascade_cost", "MC_Params!C42",
         "cascade_cost_scale_rate", False,
         "Extra cost multiplier per 180 days accumulated slip"),
    ]
    for param, named_range, fallback, config_field, is_bool, desc in chain_params:
        src, val = _sourced(named_range, fallback, config_field,
                            config_obj=chains, defaults_map=ch_defaults,
                            is_bool=is_bool)
        _row("Event Chain Parameters", param, src, val, desc)

    # --- Group 5: Correlation Coefficients ---
    _group_header("Correlation Coefficients")
    cg_raw = _read_named_xlw(wb, "mc_cg_coeffs", "MC_Params!C46:C55")
    cg_from_wb = cg_raw is not None
    if not cg_from_wb:
        cg_raw = [0.5] * 10
    if not isinstance(cg_raw, list):
        cg_raw = [cg_raw]
    # Beta-17 SSoT: read CG descriptions from MC_Params column B via xlwings.
    # Workbook is open in Excel so openpyxl re-open would deadlock; the
    # xlwings-native parser above mirrors the openpyxl reader's contract.
    try:
        mc_params_sht = wb.sheets["MC_Params"]
        cg_descriptions = _read_cg_descriptions_xlw(mc_params_sht)
    except Exception:
        cg_descriptions = {}
    for i in range(min(len(cg_raw), 10)):
        code = f"CG{i+1:02d}"
        name = cg_descriptions.get(code, "")
        val = _safe_float(cg_raw[i], 0.5)
        src = f"mc_cg_coeffs[{i}]" if cg_from_wb else "Python Default"
        _row("Correlation Coefficients",
             f"{code} — {name}", src,
             val, f"Pairwise correlation within {code} group (0-1)")

    wbs_rho_raw = _read_named_xlw(wb, "mc_wbs_rho", "MC_Params!C44")
    if wbs_rho_raw is not None:
        _row("Correlation Coefficients", "WBS cross-bucket rho", "mc_wbs_rho",
             _safe_float(wbs_rho_raw, 0.4),
             "Pairwise correlation between all Layer 1 WBS buckets (0-1)")
    else:
        _row("Correlation Coefficients", "WBS cross-bucket rho", "Python Default",
             0.4,
             "Pairwise correlation between all Layer 1 WBS buckets (0-1)")

    # --- Group 6: Filter Labels ---
    _group_header("Filter Labels")

    src, val = _sourced("mc_party_a", "MC_Params!C58", "party_a_name")
    _row("Filter Labels", "Party A label", src,
         val, "Owner label for BOP Contractor risks")

    src, val = _sourced("mc_party_b", "MC_Params!C59", "party_b_name")
    _row("Filter Labels", "Party B label", src,
         val, "Owner label for Owner risks")

    src, val = _sourced("mc_shared_label", "MC_Params!C60", "shared_label")
    _row("Filter Labels", "Shared label", src,
         val, "Owner label for Shared risk pool risks")

    # --- Group 7: Gain/Pain Configuration ---
    _group_header("Gain/Pain Configuration")
    gp_share = _read_named_xlw(wb, "mc_shared_pct", "MC_Params!C8")
    if gp_share is not None:
        _row("Gain/Pain Configuration", "TOC gain/pain share (BOP)", "mc_shared_pct",
             _safe_float(gp_share, 0.5),
             "BOP share of TOC gainshare/painshare. Used by GainPainConfig.share_split "
             "only — not applied in risk cost simulation")
    else:
        _row("Gain/Pain Configuration", "TOC gain/pain share (BOP)", "Python Default",
             0.5,
             "BOP share of TOC gainshare/painshare. Used by GainPainConfig.share_split "
             "only — not applied in risk cost simulation")

    # --- Group 8: Engine Constants ---
    _group_header("Engine Constants")
    _row("Engine Constants", "PERT lambda", "distributions.py",
         4.0, "Lambda parameter for PERT Beta distribution weighting")
    _row("Engine Constants", "Correlation method", "correlations.py",
         "Cholesky", "Method for generating correlated uniform draws")
    _row("Engine Constants", "Max probability cap", "simulation.py",
         0.95, "Maximum probability after chain/cascade amplification")

    return rows


def _write_sheet_xlw(sht, rows, wb_path, timestamp, prev_snapshot):
    """Write parameter rows to an xlwings worksheet."""
    import xlwings as xw

    # Colours as OLE integers
    GREY = _rgb_to_ole(242, 242, 242)
    NAVY = _rgb_to_ole(0, 32, 96)
    STEEL = _rgb_to_ole(180, 198, 231)
    YELLOW = _rgb_to_ole(255, 255, 153)
    WHITE = _rgb_to_ole(255, 255, 255)

    # Column widths
    for col, width in [("A", 22), ("B", 34), ("C", 26), ("D", 16), ("E", 55), ("F", 12)]:
        sht.range(f"{col}:{col}").column_width = width

    # --- Row 1: Metadata ---
    meta = [
        ("A1", "Model file:"), ("B1", Path(wb_path).name),
        ("C1", "Path:"), ("D1", str(wb_path)),
        ("E1", "Timestamp:"), ("F1", timestamp.strftime("%Y-%m-%d %H:%M:%S")),
    ]
    for cell, val in meta:
        c = sht.range(cell)
        c.value = val
        c.color = (242, 242, 242)
        c.font.italic = True
        c.font.size = 9

    # --- Row 3: Column headers ---
    headers = ["Group", "Parameter", "Source", "Value", "Description", "Changed"]
    for col_idx, header in enumerate(headers):
        c = sht.range((3, col_idx + 1))
        c.value = header
        c.color = (0, 32, 96)
        c.font.color = (255, 255, 255)
        c.font.bold = True
        c.font.size = 10
        c.api.WrapText = True

    # Freeze panes below row 3
    sht.activate()
    sht.book.app.api.ActiveWindow.FreezePanes = False
    sht.range("A4").select()
    sht.book.app.api.ActiveWindow.FreezePanes = True

    # --- Data rows from row 4 ---
    current_row = 4
    data_row_idx = 0

    for row_data in rows:
        if row_data.get("_header"):
            # Group header — center across selection A-F, steel blue, bold
            rng = sht.range((current_row, 1), (current_row, 6))
            rng.color = (180, 198, 231)
            cell = sht.range((current_row, 1))
            cell.value = row_data["group"]
            cell.font.bold = True
            cell.font.size = 10
            # Center Across Selection (xlCenterAcrossSelection = 7)
            rng.api.HorizontalAlignment = 7
            current_row += 1
            data_row_idx = 0
            continue

        group = row_data["group"]
        param = row_data["parameter"]
        source = row_data["source"]
        value = row_data["value"]
        desc = row_data["description"]

        # Changed column
        changed = ""
        if prev_snapshot is not None:
            prev_val = prev_snapshot.get(source)
            if prev_val is None:
                changed = "New"
            elif prev_val != _format_value(value):
                changed = "Yes"
            else:
                changed = "No"

        # Determine fill colour — yellow highlight for Python Default sources
        is_python_default = (source == "Python Default")
        if is_python_default:
            fill_rgb = (255, 255, 153)
        elif data_row_idx % 2 == 0:
            fill_rgb = (255, 255, 255)
        else:
            fill_rgb = (242, 242, 242)

        values = [group, param, source, _format_value(value), desc, changed]
        for col_idx, val in enumerate(values):
            c = sht.range((current_row, col_idx + 1))
            c.value = val
            c.font.size = 10
            c.color = fill_rgb
            c.api.WrapText = True
            # Right-align numeric values in column D
            if col_idx == 3 and isinstance(value, (int, float)):
                c.api.HorizontalAlignment = -4152  # xlRight

        current_row += 1
        data_row_idx += 1


def write_assumptions_xlw(wb, config: SimConfig, chains: ChainConfig) -> None:
    """Write MC_Assumptions sheet via xlwings to an open workbook.

    Was called by the legacy VBA WriteAssumptions macro (that path retired at 3c Part B).
    Not called during normal MC runs. Overwrites in place if the sheet
    already exists; creates it after MC_Params if not.
    """
    timestamp = datetime.now()
    wb_path = wb.fullname

    # Build rows (using xlwings reads)
    rows = _build_rows_xlw(wb, config, chains)

    # --- Read previous values before clearing ---
    tab_name = "MC_Assumptions"
    sheet_names = [s.name for s in wb.sheets]
    prev_snapshot = None
    if tab_name in sheet_names:
        prev_snapshot = _read_prev_snapshot_xlw_from_sheet(wb.sheets[tab_name])
        # Clear content and formatting but keep the sheet (preserves buttons/shapes)
        sht = wb.sheets[tab_name]
        sht.cells.clear()
    else:
        # Create after MC_Params
        if "MC_Params" in sheet_names:
            sht = wb.sheets.add(tab_name, after=wb.sheets["MC_Params"])
        else:
            sht = wb.sheets.add(tab_name)

    _write_sheet_xlw(sht, rows, wb_path, timestamp, prev_snapshot)

    # Tab colour: navy
    sht.api.Tab.Color = _rgb_to_ole(0, 32, 96)
