"""
Excel reader using openpyxl — reads MC_Params and MC_Inputs without xlwings.

Parallel implementation of reader.py for environments where Excel is not
running (e.g. Jupyter notebooks, CI). Uses openpyxl in read-only + data_only
mode, which reads last-cached formula results.

Cell addresses match reader.py exactly so both readers produce identical
SimConfig, WBSBucket, ChainConfig, and RiskInput objects.
"""

import re
from pathlib import Path

import openpyxl

from src.config import SimConfig, WBSBucket, ChainConfig, RiskInput, GainPainConfig
from src.rng_streams import stated_seed
from src.register_loader import _find_columns


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sheet names
MC_PARAMS_SHEET = "MC_Params"
MC_INPUTS_SHEET = "MC_Inputs"
#: REG03 Grid_Methodology sheet - the single grid surface for CG (S2b). When a
#: register carries it, CG descriptions come from its 3rd column; else the legacy
#: MC_Params col-B scan (the reference register and older client registers).
METHODOLOGY_SHEET = "Methodology"

# Row layout
MC_INPUTS_HEADER_ROW = 3
MC_INPUTS_DATA_START = 6

# MC_Inputs expected headers (for _find_columns)
MC_INPUTS_HEADERS = {
    "risk_id": ["Risk ID"],
    "description": ["Description"],
    "owner": ["Package", "Owner"],
    "dist": ["Dist", "Distribution"],
    "cg": ["CG", "Correlation Group"],
    "mc_include": ["MC Include"],
    "probability": ["Prob %", "Prob"],
    "opt_cost": ["Opt ($)", "Opt"],
    "ml_cost": ["ML ($)", "ML"],
    "pess_cost": ["Pess ($)", "Pess"],
}

# Optional MC_Inputs columns
MC_INPUTS_OPTIONAL = {
    "basis": ["Basis"],
    "ml_days": ["ML days", "ML Days"],
    "recurrence": ["Recurrence_Type", "Recurrence"],
    "max_occ": ["Max Occ", "Max_Occ"],
}

# Defaults
DEFAULT_CG = "CG_UNASSIGNED"
DEFAULT_DISTRIBUTION = "PERT"

# Risk ID validation
RISK_ID_PREFIX = "R"


# ---------------------------------------------------------------------------
# Helpers (same logic as reader.py / register_loader.py)
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


def _cell(sht, address):
    """Read a single cell value from an openpyxl sheet."""
    return sht[address].value


def _named_cell(wb, name: str, fallback_sheet: str, fallback_address: str):
    """Read a named range value, falling back to a cell address if missing.

    Mirrors reader.py's _named() helper for openpyxl workbooks.
    """
    try:
        defn = wb.defined_names[name]
        for sheet_title, coord in defn.destinations:
            return wb[sheet_title][coord].value
    except (KeyError, StopIteration, Exception):
        return wb[fallback_sheet][fallback_address].value


def _col_range(sht, col, start_row, end_row):
    """Read a column range, returning list of values."""
    return [sht.cell(row=r, column=col).value for r in range(start_row, end_row + 1)]


def _matches_party(owner: str, party_name: str) -> bool:
    return owner.lower().startswith(party_name.lower()[:6])


def _matches_shared(owner: str, shared_label: str) -> bool:
    return owner.lower() == shared_label.lower()


def _safe_col(row: tuple, col_idx: int | None) -> object:
    """Safely access a column in a row tuple, returning None if out of bounds."""
    if col_idx is None:
        return None
    if col_idx < len(row):
        return row[col_idx]
    return None


# ---------------------------------------------------------------------------
# MC_Params reader
# ---------------------------------------------------------------------------

