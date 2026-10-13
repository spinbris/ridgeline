"""GENERICINJ-01: the AM period cycle's generic driver route reads the register, not the binding.

Found at GATECOHORT-01 by tracing every caller of ``expand_auto_rules``. For every project but
RefProject the period cycle built its Stage 3 drivers in ``src/am/project_binding.py``'s
``_build_generic_drivers`` with ``injection_method=str(binding.injection_method)`` and no gate.
Both synthetic bindings declared ``additive_pert_days``, while both registers declare
``discrete_event_additive_days`` on their Methodology sheet and every Time=Yes row carries a
gate. So the period cycle broadcast the delay across the cohort for the same project whose
showcase and deliverable wrote it to the gate: one project, two methods, chosen by route.
WINDINJ-01's shape in a fourth place, one WINDINJ-01's grep did not reach because the method
there was a binding attribute, not a pin.

The property: the generic route's drivers are the register route's drivers - same method, same
gate, same cohort - for the committed wind and road fixtures, read as they are.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from src.am.project_binding import build_drivers_for_project
from src.integrated.stage3_config import build_stage3_rules_from_scope
from src.sra.cpm.auto_mapper import expand_auto_rules
from src.integrated.stage3_inputs import Stage3BindingConfig
from src.sra.cpm.graph_builder import build_schedule_graph
from src.sra.cpm.xer_reader import parse_xer
from src.sra.strawman_reader import read_risk_scope

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _both_routes(project: str, monkeypatch):
    monkeypatch.setenv("QRA_PROJECT", f"synthetic_{project}")
    importlib.import_module(f"src.sra.cpm.bindings.synthetic_{project}")
    d = _FIXTURES / f"synthetic_{project}"
    register, xer = d / f"{project}_register.xlsx", d / f"{project}_schedule.xer"
    tables = parse_xer(xer)
    graph = build_schedule_graph(tables)
    cfg = Stage3BindingConfig(register_path=register, xer_path=xer, strawman_path=register,
                              float_threshold_hours=480.0)
    generic = build_drivers_for_project(
        project=f"synthetic_{project}", binding_cfg=cfg, schedule_graph=graph,
        xer_tables=tables, strawman_path=register,
    )
    register_route = expand_auto_rules(
        build_stage3_rules_from_scope(read_risk_scope(register), graph, cfg), graph)
    return generic, register_route


@pytest.mark.parametrize("project", ["wind", "road"])
def test_the_am_route_builds_the_register_route_s_drivers(project, monkeypatch):
    generic, register_route = _both_routes(project, monkeypatch)
    assert set(generic) == set(register_route)
    for rid, g in generic.items():
        r = register_route[rid]
        assert g.injection_method == r.injection_method == "discrete_event_additive_days", (
            f"{rid}: the period cycle injects by {g.injection_method!r} while the deliverable "
            f"injects by {r.injection_method!r} - one project, two methods, chosen by route"
        )
        assert g.gating_activity_id == r.gating_activity_id, rid
        assert g.gating_relation == r.gating_relation, rid
        assert g.affected_activity_ids == r.affected_activity_ids, rid


def test_the_am_route_still_refuses_a_binding_with_no_float_threshold(monkeypatch):
    """ROAD-01 §5.3 stands: the float threshold is the project's own declaration, never
    inherited, and the generic route refuses without one."""
    from src.am.project_binding import _build_generic_drivers

    class _NoThreshold:
        name = "nameless"
        float_threshold_hours = None

    d = _FIXTURES / "synthetic_wind"
    graph = build_schedule_graph(parse_xer(d / "wind_schedule.xer"))
    cfg = Stage3BindingConfig(register_path=d / "wind_register.xlsx", xer_path=d / "wind_schedule.xer",
                              strawman_path=d / "wind_register.xlsx", float_threshold_hours=480.0)
    with pytest.raises(ValueError, match="float_threshold_hours"):
        _build_generic_drivers(strawman_path=d / "wind_register.xlsx", schedule_graph=graph,
                               binding=_NoThreshold(), binding_cfg=cfg)
