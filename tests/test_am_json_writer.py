"""Tests for src.am.json_writer.

Validates the JSON contract (Doc 3 v2.2 §"Validation requirements"
rules 1-11) against a synthetic conditional-run result + AMMetrics
bundle. The synthetic inputs let us exercise every contract rule
without invoking the Stage 3 engine.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest


from src.sra.cpm.risk_driver_schema import RiskDriver

from src.am.conditional_runner import (
    ACTION_KEPT_BASELINE,
    ConditionalRunResult,
    PinnedRiskState,
)
from src.am.json_writer import (
    JsonWriterError,
    _is_open_status,
    write_period_json,
)
from src.am.metrics import (
    ActivityPBand,
    AMMetrics,
    build_methodology_notes,
)
from src.am.workbook_reader import WorkbookData


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Synthetic builders
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _StubScheduleMCResult:
    project_finish_hours: np.ndarray
    project_finish_days: np.ndarray
    criticality_index: dict[str, float]
    activity_ids: tuple[str, ...]
    finish_mean_hours: np.ndarray
    finish_std_hours: np.ndarray
    total_float_mean_hours: np.ndarray
    deterministic_critical_path: tuple[str, ...]
    n_iter: int
    n_act: int
    seed_used: int


def _stub_schedule_result(seed: int = 0) -> _StubScheduleMCResult:
    rng = np.random.default_rng(seed)
    n = 1000
    project_h = rng.normal(loc=9000, scale=150, size=n).astype(np.float32)
    return _StubScheduleMCResult(
        project_finish_hours=project_h,
        project_finish_days=(project_h / 8.0).astype(np.float32),
        criticality_index={"a1": 0.9, "a2": 0.5, "a3": 0.2},
        activity_ids=("a1", "a2", "a3"),
        finish_mean_hours=np.array([100.0, 200.0, 9000.0], dtype=np.float64),
        finish_std_hours=np.array([5.0, 10.0, 150.0], dtype=np.float64),
        total_float_mean_hours=np.array([0.0, 80.0, 0.0], dtype=np.float64),
        deterministic_critical_path=("a1", "a3"),
        n_iter=n,
        n_act=3,
        seed_used=42,
    )


def _stub_conditional_result(schedule_result) -> ConditionalRunResult:
    return ConditionalRunResult(
        schedule_result=schedule_result,
        pinned_states=(
            PinnedRiskState(
                risk_id="R001",
                action=ACTION_KEPT_BASELINE,
                original_probability=0.3,
                new_probability=0.3,
                original_mode="Series",
                new_mode="Series",
            ),
            PinnedRiskState(
                risk_id="R002",
                action=ACTION_KEPT_BASELINE,
                original_probability=0.1,
                new_probability=0.1,
                original_mode="Hybrid",
                new_mode="Hybrid",
            ),
        ),
        fired_baseline_uplift_days=0.0,
        excluded_risk_ids=(),
        config_summary={
            "n_iter": 1000,
            "seed": 42,
            "criticality_measurement_mode": "both",
            "n_drivers_input": 2,
            "n_drivers_after_pinning": 2,
            "n_excluded": 0,
            "fired_baseline_uplift_days": 0.0,
        },
    )


def _stub_drivers() -> dict[str, RiskDriver]:
    return {
        "R001": RiskDriver(
            risk_id="R001",
            affected_activity_ids=("a1", "a2"),
            injection_method="additive_pert_days",
            opt_pert=0.0, ml_pert=5.0, pess_pert=20.0,
            probability=0.3, mode="Series",
        ),
        "R002": RiskDriver(
            risk_id="R002",
            affected_activity_ids=("a3",),
            injection_method="additive_pert_days",
            opt_pert=0.0, ml_pert=3.0, pess_pert=15.0,
            probability=0.1, mode="Hybrid",
        ),
    }


def _stub_workbook_data() -> WorkbookData:
    return WorkbookData(
        period_info={"am_period_end": "2026-05-22"},
        risk_status=[
            {
                "risk_id": "R001",
                "risk_title": "First test risk",
                "status_this_period": "Open",
                "probability_current": 0.3,
                "probability_override": None,
                "probability_resolved": 0.3,
                "owner": "Unassigned",
                "mode_current": "Series",
                "mode_override": None,
                "mode_resolved": "Series",
                "status_changed": None,
                "fired_date": None,
                "closed_date": None,
                "notes_this_period": None,
                "helper_data_missing": False,
            },
            {
                "risk_id": "R002",
                "risk_title": "Second test risk",
                "status_this_period": "Monitor",
                "probability_current": 0.1,
                "probability_override": None,
                "probability_resolved": 0.1,
                "owner": "Unassigned",
                "mode_current": "Hybrid",
                "mode_override": None,
                "mode_resolved": "Hybrid",
                "status_changed": None,
                "fired_date": None,
                "closed_date": None,
                "notes_this_period": None,
                "helper_data_missing": False,
            },
        ],
        milestones=[],
        mitigations=[],
        am_risk_ids=["R001", "R002"],
    )


def _stub_am_metrics() -> AMMetrics:
    return AMMetrics(
        per_activity_p_bands=[
            ActivityPBand(
                activity_id="a1", name="Activity A1",
                p10_start_days=0.0, p50_start_days=0.0, p90_start_days=0.0,
                p10_finish_days=10.0, p50_finish_days=12.5, p90_finish_days=15.0,
                det_es_days=0.0, det_ef_days=10.0,
                criticality_index=0.9,
            ),
            ActivityPBand(
                activity_id="a2", name="Activity A2",
                p10_start_days=10.0, p50_start_days=12.0, p90_start_days=14.0,
                p10_finish_days=20.0, p50_finish_days=24.0, p90_finish_days=28.0,
                det_es_days=10.0, det_ef_days=24.0,
                criticality_index=0.5,
            ),
        ],
        ssi_per_risk={"R001": 0.15, "R002": 0.05},
        tornado_sigma_days_per_risk={"R001": 1.0, "R002": 0.25},
        days_at_risk_p80_per_risk={"R001": 5.0, "R002": 2.0},
        counterfactual_days_saved_p80_per_mitigation={},
        methodology_notes=build_methodology_notes(p_band_method="B"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_write_period_json_produces_validated_doc(tmp_path: Path) -> None:
    """Happy path: synthetic inputs produce a valid JSON file matching
    the contract's 11 validation rules."""
    sched = _stub_schedule_result()
    out_path = write_period_json(
        conditional_result=_stub_conditional_result(sched),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="test_StatusPeriod_20260522.xlsx",
        xer_filename="test.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    assert out_path.is_file()
    assert out_path.name == "period_20260522.json"
    with out_path.open("r", encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["schema_version"] == "1.5"  # INTSCURVE-01 Part C: integrated curve points and JCL
    # A LITERAL on purpose, not SCHEMA_VERSION - a version assertion that reads the
    # constant it is checking passes through any bump and gates nothing. 1.3 was
    # PROVCRLF01 ({method, value} digests); 1.4 is C2, ruled 05/09/2026.
    assert set(doc.keys()) == {
        "schema_version", "meta", "headline", "trend",
        "risks", "mitigations", "activities", "distribution",
        "delta", "audit",
    }
    # AM10 (WIND-01 A4): divergence_flag dropped from every risks[] entry.
    for risk in doc["risks"]:
        assert "divergence_flag" not in risk, risk
        # The two CIs it was derived from remain.
        assert "criticality_conditioned" in risk
        assert "criticality_independent" in risk


def test_meta_block_contents(tmp_path: Path) -> None:
    sched = _stub_schedule_result()
    out_path = write_period_json(
        conditional_result=_stub_conditional_result(sched),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx",
        xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=_dt.date(2026, 4, 24),
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    meta = doc["meta"]
    assert meta["period_end_date"] == "2026-05-22"
    assert meta["previous_period_end_date"] == "2026-04-24"
    assert meta["register_version"] == "register"
    assert meta["iterations"] == 1000
    assert meta["seed"] == 42


def test_project_display_name_absent_by_default(tmp_path: Path) -> None:
    """showcase-P5 WS5-C: the field is OPTIONAL. Omitting it keeps the
    pre-P5 (field-less) meta shape so the frozen the engagement artefact and a
    default-args re-run still validate byte-identically."""
    out_path = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx",
        xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    meta = json.loads(out_path.read_text(encoding="utf-8"))["meta"]
    assert "project_display_name" not in meta


def test_project_display_name_emitted_when_provided(tmp_path: Path) -> None:
    """showcase-P5 WS5-C: when resolved (always, from project_binding), the
    project display name lands in meta for the dashboard chrome to read."""
    out_path = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx",
        xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
        project_display_name="Tropic Ridge Wind Farm",
    )
    meta = json.loads(out_path.read_text(encoding="utf-8"))["meta"]
    assert meta["project_display_name"] == "Tropic Ridge Wind Farm"


def test_risks_sorted_by_days_at_risk(tmp_path: Path) -> None:
    out_path = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    risks = doc["risks"]
    assert len(risks) == 2
    assert risks[0]["risk_id"] == "R001"  # 5.0 > 2.0
    assert risks[1]["risk_id"] == "R002"


def test_activities_monotonic_p_bands(tmp_path: Path) -> None:
    out_path = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    for it in doc["activities"]["items"]:
        assert it["p10_finish_days"] <= it["p50_finish_days"] <= it["p90_finish_days"]
        assert it["p10_start_days"] <= it["p50_start_days"] <= it["p90_start_days"]


def test_methodology_note_present_when_method_b(tmp_path: Path) -> None:
    out_path = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
        p_band_method="B",
    )
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert doc["activities"]["p_band_derivation_method"] == "B"
    notes = doc["audit"]["methodology_notes"]
    assert any(
        n["topic"] == "per_activity_p_bands" and n["method"] == "B"
        for n in notes
    )


def test_validation_rejects_non_monotonic_p_band(tmp_path: Path) -> None:
    """Inject an item with P10 > P50; writer must raise on validation."""
    bad_metrics = AMMetrics(
        per_activity_p_bands=[
            ActivityPBand(
                activity_id="bad", name="Bad",
                p10_start_days=20.0, p50_start_days=10.0, p90_start_days=30.0,  # inverted
                p10_finish_days=20.0, p50_finish_days=30.0, p90_finish_days=40.0,
                det_es_days=None, det_ef_days=None,
                criticality_index=0.9,
            ),
        ],
        ssi_per_risk={}, tornado_sigma_days_per_risk={},
        days_at_risk_p80_per_risk={},
        counterfactual_days_saved_p80_per_mitigation={},
        methodology_notes=build_methodology_notes(p_band_method="B"),
    )
    with pytest.raises(JsonWriterError, match="rule 10"):
        write_period_json(
            conditional_result=_stub_conditional_result(_stub_schedule_result()),
            am_metrics=bad_metrics,
            workbook_data=_stub_workbook_data(),
            risk_drivers=_stub_drivers(),
            project_start=_dt.date(2024, 1, 1),
            deterministic_finish_hours=8800.0,
            workbook_filename="wb.xlsx", xer_filename="x.xer",
            output_dir=tmp_path,
            period_end_date=_dt.date(2026, 5, 22),
            previous_period_end_date=None,
            engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
        )


def test_delta_period_0_when_no_prior(tmp_path: Path) -> None:
    """No prior period_*.json in output_dir -> delta carries period_0=true."""
    out_path = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert doc["delta"]["period_0"] is True


def test_delta_computed_from_prior_period(tmp_path: Path) -> None:
    """Write two periods; second period's delta references the first."""
    # First period
    write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result(seed=0)),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb1.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 4, 24),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 1, 14, 0, 0),
    )
    # Second period (one month later)
    out2 = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result(seed=1)),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb2.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=_dt.date(2026, 4, 24),
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    doc = json.loads(out2.read_text(encoding="utf-8"))
    assert "p80_delta_days" in doc["delta"]
    assert "p80_previous" in doc["delta"]
    assert "p80_current" in doc["delta"]