def read_params_openpyxl(
    wb_path: str | Path,
) -> tuple[SimConfig, list[WBSBucket], ChainConfig, dict[str, float], float]:
    """Read all parameters from MC_Params sheet via openpyxl.

    Returns the same tuple as reader.read_params():
        (config, buckets, chains, corr_coefficients, wbs_rho)

    Cell addresses match reader.py exactly. TIC and bop_contract defaults
    are kept non-zero to prevent division-by-zero when openpyxl returns
    stale formula cache=0.
    """
    wb = openpyxl.load_workbook(str(wb_path), data_only=True, read_only=False)
    sht = wb[MC_PARAMS_SHEET]

    # Section A — Simulation control
    # NOTE: TIC (C13) and bop_contract (C9) defaults kept non-zero because
    # openpyxl reads stale formula cache=0 for these formula cells.
    # Zero TIC causes division-by-zero in adequacy calculations.
    config = SimConfig(
        n_iter=int(_safe_float(_cell(sht, "C4"), 100_000)),
        seed=stated_seed(_cell(sht, "C5"), where="MC_Params!C5 (random seed)"),
        view=_safe_str(_cell(sht, "C6"), "All"),
        bop_contract=_safe_float(_cell(sht, "C9"), 300_000_000),
        bop_contingency=_safe_float(_cell(sht, "C10"), 5_000_000),
        cse_contingency=_safe_float(_cell(sht, "C11"), 5_000_000),
        tic=_safe_float(_cell(sht, "C13"), 300_000_000),
        contingency=_safe_float(_cell(sht, "C14"), 30_000_000),
        party_a_name=_safe_str(_cell(sht, "C58"), "BOP Contractor"),
        party_b_name=_safe_str(_cell(sht, "C59"), "Owner"),
        shared_label=_safe_str(_cell(sht, "C60"), "Shared"),
        programme_seasons=int(_safe_float(
            _named_cell(wb, "mc_programme_seasons", MC_PARAMS_SHEET, "C76"), 3)),
        reporting_p_level=int(_safe_float(_cell(sht, "C7"), 80)),
        # SP18a — bootstrap CI parameters; named ranges optional, default if missing
        bootstrap_n_blocks=int(_safe_float(
            _named_cell(wb, "mc_bootstrap_n_blocks", MC_PARAMS_SHEET, "ZZ1"), 100)),
        bootstrap_n_resamples=int(_safe_float(
            _named_cell(wb, "mc_bootstrap_n_resamples", MC_PARAMS_SHEET, "ZZ2"), 1000)),
        bootstrap_seed=stated_seed(
            _named_cell(wb, "mc_bootstrap_seed", MC_PARAMS_SHEET, "ZZ3"),
            where="mc_bootstrap_seed"),
    )

    # Section B — WBS cost buckets (rows 16–30, cols B–F)
    buckets = []
    for r in range(16, 31):
        label = _safe_str(sht.cell(row=r, column=2).value, f"WBS-{r - 15}")  # B
        base = _safe_float(sht.cell(row=r, column=3).value)                   # C
        lo = _safe_float(sht.cell(row=r, column=4).value)                     # D
        hi = _safe_float(sht.cell(row=r, column=5).value)                     # E
        dist = _safe_str(sht.cell(row=r, column=6).value, "Triangular")       # F
        if lo == 0 and hi == 0:
            continue
        buckets.append(WBSBucket(name=label, base_cost=base,
                                 low_var=lo, high_var=hi, distribution=dist))

    # Section C — Chain parameters
    chains = ChainConfig(
        c1_trigger_months=_safe_float(_cell(sht, "C35"), 3.0),
        c1_amplification=_safe_float(_cell(sht, "C36"), 2.5),
        c2_trigger_weeks=_safe_float(_cell(sht, "C37"), 2.0),
        c2_cascade_factor=_safe_float(_cell(sht, "C38"), 1.5),
        cascade_enabled=bool(_safe_float(_cell(sht, "C39"), 0)),
        cascade_slip_rate=_safe_float(_cell(sht, "C40"), 1.5),
        cascade_slip_cap=_safe_float(_cell(sht, "C41"), 3.0),
        cascade_cost_scale_rate=_safe_float(_cell(sht, "C42"), 0.5),
    )

    # Section D — Correlation coefficients. REG03 S2b de-landmine: ANCHOR the CG
    # scan at the mc_cg_coeffs NAMED RANGE's start row (address-independent; the reference register
    # = C27, legacy SP layout = C46) instead of a hardcoded row 46, which read the
    # meth_* block on the reference register. The dynamic scan (loop until an empty row) is otherwise
    # unchanged, so old workbooks (name at C46 or no name -> default 46) are identical.
    cg_start_row = 46
    if "mc_cg_coeffs" in wb.defined_names:
        for _sheet_title, coord in wb.defined_names["mc_cg_coeffs"].destinations:
            rng = wb[_sheet_title][coord]
            first = rng[0][0] if isinstance(rng, tuple) else rng
            cg_start_row = first.row
            break
    corr_coefficients = {}
    for i, r in enumerate(range(cg_start_row, cg_start_row + 40)):
        label = _safe_str(sht.cell(row=r, column=2).value)  # B = CG label
        val = _safe_float(sht.cell(row=r, column=3).value, 0.0)  # C = rho
        if not label and val == 0.0:
            break  # empty row = end of CG block
        corr_coefficients[f"CG{i + 1:02d}"] = val if val > 0 else 0.5

    # WBS cross-bucket correlation
    wbs_rho = _safe_float(_cell(sht, "C44"), 0.4)

    # Pool budget from contingency cell — default 0.0 (surfaces as "not configured")
    pool_budget = _safe_float(_cell(sht, "C14"), 0.0)
    if pool_budget > 0:
        config.pool_budget = pool_budget

    wb.close()
    return config, buckets, chains, corr_coefficients, wbs_rho


