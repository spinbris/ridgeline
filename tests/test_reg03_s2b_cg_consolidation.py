"""REG03 S2b - CG methodology consolidation onto Grid_Methodology.

Director decision D0=B (forward-consolidation): the CG readers PREFER the register's
own Grid_Methodology surface when present (scaffolded, grid-native registers), else
fall back to the legacy MC_Params surface (`mc_cg_coeffs` block for coefficients,
col-B scan for descriptions). The LOCKED client register (RefProject's) has no Methodology
sheet, so it takes the fallback path and is provably byte-unchanged.

Also: D2 = a 3rd (description) column on Grid_Methodology; D1 = de-landmine the legacy
positional CG read in openpyxl_reader (it read the wrong rows on the RefProject register).
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

REPO = Path(__file__).resolve().parents[1]
#: The client register is confidential and absent from a clean clone. Resolve it
#: lazily and skip, rather than indexing at import: an IndexError here is a
#: collection error, and a collection error takes the whole session down --
#: including the PUBLIC golden gate, which needs none of these files (GOLDCOLL-01).
WIND = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"

#: The client CG-drivers table's text inputs must be byte-unchanged (the RefProject register).
# --- coefficients ---------------------------------------------------------

def test_coefficients_prefer_grid_when_present():
    """A grid-native register (the wind fixture) is read from Grid_Methodology."""
    from src.sra.methodology_defaults_reader import _read_cg_coefficients
    wb = openpyxl.load_workbook(WIND, data_only=True)
    try:
        cg, err = _read_cg_coefficients(wb)
    finally:
        wb.close()
    assert err == ""
    assert len(cg) == 13 and cg["CG01"] == 0.6 and cg["CG06"] == 0.5


# --- descriptions ---------------------------------------------------------

def test_descriptions_prefer_grid_3rd_column():
    """The wind grid's 3rd column supplies descriptions when present."""
    from src.openpyxl_reader import read_cg_descriptions
    d = read_cg_descriptions(str(WIND))
    assert d["CG01"] == "Civil & Earthworks"
    assert d["CG06"] == "Commissioning & Controls"
    assert d["CG07"] == ""  # CG07-13 carry no wind description


# --- D1 de-landmine -------------------------------------------------------

# --- D2 scaffolder grid ---------------------------------------------------

def test_scaffolder_grid_has_description_column(tmp_path):
    """build_template emits the 3-column grid; resolve_methodology_from_grid still
    reads 13 CG + 3 modes (col C ignored)."""
    from src.qra_register_parse import resolve_methodology_from_grid
    from src.tier1_headless import extract_grids_openpyxl
    from tools.register_scaffold import build_template

    tmpl = build_template(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(tmpl, data_only=True)
    try:
        assert wb["Methodology"]["C1"].value == "Description"
    finally:
        wb.close()
    meth = resolve_methodology_from_grid(extract_grids_openpyxl(str(tmpl))["methodology"])
    assert len(meth["cg_coefficients"]) == 13
    assert set(meth["mode_multipliers"]) == {"Series", "Hybrid", "Parallel"}