def test_risk_probability_uses_effective_override(tmp_path: Path) -> None:
    """AM08 Part B: risks[].probability reflects the pinned effective value,
    not the register/driver baseline; impact_days_emv follows."""
    base = _stub_conditional_result(_stub_schedule_result())
    overridden = tuple(
        replace(ps, action="probability_overridden", new_probability=0.9)
        if ps.risk_id == "R001" else ps
        for ps in base.pinned_states
    )
    cr = replace(base, pinned_states=overridden)
    out = write_period_json(
        conditional_result=cr,
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),  # R001 driver.probability == 0.3
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    doc = json.loads(out.read_text(encoding="utf-8"))
    r001 = next(r for r in doc["risks"] if r["risk_id"] == "R001")
    assert r001["probability"] == 0.9  # effective, not baseline 0.3
    assert r001["impact_days_emv"] == pytest.approx(4.5)  # 0.9 * ml_pert 5.0


def test_days_at_risk_floored_at_zero(tmp_path: Path) -> None:
    """AM08 Part B: a small negative days_at_risk (precision-floor noise) is
    clamped to 0 on the risk table."""
    metrics = replace(
        _stub_am_metrics(),
        days_at_risk_p80_per_risk={"R001": 5.0, "R002": -0.4},
    )
    out = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=metrics,
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    doc = json.loads(out.read_text(encoding="utf-8"))
    r002 = next(r for r in doc["risks"] if r["risk_id"] == "R002")
    assert r002["days_at_risk_p80"] == 0.0
    assert all(r["days_at_risk_p80"] >= 0.0 for r in doc["risks"])