# ---------------------------------------------------------------------------
# MC_Inputs reader
# ---------------------------------------------------------------------------

def read_risks_openpyxl(
    wb_path: str | Path,
    config: SimConfig,
) -> list[RiskInput] | None:
    """Read risk inputs from MC_Inputs sheet via openpyxl.

    Uses header-based column lookup from row 3 to resolve column positions.
    Returns list of RiskInput filtered by config.view, or None if
    the sheet is broken (#REF! errors).
    """
    wb = openpyxl.load_workbook(str(wb_path), data_only=True, read_only=True)
    sht = wb[MC_INPUTS_SHEET]

    # Check first data cell — if #REF!, sheet is broken
    test_cell = sht.cell(row=MC_INPUTS_DATA_START, column=2).value  # B6
    if test_cell is not None and "#REF!" in str(test_cell):
        wb.close()
        return None

    # Build column map from row 3 headers
    try:
        col = _find_columns(sht, MC_INPUTS_HEADER_ROW, MC_INPUTS_HEADERS, MC_INPUTS_OPTIONAL)
    except ValueError:
        wb.close()
        return None

    risks = []
    for row in sht.iter_rows(min_row=MC_INPUTS_DATA_START, values_only=True):
        if row is None:
            continue

        rid = _safe_str(_safe_col(row, col["risk_id"]))
        if not rid or rid == "nan" or not rid.startswith(RISK_ID_PREFIX):
            continue

        # MC Include flag — require explicit inclusion
        mc_include = _safe_str(_safe_col(row, col["mc_include"]), "Yes")
        if mc_include.lower() in ("no", "false", "0"):
            continue

        desc = _safe_str(_safe_col(row, col["description"]))
        owner = _safe_str(_safe_col(row, col["owner"]))
        dist = _safe_str(_safe_col(row, col["dist"]), DEFAULT_DISTRIBUTION)
        cg = _safe_str(_safe_col(row, col["cg"]), DEFAULT_CG)
        prob = _safe_float(_safe_col(row, col["probability"]), 0.0)
        opt = _safe_float(_safe_col(row, col["opt_cost"]))
        ml = _safe_float(_safe_col(row, col["ml_cost"]))
        pess = _safe_float(_safe_col(row, col["pess_cost"]))
        ml_days = _safe_float(_safe_col(row, col.get("ml_days")))
        basis = _safe_str(_safe_col(row, col.get("basis")))

        # Filter by stakeholder view
        if config.view == "BOP":
            if not (_matches_party(owner, config.party_a_name)
                    or _matches_shared(owner, config.shared_label)):
                continue
        elif config.view == "CSE":
            if not (_matches_party(owner, config.party_b_name)
                    or _matches_shared(owner, config.shared_label)):
                continue
        elif config.view == "Shared":
            if not _matches_shared(owner, config.shared_label):
                continue

        # Recurrence (optional columns)
        rec_type = _safe_str(_safe_col(row, col.get("recurrence")))
        rec_param = _safe_float(_safe_col(row, col.get("max_occ")), 0.0)

        risks.append(RiskInput(
            risk_id=rid, description=desc, owner=owner,
            distribution=dist, correlation_group=cg,
            probability=prob, opt_cost=opt, ml_cost=ml, pess_cost=pess,
            ml_days=ml_days, basis=basis,
            recurrence_type=rec_type, recurrence_param=rec_param,
        ))

    wb.close()
    return risks


# ---------------------------------------------------------------------------
# Gain/pain config and pool budget
# ---------------------------------------------------------------------------

def read_gain_pain_config_openpyxl(wb_path: str | Path) -> GainPainConfig:
    """Read gain/pain share parameters via openpyxl.

    Currently returns defaults — gain/pain is OFF.
    """
    wb = openpyxl.load_workbook(str(wb_path), data_only=True, read_only=True)
    sht = wb[MC_PARAMS_SHEET]
    share_split = _safe_float(_cell(sht, "C8"), 0.5)
    wb.close()
    return GainPainConfig(share_split=share_split, enabled=False)


