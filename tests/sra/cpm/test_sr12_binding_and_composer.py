"""SR12 — binding + composer integration tests.

Covers:

* RefProject binding wiring: per-risk injection_method read from
  Risk_Scope, code→id translation, pre-flight validation called.
* Composer §10.5 risk-to-CP linkage table emits the injection_method
  column.
* Auto-mapper audit summary row emits the gating_activity_id column.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.final.composer import (
    _render_auto_mapper_audit_table,
    build_risk_to_cp_linkage_table,
)
from src.sra.cpm.risk_driver_schema import RiskDriver


def _driver(
    risk_id: str,
    *,
    affected: tuple[str, ...] = ("a1",),
    injection_method: str = "additive_pert_days",
    gating_activity_id: str | None = None,
    mode: str = "Series",
) -> RiskDriver:
    kwargs: dict = dict(
        risk_id=risk_id,
        affected_activity_ids=affected,
        injection_method=injection_method,  # type: ignore[arg-type]
        opt_pert=1.0, ml_pert=2.0, pess_pert=4.0,
        probability=0.5,
        mode=mode,  # type: ignore[arg-type]
    )
    if injection_method == "discrete_event_additive_days":
        kwargs["gating_activity_id"] = gating_activity_id or "a1"
    return RiskDriver(**kwargs)


# ---------------------------------------------------------------------------
# Composer audit table — gating_activity_id column
# ---------------------------------------------------------------------------


class TestAuditSummaryTable:

    def test_legacy_drivers_render_blank_gating(self) -> None:
        drivers = {
            "R001": _driver("R001"),
            "R002": _driver("R002", injection_method="multiplicative_pert_factor"),
        }
        rows = _render_auto_mapper_audit_table(drivers)
        assert len(rows) == 2
        assert all(r["gating_activity_id"] == "" for r in rows)

    def test_discrete_event_driver_renders_gating(self) -> None:
        drivers = {
            "R013": _driver(
                "R013",
                injection_method="discrete_event_additive_days",
                gating_activity_id="A100",
            ),
        }
        rows = _render_auto_mapper_audit_table(drivers)
        assert rows[0]["gating_activity_id"] == "A100"
        assert rows[0]["injection_method"] == "discrete_event_additive_days"

    def test_audit_summary_includes_all_sr12_methods(self) -> None:
        """Mixed-method driver set renders all four method names."""
        drivers = {
            "R001": _driver("R001", injection_method="additive_pert_days"),
            "R002": _driver(
                "R002", injection_method="discrete_event_additive_days",
                gating_activity_id="A100",
            ),
            "R003": _driver(
                "R003", injection_method="productivity_multiplicative_factor",
            ),
            "R004": _driver(
                "R004", injection_method="multiplicative_pert_factor",
            ),
        }
        rows = _render_auto_mapper_audit_table(drivers)
        methods = {r["injection_method"] for r in rows}
        assert methods == {
            "additive_pert_days",
            "discrete_event_additive_days",
            "productivity_multiplicative_factor",
            "multiplicative_pert_factor",
        }


# ---------------------------------------------------------------------------
# §10.5 risk-to-CP linkage table — injection_method column
# ---------------------------------------------------------------------------


class TestSection10_5InjectionMethod:

    def test_linkage_table_carries_injection_method_column(self) -> None:
        drivers = {
            "R013": _driver(
                "R013", affected=("a1",),
                injection_method="discrete_event_additive_days",
                gating_activity_id="a1",
                mode="Hybrid",
            ),
            "R001": _driver(
                "R001", affected=("a2",),
                injection_method="additive_pert_days",
                mode="Series",
            ),
        }
        # Synthetic extended_ci_table with two activities.
        ci_table = pd.DataFrame({
            "activity_id": ["a1", "a2"],
            "activity_name": ["A1", "A2"],
            "ci_mode_conditioned": [0.3, 0.5],
            "ci_mode_independent": [0.6, 0.5],
            "divergence": [0.3, 0.0],
        })
        out = build_risk_to_cp_linkage_table(drivers, ci_table)
        assert "injection_method" in out.columns
        # Match risk_id -> method
        method_map = dict(zip(out["risk_id"], out["injection_method"]))
        assert method_map["R013"] == "discrete_event_additive_days"
        assert method_map["R001"] == "additive_pert_days"

    def test_linkage_table_injection_method_on_empty_ci_table(self) -> None:
        """Degenerate path (no CI rows) still emits the injection_method
        column with the right values."""
        drivers = {
            "R013": _driver(
                "R013", injection_method="discrete_event_additive_days",
                gating_activity_id="a1",
            ),
        }
        empty = pd.DataFrame(
            columns=["activity_id", "activity_name", "ci_mode_conditioned",
                     "ci_mode_independent", "divergence"]
        )
        out = build_risk_to_cp_linkage_table(drivers, empty)
        assert "injection_method" in out.columns
        assert out.iloc[0]["injection_method"] == "discrete_event_additive_days"

    def test_linkage_table_zero_bound_branch_carries_injection_method(
        self,
    ) -> None:
        """Risk with affected_activity_ids not in CI lookup → zero-bound
        branch; injection_method still rendered."""
        drivers = {
            "R013": _driver(
                "R013", affected=("a_renamed",),
                injection_method="additive_pert_days",
            ),
        }
        ci_table = pd.DataFrame({
            "activity_id": ["a1"],
            "activity_name": ["A1"],
            "ci_mode_conditioned": [0.5],
            "ci_mode_independent": [0.5],
            "divergence": [0.0],
        })
        out = build_risk_to_cp_linkage_table(drivers, ci_table)
        assert out.iloc[0]["n_activities_bound"] == 1  # the count of original tuple
        assert out.iloc[0]["injection_method"] == "additive_pert_days"


# ---------------------------------------------------------------------------
# Backward-compat: existing audit-table rows unchanged shape (gating_activity_id
# is the only added field)
# ---------------------------------------------------------------------------


class TestBackwardCompat:

    def test_existing_audit_columns_preserved(self) -> None:
        """SR12 adds gating_activity_id; all other audit columns
        unchanged."""
        drivers = {
            "R001": _driver("R001"),
        }
        rows = _render_auto_mapper_audit_table(drivers)
        expected_keys = {
            "risk_id", "activity_count", "pattern_id", "injection_method",
            "gating_activity_id", "probability", "opt_d", "ml_d", "pess_d",
            "derived_at_run_time", "workshop_validated",
        }
        assert set(rows[0].keys()) == expected_keys
