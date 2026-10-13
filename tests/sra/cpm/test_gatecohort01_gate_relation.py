"""GATECOHORT-01: a declared gate belongs to its risk's cohort, and a check says so.

Director D-1, 10/09/2026, P-belongs: a ``Gating_Activity_ID`` is a member of its rule's
cohort, an ancestor of it, or a descendant of it. Anything else is refused before an iteration
runs, naming the risk, the gate, the prefix and the relation found. The relation is carried on
the driver and the audit trail.

Why: since WINDINJ-01 the gate is the sole driver of the Stage 3 schedule headline, and the
only checks on it were non-blank and resolves-to-some-task-code (`_pre_flight.py:191-207`).
A gate naming a real but unrelated activity passed everything and moved a client number
silently. Measured 10/09 on the committed fixtures: five of wind's ten gates sit outside their
cohort and every one is connected to it (three downstream, two upstream); road's ten are all
members. Those measurements are the positive controls at the end of this file.

Graphs here are built through the real builder from tiny TASK/TASKPRED tables, so precedence
is wired the way production wires it, and no committed register is edited to make a test pass.
"""
from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest

from src.integrated.stage3_config import build_stage3_rules_from_scope
from src.sra._pre_flight import MethodologyValidationError
from src.sra.cpm.auto_mapper import (
    _audit_rows_for_driver,
    expand_auto_rules,
    expand_single_rule,
    gate_relation,
)
from src.sra.cpm.graph_builder import DuplicateTaskCodeError, build_schedule_graph
from src.sra.cpm.risk_driver_schema import AutoMapperRule
from src.sra.cpm.xer_reader import parse_xer
from src.sra.strawman_reader import read_risk_scope
from tests.sra.cpm.test_graph_builder import (  # the builders the graph tests already use
    _calendar_table,
    _task_table,
    _taskpred_table,
)

# ---------------------------------------------------------------------------
# One graph, four shapes of gate
#
#   1 P.001  ->  2 A.001  ->  3 A.002  ->  4 G.001        5 X.001 (no links)
#   upstream     cohort "A" (members)      downstream      unrelated
# ---------------------------------------------------------------------------

_CODES = {1: "P.001", 2: "A.001", 3: "A.002", 4: "G.001", 5: "X.001"}


def _tables(codes: dict[int, str] | None = None) -> dict[str, pd.DataFrame]:
    codes = codes or _CODES
    tasks = [
        {"task_id": i, "task_code": c, "task_name": c, "clndr_id": 1000,
         "total_float_hr_cnt": np.float32(0.0)}
        for i, c in codes.items()
    ]
    preds = [
        {"task_pred_id": k, "task_id": succ, "pred_task_id": pred}
        for k, (pred, succ) in enumerate([(1, 2), (2, 3), (3, 4)], start=1)
        if pred in codes and succ in codes
    ]
    return {"TASK": _task_table(tasks), "TASKPRED": _taskpred_table(preds),
            "CALENDAR": _calendar_table()}


def _graph():
    return build_schedule_graph(_tables())


def _rule(gate_id: str | None, *, method: str = "discrete_event_additive_days",
          prefix: str = "A") -> AutoMapperRule:
    return AutoMapperRule(
        risk_id="T-001", pattern_id="P-A", pattern_prefixes=(prefix,),
        float_threshold_hours=480.0, injection_method=method,  # type: ignore[arg-type]
        opt_pert=1.0, ml_pert=2.0, pess_pert=4.0, probability=0.5,
        gating_activity_id=gate_id,
    )


_COHORT = ("2", "3")


@pytest.mark.parametrize("gate_id, expected", [
    ("3", "member"), ("1", "upstream"), ("4", "downstream"), ("5", "unrelated"),
])
def test_gate_relation_names_each_shape(gate_id, expected):
    assert gate_relation(gate_id, _COHORT, _graph()) == expected


# ---------------------------------------------------------------------------
# P-1: refuse the unrelated gate, name everything; accept the three related shapes
# and carry the label onto the driver and the audit trail
# ---------------------------------------------------------------------------

def test_an_unrelated_gate_is_refused_and_named():
    with pytest.raises(MethodologyValidationError) as exc:
        expand_single_rule(_rule("5"), _graph())
    msg = str(exc.value)
    for token in ("T-001", "X.001", "A", "unrelated"):
        assert token in msg, f"refusal does not name {token!r}: {msg}"


@pytest.mark.parametrize("gate_id, label", [("3", "member"), ("1", "upstream"), ("4", "downstream")])
def test_a_related_gate_passes_and_the_label_travels(gate_id, label):
    driver = expand_single_rule(_rule(gate_id), _graph())
    assert driver.gating_activity_id == gate_id
    assert driver.gating_relation == label
    rows = _audit_rows_for_driver(driver)
    assert rows and all(r.gating_relation == label for r in rows)


def test_a_broadcast_rule_carries_no_relation():
    driver = expand_single_rule(_rule(None, method="additive_pert_days"), _graph())
    assert driver.gating_relation is None


