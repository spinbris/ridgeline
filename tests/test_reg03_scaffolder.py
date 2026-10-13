"""REG03 S1 locks - the register template scaffolder.

Gates (build brief REG03 S1 section 5):
- the empty template opens clean, carries the full named-range contract, and the
  generic engine reads it to a NIL result (zero risks), never a crash;
- contract round-trip: scaffold empty -> read -> zero risks / Layer 1 OFF, with no
  missing or extra named ranges;
- empty-template guard: the template ships NO project data (no risk rows, no factor
  values, blank MC_Params values), so a new project cannot inherit stale numbers;
- role separation: the fixture builder fills data while the scaffolder does not, so
  no live project register is ever regenerated with data by the fixture path;
- no-drift: the template and the CI fixture share ONE Risk Register header contract.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from src.register_contract import REQUIRED_NAMED_RANGES
from src.tier1_headless import extract_grids_openpyxl, run_headless
from tools.register_scaffold import (
    CG_CODES, EMITTED_ONLY_NAMES, GRID_NAMES, MODE_MULTIPLIERS_DEFAULT,
    RISK_HEADERS, METHODOLOGY_DEFAULT_CG, build_template,
)

REPO = Path(__file__).resolve().parents[1]

#: The exact named-range contract the empty template must emit. REG05-A2 (1.4):
#: Layer-1 is now STANDARD on every register, so Grid_Layer1_* + Set_Layer1_Enabled
#: ARE emitted (present-but-off via the flag); the SR19 mc_*/cfg_*/meth_* surface is
#: still NOT emitted (RefProject-V9 legacy, superseded by Grid_Methodology, per D1).
#: Single-sourced from src.register_contract so the template + Validate button +
#: this test cannot drift.
#: SRA-02 S-B adds Grid_Mapping as an EMITTED-but-not-REQUIRED name: requiring it
#: would fail Validate on every register scaffolded before it, which is a
#: contract-version bump on the client-number-bearing lane and forbidden by D-3.
EXPECTED_TEMPLATE_NAMES = set(REQUIRED_NAMED_RANGES) | set(EMITTED_ONLY_NAMES)


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("reg03") / "empty_template.xlsx"
    return build_template(out, prefix="RSK")


def test_template_opens_clean_with_expected_tabs(template):
    wb = openpyxl.load_workbook(template)
    try:
        assert wb["TOC & Instructions"] is not None  # opens, TOC present
        for tab in ("Risk Register", "Methodology", "Settings", "Simulation",
                    "Mapping", "Reference (xlwings)"):
            assert tab in wb.sheetnames, tab
    finally:
        wb.close()


def test_named_range_contract_exact(template):
    """Contract round-trip part 1: exactly the Surface-A + Layer-1 names, nothing
    missing or extra. REG05-A2: Grid_Layer1_* + Set_Layer1_Enabled ARE present now
    (present-but-off); still NO SR19 names."""
    wb = openpyxl.load_workbook(template)
    try:
        got = set(wb.defined_names)
    finally:
        wb.close()
    assert got == EXPECTED_TEMPLATE_NAMES
    assert sum(n.startswith("Grid_Layer1_") for n in got) == 4  # Layer 1 present
    assert "Set_Layer1_Enabled" in got                          # the off-signal
    assert not any(n.startswith(("mc_", "cfg_", "meth_")) for n in got)  # no SR19


def test_engine_reads_template_to_nil(template):
    """Contract round-trip part 2 + the nil-result gate: the generic engine reads
    the empty template to zero risks, all P-levels zero - no crash. REG05-A2: the
    Layer-1 sheets are now PRESENT-but-empty; Set_Layer1_Enabled ships FALSE so the
    read skips them (the empty-present parser crash from brief §8.1 never fires)."""
    grids = extract_grids_openpyxl(str(template))
    assert grids["layer1_enabled"] is False          # off-signal FALSE
    assert len(grids["layer1"]) == 4                  # present-but-empty, all four
    assert len(grids["methodology"]) == 1 + 13 + 3 + 6  # header + 13 CG + 3 modes + 6 settings (RS-D 2/6, F-30)
    out = run_headless(grids, risk_id_prefix="RSK", n_iter=2000, seed=42,
                       view="owner")
    assert out["layer1_enabled"] is False
    assert all(value == 0.0 for _p, value in out["p_table"])


def test_empty_template_ships_no_project_data(template):
    """Empty-template guard: no risk rows, no factor values, blank MC_Params
    values - a new project cannot inherit stale numbers."""
    wb = openpyxl.load_workbook(template, data_only=True)
    try:
        rr = wb["Risk Register"]
        # No data rows: every contract cell (cols 1-31) from row 5 down is blank.
        for row in rr.iter_rows(min_row=5, max_col=len(RISK_HEADERS)):
            assert all(c.value is None for c in row)
        # REG05-A2: the Layer-1 factor-model sheets are now PRESENT (present-but-off)
        # but carry no project data - a new project cannot inherit stale numbers.
        for sh in ("Layer1_Base", "Layer1_Factors", "Layer1_Allocation",
                   "Layer1_Correlation"):
            assert sh in wb.sheetnames
        base = wb["Layer1_Base"]
        assert all(not isinstance(c.value, (int, float))
                   for row in base.iter_rows() for c in row)  # no base $M numbers
        # REGUX-01 A-0.4: the factor grid ships at its real shape, blank - rows exist, names do not
        assert all(c.value is None for row in wb["Layer1_Factors"].iter_rows(min_row=2) for c in row)
        # MC_Params: labels present (col B) but every value cell (col C) blank.
        mp = wb["MC_Params"]
        labelled = [r for r in mp.iter_rows(min_col=2, max_col=3, values_only=True)
                    if r[0]]
        assert labelled, "MC_Params must carry the label contract"
        assert all(value is None for _label, value in labelled)
    finally:
        wb.close()


def test_methodology_defaults_are_neutral(template):
    """D1: the empty template ships CG=0.5 (neutral default, NOT the wind
    fixture's 0.6/0.5/0.4) and the locked mode multipliers 1.0/0.5/0.0."""
    wb = openpyxl.load_workbook(template, data_only=True)
    try:
        ms = wb["Methodology"]
        rows = {r[0]: r[1] for r in ms.iter_rows(min_row=2, max_col=2,
                                                 values_only=True) if r[0]}
    finally:
        wb.close()
    for code in CG_CODES:
        assert rows[code] == METHODOLOGY_DEFAULT_CG == 0.5, code
    for mode, mult in MODE_MULTIPLIERS_DEFAULT.items():
        assert rows[mode] == mult, mode


def test_p6_activity_binding_column_present_and_inert(template):
    """The P6-ready activity-binding column is present (col 31) but inert
    (no data in the empty template)."""
    assert RISK_HEADERS[-1] == "Schedule Activity ID (P6)"
    wb = openpyxl.load_workbook(template, data_only=True)
    try:
        rr = wb["Risk Register"]
        assert rr.cell(row=4, column=len(RISK_HEADERS)).value == "Schedule Activity ID (P6)"
        # inert: no bound activity in any (empty) data row
        assert all(rr.cell(row=r, column=len(RISK_HEADERS)).value is None
                   for r in range(5, 45))
    finally:
        wb.close()


def test_template_and_fixture_share_one_header_contract(template):
    """No-drift: the empty template and the committed CI fixture carry the SAME
    Risk Register header row (cols 1-30) - one contract, two consumers."""
    fixture = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"
    wb_t = openpyxl.load_workbook(template, data_only=True)
    wb_f = openpyxl.load_workbook(fixture, data_only=True)
    try:
        hdr_t = [wb_t["Risk Register"].cell(row=4, column=c).value
                 for c in range(1, len(RISK_HEADERS) + 1)]
        hdr_f = [wb_f["Risk Register"].cell(row=4, column=c).value
                 for c in range(1, len(RISK_HEADERS) + 1)]
    finally:
        wb_t.close(); wb_f.close()
    assert hdr_t == RISK_HEADERS
    # the fixture shares cols 1-30 (the frozen contract) and the new col 31
    assert hdr_f == RISK_HEADERS


def test_fixture_builder_fills_data_scaffolder_does_not(tmp_path):
    """Role separation: build_register (fixture) writes risk rows; build_template
    (scaffolder) writes none. The scaffolder never emits a data-bearing register,
    so it cannot regenerate a live project register with stale numbers."""
    import scripts.build_synthetic_wind_fixture as fixture_builder

    tmpl = build_template(tmp_path / "tmpl.xlsx")
    filled = tmp_path / "filled.xlsx"
    fixture_builder.build_register(filled)

    def data_row_count(path: Path) -> int:
        wb = openpyxl.load_workbook(path, data_only=True)
        try:
            rr = wb["Risk Register"]
            return sum(1 for r in range(5, rr.max_row + 1)
                       if rr.cell(row=r, column=1).value is not None)
        finally:
            wb.close()

    assert data_row_count(tmpl) == 0
    assert data_row_count(filled) == len(fixture_builder.WIND_RISKS) == 35
