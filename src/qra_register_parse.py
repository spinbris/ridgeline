"""QRAXL-01 step 6a - the shared, I/O-free contract-v2 parser.

ONE parser, two readers. Tier 2 reads the register with openpyxl; Tier 1 reads
the SAME workbook with xlwings ranges. Both extract a plain GRID of cell values
(``list`` of row-tuples, ``grid[i]`` == Excel row ``i+1``) and feed it to the
functions here, which do all the section-scan / column-find / parse work and
return the ``RiskInput`` list + ``Layer1Config``. Because both readers share
this parser, Tier-1 == Tier-2 on the read side is STRUCTURAL, not just tested -
the same discipline that made ``qra_core`` bit-identical by construction.

The logic below is a MOVE, not a rewrite: it is the exact body of
``v5_register_reader.read_risks_v5`` / ``read_layer1_v5`` with the openpyxl
sheet object replaced by a grid. ``read_risks_v5`` / ``read_layer1_v5`` now
extract the grid and delegate here, so the Tier-2 numbers are unchanged (locked
by the QRAXL-01.0 raw-== gate).

Pyodide-clean: numpy + ``src.config`` (RiskInput) + ``src.layer1_factors`` only -
NO openpyxl, NO pandas. Safe inside qra_core's Tier-1 import closure.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from src.config import ChainConfig, RiskInput
from src.sra.mode_multipliers import resolve_mode_multiplier
from src.layer1_factors import Factor, Layer1Config, nearest_psd, validate_layer1

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Contract constants (mirrors v5_register_reader)
# ---------------------------------------------------------------------------

RISK_REGISTER_SHEET = "Risk Register"
SECTION_HEADER_ROW = 3
HEADER_ROW = 4
DATA_START_ROW = 5

CONTINGENT_SECTION_LABEL = "contingent risk cost"
TIME_SECTION_LABEL = "time (working days)"
DEFAULT_DISTRIBUTION = "PERT"
DEFAULT_CG = "CG_UNASSIGNED"

_LAYER1_SHEETS = (
    "Layer1_Base", "Layer1_Factors", "Layer1_Allocation", "Layer1_Correlation",
)
_ALLOC_TRUE = {"x", "yes", "true", "1"}

# QRAXL-01 GD-B - the methodology surface (CG coefficients + mode multipliers)
# is read from the register's OWN "Methodology" grid via
# resolve_methodology_from_grid, NOT a hardcoded constant. Under the no-defaults
# directive there is no fallback: a register missing the methodology grid fails
# loud. (Pre-GD-B this module inlined METHODOLOGY_CG_COEFFICIENTS / the Mode multiplier grid
# - one project's values applied to any register. Those are removed so Tier 1
# applies each project's OWN methodology, never a cross-project constant.)
_METHODOLOGY_SHEET = "methodology"  # the grids-dict key both readers use
_MODE_MULTIPLIER_NAMES: tuple[str, ...] = ("Series", "Hybrid", "Parallel")
#: RS-D-2 (D-14): the methodology grid's calibration-tolerance rows, label -> config field.
_GRID_TOLERANCE_LABELS: dict[str, str] = {
    "Cost_Calibration_Tolerance_Dollars": "cost_calibration_tolerance_dollars",
    "Cost_Calibration_Tolerance_Pct": "cost_calibration_tolerance_pct",
    "Schedule_Calibration_Tolerance_Days": "schedule_calibration_tolerance_days",
    "Schedule_Calibration_Tolerance_Pct": "schedule_calibration_tolerance_pct",
    # Stage 4 F-30 (Director, 08/09/2026): the cross-validation's schedule top-3 check treats two
    # contributors the arms rank apart as one tie when they are within this fraction of each other
    # in BOTH arms. A register value, by the Director's ruling - not a code constant.
    "Schedule_Top3_Tie_Tolerance_Pct": "schedule_top3_tie_tolerance_pct",
}
#: RS-D-6 (D-18): the register's default injection method for dual-coded risks.
_GRID_INJECTION_LABEL = "Default_Injection_Method"
_INJECTION_METHOD_NAMES = ("additive_pert_days", "discrete_event_additive_days",
                           "productivity_multiplicative_factor")

# chain_risk_ids for a register with no binding-declared chains (wind / Tier-1):
# all-None -> chains skip cleanly in run_cost_layer.
_EMPTY_CHAIN_RISK_IDS: dict[str, Any] = {
    "c1_trigger": None, "c1_target": None, "c2_trigger": None, "c2_targets": [],
}

_EXCEL_ERROR_SENTINELS: frozenset[str] = frozenset({
    "#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NAME?", "#NULL!", "#NUM!",
})

# A grid is a list of row sequences; grid[i] is Excel row i+1.
Grid = list


class RegisterReadError(ValueError):
    """Raised on a broken reference or malformed band. Composite: every located
    issue is collected so the Director sees the full diagnostic in one pass."""


# ---------------------------------------------------------------------------
# Value coercion (verbatim from v5_register_reader)
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


def _safe_col(row, col_idx: int | None):
    if col_idx is None:
        return None
    if col_idx < len(row):
        return row[col_idx]
    return None


def _excel_error(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s in _EXCEL_ERROR_SENTINELS else None


def _extract_cg_code(cg_label: str) -> str:
    if not cg_label:
        return DEFAULT_CG
    parts = cg_label.split(" - ")
    code = parts[0].strip()
    if code.startswith("CG") and len(code) >= 4:
        return code
    parts = cg_label.split()
    if parts and parts[0].startswith("CG"):
        return parts[0]
    return DEFAULT_CG


def _col_letter(idx0: int) -> str:
    """0-based column index -> Excel letter (pure; replaces openpyxl get_column_letter)."""
    n = idx0 + 1
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _compose_reader_error(consumer: str, source, issues: list[str]) -> str:
    return (
        f"consumer={consumer}: {RISK_REGISTER_SHEET} read failed for "
        f"source={source}. {len(issues)} issue(s):\n  - " + "\n  - ".join(issues)
    )


# ---------------------------------------------------------------------------
# Grid scanning (verbatim logic, sheet -> grid)
# ---------------------------------------------------------------------------

def _grid_row(grid: Grid, row_1based: int):
    idx = row_1based - 1
    if 0 <= idx < len(grid):
        return grid[idx] or ()
    return ()


def find_columns(
    grid: Grid, header_row: int, search_terms: dict[str, list[str]],
    min_col: int = 0, max_col: int | None = None,
) -> dict[str, int | None]:
    """Scan a header row and return {field_name: col_index}. Case-insensitive
    exact-then-prefix match, bounded to [min_col, max_col)."""
    headers = _grid_row(grid, header_row)
    if not headers:
        return {}
    header_pairs = [
        (idx, str(val).strip().lower())
        for idx, val in enumerate(headers) if val is not None
    ]
    col_map: dict[str, int | None] = {}
    for field, names in search_terms.items():
        found = None
        for name in names:  # exact match first
            nl = name.lower()
            for idx, low in header_pairs:
                if idx < min_col or (max_col is not None and idx >= max_col):
                    continue
                if low == nl:
                    found = idx
                    break
            if found is not None:
                break
        if found is None:  # prefix fallback
            for name in names:
                nl = name.lower()
                for idx, low in header_pairs:
                    if idx < min_col or (max_col is not None and idx >= max_col):
                        continue
                    if low.startswith(nl):
                        found = idx
                        break
                if found is not None:
                    break
        col_map[field] = found
    return col_map


def find_section_bounds(grid: Grid, section_row: int, section_label: str) -> tuple[int, int | None]:
    """Column range for a section header; raises on missing/ambiguous band (SR21)."""
    cells = _grid_row(grid, section_row)
    if not cells:
        raise ValueError(f"No section headers found in row {section_row}")
    label_lower = section_label.lower()
    match_indices = [
        idx for idx, val in enumerate(cells)
        if val is not None and str(val).strip().lower().startswith(label_lower)
    ]
    if not match_indices:
        raise ValueError(f"Section '{section_label}' not found in row {section_row}")
    if len(match_indices) > 1:
        raise ValueError(
            f"Section '{section_label}' is ambiguous in row {section_row}: "
            f"matches {len(match_indices)} cells at column indices {match_indices}. "
            f"Cannot determine section bounds; fix the section-header row."
        )
    start = match_indices[0]
    for idx in range(start + 1, len(cells)):
        if cells[idx] is not None:
            return start, idx
    return start, None


def _scan_grid_for_errors(grid: Grid, col: dict[str, int | None], risk_id_prefix: str) -> list[str]:
    issues: list[str] = []
    risk_id_idx = col.get("risk_id")
    for r_off, row in enumerate(grid[DATA_START_ROW - 1:]):
        sheet_row = DATA_START_ROW + r_off
        rid_val = _safe_col(row or (), risk_id_idx)
        rid_err = _excel_error(rid_val)
        rid = "" if rid_val is None else str(rid_val).strip()
        if rid_err is None and not rid.startswith(risk_id_prefix):
            continue
        for field, idx in col.items():
            if idx is None:
                continue
            err = _excel_error(_safe_col(row or (), idx))
            if err is not None:
                cell = f"{_col_letter(idx)}{sheet_row}"
                issues.append(
                    f"{RISK_REGISTER_SHEET}!{cell} (field '{field}', "
                    f"risk {rid or '?'}): broken Excel reference {err}"
                )
    return issues


# ---------------------------------------------------------------------------
# Risk rows: grid -> list[RiskInput]  (verbatim body of read_risks_v5)
# ---------------------------------------------------------------------------

def parse_risks_from_grid(grid: Grid, risk_id_prefix: str, source: str = "<grid>") -> list[RiskInput]:
    id_terms = {
        "risk_id": ["Risk ID"],
        "risk_status": ["Risk Status"],
        "description": ["Risk Description"],
        "package": ["Package"],
        "rbs_l1": ["RBS LVL 1"],
        "rbs_l2": ["RBS LVL 2"],
        "causes": ["Causes"],
        "consequences": ["Consequences"],
        "controls": ["Existing Controls"],
        "ctrl_effectiveness": ["Control Effectiveness"],
        "mc_include": ["MC Include"],
        "distribution": ["Distribution"],
        "corr_group": ["Correlation Group"],
        "recurrence": ["Recurrence Type"],
        "risk_owner": ["Risk Owner"],
        "planned_day": ["Planned_Day", "Planned Day"],
    }
    col = find_columns(grid, HEADER_ROW, id_terms)
    for key in ("risk_id", "mc_include"):
        if col.get(key) is None:
            raise ValueError(f"Required column '{key}' not found in V5 register headers")

    try:
        cont_start, cont_end = find_section_bounds(grid, SECTION_HEADER_ROW, CONTINGENT_SECTION_LABEL)
    except ValueError:
        raise ValueError("Cannot find 'Contingent Risk Cost' section in row 3")
    cont_terms = {
        "cost_impact": ["Cost Impact"],
        "probability": ["Probability"],
        "opt_cost": ["Optimistic ($)", "Optimistic"],
        "ml_cost": ["Most Likely ($)", "Most Likely"],
        "pess_cost": ["Pessimistic ($)", "Pessimistic"],
        "basis": ["Basis of Estimate"],
    }
    col.update(find_columns(grid, HEADER_ROW, cont_terms, min_col=cont_start, max_col=cont_end))

    try:
        time_start, time_end = find_section_bounds(grid, SECTION_HEADER_ROW, TIME_SECTION_LABEL)
        time_terms = {
            "time_impact": ["Time Impact"],
            "time_prob": ["Probability"],
            "opt_days": ["Optimistic"],
            "ml_days": ["Most Likely"],
            "pess_days": ["Pessimistic"],
            "time_basis": ["Basis of Estimate"],
        }
        col.update(find_columns(grid, HEADER_ROW, time_terms, min_col=time_start, max_col=time_end))
    except ValueError:
        logger.info("No Time section found — schedule fields will be zero")

    read_errors = _scan_grid_for_errors(grid, col, risk_id_prefix)
    if read_errors:
        raise RegisterReadError(_compose_reader_error("read_risks_v5", source, read_errors))

    risks: list[RiskInput] = []
    skipped_zero_prob = 0
    for row in grid[DATA_START_ROW - 1:]:
        row = row or ()
        risk_id = _safe_str(_safe_col(row, col["risk_id"]))
        if not risk_id or not risk_id.startswith(risk_id_prefix):
            continue
        mc_include = _safe_str(_safe_col(row, col["mc_include"]))
        if mc_include.lower() != "yes":
            continue
        probability = _safe_float(_safe_col(row, col.get("probability")))
        if probability <= 0:
            skipped_zero_prob += 1
            logger.warning("Risk %s has zero/missing probability — skipped", risk_id)
            continue
        opt_cost = _safe_float(_safe_col(row, col.get("opt_cost")))
        ml_cost = _safe_float(_safe_col(row, col.get("ml_cost")))
        pess_cost = _safe_float(_safe_col(row, col.get("pess_cost")))
        distribution = _safe_str(_safe_col(row, col.get("distribution")), DEFAULT_DISTRIBUTION)
        correlation_group = _extract_cg_code(_safe_str(_safe_col(row, col.get("corr_group"))))
        description = _safe_str(_safe_col(row, col.get("description")))
        direction = ("Opportunity" if description.lower().startswith("opportunity") else "Threat")
        risk_status = _safe_str(_safe_col(row, col.get("risk_status")), "Open")
        owner = _safe_str(_safe_col(row, col.get("package")))
        if not owner:
            owner = _safe_str(_safe_col(row, col.get("risk_owner")))
        cause = _safe_str(_safe_col(row, col.get("causes")))
        consequence = _safe_str(_safe_col(row, col.get("consequences")))
        controls = _safe_str(_safe_col(row, col.get("controls")))
        basis = _safe_str(_safe_col(row, col.get("basis")))
        # REPORT01 D-3: the Time section carries its own "Basis of Estimate". Both
        # columns share that header and are told apart only by their section band, so
        # this reads col["time_basis"] - resolved inside the Time bounds above - and
        # never col["basis"]. Absent Time section => key absent => "" (P-5: blank stays
        # blank, so the report can say "not recorded" rather than imply agreement).
        time_basis = _safe_str(_safe_col(row, col.get("time_basis")))
        recurrence_type = _safe_str(_safe_col(row, col.get("recurrence")))
        opt_sched = _safe_float(_safe_col(row, col.get("opt_days")))
        ml_sched = _safe_float(_safe_col(row, col.get("ml_days")))
        pess_sched = _safe_float(_safe_col(row, col.get("pess_days")))
        rbs_l1 = _safe_str(_safe_col(row, col.get("rbs_l1")))
        rbs_l2 = _safe_str(_safe_col(row, col.get("rbs_l2")))
        planned_day = int(_safe_float(_safe_col(row, col.get("planned_day"))))
        risks.append(RiskInput(
            risk_id=risk_id, description=description, owner=owner,
            distribution=distribution, correlation_group=correlation_group,
            probability=probability, opt_cost=opt_cost, ml_cost=ml_cost,
            pess_cost=pess_cost, ml_days=ml_sched, mc_include=True, basis=basis,
            time_basis=time_basis,
            recurrence_type=recurrence_type, opt_schedule_days=opt_sched,
            pess_schedule_days=pess_sched, cause=cause, consequence=consequence,
            existing_controls=controls, risk_status=risk_status, direction=direction,
            rbs_l1=rbs_l1, rbs_l2=rbs_l2, planned_day=planned_day,
        ))

    rbs_col_idx = col.get("rbs_l1")
    rbs_header = _safe_col(_grid_row(grid, HEADER_ROW), rbs_col_idx) if rbs_col_idx is not None else None
    if skipped_zero_prob > 0:
        logger.warning("Skipped %d risks with zero/missing probability", skipped_zero_prob)
    logger.info("Loaded %d risks from V5 register (MC Include=Yes)", len(risks))
    n_total = len(risks)
    n_blank = sum(1 for r in risks if not r.rbs_l1)
    blank_pct = n_blank / n_total if n_total else 0.0
    logger.info(
        "RBS L1 load: col_idx=%s, header=%r, non-blank=%d/%d, first5=%s",
        rbs_col_idx, rbs_header, n_total - n_blank, n_total, [r.rbs_l1 for r in risks[:5]],
    )
    if n_total > 0 and blank_pct > 0.5:
        logger.warning(
            "RBS L1 is blank on %d/%d risks (%.0f%%) — per-category analysis will "
            "collapse to '(Uncategorised)'. Check the 'RBS LVL 1' header (col %s).",
            n_blank, n_total, blank_pct * 100, rbs_col_idx,
        )
    return risks


# ---------------------------------------------------------------------------
# Aux inputs: grid -> {cg_coefficients, dual_lookup, chain_risk_ids, chain_config}
# (QRAXL-01 step 6b - the full run_cost_layer input set, Pyodide-clean)
# ---------------------------------------------------------------------------

def resolve_methodology_from_grid(
    grid: Grid, source: str = "<methodology grid>"
) -> dict[str, dict[str, float]]:
    """Read the methodology surface (CG coefficients + mode multipliers) from the
    register's own "Methodology" grid. Pyodide-clean; fed by both readers.

    The grid is a two-column (label, value) block: each ``CGnn`` row contributes a
    CG coefficient, and each of the three mode-name rows (Series / Hybrid /
    Parallel) contributes a mode multiplier. Returns
    ``{"cg_coefficients": {...}, "mode_multipliers": {...}}``.

    Fail-loud (SR21 / the no-defaults directive): a missing / empty / malformed
    methodology grid raises ``RegisterReadError`` - there is NO fallback to a
    cross-project constant. Every located issue is collected into one error.
    """
    issues: list[str] = []
    cg: dict[str, float] = {}
    mode_mult: dict[str, float] = {}
    tolerances: dict[str, float] = {}
    injection_method: str | None = None
    seen: set[str] = set()
    for r_off, row in enumerate(grid or ()):
        row = row or ()
        label = _safe_str(_safe_col(row, 0))
        if not label:
            continue
        is_cg = label.startswith("CG") and len(label) == 4 and label[2:].isdigit()
        is_tol = label in _GRID_TOLERANCE_LABELS
        is_inj = label == _GRID_INJECTION_LABEL
        if not (is_cg or label in _MODE_MULTIPLIER_NAMES or is_tol or is_inj):
            continue  # unknown labels are ignored, never absorbed (RS-D-3 review, GRIDPARSE-01)
        if label in seen:  # an exact duplicate row is a register defect, not a last-wins
            issues.append(f"{_METHODOLOGY_SHEET} row {r_off + 1}: {label!r} appears more than once")
            continue
        seen.add(label)
        raw = _safe_col(row, 1)
        if is_inj:
            text = _safe_str(raw)
            if text not in _INJECTION_METHOD_NAMES:
                issues.append(
                    f"{_METHODOLOGY_SHEET} row {r_off + 1}: {label!r} is {text!r}, not one of "
                    f"{list(_INJECTION_METHOD_NAMES)}")
                continue
            injection_method = text
            continue
        try:
            val = float(raw)  # None / non-numeric -> ValueError/TypeError below
        except (TypeError, ValueError):
            issues.append(
                f"{_METHODOLOGY_SHEET} row {r_off + 1}: {label!r} has non-numeric "
                f"value {raw!r}")
            continue
        if is_tol:
            tolerances[_GRID_TOLERANCE_LABELS[label]] = val
        else:
            (cg if is_cg else mode_mult)[label] = val
    if not cg:
        issues.append("no CG coefficients (CGnn label rows) found")
    missing_modes = [m for m in _MODE_MULTIPLIER_NAMES if m not in mode_mult]
    if missing_modes:
        issues.append(
            f"missing mode multiplier row(s): {missing_modes} "
            f"(need all of {list(_MODE_MULTIPLIER_NAMES)})")
    if issues:
        raise RegisterReadError(_compose_reader_error(
            "resolve_methodology_from_grid", source, issues))
    # RS-D parts 2/6: the settings rows are optional at the parser (older grid-native
    # registers and test grids carry none); the readers that need them refuse when absent.
    return {"cg_coefficients": cg, "mode_multipliers": mode_mult,
            "calibration_tolerances": tolerances, "default_injection_method": injection_method}


def resolve_dual_lookup_from_grid(
    grid: Grid, risk_id_prefix: str, mode_multipliers: dict[str, float],
) -> dict[str, dict[str, Any]]:
    """dual_lookup = the Time-Impact=Yes (dual-coded) risks, grid-derived.

    Reproduces the Tier-2 ``_resolve_modes`` output: for each Time=Yes risk,
    ``{mode_multiplier=mode_multipliers[mode], mode, opt_d, ml_d, pess_d}`` from
    the Risk Register grid (Mode column + Time-section three-point days). The
    ``mode_multipliers`` come from the register's own methodology grid
    (resolve_methodology_from_grid), NOT a hardcoded constant. No pandas /
    read_risk_scope - the same grid the risk parser reads.
    """
    col = find_columns(grid, HEADER_ROW, {"risk_id": ["Risk ID"], "mode": ["Mode"]})
    try:
        t_start, t_end = find_section_bounds(grid, SECTION_HEADER_ROW, TIME_SECTION_LABEL)
        col.update(find_columns(grid, HEADER_ROW, {
            "time_impact": ["Time Impact"],
            "opt_days": ["Optimistic"], "ml_days": ["Most Likely"],
            "pess_days": ["Pessimistic"],
        }, min_col=t_start, max_col=t_end))
    except ValueError:
        return {}  # no Time section -> no dual-coded risks

    dual: dict[str, dict[str, Any]] = {}
    for row in grid[DATA_START_ROW - 1:]:
        row = row or ()
        rid = _safe_str(_safe_col(row, col.get("risk_id")))
        if not rid or not rid.startswith(risk_id_prefix):
            continue
        if _safe_str(_safe_col(row, col.get("time_impact"))).lower() != "yes":
            continue
        mode = _safe_str(_safe_col(row, col.get("mode")))
        dual[rid] = {
            "mode_multiplier": resolve_mode_multiplier(mode, mode_multipliers, rid),  # RS-D-3
            "mode": mode,
            "opt_d": _safe_float(_safe_col(row, col.get("opt_days"))),
            "ml_d": _safe_float(_safe_col(row, col.get("ml_days"))),
            "pess_d": _safe_float(_safe_col(row, col.get("pess_days"))),
        }
    return dual


def resolve_aux_from_grid(
    risk_grid: Grid, methodology_grid: Grid, risk_id_prefix: str,
) -> dict[str, Any]:
    """Resolve the full run_cost_layer aux input set from the register grids.

    Returns ``{cg_coefficients, dual_lookup, chain_risk_ids, chain_config}`` -
    Pyodide-clean, reproducing exactly what the Tier-2 integrated cost arm passes
    to ``run_cost_layer`` (verified deep-equal by the step-6b read-parity gate):
    cg + mode multipliers come from the register's OWN methodology grid
    (GD-B - no cross-project constant); dual_lookup = grid-derived using those
    mode multipliers; chain_config = ChainConfig() default; chain_risk_ids =
    all-None (chains off for a register with no declared chains). Fail-loud if the
    methodology grid is absent/malformed.
    """
    methodology = resolve_methodology_from_grid(methodology_grid)
    return {
        "cg_coefficients": dict(methodology["cg_coefficients"]),
        "dual_lookup": resolve_dual_lookup_from_grid(
            risk_grid, risk_id_prefix, methodology["mode_multipliers"]),
        "chain_risk_ids": {k: (list(v) if isinstance(v, list) else v)
                           for k, v in _EMPTY_CHAIN_RISK_IDS.items()},
        "chain_config": ChainConfig(),
    }


# ---------------------------------------------------------------------------
# Layer-1 sheets: grids -> Layer1Config  (verbatim body of read_layer1_v5)
# ---------------------------------------------------------------------------

def parse_layer1_from_grids(sheets: dict[str, Grid], source: str = "<grids>") -> Layer1Config | None:
    """Build the Layer1Config from the four Layer-1 sheet grids. ``sheets`` maps
    sheet name -> grid, containing ONLY the Layer-1 sheets present in the
    workbook. Returns None when none are present (client register -> Layer 1 OFF).
    Fail-loud (SR21) on a malformed set."""
    present = [s for s in _LAYER1_SHEETS if s in sheets]
    if not present:
        return None
    if len(present) != len(_LAYER1_SHEETS):
        missing = [s for s in _LAYER1_SHEETS if s not in sheets]
        raise RegisterReadError(_compose_reader_error(
            "read_layer1_v5", source, [f"partial Layer-1 sheet set: missing {missing}"]))

    issues: list[str] = []

    def _num(what: str, field: str, v) -> float:
        """A number, or a named issue. REGUX-01 A-0.4: this was ``float(v)`` and a blank
        cell surfaced as a raw TypeError; the template now ships its grids blank on
        purpose, so blank has to be refused by name."""
        if isinstance(v, bool):
            v = int(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            issues.append(f"{what}: {field} is {'blank' if v is None else repr(v)}, "
                          f"must be a number")
            return float("nan")

    # --- Layer1_Base: WBS rows x resource columns, $M. Values are taken by HEADER POSITION,
    # so a blank placeholder header cannot shift its neighbour's numbers onto it. A row with a
    # label and no numbers is a placeholder the project did not use (or the Units trailer) and
    # is not a WBS row; a genuine zero is typed as 0.
    bs = sheets["Layer1_Base"]
    header = list(_grid_row(bs, 1))
    col_pos = [(j, str(h)) for j, h in enumerate(header[1:]) if h is not None]
    col_labels = tuple(lbl for _, lbl in col_pos)
    row_labels: list[str] = []
    base_rows: list[list[float]] = []
    declared_total_m: float | None = None
    for row in bs[1:]:
        row = row or ()
        if not row or row[0] is None:
            continue
        label = str(row[0]).strip()
        if label.lower().startswith("declared"):
            declared_total_m = (_num("Layer1_Base", "Declared_Total", row[1])
                                if len(row) > 1 and row[1] is not None else None)
            continue
        vals = list(row[1:]) + [None] * len(header)
        cells = [vals[j] for j, _ in col_pos]
        if not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in cells):
            continue
        row_labels.append(label)
        base_rows.append([
            _num("Layer1_Base", f"{label} / {lbl}", v) if v is not None else 0.0
            for (_, lbl), v in zip(col_pos, cells)])
    base = np.array(base_rows, dtype=np.float64) * 1_000_000.0
    declared_total = None if declared_total_m is None else declared_total_m * 1_000_000.0

    factors_raw = [row for row in sheets["Layer1_Factors"][1:] if row and row[0] is not None]

    # REGUX-01 A-0.4: the template ships the grids blank, and blank is refused by name. A zero
    # grid would parse to a Layer 1 that is on and contributes nothing - silently.
    if not row_labels and not factors_raw:
        raise RegisterReadError(_compose_reader_error("read_layer1_v5", source, [
            "the Layer-1 grids are unfilled: Layer1_Base has no WBS row with numbers and "
            "Layer1_Factors has no factor rows. Fill the four Layer1_* tabs (the TOC's "
            "'Layer 1' section says how), or keep Set_Layer1_Enabled = FALSE so Layer 1 is "
            "not read"]))
    if not row_labels:
        issues.append("Layer1_Base has no WBS row with numbers in its resource columns")
    if not factors_raw:
        issues.append("Layer1_Factors has no factor rows")

    # --- Layer1_Allocation: factor x WBS ticks. Columns are matched to Base rows BY NAME. A
    # placeholder column the project left unticked is ignored; a ticked column with no Base
    # row behind it is an error, because the tick would otherwise vanish silently.
    al = sheets["Layer1_Allocation"]
    alloc_header = list(_grid_row(al, 1))
    alloc_pos = [(j, str(h)) for j, h in enumerate(alloc_header[1:]) if h is not None]
    alloc: dict[str, list[str]] = {}
    ticked: set[str] = set()
    for row in al[1:]:
        row = row or ()
        if not row or row[0] is None:
            continue
        vals = list(row[1:]) + [None] * len(alloc_header)
        bound = [lbl for j, lbl in alloc_pos
                 if vals[j] is not None and str(vals[j]).strip().lower() in _ALLOC_TRUE]
        ticked.update(bound)
        alloc[str(row[0]).strip()] = bound
    alloc_rows = tuple(lbl for _, lbl in alloc_pos if lbl in row_labels or lbl in ticked)
    for lbl in alloc_rows:
        if lbl not in row_labels:
            issues.append(
                f"Layer1_Allocation: column '{lbl}' is ticked but '{lbl}' has no numbers on "
                f"Layer1_Base - rename the column to match a filled WBS row, or clear the tick")

    # --- Layer1_Correlation: names across the header row and down column A in the same
    # order, coefficients strictly below the diagonal. Both read by header position.
    cs = sheets["Layer1_Correlation"]
    corr_mode = "elicited"
    corr_names: list[str] = []
    corr_pos: list[int] = []
    lower_by_row: list[list[float]] = []
    header_row_idx = None
    for r_i, row in enumerate(cs):
        row = row or ()
        if row and row[0] is not None and str(row[0]).strip().lower() == "corr_mode":
            corr_mode = str(row[1]).strip() if len(row) > 1 and row[1] is not None else "elicited"
        if row and row[0] is not None and str(row[0]).strip().lower() == "factor":
            header_row_idx = r_i
            corr_pos = [j for j, h in enumerate(row[1:]) if h is not None]
            corr_names = [str(row[1 + j]) for j in corr_pos]
    k = len(corr_names)
    if header_row_idx is not None and corr_names:
        for i, row in enumerate(cs[header_row_idx + 1: header_row_idx + 1 + k]):
            row = row or ()
            excel_row = header_row_idx + 2 + i
            label = str(row[0]).strip() if row and row[0] is not None else ""
            if label != corr_names[i]:
                issues.append(
                    f"Layer1_Correlation: row {excel_row} column A reads {label!r} but the "
                    f"header names {corr_names[i]!r} in that position - names must run in the "
                    f"same order across the header row and down column A")
            vals = list(row[1:]) + [None] * (max(corr_pos) + 2)
            lower_by_row.append([
                (_num("Layer1_Correlation", f"{corr_names[i]} / {corr_names[j]}", vals[p])
                 if vals[p] is not None else 0.0)
                for j, p in enumerate(corr_pos)])
            for j, p in enumerate(corr_pos):
                if j > i and vals[p] is not None:
                    issues.append(
                        f"Layer1_Correlation: {vals[p]!r} at row {excel_row} column "
                        f"{_col_letter(1 + p)} is above the diagonal and is never read - enter "
                        f"coefficients in the lower triangle only")
    corr_matrix = np.zeros((k, k), dtype=np.float64)
    for i in range(min(k, len(lower_by_row))):
        vals = lower_by_row[i]
        for j in range(min(i + 1, len(vals))):
            corr_matrix[i, j] = vals[j]
    for i in range(k):
        corr_matrix[i, i] = 1.0

    defined = {str(r[0]).strip() for r in factors_raw}
    factors: list[Factor] = []
    for raw in factors_raw:
        name, driver, opt, ml, p90, colscope = (list(raw) + [None] * 6)[:6]
        name = str(name).strip()
        cs_str = str(colscope).strip() if colscope is not None else "ALL"
        col_scope = ("ALL",) if cs_str.upper() == "ALL" else tuple(
            x.strip() for x in cs_str.split(",") if x.strip())
        bound = alloc.get(name)
        if bound is None:
            issues.append(f"factor '{name}' has no Allocation row")
            bound = []
        rows_tuple = ("ALL",) if set(bound) == set(row_labels) and row_labels else tuple(bound)
        what = f"factor '{name}'"
        factors.append(Factor(
            name=name, driver=str(driver).strip() if driver is not None else "",
            opt=_num(what, "Opt_P10", opt), ml=_num(what, "ML_mode", ml),
            p90=_num(what, "P90", p90),
            col_scope=col_scope, rows=rows_tuple,
        ))

    if declared_total is not None and abs(float(base.sum()) - declared_total) > 1e-6 * max(1.0, abs(declared_total)):
        issues.append(f"Layer1_Base: base sum {base.sum()} != declared total {declared_total}")
    for fname in alloc:
        if fname not in defined:
            issues.append(f"Layer1_Allocation: '{fname}' is not a defined factor")
    if set(alloc_rows) != set(row_labels):
        issues.append(
            f"Layer1_Allocation WBS rows {sorted(alloc_rows)} (its header) != Layer1_Base rows "
            f"{sorted(row_labels)} - the two are matched by name, so a renamed WBS row is "
            f"renamed in both places")
    for cn in corr_names:
        if cn not in defined:
            issues.append(f"Layer1_Correlation: '{cn}' is not a defined factor")
    for f in factors:
        if "ALL" not in f.col_scope and not set(f.col_scope) <= set(col_labels):
            issues.append(f"factor '{f.name}': column scope {f.col_scope} not in {col_labels}")
    if issues:
        raise RegisterReadError(_compose_reader_error("read_layer1_v5", source, issues))

    cfg = Layer1Config(
        base=base, row_labels=tuple(row_labels), col_labels=col_labels,
        factors=tuple(factors), corr_names=tuple(corr_names),
        corr_matrix=corr_matrix, corr_mode=corr_mode, declared_total=declared_total,
    )
    validate_layer1(cfg)
    mirrored = np.tril(corr_matrix) + np.tril(corr_matrix, -1).T
    np.fill_diagonal(mirrored, 1.0)
    psd = nearest_psd(mirrored)
    if psd["invalid"]:
        raise RegisterReadError(_compose_reader_error(
            "read_layer1_v5", source,
            [f"Layer1_Correlation is not positive semi-definite "
             f"(min eigenvalue {psd['min_eig']:.4g}); fix the elicited matrix"]))
    return cfg
