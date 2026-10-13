"""REG04 - contract hardening (sheet + workbook protection) + cascade completion.

Scope A: machine/contract sheets are protected with the contract cells LOCKED and the
input cells explicitly UNLOCKED; Out_* stay unlocked so the xlwings write-back works on
the protected Simulation sheet (Director ruling 3a, option a); the workbook structure is
locked. Protection is Excel-runtime only, so the engine read, the Validate button and
the resize helper are unaffected (bit-identity trivially safe).

Scope B: List_Package / List_Factor seeded; the List_Factor dropdown wired onto the
Layer-1 factor columns.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from src.register_contract import CONTRACT_VERSION, check_contract
from src.tier1_headless import extract_grids_openpyxl, run_headless
from tools.register_scaffold import build_template, resize_layer1_correlation

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> Path:
    return build_template(tmp_path_factory.mktemp("reg04") / "t.xlsx")


# --- Scope A: protection --------------------------------------------------

def test_machine_sheets_protected_and_workbook_structure_locked(template):
    wb = openpyxl.load_workbook(template)
    try:
        for sh in ("Risk Register", "Methodology", "Settings", "Simulation",
                   "Mapping", "Lists", "TOC & Instructions", "Reference (xlwings)"):
            assert wb[sh].protection.sheet is True, sh
        assert wb.security is not None and wb.security.lockStructure is True
        # 3c Part C-2, corrected twice, and the second correction is the honest one.
        #
        # This originally read `is True  # add-risk-row workflow`. I flipped it to `is False`
        # on the reasoning that True means LOCKED in OOXML, so the assertion was defending the
        # very thing its comment claimed to enable. The reading of the flag was right; the
        # conclusion was not. The Director then tried the insert in Excel and it did nothing,
        # on the shipped file and on two variants with unlocked headroom below the data.
        #
        # The reason is that Excel inserts a WHOLE row, and every data row carries locked
        # cells at AB, AC and AD - the EMV formula columns - plus everything from AF out. The
        # insert is refused across the row, not for want of space below it, and unlocking the
        # EMV formulas to permit it is the one thing this protection exists to prevent.
        #
        # So True (locked) is correct, and it always was. What was wrong was only the comment
        # naming a workflow the sheet has never supported. Adding a row is Review > Unprotect
        # Sheet - a specialist's step (R-8) - or a regeneration at a higher count.
        assert wb["Risk Register"].protection.insertRows is True, (
            "row insertion is permitted, but the EMV columns make it unusable - see the "
            "comment above and _PERMITTED in tools/register_scaffold.py")
    finally:
        wb.close()


def test_input_cells_unlocked_contract_cells_locked(template):
    wb = openpyxl.load_workbook(template)
    try:
        rr, meth, st = wb["Risk Register"], wb["Methodology"], wb["Settings"]
        # inputs unlocked
        assert rr["A5"].protection.locked is False        # Risk ID input
        assert meth["B2"].protection.locked is False       # CG coefficient
        assert st["B1"].protection.locked is False         # Set_iterations
        assert wb["Lists"]["A3"].protection.locked is False  # cascade list value
        # contract cells locked
        assert rr["A4"].protection.locked is True          # header row
        assert rr["AB5"].protection.locked is True         # EMV formula col
        assert meth["B15"].protection.locked is True       # mode multiplier
        assert st["B6"].protection.locked is True          # Set_ContractVersion
    finally:
        wb.close()


def test_out_ranges_unlocked_for_writeback(template):
    """§3a option (a): the Out_* write-back cells are UNLOCKED (over their full extent)
    so the @script can write them on the protected Simulation sheet."""
    wb = openpyxl.load_workbook(template)
    try:
        sim = wb["Simulation"]
        assert sim.protection.sheet is True
        for addr in ("A2", "B20", "D2", "E102", "H1", "I2", "L20", "N2"):
            assert sim[addr].protection.locked is False, addr
    finally:
        wb.close()


def test_protection_does_not_break_the_engine_read(template):
    """Protection is Excel-runtime only - openpyxl reads regardless (bit-identity safe)."""
    grids = extract_grids_openpyxl(str(template))
    out = run_headless(grids, risk_id_prefix="RSK", n_iter=2000, seed=42, view="owner")
    assert all(value == 0.0 for _p, value in out["p_table"])


def test_validate_button_passes_on_protected_template(template):
    wb = openpyxl.load_workbook(template)
    try:
        present = list(wb.defined_names)
        version = wb["Settings"]["B6"].value
    finally:
        wb.close()
    ok, msg = check_contract(present, extract_grids_openpyxl(str(template))["methodology"],
                             version)
    assert ok is True, msg
    assert CONTRACT_VERSION in msg


def test_layer1_grid_extent_not_exploded_by_protection():
    """The clamp keeps the Layer1 grids at their true extent (protecting an input block
    must not materialise empty cells that desync the extent-sized Grid_* ranges)."""
    wb = openpyxl.load_workbook(FIXTURE)
    try:
        assert wb["Layer1_Factors"].max_column == 6   # Factor..Column_Scope, not A:Z
        assert wb["Layer1_Correlation"].protection.sheet is True
    finally:
        wb.close()


def test_resize_helper_still_writes_on_a_protected_sheet(tmp_path):
    """openpyxl ignores protection when writing - the S3b resize mechanic still works."""
    import scripts.build_synthetic_wind_fixture as fx
    p = tmp_path / "w.xlsx"
    fx.build_register(p)
    wb = openpyxl.load_workbook(p)
    try:
        cs = wb["Layer1_Correlation"]
        assert cs.protection.sheet is True
        resize_layer1_correlation(cs, ["R_Turbine", "FX", "R_Concrete"])
        assert cs["A7"].value == "R_Concrete"  # wrote on the protected sheet
    finally:
        wb.close()


# --- Scope B: cascade completion ------------------------------------------

def test_package_and_factor_lists_seeded(template):
    wb = openpyxl.load_workbook(template, data_only=True)
    try:
        ls = wb["Lists"]
        assert ls["I3"].value == "Civil"          # List_Package seeded
        assert ls["J3"].value == "Labour rate"    # List_Factor generic seed (template)
    finally:
        wb.close()


def test_factor_dropdown_on_layer1_and_factor_seed_in_fixture():
    wb = openpyxl.load_workbook(FIXTURE)
    try:
        for sh in ("Layer1_Factors", "Layer1_Correlation"):
            formulas = {str(dv.formula1) for dv in wb[sh].data_validations.dataValidation}
            assert "List_Factor" in formulas, sh
        # the fixture seeds List_Factor with its own factor names
        assert wb["Lists"]["J3"].value == "Provisions"
    finally:
        wb.close()
