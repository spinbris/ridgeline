"""
V5 Register Reader — reads risks AND simulation parameters from a single
V5 register workbook.

Replaces the split between register_loader.py (risks) and reader.py (params)
for V5-format registers. Existing modules are preserved unchanged.

Detection: a workbook is V5 if it contains both a "Risk Register" sheet
and an "MC_Params" sheet.

Public API:
    read_risks_v5(workbook_path) -> list[RiskInput]
    read_params_v5(workbook_path) -> (SimConfig, list[WBSBucket], ChainConfig, dict, float)
    is_v5_register(workbook_path) -> bool
"""

import logging
from pathlib import Path

import numpy as np
import openpyxl

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput, GainPainConfig
from src.rng_streams import stated_seed
# QRAXL-01 step 5 (contract v2, scope C) - Layer-1 factor model. read_layer1_v5
# lives HERE in the Tier-2 shell (openpyxl is fine); it returns a plain
# Layer1Config the Pyodide-clean layer1_factors consumes, so that module's
# import closure is unchanged (brief section 5, import discipline).
from src.layer1_factors import Factor, Layer1Config, nearest_psd, validate_layer1
# QRAXL-01 step 6a - the shared I/O-free parser. read_risks_v5 / read_layer1_v5
# now extract a grid of cell values and delegate the section-scan/parse to these,
# so the Tier-1 xlwings reader (which feeds the SAME parser its own grid) agrees
# with Tier 2 by construction. RegisterReadError is re-exported from there so
# existing `from src.v5_register_reader import RegisterReadError` importers keep
# working and catch the SAME class the parser raises.
from src.qra_register_parse import (
    RegisterReadError,
    parse_layer1_from_grids,
    parse_risks_from_grid,
)
from src.qra_register_parse import _LAYER1_SHEETS as _PARSE_LAYER1_SHEETS
# QRAXL-01 Coupling C: HEADLESS_CG_COEFFICIENTS / WBS_CROSS_BUCKET_RHO are now
# binding-sourced (fail-loud) and imported FUNCTION-LOCAL inside read_params_v5,
# so merely importing this widely-imported reader does not force a project
# selection at import time. HEADLESS_BUCKETS / DEFAULT_PROGRAMME_SEASONS /
# DEFAULT_GP_TOC were imported here but never used - dropped. The gain/pain
# share constants below stay literals in defaults.py.
from src.defaults import (
    DEFAULT_GP_SHARE_SPLIT,
    DEFAULT_GP_MAX_REWARD_PCT,
    DEFAULT_GP_MAX_RISK_PCT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RISK_REGISTER_SHEET = "Risk Register"
MC_PARAMS_SHEET = "MC_Params"

#: The MC_Params seed row's label (CONFIGTRUTH-01 P5). Only this legacy cost-MC reader reads it;
#: the deliverable's seed is ``SR9_SEED``, so the label says so rather than letting a filler
#: think the cell sets the deliverable's seed. The old label is still read, so an existing
#: register keeps its seed.
SEED_LABEL = "Random seed - legacy cost MC only (0=random; the deliverable's seed is SR9_SEED)"
SEED_LABEL_BEFORE_CONFIGTRUTH01 = "Random seed (0=random)"

SECTION_HEADER_ROW = 3
HEADER_ROW = 4
DATA_START_ROW = 5

RISK_ID_PREFIX = "R"
CONTINGENT_SECTION_LABEL = "contingent risk cost"
TIME_SECTION_LABEL = "time (working days)"

DEFAULT_DISTRIBUTION = "PERT"
DEFAULT_CG = "CG_UNASSIGNED"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val, default=0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace("$", "")
    if s in ("", "#REF!", "#N/A", "#VALUE!", "None", "nan"):
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def _safe_str(val, default="") -> str:
    if val is None:
        return default
    s = str(val).strip()
    return default if s in ("#REF!", "#N/A", "#VALUE!", "None", "nan", "") else s


def _safe_col(row: tuple, col_idx: int | None) -> object:
    if col_idx is None:
        return None
    if col_idx < len(row):
        return row[col_idx]
    return None


def _find_columns_v5(
    sheet,
    header_row: int,
    search_terms: dict[str, list[str]],
    min_col: int = 0,
    max_col: int | None = None,
) -> dict[str, int | None]:
    """Scan header row and return {field_name: col_index} map.

    Uses case-insensitive prefix matching to handle headers with embedded
    newlines or openpyxl deduplication suffixes.

    Parameters
    ----------
    min_col : only match columns at or after this 0-based index
    max_col : only match columns before this 0-based index (None = no limit)
    """
    row_data = list(sheet.iter_rows(
        min_row=header_row, max_row=header_row, values_only=True,
    ))
    if not row_data or not row_data[0]:
        return {}

    headers = row_data[0]
    # Build (index, normalised_text) pairs for non-empty cells
    header_pairs: list[tuple[int, str]] = []
    for idx, val in enumerate(headers):
        if val is not None:
            header_pairs.append((idx, str(val).strip().lower()))

    col_map: dict[str, int | None] = {}

    for field, names in search_terms.items():
        found = None
        # Exact match first
        for name in names:
            nl = name.lower()
            for idx, low in header_pairs:
                if idx < min_col:
                    continue
                if max_col is not None and idx >= max_col:
                    continue
                if low == nl:
                    found = idx
                    break
            if found is not None:
                break
        # Prefix match fallback
        if found is None:
            for name in names:
                nl = name.lower()
                for idx, low in header_pairs:
                    if idx < min_col:
                        continue
                    if max_col is not None and idx >= max_col:
                        continue
                    if low.startswith(nl):
                        found = idx
                        break
                if found is not None:
                    break
        col_map[field] = found

    return col_map


def _find_section_bounds(sheet, section_row: int, section_label: str) -> tuple[int, int | None]:
    """Find the column range for a section in the section header row.

    Returns (start_col, end_col) where end_col is the start of the next
    section or None if it's the last section.
    """
    row_data = list(sheet.iter_rows(
        min_row=section_row, max_row=section_row, values_only=True,
    ))
    if not row_data or not row_data[0]:
        raise ValueError(f"No section headers found in row {section_row}")

    cells = row_data[0]
    label_lower = section_label.lower()

    # SR21 §3b: harden against a missing or ambiguous band. The old code took
    # the first label match and the next non-empty cell as the end; if the
    # label matched more than one cell it would silently mis-slice. Detect the
    # ambiguity up front and raise. Output-neutral when the label is present
    # exactly once (the reference register): same (start, end) as before.
    match_indices = [
        idx for idx, val in enumerate(cells)
        if val is not None and str(val).strip().lower().startswith(label_lower)
    ]
    if not match_indices:
        raise ValueError(f"Section '{section_label}' not found in row {section_row}")
    if len(match_indices) > 1:
        raise ValueError(
            f"Section '{section_label}' is ambiguous in row {section_row}: "
            f"matches {len(match_indices)} cells at column indices "
            f"{match_indices}. Cannot determine section bounds; fix the "
            f"section-header row before re-running."
        )

    start = match_indices[0]
    # End = first non-empty cell after start (start of the next section).
    for idx in range(start + 1, len(cells)):
        if cells[idx] is not None:
            return start, idx
    return start, None  # last section extends to end of row


def _extract_cg_code(cg_label: str) -> str:
    """Extract short CG code from label like 'CG05 - Weather' -> 'CG05'."""
    if not cg_label:
        return DEFAULT_CG
    # Split on ' - ' first, then whitespace
    parts = cg_label.split(" - ")
    code = parts[0].strip()
    if code.startswith("CG") and len(code) >= 4:
        return code
    # Try splitting on whitespace
    parts = cg_label.split()
    if parts and parts[0].startswith("CG"):
        return parts[0]
    return DEFAULT_CG


# ---------------------------------------------------------------------------
# SR21: fail-loud on broken Excel references
# ---------------------------------------------------------------------------
#
# When openpyxl reads a workbook with ``data_only=True``, a formula cell that
# evaluated to an Excel error is read back as the error string ("#REF!", ...).
# The ``_safe_*`` helpers historically coerced these to a default (0.0 / ""),
# which means a broken reference in a read cell would silently produce a wrong
# headline. SR21 makes the live cost-arm read fail loud on such a cell instead,
# with a located message (sheet / cell / field / risk). Output-neutral for
# The reference register today has no has no broken references in the read
# ranges, so the scan finds nothing and the read is bit-identical.

# The full set of Excel error sentinels (the prior code only listed three).
_EXCEL_ERROR_SENTINELS: frozenset[str] = frozenset({
    "#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NAME?", "#NULL!", "#NUM!",
})


def _excel_error(val) -> str | None:
    """Return the Excel error sentinel if ``val`` is one, else ``None``."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s in _EXCEL_ERROR_SENTINELS else None


def _compose_reader_error(
    consumer: str, workbook_path, issues: list[str]
) -> str:
    return (
        f"consumer={consumer}: {RISK_REGISTER_SHEET} read failed for "
        f"workbook={workbook_path}. {len(issues)} issue(s):\n  - "
        + "\n  - ".join(issues)
    )


def _scan_columns_for_errors(
    sht, col: dict[str, int | None], risk_id_prefix: str
) -> list[str]:
    """Scan the risk rows' mapped cells for Excel error sentinels.

    Returns a list of located issue strings (sheet!cell, field, risk id). A
    row is scanned when its Risk_ID cell starts with ``risk_id_prefix`` (a real
    risk row) or is itself an error sentinel (which would otherwise cause a
    silent wrong-skip). Output-neutral when there are no error cells.
    """
    from openpyxl.utils import get_column_letter

    issues: list[str] = []
    risk_id_idx = col.get("risk_id")
    for r_off, row in enumerate(
        sht.iter_rows(min_row=DATA_START_ROW, values_only=True)
    ):
        sheet_row = DATA_START_ROW + r_off
        rid_val = _safe_col(row, risk_id_idx)
        rid_err = _excel_error(rid_val)
        rid = "" if rid_val is None else str(rid_val).strip()
        if rid_err is None and not rid.startswith(risk_id_prefix):
            continue  # not a risk row
        for field, idx in col.items():
            if idx is None:
                continue
            err = _excel_error(_safe_col(row, idx))
            if err is not None:
                cell = f"{get_column_letter(idx + 1)}{sheet_row}"
                issues.append(
                    f"{RISK_REGISTER_SHEET}!{cell} (field '{field}', "
                    f"risk {rid or '?'}): broken Excel reference {err}"
                )
    return issues


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def is_v5_register(workbook_path: str | Path) -> bool:
    """Check if a workbook is a V5 register (has both Risk Register and MC_Params)."""
    try:
        wb = openpyxl.load_workbook(str(workbook_path), read_only=True, data_only=True)
        sheets = wb.sheetnames
        wb.close()
        return RISK_REGISTER_SHEET in sheets and MC_PARAMS_SHEET in sheets
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Risk reader
# ---------------------------------------------------------------------------

def _active_risk_id_prefix() -> str:
    """Risk-ID prefix for the active project (binding-sourced, fallback 'R').

    Imported lazily so the reader never triggers a
    binding import at module load.
    """
    from src.sra.cpm.bindings import active_risk_id_prefix

    # No cross-project "R" fallback (QRAXL-01 no-defaults): if no project is
    # selected this raises NoProjectSelectedError rather than silently reading
    # another project's prefix. Callers that know it pass it to read_risks_v5.
    return active_risk_id_prefix()


def read_risks_v5(
    workbook_path: str | Path,
    *,
    risk_id_prefix: str | None = None,
) -> list[RiskInput]:
    """Read risk data from the V5 register 'Risk Register' sheet.

    Returns list of RiskInput for risks with MC Include = 'Yes'.
    Skips risks with missing or zero probability (with warning).

    ``risk_id_prefix`` selects which rows count as risks (vs header/blank
    rows). Defaults to the active project binding's ``risk_id_prefix``
    (synthetic wind ``"WT"``, synthetic road ``"KH"``); pass explicitly to override.
    """
    if risk_id_prefix is None:
        risk_id_prefix = _active_risk_id_prefix()

    workbook_path = Path(workbook_path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"Register file not found: {workbook_path}")

    wb = openpyxl.load_workbook(str(workbook_path), data_only=True, read_only=True)
    try:
        grid = list(wb[RISK_REGISTER_SHEET].iter_rows(values_only=True))
    finally:
        wb.close()
    # Delegate the section-scan / parse to the shared, I/O-free parser so the
    # Tier-1 xlwings reader (feeding the SAME parser its own grid) agrees by
    # construction. Verbatim logic move; Tier-2 numbers unchanged (QRAXL-01.0).
    return parse_risks_from_grid(grid, risk_id_prefix, source=str(workbook_path))


# ---------------------------------------------------------------------------
# Params reader
# ---------------------------------------------------------------------------

def read_params_v5(
    workbook_path: str | Path,
) -> tuple[SimConfig, list[WBSBucket], ChainConfig, dict[str, float], float]:
    """Read simulation parameters from the V5 register 'MC_Params' sheet.

    Returns the same tuple as reader.read_params() and openpyxl_reader.read_params_openpyxl():
        (config, buckets, chains, corr_coefficients, wbs_rho)

    Uses label-based scanning of column B to find values in column C.
    This is robust to row insertions/deletions.
    """
    workbook_path = Path(workbook_path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"Register file not found: {workbook_path}")

    wb = openpyxl.load_workbook(str(workbook_path), data_only=True, read_only=False)
    sht = wb[MC_PARAMS_SHEET]

    # Build label -> value map by scanning column B/C
    label_map: dict[str, object] = {}
    for row in sht.iter_rows(min_row=1, max_row=100, min_col=2, max_col=3,
                             values_only=True):
        label = row[0]
        value = row[1] if len(row) > 1 else None
        if label is not None:
            label_map[str(label).strip()] = value

    def _get(label: str, default=None):
        """Look up a value by its label text."""
        val = label_map.get(label)
        if val is not None:
            return val
        # Try prefix match for labels that may have slight variations
        label_lower = label.lower()
        for key, v in label_map.items():
            if key.lower().startswith(label_lower):
                return v
        return default

    # --- Section A: Simulation control ---
    config = SimConfig(
        n_iter=int(_safe_float(_get("Iterations (n)"), 100_000)),
        seed=stated_seed(_get(SEED_LABEL, _get(SEED_LABEL_BEFORE_CONFIGTRUTH01)),
                         where=f"{workbook_path.name} MC_Params 'Random seed'"),
        view=_safe_str(_get("Stakeholder view"), "All"),
        reporting_p_level=int(_safe_float(_get("Reporting P-Level (pct)"), 80)),
        bop_contract=_safe_float(_get("BOP Contract Price ($)"), 0),
        bop_contingency=_safe_float(_get("BOP Contingency ($)"), 0),
        cse_contingency=_safe_float(_get("CSE Contingency ($)"), 0),
        # SP18a — bootstrap CI parameters; default if MC_Params row is missing
        bootstrap_n_blocks=int(_safe_float(_get("Bootstrap n_blocks"), 100)),
        bootstrap_n_resamples=int(_safe_float(_get("Bootstrap n_resamples"), 1000)),
        bootstrap_seed=stated_seed(_get("Bootstrap seed"),
                                   where=f"{workbook_path.name} MC_Params 'Bootstrap seed'"),
    )

    # --- Section B: Base cost estimate ---
    config.tic = _safe_float(_get("TIC - Total Installed Cost ($)"), 0)
    pool_budget = _safe_float(_get("Shared Risk Pool ($)"), 0)
    if pool_budget > 0:
        config.pool_budget = pool_budget

    # WBS buckets — scan for labelled rows in section B
    # V5 may have WBS rows below TIC; for now use headless defaults if none found
    buckets: list[WBSBucket] = []
    # (V5 register currently has TIC=0, no WBS detail — use defaults)
    if not buckets and config.tic == 0:
        buckets = []  # L2Only mode, no Layer 1

    # --- Section C: Event chain parameters ---
    chains = ChainConfig(
        c1_trigger_months=_safe_float(
            _get("Chain 1 trigger - planning delay (months)"), 3.0),
        c1_amplification=_safe_float(
            _get("Chain 1 - weather amplification factor"), 2.5),
        c2_trigger_weeks=_safe_float(
            _get("Chain 2 trigger - site estab delay (weeks)"), 2.0),
        c2_cascade_factor=_safe_float(
            _get("Chain 2 - cascade factor"), 1.5),
        cascade_enabled=bool(_safe_float(_get("Cascade enabled"), 0)),
        cascade_slip_rate=_safe_float(_get("Cascade slip rate"), 1.5),
        cascade_slip_cap=_safe_float(_get("Cascade slip cap"), 3.0),
        cascade_cost_scale_rate=_safe_float(_get("Cascade cost scale"), 0.5),
    )

    # --- Section D: Correlation coefficients ---
    corr_coefficients: dict[str, float] = {}
    for key, val in label_map.items():
        if key.startswith("CG") and " - " in key:
            cg_code = _extract_cg_code(key)
            rho = _safe_float(val, 0.0)
            corr_coefficients[cg_code] = rho

    # Fall back to the active binding's headless values for any missing CG codes /
    # the WBS cross-bucket rho (function-local import: fail-loud, binding-sourced,
    # and it keeps the module import free of a project-selection requirement).
    from src.defaults import get_headless_cg_coefficients, get_wbs_cross_bucket_rho

    if not corr_coefficients:
        corr_coefficients = get_headless_cg_coefficients()
        logger.warning("No CG coefficients found in MC_Params — using binding defaults")

    # WBS cross-bucket correlation (not in V5 MC_Params — use the binding default)
    wbs_rho = get_wbs_cross_bucket_rho()

    wb.close()
    return config, buckets, chains, corr_coefficients, wbs_rho


def read_gain_pain_v5(workbook_path: str | Path) -> GainPainConfig:
    """Read gain/pain share parameters from V5 MC_Params.

    Currently returns defaults with share_split from the sheet.
    """
    wb = openpyxl.load_workbook(str(workbook_path), data_only=True, read_only=False)
    sht = wb[MC_PARAMS_SHEET]

    # Scan for gain/pain label
    share_split = DEFAULT_GP_SHARE_SPLIT
    for row in sht.iter_rows(min_row=1, max_row=100, min_col=2, max_col=3,
                             values_only=True):
        label = str(row[0]).strip() if row[0] else ""
        val = row[1] if len(row) > 1 else None
        if label.startswith("TOC Gain/Pain share"):
            share_split = _safe_float(val, DEFAULT_GP_SHARE_SPLIT)
            break

    wb.close()
    return GainPainConfig(share_split=share_split, enabled=False)


# ---------------------------------------------------------------------------
# QRAXL-01 step 5 (contract v2, scope C) - register-driven Layer 1
# ---------------------------------------------------------------------------

_LAYER1_SHEETS = (
    "Layer1_Base", "Layer1_Factors", "Layer1_Allocation", "Layer1_Correlation",
)
_ALLOC_TRUE = {"x", "yes", "true", "1"}


def read_layer1_v5(workbook_path: str | Path) -> Layer1Config | None:
    """Read the register's four Layer-1 sheets into a ``Layer1Config``.

    Returns ``None`` when the workbook has NO Layer-1 sheets - the client
    register, so Layer 1 stays OFF (L2Only), exactly as before
    contract v2. When the sheets are present, builds the same Layer1Config
    ``layer1_showcase.build_showcase_layer1()`` produces (base in dollars,
    factors, corr set, corr_mode, declared_total).

    Fail-loud (SR21 doctrine): a malformed Layer-1 workbook (undefined factor,
    missing WBS row, base-sum off, non-PSD correlation) raises a located
    ``RegisterReadError`` composite - never a silent wrong Layer 1. Base is read
    in $M and scaled to dollars; the same arithmetic build_showcase uses, so the
    migrated config is bit-identical.
    """
    wb = openpyxl.load_workbook(workbook_path, data_only=True)
    try:
        sheets = {
            name: list(wb[name].iter_rows(values_only=True))
            for name in _PARSE_LAYER1_SHEETS if name in wb.sheetnames
        }
    finally:
        wb.close()
    # Delegate to the shared parser (same one the Tier-1 xlwings reader feeds).
    return parse_layer1_from_grids(sheets, source=str(workbook_path))