# ---------------------------------------------------------------------------
# CG map and descriptions
# ---------------------------------------------------------------------------

def read_cg_map(wb_path: str | Path) -> dict[str, str]:
    """Read risk ID -> CG group mapping from MC_Inputs sheet.

    Uses header-based column lookup from row 3 to find Risk ID and CG columns.
    Returns dict: {"R026.1": "CG01", "R027": "CG01", ...}
    Only includes rows where both risk ID and CG are non-empty.
    """
    wb = openpyxl.load_workbook(str(wb_path), data_only=True, read_only=True)
    sht = wb[MC_INPUTS_SHEET]

    # Only need risk_id and cg columns
    cg_headers = {
        "risk_id": ["Risk ID"],
        "cg": ["CG", "Correlation Group"],
    }
    try:
        col = _find_columns(sht, MC_INPUTS_HEADER_ROW, cg_headers)
    except ValueError:
        wb.close()
        return {}

    cg_map = {}
    for row in sht.iter_rows(min_row=MC_INPUTS_DATA_START, values_only=True):
        if row is None:
            continue
        rid = _safe_str(_safe_col(row, col["risk_id"]))
        cg = _safe_str(_safe_col(row, col["cg"]))
        if rid and rid.startswith(RISK_ID_PREFIX) and cg and cg.startswith("CG"):
            # Extract just the CG code (first 4 chars, e.g. "CG05")
            cg_code = cg.split(" ")[0].split("-")[0].strip()
            cg_map[rid] = cg_code
    wb.close()
    return cg_map


def read_dist_map(wb_path: str | Path) -> dict[str, str]:
    """Read risk ID -> distribution type mapping from MC_Inputs sheet.

    Uses header-based column lookup from row 3 to find Risk ID and Dist columns.
    Returns dict: {"R001": "PERT", "R002": "PERT", ...}
    Only includes rows where both risk ID and Dist are non-empty.
    """
    wb = openpyxl.load_workbook(str(wb_path), data_only=True, read_only=True)
    sht = wb[MC_INPUTS_SHEET]

    dist_headers = {
        "risk_id": ["Risk ID"],
        "dist": ["Dist", "Distribution"],
    }
    try:
        col = _find_columns(sht, MC_INPUTS_HEADER_ROW, dist_headers)
    except ValueError:
        wb.close()
        return {}

    dist_map = {}
    for row in sht.iter_rows(min_row=MC_INPUTS_DATA_START, values_only=True):
        if row is None:
            continue
        rid = _safe_str(_safe_col(row, col["risk_id"]))
        dist = _safe_str(_safe_col(row, col["dist"]))
        if rid and rid.startswith(RISK_ID_PREFIX) and dist:
            dist_map[rid] = dist.strip()
    wb.close()
    return dist_map


_CG_CELL_PATTERN = re.compile(r"^\s*(CG\d{2})\b\s*[-–—:]?\s*(.*?)\s*$")


# SR21: Excel error sentinels (full set; the _safe_* helpers above list a
# subset for historical reasons).
_CG_EXCEL_ERROR_SENTINELS: frozenset[str] = frozenset({
    "#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NAME?", "#NULL!", "#NUM!",
})


class CgBlockError(ValueError):
    """Raised when the MC_Params CG description block is malformed.

    Composite: every located issue (broken reference, duplicate CG code) is
    collected into a single error. Output-neutral for a well-formed block
    (the reference register): no issues, the same ``{CG_ID: description}`` dict as before.
    """


def _read_cg_descriptions_from_grid(sht) -> dict[str, str]:
    """REG03 S2b: read CG descriptions from the Grid_Methodology 3rd column.

    Col A = CG code (``CGnn``); col C = the bare description (e.g. "Labour"). Same
    ``{CG_ID: description}`` shape and fail-loud discipline as the col-B scan: a
    duplicate CG code raises a located ``CgBlockError``; a blank col C yields ``""``.
    Mode-multiplier rows (Series/Hybrid/Parallel) are skipped (not ``CGnn``).
    """
    descriptions: dict[str, str] = {}
    issues: list[str] = []
    for r in range(1, 200):
        code = sht.cell(row=r, column=1).value
        if code is None:
            continue
        code = str(code).strip().upper()
        if not (len(code) == 4 and code[:2] == "CG" and code[2:].isdigit()):
            continue
        if code in descriptions:
            issues.append(
                f"{METHODOLOGY_SHEET}!A{r}: duplicate CG code {code} "
                f"(already defined earlier in column A)"
            )
            continue
        desc = sht.cell(row=r, column=3).value
        descriptions[code] = str(desc).strip() if desc is not None else ""
    if issues:
        raise CgBlockError(
            f"Grid_Methodology CG description column malformed. {len(issues)} "
            f"issue(s):\n  - " + "\n  - ".join(issues)
        )
    return descriptions


