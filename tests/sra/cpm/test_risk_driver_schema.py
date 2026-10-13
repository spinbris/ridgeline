"""Dataclass invariants for src.sra.cpm.risk_driver_schema (SR-S3-Beta-04).

Six tests covering the frozen-dataclass contract, defaults, and
parquet-schema agreement (the column list is derived from
``dataclasses.fields(AutoMapAuditRow)`` so any drift is caught).
"""

from __future__ import annotations

import dataclasses

import pytest

from src.sra.cpm.risk_driver_schema import (
    AutoMapAuditRow,
    AutoMapperConfig,
    AutoMapperRule,
    InjectionMethod,
    RiskDriver,
)


_BASE_RULE_KW = dict(
    risk_id="R001",
    pattern_id="P01",
    pattern_prefixes=("10.",),
    float_threshold_hours=480.0,
    injection_method="additive_pert_days",
    opt_pert=1.0,
    ml_pert=2.0,
    pess_pert=4.0,
    probability=0.5,
)


class TestSchemaInvariants:
    """RiskDriver / AutoMapperRule / AutoMapperConfig / AutoMapAuditRow."""

    def test_riskdriver_frozen(self) -> None:
        """Assigning to a frozen dataclass field raises FrozenInstanceError."""
        rd = RiskDriver(
            risk_id="R001",
            affected_activity_ids=("A1",),
            injection_method="additive_pert_days",
            opt_pert=1.0,
            ml_pert=2.0,
            pess_pert=3.0,
            probability=0.5,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            rd.probability = 0.9  # type: ignore[misc]

    def test_riskdriver_minimum_fields_construct(self) -> None:
        """Required fields constructible; optional flags default False / None."""
        rd = RiskDriver(
            risk_id="R001",
            affected_activity_ids=(),
            injection_method="additive_pert_days",
            opt_pert=1.0,
            ml_pert=2.0,
            pess_pert=3.0,
            probability=0.5,
        )
        assert rd.pattern_id is None
        assert rd.derived_at_run_time is False
        assert rd.workshop_validated is False

    def test_automapperrule_pattern_prefixes_is_tuple(self) -> None:
        """pattern_prefixes must be a tuple — list input is not hashable.

        The frozen-dataclass contract relies on the tuple to keep the
        rule hashable; a list would silently break dict-key usage and
        equality semantics. We assert the type is preserved verbatim
        rather than coerced.
        """
        rule = AutoMapperRule(**_BASE_RULE_KW)
        assert isinstance(rule.pattern_prefixes, tuple)
        # Frozen + tuple makes the rule hashable — exercise it.
        hash(rule)

    def test_automapperconfig_defaults_match_methodology(self) -> None:
        """Defaults match SR_S3_workshop_preread §Methodology."""
        cfg = AutoMapperConfig()
        assert cfg.default_float_threshold_hours == 480.0
        # RS-D-6 (D-18): no code default for the injection method; the register carries it.
        assert not hasattr(cfg, "default_injection_method")
        assert cfg.require_task_type_TT_Task is True
        assert cfg.min_activities_warning_threshold == 5
        assert cfg.max_activities_warning_threshold == 500

    def test_audit_row_columns_match_parquet_schema(self) -> None:
        """dataclasses.fields(AutoMapAuditRow) produces the parquet column list.

        The auto_mapper.write_audit_trail writer derives its column list
        from this exact dataclass, so this test pins the parquet schema
        against the documented column ordering in the brief §4.2.
        """
        names = [f.name for f in dataclasses.fields(AutoMapAuditRow)]
        assert names == [
            "risk_id",
            "activity_id",
            "pattern_id",
            "injection_method",
            "opt_pert",
            "ml_pert",
            "pess_pert",
            "probability",
            "derived_at_run_time",
            "workshop_validated",
            # SR10.A — Mode classification persisted to the parquet
            # audit trail so the divergence-table interpretation in
            # SR10.B is traceable to the per-run inputs.
            "mode",
            # SR12 — per-risk gating activity id persisted onto the
            # audit parquet so a reviewer can trace which gating
            # activity the engine wrote to for a discrete-event risk.
            # Empty string for non-discrete-event methods.
            "gating_activity_id",
            # GATECOHORT-01 (Director D-4, 10/09/2026) — the gate's
            # relation to its cohort (member / upstream / downstream),
            # so the audit says which shape each discrete-event row
            # takes. None for non-discrete-event methods.
            "gating_relation",
        ]

    def test_pert_inverted_triple_rejected(self) -> None:
        """opt > ml or ml > pess raises ValueError at construction.

        Catches workshop / binding-layer data-entry errors at the
        boundary; without this guard an inverted triple would propagate
        to NaN deltas (negative Beta shape parameters). Both
        AutoMapperRule and RiskDriver enforce the invariant.
        """
        bad_triple_kw = dict(_BASE_RULE_KW, opt_pert=4.0, ml_pert=2.0, pess_pert=1.0)
        with pytest.raises(ValueError, match="opt <= ml <= pess"):
            AutoMapperRule(**bad_triple_kw)

        with pytest.raises(ValueError, match="opt <= ml <= pess"):
            RiskDriver(
                risk_id="R001",
                affected_activity_ids=(),
                injection_method="additive_pert_days",
                opt_pert=4.0,
                ml_pert=2.0,
                pess_pert=1.0,
                probability=0.5,
            )

    def test_probability_out_of_range_rejected(self) -> None:
        """probability outside [0, 1] raises ValueError at construction."""
        for bad_prob in (-0.1, 1.5):
            kw = dict(_BASE_RULE_KW, probability=bad_prob)
            with pytest.raises(ValueError, match="probability"):
                AutoMapperRule(**kw)

    def test_injection_method_literal_values(self) -> None:
        """Both literal values constructible as injection_method.

        The Literal type itself is enforced statically; at runtime a
        string is accepted. We assert both canonical values round-trip
        through both an AutoMapperRule and a RiskDriver, locking the
        public-API contract.
        """
        for method in ("additive_pert_days", "multiplicative_pert_factor"):
            kw = dict(_BASE_RULE_KW, injection_method=method)
            rule = AutoMapperRule(**kw)
            assert rule.injection_method == method
            rd = RiskDriver(
                risk_id="R001",
                affected_activity_ids=(),
                injection_method=method,
                opt_pert=1.0,
                ml_pert=2.0,
                pess_pert=3.0,
                probability=0.5,
            )
            assert rd.injection_method == method

        # Sanity — type-alias exists and is the expected Literal.
        # (Runtime check; mypy enforces statically.)
        assert InjectionMethod is not None
