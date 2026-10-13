"""SR12 — audit trail and strawman reader tests.

Covers Acceptance Criteria 2, 7 from the SR12 brief:

* AC2 — three new Risk_Scope columns (injection_method,
  gating_activity_id, injection_method_notes) read by the strawman
  reader, defaulting to empty string on legacy strawmans.
* AC7 — auto_mapper parquet audit trail carries injection_method AND
  gating_activity_id per risk.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

from src.sra import strawman_reader
from src.sra.cpm.auto_mapper import write_audit_trail
from src.sra.cpm.risk_driver_schema import (
    AutoMapAuditRow,
    RiskDriver,
)

import pytest

# RS-B step 2: this module asserts against the reference project's register
# shape, RBS map or narrative templates, so it selects that binding explicitly
# rather than inheriting the suite default.
pytestmark = pytest.mark.project("fixture_r_prefix")   # REFRETIRE-01: the fixtures here carry R-prefixed risk IDs


# ---------------------------------------------------------------------------
# Strawman reader — SR12 columns
# ---------------------------------------------------------------------------


def _build_risk_scope_workbook(
    tmp_path: Path,
    rows: list[dict],
    *,
    include_sr12_columns: bool = True,
) -> Path:
    """Build a minimal workbook with the Risk_Scope sheet shape the reader
    expects (header row 1, data rows below)."""
    base_headers = [
        "Risk_ID", "Risk_Title", "Risk_Owner", "RBS_L1",
        "Time_Impact", "Dual_Coded", "Pattern_ID", "Pattern_Description",
        "Prefix_List", "Is_Cost_Only", "Activity_Count", "Min_Total_Float",
        "Mode_Aggregated", "Series_Source", "Probability", "Probability_Time",
        "Opt_Days", "ML_Days", "Pess_Days", "LD_Considered", "Day_Rate",
        "Reconciliation_Treatment", "EMV_days_Simple", "EMV_days_PERT",
        "EMV_cost_Simple", "EMV_cost_PERT", "Finish_delay_contribution",
        "Finish_delay_days", "Finish_delay_dollars", "Review_Flag",
    ]
    headers = list(base_headers)
    if include_sr12_columns:
        headers += [
            "Injection_Method", "Gating_Activity_ID", "Injection_Method_Notes",
        ]
    wb = Workbook()
    ws = wb.active
    ws.title = "Risk_Scope"
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
    for r_idx, row in enumerate(rows, start=2):
        for c_idx, h in enumerate(headers, start=1):
            key = h
            if key in row:
                ws.cell(row=r_idx, column=c_idx, value=row[key])
    out = tmp_path / "sr12_strawman.xlsx"
    wb.save(out)
    return out


class TestStrawmanReaderSR12Columns:

    def test_reader_exposes_new_columns_when_present(self, tmp_path: Path) -> None:
        path = _build_risk_scope_workbook(
            tmp_path,
            [
                {
                    "Risk_ID": "R013",
                    "Time_Impact": "Yes",
                    "Mode_Aggregated": "Series",
                    "Probability": 0.6, "Probability_Time": 0.6,
                    "Opt_Days": 0.0, "ML_Days": 0.0, "Pess_Days": 14.0,
                    "Injection_Method": "discrete_event_additive_days",
                    "Gating_Activity_ID": "A100",
                    "Injection_Method_Notes": "Workshop pilot",
                },
            ],
        )
        df = strawman_reader.read_risk_scope(path)
        assert "injection_method" in df.columns
        assert "gating_activity_id" in df.columns
        assert "injection_method_notes" in df.columns
        row = df.iloc[0]
        assert row["injection_method"] == "discrete_event_additive_days"
        assert row["gating_activity_id"] == "A100"
        assert row["injection_method_notes"] == "Workshop pilot"

    def test_reader_returns_empty_for_legacy_strawman_without_columns(
        self, tmp_path: Path,
    ) -> None:
        path = _build_risk_scope_workbook(
            tmp_path,
            [
                {
                    "Risk_ID": "R013",
                    "Time_Impact": "Yes",
                    "Mode_Aggregated": "Series",
                    "Probability": 0.6, "Probability_Time": 0.6,
                    "Opt_Days": 0.0, "ML_Days": 0.0, "Pess_Days": 14.0,
                },
            ],
            include_sr12_columns=False,
        )
        df = strawman_reader.read_risk_scope(path)
        # Reader returns the canonical column set always — missing ones
        # are None.
        assert df.iloc[0]["injection_method"] is None
        assert df.iloc[0]["gating_activity_id"] is None
        assert df.iloc[0]["injection_method_notes"] is None

    def test_reader_handles_blank_cells(self, tmp_path: Path) -> None:
        path = _build_risk_scope_workbook(
            tmp_path,
            [
                {
                    "Risk_ID": "R001",
                    "Time_Impact": "Yes",
                    "Mode_Aggregated": "Series",
                    "Probability": 0.5, "Probability_Time": 0.5,
                    "Opt_Days": 1.0, "ML_Days": 2.0, "Pess_Days": 4.0,
                    # Sr12 columns left blank.
                },
            ],
        )
        df = strawman_reader.read_risk_scope(path)
        assert df.iloc[0]["injection_method"] == ""
        assert df.iloc[0]["gating_activity_id"] == ""
        assert df.iloc[0]["injection_method_notes"] == ""


# ---------------------------------------------------------------------------
# Audit trail — SR12 gating_activity_id column
# ---------------------------------------------------------------------------


class TestAuditTrailInjectionMethod:

    def test_audit_row_carries_injection_method_field(self) -> None:
        names = [f.name for f in dataclasses.fields(AutoMapAuditRow)]
        assert "injection_method" in names
        assert "gating_activity_id" in names

    def test_parquet_includes_gating_activity_id(
        self, tmp_path: Path,
    ) -> None:
        drivers = {
            "R013": RiskDriver(
                risk_id="R013",
                affected_activity_ids=("a1", "a2"),
                injection_method="discrete_event_additive_days",
                opt_pert=0.0, ml_pert=0.0, pess_pert=14.0,
                probability=0.6,
                pattern_id="P01",
                derived_at_run_time=False,
                workshop_validated=True,
                gating_activity_id="a1",
            ),
            "R001": RiskDriver(
                risk_id="R001",
                affected_activity_ids=("a3",),
                injection_method="additive_pert_days",
                opt_pert=1.0, ml_pert=2.0, pess_pert=4.0,
                probability=0.5,
                pattern_id="P02",
            ),
        }
        out_path = tmp_path / "audit.parquet"
        write_audit_trail(drivers, out_path)
        df = pd.read_parquet(out_path)
        assert "injection_method" in df.columns
        assert "gating_activity_id" in df.columns
        r013_rows = df[df["risk_id"] == "R013"]
        assert all(
            r013_rows["injection_method"] == "discrete_event_additive_days"
        )
        assert all(r013_rows["gating_activity_id"] == "a1")
        r001_rows = df[df["risk_id"] == "R001"]
        # Non-discrete methods write empty gating field.
        assert all(r001_rows["gating_activity_id"] == "")
