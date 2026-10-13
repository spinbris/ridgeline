"""One Stage 3 config construction, shared by the showcase and the deliverable.

3c Part A, Director decision 04/09/2026 (option A): the deliverable's Stage 3 arm and
``scripts/run_wind_showcase.run_integrated`` build their :class:`IntegratedConfigStage3`
**here**, so A-5's "the deliverable reproduces the showcase headline exactly" holds because
they are the same construction - not because two hand-built configs happen to coincide today.
Two sources for one number is the shape that drifts silently the first time either is edited.

Why this is not ``load_integrated_config_stage3``
-------------------------------------------------
That loader reads its inputs from the environment and stays as it is. It cannot serve a
grid-native register, for one reason: it populates :class:`MethodologyDefaults` through
``read_methodology_defaults``, which reads the legacy register's named ranges and raises on a
grid-native register naming 22 absent ranges (WINDMETH-01).

The measured shape of that dependency (3c Part A pre-paste, recorded in
the 3c Part A running record, §3): ``MethodologyDefaults``
declares 22 fields and **exactly two are read anywhere in src/** - ``mode_multipliers``
(``src/final/composer.py``, ``src/final/stage3_composer.py``) and ``cg_coefficients``
(``src/final/composer.py``). Both are readable from either register shape today. So this module
sources those two from the register the run is actually using, and leaves the twenty
nothing reads to the factory that already supplies them.

That the other twenty are inert is a measurement, not an assumption, and measurements go stale:
``tests/test_3c_a_methodology_fields.py`` re-derives the read set from the tree and fails
naming any third field the day one is read, so this module's premise cannot rot unnoticed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.integrated.integrated_simulation import IntegratedConfig
from src.integrated.integrated_simulation_stage3 import IntegratedConfigStage3
from src.integrated.run_config_contract import (
    read_run_config_strict,
    require_day_rate,
    resolve_day_rate,
    resolve_programme_days,
    resolve_run_setting,
)
from src.sra import strawman_reader
from src.sra._pre_flight import MethodologyValidationError
from src.rng_streams import require_seed
from src.integrated.stage3_inputs import (
    Stage3BindingConfig,
    resolve_default_injection_method,
    resolve_float_threshold_hours,
)
from src.sra.cpm.cpm_simulation import ScheduleMCConfig
from src.sra.methodology_defaults_reader import (
    build_test_methodology_defaults,
    read_calibration_tolerances,
    read_cg_coefficients,
    read_mode_multipliers,
)

#: The Stage 3 production basis, in one place instead of at each call site.
#:
#: ``apply_mode_multipliers=False`` - SR15 retired the Mode multiplier on the full-CPM path
#: (the CPM kernel models schedule propagation directly, so a multiplier on top double-counts);
#: SR17 made Stage 3 the production headline. Every Stage 3 caller in the tree already sets
#: False explicitly; naming it once is what stops the next caller relying on the dataclass
#: default, which is True and which relying on was the pre-WIND-01 defect.
#:
#: ``criticality_measurement_mode="mode_independent"`` - under ``apply=False`` the
#: Mode-conditioned and Mode-independent indices coincide, so a second pass produces an
#: identical array at twice the cost.
STAGE3_APPLY_MODE_MULTIPLIERS = False
STAGE3_CRITICALITY_MODE = "mode_independent"
STAGE3_BATCH_SIZE = 2000


def build_stage3_config(
    *,
    register_path: Path | str,
    xer_path: Path | str,
    strawman_path: Path | str,
    iterations: int | None = None,
    seed: int | None = None,
    day_rate: float | None = None,
    project: str | None = None,
    caller_module: str = "unspecified",
) -> IntegratedConfigStage3:
    """Build the Stage 3 integrated config for one project, from that project's register.

    Every methodology value that reaches a number is read from ``register_path``: the four
    calibration tolerances (RS-D-2, D-14), the Mode multiplier grid (RS-D-3b, D-15), the CG
    coefficients, and the run-config block (day rate, iterations, reporting P-level, programme
    days). Nothing here carries a code default for any of them - a register that does not
    supply one raises through the reader that owns it, by ruling.

    ``iterations`` and ``day_rate`` override the register's values where a caller needs to (a
    draft run at low iterations). ``None`` means "the register's". ``seed`` is required: the
    register carries none for this route, and a missing one is refused by name, where it used to
    run the schedule arm at 42 and record no seed on the integrated arm (SEEDFALLBACK-01).

    ``project`` names the project whose binding supplies the float threshold. A caller that
    resolved these three paths from a project passes that project's name, so the threshold
    follows the run's inputs rather than whatever ``QRA_PROJECT`` happens to hold; ``None``
    falls back to the active selection, which is all a caller who named no project can mean
    (REFRETIRE-01 numerics review, WARN-1).

    Works for both register shapes - legacy named-range and grid-native - because every reader
    it calls does.
    """
    register_path = Path(register_path)
    xer_path = Path(xer_path)
    strawman_path = Path(strawman_path)

    run_cfg = read_run_config_strict(strawman_path, strawman_reader.read_run_config)
    resolved_day_rate = (
        float(day_rate) if day_rate is not None
        else resolve_day_rate(run_cfg, strawman_path)
    )
    # No code default for either (CONFIGTRUTH-01): the register's row, else the project's
    # binding's declared default, else a refusal naming the row, the sheet and the binding. A
    # zero or negative is refused from every source. The source travels to the manifest. The
    # deliverable's pre-flight reports both by name before anything computes, so the refusal an
    # operator actually meets is the single message, not this.
    resolved_iterations, iterations_source = resolve_run_setting(
        run_cfg, "iterations", strawman_path=strawman_path, project=project,
        override=iterations, caller_module=caller_module,
    )
    reporting_p_level, p_level_source = resolve_run_setting(
        run_cfg, "p_level_reporting", strawman_path=strawman_path, project=project,
        caller_module=caller_module,
    )

    mode_multipliers = read_mode_multipliers(register_path, caller_module=caller_module)
    cg_coefficients = read_cg_coefficients(register_path, caller_module=caller_module)

    # The twenty fields nothing reads (see module docstring); the two that are read are
    # overridden here with this register's own values, so no other project's number can
    # reach this run through them.
    methodology_defaults = build_test_methodology_defaults(
        mode_multipliers=dict(mode_multipliers),
        cg_coefficients=dict(cg_coefficients),
    )

    seed = require_seed(seed, where=f"build_stage3_config (called from {caller_module})")
    integrated_config = IntegratedConfig(
        register_path=register_path,
        p6_path=xer_path,
        strawman_path=strawman_path,
        methodology_defaults=methodology_defaults,
        iterations=resolved_iterations,
        random_seed=seed,
        day_rate=resolved_day_rate,
        reporting_p_level=reporting_p_level,
        programme_days=resolve_programme_days(run_cfg),
        cg_correlation_coefficients=dict(cg_coefficients),
        **read_calibration_tolerances(register_path, caller_module=caller_module),
    )

    # REFRETIRE-01: the float threshold comes from the active project's binding. It used to be
    # the config class's field default - one project's 480 hours, inherited by every run that
    # did not override it, and inert only because the two synthetic bindings declare the same
    # number. A project that declares none is refused by name.
    binding_config = Stage3BindingConfig(
        register_path=register_path,
        xer_path=xer_path,
        strawman_path=strawman_path,
        float_threshold_hours=resolve_float_threshold_hours(project),
        cg_coefficients=dict(cg_coefficients),
        populate_modes_from_strawman=True,
        apply_mode_multipliers=STAGE3_APPLY_MODE_MULTIPLIERS,
    )

    schedule_mc_config = ScheduleMCConfig(
        n_iter=resolved_iterations,
        batch_size=STAGE3_BATCH_SIZE,
        seed=seed,
        apply_mode_multipliers=STAGE3_APPLY_MODE_MULTIPLIERS,
        mode_multipliers=dict(mode_multipliers),
    )

    return IntegratedConfigStage3(
        integrated_config=integrated_config,
        schedule_mc_config=schedule_mc_config,
        binding_config=binding_config,
        criticality_measurement_mode=STAGE3_CRITICALITY_MODE,
        run_setting_sources={"iterations": iterations_source,
                             "reporting_p_level": p_level_source},
    )


#: The sheet a register carries when its Stage 3 drivers come from a pattern catalogue.
#: Its presence is what decides which rule source below applies - a property of the register,
#: read from the register, not a branch on which project is selected.
PATTERN_CATALOGUE_SHEET = "Risk_Activity_Patterns"


def register_carries_pattern_catalogue(strawman_path: Path | str) -> bool:
    """Whether this register/strawman supplies a Stage 3 pattern catalogue.

    Two register shapes reach Stage 3 by two routes, and this is the difference between them:

    * **With a catalogue** - the binding's own driver builder joins the pattern sheets into
      per-risk rules. The reference project's separate strawman is this shape.
    * **Without one** - the schedule scope lives in the register itself (REG-01 dissolved the
      strawman into it) and rules are built from each Time=Yes row's ``Prefix_List`` by
      :func:`build_stage3_rules_from_scope`. The synthetic wind register is this shape.

    Asking the register rather than the project name is what keeps this generic: a third
    project is placed by its own structure, with no code change.

    **A catalogue is pattern rows, not a sheet** (stage 4 F-28, first-rank, 08/09/2026). This
    tested for the sheet's *presence*, and the scaffolder ships ``Risk_Activity_Patterns`` on
    every register, header only - so every hand-made register was forced onto the pattern route,
    which its empty pattern sheets cannot satisfy, while the structure lock stopped the filler
    deleting the sheet. Neither fixture carries the sheet, so neither ever met it. Now: the sheet
    counts as a catalogue only if a pattern row sits below the header, located the way
    ``read_risk_activity_patterns`` locates it (column A reads ``Pattern_ID``, scanned twenty rows
    down), so the note block the scaffolder writes above the header is not mistaken for data.
    """
    from openpyxl import load_workbook

    wb = load_workbook(str(strawman_path), read_only=True)
    try:
        if PATTERN_CATALOGUE_SHEET not in wb.sheetnames:
            return False
        header_seen = False
        for i, row in enumerate(wb[PATTERN_CATALOGUE_SHEET].iter_rows(values_only=True), start=1):
            first = row[0] if row else None
            if not header_seen:
                if str(first or "").strip().lower() == "pattern_id":
                    header_seen = True
                elif i >= 20:
                    return False        # no header where the reader would look: no catalogue
                continue
            if first is not None and str(first).strip():
                return True             # a pattern row below the header
        return False
    finally:
        wb.close()


def build_stage3_rules_from_scope(risk_scope, graph, binding_config) -> dict[str, Any]:
    """Auto-mapper rules from a register's own Time=Yes rows, for registers with no catalogue.

    Lifted verbatim from ``run_wind_showcase._strawman_stage3_rules`` under the Director's
    option-A decision (04/09/2026) so the showcase and the deliverable build wind's Stage 3
    drivers with one function rather than two that must agree. Behaviour is unchanged, and the
    wind golden is what holds it unchanged.

    ``graph`` is required rather than optional, and that is the point (SRA-02 S-F, D-7): a
    ``Gating_Activity_ID`` naming no activity in the schedule about to run is refused here
    rather than skipped silently in the kernel's per-iteration write. An optional argument
    would let a future third caller skip the check.

    **WINDINJ-01 closed here, Director D-1 09/09/2026.** ``injection_method`` was pinned to
    ``additive_pert_days`` and is now the register's, per row where the row declares one and
    the register's ``Default_Injection_Method`` otherwise. The pin's stated reason - that
    these rows carry no ``Gating_Activity_ID`` - held on no register in the tree: all three
    carry one on every Time=Yes row. Removing it moves both showcase projects' Stage 3
    numbers, which is the re-bless the Director approved rather than a side-effect.
    """
    from src.sra._pre_flight import assert_injection_method_consistency
    from src.sra.cpm.risk_driver_schema import AutoMapperRule

    assert_injection_method_consistency(
        risk_scope, {a.code for a in graph.activities.values()})

    # The register writes ``Gating_Activity_ID`` as the human-readable XER ``task_code``; the
    # kernel indexes activities by ``Activity.id``. Translating here is the whole of WINDINJ-01's
    # second half: a code handed through untranslated satisfies every check in this module and
    # then misses ``risk_injection``'s ``id_to_col`` lookup, whose documented defensive skip
    # (:377-383) turns it into 0.000 delay on every iteration with nothing on screen.
    code_to_id = {a.code: a.id for a in graph.activities.values()}
    default_method = resolve_default_injection_method(binding_config)

    rules: dict[str, Any] = {}
    for _, row in risk_scope.iterrows():
        if str(row["time_impact"]).strip() != "Yes":
            continue
        prefix_list = str(row["prefix_list"] or "").strip()
        prefix = prefix_list.rstrip(".") if prefix_list else ""
        if not prefix:
            continue
        rid = row["risk_id"]
        method = str(row["injection_method"] or "").strip() or default_method
        rules[rid] = AutoMapperRule(
            risk_id=rid, pattern_id=str(row["pattern_id"] or f"P{prefix}"),
            pattern_prefixes=(prefix,),
            float_threshold_hours=float(binding_config.float_threshold_hours),
            injection_method=method,
            gating_activity_id=_resolve_gating_activity_id(row, rid, method, code_to_id),
            opt_pert=float(row["opt_days"]), ml_pert=float(row["ml_days"]),
            pess_pert=float(row["pess_days"]), probability=float(row["probability"]),
            mode=str(row["mode_aggregated"]),
        )
    return rules


def _resolve_gating_activity_id(row, risk_id, method, code_to_id) -> str | None:
    """The internal activity id this row's discrete-event write lands on, or a refusal.

    Brief WINDINJ-01 §5: where a register declares a method its rows cannot satisfy, the run
    refuses and names the row rather than falling back.

    The blank-gate refusal below is reachable and is new here. ``assert_injection_method_consistency``
    scopes its own blank-gate rule to the method the *row* declares, so a row that declares
    nothing and inherits a discrete default from the register passes it and arrives with no
    activity to write to. Reading the register's default is what opens that gap, so closing it
    belongs on the same change.

    There is deliberately no second refusal for a code that does not resolve. The pre-flight
    validated every non-blank gate against ``{a.code for a in graph.activities.values()}`` and
    ``code_to_id`` is built from that same set, so a miss here would mean the validator and the
    graph disagree - this module's bug, not a register's. Let the lookup raise, as the sibling
    retired binding did. A branch that cannot fire is not a guard.
    """
    if method != "discrete_event_additive_days":
        return None

    code = str(row.get("gating_activity_id") or "").strip()
    if not code:
        raise MethodologyValidationError(
            f"risk {risk_id!r} takes injection_method='discrete_event_additive_days' from the "
            f"register's default but carries no Gating_Activity_ID. The method writes the "
            f"sampled delay to one activity and this row names none. Refusing rather than "
            f"falling back to a broadcast, which would answer a different question under the "
            f"same label."
        )
    return code_to_id[code]


def stage3_config_summary(config: IntegratedConfigStage3) -> dict[str, Any]:
    """The values this config was built from, for the run's provenance manifest (§3 limb 3)."""
    ic = config.integrated_config
    return {
        "register_path": str(ic.register_path),
        "xer_path": str(ic.p6_path),
        "strawman_path": str(ic.strawman_path),
        "iterations": int(ic.iterations),
        "seed": ic.random_seed,
        # DAYRATE-02: every IntegratedConfig day-rate read in src/ passes through the guard,
        # so a run that reached here without one stops rather than stamping a plausible
        # number into the provenance manifest.
        "day_rate": float(require_day_rate(ic.day_rate, caller="stage3_config_summary")),
        "reporting_p_level": int(ic.reporting_p_level),
        # CONFIGTRUTH-01: "register", "binding default" or "override", so a defaulted value
        # never passes for a chosen one. None for a config not built by build_stage3_config.
        "iterations_source": config.run_setting_sources.get("iterations"),
        "reporting_p_level_source": config.run_setting_sources.get("reporting_p_level"),
        "programme_days": ic.programme_days,
        "mode_multipliers": dict(config.schedule_mc_config.mode_multipliers),
        "cg_coefficients": dict(ic.cg_correlation_coefficients),
        "apply_mode_multipliers": bool(config.schedule_mc_config.apply_mode_multipliers),
        "criticality_measurement_mode": config.criticality_measurement_mode,
        "cost_calibration_tolerance_dollars": ic.cost_calibration_tolerance_dollars,
        "cost_calibration_tolerance_pct": ic.cost_calibration_tolerance_pct,
        "schedule_calibration_tolerance_days": ic.schedule_calibration_tolerance_days,
        "schedule_calibration_tolerance_pct": ic.schedule_calibration_tolerance_pct,
    }