def test_trend_strip_includes_current(tmp_path: Path) -> None:
    out_path = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    periods = doc["trend"]["periods"]
    assert len(periods) >= 1
    assert periods[-1]["period_end"] == "2026-05-22"


# ---------------------------------------------------------------------------
# AM02.1 §3.A.1 — _is_open_status and open_risks_count consistency
# ---------------------------------------------------------------------------

class TestOpenRisksCountAM02_1:
    """Unfilled status_this_period (None/blank) should count as Open."""

    pytestmark = pytest.mark.unit

    def test_none_status_counts_as_open(self) -> None:
        assert _is_open_status({"status_this_period": None}) is True

    def test_empty_string_status_counts_as_open(self) -> None:
        """Workbook reader sometimes returns "" for blank cells."""
        assert _is_open_status({"status_this_period": ""}) is True

    def test_literal_open_actioned_monitor_all_count(self) -> None:
        """Existing taxonomy preserved."""
        for status in ("Open", "Actioned", "Monitor"):
            assert _is_open_status({"status_this_period": status}) is True

    def test_fired_and_closed_do_not_count_as_open(self) -> None:
        assert _is_open_status({"status_this_period": "Fired"}) is False
        assert _is_open_status({"status_this_period": "Closed"}) is False

    def _make_wb_with_statuses(
        self, statuses: list[str | None]
    ) -> WorkbookData:
        rows = []
        for i, status in enumerate(statuses):
            rows.append({
                "risk_id": f"R{i:03d}",
                "risk_title": f"Risk {i}",
                "status_this_period": status,
                "probability_current": 0.1, "probability_override": None,
                "probability_resolved": 0.1,
                "owner": "Unassigned",
                "mode_current": "Series", "mode_override": None,
                "mode_resolved": "Series",
                "status_changed": None, "fired_date": None,
                "closed_date": None, "notes_this_period": None,
                "helper_data_missing": False,
            })
        return WorkbookData(
            period_info={}, risk_status=rows,
            milestones=[], mitigations=[], am_risk_ids=[],
        )

    def test_headline_8_none_statuses_count_as_8_open(
        self, tmp_path: Path
    ) -> None:
        """The bug: 8 unfilled statuses produced open_risks_count=0.
        Fix: counts to 8."""
        wb = self._make_wb_with_statuses([None] * 8)
        out = write_period_json(
            conditional_result=_stub_conditional_result(_stub_schedule_result()),
            am_metrics=_stub_am_metrics(),
            workbook_data=wb,
            risk_drivers={},  # drivers not needed for headline counts
            project_start=_dt.date(2024, 1, 1),
            deterministic_finish_hours=8800.0,
            workbook_filename="wb.xlsx", xer_filename="x.xer",
            output_dir=tmp_path,
            period_end_date=_dt.date(2026, 5, 22),
            previous_period_end_date=None,
            engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
        )
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["headline"]["open_risks_count"] == 8
        assert doc["headline"]["fired_this_period_count"] == 0
        assert doc["headline"]["closed_this_period_count"] == 0

    def test_headline_mixed_statuses_counted_correctly(
        self, tmp_path: Path
    ) -> None:
        """5 None + 2 Fired + 1 Closed -> open=5, fired=2, closed=1."""
        wb = self._make_wb_with_statuses(
            [None, None, None, None, None, "Fired", "Fired", "Closed"]
        )
        out = write_period_json(
            conditional_result=_stub_conditional_result(_stub_schedule_result()),
            am_metrics=_stub_am_metrics(),
            workbook_data=wb,
            risk_drivers={},
            project_start=_dt.date(2024, 1, 1),
            deterministic_finish_hours=8800.0,
            workbook_filename="wb.xlsx", xer_filename="x.xer",
            output_dir=tmp_path,
            period_end_date=_dt.date(2026, 5, 22),
            previous_period_end_date=None,
            engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
        )
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["headline"]["open_risks_count"] == 5
        assert doc["headline"]["fired_this_period_count"] == 2
        assert doc["headline"]["closed_this_period_count"] == 1

    def test_headline_all_literal_open_preserves_legacy_behaviour(
        self, tmp_path: Path
    ) -> None:
        """A workbook with all 8 risks at literal "Open" still counts to 8."""
        wb = self._make_wb_with_statuses(["Open"] * 8)
        out = write_period_json(
            conditional_result=_stub_conditional_result(_stub_schedule_result()),
            am_metrics=_stub_am_metrics(),
            workbook_data=wb,
            risk_drivers={},
            project_start=_dt.date(2024, 1, 1),
            deterministic_finish_hours=8800.0,
            workbook_filename="wb.xlsx", xer_filename="x.xer",
            output_dir=tmp_path,
            period_end_date=_dt.date(2026, 5, 22),
            previous_period_end_date=None,
            engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
        )
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["headline"]["open_risks_count"] == 8


