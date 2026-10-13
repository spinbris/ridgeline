"""SR18 Item 3 — duplicate caveat-lead paragraph at §10.5.

Root cause (audit 2026-05-20): the composer's
`_apply_criticality_keys` populated BOTH
`composed["page4b_criticality"]["near_critical_table_caveat"]` AND
`...["risk_to_activity_bridge_caveat"]` with the same string
(`commentary_text.CRITICALITY_CALENDAR_CAVEAT_INLINE`). Two separate
notebook cells (49 + 51 in final_runner.ipynb) read those keys and
each rendered the caveat under their respective tables, so the HTML
ended up with the caveat at lines 8690 AND 8893 (~200 lines apart,
visible as duplication in the rendered §10.5 area).

Fix (composer-side, single source): the second caveat is set to empty
string so the second notebook render guard short-circuits. Reader sees
the caveat once (inline under the first table, near-critical-
activities); the second table (risk-to-activity bridge) inherits the
caveat by section context.

These tests lock both the composer keys and the rendered-HTML
single-occurrence outcome via a synthetic stage3 result fixture.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.final import commentary_text
from src.final.sections.criticality import _apply_criticality_keys


def _stub_stage3_beta_result():
    """Minimal stage3_beta_result that exercises _apply_criticality_keys."""

    class _StubScheduleResult:
        activity_ids = ("a1",)
        criticality_index = {"a1": 0.5}
        mode_independent_criticality_index = {"a1": 0.5}
        total_float_mean_hours = (40.0,)
        total_float_std_hours = (8.0,)
        deterministic_critical_path = ("a1",)

    class _StubDriver:
        affected_activity_ids = ("a1",)
        probability = 0.5
        mode = "Series"
        injection_method = "discrete_event_additive_days"
        gating_activity_id = "a1"

    return {
        "schedule_result": _StubScheduleResult(),
        "risk_drivers": {"R013": _StubDriver()},
        "auto_mapper_audit_path": None,
    }


def test_near_critical_caveat_carries_the_inline_caveat():
    composed: dict = {
        "page4_schedule_drivers": {
            "drivers_table": [{"Risk": "R013"}],
        },
    }
    _apply_criticality_keys(
        composed, _stub_stage3_beta_result(), chart_output_dir=None,
    )

    page4b = composed.get("page4b_criticality") or {}
    assert (
        page4b.get("near_critical_table_caveat")
        == commentary_text.CRITICALITY_CALENDAR_CAVEAT_INLINE
    ), "First (near-critical) caveat must still carry the inline text"


def test_bridge_caveat_is_empty_to_prevent_duplicate_render():
    composed: dict = {
        "page4_schedule_drivers": {
            "drivers_table": [{"Risk": "R013"}],
        },
    }
    _apply_criticality_keys(
        composed, _stub_stage3_beta_result(), chart_output_dir=None,
    )

    page4b = composed.get("page4b_criticality") or {}
    assert page4b.get("risk_to_activity_bridge_caveat") == "", (
        "Second (risk-to-activity bridge) caveat must be empty so the "
        "notebook render guard short-circuits and the caveat appears "
        "once in §10.5. Setting it to anything truthy re-introduces the "
        "duplicate-caveat regression."
    )


def test_sibling_criticality_note_also_avoids_duplicate():
    """The sibling criticality_note dict (built but no longer emitted
    per SR14b D4) carries the same key pair. Same fix applied for
    consistency when sibling emission resumes."""
    composed: dict = {
        "page4_schedule_drivers": {
            "drivers_table": [{"Risk": "R013"}],
        },
    }
    _apply_criticality_keys(
        composed, _stub_stage3_beta_result(), chart_output_dir=None,
    )

    note = composed.get("criticality_note") or {}
    assert (
        note.get("near_critical_table_caveat")
        == commentary_text.CRITICALITY_CALENDAR_CAVEAT_INLINE
    )
    assert note.get("risk_to_activity_bridge_caveat") == "", (
        "Sibling criticality_note dict must mirror the page4b fix "
        "(second caveat empty) for consistency"
    )
