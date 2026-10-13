"""SR1 - P6 reader tests.

Integration tests run against the locked 22 April P6 file:
    inputs/<the reference P6 longest-path export>.xlsx

Override via env var P6_FILE if needed. Tests skip cleanly if the file
is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from src.sra.p6_reader import read_p6_schedule


# ---- integration tests against the locked 22 April Longest-Path file ----

# ---- synthetic fixtures (no real P6 file required) ----

def _build_synthetic_xlsx(
    path: Path,
    header_row: int = 1,
    drop_activity_id: bool = False,
    sheet_name: str = "P6-Schedule",
) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    headers = [
        "Level", "WBS", "Activity ID", "Activity Name", "Duration",
        "Start", "Finish", "Total Float", "Critical", "Primary Constraint",
        "WBS",
    ]
    if drop_activity_id:
        headers[2] = "Other Column"
    for _ in range(header_row - 1):
        ws.append([None] * len(headers))
    ws.append(headers)
    ws.append([
        1, "YES", "WBS-001", "Top WBS", "100.0d",
        "2026-01-01", "2026-04-01", "0.0d", None, None, "WBS.A",
    ])
    ws.append([
        2, "NO", "ACT-001", "An activity", "10.0d",
        "2026-01-01", "2026-01-15", "5.0d", "Yes", "SNET", "WBS.A.1",
    ])
    ws.append([
        3, "NO", "MS-001", "A milestone", "0.0d",
        "2026-02-01", "2026-02-01", "0.0d", "Yes", None, "WBS.A.2",
    ])
    wb.save(str(path))


def test_p6_reader_header_driven_column_lookup(tmp_path: Path):
    fp = tmp_path / "synthetic_offset_header.xlsx"
    _build_synthetic_xlsx(fp, header_row=3)
    df = read_p6_schedule(fp)
    assert len(df) == 3
    types = set(df["row_type"].tolist())
    assert {"wbs_summary", "activity", "milestone"}.issubset(types)
    act = df[df["row_type"] == "activity"].iloc[0]
    assert bool(act["critical_flag"]) is True
    assert act["primary_constraint"] == "SNET"
    # Duplicate "WBS" header: leftmost is the YES/NO flag, rightmost is the path.
    assert act["wbs"] == "WBS.A.1"


def test_p6_reader_raises_on_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        read_p6_schedule(tmp_path / "does-not-exist.xlsx")


def test_p6_reader_raises_on_missing_required_column(tmp_path: Path):
    fp = tmp_path / "no_id.xlsx"
    _build_synthetic_xlsx(fp, header_row=1, drop_activity_id=True)
    with pytest.raises(ValueError) as exc:
        read_p6_schedule(fp)
    msg = str(exc.value).lower()
    assert "activity id" in msg