# ---------------------------------------------------------------------------
# AM02.1 §3.A.2 — stochastic_cp_additions set-difference
# ---------------------------------------------------------------------------

def _stub_schedule_result_with_ci(
    *,
    criticality_index: dict[str, float],
    deterministic_critical_path: tuple[str, ...],
) -> "_StubScheduleMCResult":
    """Synthetic schedule result with caller-controlled CI dict and det CP."""
    act_ids = tuple(criticality_index.keys())
    n = len(act_ids)
    return _StubScheduleMCResult(
        project_finish_hours=np.full(1000, 9000.0, dtype=np.float32),
        project_finish_days=np.full(1000, 1125.0, dtype=np.float32),
        criticality_index=criticality_index,
        activity_ids=act_ids,
        finish_mean_hours=np.full(n, 9000.0, dtype=np.float64),
        finish_std_hours=np.full(n, 10.0, dtype=np.float64),
        total_float_mean_hours=np.zeros(n, dtype=np.float64),
        deterministic_critical_path=deterministic_critical_path,
        n_iter=1000,
        n_act=n,
        seed_used=42,
    )


class TestStochasticCpAdditionsAM02_1:
    """stochastic_cp_additions is a set-difference count (>= 0)."""

    pytestmark = pytest.mark.unit

    def _run_and_extract_count(
        self,
        sched: "_StubScheduleMCResult",
        tmp_path: Path,
    ) -> int:
        out = write_period_json(
            conditional_result=_stub_conditional_result(sched),
            am_metrics=_stub_am_metrics(),
            workbook_data=_stub_workbook_data(),
            risk_drivers=_stub_drivers(),
            project_start=_dt.date(2024, 1, 1),
            deterministic_finish_hours=8800.0,
            workbook_filename="wb.xlsx", xer_filename="x.xer",
            output_dir=tmp_path,
            period_end_date=_dt.date(2026, 5, 22),
            previous_period_end_date=None,
            engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
        )
        doc = json.loads(out.read_text(encoding="utf-8"))
        return doc["activities"]["cp_stats"]["stochastic_cp_additions"]

    def test_high_ci_superset_of_det_cp_two_additions(
        self, tmp_path: Path
    ) -> None:
        """det_cp = {A, B, C}; high_ci = {A, B, C, D, E} -> 2 additions."""
        sched = _stub_schedule_result_with_ci(
            criticality_index={
                "A": 1.0, "B": 1.0, "C": 1.0, "D": 0.85, "E": 0.9,
                "F": 0.4, "G": 0.1,
            },
            deterministic_critical_path=("A", "B", "C"),
        )
        assert self._run_and_extract_count(sched, tmp_path) == 2

    def test_identical_sets_zero_additions(self, tmp_path: Path) -> None:
        """det_cp == high_ci -> 0 additions."""
        sched = _stub_schedule_result_with_ci(
            criticality_index={"A": 1.0, "B": 1.0, "C": 1.0, "D": 0.3},
            deterministic_critical_path=("A", "B", "C"),
        )
        assert self._run_and_extract_count(sched, tmp_path) == 0

    def test_strict_subset_of_det_cp_zero_additions_not_negative(
        self, tmp_path: Path
    ) -> None:
        """high_ci = {A} but det_cp = {A, B, C} -> 0 (no new paths surfaced).

        This is exactly the engagement case: 91 det CP activities, 16
        CI>80 activities, and the old arithmetic-subtraction formula
        gave -75. Set-difference correctly yields 0."""
        sched = _stub_schedule_result_with_ci(
            criticality_index={
                "A": 0.95, "B": 0.4, "C": 0.4, "D": 0.1,
            },
            deterministic_critical_path=("A", "B", "C"),
        )
        result = self._run_and_extract_count(sched, tmp_path)
        assert result == 0
        assert result >= 0  # invariant: never negative

    def test_empty_high_ci_zero_additions(self, tmp_path: Path) -> None:
        """No activity has CI > 0.8 -> 0 additions."""
        sched = _stub_schedule_result_with_ci(
            criticality_index={"A": 0.5, "B": 0.5, "C": 0.5},
            deterministic_critical_path=("A", "B", "C"),
        )
        assert self._run_and_extract_count(sched, tmp_path) == 0


