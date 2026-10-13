"""SR-S3-Beta-19 §8 — Treatments sheet round-trip tests.

Covers the strawman Treatments sheet contract for Beta-19 §4:

* ``write_treatments_placeholder_sheet`` writes the expected schema
  (Risk_ID / Treatment_Description / Effectiveness_Pct /
  Effectiveness_Confidence) and one placeholder row per risk_id.
* The emitter is idempotent — calling it twice without ``overwrite``
  preserves an existing sheet (the workshop-edited rows are never
  destroyed).
* ``read_treatments`` round-trips: writing the placeholder rows and
  reading them back yields a 4-column DataFrame with the expected
  risk_ids and placeholder descriptions.
* A workshop-populated row (non-None effectiveness_pct) reads through
  as a float.

These tests use a synthetic workbook (no canonical strawman
required), so they are fast-lane and can run on any developer
machine without xlwings / Excel.
"""
from __future__ import annotations

from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from src.sra.strawman_reader import (  # noqa: E402
    read_treatments,
    write_treatments_placeholder_sheet,
)


def _make_minimal_strawman(path: Path) -> None:
    """Write a minimal workbook with just enough structure for the
    emitter to operate. No Risk_Scope / Risk_Pattern_Assignments
    sheets are required — the emitter writes a new Treatments sheet
    onto whatever workbook is supplied.
    """
    wb = openpyxl.Workbook()
    wb.active.title = "Placeholder"
    wb.save(str(path))


def test_write_treatments_placeholder_sheet_creates_schema(tmp_path: Path) -> None:
    """The emitter writes a Treatments sheet with the four canonical
    columns in row 1 and one placeholder row per risk_id starting at
    row 2. Each placeholder row has ``Workshop input required`` in
    the description column and empty effectiveness cells.
    """
    p = tmp_path / "synthetic_strawman.xlsx"
    _make_minimal_strawman(p)

    risk_ids = ["R001", "R013", "R067", "R090"]
    result = write_treatments_placeholder_sheet(
        strawman_path=p,
        risk_ids=risk_ids,
        recalc_via_excel=False,  # tests must not depend on Excel
    )
    assert result["action"] == "written"
    assert result["rows_written"] == 4

    wb = openpyxl.load_workbook(str(p))
    assert "Treatments" in wb.sheetnames
    ws = wb["Treatments"]
    # Row 1: headers.
    assert ws.cell(row=1, column=1).value == "Risk_ID"
    assert ws.cell(row=1, column=2).value == "Treatment_Description"
    assert ws.cell(row=1, column=3).value == "Effectiveness_Pct"
    assert ws.cell(row=1, column=4).value == "Effectiveness_Confidence"
    # Row 2+: one row per risk_id, placeholder copy.
    for i, rid in enumerate(risk_ids, start=2):
        assert ws.cell(row=i, column=1).value == rid
        assert ws.cell(row=i, column=2).value == "Workshop input required"
        assert ws.cell(row=i, column=3).value is None
        assert ws.cell(row=i, column=4).value is None
    wb.close()


def test_write_treatments_placeholder_sheet_is_idempotent(tmp_path: Path) -> None:
    """A second call without ``overwrite=True`` does not destroy the
    existing sheet. Workshop output edited in-place is preserved.
    """
    p = tmp_path / "synthetic.xlsx"
    _make_minimal_strawman(p)

    write_treatments_placeholder_sheet(
        strawman_path=p,
        risk_ids=["R001", "R013"],
        recalc_via_excel=False,
    )

    # Simulate a workshop edit on R001.
    wb = openpyxl.load_workbook(str(p))
    ws = wb["Treatments"]
    ws.cell(row=2, column=2, value="Pre-build long-lead inverters")
    ws.cell(row=2, column=3, value=40.0)
    wb.save(str(p))
    wb.close()

    # Second call without overwrite should skip.
    result = write_treatments_placeholder_sheet(
        strawman_path=p,
        risk_ids=["R001", "R013"],
        overwrite=False,
        recalc_via_excel=False,
    )
    assert result["action"] == "skipped_existing"

    # Verify the workshop edit survived.
    df = read_treatments(p)
    r001 = df[df["risk_id"] == "R001"].iloc[0]
    assert r001["treatment_description"] == "Pre-build long-lead inverters"
    assert r001["effectiveness_pct"] == 40.0


