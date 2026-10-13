"""Tests for src.am.conditional_runner.

Two layers:

1. Unit tests for ``_build_pinning_decisions`` against synthetic
   RiskDriver dicts. No engine invocation; fast.
2. Integration test for ``run_conditional_mc`` against the live
   template (template state has no Fired / Closed / completed
   mitigation / completed milestone WBS) at 500 iterations. Confirms
   the orchestrator runs end-to-end and produces a populated
   ScheduleMCResult with the SR10.D fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.input_skips import skip_missing

from src.sra.cpm.risk_driver_schema import RiskDriver

from src.am.conditional_runner import (
    ACTION_CLOSED_PROBABILITY_ZERO,
    ACTION_FIRED_REMOVED,
    ACTION_KEPT_BASELINE,
    ACTION_MITIGATION_COMPLETED_REMOVED,
    ACTION_PROBABILITY_OVERRIDDEN,
    ConditionalRunInputs,
    PinnedRiskState,
    _build_pinning_decisions,
    run_conditional_mc,
)
from src.am.workbook_reader import WorkbookData, read_workbook


AM_REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = AM_REPO_ROOT / "status_periods" / "wind_am_template.xlsx"
REGISTER_V9 = AM_REPO_ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"
XER_PATH = AM_REPO_ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_schedule.xer"
STRAWMAN_PATH = AM_REPO_ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"  # the wind tier is its own strawman


# ---------------------------------------------------------------------------
# Unit-test helpers — synthetic RiskDrivers
# ---------------------------------------------------------------------------

def _make_driver(
    risk_id: str,
    *,
    probability: float = 0.5,
    mode: str = "Series",
    affected: tuple[str, ...] = ("task_a", "task_b"),
    ml_pert: float = 10.0,
) -> RiskDriver:
    return RiskDriver(
        risk_id=risk_id,
        affected_activity_ids=affected,
        injection_method="additive_pert_days",
        opt_pert=5.0,
        ml_pert=ml_pert,
        pess_pert=20.0,
        probability=probability,
        derived_at_run_time=False,
        workshop_validated=True,
        mode=mode,
    )


def _make_workbook_data(
    *,
    risk_status: list[dict] | None = None,
    milestones: list[dict] | None = None,
    mitigations: list[dict] | None = None,
) -> WorkbookData:
    return WorkbookData(
        period_info={},
        risk_status=risk_status or [],
        milestones=milestones or [],
        mitigations=mitigations or [],
        am_risk_ids=[],
    )


# ---------------------------------------------------------------------------
# Unit tests — pinning decision logic
# ---------------------------------------------------------------------------

class TestPinningDecisions:
    pytestmark = pytest.mark.unit

    def test_open_status_no_overrides_keeps_baseline(self) -> None:
        drivers = {"R001": _make_driver("R001", probability=0.3, mode="Hybrid")}
        wb = _make_workbook_data(risk_status=[{
            "risk_id": "R001",
            "status_this_period": "Open",
            "probability_override": None,
            "mode_override": None,
        }])
        new_drivers, states, fired_uplift = _build_pinning_decisions(wb, drivers, {})
        assert set(new_drivers.keys()) == {"R001"}
        assert states[0].action == ACTION_KEPT_BASELINE
        assert states[0].new_probability == 0.3
        assert states[0].new_mode == "Hybrid"
        assert fired_uplift == 0.0

    def test_probability_override_changes_driver(self) -> None:
        drivers = {"R001": _make_driver("R001", probability=0.3, mode="Series")}
        wb = _make_workbook_data(risk_status=[{
            "risk_id": "R001",
            "status_this_period": "Actioned",
            "probability_override": 0.1,
            "mode_override": None,
        }])
        new_drivers, states, _ = _build_pinning_decisions(wb, drivers, {})
        assert new_drivers["R001"].probability == pytest.approx(0.1)
        assert new_drivers["R001"].mode == "Series"  # unchanged
        assert states[0].action == ACTION_PROBABILITY_OVERRIDDEN

    def test_mode_override_alone_ignored_am07(self) -> None:
        """AM07: a Mode_override with no probability override is a complete
        no-op -- the risk keeps its baseline (mode and probability unchanged,
        action kept_baseline)."""
        drivers = {"R001": _make_driver("R001", probability=0.3, mode="Series")}
        wb = _make_workbook_data(risk_status=[{
            "risk_id": "R001",
            "status_this_period": "Monitor",
            "probability_override": None,
            "mode_override": "Hybrid",  # present but ignored
        }])
        new_drivers, states, _ = _build_pinning_decisions(wb, drivers, {})
        assert new_drivers["R001"].probability == pytest.approx(0.3)
        assert new_drivers["R001"].mode == "Series"  # AM07: unchanged
        assert states[0].action == ACTION_KEPT_BASELINE

    def test_mode_override_ignored_am07(self) -> None:
        """AM07: the mode-override lever is retired. A Mode_override on the
        workbook is ignored; the driver's mode is unchanged and only the
        probability override applies."""
        drivers = {"R001": _make_driver("R001", probability=0.3, mode="Series")}
        wb = _make_workbook_data(risk_status=[{
            "risk_id": "R001",
            "status_this_period": "Actioned",
            "probability_override": 0.05,
            "mode_override": "Parallel",  # present but ignored
        }])
        new_drivers, states, _ = _build_pinning_decisions(wb, drivers, {})
        assert new_drivers["R001"].probability == pytest.approx(0.05)
        assert new_drivers["R001"].mode == "Series"  # AM07: unchanged
        assert states[0].action == ACTION_PROBABILITY_OVERRIDDEN
        assert states[0].new_mode == "Series"  # record-only, baseline

    def test_closed_forces_probability_zero(self) -> None:
        drivers = {"R001": _make_driver("R001", probability=0.3)}
        wb = _make_workbook_data(risk_status=[{
            "risk_id": "R001",
            "status_this_period": "Closed",
            "probability_override": None,
            "mode_override": None,
        }])
        new_drivers, states, _ = _build_pinning_decisions(wb, drivers, {})
        assert "R001" in new_drivers  # kept (so severity-uniform projection works)
        assert new_drivers["R001"].probability == 0.0
        assert states[0].action == ACTION_CLOSED_PROBABILITY_ZERO

    def test_fired_removes_driver_and_uplifts_baseline(self) -> None:
        drivers = {"R001": _make_driver("R001", probability=0.3, ml_pert=12.0)}
        wb = _make_workbook_data(risk_status=[{
            "risk_id": "R001",
            "status_this_period": "Fired",
            "probability_override": None,
            "mode_override": None,
        }])
        new_drivers, states, fired_uplift = _build_pinning_decisions(wb, drivers, {})
        assert "R001" not in new_drivers
        assert states[0].action == ACTION_FIRED_REMOVED
        assert states[0].realised_impact_days == pytest.approx(12.0)
        assert fired_uplift == pytest.approx(12.0)

    def test_completed_mitigation_removes_linked_risk(self) -> None:
        drivers = {"R001": _make_driver("R001", probability=0.3)}
        wb = _make_workbook_data(
            risk_status=[{
                "risk_id": "R001",
                "status_this_period": "Open",
                "probability_override": None,
                "mode_override": None,
            }],
            mitigations=[{
                "mitigation_id": "M001",
                "risk_id": "R001",
                "status": "Completed",
            }],
        )
        new_drivers, states, _ = _build_pinning_decisions(wb, drivers, {})
        assert "R001" not in new_drivers
        assert states[0].action == ACTION_MITIGATION_COMPLETED_REMOVED

    def test_risk_not_in_workbook_kept_with_baseline(self) -> None:
        """A risk present on the engine but absent from AM_Period_Status
        is kept at its baseline (no override applied)."""
        drivers = {"R999": _make_driver("R999", probability=0.5)}
        wb = _make_workbook_data(risk_status=[])
        new_drivers, states, _ = _build_pinning_decisions(wb, drivers, {})
        assert "R999" in new_drivers
        assert new_drivers["R999"].probability == pytest.approx(0.5)
        assert states[0].action == ACTION_KEPT_BASELINE

    def test_multiple_fired_uplift_sums(self) -> None:
        drivers = {
            "R001": _make_driver("R001", ml_pert=12.0),
            "R002": _make_driver("R002", ml_pert=8.0),
            "R003": _make_driver("R003", ml_pert=5.0),
        }
        wb = _make_workbook_data(risk_status=[
            {"risk_id": "R001", "status_this_period": "Fired",
             "probability_override": None, "mode_override": None},
            {"risk_id": "R002", "status_this_period": "Fired",
             "probability_override": None, "mode_override": None},
            {"risk_id": "R003", "status_this_period": "Open",
             "probability_override": None, "mode_override": None},
        ])
        new_drivers, _, fired_uplift = _build_pinning_decisions(wb, drivers, {})
        assert set(new_drivers.keys()) == {"R003"}
        assert fired_uplift == pytest.approx(12.0 + 8.0)


# ---------------------------------------------------------------------------
# Integration tests — full conditional run against the live template
# ---------------------------------------------------------------------------

class TestConditionalRunIntegration:
    pytestmark = pytest.mark.integration

    @pytest.fixture(scope="class")
    def template_workbook(self) -> WorkbookData:
        if not TEMPLATE_PATH.is_file():
            skip_missing(TEMPLATE_PATH)
        return read_workbook(TEMPLATE_PATH)

    @pytest.fixture(scope="class")
    def conditional_result(self, template_workbook: WorkbookData):
        for name, p in (
            ("register", REGISTER_V9), ("xer", XER_PATH), ("strawman", STRAWMAN_PATH),
        ):
            if not p.is_file():
                skip_missing(p, label=name)
        inputs = ConditionalRunInputs(
            workbook_data=template_workbook,
            register_path=REGISTER_V9,
            xer_path=XER_PATH,
            strawman_path=STRAWMAN_PATH,
            n_iter=500,
            seed=42,
            criticality_measurement_mode="both",
        )
        return run_conditional_mc(inputs)

    def test_conditional_run_returns_populated_result(self, conditional_result) -> None:
        r = conditional_result.schedule_result
        assert r.n_iter == 500
        assert r.n_act > 0
        assert r.n_risks > 0

    def test_template_state_period_0_equals_baseline_keep_all(
        self, conditional_result, template_workbook
    ) -> None:
        """Template state: no Fired, no Closed, no completed mitigations,
        no milestone WBS codes -> every driver pinned 'kept_baseline'.

        This is the §4 Phase 2.C item 6 'Edge case handling' AC:
        period 0 conditional output equals baseline.
        """
        assert conditional_result.fired_baseline_uplift_days == 0.0
        assert conditional_result.excluded_risk_ids == ()
        actions = {s.action for s in conditional_result.pinned_states}
        # Every action should be kept_baseline (no overrides filled in
        # in the template; all owners blank doesn't trigger any branch).
        assert actions == {ACTION_KEPT_BASELINE}, (
            f"Expected all actions to be {ACTION_KEPT_BASELINE!r}; "
            f"got actions={actions}"
        )

    def test_sr10d_fields_populated(self, conditional_result) -> None:
        r = conditional_result.schedule_result
        assert r.finish_mean_hours.shape == (r.n_act,)
        assert r.finish_std_hours.shape == (r.n_act,)
        assert float(r.finish_std_hours.max()) > 0.0

    def test_config_summary_carries_pinning_audit(self, conditional_result) -> None:
        cs = conditional_result.config_summary
        assert cs["n_iter"] == 500
        assert cs["seed"] == 42
        assert cs["criticality_measurement_mode"] == "both"
        assert cs["n_drivers_input"] == cs["n_drivers_after_pinning"]
        assert cs["n_excluded"] == 0
        assert cs["fired_baseline_uplift_days"] == 0.0