def _read_cg_descriptions_from_open_wb(wb) -> dict[str, str]:
    """Inner parser — operates on an already-open openpyxl workbook.

    Shared by :func:`read_cg_descriptions` (which opens its own
    workbook) and by callers that already have one open (e.g.
    ``assumptions_writer.write_assumptions`` — Beta-17 SSoT). Walks
    MC_Params column B, parses any cell matching
    ``CG{NN}[separator description]``, returns ``{CG_ID: description}``
    (description may be ``""`` when the cell has only the prefix).

    Row-agnostic scan over a generous bound (200 rows) so schema drift
    in either direction is tolerated.

    SR21 §3a/§3c: the scan fails loud on a malformed block -- a broken Excel
    reference where a CG label should be, or a duplicate CG code (which the
    old code silently overwrote, last-wins) -- with a located message. A
    well-formed block reads identically.

    REG03 S2b (D0=B): PREFER the register's own ``Grid_Methodology`` description
    column (col C) when the register carries a Methodology grid (scaffolded,
    grid-native); else fall back to the MC_Params col-B scan (the reference register and older
    client registers have no Methodology sheet -> this path -> byte-unchanged).
    """
    if METHODOLOGY_SHEET in wb.sheetnames:
        return _read_cg_descriptions_from_grid(wb[METHODOLOGY_SHEET])
    sht = wb[MC_PARAMS_SHEET]
    descriptions: dict[str, str] = {}
    issues: list[str] = []
    for r in range(1, 200):
        cell_value = sht.cell(row=r, column=2).value
        if cell_value is None:
            continue
        s = str(cell_value).strip()
        if s in _CG_EXCEL_ERROR_SENTINELS:
            issues.append(f"{MC_PARAMS_SHEET}!B{r}: broken Excel reference {s}")
            continue
        m = _CG_CELL_PATTERN.match(s)
        if not m:
            continue
        cg_id = m.group(1).upper()
        if cg_id in descriptions:
            issues.append(
                f"{MC_PARAMS_SHEET}!B{r}: duplicate CG code {cg_id} "
                f"(already defined earlier in column B)"
            )
            continue
        descriptions[cg_id] = m.group(2).strip()
    if issues:
        raise CgBlockError(
            f"MC_Params CG description block malformed. {len(issues)} "
            f"issue(s):\n  - " + "\n  - ".join(issues)
        )
    return descriptions


def read_cg_descriptions(wb_path: str | Path) -> dict[str, str]:
    """Read CG code → description mapping from the MC_Params CG block.

    Single source of truth for CG driver descriptions. Walks column B of
    the MC_Params sheet, parses any cell matching ``CG{NN}[- description]``,
    and returns ``{"CG01": "Labour", "CG02": "Design", ...}``. The
    description is the trimmed text after the ``CG{NN}`` prefix and any
    optional separator (``-``, ``–``, ``—``, ``:``); an empty description
    yields ``""`` for that key so the caller can distinguish "CG present
    in register but unnamed" from "CG absent from register entirely".

    The scan is row-agnostic: V8 places the block at rows ~30-42 with
    cells like ``"CG01 - Labour"``; earlier register revisions placed it
    around rows 46-58. The full MC_Params column-B range is checked so
    schema drift cannot silently produce an empty result.

    No-fallback policy (Beta-17 SSoT cleanup): callers MUST NOT fall back
    to any hardcoded dict when this returns no rows or is missing an
    expected CG. A blank cell in the deliverable is the correct response
    to "register has no description for this CG"; the absence is visible
    to the reader of the deliverable. If the workbook structure is broken
    (e.g. MC_Params sheet missing), this function raises and the
    deliverable build halts — no silent degradation.

    Uses read_only=False because random cell access via
    ``sht.cell(row, column)`` is not supported in read-only mode.
    """
    wb = openpyxl.load_workbook(str(wb_path), data_only=True, read_only=False)
    try:
        return _read_cg_descriptions_from_open_wb(wb)
    finally:
        wb.close()
