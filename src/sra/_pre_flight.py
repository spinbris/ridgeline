"""Pre-flight assertions for the SRA workstream.

The strawman is the single source of truth for which risks simulate
(`Risk_Scope.Time_Impact == "Yes"`). Engine code does not encode the
expected risk set. This module provides the runtime check that the
strawman's actual Time_Impact=Yes count matches the count the strawman
itself declares in `Run_Config_Preview.Expected_Time_Yes_Count`.

The check is hard-fail. Any drift must be reconciled at the input layer
(strawman edit) and signed off as a stage amendment, not silently
processed by the engine.

Usage:
    from src.sra._pre_flight import preflight_strawman_shape
    preflight_strawman_shape()  # uses STRAWMAN_FILE env var
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import pandas as pd

from src.sra.strawman_reader import read_risk_scope, read_run_config


class MethodologyValidationError(RuntimeError):
    """Raised on strawman methodology violations the engine cannot
    silently work around.

    Reserved for input-layer drift that would silently produce wrong
    numbers if the engine kept running — e.g. SR12's
    ``injection_method = "discrete_event_additive_days"`` paired with a
    blank or unresolvable ``gating_activity_id``. Distinct from
    :class:`RuntimeError` shape mismatches so notebook callers can
    surface a methodology-banner vs an input-shape-banner without
    string-matching on the message.
    """


def assert_strawman_shape(
    risk_scope_df: pd.DataFrame, expected_count: int | None
) -> None:
    """Verify the strawman's Time_Impact=Yes count matches its declaration.

    Parameters
    ----------
    risk_scope_df : pd.DataFrame
        Output of `strawman_reader.read_risk_scope`.
    expected_count : int or None
        Value of `Run_Config_Preview.Expected_Time_Yes_Count`. None means
        the row is absent from the strawman.

    Raises
    ------
    RuntimeError
        If `expected_count` is None (declaration missing) or the actual
        Time_Impact=Yes count does not match `expected_count`.
    """
    if "time_impact" not in risk_scope_df.columns:
        raise RuntimeError(
            "Strawman Risk_Scope is missing the 'time_impact' column. "
            "Cannot run shape pre-flight."
        )

    mask = risk_scope_df["time_impact"].astype(str).str.strip().str.lower() == "yes"
    actual_count = int(mask.sum())

    if expected_count is None:
        raise RuntimeError(
            "Strawman Run_Config_Preview is missing 'Expected_Time_Yes_Count'. "
            "Add a row with Parameter='Expected_Time_Yes_Count' and "
            f"Value={actual_count} to declare the expected number of simulating "
            "risks. The engine will not run without this declaration."
        )

    if actual_count != expected_count:
        actual_ids = (
            risk_scope_df.loc[mask, "risk_id"].astype(str).tolist()
            if "risk_id" in risk_scope_df.columns else []
        )
        raise RuntimeError(
            f"Strawman shape mismatch: Run_Config_Preview declares "
            f"Expected_Time_Yes_Count={expected_count} but Risk_Scope contains "
            f"{actual_count} Time_Impact=Yes rows ({actual_ids}). "
            "Either (a) update Risk_Scope to match the declaration, "
            "(b) update Expected_Time_Yes_Count to match Risk_Scope and brief "
            "the change as a stage amendment, or (c) restore the strawman "
            "from git if this drift was unintentional."
        )


def assert_injection_method_consistency(
    risk_scope_df: pd.DataFrame,
    xer_task_codes: Iterable[str],
) -> None:
    """Validate per-risk SR12 injection-method dispatch consistency.

    Director Decision 3 = Option A (strict): when a risk's
    ``injection_method`` is ``"discrete_event_additive_days"``, its
    ``gating_activity_id`` must be non-blank AND must resolve to a
    ``task_code`` present in the current ``.xer`` TASK table.

    SRA-02 S-F, Director Decision D-7 (30/08/2026), widens resolution to
    every method: **any** non-blank ``gating_activity_id`` must resolve,
    whatever ``injection_method`` says, blank included. Only the
    *blank-gate* rule stays method-scoped. Under the old, method-scoped
    check the column was inert — GATINGINERT-01 — because no live path
    selects discrete-event dispatch, so a register could carry a
    non-existent activity id on every mapped risk and every gate in the
    tree stayed green.

    Bad gating activities silently producing wrong numbers is exactly
    the failure mode SR12 exists to prevent — the legacy additive
    broadcast hides a mis-bound activity inside the K × X aggregate;
    a single-column write to the wrong column would produce a
    plausible-looking but methodology-violating answer. We refuse to
    run rather than risk that.

    Parameters
    ----------
    risk_scope_df : pd.DataFrame
        Output of :func:`strawman_reader.read_risk_scope`. Must carry
        the SR12 columns ``injection_method`` and ``gating_activity_id``
        on every row (legacy strawmans without the columns emit empty
        strings, which pass the check unless the methodology column
        itself was populated to ``"discrete_event_additive_days"`` —
        in which case the gating column being blank is the error).
    xer_task_codes : Iterable[str]
        Every valid ``TASK.task_code`` from the current .xer parse.
        Coerced to ``set[str]`` for O(1) membership lookup. Callers
        typically pass ``set(xer_tables["TASK"]["task_code"])``.

    Raises
    ------
    MethodologyValidationError
        On any of:

        * ``injection_method = "discrete_event_additive_days"`` and the
          row's ``gating_activity_id`` is blank/None.
        * a non-blank ``gating_activity_id`` that does not appear in
          ``xer_task_codes``, under any ``injection_method`` (D-7).
        * ``injection_method`` is populated with a non-empty value that
          is not one of the four recognised dispatch keys.

    Notes
    -----
    Legacy rows with ``injection_method`` null/blank pass — the
    binding's null-fallback to ``additive_pert_days`` is the SR12
    backward-compat guarantee (Director Decision 1 = Option A). Blank
    *gating* rows pass on the same terms; D-7 constrains gates that are
    populated, not gates that are absent.
    """
    valid_methods = {
        "",  # null/blank — legacy fallback (Decision 1=A)
        "additive_pert_days",
        "multiplicative_pert_factor",
        "discrete_event_additive_days",
        "productivity_multiplicative_factor",
    }
    valid_codes = {str(c) for c in xer_task_codes}

    if (
        "injection_method" not in risk_scope_df.columns
        and "gating_activity_id" not in risk_scope_df.columns
    ):
        # Legacy strawman without the SR12 columns — every row is
        # implicitly null. Nothing to validate.
        return

    for row in risk_scope_df.itertuples():
        method = str(getattr(row, "injection_method", "") or "").strip()
        if method not in valid_methods:
            raise MethodologyValidationError(
                f"Risk {getattr(row, 'risk_id', '?')!r}: unknown "
                f"injection_method {method!r}. Allowed values: "
                f"{sorted(m for m in valid_methods if m)} or blank "
                "(legacy fallback)."
            )
        gating = str(
            getattr(row, "gating_activity_id", "") or ""
        ).strip()
        # SRA-02 S-F / D-7 — presence, not method. A populated gate must
        # resolve whatever injection_method says, blank included. Scoping
        # this to discrete-event was GATINGINERT-01: no live path selects
        # that method, so the column was written, read, carried onto live
        # drivers and never checked, and a register could name a
        # non-existent activity on every mapped risk and stay green.
        if gating and gating not in valid_codes:
            raise MethodologyValidationError(
                f"Risk {getattr(row, 'risk_id', '?')!r}: "
                f"gating_activity_id={gating!r} is not present in the "
                "current .xer TASK table. Either correct the strawman's "
                "Gating_Activity_ID value or re-promote the .xer baseline "
                "this strawman targets."
            )
        if method != "discrete_event_additive_days":
            continue
        if not gating:
            raise MethodologyValidationError(
                f"Risk {getattr(row, 'risk_id', '?')!r}: "
                "injection_method='discrete_event_additive_days' "
                "requires a non-blank gating_activity_id (Risk_Scope "
                "column 'Gating_Activity_ID')."
            )
        # The non-resolving case is already covered by the presence limb
        # above, which fires for every method — this limb is now only the
        # blank-gate rule that discrete-event dispatch adds on top.


def preflight_strawman_shape(strawman_path: str | Path | None = None) -> None:
    """End-to-end pre-flight: resolve strawman path, read inputs, assert shape.

    Resolution order: explicit argument > STRAWMAN_FILE env var.
    Designed to be called from `RUN_*.bat` via
    `python -c "from src.sra._pre_flight import preflight_strawman_shape; preflight_strawman_shape()"`.
    """
    if strawman_path is None:
        env_val = os.environ.get("STRAWMAN_FILE")
        if not env_val:
            raise RuntimeError(
                "preflight_strawman_shape: no strawman path provided and "
                "STRAWMAN_FILE env var is not set."
            )
        strawman_path = env_val
    p = Path(strawman_path)
    if not p.exists():
        raise RuntimeError(f"Strawman file not found: {p}")

    risk_scope_df = read_risk_scope(p)
    run_config = read_run_config(p)
    assert_strawman_shape(risk_scope_df, run_config.get("expected_time_yes_count"))


# ----------------------------------------------------------------------------
# SR19 — the reference register's named-range surface pre-flight
# ----------------------------------------------------------------------------
#
# Two anchor classes guard the engine against stale-formula corruption
# and silent register-drift:
#
# 1. SR19-D5 sentinel anchors: openpyxl reads stored cell values, not
#    live formula outputs. If the reference register is saved without an Excel F9
#    recalc (manual-calc mode, programmatic edit, CiE skipping F9),
#    every formula-derived cell returns stale results and the engine
#    silently consumes wrong numbers. Two anchors:
#
#      SR19_SENTINEL_CG01 = 0.6 (mc_cg_coeffs[CG01] lock-preserve value)
#      SR19_SENTINEL_FLOAT_THRESHOLD_HOURS = 480 (60wd × 8hpd derived value)
#
#    Both are part of the methodology surface; when a legitimate
#    methodology shift changes either, this constant MUST be updated
#    in the SAME commit that lands the methodology change. Loosening
#    the assertion (e.g. `> 0.5`) to silence a failing pre-flight
#    while a methodology call is in flight defeats the stale-formula
#    defence; skipping a methodology change because the sentinel
#    objects misreads the signal. See SR19 brief §4 SR19-D5.
#
# 2. SR19-D6 set-level assertion: the reference register's `cfg_expected_dual_coded_risk_ids`
#    cell holds the registered baseline set of dual-coded risk_ids.
#    Pre-flight asserts the live `Risk_Scope.Time_Impact=Yes` filter
#    returns exactly this set. A register update that flips
#    Time_Impact=Yes on a different risk keeps the count at 8 but
#    silently changes the ID set; the set-level check catches that.
#
# Sentinels are exposed as named constants at module top for a single
# grep-target update site per the SR19-D5 brief language.

SR19_SENTINEL_CG01: float = 0.6
SR19_SENTINEL_FLOAT_THRESHOLD_HOURS: int = 480


def preflight_v9_named_ranges(
    register_path: str | Path,
    *,
    caller_module: str = "unspecified",
    strawman_path: str | Path | None = None,
) -> None:
    """SR19 pre-flight: read the reference register's methodology defaults and verify both
    SR19-D5 sentinel anchors plus the SR19-D6 dual-coded set assertion.

    Composite failure mode per SR19-D1: every assertion failure is
    collected into a single error so the Director sees the full
    diagnostic in one pass.

    Parameters
    ----------
    register_path : str or Path
        The reference register workbook path. read_methodology_defaults uses this.
    caller_module : str
        Identifier for the calling code, surfaced in error messages.
    strawman_path : str or Path or None
        Optional strawman path for the SR19-D6 dual-coded set check.
        When None, the dual-coded set assertion is skipped (count-only
        check still happens via the dataclass __post_init__).

    Raises
    ------
    MethodologyDefaultsError (collected) on any failure.
    """
    # Import here to avoid the module-level circular: this module is
    # imported from various engine modules; the reader is a leaf and
    # safe to import lazily.
    from src.sra.methodology_defaults_reader import (
        MethodologyDefaultsError,
        read_methodology_defaults,
    )

    mdefaults = read_methodology_defaults(
        register_path, caller_module=caller_module,
    )

    issues: list[str] = []

    # SR19-D5 sentinel anchor #1: mc_cg_coeffs[CG01] lock-preserve value.
    actual_cg01 = mdefaults.cg_coefficients.get("CG01")
    if actual_cg01 != SR19_SENTINEL_CG01:
        issues.append(
            f"SR19-D5 sentinel anchor #1 failed: mc_cg_coeffs[CG01] = "
            f"{actual_cg01!r}, expected {SR19_SENTINEL_CG01} "
            f"(lock-preserve baseline). Probable cause: the reference register was saved "
            f"without an Excel F9 recalc + save after an MC_Params "
            f"edit (openpyxl reads stored cell values, not live formula "
            f"outputs). Less likely: a legitimate methodology shift "
            f"changed CG01; in that case update SR19_SENTINEL_CG01 in "
            f"src/sra/_pre_flight.py in the SAME commit that lands the "
            f"methodology change (do NOT loosen the assertion)."
        )

    # SR19-D5 sentinel anchor #2: float-threshold derived value.
    actual_derived = (
        mdefaults.auto_mapper_float_threshold_working_days
        * mdefaults.working_hours_per_day
    )
    if actual_derived != SR19_SENTINEL_FLOAT_THRESHOLD_HOURS:
        issues.append(
            f"SR19-D5 sentinel anchor #2 failed: "
            f"auto_mapper_float_threshold_working_days "
            f"({mdefaults.auto_mapper_float_threshold_working_days}) "
            f"× working_hours_per_day ({mdefaults.working_hours_per_day}) "
            f"= {actual_derived}, expected {SR19_SENTINEL_FLOAT_THRESHOLD_HOURS}. "
            f"Probable cause: the reference register was saved without an Excel F9 recalc "
            f"after a MC_Params edit on one of the two input cells. "
            f"Less likely: a legitimate methodology shift; in that case "
            f"update SR19_SENTINEL_FLOAT_THRESHOLD_HOURS in the SAME "
            f"commit that lands the methodology change."
        )

    # SR19-D6 set-level dual-coded assertion (when strawman supplied).
    if strawman_path is not None:
        try:
            risk_scope_df = read_risk_scope(Path(strawman_path))
        except Exception as exc:
            issues.append(
                f"SR19-D6 dual-coded set assertion failed at strawman "
                f"read: {exc}"
            )
        else:
            mask = risk_scope_df["time_impact"].astype(str).str.strip().str.lower() == "yes"
            live = frozenset(str(r).strip() for r in risk_scope_df.loc[mask, "risk_id"])
            expected = mdefaults.expected_dual_coded_risk_ids
            if live != expected:
                added = sorted(live - expected)
                removed = sorted(expected - live)
                issues.append(
                    f"SR19-D6 dual-coded set drift detected. "
                    f"Expected (the reference register's cfg_expected_dual_coded_risk_ids): "
                    f"{sorted(expected)}. Live (strawman Risk_Scope."
                    f"Time_Impact=Yes): {sorted(live)}. Added: {added}. "
                    f"Removed: {removed}. Update the reference register's cell + named "
                    f"range (Director sign-off) before re-running."
                )

    # SR21: catch a broken reference in the cost-arm risk-register read before
    # the run. read_risks_v5 scans its read ranges and raises a located
    # composite RegisterReadError on any Excel-error sentinel; fold that into
    # the pre-flight's composite so the Director sees it alongside the named-
    # range issues in one pass. Output-neutral for the reference register (no broken refs).
    from src.v5_register_reader import RegisterReadError, read_risks_v5

    try:
        read_risks_v5(register_path)
    except RegisterReadError as exc:
        issues.append(f"SR21 risk-register read: {exc}")

    if issues:
        raise MethodologyDefaultsError(
            f"consumer={caller_module}: the reference register pre-flight failed. "
            f"{len(issues)} issue(s):\n  - " + "\n  - ".join(issues)
        )
