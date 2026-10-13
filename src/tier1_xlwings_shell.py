"""QRAXL-01 Tier-1 xlwings Lite shell (front-end I/O layer).

The @script entry point the xlwings Lite runtime calls with the open workbook.
It reads the contract-v2 register via xlwings ranges, feeds the cell GRIDS to the
SHARED parser (``qra_register_parse`` - the same one Tier 2 uses, so Tier-1 ==
Tier-2 on the read side by construction), then runs ``qra_core`` and writes the
P-curve back.

The @script is a THIN I/O wrapper over the headless-testable
``tier1_headless.run_headless`` (read ranges -> call the headless run -> write
ranges), mirroring RF-01 (rf_headless.py is the runner, shell_xlwings.py the
I/O). CI covers the compute + formatting; only the literal xlwings range read/
write is Excel-only. ``qra_core``, the parser and the resolver stay Pyodide-
clean; only THIS shell imports xlwings.
"""

from __future__ import annotations

import xlwings as xw
from xlwings import script

from src.qra_register_parse import RISK_REGISTER_SHEET, _LAYER1_SHEETS
from src.register_contract import (
    LAYER1_ENABLED_NAME, check_contract, layer1_enabled_flag,
)
from src.rng_streams import SEED_DRAWN, resolve_seed
from src.tier1_headless import METHODOLOGY_SHEET_TITLE, run_headless

# ---------------------------------------------------------------------------
# xlwings Lite COMPATIBILITY (this class of defect cannot be caught headless)
# ---------------------------------------------------------------------------
# xlwings Lite's Office.js backend does NOT implement several classic xlwings
# Sheet APIs. The Tier-1 shell MUST NOT use any of these (they raise a
# base-class NotImplementedError only at runtime in Excel - the headless gates
# read via openpyxl and never exercise them):
#
#   FORBIDDEN in Lite:  sheet.used_range   (xlwings-lite discussion #19)
#                       sheet.copy()
#                       sheet.api / Office.js getUsedRange (`.api` unsupported)
#
# SUPPORTED reads/writes used here: named ranges via book.names[nm].
# refers_to_range (Set_*, Out_*, Grid_RiskRegister, Grid_Methodology), and a FIXED
# A1-anchored address read via book.sheets[name].range("A1:..") (Office.js getRange -
# NOT getUsedRange). The grids are anchored at $A$1 (the parser uses ABSOLUTE Excel
# row indices, so the grid must be row-1-aligned).
#
# REG05-A2-FIX (D1): the Layer-1 sheets are read via their whole USED RANGE (a
# generous fixed A1 block, see _sheet_grid), NOT the fixed Grid_Layer1_* names. The
# Grid_Layer1_* names are sized to the empty template's header-only shell and do NOT
# grow when the user fills the sheets, so a name-read saw only the shell (base sum
# 3.9M != declared 50M, 0 factors, empty allocation). The used-range read grows with
# the fill and matches tier1_headless.extract_grids_openpyxl. The Grid_Layer1_* names
# stay EMITTED (contract v1.4 / Validate) - a contract surface, just not the read
# source. Not .expand() (truncates at the V5 layout's interior blank rows) and not
# .used_range/.api (Lite-forbidden); the parser trims trailing blanks, so an
# over-extended fixed block is harmless.
_GRID_NAMES: dict[str, str] = {
    RISK_REGISTER_SHEET: "Grid_RiskRegister",
    METHODOLOGY_SHEET_TITLE: "Grid_Methodology",
}

# Fixed A1-anchored block for the Layer-1 used-range read (rows x cols). Must
# comfortably exceed any realistic Layer-1 extent (cost columns, WBS rows, factors -
# a compact factor model, never a large table); the parser trims trailing blanks.
# Parked robust option (brief §2.1): dynamic OFFSET Grid_Layer1_* names.
_LAYER1_READ_RANGE = "A1:AX200"  # AX = col 50; 200 rows


def _range_grid(book, range_name: str):
    """Read a named range's values as a 2D grid (list of row-lists). Returns []
    if the named range is absent. Lite-safe (named-range read only)."""
    try:
        rng = book.names[range_name].refers_to_range
    except (KeyError, Exception):  # noqa: BLE001 - Lite raises varied types on a missing name
        return []
    v = rng.value
    if v is None:
        return []
    if not isinstance(v, list):
        return [[v]]  # single cell
    if v and not isinstance(v[0], list):
        v = [v]  # xlwings collapses a single row to 1D; re-wrap to 2D
    return v


