"""SR11 — Stage 3 Beta integrated engine.

Joint cost + Stage 3 Beta CPM-replay schedule MC. Mirrors
:mod:`src.integrated.integrated_simulation` structurally but swaps the
schedule branch from Stage 2.5 risk-driver PERT-on-days to the Stage 3
CPM-replay produced by :func:`src.sra.cpm.cpm_simulation.run_schedule_mc`.

Design decision: Director D1 = Option A (new module). The Stage 2.5
integrated engine remains untouched. This module is engine-tier and
methodology-bearing: any change here must respect the joint-sampling
invariant (per-iteration shared severity uniform across cost and
schedule for dual-coded risks; independent uniforms for cost-only
risks) and the Page 1 contingency-table contract expected by the
composer sibling deliverable.

Output contract
---------------
The return dict surface key-compatibility with the existing
:func:`run_integrated_simulation` return dict — same key names for
``cost_dollars_array`` (per-iteration cost), ``schedule_days_array``
(per-iteration project finish in working days), ``per_risk_cost_array``,
``risk_ids_all``, etc. — so :func:`src.final.composer._compute_component_breakdown`
can be re-used unchanged via a thin adapter (see
:func:`adapt_to_integrated_results_shape`).

Hard invariants
---------------
1. Joint sampling: dual-coded risks share ONE fire decision and ONE severity
   uniform per iteration across the cost arm and the Stage 3 Beta schedule
   arm (SPEC R-10, METHFIRE-01). The fire decision is the cost arm's own
   record, post-chain (:func:`src.qra_core.draw_fire_matrix`); the schedule
   kernel consumes it rather than drawing. Cost-only risks use independent
   severity uniforms. Severity construction site:
   :func:`src.integrated.stage3_inputs.build_joint_severity_uniforms`.
2. Cost-side parity with Stage 2.5: when the same seed and same
   severity uniforms are passed through, the cost-arm output is
   bit-identical to :func:`run_integrated_simulation` invoked with the
   same ``precomputed_severity_uniforms``. Locked by
   :func:`tests.test_sr11_integrated_simulation_stage3.test_cost_parity_with_stage25`.
3. Calibration tolerances unchanged: $50k cost / 1 day schedule
   marginal calibration against the standalone arms. The schedule
   standalone is the Stage 3 Beta CPM-replay run via
   :func:`src.sra.cpm.cpm_simulation.run_schedule_mc`; its mean may be
   large where a register's dual-coded risks over-bind, and the gate
   validates engine integrity, not data quality.
4. Pure-data engine layer: returns DataFrames / dicts / numpy arrays
   only. No rendering. No printing. Logger.info for run-level
   instrumentation.
5. Stage 2.5 production deliverable is bit-for-bit unchanged. This
   module imports the Stage 2.5 cost branch (it depends on
   ``run_integrated_simulation`` to do the joint cost draw) but the
   Stage 2.5 engine itself is not modified.

Out of scope
------------
- Injection-method change in ``risk_injection.py`` (see SR12 brief).
- Workshop mapping work.
- VG3 / VG5 graduation analysis.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.rng_streams import kernel_generator, require_seed, severity_generator
from src.sra.methodology_defaults_reader import (
    read_calibration_tolerances,
    read_cg_coefficients,
)

from src.integrated.integrated_simulation import (
    IntegratedConfig,
    run_integrated_simulation,
)
from src.integrated.run_config_contract import (
    day_rate_audit_fields,
    read_run_config_strict,
    require_day_rate,
    resolve_day_rate,
    resolve_programme_days,
)
from src.integrated.stage3_inputs import (
    Stage3BindingConfig,
    build_joint_severity_uniforms,
    resolve_default_injection_method,
    resolve_float_threshold_hours,
)
from src.sra.cpm.cpm_simulation import (
    CriticalityMeasurementMode,
    ScheduleMCConfig,
    ScheduleMCResult,
    run_schedule_mc,
)
from src.sra.cpm.graph_builder import build_schedule_graph
from src.sra.cpm.xer_reader import parse_xer
from src.sra import strawman_reader
from src.v5_register_reader import read_risks_v5


logger = logging.getLogger(__name__)


__all__ = [
    "IntegratedConfigStage3",
    "Stage3IntegratedResult",
    "load_integrated_config_stage3",
    "run_integrated_simulation_stage3",
    "adapt_to_integrated_results_shape",
]


# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

@dataclass
class IntegratedConfigStage3:
    """Universal knobs for the Stage 3 Beta integrated engine.

    Wraps the Stage 2.5 :class:`IntegratedConfig` (cost arm) and the
    schedule-arm :class:`ScheduleMCConfig` so the two arms see a
    consistent iteration count and seed. There are no default paths: every run names its
    own register, schedule and strawman through :class:`Stage3BindingConfig` (REFRETIRE-01).

    Calibration tolerances are inherited verbatim from
    :class:`IntegratedConfig` (per the SR11 brief §4.2: tolerances apply
    against whatever the Stage 3 standalone produces, over-binding
    artefacts included).

    Attributes
    ----------
    integrated_config : IntegratedConfig
        Cost-arm sampling/tolerance configuration (iteration count,
        seed, day rate, calibration tolerances, CG correlation
        coefficients, chain config). Same surface as Stage 2.5.
    schedule_mc_config : ScheduleMCConfig
        Schedule-arm chunking + precision configuration.
    binding_config : Stage3BindingConfig
        This run's inputs and knobs (register / xer / strawman paths, float threshold,
        injection method, Mode population flag). Required: it has no project defaults.
    criticality_measurement_mode : CriticalityMeasurementMode
        SR10.A criticality measurement mode. Default
        ``"mode_conditioned"`` matches Stage 2.5 semantics.
    """

    integrated_config: IntegratedConfig
    schedule_mc_config: ScheduleMCConfig
    binding_config: Stage3BindingConfig
    criticality_measurement_mode: CriticalityMeasurementMode = (
        "mode_conditioned"
    )
    #: CONFIGTRUTH-01: where ``iterations`` and ``reporting_p_level`` came from ("register",
    #: "binding default" or "override"), for the provenance manifest only. No engine reads it.
    #: Empty for a config built other than by ``build_stage3_config``.
    run_setting_sources: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.integrated_config.iterations != self.schedule_mc_config.n_iter:
            raise ValueError(
                "iteration counts differ between cost and schedule arms: "
                f"integrated_config.iterations={self.integrated_config.iterations}, "
                f"schedule_mc_config.n_iter={self.schedule_mc_config.n_iter}; "
                "both arms must run at the same iteration count for the "
                "joint severity-uniform matrix to align"
            )


# ----------------------------------------------------------------------------
# Result container
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Stage3IntegratedResult:
    """Frozen result container for one Stage 3 Beta integrated run.

    Carries both arms' raw outputs and the joint metadata. The composer
    consumes ``cost_result`` and ``schedule_result_days_array`` to build
    the Page 1 contingency table; the Mode-override scenario name is
    used for sibling-deliverable filename suffixing.
    """

    cost_result: dict[str, Any]
    schedule_result: ScheduleMCResult
    schedule_days_array: np.ndarray
    severity_uniforms_by_risk_id: dict[str, np.ndarray]
    risk_drivers: dict[str, Any]
    schedule_graph: Any
    xer_tables: dict[str, pd.DataFrame]
    auto_mapper_audit_path: str | None
    beta_flag: bool
    iterations: int
    seed_used: int
    variant_label: str
    config_summary: dict[str, Any]


# ----------------------------------------------------------------------------
# Config loader (mirrors load_integrated_config in the Stage 2.5 module)
# ----------------------------------------------------------------------------

_CALLER_MODULE = "src/integrated/integrated_simulation_stage3.py"

_ENV_REGISTER = "REGISTER_FILE"
_ENV_P6 = "P6_FILE"
_ENV_STRAWMAN = "STRAWMAN_FILE"


def _resolve_path(cli_override: str | None, env_var: str) -> Path | None:
    if cli_override:
        return Path(cli_override)
    env_val = os.environ.get(env_var)
    if env_val:
        return Path(env_val)
    return None


def load_integrated_config_stage3(
    register_override: str | None = None,
    p6_override: str | None = None,
    strawman_override: str | None = None,
    seed_override: int | None = None,
    iterations_override: int | None = None,
) -> IntegratedConfigStage3:
    """Resolve :class:`IntegratedConfigStage3` from CLI overrides / env / defaults.

    Same path-resolution order as
    :func:`src.integrated.integrated_simulation.load_integrated_config`:
    CLI override → env var → strawman default → binding default. The
    ``Day_rate_default`` and ``iterations`` are sourced from the
    strawman ``Run_Config_Preview`` sheet when present.
    """
    register_path = _resolve_path(register_override, _ENV_REGISTER)
    p6_path = _resolve_path(p6_override, _ENV_P6)
    strawman_path = _resolve_path(strawman_override, _ENV_STRAWMAN)

    # REFRETIRE-01: an input this loader cannot resolve stops the run naming the input.
    # Until REFRETIRE-01, each of these fell through to one project's own file, so a caller
    # who named none of them silently ran somebody else's register.
    missing = [
        name for name, value, env in (
            ("register", register_path, _ENV_REGISTER),
            ("schedule (.xer)", p6_path, _ENV_P6),
            ("strawman", strawman_path, _ENV_STRAWMAN),
        ) if value is None
    ]
    if missing:
        raise ValueError(
            "load_integrated_config_stage3: no "
            + ", ".join(m for m in missing)
            + " supplied. Name each input on the call or in its environment variable "
              f"({_ENV_REGISTER}, {_ENV_P6}, {_ENV_STRAWMAN}); there is no default project."
        )
    # DAYRATE-01: same contract as the Stage 2.5 loader, from the same module
    # so the two arms cannot drift apart again. This is the production
    # headline arm since SR17, and it is what the golden gate exercises.
    cfg = read_run_config_strict(
        strawman_path, strawman_reader.read_run_config,
    )
    day_rate = resolve_day_rate(cfg, strawman_path)
    # Built after the strawman read, so a malformed strawman is reported as such rather than
    # behind a register error (DAYRATE-01's contract, kept at REFRETIRE-01).
    binding_cfg = Stage3BindingConfig(
        register_path=register_path,
        xer_path=p6_path,
        strawman_path=strawman_path,
        float_threshold_hours=resolve_float_threshold_hours(),
        cg_coefficients=dict(
            read_cg_coefficients(register_path, caller_module=_CALLER_MODULE)),
    )
    # DAYRATE-02 (F-9): this arm left programme_days at 0, which
    # per_day_curve.compute_per_day_curve reads as "disable the curve". Same
    # strawman-blindness as the day rate, one field over.
    programme_days = resolve_programme_days(cfg)

    iterations = 100_000
    reporting_p_level = 80
    if cfg.get("iterations"):
        iterations = int(cfg["iterations"])
    if cfg.get("p_level_reporting"):
        reporting_p_level = int(cfg["p_level_reporting"])

    if iterations_override is not None:
        iterations = int(iterations_override)

    # SR19 §6.2: methodology_defaults is REQUIRED on IntegratedConfig.
    # Stage 3 config constructed here reads from the register workbook
    # (the reference register) via the shared reader.
    from src.sra.methodology_defaults_reader import read_methodology_defaults
    methodology_defaults = read_methodology_defaults(
        binding_cfg.register_path,
        caller_module="src/integrated/integrated_simulation_stage3.py",
    )
    int_cfg = IntegratedConfig(
        register_path=binding_cfg.register_path,
        **read_calibration_tolerances(binding_cfg.register_path, caller_module="src/integrated/integrated_simulation_stage3.py"),  # RS-D-2
        p6_path=binding_cfg.xer_path,
        strawman_path=binding_cfg.strawman_path,
        methodology_defaults=methodology_defaults,
        iterations=iterations,
        random_seed=seed_override,
        day_rate=day_rate,
        reporting_p_level=reporting_p_level,
        programme_days=programme_days,
        cg_correlation_coefficients=dict(binding_cfg.cg_coefficients),
    )
    # SR15 — Stage 3 path defaults ``apply_mode_multipliers=False``.
    # Per Decision 2 (Option A) the Stage 3 full-CPM engine drops Mode
    # multipliers; the CPM kernel handles float consumption directly,
    # so layering the Stage 2.5-era practitioner-judgement multiplier on
    # top would double-count. Stage 2.5 path (``IntegratedConfig`` +
    # ``run_integrated_simulation``) is unaffected — it does not consult
    # this flag. ``Stage3BindingConfig.apply_mode_multipliers`` is
    # preserved as the per-run record of the methodology call;
    # the Stage 3 integrated path keeps the brief's locked default of
    # ``False`` here regardless of the binding's value.
    sched_cfg = ScheduleMCConfig(
        n_iter=iterations,
        seed=seed_override,  # None stays None: the run refuses it by name (SEEDZERO-01)
        apply_mode_multipliers=False,
        mode_multipliers=methodology_defaults.mode_multipliers,  # RS-D-3b
    )
    return IntegratedConfigStage3(
        integrated_config=int_cfg,
        schedule_mc_config=sched_cfg,
        binding_config=binding_cfg,
    )


# ----------------------------------------------------------------------------
# Variant label resolution (for sibling filename suffixing)
# ----------------------------------------------------------------------------

def _resolve_variant_label(strawman_path: Path) -> str:
    """Derive a variant label from the strawman filename.

    Mirrors :func:`src.final.executive_summary.detect_strawman_variant`
    semantics: returns "Hybrid" for the canonical Hybrid strawman,
    "Series" if the path contains "Series", etc. The default for the
    canonical DPReview strawman variant is "Hybrid" (the production
    Mode classification under V8).
    """
    name = Path(strawman_path).name.lower()
    if "series" in name:
        return "Series"
    if "hybrid" in name:
        return "Hybrid"
    if "dpreview" in name or "dp_review" in name or "wip" in name:
        # The canonical DPReview strawman is the Hybrid variant
        # under V8 (the DP Review baseline carries the Hybrid Mode mix
        # after Beta-19's strawman build).
        return "Hybrid"
    return "Hybrid"


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------

def cost_arm_fire_mask(
    cost_result: dict[str, Any],
    schedule_risk_ids: tuple[str, ...] | list[str],
) -> np.ndarray:
    """The cost arm's fire record, projected onto the schedule arm's driver order.

    SPEC R-10 (METHFIRE-01): a risk is one event, so the schedule replay fires a driver exactly
    when the cost arm fired its risk - the cost arm's final record, after chain resamples. A
    driver with no cost-arm risk has no fire decision to share and is refused by name, rather
    than left to draw one of its own.
    """
    fired = np.asarray(cost_result["fired_array"], dtype=bool)
    index = {str(rid): i for i, rid in enumerate(cost_result["risk_ids_all"])}
    missing = [rid for rid in schedule_risk_ids if str(rid) not in index]
    if missing:
        raise ValueError(
            f"schedule drivers {missing[:5]}{'...' if len(missing) > 5 else ''} have no risk in "
            f"the cost arm, so there is no fire decision to share (SPEC R-10). A Time Impact = Yes "
            f"risk must be priced by the cost arm."
        )
    columns = [index[str(rid)] for rid in schedule_risk_ids]
    return np.ascontiguousarray(fired[:, columns]).reshape(fired.shape[0], len(columns))


def run_integrated_simulation_stage3(
    config: IntegratedConfigStage3,
    *,
    risks: list[Any] | None = None,
    risk_scope_df: pd.DataFrame | None = None,
    schedule_graph: Any | None = None,
    risk_drivers: dict[str, Any] | None = None,
    xer_tables: dict[str, pd.DataFrame] | None = None,
    severity_uniforms_by_risk_id: dict[str, np.ndarray] | None = None,
    variant_label: str | None = None,
) -> Stage3IntegratedResult:
    """Run one Stage 3 Beta integrated MC iteration set.

    Sequence:

    1. Load inputs (risks, .xer tables, schedule graph, drivers,
       risk_scope_df) — using the binding-supplied defaults when
       caller-supplied values are None. Tests pass synthetic inputs to
       bypass file I/O.
    2. Build the joint severity-uniform dict via
       :func:`build_joint_severity_uniforms`. The dict order is the
       cost engine's ``risk_ids_all`` order; same dict is consumed by
       both arms.
    3. Run the cost arm via :func:`run_integrated_simulation` with
       ``precomputed_severity_uniforms`` populated.
    4. Run the schedule arm via :func:`run_schedule_mc` consuming the
       column-projected severity-uniform matrix in
       ``risk_drivers.keys()`` order.
    5. Project the schedule arm's ``project_finish_days`` against the
       deterministic baseline to produce a ``schedule_days_array``
       (per-iteration delay relative to the deterministic CP) suitable
       for direct consumption by the composer's component-breakdown
       arithmetic.
    6. Return a :class:`Stage3IntegratedResult`.

    Parameters
    ----------
    config : IntegratedConfigStage3
        The merged configuration object. Iteration count parity between
        cost and schedule arms is asserted in
        :meth:`IntegratedConfigStage3.__post_init__`.
    risks : list | None
        Optional pre-loaded ``list[RiskInput]`` from
        :func:`read_risks_v5`. When None, loaded from
        ``config.binding_config.register_path``.
    risk_scope_df : DataFrame | None
        Optional pre-loaded Risk_Scope DataFrame. When None, loaded
        from ``config.binding_config.strawman_path``.
    schedule_graph : ScheduleGraph | None
        Optional pre-built schedule graph. When None, built from the
        parsed .xer.
    risk_drivers : dict | None
        Pre-built risk drivers dict. Required since REFRETIRE-01: a call that omits it is
        refused rather than routed to a retired builder.
    xer_tables : dict | None
        Optional pre-parsed XER tables. When None, parsed from
        ``config.binding_config.xer_path``.
    severity_uniforms_by_risk_id : dict | None
        Optional pre-built severity-uniform dict. When None, built via
        :func:`build_joint_severity_uniforms` on
        :func:`src.rng_streams.severity_generator` of
        ``config.integrated_config.random_seed``.
        Used by tests to inject a controlled uniform matrix.
    variant_label : str | None
        Optional override for the variant label used in sibling
        filename suffixing. When None, derived from the strawman path.

    Returns
    -------
    Stage3IntegratedResult
        Frozen container with both arms' results.

    Raises
    ------
    ValueError
        If iteration counts mismatch (caught at config construction
        time, but defence-in-depth re-check here).
    """
    int_cfg = config.integrated_config
    sched_cfg = config.schedule_mc_config
    bind_cfg = config.binding_config

    n_iter = int(int_cfg.iterations)
    seed = require_seed(
        int_cfg.random_seed if int_cfg.random_seed is not None else sched_cfg.seed,
        where="src.integrated.integrated_simulation_stage3.run_integrated_simulation_stage3",
    )

    if int_cfg.iterations != sched_cfg.n_iter:
        raise ValueError(
            f"iteration count mismatch: integrated={int_cfg.iterations}, "
            f"schedule={sched_cfg.n_iter}"
        )

    # ----- Inputs --------------------------------------------------------
    if risks is None:
        risks = read_risks_v5(bind_cfg.register_path)
    if xer_tables is None:
        xer_tables = parse_xer(bind_cfg.xer_path)
    if schedule_graph is None:
        schedule_graph = build_schedule_graph(xer_tables)
    if risk_drivers is None:
        # REFRETIRE-01 (D-3): this fell through to a pattern-catalogue driver builder that
        # belonged to one project's binding, and retired with it. Every in-tree caller passes drivers - the
        # deliverable and both showcases build them from the strawman's Time=Yes rows through
        # build_stage3_rules_from_scope. A caller that passes none is refused, not routed.
        raise ValueError(
            "run_integrated_simulation_stage3: no risk_drivers supplied. The pattern-catalogue "
            "driver builder retired with its binding (REFRETIRE-01); build them from "
            "the strawman with src.integrated.stage3_config.build_stage3_rules_from_scope and "
            "src.sra.cpm.auto_mapper.expand_auto_rules, and pass risk_drivers."
        )
    if risk_scope_df is None:
        risk_scope_df = strawman_reader.read_risk_scope(
            bind_cfg.strawman_path,
        )

    # ----- Joint severity uniforms ---------------------------------------
    risk_ids_all = tuple(str(getattr(r, "risk_id")) for r in risks)
    # Severity on its own stream, not the fire draw's (src.rng_streams, RNGSTREAM-01).
    if severity_uniforms_by_risk_id is None:
        severity_uniforms_by_risk_id = build_joint_severity_uniforms(
            risk_ids=risk_ids_all,
            n_iter=n_iter,
            rng=severity_generator(seed),
            precision=sched_cfg.precision,
        )
    else:
        # Validate every risk_id is present; the cost arm tolerates
        # missing entries (falls back to its own rng.random draw) but
        # for the Stage 3 integrated engine the joint contract is
        # strict: every risk must be in the dict.
        missing = [rid for rid in risk_ids_all if rid not in severity_uniforms_by_risk_id]
        if missing:
            raise ValueError(
                "severity_uniforms_by_risk_id is missing entries for: "
                f"{missing[:5]}{'...' if len(missing) > 5 else ''}"
            )
    master_rng = kernel_generator(seed)

    # ----- Cost arm ------------------------------------------------------
    # Re-uses Stage 2.5 integrated engine. The cost arm output is
    # bit-identical to the Stage 2.5 integrated engine invoked with the
    # same severity uniforms — the parity test locks this.
    cost_result = run_integrated_simulation(
        config=int_cfg,
        risks=risks,
        risk_scope_df=risk_scope_df,
        precomputed_severity_uniforms=severity_uniforms_by_risk_id,
    )

    # ----- Schedule arm — Stage 3 Beta CPM-replay -----------------------
    schedule_risk_ids = tuple(risk_drivers.keys())
    schedule_severity_uniforms = np.stack(
        [severity_uniforms_by_risk_id[rid] for rid in schedule_risk_ids],
        axis=1,
    )
    schedule_result = run_schedule_mc(
        graph=schedule_graph,
        risk_drivers=risk_drivers,
        config=sched_cfg,
        severity_uniforms=schedule_severity_uniforms,
        rng=master_rng,
        criticality_measurement_mode=config.criticality_measurement_mode,
        fire_mask=cost_arm_fire_mask(cost_result, schedule_risk_ids),
    )

    # ----- Per-iteration delay (project finish days minus deterministic
    # baseline) -----------------------------------------------------------
    # The composer's component-breakdown arithmetic expects a
    # "schedule_days_array" carrying per-iteration delay in working
    # days (i.e. days BEYOND the deterministic baseline). Stage 2.5's
    # integrated engine emits this directly. Stage 3 Beta's
    # run_schedule_mc returns absolute project-finish days, so we
    # subtract the deterministic baseline here.
    project_finish_days = np.asarray(schedule_result.project_finish_days)
    # Deterministic baseline = the project finish when no risk fires: the kernel's own
    # zero-risk forward pass (STAGE3HEADLINE-01 D-7, 10/09/2026). Until then this took
    # ``min(project_finish_days)`` as a proxy, which equals the pass only when some
    # iteration fires no risk; on a project whose drivers fire in every iteration the proxy
    # overstates the baseline and understates every delay by a constant. Measured on the
    # road fixture at 2,000 iterations the two were identical; the period engine has used the
    # pass since AM02, so the two surfaces now subtract the same number by construction.
    from src.sra.cpm.deterministic import deterministic_finish_hours
    hours_per_day = float(schedule_graph.project_default_calendar.working_hours_per_day)
    # Precision must match the stochastic batch above (sched_cfg.precision, recorded in
    # config_summary["schedule_mc"]["precision"] below) so the baseline and the batch it is
    # subtracted from are computed at the same precision (review re-review: precision coupling).
    deterministic_baseline_days = (
        deterministic_finish_hours(schedule_graph, precision=sched_cfg.precision) / hours_per_day
    )
    schedule_days_array = (
        project_finish_days.astype(np.float64) - deterministic_baseline_days
    )
    earliest = float(schedule_days_array.min())
    # 1e-4 relative, not 1e-6: at float32 precision (~7 significant digits) a baseline of a
    # few hundred to a few thousand hours carries ~8 float32 ulps of rounding noise at 1e-6
    # relative, which a rounding-driven inversion can exceed while a real inversion (kernel
    # and baseline genuinely disagree) is orders of magnitude larger either way. Widened so
    # rounding inversions clamp below and real inversions still raise.
    if earliest < -1e-4 * max(1.0, abs(deterministic_baseline_days)):
        raise ValueError(
            f"a Stage 3 iteration finished {abs(earliest):.3f} days EARLIER than the zero-risk "
            f"pass ({deterministic_baseline_days:.3f} d). Delay days would be negative; the "
            f"kernel and the baseline disagree - stop and report, do not clamp.")
    schedule_days_array = np.maximum(schedule_days_array, 0.0)

    # ----- Variant label -------------------------------------------------
    if variant_label is None:
        variant_label = _resolve_variant_label(bind_cfg.strawman_path)

    # Resolved once, so the audit stamp below cannot be handed a None that the
    # dict entry above already refused - two reads of the same optional field
    # is how they drift apart.
    resolved_day_rate = require_day_rate(
        int_cfg.day_rate, caller="run_integrated_simulation_stage3",
    )
    config_summary: dict[str, Any] = {
        "iterations": n_iter,
        "seed": seed,
        "day_rate": resolved_day_rate,
        # DAYRATE-01: an explicit zero day rate is permitted, and is marked
        # here because the warning at resolution time scrolls past and a
        # zero-rate run looks exactly like a correct one. This dict is in
        # memory only - nothing persists config_summary - so the durable record
        # is the run's metadata.json, which carries day_rate at three paths.
        # Empty for every real rate, so no existing artefact gains a key.
        **day_rate_audit_fields(resolved_day_rate),
        "criticality_measurement_mode": config.criticality_measurement_mode,
        "binding": {
            "register_path": str(bind_cfg.register_path),
            "xer_path": str(bind_cfg.xer_path),
            "strawman_path": str(bind_cfg.strawman_path),
            "float_threshold_hours": bind_cfg.float_threshold_hours,
            "default_injection_method": resolve_default_injection_method(bind_cfg),  # RS-D-6
            "populate_modes_from_strawman": bind_cfg.populate_modes_from_strawman,
        },
        "schedule_mc": {
            "n_iter": sched_cfg.n_iter,
            "batch_size": sched_cfg.batch_size,
            "seed": sched_cfg.seed,
            "precision": sched_cfg.precision,
            "mode": sched_cfg.mode,
            "apply_mode_multipliers": sched_cfg.apply_mode_multipliers,
            "mode_multipliers": dict(sched_cfg.mode_multipliers),  # RS-D-3b
        },
        "deterministic_baseline_days": deterministic_baseline_days,
        "variant_label": variant_label,
    }

    logger.info(
        "run_integrated_simulation_stage3: complete; n_iter=%d, "
        "cost_mean=$%.2fM, schedule_mean_days=%.2f (baseline=%.2f), "
        "variant=%s",
        n_iter,
        float(np.mean(cost_result["cost_dollars_array"])) / 1e6,
        float(np.mean(schedule_days_array)),
        deterministic_baseline_days,
        variant_label,
    )

    return Stage3IntegratedResult(
        cost_result=cost_result,
        schedule_result=schedule_result,
        schedule_days_array=schedule_days_array,
        severity_uniforms_by_risk_id=severity_uniforms_by_risk_id,
        risk_drivers=risk_drivers,
        schedule_graph=schedule_graph,
        xer_tables=xer_tables,
        auto_mapper_audit_path=None,  # populated by binding when present
        beta_flag=bool(schedule_result.beta_flag),
        iterations=n_iter,
        seed_used=seed,
        variant_label=variant_label,
        config_summary=config_summary,
    )


# ----------------------------------------------------------------------------
# Composer adapter
# ----------------------------------------------------------------------------

def adapt_to_integrated_results_shape(
    result: Stage3IntegratedResult,
) -> dict[str, Any]:
    """Project a :class:`Stage3IntegratedResult` into the dict shape the
    Stage 2.5 composer's ``_compute_component_breakdown`` expects.

    The composer reads ``cost_dollars_array`` (per-iteration cost in $)
    and ``schedule_days_array`` (per-iteration schedule delay in
    working days) and dollarises the schedule at the supplied day-rate
    constant. Returning a dict with the same keys means the composer
    can be invoked unchanged — the only divergence is that the
    schedule array is sourced from the Stage 3 Beta CPM-replay rather
    than Stage 2.5's risk-driver PERT-on-days.

    Returns
    -------
    dict
        Keys: ``cost_dollars_array``, ``schedule_days_array``,
        ``per_risk_cost_array``, ``risk_ids_all``, ``iterations``,
        ``seed_used``, and the Stage 3 metadata keys
        (``stage3_beta_p80_schedule_days``, ``beta_flag``,
        ``auto_mapper_audit_path``).
    """
    cost = result.cost_result
    return {
        "cost_dollars_array": np.asarray(cost["cost_dollars_array"]),
        "schedule_days_array": np.asarray(result.schedule_days_array),
        "per_risk_cost_array": np.asarray(cost["per_risk_cost_array"]),
        "per_risk_schedule_array": np.asarray(
            cost.get("per_risk_schedule_array", np.zeros((result.iterations, 0)))
        ),
        "risk_ids_all": list(cost.get("risk_ids_all", [])),
        "risk_ids_dual": list(cost.get("risk_ids_dual", [])),
        # REPORT01 F-B, revised by METHFIRE-01. One fire decision per risk per iteration:
        # the schedule arm fires on the cost arm's draw (SPEC R-10), so for every
        # schedule risk the two records agree column for column. Both are kept because
        # they are indexed differently - `risk_ids_all` and `schedule_fired_risk_ids`.
        "fired_array": np.asarray(
            cost.get("fired_array", np.zeros((result.iterations, 0), dtype=bool))
        ),
        "schedule_fired_array": np.asarray(result.schedule_result.risk_fired_array),
        "schedule_fired_risk_ids": list(result.schedule_result.risk_ids),
        "iterations": int(result.iterations),
        "seed_used": int(result.seed_used),
        "beta_flag": bool(result.beta_flag),
        "auto_mapper_audit_path": result.auto_mapper_audit_path,
        "variant_label": result.variant_label,
    }
