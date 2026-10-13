"""WINDINJ-01 Stage B: the injection method reaching the kernel is the register's.

Director D-1, 09/09/2026. `build_stage3_rules_from_scope` pinned `additive_pert_days` over
whatever the register declared. These tests hold the three properties that replaced it:

1. the method comes from the row, else the register's ``Default_Injection_Method``;
2. the register's ``Gating_Activity_ID`` is translated from XER task code to internal
   activity id, because the kernel keys on the id and an untranslated code is skipped
   silently (`risk_injection.py:377-383`) - 0.000 delay on every iteration;
3. a row that inherits a discrete default with no gating id REFUSES and names the row.

Property 3 is the one the existing pre-flight does not cover:
``assert_injection_method_consistency`` scopes its blank-gate rule to the method the *row*
declares, so a row declaring nothing passes it. Reading the register's default is what opens
that gap, which is why closing it lives on the same change.

Scopes are constructed here rather than by editing a committed register - a real register
broken to make a test pass is a register somebody later trusts.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.integrated.stage3_config import build_stage3_rules_from_scope
from src.sra._pre_flight import MethodologyValidationError
from src.sra.cpm.calendar import Calendar
from src.sra.cpm.graph import Activity, ScheduleGraph


_CAL = Calendar()


def _graph() -> ScheduleGraph:
    """Two activities whose codes and ids differ, which is the whole point of the test."""
    activities = {
        "2001": Activity(id="2001", code="10.G.001", name="gate one", task_type="TT_Task",
                         original_duration_hours=80.0, total_float_hours=0.0, calendar_id="1"),
        "2002": Activity(id="2002", code="10.A.001", name="worker", task_type="TT_Task",
                         original_duration_hours=80.0, total_float_hours=0.0, calendar_id="1"),
    }
    return ScheduleGraph(activities=activities, links=(), topo_order=("2001", "2002"),
                         project_default_calendar=_CAL)


def _scope(*, injection_method: str = "", gating: str = "10.G.001") -> pd.DataFrame:
    return pd.DataFrame([{
        "risk_id": "T-001", "time_impact": "Yes", "prefix_list": "10.", "pattern_id": "P10",
        "opt_days": 1.0, "ml_days": 2.0, "pess_days": 4.0, "probability": 0.5,
        "mode_aggregated": "Series",
        "injection_method": injection_method, "gating_activity_id": gating,
    }])


class _Binding:
    """The two fields the builder reads off a binding config."""
    float_threshold_hours = 480.0
    default_injection_method = None  # forces the register read; set by tests that pin it


def _binding(default_method: str | None) -> _Binding:
    b = _Binding()
    b.default_injection_method = default_method
    return b


def test_method_comes_from_the_register_default_when_the_row_declares_none():
    rules = build_stage3_rules_from_scope(
        _scope(), _graph(), _binding("discrete_event_additive_days"))
    assert rules["T-001"].injection_method == "discrete_event_additive_days"


def test_a_row_that_declares_a_method_keeps_its_own():
    rules = build_stage3_rules_from_scope(
        _scope(injection_method="additive_pert_days"), _graph(),
        _binding("discrete_event_additive_days"))
    assert rules["T-001"].injection_method == "additive_pert_days"


def test_gating_id_is_translated_from_task_code_to_activity_id():
    """The defect WINDINJ-01's second half was: a code reaches the kernel and is skipped."""
    rules = build_stage3_rules_from_scope(
        _scope(), _graph(), _binding("discrete_event_additive_days"))
    assert rules["T-001"].gating_activity_id == "2001", (
        "the rule carries the XER task code, not the internal activity id; the kernel's "
        "id_to_col lookup misses it and the per-iteration write is skipped silently"
    )


def test_non_discrete_methods_carry_no_gating_id():
    rules = build_stage3_rules_from_scope(
        _scope(injection_method="additive_pert_days"), _graph(),
        _binding("discrete_event_additive_days"))
    assert rules["T-001"].gating_activity_id is None


def test_discrete_default_with_no_gating_id_refuses_and_names_the_row():
    with pytest.raises(MethodologyValidationError, match="T-001"):
        build_stage3_rules_from_scope(
            _scope(gating=""), _graph(), _binding("discrete_event_additive_days"))
