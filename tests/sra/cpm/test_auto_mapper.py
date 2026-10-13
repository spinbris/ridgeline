"""Tests for src.sra.cpm.auto_mapper (SR-S3-Beta-04).

Covers:

* Filter A — pattern prefix match (str.startswith semantics).
* Filter B — task_type ∩ float threshold.
* Determinism — sort by (topo_index, code), stable under
  ``graph.activities`` insertion-order permutation.
* Warnings — zero-expansion / below-min / above-max.
* ``expand_auto_rules`` orchestration — preserves input order, retains
  zero-expansion entries.
* Audit-trail parquet round-trip — column list, zero-expansion row
  format.

All tests construct synthetic ScheduleGraphs directly; no RefProject
file references. The reusability invariant per Beta-00.3 is locked
here.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pytest

from src.sra.cpm.auto_mapper import (
    expand_auto_rules,
    expand_single_rule,
    write_audit_trail,
)
from src.sra.cpm.calendar import Calendar
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from src.sra.cpm.risk_driver_schema import (
    AutoMapAuditRow,
    AutoMapperConfig,
    AutoMapperRule,
    RiskDriver,
)

# ---------------------------------------------------------------------------
# Synthetic-graph helpers
# ---------------------------------------------------------------------------

_DEFAULT_CAL = Calendar()


def _make_activity(
    aid: str,
    *,
    code: str | None = None,
    task_type: str = "TT_Task",
    duration_hours: float = 80.0,
    total_float_hours: float | None = 0.0,
) -> Activity:
    return Activity(
        id=aid,
        code=code if code is not None else aid,
        name=aid,
        task_type=task_type,
        original_duration_hours=duration_hours,
        total_float_hours=total_float_hours,
        calendar_id=None,
    )


def _make_graph(
    activities: list[Activity],
    *,
    links: list[Link] | None = None,
    topo_order: list[str] | None = None,
) -> ScheduleGraph:
    acts = {a.id: a for a in activities}
    return ScheduleGraph(
        activities=acts,
        links=links or [],
        topo_order=topo_order if topo_order is not None else [a.id for a in activities],
        project_default_calendar=_DEFAULT_CAL,
    )


def _rule(
    risk_id: str = "R001",
    *,
    pattern_id: str = "P01",
    pattern_prefixes: tuple[str, ...] = ("10.",),
    float_threshold_hours: float = 480.0,
    injection_method: str = "additive_pert_days",
    opt_pert: float = 1.0,
    ml_pert: float = 2.0,
    pess_pert: float = 4.0,
    probability: float = 0.5,
) -> AutoMapperRule:
    return AutoMapperRule(
        risk_id=risk_id,
        pattern_id=pattern_id,
        pattern_prefixes=pattern_prefixes,
        float_threshold_hours=float_threshold_hours,
        injection_method=injection_method,  # type: ignore[arg-type]
        opt_pert=opt_pert,
        ml_pert=ml_pert,
        pess_pert=pess_pert,
        probability=probability,
    )


# ---------------------------------------------------------------------------
# Filter A — pattern prefix
# ---------------------------------------------------------------------------

class TestFilterA:
    """Pattern-prefix matching against Activity.code."""

    def test_single_prefix_matches_one_activity(self) -> None:
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="20.B"),
            _make_activity("a3", code="30.C"),
        ])
        rule = _rule(pattern_prefixes=("10.",))
        rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ("a1",)

    def test_multiple_prefixes_union(self) -> None:
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="20.B"),
            _make_activity("a3", code="30.C"),
        ])
        rule = _rule(pattern_prefixes=("10.", "30."))
        rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ("a1", "a3")

    def test_no_prefix_match_returns_empty(self, caplog: pytest.LogCaptureFixture) -> None:
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="20.B"),
        ])
        rule = _rule(pattern_prefixes=("XX.",))
        with caplog.at_level(logging.WARNING):
            rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ()
        # WARNING raised — sanity check; full warning-text assertion in
        # TestWarnings.
        assert any("ZERO" in r.getMessage() for r in caplog.records)

    def test_prefix_is_strict_startswith(self) -> None:
        """``"10."`` does not match ``"X.10.A"`` — substring would but startswith should not."""
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="X.10.A"),
        ])
        rule = _rule(pattern_prefixes=("10.",))
        rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ("a1",)

    def test_empty_prefix_tuple_returns_empty(self, caplog: pytest.LogCaptureFixture) -> None:
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
        ])
        rule = _rule(pattern_prefixes=())
        with caplog.at_level(logging.WARNING):
            rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ()

    def test_overlapping_prefixes_no_double_count(self) -> None:
        """``("10.", "10.A")`` doesn't add an activity twice."""
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="10.B"),
        ])
        rule = _rule(pattern_prefixes=("10.", "10.A"))
        rd = expand_single_rule(rule, graph)
        # Two activities, no duplicates.
        assert rd.affected_activity_ids == ("a1", "a2")
        assert len(rd.affected_activity_ids) == len(set(rd.affected_activity_ids))


