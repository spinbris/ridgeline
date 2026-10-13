"""
Risk register loader — reads directly from the risk register .xlsx file.

Two formats supported:

**Old format** (WS3 TRIAL V8–V13):
  load_from_register() — header-based column lookup from row 4

**New format** (the master register, V1+):
  load_from_register_v2() — header-based column lookup from row 4

Auto-detection: detect_register_format() checks col A/D/F of row 5 for "R" prefix.

All column positions are resolved dynamically from header names — no positional
indices are hardcoded. Configuration constants are defined at the top of this file.
"""

from pathlib import Path
import openpyxl
from src.config import RiskInput


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sheet names
REGISTER_SHEET = "Risk Register"
MC_INPUTS_SHEET = "MC_Inputs"

# Row layout
SECTION_HEADER_ROW = 3  # Row containing section headers (merged cells)
HEADER_ROW = 4          # Row containing column headers
DATA_START_ROW = 5      # First row of risk data

# Section labels (row 3 merged headers) — used to constrain cost field search
CONTINGENT_SECTION_LABEL = "contingent"  # prefix match on row 3 text

# Validation
RISK_ID_PREFIX = "R"
ACTIVE_STATUSES = {"open", ""}

# Defaults
DEFAULT_DISTRIBUTION = "PERT"       # Standard distribution when not in dist_map
DEFAULT_CG = "CG_UNASSIGNED"       # Visibly flags unmapped risks in output
MAX_DESC_LENGTH = 80

# Basis labels
BASIS_REGISTER = "Register"
BASIS_ZERO_COST = "ZERO"


# ---------------------------------------------------------------------------
# Header maps — expected column names per register format
# ---------------------------------------------------------------------------

# V1 required: only fields with actual headers in the V8 register.
# The early columns (Risk ID, Status, Description, Owner) have no header text
# in V8 — they use positional fallbacks defined in V1_POSITIONAL_FALLBACKS.
V1_HEADERS = {
    "likelihood": ["Likelihood"],
    "probability": ["Probability", "Prob"],
    "opt_cost": ["Optimistic ($)", "Opt ($)", "Optimistic"],
    "ml_cost": ["Most Likely ($)", "ML ($)", "Most Likely"],
    "pess_cost": ["Pessimistic ($)", "Pess ($)", "Pessimistic"],
}

# V1 optional: fields that may or may not have headers
V1_OPTIONAL_NAMED = {
    "risk_id": ["Risk ID"],
    "status": ["Risk Status", "Status"],
    "description": ["Risk Description", "Description"],
    "owner": ["Risk Owner", "Owner"],
    "cost_flag": ["Cost Flag", "Cost Impact"],
}

# Positional fallbacks for V1 fields without headers (V8 column layout).
# Used only when the header-based lookup finds nothing.
V1_POSITIONAL_FALLBACKS = {
    "risk_id": 3,       # D
    "status": 5,        # F
    "description": 8,   # I
    "owner": 13,        # N
    "cost_flag": 34,    # AI
}

# V2 identification fields — unique headers, safe to search full row
V2_HEADERS = {
    "risk_id": ["Risk ID"],
    "status": ["Risk Status", "Status"],
    "owner": ["Package"],
    "description": ["Risk Description", "Description"],
    "likelihood": ["Likelihood"],
}

# V2 cost fields — headers repeat across Inherent/Contingent/Time sections.
# Must search ONLY within the Contingent section (row 3 label "Contingent...")
# to avoid matching duplicate headers in the Inherent section.
V2_COST_HEADERS = {
    "probability": ["Probability", "Prob"],
    "opt_cost": ["Optimistic ($)", "Opt ($)", "Optimistic"],
    "ml_cost": ["Most Likely ($)", "ML ($)", "Most Likely"],
    "pess_cost": ["Pessimistic ($)", "Pess ($)", "Pessimistic"],
}

# V2 has an optional fallback owner column (separate from the required "Package" col)
V2_OPTIONAL_OWNER = {
    "owner_fallback": ["Risk Owner", "Owner"],
}

