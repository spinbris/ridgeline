"""REG05-A2-FIX - Layer-1 read coverage (D1) + empty-starter consistency (D2).

Closes the gap the in-Excel gate found (the A2 suite only ever ran the headless
whole-sheet read with the flag FALSE; nothing read a FILLED empty-template Layer-1
via the xlwings named-range path):

- D1 round-trip: scaffold empty -> fill all four Layer-1 tabs -> read -> the parsed
  Layer1Config matches the fill and a run is Layer-1-ON. Exercised both via the
  headless used-range reader AND via the xlwings shell's ``read_grids_xlwings`` (over
  a FakeBook), with the ``Grid_Layer1_*`` names left at their stale empty-shell size -
  the exact failure mode: a name-read saw only the shell, the used-range read sees the
  fill.
- D2 empty-consistency: the untouched empty template ships ``Layer1_Correlation`` BARE,
  so the factor sets across Factors/Allocation/Correlation are all empty and mutually
  consistent (a seeded correlation declared 7 factors defined nowhere).
- Regression: the wind fixture Layer-1 read stays byte-identical (D2 must not touch the
  fixture path); the bare template still reads to nil with the flag FALSE.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import openpyxl
import pytest

from src.tier1_headless import (
    _layer1_from_grids, extract_grids_openpyxl, run_headless,
)
from src.tier1_xlwings_shell import read_grids_xlwings
from tools.register_scaffold import build_template

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"


# --- a FakeBook: openpyxl-backed emulation of the xlwings Book the shell reads ---
# read_grids_xlwings touches only book.names[nm].refers_to_range.value (scalars +
# the Grid_RiskRegister/Grid_Methodology ranges) and book.sheets[name].range(addr)
# .value (the Layer-1 used-range read). This backs both onto an openpyxl workbook so
# the Excel-only shell read is exercised in CI.

def _region_values(ws, coord):
    reg = ws[coord]
    if not isinstance(reg, tuple):          # single cell
        return reg.value
    return [[c.value for c in row] for row in reg]


class _Rng:
    def __init__(self, v): self.value = v


class _Name:
    def __init__(self, rng): self.refers_to_range = rng


class _Names:
    def __init__(self, wb): self._wb = wb

    def __getitem__(self, name):
        dn = self._wb.defined_names[name]   # KeyError if absent (as xlwings)
        title, coord = list(dn.destinations)[0]
        return _Name(_Rng(_region_values(self._wb[title], coord.replace("$", ""))))


class _Sheet:
    def __init__(self, ws): self._ws = ws

    def range(self, addr): return _Rng(_region_values(self._ws, addr))


class _Sheets:
    def __init__(self, wb): self._wb = wb

    def __getitem__(self, name): return _Sheet(self._wb[name])   # KeyError if absent


class FakeBook:
    def __init__(self, wb):
        self.names = _Names(wb)
        self.sheets = _Sheets(wb)


# --- a small, VALID Layer-1 fill (base sum == declared; corr PSD) ---------------

def _fill_layer1(wb) -> None:
    """Write a minimal consistent Layer-1 into a scaffolded (empty) workbook, WITHOUT
    resizing the Grid_Layer1_* names (mirrors a user just typing into the tabs)."""
    b = wb["Layer1_Base"]
    for row in list(b.iter_rows()):
        for c in row:
            c.value = None
    b["A1"], b["B1"], b["C1"] = "WBS Row", "Labour", "Plant"
    b["A2"], b["B2"], b["C2"] = "Civils", 10.0, 5.0
    b["A3"], b["B3"], b["C3"] = "Electrical", 8.0, 2.0
    b["A5"], b["B5"] = "Declared_Total ($M)", 25.0        # 10+5+8+2 = 25
    b["A6"], b["B6"] = "Units", "$M (read x 1,000,000 -> dollars)"

    f = wb["Layer1_Factors"]
    f["A2"], f["B2"], f["C2"], f["D2"], f["E2"], f["F2"] = \
        "Labour rate", "labour_rate", -0.05, 0.0, 0.1, "Labour"
    f["A3"], f["B3"], f["C3"], f["D3"], f["E3"], f["F3"] = \
        "Plant rate", "plant_rate", -0.05, 0.0, 0.1, "Plant"

    a = wb["Layer1_Allocation"]
    a["A1"], a["B1"], a["C1"] = "Factor", "Civils", "Electrical"
    a["A2"], a["B2"], a["C2"] = "Labour rate", "x", "x"
    a["A3"], a["B3"], a["C3"] = "Plant rate", "x", ""

    cs = wb["Layer1_Correlation"]
    cs["A4"], cs["B4"], cs["C4"] = "Factor", "Labour rate", "Plant rate"
    cs["A5"], cs["B5"] = "Labour rate", 1.0
    cs["A6"], cs["B6"], cs["C6"] = "Plant rate", 0.2, 1.0

    wb["Settings"]["B8"] = True                           # Set_Layer1_Enabled


def _assert_matches_fill(cfg) -> None:
    assert cfg is not None
    assert cfg.row_labels == ("Civils", "Electrical")
    assert cfg.col_labels == ("Labour", "Plant")
    assert cfg.declared_total == 25_000_000.0
    assert np.array_equal(cfg.base, np.array([[10e6, 5e6], [8e6, 2e6]]))
    assert [f.name for f in cfg.factors] == ["Labour rate", "Plant rate"]
    assert cfg.corr_names == ("Labour rate", "Plant rate")
    assert cfg.corr_matrix[1, 0] == 0.2


@pytest.fixture
def filled_template(tmp_path) -> Path:
    p = build_template(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(p)
    _fill_layer1(wb)
    wb.save(p)
    wb.close()
    return p


# --- D1: the scaffold -> fill -> read round-trip (the missing test) -------------

def test_roundtrip_headless_used_range_read(filled_template):
    """Headless used-range read (extract_grids_openpyxl) sees the fill and a run is ON."""
    grids = extract_grids_openpyxl(str(filled_template))
    assert grids["layer1_enabled"] is True
    _assert_matches_fill(_layer1_from_grids(grids))

    out = run_headless(grids, risk_id_prefix="RSK", n_iter=1000, seed=42, view="owner")
    assert out["layer1_enabled"] is True
    assert out["cost_mean"] > 0.0


def test_roundtrip_xlwings_read_sees_fill_despite_stale_grid_names(filled_template):
    """D1 core: read_grids_xlwings reads the FILLED Layer-1 via the used range even
    though Grid_Layer1_* are still sized to the empty-template shell. On the pre-fix
    name-read this returned only the shell (base sum != declared, 0 factors)."""
    wb = openpyxl.load_workbook(filled_template, data_only=True)
    try:
        # precondition: the names really are stale (empty-shell extent), so this test
        # would FAIL on a name-based read.
        # REGUX-01 A-0.4: the template's names now cover the real grid, so the stale-name
        # scenario is made deliberately - the name is shrunk to the old one-cell shell, and
        # the used-range read must still see the fill.
        wb.defined_names["Grid_Layer1_Base"].attr_text = "'Layer1_Base'!$A$1:$B$4"
        _t, coord = list(wb.defined_names["Grid_Layer1_Base"].destinations)[0]
        assert coord.replace("$", "") == "A1:B4", coord  # shell, not the fill

        grids = read_grids_xlwings(FakeBook(wb))
    finally:
        wb.close()
    assert grids["layer1_enabled"] is True
    _assert_matches_fill(_layer1_from_grids(grids))


def test_xlwings_and_headless_reads_agree(filled_template):
    """The two read paths produce the same Layer-1 (Tier-1 == Tier-2 on the read)."""
    hl = _layer1_from_grids(extract_grids_openpyxl(str(filled_template)))
    wb = openpyxl.load_workbook(filled_template, data_only=True)
    try:
        xl = _layer1_from_grids(read_grids_xlwings(FakeBook(wb)))
    finally:
        wb.close()
    assert xl.factors == hl.factors
    assert xl.corr_names == hl.corr_names
    assert np.array_equal(xl.base, hl.base)
    assert xl.declared_total == hl.declared_total


# --- D2: empty-starter consistency ----------------------------------------------

def _col_a_names(ws, min_row):
    return [ws.cell(row=r, column=1).value
            for r in range(min_row, ws.max_row + 1)
            if ws.cell(row=r, column=1).value not in (None, "")]


def test_empty_template_layer1_is_empty_and_consistent(tmp_path):
    """The untouched empty template ships all four Layer-1 tabs empty; in particular
    Layer1_Correlation carries NO factor rows (D2 - was seeded with 7 List_Factor
    names + identity, declaring factors defined nowhere)."""
    p = build_template(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(p)
    try:
        cs = wb["Layer1_Correlation"]
        header = next(r for r in range(1, cs.max_row + 1)
                      if str(cs.cell(row=r, column=1).value or "").lower() == "factor")
        corr_factors = [c.value for c in cs[header][1:] if c.value is not None]
        factors_defined = _col_a_names(wb["Layer1_Factors"], 2)
        alloc_factors = _col_a_names(wb["Layer1_Allocation"], 2)
        # all three factor surfaces empty -> mutually consistent
        assert corr_factors == []
        assert factors_defined == []
        assert alloc_factors == []
        # the List_Factor dropdowns are kept so the user still picks from the cascade
        assert wb["Layer1_Factors"].data_validations.dataValidation
        assert wb["Layer1_Correlation"].data_validations.dataValidation
    finally:
        wb.close()


def test_empty_template_reads_nil_with_flag_false(tmp_path):
    """D2 regression: the bare-correlation empty template still reads to nil (flag
    FALSE), no crash."""
    p = build_template(tmp_path / "t.xlsx")
    grids = extract_grids_openpyxl(str(p))
    assert grids["layer1_enabled"] is False
    out = run_headless(grids, risk_id_prefix="RSK", n_iter=1000, seed=42, view="owner")
    assert out["layer1_enabled"] is False
    assert all(v == 0.0 for _p, v in out["p_table"])


# --- regression: the wind FIXTURE path is untouched by D2 -----------------------

def test_wind_fixture_layer1_read_byte_identical(tmp_path):
    """D2 must not touch the fixture path: regenerating the fixture reproduces the
    committed Layer-1 read byte-identically (the filled branch is unchanged)."""
    import scripts.build_synthetic_wind_fixture as fx
    from src.v5_register_reader import read_layer1_v5

    regen = tmp_path / "wind.xlsx"
    fx.build_register(regen)

    def fp(p):
        c = read_layer1_v5(str(p))
        return (c.row_labels, c.col_labels, c.base.tolist(), [str(x) for x in c.factors],
                c.corr_names, c.corr_matrix.tolist(), c.corr_mode, c.declared_total)

    assert fp(regen) == fp(FIXTURE)