def test_risks_carry_tornado_sample_sigma_days(tmp_path: Path) -> None:
    """AM04 / Doc 3 v2.4: every risks[] row carries
    tornado_sample_sigma_days (number for an evaluated risk, null for a
    risk outside the evaluated set), and the PERT proxy tornado_sigma_days
    is still present alongside it."""
    metrics = replace(
        _stub_am_metrics(),
        # R001 evaluated (number); R002 absent from the dict -> null.
        tornado_sample_sigma_days_per_risk={"R001": 0.42},
    )
    out = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=metrics,
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    doc = json.loads(out.read_text(encoding="utf-8"))
    by_id = {r["risk_id"]: r for r in doc["risks"]}
    assert by_id["R001"]["tornado_sample_sigma_days"] == 0.42
    assert by_id["R002"]["tornado_sample_sigma_days"] is None
    # PERT proxy retained as the documented fallback.
    assert "tornado_sigma_days" in by_id["R001"]
    assert "tornado_sigma_days" in by_id["R002"]


def test_tornado_sample_sigma_nan_serialises_as_null(tmp_path: Path) -> None:
    """A skipped leave-one-out re-run yields NaN; the writer must emit
    null (NaN is not valid JSON)."""
    metrics = replace(
        _stub_am_metrics(),
        tornado_sample_sigma_days_per_risk={"R001": float("nan")},
    )
    out = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=metrics,
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    raw = out.read_text(encoding="utf-8")
    assert "NaN" not in raw
    by_id = {r["risk_id"]: r for r in json.loads(raw)["risks"]}
    assert by_id["R001"]["tornado_sample_sigma_days"] is None