# Optional columns shared by both formats
OPTIONAL_HEADERS = {
    "recurrence_type": ["Recurrence_Type", "Recurrence Type"],
    "recurrence_param": ["Recurrence_Param", "Max Occ", "Max_Occ"],
    "cascade_group": ["Cascade_Group", "Cascade Group"],
    "schedule_ml_days": ["Schedule_ML_Days", "ML Days"],
    "schedule_opt_days": ["Schedule_Opt_Days", "Opt Days"],
    "schedule_pess_days": ["Schedule_Pess_Days", "Pess Days"],
    # Stage B: qualitative fields for risk cards
    "cause": ["Causes", "Cause"],
    "consequence": ["Consequences", "Consequence"],
    "controls": ["Existing Controls", "Controls"],
    # SP18b — optional Planned_Day column for per-day P-curve
    "planned_day": ["Planned_Day", "Planned Day"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val, default=0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace("$", "")
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def _safe_str(val, default="") -> str:
    if val is None:
        return default
    s = str(val).strip()
    return default if s in ("#REF!", "#N/A", "#VALUE!", "None", "nan", "") else s


def _find_columns(
    sheet,
    header_row: int,
    required: dict[str, list[str]],
    optional: dict[str, list[str]] | None = None,
    min_col: int = 0,
) -> dict[str, int | None]:
    """Scan header row and return {field_name: col_index} map.

    Parameters
    ----------
    sheet : openpyxl worksheet (read-only)
    header_row : 1-based row number containing column headers
    required : {field_name: [possible header text, ...]} — raises if not found
    optional : {field_name: [possible header text, ...]} — None if not found

    Returns
    -------
    dict mapping field_name to 0-based column index (or None for missing optionals)

    Raises
    ------
    ValueError if any required header is missing
    """
    row_data = list(sheet.iter_rows(
        min_row=header_row, max_row=header_row, values_only=True
    ))
    if not row_data or not row_data[0]:
        raise ValueError(f"No headers found in row {header_row}")

    headers = row_data[0]
    col_map: dict[str, int | None] = {}

    # Build normalised header list: (index, lowercase text) for non-empty cells.
    # _match() returns first occurrence, which matters when headers repeat
    # across sections (e.g. "Probability" in both contingent-cost and time).
    header_pairs: list[tuple[int, str]] = []
    for idx, val in enumerate(headers):
        if val is not None:
            header_pairs.append((idx, str(val).strip().lower()))

    def _match(search_names: list[str]) -> int | None:
        """Find the first column matching any of the search names.

        Tries exact match first, then prefix match (handles multi-line
        headers like "Risk Description:\\nRisk is an effect...").
        Only considers columns at or after min_col.
        """
        for name in search_names:
            nl = name.lower()
            # Exact match (first occurrence at or after min_col)
            for idx, low in header_pairs:
                if idx >= min_col and low == nl:
                    return idx
        # Prefix match (first occurrence at or after min_col)
        for name in search_names:
            nl = name.lower()
            for idx, low in header_pairs:
                if idx >= min_col and low.startswith(nl):
                    return idx
        return None

    # Match required columns
    for field, names in required.items():
        found = _match(names)
        if found is None:
            raise ValueError(
                f"Required column '{field}' not found. "
                f"Searched for: {names}. "
                f"Available headers: {[str(h) for h in headers if h is not None]}"
            )
        col_map[field] = found

    # Match optional columns
    if optional:
        for field, names in optional.items():
            col_map[field] = _match(names)

    return col_map


def _find_section_start(
    sheet,
    section_row: int,
    section_label: str,
) -> int:
    """Find the 0-based column index where a section starts in the section header row.

    Scans row 3 (or specified section_row) for a cell whose text starts with
    section_label (case-insensitive prefix match). Returns the column index.
    Raises ValueError if the section is not found.
    """
    row_data = list(sheet.iter_rows(
        min_row=section_row, max_row=section_row, values_only=True
    ))
    if not row_data or not row_data[0]:
        raise ValueError(f"No section headers found in row {section_row}")

    for idx, val in enumerate(row_data[0]):
        if val is not None and str(val).strip().lower().startswith(section_label.lower()):
            return idx

    raise ValueError(
        f"Section '{section_label}' not found in row {section_row}. "
        f"Available: {[str(v) for v in row_data[0] if v is not None]}"
    )


def _safe_col(row: tuple, col_idx: int | None) -> object:
    """Safely access a column in a row tuple, returning None if out of bounds."""
    if col_idx is None:
        return None
    if col_idx < len(row):
        return row[col_idx]
    return None


# ---------------------------------------------------------------------------
# CG assignments from MC_Inputs
# ---------------------------------------------------------------------------

def _load_cg_from_mc_inputs(wb_path: str | Path) -> dict[int, str]:
    """Read CG column (N, col 14) from MC_Inputs sheet.

    Returns dict mapping row index (0-based from data start) to CG code.
    Column N is the only column not broken by #REF!.
    """
    wb = openpyxl.load_workbook(wb_path, data_only=True, read_only=True)
    sht = wb[MC_INPUTS_SHEET]
    cg_map = {}
    for idx, row in enumerate(sht.iter_rows(min_row=DATA_START_ROW + 1, max_col=14, values_only=True)):
        val = row[13] if len(row) > 13 else None  # col N = index 13
        if val and str(val).startswith("CG"):
            cg_map[idx] = str(val).strip()
    wb.close()
    return cg_map


# ---------------------------------------------------------------------------
# Main loader — old format (WS3 TRIAL V8–V13)
# ---------------------------------------------------------------------------

def load_from_register(
    register_path: str | Path,
    mc_model_path: str | Path | None = None,
    include_zero_cost: bool = True,
    dist_map: dict[str, str] | None = None,
    default_dist: str = DEFAULT_DISTRIBUTION,
) -> list[RiskInput]:
    """Load risks directly from the risk register .xlsx file (old format).

    Parameters
    ----------
    register_path : path to the risk register Excel file
    mc_model_path : path to the MC model .xlsm (for CG assignments).
                    If None, all risks get CG_UNASSIGNED.
    include_zero_cost : if True, include risks with no cost data
                        (they contribute zero to the simulation)
    dist_map : optional risk_id -> distribution type mapping from MC_Inputs
    default_dist : distribution type when risk not in dist_map

    Returns
    -------
    list of RiskInput objects, filtered to Open status
    """
    # Load CG assignments
    cg_map: dict[int, str] = {}
    if mc_model_path and Path(mc_model_path).exists():
        cg_map = _load_cg_from_mc_inputs(mc_model_path)

    # Read register
    wb = openpyxl.load_workbook(register_path, data_only=True, read_only=True)
    sht = wb[REGISTER_SHEET]

    # Build column map from headers.
    # V1 required headers (Likelihood, Probability, costs) must be found.
    # V1 optional named fields (Risk ID, Status, etc.) use header lookup
    # with positional fallbacks for old registers that lack those headers.
    v1_optional = {**OPTIONAL_HEADERS, **V1_OPTIONAL_NAMED}
    try:
        col = _find_columns(sht, HEADER_ROW, V1_HEADERS, v1_optional)
    except ValueError:
        wb.close()
        return []

    # Apply positional fallbacks for fields not found by header scan
    for field, fallback_idx in V1_POSITIONAL_FALLBACKS.items():
        if col.get(field) is None:
            col[field] = fallback_idx

    risks = []
    risk_idx = 0  # index into CG map (aligned with MC_Inputs row order)

    for row in sht.iter_rows(min_row=DATA_START_ROW, values_only=True):
        risk_id = _safe_str(_safe_col(row, col["risk_id"]))
        status = _safe_str(_safe_col(row, col["status"]))
        description = _safe_str(_safe_col(row, col["description"]))
        owner = _safe_str(_safe_col(row, col["owner"]))
        likelihood = _safe_str(_safe_col(row, col["likelihood"]))
        probability = _safe_float(_safe_col(row, col["probability"]))
        opt_cost = _safe_float(_safe_col(row, col["opt_cost"]))
        ml_cost = _safe_float(_safe_col(row, col["ml_cost"]))
        pess_cost = _safe_float(_safe_col(row, col["pess_cost"]))

        if not risk_id or not risk_id.startswith(RISK_ID_PREFIX):
            continue

        # Skip closed risks
        if status.lower() not in ACTIVE_STATUSES:
            risk_idx += 1
            continue

        # Skip zero-cost risks if requested
        has_cost = (opt_cost != 0 or ml_cost != 0 or pess_cost != 0)
        if not include_zero_cost and not has_cost:
            risk_idx += 1
            continue

        # Probability: numeric column is single source of truth.
        # If 0 or None, the risk is inactive (probability stays 0.0).

        # Cost signs preserved as-is from the register. Negative opt values
        # represent upside within a risk. The distribution samplers handle
        # negative lower bounds directly (fixed in distributions.py).

        # Distribution from MC_Inputs dist_map
        distribution = dist_map.get(risk_id, default_dist) if dist_map else default_dist

        # CG assignment from MC_Inputs
        cg = cg_map.get(risk_idx, DEFAULT_CG)

        # Optional fields
        rec_type = _safe_str(_safe_col(row, col.get("recurrence_type")))
        rec_param = _safe_float(_safe_col(row, col.get("recurrence_param")), 0.0)
        casc_group = _safe_str(_safe_col(row, col.get("cascade_group")))
        ml_sched = _safe_float(_safe_col(row, col.get("schedule_ml_days")))
        opt_sched = _safe_float(_safe_col(row, col.get("schedule_opt_days")))
        pess_sched = _safe_float(_safe_col(row, col.get("schedule_pess_days")))

        # Stage B: qualitative fields for risk cards
        cause = _safe_str(_safe_col(row, col.get("cause")))
        consequence = _safe_str(_safe_col(row, col.get("consequence")))
        controls = _safe_str(_safe_col(row, col.get("controls")))
        direction = "Opportunity" if description.lower().startswith("opportunity") else "Threat"

        # SP18b — Planned_Day; absent column ⇒ col.get returns None ⇒ default 0
        planned_day = int(_safe_float(_safe_col(row, col.get("planned_day"))))

        risks.append(RiskInput(
            risk_id=risk_id,
            description=description,
            owner=owner,
            distribution=distribution,
            correlation_group=cg,
            probability=probability,
            opt_cost=opt_cost,
            ml_cost=ml_cost,
            pess_cost=pess_cost,
            basis=BASIS_REGISTER if has_cost else BASIS_ZERO_COST,
            recurrence_type=rec_type,
            recurrence_param=rec_param,
            cascade_group=casc_group,
            ml_days=ml_sched,
            opt_schedule_days=opt_sched,
            pess_schedule_days=pess_sched,
            cause=cause,
            consequence=consequence,
            existing_controls=controls,
            risk_status=status,
            direction=direction,
            planned_day=planned_day,
        ))
        risk_idx += 1

    wb.close()
    return risks


# ---------------------------------------------------------------------------
# V2 loader — master-register format (2026+)
# ---------------------------------------------------------------------------

def detect_register_format(register_path: str | Path) -> str:
    """Detect whether a register file uses old or new column format.

    Returns "new" if col A row 5 starts with "R" (master-register format),
    "old" if col D or F row 5 starts with "R" (WS3 TRIAL format),
    or raises ValueError if neither is detected.
    """
    wb = openpyxl.load_workbook(register_path, data_only=True, read_only=True)
    sht = wb[REGISTER_SHEET]
    row5 = list(sht.iter_rows(min_row=DATA_START_ROW, max_row=DATA_START_ROW, values_only=True))
    wb.close()

    if not row5 or not row5[0]:
        raise ValueError(f"No data found in row {DATA_START_ROW} of {REGISTER_SHEET} sheet")

    cells = row5[0]
    # New format: Risk ID in col A (index 0)
    if len(cells) > 0 and _safe_str(cells[0]).startswith(RISK_ID_PREFIX):
        return "new"
    # Old format: Risk ID in col D (index 3) for V8, or col F (index 5) for V12+
    if len(cells) > 3 and _safe_str(cells[3]).startswith(RISK_ID_PREFIX):
        return "old"
    if len(cells) > 5 and _safe_str(cells[5]).startswith(RISK_ID_PREFIX):
        return "old"

    raise ValueError(
        f"Cannot detect register format: no Risk ID found in col A, D, or F of row {DATA_START_ROW}"
    )


def load_from_register_v2(
    register_path: str | Path,
    cg_map: dict[str, str] | None = None,
    default_cg: str = DEFAULT_CG,
    include_zero_cost: bool = True,
    dist_map: dict[str, str] | None = None,
    default_dist: str = DEFAULT_DISTRIBUTION,
) -> list[RiskInput]:
    """Load risks from a master-register format register.

    Auto-detects format: if old format is detected, delegates to
    load_from_register() for backwards compatibility.

    Parameters
    ----------
    register_path : path to the risk register Excel file
    cg_map : optional risk_id -> CG code mapping (e.g. {"R001": "CG03"})
    default_cg : CG code for risks not in cg_map (default CG_UNASSIGNED)
    include_zero_cost : if True, include risks with no cost data
    dist_map : optional risk_id -> distribution type mapping from MC_Inputs
    default_dist : distribution type when risk not in dist_map

    Returns
    -------
    list of RiskInput objects, filtered to Open status
    """
    register_path = Path(register_path)
    if not register_path.exists():
        raise FileNotFoundError(f"Register file not found: {register_path}")

    # Auto-detect format
    fmt = detect_register_format(register_path)
    if fmt == "old":
        return load_from_register(register_path, include_zero_cost=include_zero_cost,
                                  dist_map=dist_map, default_dist=default_dist)

    if cg_map is None:
        cg_map = {}

    wb = openpyxl.load_workbook(register_path, data_only=True, read_only=True)
    sht = wb[REGISTER_SHEET]

    # Build column map from headers — two passes to handle duplicate headers
    # across Inherent/Contingent/Time sections.
    # Pass 1: identification fields (unique headers, search full row)
    v2_optional = {**OPTIONAL_HEADERS, **V2_OPTIONAL_OWNER}
    col = _find_columns(sht, HEADER_ROW, V2_HEADERS, v2_optional)

    # Pass 2: cost fields (search only within the Contingent section)
    contingent_start = _find_section_start(sht, SECTION_HEADER_ROW, CONTINGENT_SECTION_LABEL)
    cost_col = _find_columns(sht, HEADER_ROW, V2_COST_HEADERS, min_col=contingent_start)
    col.update(cost_col)

    risks = []
    for row in sht.iter_rows(min_row=DATA_START_ROW, values_only=True):
        risk_id = _safe_str(_safe_col(row, col["risk_id"]))
        status = _safe_str(_safe_col(row, col["status"]))
        owner = _safe_str(_safe_col(row, col["owner"]))
        description = _safe_str(_safe_col(row, col["description"]))
        likelihood = _safe_str(_safe_col(row, col["likelihood"]))
        probability = _safe_float(_safe_col(row, col["probability"]))
        opt_cost = _safe_float(_safe_col(row, col["opt_cost"]))
        ml_cost = _safe_float(_safe_col(row, col["ml_cost"]))
        pess_cost = _safe_float(_safe_col(row, col["pess_cost"]))

        if not risk_id or not risk_id.startswith(RISK_ID_PREFIX):
            continue

        # Skip closed risks
        if status.lower() not in ACTIVE_STATUSES:
            continue

        # Skip zero-cost risks if requested
        has_cost = (opt_cost != 0 or ml_cost != 0 or pess_cost != 0)
        if not include_zero_cost and not has_cost:
            continue

        # Probability: numeric column is single source of truth.
        # If 0 or None, the risk is inactive (probability stays 0.0).

        # Use Owner fallback col if Package (primary owner col) is empty
        if not owner:
            owner = _safe_str(_safe_col(row, col.get("owner_fallback")))

        # CG assignment from cg_map (risk_id -> CG code)
        cg = cg_map.get(risk_id, default_cg)

        # Distribution from MC_Inputs dist_map
        distribution = dist_map.get(risk_id, default_dist) if dist_map else default_dist

        # Preserve negative cost signs as-is (no opportunity sign-flip).
        # The triangular sampler handles negative lower bounds naturally.

        # Optional fields
        rec_type = _safe_str(_safe_col(row, col.get("recurrence_type")))
        rec_param = _safe_float(_safe_col(row, col.get("recurrence_param")), 0.0)
        casc_group = _safe_str(_safe_col(row, col.get("cascade_group")))
        ml_sched = _safe_float(_safe_col(row, col.get("schedule_ml_days")))
        opt_sched = _safe_float(_safe_col(row, col.get("schedule_opt_days")))
        pess_sched = _safe_float(_safe_col(row, col.get("schedule_pess_days")))

        # Stage B: qualitative fields for risk cards
        cause = _safe_str(_safe_col(row, col.get("cause")))
        consequence = _safe_str(_safe_col(row, col.get("consequence")))
        controls = _safe_str(_safe_col(row, col.get("controls")))
        direction = "Opportunity" if description.lower().startswith("opportunity") else "Threat"

        # SP18b — Planned_Day; absent column ⇒ default 0
        planned_day = int(_safe_float(_safe_col(row, col.get("planned_day"))))

        risks.append(RiskInput(
            risk_id=risk_id,
            description=description,
            owner=owner,
            distribution=distribution,
            correlation_group=cg,
            probability=probability,
            opt_cost=opt_cost,
            ml_cost=ml_cost,
            pess_cost=pess_cost,
            basis=BASIS_REGISTER if has_cost else BASIS_ZERO_COST,
            recurrence_type=rec_type,
            recurrence_param=rec_param,
            cascade_group=casc_group,
            ml_days=ml_sched,
            opt_schedule_days=opt_sched,
            pess_schedule_days=pess_sched,
            cause=cause,
            consequence=consequence,
            existing_controls=controls,
            risk_status=status,
            direction=direction,
            planned_day=planned_day,
        ))

    wb.close()
    return risks