def test_a_discrete_gate_over_an_empty_cohort_is_refused():
    """Director, 10/09/2026, on the review's BLOCKER: refuse the empty cohort on every route.

    A discrete rule whose prefix matches nothing used to expand to a driver with no cohort and a
    gate. `risk_injection.py:301` skips any empty-cohort driver before the discrete write, so the
    risk's whole delay vanished and the run completed green. On the binding route D-2 had just
    removed the only refusal that caught it (the SR16 auto-pick's), because a declared gate
    means no auto-pick; on the register route there never was one. One refusal, at the seam.
    """
    with pytest.raises(MethodologyValidationError) as exc:
        expand_single_rule(_rule("4", prefix="ZZZ"), _graph())
    msg = str(exc.value)
    for token in ("T-001", "G.001", "ZZZ", "no activity"):
        assert token in msg, f"refusal does not name {token!r}: {msg}"


def test_a_broadcast_rule_over_an_empty_cohort_still_only_warns():
    """The zero-expansion path for a broadcast rule is unchanged: retained in the audit with an
    empty activity_id, no delta, no refusal."""
    driver = expand_single_rule(_rule(None, method="additive_pert_days", prefix="ZZZ"), _graph())
    assert driver.affected_activity_ids == ()
    assert driver.gating_relation is None


# ---------------------------------------------------------------------------
# P-2: every route. The register route (wind, road, the deliverable, both showcase
# scripts) and the binding route (RefProject).
# ---------------------------------------------------------------------------

def _scope(gate_code: str, *, method: str = "") -> pd.DataFrame:
    return pd.DataFrame([{
        "risk_id": "T-001", "time_impact": "Yes", "prefix_list": "A.", "pattern_id": "P-A",
        "opt_days": 1.0, "ml_days": 2.0, "pess_days": 4.0, "probability": 0.5,
        "mode_aggregated": "Series", "injection_method": method, "gating_activity_id": gate_code,
    }])


class _Binding:
    float_threshold_hours = 480.0
    default_injection_method = "discrete_event_additive_days"


def test_register_route_refuses_an_unrelated_gate():
    graph = _graph()
    rules = build_stage3_rules_from_scope(_scope("X.001"), graph, _Binding())
    with pytest.raises(MethodologyValidationError, match="unrelated"):
        expand_auto_rules(rules, graph)


def test_register_route_passes_a_downstream_gate():
    graph = _graph()
    drivers = expand_auto_rules(build_stage3_rules_from_scope(_scope("G.001"), graph, _Binding()), graph)
    assert drivers["T-001"].gating_relation == "downstream"


# REFRETIRE-01 (D-3): the binding route's half of this file went with the pattern-catalogue
# assembler it exercised. Every project now takes the register route below, so the pairs that
# checked the two routes agreed have nothing left to disagree about.


def test_register_route_refuses_a_gate_over_an_empty_cohort():
    graph = _graph()
    scope = _scope("G.001")
    scope.loc[0, "prefix_list"] = "ZZZ."
    with pytest.raises(MethodologyValidationError, match="no activity"):
        expand_auto_rules(build_stage3_rules_from_scope(scope, graph, _Binding()), graph)


def test_a_declared_gate_is_read_under_an_inherited_method():
    """P-3: a blank-method row with a declared gate reads that gate, once the resolved method
    is discrete. The retired binding route ignored it and auto-picked from the cohort instead
    - same row, two activities, chosen by route."""
    graph = _graph()
    rules = build_stage3_rules_from_scope(_scope("G.001", method=""), graph, _Binding())
    assert rules["T-001"].injection_method == "discrete_event_additive_days"
    assert rules["T-001"].gating_activity_id == "4"


# ---------------------------------------------------------------------------
# P-5: a TASK table with two rows sharing a task_code is refused at graph build.
# Both code_to_id builders are dict comprehensions where the last duplicate wins,
# so a duplicated code makes every later code lookup ambiguous, the gate's included.
# ---------------------------------------------------------------------------

def test_duplicate_task_codes_refuse_at_graph_build():
    tables = _tables({**_CODES, 5: "A.001"})     # 5 now shares A.001 with 2
    with pytest.raises(DuplicateTaskCodeError, match="A.001"):
        build_schedule_graph(tables)


def test_unique_task_codes_build():
    assert len(build_schedule_graph(_tables()).activities) == 5


# ---------------------------------------------------------------------------
# P-4 positive controls: the committed registers, unchanged, pass with the labels
# measured on 10/09. A register broken to make a test pass is a register someone later
# trusts, so these read the fixtures as they are.
# ---------------------------------------------------------------------------

_WIND = {"WT-001": "downstream", "WT-002": "member", "WT-008": "upstream", "WT-009": "member",
         "WT-020": "downstream", "WT-021": "member", "WT-026": "member", "WT-027": "member",
         "WT-031": "upstream", "WT-032": "downstream"}


def _fixture_drivers(project: str, monkeypatch):
    monkeypatch.setenv("QRA_PROJECT", f"synthetic_{project}")
    importlib.import_module(f"src.sra.cpm.bindings.synthetic_{project}")
    d = f"tests/fixtures/synthetic_{project}"
    graph = build_schedule_graph(parse_xer(f"{d}/{project}_schedule.xer"))
    scope = read_risk_scope(f"{d}/{project}_register.xlsx")
    return expand_auto_rules(build_stage3_rules_from_scope(scope, graph, _Binding()), graph)


def test_wind_register_passes_with_the_measured_relations(monkeypatch):
    drivers = _fixture_drivers("wind", monkeypatch)
    assert {rid: d.gating_relation for rid, d in drivers.items()} == _WIND


def test_road_register_passes_all_members(monkeypatch):
    drivers = _fixture_drivers("road", monkeypatch)
    assert len(drivers) == 10
    assert {d.gating_relation for d in drivers.values()} == {"member"}