def test_write_treatments_placeholder_sheet_overwrite_rewrites(tmp_path: Path) -> None:
    """``overwrite=True`` rewrites the sheet to placeholder form
    (workshop edits are discarded — caller's responsibility).
    """
    p = tmp_path / "synthetic.xlsx"
    _make_minimal_strawman(p)

    write_treatments_placeholder_sheet(
        strawman_path=p, risk_ids=["R001"], recalc_via_excel=False,
    )
    wb = openpyxl.load_workbook(str(p))
    wb["Treatments"].cell(row=2, column=2, value="Workshop value")
    wb.save(str(p))
    wb.close()

    result = write_treatments_placeholder_sheet(
        strawman_path=p,
        risk_ids=["R001"],
        overwrite=True,
        recalc_via_excel=False,
    )
    assert result["action"] == "written"
    df = read_treatments(p)
    assert df.iloc[0]["treatment_description"] == "Workshop input required"


def test_read_treatments_empty_sheet_returns_empty_dataframe(tmp_path: Path) -> None:
    """A workbook without the Treatments sheet reads as an empty
    DataFrame with the canonical four columns. Legacy-strawman
    safety net per Beta-19 §4.
    """
    p = tmp_path / "no_treatments.xlsx"
    _make_minimal_strawman(p)

    df = read_treatments(p)
    assert df.empty
    assert list(df.columns) == [
        "risk_id",
        "treatment_description",
        "effectiveness_pct",
        "effectiveness_confidence",
    ]


def test_read_treatments_returns_populated_rows(tmp_path: Path) -> None:
    """A workshop-populated row reads through as the expected types:
    risk_id as str, treatment_description as str, effectiveness_pct
    as float, effectiveness_confidence as str.
    """
    p = tmp_path / "populated.xlsx"
    _make_minimal_strawman(p)

    write_treatments_placeholder_sheet(
        strawman_path=p,
        risk_ids=["R067", "R013"],
        recalc_via_excel=False,
    )
    wb = openpyxl.load_workbook(str(p))
    ws = wb["Treatments"]
    ws.cell(row=2, column=2, value="Pre-build long-lead inverters")
    ws.cell(row=2, column=3, value=40.0)
    ws.cell(row=2, column=4, value="Medium")
    wb.save(str(p))
    wb.close()

    df = read_treatments(p)
    assert len(df) == 2
    populated = df[df["risk_id"] == "R067"].iloc[0]
    assert populated["treatment_description"] == "Pre-build long-lead inverters"
    assert populated["effectiveness_pct"] == 40.0
    assert populated["effectiveness_confidence"] == "Medium"
    # Other row stays as placeholder.
    placeholder = df[df["risk_id"] == "R013"].iloc[0]
    assert placeholder["treatment_description"] == "Workshop input required"
    # Empty effectiveness cell reads through as None / NaN depending on
    # pandas dtype coercion in the populated DataFrame.
    import pandas as pd  # noqa: PLC0415 (test-local check)
    eff_pct = placeholder["effectiveness_pct"]
    assert eff_pct is None or pd.isna(eff_pct)


@pytest.mark.slow
@pytest.mark.skipif(
    not __import__("os").environ.get("OUTTURN_DESKTOP_EXCEL"),
    reason="needs desktop Excel; the weekly full-suite runner sets OUTTURN_DESKTOP_EXCEL=1 (PROCDIET-01 R3)",
)
def test_the_desktop_excel_recalc_runs(tmp_path: Path) -> None:
    """PROCDIET-01 R3: the desktop-Excel recalc is exercised weekly, on the machine that has
    Excel. The emitter swallows an Excel failure into ``recalc == "failed"``, so the verdict is
    read from the result rather than from the absence of an exception."""
    p = tmp_path / "synthetic_strawman.xlsx"
    _make_minimal_strawman(p)
    result = write_treatments_placeholder_sheet(strawman_path=p, risk_ids=["R001"],
                                                recalc_via_excel=True)
    assert result["recalc"] == "excel", result.get("recalc_error")