def _sheet_grid(book, sheet_name: str):
    """Read a whole Layer-1 sheet as a 2D grid over a generous FIXED A1-anchored
    block (:data:`_LAYER1_READ_RANGE`). Lite-safe: an explicit address via
    ``book.sheets[name].range(addr)`` (Office.js getRange), never the Lite-forbidden
    whole-sheet readers listed in this module's header. Grows with the user's fill
    where the fixed ``Grid_Layer1_*`` name would not (REG05-A2-FIX D1); the parser
    trims trailing blanks, so over-covering is harmless. ``[]`` if the sheet absent."""
    try:
        sht = book.sheets[sheet_name]
    except (KeyError, Exception):  # noqa: BLE001 - Lite raises varied types when absent
        return []
    try:
        v = sht.range(_LAYER1_READ_RANGE).value
    except Exception:  # noqa: BLE001 - a missing/empty sheet range reads as nothing
        return []
    if v is None:
        return []
    if not isinstance(v, list):
        v = [[v]]                       # single cell
    elif v and not isinstance(v[0], list):
        v = [v]                         # xlwings collapses a single row to 1D
    # trim trailing all-blank rows so the grid matches the openpyxl used range.
    while v and all(c is None for c in v[-1]):
        v.pop()
    return v


def read_grids_xlwings(book) -> dict:
    """Tier-1 grid extraction (the Lite-safe analogue of
    ``tier1_headless.extract_grids_openpyxl``). Risk register + methodology via their
    ``Grid_*`` named ranges (sized to extent at build); the Layer-1 sheets via their
    whole USED RANGE (:func:`_sheet_grid`, REG05-A2-FIX D1). Same grids, same parser.
    A client register with no Layer-1 sheets -> ``layer1={}`` -> Layer 1 OFF, as Tier 2.

    REG05-A2 §3.2: read ``Set_Layer1_Enabled`` and thread it in as
    ``layer1_enabled``; when not TRUE, pass ``layer1={}`` so the shared parse gate
    returns None (an empty, present-but-disabled Layer-1 is a read no-op)."""
    enabled = layer1_enabled_flag(_named_value(book, LAYER1_ENABLED_NAME))
    layer1 = (
        {
            sheet: _sheet_grid(book, sheet)
            for sheet in _LAYER1_SHEETS
            if _sheet_grid(book, sheet)
        }
        if enabled else {}
    )
    return {
        "risk_register": _range_grid(book, _GRID_NAMES[RISK_REGISTER_SHEET]),
        "layer1": layer1,
        "layer1_enabled": enabled,
        # GD-B: the register's own methodology surface (CG coeffs + mode
        # multipliers). Absent -> [] -> the resolver fails loud (no fallback).
        "methodology": _range_grid(book, _GRID_NAMES[METHODOLOGY_SHEET_TITLE]),
    }


def _named_value(book, name):
    """Read a named-range scalar value (Lite-safe). Returns None if absent."""
    try:
        return book.names[name].refers_to_range.value
    except Exception:  # noqa: BLE001 - Lite raises varied types on a missing name
        return None


def _pad(rows2d: list, nrows: int, ncols: int) -> list:
    """Truncate/pad a 2D list to (nrows, ncols) with None so the write matches
    the fixed named-range shape (RF-01 pattern)."""
    out = []
    for i in range(nrows):
        row = list(rows2d[i]) if i < len(rows2d) else []
        out.append([(row[j] if j < len(row) else None) for j in range(ncols)])
    return out