def test_activities_items_no_mode_field_per_v2_3(tmp_path: Path) -> None:
    """AM02.1 §4.B.1: per-activity 'mode' removed (category error).
    Confirms no item in the activities.items[] array carries a
    'mode' key under Doc 3 v2.3."""
    out = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx", xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["activities"]["items"], "expected at least one item"
    for it in doc["activities"]["items"]:
        assert "mode" not in it, (
            f"activity {it['activity_id']} still carries 'mode' field; "
            f"per Doc 3 v2.3 / AM02.1 §4.B.1 the per-activity mode is "
            f"removed as a category error"
        )


# ---------------------------------------------------------------------------
# AM09 - engine provenance stamp (Doc 3 v2.6)
# ---------------------------------------------------------------------------

# A representative provenance stamp as run_period would assemble it. Literal
# here so these writer-level tests do not import the engine-coupled run_period.
_SAMPLE_PROVENANCE = {
    "engine_sha": "5972da0d28907f7f8e86963dfb3df9029daacb02",
    "engine_sha_pinned": "5972da0d28907f7f8e86963dfb3df9029daacb02",
    "engine_sha_matches_pin": True,
    "engine_tree_dirty": False,
    "input_sha256": {
        "register": "a" * 64,
        "xer": "b" * 64,
        "workbook": "c" * 64,
    },
}


def _write_doc(tmp_path: Path, *, engine_provenance=None):
    """Build a period doc from the shared stubs; AM09 tests vary only the
    provenance argument."""
    out_path = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx",
        xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
        engine_provenance=engine_provenance,
    )
    return json.loads(out_path.read_text(encoding="utf-8"))


_AM09_META_KEYS = {
    "engine_sha",
    "engine_tree_dirty",
    "input_sha256",
}  # RS-A2 P-3: engine_sha_pinned / engine_sha_matches_pin dropped (Director 03/09/2026)


