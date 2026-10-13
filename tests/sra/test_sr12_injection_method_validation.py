"""SR12 — pre-flight validation tests for injection-method dispatch.

Covers Acceptance Criteria 2, 3, 7 from the SR12 brief:

* AC2 — strawman reader exposes the three new Risk_Scope columns.
* AC3 — pre-flight validation raises on missing/invalid gating
  activity for discrete-event risks (Director Decision 3 = Option A).
* AC7 — audit trail emits injection_method per risk (covered alongside
  in test_audit_trail_injection_method.py).
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.sra._pre_flight import (
    MethodologyValidationError,
    assert_injection_method_consistency,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _scope_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal Risk_Scope-shaped DataFrame for the validator."""
    base = {
        "risk_id": None,
        "injection_method": None,
        "gating_activity_id": None,
        "injection_method_notes": None,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


# ---------------------------------------------------------------------------
# AC3 — strict pre-flight validation
# ---------------------------------------------------------------------------


class TestPreflightDiscreteEventValidation:

    def test_legacy_null_rows_pass(self) -> None:
        """Decision 1=A: injection_method null → fallback, no validation
        error."""
        df = _scope_df([
            {"risk_id": "R001"},
            {"risk_id": "R002", "injection_method": ""},
        ])
        # Should not raise.
        assert_injection_method_consistency(df, xer_task_codes=set())

    def test_discrete_event_with_valid_gating_passes(self) -> None:
        df = _scope_df([
            {
                "risk_id": "R013",
                "injection_method": "discrete_event_additive_days",
                "gating_activity_id": "A100",
            },
        ])
        assert_injection_method_consistency(df, {"A100", "A200"})

    def test_discrete_event_missing_gating_raises(self) -> None:
        df = _scope_df([
            {
                "risk_id": "R013",
                "injection_method": "discrete_event_additive_days",
                "gating_activity_id": "",
            },
        ])
        with pytest.raises(
            MethodologyValidationError, match="gating_activity_id"
        ):
            assert_injection_method_consistency(df, {"A100"})

    def test_discrete_event_stale_gating_raises(self) -> None:
        df = _scope_df([
            {
                "risk_id": "R013",
                "injection_method": "discrete_event_additive_days",
                "gating_activity_id": "A_renamed",
            },
        ])
        with pytest.raises(
            MethodologyValidationError, match="not present"
        ):
            assert_injection_method_consistency(df, {"A100", "A200"})

    def test_unknown_injection_method_raises(self) -> None:
        df = _scope_df([
            {
                "risk_id": "R013",
                "injection_method": "calendar_filtered_multiplicative",
                "gating_activity_id": "",
            },
        ])
        with pytest.raises(
            MethodologyValidationError, match="unknown injection_method"
        ):
            assert_injection_method_consistency(df, {"A100"})

    def test_productivity_method_does_not_require_gating(self) -> None:
        df = _scope_df([
            {
                "risk_id": "R017.1",
                "injection_method": "productivity_multiplicative_factor",
                "gating_activity_id": "",
            },
        ])
        # Should not raise — gating is only required for discrete-event.
        assert_injection_method_consistency(df, set())

    def test_multiplicative_pert_factor_accepted(self) -> None:
        df = _scope_df([
            {
                "risk_id": "R001",
                "injection_method": "multiplicative_pert_factor",
            },
        ])
        assert_injection_method_consistency(df, set())

    def test_additive_pert_days_accepted(self) -> None:
        df = _scope_df([
            {
                "risk_id": "R001",
                "injection_method": "additive_pert_days",
            },
        ])
        assert_injection_method_consistency(df, set())

    def test_legacy_strawman_without_columns_passes(self) -> None:
        """A strawman whose Risk_Scope predates SR12 (no injection_method
        column at all) skips validation entirely — the binding falls
        back to default_injection_method."""
        df = pd.DataFrame([{"risk_id": "R001", "probability_time": 0.6}])
        assert "injection_method" not in df.columns
        assert_injection_method_consistency(df, set())

    def test_blank_method_with_gating_id_set_does_not_raise(self) -> None:
        """SRA-02 S-F / D-18, limb 1: a gate that RESOLVES passes under any
        method, blank included.

        The pre-S-F docstring said the validator "does not complain" because
        "the engine ignores it for non-discrete methods". D-7 withdrew that
        rationale — GATINGINERT-01 is exactly the state it described — but not
        this assertion: presence validation fires on non-resolution, not on
        presence, so a resolving gate under a blank method is still fine.
        """
        df = _scope_df([
            {
                "risk_id": "R001",
                "injection_method": "",
                "gating_activity_id": "A100",
            },
        ])
        assert_injection_method_consistency(df, {"A100"})

    @pytest.mark.parametrize(
        "method",
        [
            "",
            "additive_pert_days",
            "multiplicative_pert_factor",
            "discrete_event_additive_days",
            "productivity_multiplicative_factor",
        ],
    )
    def test_non_resolving_gate_raises_under_every_method(
        self, method: str
    ) -> None:
        """D-18, limb 2: a gate that does NOT resolve raises under any method.

        The GATINGINERT-01 shape. Before S-F this passed silently: the
        validator reached ``continue`` at the method gate and never looked at
        the value, so a register could carry a made-up activity id on every
        mapped risk and stay green.

        Parametrised across all five method values (S-F WARN-1): D-7's clause
        is "under any method", so a limb re-narrowed to the subset a test
        happens to name must red. ``additive_pert_days`` is not hypothetical —
        it is what ``scripts/run_wind_showcase.py`` hard-codes onto every wind
        ``AutoMapperRule``.
        """
        df = _scope_df([
            {
                "risk_id": "R001",
                "injection_method": method,
                "gating_activity_id": "TOTALLY-MADE-UP",
            },
        ])
        with pytest.raises(MethodologyValidationError) as excinfo:
            assert_injection_method_consistency(df, {"A100"})
        message = str(excinfo.value)
        assert "R001" in message, message
        assert "TOTALLY-MADE-UP" in message, message

    def test_blank_gating_id_is_an_error_only_under_discrete_event(self) -> None:
        """D-18, limb 3: the method-scoped limb is kept unchanged (P-F1)."""
        blank_gate = {"risk_id": "R001", "gating_activity_id": ""}
        # Blank gate, non-discrete method: not an error.
        assert_injection_method_consistency(
            _scope_df([{**blank_gate, "injection_method": "additive_pert_days"}]),
            {"A100"},
        )
        # Blank gate, discrete-event method: still an error.
        with pytest.raises(
            MethodologyValidationError, match="gating_activity_id"
        ):
            assert_injection_method_consistency(
                _scope_df([
                    {**blank_gate,
                     "injection_method": "discrete_event_additive_days"},
                ]),
                {"A100"},
            )

    def test_validator_iterates_all_rows(self) -> None:
        """Mixed-method DataFrame: legitimate first row should not mask a
        violation in a later row."""
        df = _scope_df([
            {
                "risk_id": "R013",
                "injection_method": "discrete_event_additive_days",
                "gating_activity_id": "A100",
            },
            {
                "risk_id": "R014",
                "injection_method": "discrete_event_additive_days",
                "gating_activity_id": "A_renamed",
            },
        ])
        with pytest.raises(
            MethodologyValidationError, match="R014"
        ):
            assert_injection_method_consistency(df, {"A100"})