def _run_and_write(book, iterations_name: str, default_iter: int):
    """Shared run path for the run buttons: read Set_* ranges -> run_headless ->
    write Out_* ranges. ``iterations_name`` selects which Settings cell drives the
    iteration count (Set_iterations = interactive default; Set_iterations_max =
    the 100k button). Named-range reads/writes only (Lite-safe)."""
    grids = read_grids_xlwings(book)

    def R(nm):
        return book.names[nm].refers_to_range

    def _named(nm, default):
        try:
            return R(nm).value
        except Exception:
            return default

    n_iter = int(_named(iterations_name, default_iter) or default_iter)
    # SEEDZERO-01 P5: a stated seed is used as given; blank or 0 is drawn here and written back
    # below, so the workbook records the seed its outputs came from. A fraction is refused, not
    # truncated. The range is contract-required: without it a drawn seed has nowhere to be
    # recorded, so a missing one is refused rather than run unrecorded.
    try:
        seed_range = R("Set_seed")
    except Exception:
        raise ValueError(
            "Set_seed is missing. It is required by the register contract, and it is where a "
            "drawn seed is recorded: restore it (Settings!B2), blank or 0 for a random run."
        ) from None
    seed, seed_source = resolve_seed(seed_range.value, where="Set_seed")
    view = str(_named("Set_view", "owner") or "owner").strip().lower()
    # GENERIC-01: no fallback. `Set_risk_prefix` is contract-required, and defaulting it to the
    # wind project's "WT" meant a register that omitted it had every risk row read against another
    # project's prefix, matched none, and returned an EMPTY result rather than an error - a wrong
    # answer where the missing range should have been a refusal.
    prefix = str(_named("Set_risk_prefix", "") or "").strip()
    if not prefix:
        raise ValueError(
            "Set_risk_prefix is missing or empty. It is required by the register contract and "
            "there is no default: a prefix borrowed from another project would match no risk "
            "rows and report an empty register as though it were a result.")

    # The ENTIRE compute + formatting is the headless core (CI-covered). This
    # wrapper only reads the ranges above and writes the ranges below.
    out = run_headless(grids, risk_id_prefix=prefix, n_iter=n_iter, seed=seed, view=view)
    # First write: if a later output write fails, the outputs already in the sheet still name
    # the seed they came from.
    if seed_source == SEED_DRAWN:
        seed_range.value = seed

    R("Out_ptable").value = _pad(out["p_table"], 19, 2)
    R("Out_scurve").value = _pad(
        list(zip(out["s_curve"]["prob"], out["s_curve"]["value"])), 101, 2
    )
    R("Corr_flag").value = out["corr_flag"]
    conv = out["convergence_note"]
    R("Out_conv_halfwidth").value = round(conv["p80_ci95_half_width"], 2)
    R("Out_conv_pct").value = round(conv["p80_ci95_half_width_pct"], 4)
    if out["triple"]:
        modes = ("zero", "elicited", "one")
        triple_rows = [
            [out["triple"]["elicited"][i][0]] + [out["triple"][m][i][1] for m in modes]
            for i in range(len(out["triple"]["elicited"]))
        ]
        R("Out_triple").value = _pad(triple_rows, 19, 4)


@script
def run_simulation(book: xw.Book):  # pragma: no cover - exercised in Excel (6b load test)
    """BUTTON: run the cost-QRA at the interactive iteration count (Settings B1 /
    Set_iterations, default 25k) and write the P-curve/S-curve/convergence back."""
    _run_and_write(book, "Set_iterations", 25_000)


@script
def run_simulation_100k(book: xw.Book):  # pragma: no cover - exercised in Excel
    """BUTTON: run the cost-QRA at the on-demand 100k count (Settings B5 /
    Set_iterations_max, default 100k) - the high-resolution run for the deliverable.
    Same write-back as run_simulation; only the iteration count differs."""
    _run_and_write(book, "Set_iterations_max", 100_000)


@script
def validate_contract(book: xw.Book):  # pragma: no cover - exercised in Excel
    """REG03 S2 rider (1): a contract self-check for a scaffold-once handover.

    After a user hand-edits the scaffolded register, this verifies the
    Grid_*/Set_*/Out_* named ranges are all present, Set_ContractVersion matches,
    and Grid_Methodology carries its 13 CG + 3 mode rows - writing PASS/FAIL + a
    human-readable message to the Out_validation range. A thin I/O wrapper over the
    headless ``check_contract`` (CI-covered); it reads via named ranges only, so it
    obeys the Lite forbidden-API list documented in this module's header."""
    grids = read_grids_xlwings(book)
    try:
        present = [nm.name for nm in book.names]
    except Exception:
        present = []

    def _named(nm, default=None):
        try:
            return book.names[nm].refers_to_range.value
        except Exception:
            return default

    ok, message = check_contract(present, grids["methodology"],
                                 _named("Set_ContractVersion"))
    book.names["Out_validation"].refers_to_range.value = [
        ["PASS" if ok else "FAIL"], [message]]