# ---------------------------------------------------------------------------
# Filter B — float threshold
# ---------------------------------------------------------------------------

class TestFloatThreshold:
    """total_float_hours <= rule.float_threshold_hours."""

    def test_below_threshold_passes(self) -> None:
        graph = _make_graph([
            _make_activity("a1", code="10.A", total_float_hours=400.0),
        ])
        rule = _rule(float_threshold_hours=480.0)
        rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ("a1",)

    def test_at_threshold_passes(self) -> None:
        """``<=`` semantics — exactly-at-threshold activity passes."""
        graph = _make_graph([
            _make_activity("a1", code="10.A", total_float_hours=480.0),
        ])
        rule = _rule(float_threshold_hours=480.0)
        rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ("a1",)

    def test_above_threshold_filtered(self) -> None:
        graph = _make_graph([
            _make_activity("a1", code="10.A", total_float_hours=600.0),
        ])
        rule = _rule(float_threshold_hours=480.0)
        rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ()

    def test_total_float_none_filtered(self) -> None:
        """Milestone with float=None excluded — no implicit-zero treatment."""
        graph = _make_graph([
            _make_activity("a1", code="10.A", total_float_hours=None),
        ])
        rule = _rule(float_threshold_hours=480.0)
        rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ()

    def test_custom_threshold_in_rule(self) -> None:
        """rule.float_threshold_hours overrides the config default."""
        graph = _make_graph([
            _make_activity("a1", code="10.A", total_float_hours=300.0),
            _make_activity("a2", code="10.B", total_float_hours=200.0),
        ])
        rule = _rule(float_threshold_hours=240.0)
        rd = expand_single_rule(rule, graph)
        # Only a2 (200 ≤ 240); a1 (300) filtered out.
        assert rd.affected_activity_ids == ("a2",)


# ---------------------------------------------------------------------------
# Filter B — task_type filter
# ---------------------------------------------------------------------------

class TestTaskTypeFilter:
    """task_type == "TT_Task" required when require_task_type_TT_Task=True."""

    def test_TT_Task_passes(self) -> None:
        graph = _make_graph([
            _make_activity("a1", code="10.A", task_type="TT_Task"),
        ])
        rule = _rule()
        rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ("a1",)

    def test_TT_Mile_filtered(self) -> None:
        """Milestones excluded by default."""
        graph = _make_graph([
            _make_activity("a1", code="10.A", task_type="TT_Mile",
                           total_float_hours=0.0, duration_hours=0.0),
        ])
        rule = _rule()
        rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ()

    def test_TT_WBS_filtered(self) -> None:
        """WBS summaries excluded by default."""
        graph = _make_graph([
            _make_activity("a1", code="10.A", task_type="TT_WBS"),
        ])
        rule = _rule()
        rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ()