def test_meta_carries_engine_provenance_when_supplied(tmp_path: Path) -> None:
    """AM09 3.1-3.3: when run_period supplies the stamp, meta carries the
    engine SHA, its relation to the pin, the dirty flag, and per-file input
    digests keyed register/xer/workbook."""
    doc = _write_doc(tmp_path, engine_provenance=_SAMPLE_PROVENANCE)
    meta = doc["meta"]
    assert _AM09_META_KEYS <= set(meta)
    assert meta["engine_sha"] == _SAMPLE_PROVENANCE["engine_sha"]
    # RS-A2 P-3: pin-field assertion removed - the fields are no longer in the contract
    assert meta["engine_tree_dirty"] is False
    assert set(meta["input_sha256"]) == {"register", "xer", "workbook"}


def test_meta_omits_provenance_for_pre_am09_caller(tmp_path: Path) -> None:
    """AM09 additive-compat: a caller that does not supply the stamp (the
    pre-AM09 shape) produces a valid doc with NONE of the provenance keys, so
    the contract keeping them OPTIONAL holds and a 1.1 artefact still parses."""
    doc = _write_doc(tmp_path, engine_provenance=None)
    meta = doc["meta"]
    assert not (_AM09_META_KEYS & set(meta)), "no provenance keys expected"


def test_whole_json_lock_only_meta_and_schema_version_move(
    tmp_path: Path, monkeypatch
) -> None:
    """AM09 4 lock test (writer level): between a pre-AM09 (1.1, no stamp) doc
    and an AM09 (1.2, stamped) doc built from IDENTICAL inputs, ONLY
    schema_version and the new meta fields differ. headline, trend, risks,
    mitigations, activities, distribution, delta, audit are byte-identical."""
    import src.am.json_writer as jw

    monkeypatch.setattr(jw, "SCHEMA_VERSION", "1.1")
    old = _write_doc(tmp_path / "old", engine_provenance=None)
    monkeypatch.setattr(jw, "SCHEMA_VERSION", "1.2")
    new = _write_doc(tmp_path / "new", engine_provenance=_SAMPLE_PROVENANCE)

    assert old["schema_version"] == "1.1"
    assert new["schema_version"] == "1.2"

    # Every non-meta block is unchanged.
    for block in (
        "headline", "trend", "risks", "mitigations",
        "activities", "distribution", "delta", "audit",
    ):
        assert old[block] == new[block], f"block '{block}' moved under AM09"

    # meta: exactly the AM09 keys are added; everything else is unchanged,
    # save engine_run_hash, a pre-existing per-run uuid4 nonce (not AM09).
    assert set(new["meta"]) - set(old["meta"]) == _AM09_META_KEYS
    for k, v in old["meta"].items():
        if k == "engine_run_hash":
            continue
        assert new["meta"][k] == v, f"meta.{k} moved under AM09"


def test_period_json_written_with_lf_on_every_platform(tmp_path: Path) -> None:
    """JSONEOL-01: the served bytes must not depend on the machine that wrote
    them. json_writer opened the period JSON with no `newline` argument, so
    Python's universal-newline translation emitted os.linesep - CRLF on the
    XPS, LF on the Mac - and the same build produced two different files for
    the same content. Latent only because nothing hashes, tracks or
    byte-diffs these artefacts; PROVCRLF01 removed exactly this dependence
    from the INPUT digests and left it standing on the output."""
    out_path = write_period_json(
        conditional_result=_stub_conditional_result(_stub_schedule_result()),
        am_metrics=_stub_am_metrics(),
        workbook_data=_stub_workbook_data(),
        risk_drivers=_stub_drivers(),
        project_start=_dt.date(2024, 1, 1),
        deterministic_finish_hours=8800.0,
        workbook_filename="wb.xlsx",
        xer_filename="x.xer",
        output_dir=tmp_path,
        period_end_date=_dt.date(2026, 5, 22),
        previous_period_end_date=None,
        engine_run_date=_dt.datetime(2026, 5, 28, 14, 0, 0),
    )
    raw = out_path.read_bytes()

    # Premise guard: indent=2 must actually emit newlines, or the CR
    # assertion below would pass on a file that has no line endings at all.
    assert raw.count(b"\n") > 0, "expected a multi-line document"

    cr = raw.count(b"\r")
    assert cr == 0, (
        f"{cr} CR bytes in the served JSON: the artefact is platform-dependent, "
        "so the same build on the Mac would produce different bytes"
    )
