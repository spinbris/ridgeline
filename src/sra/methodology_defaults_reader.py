"""SR19 reader: the reference register's MC_Params + Variables named-range surface to typed dataclass.

Single source of truth for methodology defaults and project-config values
that were previously hardcoded across `src/defaults.py`,
the Stage 3 binding config, and `src/sra/sra_config.py`. The
SR19 brief
§3 enumerates the 14 constants being evacuated; this module exposes
each as a typed field on the `MethodologyDefaults` frozen dataclass.

Design decisions per the v3 brief:

* `MethodologyDefaults` is a frozen dataclass; every consumer reads via
  attribute access (`mdefaults.cg_coefficients`, not dict lookup).
* `ChainRiskIDs` is a frozen sub-dataclass with explicit typed fields
  (c1_trigger, c1_target, c2_trigger, c2_targets) replacing the v1
  `dict[str, str | list[str]]` shape (grep-friendly, type-safe).
* Two float-threshold fields have distinct names that carry their
  consumer site: `auto_mapper_float_threshold_working_days` (60wd,
  auto-mapper Filter B) and `cp_hybrid_classifier_float_threshold_working_days`
  (20wd, CP classifier Hybrid vs Parallel). Naming defeats the
  60-vs-20 mixup at the call site.
* `expected_dual_coded_risk_ids` is a `frozenset[str]` sourced from the
  CiE-prerequisite cell `cfg_expected_dual_coded_risk_ids` per SR19-D6.
  The redundant `expected_dual_coded_count: int` is also exposed for
  legacy consumers and pre-flight cross-check.
* No backward-compat shim per SR19-D1. Missing or mistyped named ranges
  raise `MethodologyDefaultsError` with a structured message naming
  the consumer module and the workbook path. Composite error
  collection: every issue surfaces in a single error, not first-fail.

The two SR19-D5 sentinel anchors (mc_cg_coeffs[CG01]==0.6 and
60*8==480) live in `src/sra/_pre_flight.py` as named constants;
this module does not evaluate the anchors itself. The reader's job
is to load values; the pre-flight's job is to assert their
consistency.

Reusable across projects: the reader is project-agnostic. A
other project that defines the same named ranges on its own
workbook gets the same dataclass shape. Project-specific code lives
in `bindings/<project>.py` per the existing Stage 3 Beta convention.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook


# ----------------------------------------------------------------------------
# Sub-dataclasses
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainRiskIDs:
    """Event-chain risk-ID mapping (SR19-D2 v3 sub-dataclass).

    Replaces the v1 `dict[str, str | list[str]]` shape with explicit typed
    fields so call sites can do `mdefaults.chain_risk_ids.c1_trigger`
    (grep-friendly) rather than `mdefaults.chain_risk_ids["c1_trigger"]`
    (string key, untyped).

    Sourced from the reference register's Variables!B72:C75 (named range `cfg_chain_risk_ids`).
    Row layout: each row is (Role, Risk_ID(s)). The c2_targets row carries
    a semicolon-joined string (e.g. "RNNN;RMMM") parsed into a tuple here.
    """

    c1_trigger: str
    c1_target: str
    c2_trigger: str
    c2_targets: tuple[str, ...]


@dataclass(frozen=True)
class WBSBucket:
    """One Layer-1 WBS bucket on the cost MC.

    Field types and ordering match `src.defaults.WBSBucket` so the
    SR19 evacuation is value-equivalent at the bucket level.
    """

    name: str
    base_value: float
    variation_min: float
    variation_max: float
    distribution: str


# ----------------------------------------------------------------------------
# Exception
# ----------------------------------------------------------------------------


class MethodologyDefaultsError(ValueError):
    """Raised when the reference register cannot supply a complete MethodologyDefaults.

    Composite per SR19-D1: every missing / mistyped / sentinel-failing /
    set-mismatching issue is collected into a single error so the
    Director sees the full diff in one pass, not first-fail.

    The structured message format includes:
      consumer={caller_module}: which Python file triggered the read
      workbook={workbook_path}: which register was being read
      issues=[...]: one bullet per problem with the named range + actual state + remediation hint
    """


# ----------------------------------------------------------------------------
# Main dataclass
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class MethodologyDefaults:
    """Frozen snapshot of every value of the reference register that SR19 consumes.

    Every field is required (no `| None`, no defaults). Construct via
    `read_methodology_defaults(workbook_path)`. The frozen posture
    means consumers can pass the dataclass freely without worrying
    about mutation; the required-field posture means a partially-
    constructed dataclass cannot exist (the reader populates everything
    or raises).
    """

    # CG correlation coefficients (CG01..CG13), evacuating
    # src.defaults.HEADLESS_CG_COEFFICIENTS + the binding's own CG coefficients
    cg_coefficients: dict[str, float]

    # Event-chain risk-ID mapping, evacuating src.defaults.CHAIN_RISK_IDS
    chain_risk_ids: ChainRiskIDs

    # WBS bucket structure for headless mode, evacuating src.defaults.HEADLESS_BUCKETS
    wbs_buckets: tuple[WBSBucket, ...]

    # SR19-D6 set-level dual-coded risk assertion (v3 added)
    expected_dual_coded_risk_ids: frozenset[str]
    # Redundant count, must equal len(expected_dual_coded_risk_ids); kept
    # for legacy consumers and pre-flight cross-check
    expected_dual_coded_count: int

    # Float-threshold pair stored separately per F10 so a future change
    # to working_hours_per_day does not leave a stale pre-computed value
    auto_mapper_float_threshold_working_days: int
    working_hours_per_day: int
    # Stage 2.5 CP-classifier Hybrid vs Parallel boundary (distinct name
    # per SR19 minor-add #3 so future maintainers cannot confuse with
    # the auto-mapper threshold above)
    cp_hybrid_classifier_float_threshold_working_days: int

    # Stage 2.5 Mode multipliers, the register's grid (the engine constant was retired at RS-D-3)
    mode_multipliers: dict[str, float]

    # SR16 default injection method (the register's; the binding constant was retired at RS-D-6)
    default_injection_method: str

    # Mode classification + reconciliation
    cp_rule: str
    reconciliation_default_non_binomial: str
    reconciliation_default_binomial: str

    # Layer 1 cross-bucket correlation, evacuating src.defaults.WBS_CROSS_BUCKET_RHO
    wbs_cross_bucket_rho: float

    # Auto-mapper broad-linkage downgrade threshold
    broad_linkage_threshold: int

    # GP caps, evacuating src.defaults.DEFAULT_GP_MAX_REWARD_PCT / _RISK_PCT
    gp_max_reward_pct: float
    gp_max_risk_pct: float

    # Project metadata + LDs (Variables tab E19/E24/E25/E26 + new SR18-config block)
    programme_seasons: int
    gp_toc: float
    prelims_weekly: float
    ld_burn_rate: float
    ld_cap: float
    xer_filename: str
    strawman_filename: str

    def __post_init__(self) -> None:
        # Cross-field invariant per SR19-D6: count must equal len(set).
        if self.expected_dual_coded_count != len(self.expected_dual_coded_risk_ids):
            raise MethodologyDefaultsError(
                f"MethodologyDefaults invariant violated: "
                f"expected_dual_coded_count={self.expected_dual_coded_count} "
                f"!= len(expected_dual_coded_risk_ids)={len(self.expected_dual_coded_risk_ids)}. "
                f"the reference register's cfg_expected_dual_coded_count and "
                f"cfg_expected_dual_coded_risk_ids must agree."
            )


# ----------------------------------------------------------------------------
# Reader
# ----------------------------------------------------------------------------


# Maps each MethodologyDefaults field name to its named range on the reference register
# (single-cell ranges) or "block" marker (multi-cell ranges handled below).
_SINGLE_CELL_RANGES: dict[str, str] = {
    "default_injection_method": "meth_default_injection_method",
    "auto_mapper_float_threshold_working_days": "meth_float_threshold_working_days",
    "working_hours_per_day": "meth_working_hours_per_day",
    "cp_hybrid_classifier_float_threshold_working_days": "meth_cp_hybrid_float_threshold_working_days",
    "cp_rule": "meth_cp_rule",
    "reconciliation_default_non_binomial": "meth_reconciliation_default_non_binomial",
    "reconciliation_default_binomial": "meth_reconciliation_default_binomial",
    "wbs_cross_bucket_rho": "meth_wbs_cross_bucket_rho",
    "broad_linkage_threshold": "meth_broad_linkage_threshold",
    "gp_max_reward_pct": "meth_gp_max_reward_pct",
    "gp_max_risk_pct": "meth_gp_max_risk_pct",
    "programme_seasons": "cfg_programme_seasons",
    "expected_dual_coded_count": "cfg_expected_dual_coded_count",
    "gp_toc": "cfg_toc",
    "prelims_weekly": "cfg_prelims_weekly",
    "ld_burn_rate": "cfg_ld_burn_rate",
    "ld_cap": "cfg_ld_cap",
    "xer_filename": "cfg_xer_filename",
    "strawman_filename": "cfg_strawman_filename",
}

# Type coercers per field — openpyxl returns int for "1" and "60" even
# when the consumer wants float. Explicit coercion at read time so the
# dataclass field types are honoured.
_FIELD_COERCERS: dict[str, Any] = {
    "default_injection_method": str,
    "auto_mapper_float_threshold_working_days": int,
    "working_hours_per_day": int,
    "cp_hybrid_classifier_float_threshold_working_days": int,
    "cp_rule": str,
    "reconciliation_default_non_binomial": str,
    "reconciliation_default_binomial": str,
    "wbs_cross_bucket_rho": float,
    "broad_linkage_threshold": int,
    "gp_max_reward_pct": float,
    "gp_max_risk_pct": float,
    "programme_seasons": int,
    "expected_dual_coded_count": int,
    "gp_toc": float,
    "prelims_weekly": float,
    "ld_burn_rate": float,
    "ld_cap": float,
    "xer_filename": str,
    "strawman_filename": str,
}


def _resolve_single_cell(
    wb: Workbook, range_name: str,
) -> tuple[Any, str]:
    """Return (cell_value, location_for_error_messages) for a single-cell named range."""
    if range_name not in wb.defined_names:
        return None, f"named range {range_name!r} not defined in workbook"
    dn = wb.defined_names[range_name]
    destinations = list(dn.destinations)
    if not destinations:
        return None, f"named range {range_name!r} has no destinations"
    sheet, addr = destinations[0]
    ws = wb[sheet]
    cell = ws[addr]
    # openpyxl returns a tuple for multi-cell refs; single-cell returns the Cell
    if isinstance(cell, tuple):
        return None, (
            f"named range {range_name!r} resolves to a multi-cell range "
            f"({sheet}!{addr}); expected single cell"
        )
    return cell.value, f"{sheet}!{addr}"


#: The register's own methodology grid sheet (REG03 Grid_Methodology surface).
_METHODOLOGY_SHEET_TITLE = "Methodology"


def _read_cg_coefficients(wb: Workbook) -> tuple[dict[str, float] | None, str]:
    """Read the 13 CG coefficients. Returns (dict_or_None, error_msg).

    REG03 S2b (D0=B, forward-consolidation): PREFER the register's own
    ``Grid_Methodology`` grid when present (scaffolded, grid-native registers), else
    fall back to the ``mc_cg_coeffs`` named-range block (the legacy client register
    the reference register, which has no Methodology sheet -> this path -> unchanged). One code path;
    a register can only carry one of the two surfaces, so there is no ambiguity.
    """
    if _METHODOLOGY_SHEET_TITLE in wb.sheetnames:
        from src.qra_register_parse import resolve_methodology_from_grid
        grid = [list(r) for r in wb[_METHODOLOGY_SHEET_TITLE].iter_rows(values_only=True)]
        try:
            meth = resolve_methodology_from_grid(grid, source="Grid_Methodology")
        except Exception as exc:  # noqa: BLE001 - surface the located grid error
            return None, f"Grid_Methodology present but unreadable: {exc}"
        return meth["cg_coefficients"], ""

    if "mc_cg_coeffs" not in wb.defined_names:
        return None, "named range 'mc_cg_coeffs' not defined in workbook"
    dn = wb.defined_names["mc_cg_coeffs"]
    destinations = list(dn.destinations)
    if not destinations:
        return None, "named range 'mc_cg_coeffs' has no destinations"
    sheet, addr = destinations[0]
    ws = wb[sheet]
    rng = ws[addr]
    if not isinstance(rng, tuple):
        return None, f"mc_cg_coeffs ({sheet}!{addr}) resolved to a single cell; expected 13-cell range"
    cells = [c for row in rng for c in row]
    if len(cells) != 13:
        return None, (
            f"mc_cg_coeffs ({sheet}!{addr}) has {len(cells)} cells; expected 13 (CG01..CG13)"
        )
    cg_dict: dict[str, float] = {}
    for i, c in enumerate(cells, start=1):
        key = f"CG{i:02d}"
        if c.value is None:
            return None, f"mc_cg_coeffs cell {c.coordinate} ({key}) is empty"
        try:
            cg_dict[key] = float(c.value)
        except (TypeError, ValueError):
            return None, (
                f"mc_cg_coeffs cell {c.coordinate} ({key}) has non-numeric value "
                f"{c.value!r}"
            )
    return cg_dict, ""


def _read_chain_risk_ids(wb: Workbook) -> tuple[ChainRiskIDs | None, str]:
    """Read cfg_chain_risk_ids (4x2 block). Parses c2_targets semicolon list."""
    if "cfg_chain_risk_ids" not in wb.defined_names:
        return None, "named range 'cfg_chain_risk_ids' not defined in workbook"
    dn = wb.defined_names["cfg_chain_risk_ids"]
    destinations = list(dn.destinations)
    if not destinations:
        return None, "named range 'cfg_chain_risk_ids' has no destinations"
    sheet, addr = destinations[0]
    ws = wb[sheet]
    rng = ws[addr]
    if not isinstance(rng, tuple):
        return None, f"cfg_chain_risk_ids ({sheet}!{addr}) resolved to a single cell"
    if len(rng) != 4 or len(rng[0]) != 2:
        return None, (
            f"cfg_chain_risk_ids ({sheet}!{addr}) shape is {len(rng)}x{len(rng[0]) if rng else 0}; "
            f"expected 4x2 (Role | Risk_ID(s) for c1_trigger / c1_target / c2_trigger / c2_targets)"
        )
    role_to_value: dict[str, str] = {}
    for row in rng:
        role_cell, value_cell = row
        if role_cell.value is None or value_cell.value is None:
            return None, f"cfg_chain_risk_ids row {role_cell.coordinate}/{value_cell.coordinate} has empty cell"
        role_to_value[str(role_cell.value).strip()] = str(value_cell.value).strip()
    expected_roles = {"c1_trigger", "c1_target", "c2_trigger", "c2_targets"}
    missing_roles = expected_roles - set(role_to_value)
    if missing_roles:
        return None, (
            f"cfg_chain_risk_ids missing roles: {sorted(missing_roles)}. "
            f"Present: {sorted(role_to_value)}"
        )
    return ChainRiskIDs(
        c1_trigger=role_to_value["c1_trigger"],
        c1_target=role_to_value["c1_target"],
        c2_trigger=role_to_value["c2_trigger"],
        c2_targets=tuple(s.strip() for s in role_to_value["c2_targets"].split(";") if s.strip()),
    ), ""


def _read_wbs_buckets(wb: Workbook) -> tuple[tuple[WBSBucket, ...] | None, str]:
    """Read cfg_wbs_buckets (11x5 block)."""
    if "cfg_wbs_buckets" not in wb.defined_names:
        return None, "named range 'cfg_wbs_buckets' not defined in workbook"
    dn = wb.defined_names["cfg_wbs_buckets"]
    destinations = list(dn.destinations)
    if not destinations:
        return None, "named range 'cfg_wbs_buckets' has no destinations"
    sheet, addr = destinations[0]
    ws = wb[sheet]
    rng = ws[addr]
    if not isinstance(rng, tuple):
        return None, f"cfg_wbs_buckets ({sheet}!{addr}) resolved to a single cell"
    buckets: list[WBSBucket] = []
    for row_idx, row in enumerate(rng, start=1):
        cells = list(row)
        if len(cells) != 5:
            return None, (
                f"cfg_wbs_buckets row {row_idx} has {len(cells)} cells; expected 5 "
                f"(Bucket_Name | Base_Value | Variation_Min | Variation_Max | Distribution)"
            )
        try:
            buckets.append(WBSBucket(
                name=str(cells[0].value),
                base_value=float(cells[1].value),
                variation_min=float(cells[2].value),
                variation_max=float(cells[3].value),
                distribution=str(cells[4].value),
            ))
        except (TypeError, ValueError) as exc:
            return None, (
                f"cfg_wbs_buckets row {row_idx} type-coercion failed: {exc}. "
                f"Values: {[c.value for c in cells]}"
            )
    return tuple(buckets), ""


def _read_expected_dual_coded_ids(
    wb: Workbook,
) -> tuple[frozenset[str] | None, str]:
    """Read cfg_expected_dual_coded_risk_ids (single-cell semicolon-joined sorted list).

    Per SR19-D6: this is the set-level baseline. Pre-flight asserts the
    live Risk_Scope.Time_Impact=Yes filter returns exactly this set.
    """
    raw, location = _resolve_single_cell(wb, "cfg_expected_dual_coded_risk_ids")
    if raw is None:
        return None, location
    if not isinstance(raw, str):
        return None, (
            f"cfg_expected_dual_coded_risk_ids at {location} has type {type(raw).__name__!r}; "
            f"expected str (semicolon-joined sorted list)"
        )
    parsed = frozenset(s.strip() for s in raw.split(";") if s.strip())
    if not parsed:
        return None, (
            f"cfg_expected_dual_coded_risk_ids at {location} parsed to empty set; "
            f"raw value {raw!r}"
        )
    return parsed, ""


def _read_mode_multipliers(wb: Workbook) -> tuple[dict[str, float] | None, str]:
    """Read the Mode multiplier grid into the canonical dict shape.

    RS-D-3b (D-15): PREFER the register's own ``Methodology`` grid when present
    (scaffolded, grid-native registers), else the three ``meth_mode_mult_*``
    singletons (the legacy named-range register). Same one-code-path rule as
    :func:`_read_cg_coefficients`.
    """
    if _METHODOLOGY_SHEET_TITLE in wb.sheetnames:
        from src.qra_register_parse import resolve_methodology_from_grid
        grid = [list(r) for r in wb[_METHODOLOGY_SHEET_TITLE].iter_rows(values_only=True)]
        try:
            meth = resolve_methodology_from_grid(grid, source="Grid_Methodology")
        except Exception as exc:  # noqa: BLE001 - surface the located grid error
            return None, f"Grid_Methodology present but unreadable: {exc}"
        grid_mults = {str(k): float(v) for k, v in meth["mode_multipliers"].items()}
        bad = {k: v for k, v in grid_mults.items() if not 0.0 <= v <= 1.0}
        if bad:  # same range rule as the named-range path (review WARN, RS-D-3b)
            return None, f"Grid_Methodology Mode multipliers outside [0, 1]: {bad}"
        return grid_mults, ""
    result: dict[str, float] = {}
    for mode_key, range_name in [
        ("Series", "meth_mode_mult_series"),
        ("Hybrid", "meth_mode_mult_hybrid"),
        ("Parallel", "meth_mode_mult_parallel"),
    ]:
        raw, location = _resolve_single_cell(wb, range_name)
        if raw is None:
            return None, location
        try:
            result[mode_key] = float(raw)
        except (TypeError, ValueError):
            return None, (
                f"{range_name} at {location} has non-numeric value {raw!r}; "
                f"expected float in [0, 1]"
            )
        if not 0.0 <= result[mode_key] <= 1.0:
            return None, (
                f"{range_name} at {location} value {result[mode_key]} outside [0, 1] range"
            )
    return result, ""


def _open_register(workbook_path: Path | str, caller_module: str):
    """Open a register for a narrow read, with the same two pre-checks as
    :func:`read_methodology_defaults`: the Excel lock (stale cached values) and existence."""
    path = Path(workbook_path)
    lock_path = path.parent / f"~${path.name}"
    if lock_path.exists():
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: register workbook is locked by Excel ({lock_path}); "
            f"close Excel before re-running. A stale value would otherwise propagate silently."
        )
    if not path.exists():
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: expected a register at {path} but the file does not exist."
        )
    return path, load_workbook(str(path), read_only=True, data_only=True)


def _grid_settings(wb: Workbook) -> dict | None:
    """The grid-native ``Methodology`` sheet's settings, or None when the register has no
    such sheet (legacy named-range register)."""
    if _METHODOLOGY_SHEET_TITLE not in wb.sheetnames:
        return None
    from src.qra_register_parse import resolve_methodology_from_grid
    grid = [list(r) for r in wb[_METHODOLOGY_SHEET_TITLE].iter_rows(values_only=True)]
    try:
        return resolve_methodology_from_grid(grid, source="Grid_Methodology")
    except Exception as exc:  # noqa: BLE001 - name the workbook and the real cause
        raise MethodologyDefaultsError(
            f"a 'Methodology' sheet is present but is not a settings grid this reader can "
            f"parse (a narrative strawman sheet, or a malformed grid): {exc}"
        ) from exc


#: RS-D-2: the legacy register's named ranges for the four calibration tolerances.
_TOLERANCE_RANGE_NAMES: dict[str, str] = {
    "cost_calibration_tolerance_dollars": "meth_cal_tol_cost_dollars",
    "cost_calibration_tolerance_pct": "meth_cal_tol_cost_pct",
    "schedule_calibration_tolerance_days": "meth_cal_tol_sched_days",
    "schedule_calibration_tolerance_pct": "meth_cal_tol_sched_pct",
    # F-30: the schedule top-3 tie band (a fraction of third place). Grid registers carry the
    # Schedule_Top3_Tie_Tolerance_Pct row; legacy registers this named range.
    "schedule_top3_tie_tolerance_pct": "meth_top3_tie_tol_pct",
}


def read_calibration_tolerances(
    workbook_path: Path | str,
    *,
    caller_module: str = "unspecified",
) -> dict[str, float]:
    """The register's five calibration tolerances: cost dollars OR percent, schedule days OR
    percent (RS-D-2, D-14), and the schedule top-3 tie band (stage 4 F-30, 08/09/2026 - the
    fraction of third place within which a contributor the two arms rank apart is still
    "the same risks in the top three"). Grid-native registers from the ``Methodology`` sheet's
    settings rows, legacy registers from the ``meth_cal_tol_*`` / ``meth_top3_tie_tol_pct``
    named ranges; a register carrying neither raises. There is no code default, by ruling.
    """
    path, wb = _open_register(workbook_path, caller_module)
    try:
        meth = _grid_settings(wb)
        if meth is not None:
            tol = dict(meth.get("calibration_tolerances") or {})
            where = "Methodology sheet settings rows"
        else:
            tol = {}
            where = "meth_cal_tol_* named ranges"
            for key, name in _TOLERANCE_RANGE_NAMES.items():
                raw, _loc = _resolve_single_cell(wb, name)
                if raw is not None:
                    try:
                        tol[key] = float(raw)
                    except (TypeError, ValueError):
                        raise MethodologyDefaultsError(
                            f"consumer={caller_module}: {name} in {path} is not numeric ({raw!r})")
    finally:
        wb.close()
    missing = [k for k in _TOLERANCE_RANGE_NAMES if k not in tol]
    if missing:
        # F-30 review WARN: name what the operator must add, in the register's own vocabulary -
        # the grid row label and the legacy named range - not the internal key alone.
        from src.qra_register_parse import _GRID_TOLERANCE_LABELS
        row_label = {v: k for k, v in _GRID_TOLERANCE_LABELS.items()}
        wanted = ", ".join(
            f"row '{row_label.get(k, k)}' (or named range '{_TOLERANCE_RANGE_NAMES[k]}')"
            for k in missing)
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: register ({path}) carries no calibration tolerance for "
            f"{missing} in its {where}. The engine has no default tolerance (RS-D-2, D-14; "
            f"F-30 for the tie band); add to the register: {wanted}."
        )
    bad = {k: v for k, v in tol.items() if v < 0 or (k.endswith("_pct") and v > 1.0)}
    if bad:
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: calibration tolerances out of range in {path}: {bad} "
            f"(dollars and days >= 0; percents in [0, 1])")
    return {k: float(tol[k]) for k in _TOLERANCE_RANGE_NAMES}


def read_default_injection_method(
    workbook_path: Path | str,
    *,
    caller_module: str = "unspecified",
) -> str:
    """The register's default injection method for dual-coded risks whose row does not pin
    one (RS-D-6, D-18). Grid-native registers from the ``Default_Injection_Method`` settings
    row, legacy registers from the ``meth_default_injection_method`` named range; neither
    raises. There is no code default, by ruling.
    """
    path, wb = _open_register(workbook_path, caller_module)
    try:
        meth = _grid_settings(wb)
        if meth is not None:
            method = meth.get("default_injection_method")
            where = "Methodology sheet settings rows"
        else:
            raw, _loc = _resolve_single_cell(wb, "meth_default_injection_method")
            method = None if raw is None else str(raw).strip()
            where = "meth_default_injection_method named range"
    finally:
        wb.close()
    if not method:
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: register ({path}) carries no default injection method in "
            f"its {where}. The engine has no default (RS-D-6, D-18); add it to the register."
        )
    from src.sra.cpm.risk_driver_schema import INJECTION_METHODS
    if method not in INJECTION_METHODS:
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: default injection method {method!r} in {path} is not one "
            f"of {list(INJECTION_METHODS)}")
    return method


def read_mode_multipliers(
    workbook_path: Path | str,
    *,
    caller_module: str = "unspecified",
) -> dict[str, float]:
    """The register's Mode multiplier grid, and nothing else (RS-D-3b, D-15).

    The one entry point every engine config takes its grid from: the SRA loader,
    the bindings, the AM runner and the scripts. Grid-native registers are read from
    their ``Methodology`` sheet, legacy registers from the ``meth_mode_mult_*`` named
    ranges; a register carrying neither raises - there is no code default to fall
    back to, by ruling.
    """
    path, wb = _open_register(workbook_path, caller_module)
    try:
        grid, err = _read_mode_multipliers(wb)
    finally:
        wb.close()
    if grid is None:
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: register ({path}) carries no Mode multiplier "
            f"grid: {err}. The engine has no default grid (RS-D-3, D-15); fix the register."
        )
    return grid


def read_cg_coefficients(
    workbook_path: Path | str,
    *,
    caller_module: str = "unspecified",
) -> dict[str, float]:
    """The register's CG correlation coefficients, and nothing else.

    The narrow counterpart to :func:`read_mode_multipliers`, and the second of the two
    ``MethodologyDefaults`` fields any engine path actually reads (3c Part A). Grid-native
    registers are read from their ``Methodology`` sheet, legacy registers from the
    ``mc_cg_coeffs`` named-range block; a register carrying neither raises, because there is
    no code default to fall back to.
    """
    path, wb = _open_register(workbook_path, caller_module)
    try:
        coefficients, err = _read_cg_coefficients(wb)
    finally:
        wb.close()
    if coefficients is None:
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: register ({path}) carries no CG coefficients: "
            f"{err}. The engine has no default set; fix the register."
        )
    return coefficients


def read_methodology_defaults(
    workbook_path: Path | str,
    *,
    caller_module: str = "unspecified",
) -> MethodologyDefaults:
    """Read the reference register's named ranges into a MethodologyDefaults frozen dataclass.

    Parameters
    ----------
    workbook_path : Path or str
        The reference register workbook path.
    caller_module : str
        Source-module identifier the calling code passes in (e.g.
        "src/integrated/stage3_inputs.py"). Surfaces in
        MethodologyDefaultsError messages so debuggers know which
        consumer triggered the read.

    Raises
    ------
    MethodologyDefaultsError
        Composite error if any required named range is missing / mistyped /
        empty / has wrong shape, or if the lock-file pattern (`~$*.xlsx`)
        indicates Excel has the workbook open. Every issue is collected
        into one error per SR19-D1; not first-fail.

    Returns
    -------
    MethodologyDefaults
        Frozen dataclass with every field populated and validated.
    """
    workbook_path = Path(workbook_path)

    # Pre-check: register lock-file pattern (mirrors src.sra._pre_flight
    # strawman lock check). Excel has the workbook open -> openpyxl
    # may read stale cached values.
    lock_path = workbook_path.parent / f"~${workbook_path.name}"
    if lock_path.exists():
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: register workbook is locked by Excel "
            f"({lock_path}); close Excel before re-running. "
            f"Stale named-range values would otherwise propagate silently."
        )

    if not workbook_path.exists():
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: expected reference register at "
            f"{workbook_path} but the file does not exist."
        )

    # data_only=True so formula cells return their last cached value;
    # this combined with the SR19-D5 sentinel anchors in _pre_flight
    # catches stale-formula corruption from manual-calc-mode saves.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
        wb = openpyxl.load_workbook(workbook_path, data_only=True)

    issues: list[str] = []
    values: dict[str, Any] = {}

    # Multi-cell ranges
    cg_dict, cg_err = _read_cg_coefficients(wb)
    if cg_err:
        issues.append(cg_err)
    else:
        values["cg_coefficients"] = cg_dict

    chain, chain_err = _read_chain_risk_ids(wb)
    if chain_err:
        issues.append(chain_err)
    else:
        values["chain_risk_ids"] = chain

    buckets, bucket_err = _read_wbs_buckets(wb)
    if bucket_err:
        issues.append(bucket_err)
    else:
        values["wbs_buckets"] = buckets

    expected_ids, expected_err = _read_expected_dual_coded_ids(wb)
    if expected_err:
        issues.append(expected_err)
    else:
        values["expected_dual_coded_risk_ids"] = expected_ids

    mode_mults, mode_err = _read_mode_multipliers(wb)
    if mode_err:
        issues.append(mode_err)
    else:
        values["mode_multipliers"] = mode_mults

    # Single-cell ranges with type coercion
    for field_name, range_name in _SINGLE_CELL_RANGES.items():
        raw, location = _resolve_single_cell(wb, range_name)
        if raw is None:
            issues.append(
                f"named range {range_name!r} for field {field_name!r}: {location}"
            )
            continue
        coercer = _FIELD_COERCERS[field_name]
        try:
            values[field_name] = coercer(raw)
        except (TypeError, ValueError):
            issues.append(
                f"named range {range_name!r} at {location} value {raw!r} "
                f"failed coercion to {coercer.__name__} for field {field_name!r}"
            )

    if issues:
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: the reference register ({workbook_path}) failed to populate "
            f"MethodologyDefaults. {len(issues)} issue(s):\n  - "
            + "\n  - ".join(issues)
            + "\nRemediation: confirm the reference register is the Register_Unify_followup output and "
            "Excel has been F9-recalc-saved since the last edit. If a named range "
            "rename or restructure is intentional, update the brief §3 inventory and "
            "this reader together."
        )

    return MethodologyDefaults(**values)


def build_test_methodology_defaults(**overrides: Any) -> MethodologyDefaults:
    """Construct a MethodologyDefaults with the reference register's lock-preserve values inlined.

    Test factory per §6.2 step 4. Fixture surface that previously
    constructed `IntegratedConfig(...)` without a methodology-defaults
    argument now uses this. Overrides allow per-test customisation
    (e.g. swap mode_multipliers for a Stage 3 test).

    Values mirror the Director-locked lock-preserve set on the reference register
    MC_Params after the Register_Unify v2 §4.1 edits (CG05/07/09/13
    aligned with engine fallback behaviour). Any drift here from
    the reference register is a test bug; the production path always reads from
    the reference register via `read_methodology_defaults`. The chain-risk-id row is
    sourced from the active project binding's ``LEGACY_CHAIN_IDS`` rather
    than inlined, so the bare risk-id literals live only in the binding
    (portability static guard); the binding copy is gated equal to the
    the reference register's ``cfg_chain_risk_ids`` surface by the binding-registry test.
    """
    from src.sra.cpm.bindings import get_active_binding

    _legacy_chain = get_active_binding().legacy_chain_ids or {}
    defaults: dict[str, Any] = {
        "cg_coefficients": {
            "CG01": 0.6, "CG02": 0.5, "CG03": 0.5, "CG04": 0.4,
            "CG05": 0.5, "CG06": 0.5, "CG07": 0.4, "CG08": 0.4,
            "CG09": 0.4, "CG10": 0.4, "CG11": 0.5, "CG12": 0.5,
            "CG13": 0.5,
        },
        "chain_risk_ids": ChainRiskIDs(
            c1_trigger=str(_legacy_chain.get("c1_trigger", "")),
            c1_target=str(_legacy_chain.get("c1_target", "")),
            c2_trigger=str(_legacy_chain.get("c2_trigger", "")),
            c2_targets=tuple(_legacy_chain.get("c2_targets", ())),
        ),
        "wbs_buckets": (
            WBSBucket("Preliminaries", 77470585.0, -0.10, 0.15, "Triangular"),
            WBSBucket("Design Cost", 3672140.0, -0.05, 0.075, "Triangular"),
            WBSBucket("Turnkey Packages", 31350000.0, -0.05, 0.075, "Triangular"),
            WBSBucket("Civils", 57879500.0, -0.05, 0.075, "Triangular"),
            WBSBucket("Structural", 4309732.0, -0.03, 0.045, "Triangular"),
            WBSBucket("Mechanical", 2000000.0, -0.05, 0.075, "Triangular"),
            WBSBucket("Gas Turbine, Gen & Aux", 13000000.0, -0.05, 0.075, "Triangular"),
            WBSBucket("Valves", 1571595.0, -0.05, 0.075, "Triangular"),
            WBSBucket("Insulation", 1349198.0, -0.05, 0.075, "Triangular"),
            WBSBucket("Electrical / Instrumentation", 38158300.0, -0.05, 0.075, "Triangular"),
            WBSBucket("Commissioning", 1752781.0, -0.05, 0.075, "Triangular"),
        ),
        "expected_dual_coded_risk_ids": frozenset({
            "R013", "R015.1", "R016.1", "R016.2",
            "R017.1", "R026.1", "R067", "R090",
        }),
        "expected_dual_coded_count": 8,
        "auto_mapper_float_threshold_working_days": 60,
        "working_hours_per_day": 8,
        "cp_hybrid_classifier_float_threshold_working_days": 20,
        "mode_multipliers": {"Series": 1.0, "Hybrid": 0.5, "Parallel": 0.0},
        "default_injection_method": "discrete_event_additive_days",
        "cp_rule": "Option_Z_Hybrid",
        "reconciliation_default_non_binomial": "A",
        "reconciliation_default_binomial": "B",
        "wbs_cross_bucket_rho": 0.4,
        "broad_linkage_threshold": 500,
        "gp_max_reward_pct": 0.05,
        "gp_max_risk_pct": 0.05,
        "programme_seasons": 3,
        "gp_toc": 330000000.0,
        "prelims_weekly": 700000.0,
        "ld_burn_rate": 250000.0,
        "ld_cap": 33000000.0,
        "xer_filename": "reference_schedule.xer",
        "strawman_filename": "strawman_DPReview.xlsx",
    }
    defaults.update(overrides)
    return MethodologyDefaults(**defaults)