# ---------------------------------------------------------------------------
# Determinism + warnings
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Sort by (topo_index, code); stable under dict-permutation."""

    def test_expansion_order_topo_then_code(self) -> None:
        """Expansion order matches topo order, not insertion order."""
        # Insertion order: a3, a1, a2; topo order: a1, a2, a3
        acts = [
            _make_activity("a3", code="10.C"),
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="10.B"),
        ]
        graph = _make_graph(acts, topo_order=["a1", "a2", "a3"])
        rule = _rule(pattern_prefixes=("10.",))
        rd = expand_single_rule(rule, graph)
        assert rd.affected_activity_ids == ("a1", "a2", "a3")

    def test_expansion_stable_under_dict_reordering(self) -> None:
        """Same (rules, graph) topology with permuted activity dict →
        identical affected_activity_ids tuple."""
        # Build two graphs — same activities + topo, different insertion order.
        topo = ["a1", "a2", "a3"]
        acts_v1 = [
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="10.B"),
            _make_activity("a3", code="10.C"),
        ]
        acts_v2 = [
            _make_activity("a3", code="10.C"),
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="10.B"),
        ]
        graph_v1 = _make_graph(acts_v1, topo_order=topo)
        graph_v2 = _make_graph(acts_v2, topo_order=topo)
        rule = _rule(pattern_prefixes=("10.",))
        rd1 = expand_single_rule(rule, graph_v1)
        rd2 = expand_single_rule(rule, graph_v2)
        assert rd1.affected_activity_ids == rd2.affected_activity_ids


class TestWarnings:
    """logging.WARNING messages — zero-expansion, below-min, above-max."""

    def test_warning_on_zero_expansion(self, caplog: pytest.LogCaptureFixture) -> None:
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
        ])
        rule = _rule(risk_id="R001", pattern_id="P01", pattern_prefixes=("XX.",))
        with caplog.at_level(logging.WARNING):
            expand_single_rule(rule, graph)
        msgs = [r.getMessage() for r in caplog.records]
        assert any("R001" in m and "P01" in m and "ZERO" in m for m in msgs)

    def test_warning_on_too_few_activities(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Two activities; default below-min threshold is 5.
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="10.B"),
        ])
        rule = _rule(risk_id="R002", pattern_id="P02", pattern_prefixes=("10.",))
        with caplog.at_level(logging.WARNING):
            expand_single_rule(rule, graph)
        msgs = [r.getMessage() for r in caplog.records]
        # Below-min message — not the ZERO message.
        assert any("R002" in m and "2" in m and "ZERO" not in m for m in msgs)

    def test_warning_on_too_many_activities(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 600 activities; default max threshold is 500.
        acts = [
            _make_activity(f"a{i}", code=f"10.{i:03d}")
            for i in range(600)
        ]
        topo = [a.id for a in acts]
        graph = _make_graph(acts, topo_order=topo)
        rule = _rule(risk_id="R003", pattern_id="P03", pattern_prefixes=("10.",))
        with caplog.at_level(logging.WARNING):
            rd = expand_single_rule(rule, graph)
        assert len(rd.affected_activity_ids) == 600
        msgs = [r.getMessage() for r in caplog.records]
        assert any("R003" in m and "600" in m and "500" in m for m in msgs)


# ---------------------------------------------------------------------------
# expand_auto_rules orchestration
# ---------------------------------------------------------------------------

class TestExpandAutoRules:
    """The orchestration wrapper."""

    def test_expand_auto_rules_preserves_input_order(self) -> None:
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="20.B"),
        ])
        rules = {
            "R002": _rule(risk_id="R002", pattern_prefixes=("20.",)),
            "R001": _rule(risk_id="R001", pattern_prefixes=("10.",)),
        }
        out = expand_auto_rules(rules, graph)
        # Python 3.7+ insertion-order guarantee — output mirrors input.
        assert list(out.keys()) == ["R002", "R001"]

    def test_zero_expansion_rule_retained_in_output(self) -> None:
        """A rule with zero expansion still produces an entry."""
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
        ])
        rules = {
            "R001": _rule(risk_id="R001", pattern_prefixes=("XX.",)),
            "R002": _rule(risk_id="R002", pattern_prefixes=("10.",)),
        }
        out = expand_auto_rules(rules, graph)
        assert set(out.keys()) == {"R001", "R002"}
        assert out["R001"].affected_activity_ids == ()
        assert out["R002"].affected_activity_ids == ("a1",)

    def test_multi_rule_independence(self) -> None:
        """Two rules with overlapping matches produce separate entries."""
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="10.B"),
        ])
        rules = {
            "R001": _rule(risk_id="R001", pattern_prefixes=("10.A",)),
            "R002": _rule(risk_id="R002", pattern_prefixes=("10.",)),
        }
        out = expand_auto_rules(rules, graph)
        assert out["R001"].affected_activity_ids == ("a1",)
        assert out["R002"].affected_activity_ids == ("a1", "a2")
        # Drivers carry the source rule's risk_id.
        assert out["R001"].risk_id == "R001"
        assert out["R002"].risk_id == "R002"


# ---------------------------------------------------------------------------
# Audit-trail parquet round-trip
# ---------------------------------------------------------------------------

class TestAuditTrail:
    """write_audit_trail output schema and round-trip."""

    def test_audit_trail_parquet_round_trip(self, tmp_path: Path) -> None:
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
            _make_activity("a2", code="10.B"),
            _make_activity("a3", code="20.C"),
        ])
        rules = {
            "R001": _rule(risk_id="R001", pattern_prefixes=("10.",)),
            "R002": _rule(risk_id="R002", pattern_prefixes=("20.",)),
        }
        drivers = expand_auto_rules(rules, graph)

        out_path = tmp_path / "subdir" / "audit.parquet"
        result_path = write_audit_trail(drivers, out_path)
        assert result_path.exists()

        df = pd.read_parquet(result_path)
        # Row count: one row per (risk_id, activity_id) across all
        # drivers. R001 → 2 rows (a1, a2); R002 → 1 row (a3) → 3 total.
        expected_rows = sum(len(d.affected_activity_ids) for d in drivers.values())
        assert len(df) == expected_rows

        # All R001 rows refer to a1/a2; R002 row refers to a3.
        r001_rows = df[df["risk_id"] == "R001"]
        assert sorted(r001_rows["activity_id"].tolist()) == ["a1", "a2"]
        r002_rows = df[df["risk_id"] == "R002"]
        assert r002_rows["activity_id"].tolist() == ["a3"]

    def test_audit_trail_zero_expansion_row(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Zero-expansion rule writes one row with activity_id=''."""
        graph = _make_graph([
            _make_activity("a1", code="10.A"),
        ])
        rules = {
            "R001": _rule(risk_id="R001", pattern_id="P01", pattern_prefixes=("XX.",)),
        }
        with caplog.at_level(logging.WARNING):
            drivers = expand_auto_rules(rules, graph)

        out_path = tmp_path / "audit.parquet"
        with caplog.at_level(logging.WARNING):
            write_audit_trail(drivers, out_path)

        df = pd.read_parquet(out_path)
        assert len(df) == 1
        assert df.iloc[0]["risk_id"] == "R001"
        assert df.iloc[0]["activity_id"] == ""
        assert df.iloc[0]["pattern_id"] == "P01"

        # write_audit_trail logged a warning about zero-expansion entries.
        msgs = [r.getMessage() for r in caplog.records]
        assert any("zero-expansion" in m.lower() for m in msgs)

    def test_audit_trail_columns_exact(self, tmp_path: Path) -> None:
        """Parquet column list matches AutoMapAuditRow field list exactly."""
        import dataclasses

        graph = _make_graph([
            _make_activity("a1", code="10.A"),
        ])
        rules = {"R001": _rule(risk_id="R001", pattern_prefixes=("10.",))}
        drivers = expand_auto_rules(rules, graph)

        out_path = tmp_path / "audit.parquet"
        write_audit_trail(drivers, out_path)
        df = pd.read_parquet(out_path)

        expected = [f.name for f in dataclasses.fields(AutoMapAuditRow)]
        assert list(df.columns) == expected
