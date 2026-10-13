"""REPORT01 F-F / D-3: the register's two Basis of Estimate columns reach the risk row.

The V5 register carries `Basis of Estimate` **twice** - once in the Contingent Risk Cost
section and once in the Time (Working Days) section. `parse_risks_from_grid` locates both
(`qra_register_parse.py` `cont_terms["basis"]` and `time_terms["time_basis"]`) but before
REPORT01 assigned only the first: the time column was resolved to an index and then dropped,
so no consumer could ever see it.

These tests pin both. The cost limb guards a field that already worked; the time limb is
D-3's fix and was red before it.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from src.v5_register_reader import read_risks_v5

# Column layout of the minimal V5-shaped register below. Mirrors the section/header
# geometry the reader scans for, not the full production register.
_CONT_HEADERS = {
    3: "Cost Impact", 4: "Probability", 5: "Optimistic ($)",
    6: "Most Likely ($)", 7: "Pessimistic ($)", 8: "Basis of Estimate",
}
_TIME_HEADERS = {
    10: "Time Impact", 11: "Probability", 12: "Optimistic",
    13: "Most Likely", 14: "Pessimistic", 15: "Basis of Estimate",
}

COST_BASIS = "ECI agreed - package 4 quotation"
TIME_BASIS = "Workshop agreed - 2026-03-11 session"


def _build_register(tmp_path: Path, *, cost_basis=COST_BASIS, time_basis=TIME_BASIS) -> Path:
    """Minimal V5-shaped Risk Register with both Basis of Estimate cells populated."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Risk Register"
    wb.create_sheet("MC_Params")
    ws.cell(row=3, column=3, value="Contingent Risk Cost")
    ws.cell(row=3, column=10, value="Time (Working Days)")
    ws.cell(row=4, column=1, value="Risk ID")
    ws.cell(row=4, column=2, value="MC Include")
    for c, v in {**_CONT_HEADERS, **_TIME_HEADERS}.items():
        ws.cell(row=4, column=c, value=v)
    row5 = {
        1: "R001", 2: "Yes",
        3: "Yes", 4: 0.5, 5: 100.0, 6: 200.0, 7: 300.0, 8: cost_basis,
        10: "Yes", 11: 0.4, 12: 5.0, 13: 10.0, 14: 20.0, 15: time_basis,
    }
    for c, v in row5.items():
        ws.cell(row=5, column=c, value=v)
    p = tmp_path / "basis_register.xlsx"
    wb.save(p)
    return p


def _one_risk(tmp_path: Path, **kw):
    risks = read_risks_v5(_build_register(tmp_path, **kw), risk_id_prefix="R")
    assert len(risks) == 1, f"expected one parsed risk, got {len(risks)}"
    return risks[0]


def test_cost_basis_of_estimate_reaches_the_risk(tmp_path):
    """The Contingent section's Basis of Estimate lands on RiskInput.basis."""
    assert _one_risk(tmp_path).basis == COST_BASIS


def test_time_basis_of_estimate_reaches_the_risk(tmp_path):
    """D-3: the Time section's Basis of Estimate lands on RiskInput.time_basis.

    Red before REPORT01 - the column was located and then never assigned, so this
    raised AttributeError rather than returning the wrong string.
    """
    assert _one_risk(tmp_path).time_basis == TIME_BASIS


def test_the_two_bases_do_not_cross_over(tmp_path):
    """Distinct values stay in their own field.

    The two columns share the header text `Basis of Estimate`, and are told apart only
    by which section band they fall in. A section-bounds regression would read one
    column into both fields, which each single-field test above would still pass.
    """
    risk = _one_risk(tmp_path)
    assert (risk.basis, risk.time_basis) == (COST_BASIS, TIME_BASIS)


@pytest.mark.parametrize("missing", ["cost_basis", "time_basis"])
def test_an_unrecorded_basis_reads_as_empty_not_as_a_placeholder(tmp_path, missing):
    """P-5: blank stays blank.

    A risk with no recorded basis must reach the report as an empty string, so the
    rendering layer can say "not recorded". It must never acquire a default that a
    reader could mistake for an agreed elicitation.
    """
    risk = _one_risk(tmp_path, **{missing: None})
    field = "basis" if missing == "cost_basis" else "time_basis"
    assert getattr(risk, field) == ""
