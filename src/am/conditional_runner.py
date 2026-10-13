"""Conditional Monte Carlo orchestrator for AM02.

Wraps the engagement's Stage 3 CPM-replay engine (``run_schedule_mc``)
with the AM-specific pinning rules from the status-period workbook:

- ``Fired`` risks: removed from the MC; realised impact (the risk's
  ``ml_pert`` value) is added to the deterministic baseline uplift.
- ``Closed`` risks: probability forced to 0.0.
- ``Open`` / ``Actioned`` / ``Monitor`` risks: use
  ``Probability_override`` (if non-blank) else the register value
  already on the driver.
- Mode: AM07 retired the mode lever. The AM is Stage 3 only, so
  ``apply_mode_multipliers`` is off on the engagement path and there is
  no ``Mode_override`` handling; the driver's baseline mode is recorded
  in the audit unchanged.
- Milestone progress: when a milestone with non-blank WBS code has
  ``Status="Complete"``, the risks whose ``affected_activity_ids``
  intersect the milestone's WBS-tagged activities are removed from
  the MC. In template state with no milestone WBS codes populated,
  this is a no-op.
- ``Status="Completed"`` mitigations: the linked risk is removed
  from the MC (the mitigation is assumed to have neutralised that
  risk's residual exposure for the current period).

The wrapper preserves the engine's reproducibility invariants:

- Severity uniforms are drawn against the FULL register risk set
  (the deliverable's joint-sampling pattern).
  Only the schedule-arm projection picks the dual-coded subset that
  survives pinning.
- Every generator comes from :mod:`src.rng_streams` on the run seed:
  severity on its own stream, the fire draw reproduced on the cost
  arm's, the kernel's batches spawned from the seed (RNGSTREAM-01).
  Re-running the same workbook + inputs at the same seed produces a
  bit-identical :class:`ScheduleMCResult`.

The wrapper does NOT modify any engine module. It re-uses the public Stage 3 helpers
(``build_drivers_for_project``, ``build_joint_severity_uniforms``) in the sequence the
deliverable's Stage 3 route does, with one inserted step: the AM pinning between driver
construction and severity-uniform projection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np


from src.rng_streams import (  # noqa: E402
    fire_generator, kernel_generator, require_seed, severity_generator,
)
from src.integrated.stage3_inputs import (  # noqa: E402
    Stage3BindingConfig,
    build_joint_severity_uniforms,
    resolve_float_threshold_hours,
)
from src.sra.methodology_defaults_reader import read_mode_multipliers
from src.sra.cpm.cpm_simulation import (  # noqa: E402
    ScheduleMCConfig,
    ScheduleMCResult,
    run_schedule_mc,
)
from src.sra.cpm.graph_builder import build_schedule_graph  # noqa: E402
from src.sra.cpm.risk_driver_schema import RiskDriver  # noqa: E402
from src.sra.cpm.xer_reader import parse_xer  # noqa: E402
from src.v5_register_reader import read_risks_v5  # noqa: E402

from src.am.project_binding import (
    activate_project,
    build_drivers_for_project,
)
from src.am.workbook_reader import WorkbookData


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inputs and outputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConditionalRunInputs:
    """All inputs to a conditional Stage 3 MC run."""
    workbook_data: WorkbookData
    register_path: Path
    xer_path: Path
    strawman_path: Path
    n_iter: int = 100_000
    seed: int | None = None   # required: refused by name when missing (SEEDZERO-01)
    criticality_measurement_mode: str = "both"
    project: str | None = None
    # WIND-01: explicit Mode-multiplier override. ``None`` (default) means
    # the pure-MC (Mode-independent, apply=False) basis for every project;
    # set ``True`` only for the deferred WIND-01b sensitivity side-analysis
    # ("what the Mode classifications would have done"). Never rely on an
    # implicit default in either direction.
    apply_mode_multipliers: bool | None = None


@dataclass(frozen=True)
class PinnedRiskState:
    """Audit record of how one risk was treated by the AM pinning step.

    Surfaced in :class:`ConditionalRunResult` so the JSON ``audit``
    block can show, per risk, what the wrapper did and why.
    """
    risk_id: str
    action: str  # see ACTION_* constants below
    original_probability: float
    new_probability: float | None  # None when risk was removed
    original_mode: str
    new_mode: str | None
    realised_impact_days: float | None = None
    notes: str | None = None


# Action enum (string-typed for JSON friendliness).
# AM07: the mode-override actions are retired (the AM is Stage 3 only; modes
# no longer participate in pinning).
ACTION_KEPT_BASELINE = "kept_baseline"
ACTION_PROBABILITY_OVERRIDDEN = "probability_overridden"
ACTION_CLOSED_PROBABILITY_ZERO = "closed_probability_zero"
ACTION_FIRED_REMOVED = "fired_removed"
ACTION_MILESTONE_EXCLUDED = "milestone_excluded"
ACTION_MITIGATION_COMPLETED_REMOVED = "mitigation_completed_removed"


@dataclass(frozen=True)
class ConditionalRunResult:
    """Output of a conditional Stage 3 MC run."""
    schedule_result: ScheduleMCResult
    pinned_states: tuple[PinnedRiskState, ...]
    fired_baseline_uplift_days: float
    excluded_risk_ids: tuple[str, ...]
    config_summary: dict[str, Any] = field(default_factory=dict)
    #: Stage 7 part B, numerics-review B1. The per-risk severity uniforms this run drew,
    #: keyed by risk_id over the FULL register. Exposed so a cost arm can consume the SAME
    #: draws, which is invariant 1 of `integrated_simulation_stage3`: a dual-coded risk
    #: shares ONE severity uniform per iteration across cost and schedule. They were already
    #: built here for exactly that contract (see the comment at the build site); before this
    #: they simply had no way out of the function, and the first integrated arm drew its own.
    severity_uniforms_by_risk_id: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helper — risk-id resolution by milestone WBS
# ---------------------------------------------------------------------------

def _activity_ids_for_wbs(wbs_code: str, xer_tables: dict[str, Any]) -> set[str]:
    """Return the set of TASK activity IDs whose ``wbs_id`` matches ``wbs_code``.

    The .xer ``PROJWBS`` table maps internal ``wbs_id`` numbers to
    ``wbs_short_name`` codes. The ``TASK`` table's ``wbs_id`` column
    references back to ``PROJWBS.wbs_id``. So a milestone with WBS
    code ``"50.E.1"`` (for example) needs first to find the matching
    PROJWBS row, then collect TASKs whose ``wbs_id`` equals that
    row's wbs_id.

    In the current template state, milestone WBS codes are blank, so
    this function is exercised mainly by future periods. It's safe to
    call with an unknown wbs_code (returns empty set).
    """
    if not wbs_code:
        return set()

    projwbs = xer_tables.get("PROJWBS")
    task = xer_tables.get("TASK")
    if projwbs is None or task is None:
        return set()

    # Match wbs_short_name OR wbs_name (whichever the analyst entered).
    matching = projwbs[
        (projwbs.get("wbs_short_name", "") == wbs_code)
        | (projwbs.get("wbs_name", "") == wbs_code)
    ]
    if matching.empty:
        return set()
    wbs_ids = set(matching["wbs_id"].astype(str))
    matching_tasks = task[task["wbs_id"].astype(str).isin(wbs_ids)]
    return set(matching_tasks["task_code"].astype(str))


# ---------------------------------------------------------------------------
# Pinning logic
# ---------------------------------------------------------------------------

def _build_pinning_decisions(
    workbook_data: WorkbookData,
    risk_drivers: dict[str, RiskDriver],
    xer_tables: dict[str, Any],
) -> tuple[dict[str, RiskDriver], list[PinnedRiskState], float]:
    """Apply AM pinning rules and return:

    1. The modified ``risk_drivers`` dict (some entries removed, others
       with overridden ``probability`` / ``mode`` via ``dataclasses.replace``)
    2. The list of :class:`PinnedRiskState` audit records, one per
       input risk
    3. The Fired-risk realised-impact uplift in working days (added to
       the deterministic baseline downstream)

    Mutation discipline: this function does NOT mutate its argument
    dict. It builds and returns a new dict with the same risk_id
    ordering as the input (minus removed entries).
    """
    # Build maps from the workbook reader output for fast lookup.
    risk_status_by_id = {
        r["risk_id"]: r for r in workbook_data.risk_status
    }
    completed_milestone_wbs: list[str] = [
        m["wbs_code"]
        for m in workbook_data.milestones
        if m.get("status") == "Complete" and m.get("wbs_code")
    ]
    completed_mitigation_risk_ids: set[str] = {
        m["risk_id"]
        for m in workbook_data.mitigations
        if m.get("status") == "Completed" and m.get("risk_id")
    }

    # Pre-compute activities-excluded-by-completed-milestones (typically
    # empty in template state).
    excluded_activity_ids: set[str] = set()
    for wbs in completed_milestone_wbs:
        excluded_activity_ids |= _activity_ids_for_wbs(wbs, xer_tables)
    if excluded_activity_ids:
        logger.info(
            "Milestone-progress exclusion: %d activities excluded via "
            "completed milestones (WBS: %s)",
            len(excluded_activity_ids),
            ", ".join(completed_milestone_wbs),
        )

    new_drivers: dict[str, RiskDriver] = {}
    pinned_states: list[PinnedRiskState] = []
    fired_uplift_days = 0.0

    for risk_id, driver in risk_drivers.items():
        original_prob = float(driver.probability)
        original_mode = str(driver.mode)
        ws_row = risk_status_by_id.get(risk_id)

        # Branch 1: mitigation completed → remove
        if risk_id in completed_mitigation_risk_ids:
            pinned_states.append(PinnedRiskState(
                risk_id=risk_id,
                action=ACTION_MITIGATION_COMPLETED_REMOVED,
                original_probability=original_prob,
                new_probability=None,
                original_mode=original_mode,
                new_mode=None,
                notes="Linked mitigation Status=Completed; risk removed from MC",
            ))
            continue

        # Branch 2: any of driver's affected_activity_ids overlap with
        # excluded_activity_ids → milestone-excluded
        if excluded_activity_ids and set(driver.affected_activity_ids) & excluded_activity_ids:
            pinned_states.append(PinnedRiskState(
                risk_id=risk_id,
                action=ACTION_MILESTONE_EXCLUDED,
                original_probability=original_prob,
                new_probability=None,
                original_mode=original_mode,
                new_mode=None,
                notes="Affected activities sit under a completed milestone",
            ))
            continue

        # Branch 3: workbook status branches (only if a status row exists
        # for this risk; risks present in the engine but absent from
        # AM_Period_Status are left untouched — kept_baseline action).
        status = ws_row.get("status_this_period") if ws_row else None

        if status == "Fired":
            # Realised impact proxy: ml_pert in working days.
            # (Workbook doesn't carry an actual-impact column; ml is the
            # best available estimate. Documented in close-out audit.)
            ml_days = float(getattr(driver, "ml_pert", 0.0) or 0.0)
            fired_uplift_days += ml_days
            pinned_states.append(PinnedRiskState(
                risk_id=risk_id,
                action=ACTION_FIRED_REMOVED,
                original_probability=original_prob,
                new_probability=None,
                original_mode=original_mode,
                new_mode=None,
                realised_impact_days=ml_days,
                notes="Status=Fired; removed from MC, ml_pert days added to "
                      "deterministic baseline uplift",
            ))
            continue

        if status == "Closed":
            # Force probability to 0; keep the driver so the shape of
            # the severity-uniform projection is unchanged. The
            # Bernoulli gates fire 0% of iterations.
            new_drivers[risk_id] = replace(driver, probability=0.0)
            pinned_states.append(PinnedRiskState(
                risk_id=risk_id,
                action=ACTION_CLOSED_PROBABILITY_ZERO,
                original_probability=original_prob,
                new_probability=0.0,
                original_mode=original_mode,
                new_mode=original_mode,
                notes="Status=Closed; probability forced to 0",
            ))
            continue

        # Branch 4: Open / Actioned / Monitor / blank → apply probability
        # override only. AM07: the mode-override lever is retired (the AM is
        # Stage 3 only; Stage 3 CPM-replay already models schedule propagation,
        # so a mode multiplier on top would double-count). Mode is no longer
        # read from the workbook or written to the driver; original_mode /
        # new_mode are recorded unchanged (record-only) for the audit shape.
        prob_override = ws_row.get("probability_override") if ws_row else None
        new_prob = (
            float(prob_override) if prob_override is not None else original_prob
        )
        prob_changed = prob_override is not None

        action = (
            ACTION_PROBABILITY_OVERRIDDEN if prob_changed else ACTION_KEPT_BASELINE
        )

        if prob_changed:
            new_drivers[risk_id] = replace(driver, probability=new_prob)
        else:
            new_drivers[risk_id] = driver

        pinned_states.append(PinnedRiskState(
            risk_id=risk_id,
            action=action,
            original_probability=original_prob,
            new_probability=new_prob,
            original_mode=original_mode,
            new_mode=original_mode,  # record-only; AM is mode-less
            notes=f"Status={status!r}; {action}",
        ))

    return new_drivers, pinned_states, fired_uplift_days


# ---------------------------------------------------------------------------
# End-to-end orchestrator
# ---------------------------------------------------------------------------

def period_fire_mask(
    *,
    risks: list[Any],
    pinned_states: list[PinnedRiskState],
    schedule_risk_ids: tuple[str, ...],
    register_path: Path,
    n_iter: int,
    seed: int,
) -> np.ndarray:
    """The period cost arm's fire decisions, for the schedule drivers, without running the cost arm.

    SPEC R-10 (METHFIRE-01): one risk, one fire decision on both arms. The period route runs
    the schedule arm first and the cost arm (``run_integrated_period``) second, and the
    deliverable's cross-surface check runs this schedule arm alone, so the cost arm's draw is
    reproduced rather than read: :func:`src.qra_core.draw_fire_matrix` on a generator seeded as
    ``run_cost_layer`` seeds its own, over the risk set ``run_integrated_period`` prices (pinning
    applied the same way) and the register's CG coefficients.

    That draw is the cost arm's record **before chain resamples**. A register whose event chain
    targets a schedule driver would diverge from the cost arm on the resampled iterations, so it
    is refused rather than run on a draw that is only nearly shared.
    """
    from src.am.integrated_period import apply_pinning_to_risks
    from src.defaults import get_chain_risk_ids
    from src.qra_core import draw_fire_matrix
    from src.sra.methodology_defaults_reader import read_cg_coefficients

    chain = get_chain_risk_ids()
    targets = [chain.get("c1_target"), *(chain.get("c2_targets") or [])]
    chained = sorted({str(t) for t in targets if t} & set(schedule_risk_ids))
    if chained:
        raise ValueError(
            f"event-chain targets {chained} are schedule drivers. The period route reproduces the "
            f"cost arm's fire draw before chain resamples, so these risks would fire differently on "
            f"the two arms (SPEC R-10). No shipped project declares a chain; the one binding that does is retired by "
            f"REFRETIRE-01."
        )
    priced_risks, _ = apply_pinning_to_risks(risks, pinned_states)
    fired = draw_fire_matrix(
        n_iter, priced_risks,
        read_cg_coefficients(register_path, caller_module="src/am/conditional_runner.py"),
        fire_generator(seed),
    )
    index = {str(getattr(r, "risk_id")): i for i, r in enumerate(priced_risks)}
    missing = [rid for rid in schedule_risk_ids if rid not in index]
    if missing:
        raise ValueError(
            f"schedule drivers {missing[:5]}{'...' if len(missing) > 5 else ''} are not priced by "
            f"the period cost arm, so there is no fire decision to share (SPEC R-10)."
        )
    columns = [index[rid] for rid in schedule_risk_ids]
    return np.ascontiguousarray(fired[:, columns]).reshape(n_iter, len(columns))


def run_conditional_mc(inputs: ConditionalRunInputs) -> ConditionalRunResult:
    """Run the Stage 3 schedule MC under AM-pinned risk states.

    Replicates the deliverable's Stage 3 orchestration sequence
    (read register -> parse xer -> build graph -> build drivers ->
    build severity uniforms -> run_schedule_mc) with the AM pinning
    step inserted between driver construction and severity-uniform
    projection.

    The cost arm is NOT invoked — AM02 v1 is schedule-only. The joint-sampling
    contract is still honoured on both of its halves: severity uniforms are
    built over the full register, and the fire decisions are the cost arm's own
    draw, reproduced here from the same seed, pinned risk set and CG
    coefficients (:func:`period_fire_mask`, SPEC R-10, METHFIRE-01), so
    ``run_integrated_period`` prices exactly the risks this run fired.

    Returns
    -------
    ConditionalRunResult
        With ``schedule_result`` (Stage 3 ScheduleMCResult),
        ``pinned_states`` (one per input risk), ``fired_baseline_uplift_days``
        (added to the deterministic baseline by downstream consumers),
        and a ``config_summary`` dict for the audit block.
    """
    # Activate the active project BEFORE any register/strawman read so the
    # V5 reader resolves the right risk_id_prefix (the engagement 'R', wind 'WT').
    # There is no default project (QRAXL-01): inputs.project must name one.
    activate_project(inputs.project)

    binding_cfg = Stage3BindingConfig(
        register_path=inputs.register_path,
        xer_path=inputs.xer_path,
        strawman_path=inputs.strawman_path,
        # REFRETIRE-01: the active project's own threshold, not a field default carrying one
        # project's 480 hours onto every route. ``build_drivers_for_project`` re-reads it from
        # the binding for the generic build; this is the same number, named at construction.
        float_threshold_hours=resolve_float_threshold_hours(inputs.project or None),
    )
    # WIND-01: pure-MC (Mode-independent) basis for BOTH projects. Stage 3
    # CPM-replay already models schedule propagation directly, so a Mode
    # multiplier on top double-counts (the SR15 call). Pre-WIND-01 this was
    # scoped to the engagement only and the synthetic-wind cycle inherited the
    # binding default (True) -- meaning the wind showcase demonstrated an
    # OLDER basis than the engagement production work it is meant to showcase.
    # WIND-01 aligns them: apply_mode_multipliers is False for every project
    # unless an explicit inputs override says otherwise. The override is the
    # hook for the deferred WIND-01b sensitivity run (apply=True side-
    # analysis). Never rely on the ScheduleMCConfig / binding default.
    apply_mode_multipliers = (
        inputs.apply_mode_multipliers
        if inputs.apply_mode_multipliers is not None
        else False
    )
    seed = require_seed(inputs.seed, where="src.am.conditional_runner.run_conditional_mc")
    sched_cfg = ScheduleMCConfig(
        n_iter=inputs.n_iter,
        seed=seed,
        apply_mode_multipliers=apply_mode_multipliers,
        mode_multipliers=read_mode_multipliers(
            inputs.register_path, caller_module="src/am/conditional_runner.py"),  # RS-D-3b
    )

    # ----- Read inputs (mirrors the deliverable's Stage 3 route) -----
    risks = read_risks_v5(inputs.register_path)
    xer_tables = parse_xer(inputs.xer_path)
    schedule_graph = build_schedule_graph(xer_tables)
    risk_drivers = build_drivers_for_project(
        project=inputs.project,
        binding_cfg=binding_cfg,
        schedule_graph=schedule_graph,
        xer_tables=xer_tables,
        strawman_path=inputs.strawman_path,
    )

    # ----- AM pinning step -----
    pinned_drivers, pinned_states, fired_uplift_days = _build_pinning_decisions(
        workbook_data=inputs.workbook_data,
        risk_drivers=risk_drivers,
        xer_tables=xer_tables,
    )

    excluded_risk_ids = tuple(
        sorted(set(risk_drivers.keys()) - set(pinned_drivers.keys()))
    )

    if not pinned_drivers:
        raise ValueError(
            "All risks were excluded by AM pinning; the schedule MC has "
            "no Bernoulli sources to sample. This usually means every "
            "Time=Yes risk fired or closed in the current period. The "
            "deterministic baseline (with fired-risk uplift) IS the "
            "headline; no stochastic run is necessary."
        )

    # ----- Build severity uniforms against the FULL register (joint-sampling
    # contract preserved). The schedule arm projects onto the pinned subset.
    risk_ids_all = tuple(str(getattr(r, "risk_id")) for r in risks)
    master_rng = kernel_generator(seed)
    severity_uniforms_by_risk_id = build_joint_severity_uniforms(
        risk_ids=risk_ids_all,
        n_iter=sched_cfg.n_iter,
        rng=severity_generator(seed),
        precision=sched_cfg.precision,
    )
    schedule_risk_ids = tuple(pinned_drivers.keys())
    schedule_severity_uniforms = np.stack(
        [severity_uniforms_by_risk_id[rid] for rid in schedule_risk_ids],
        axis=1,
    )

    # ----- Run the schedule MC -----
    schedule_result = run_schedule_mc(
        graph=schedule_graph,
        risk_drivers=pinned_drivers,
        config=sched_cfg,
        severity_uniforms=schedule_severity_uniforms,
        rng=master_rng,
        criticality_measurement_mode=inputs.criticality_measurement_mode,
        fire_mask=period_fire_mask(
            risks=risks,
            pinned_states=pinned_states,
            schedule_risk_ids=schedule_risk_ids,
            register_path=inputs.register_path,
            n_iter=sched_cfg.n_iter,
            seed=seed,
        ),
    )

    config_summary: dict[str, Any] = {
        "n_iter": sched_cfg.n_iter,
        "seed": sched_cfg.seed,
        "criticality_measurement_mode": inputs.criticality_measurement_mode,
        "n_drivers_input": len(risk_drivers),
        "n_drivers_after_pinning": len(pinned_drivers),
        "n_excluded": len(excluded_risk_ids),
        "fired_baseline_uplift_days": fired_uplift_days,
    }

    return ConditionalRunResult(
        schedule_result=schedule_result,
        severity_uniforms_by_risk_id=severity_uniforms_by_risk_id,
        pinned_states=tuple(pinned_states),
        fired_baseline_uplift_days=fired_uplift_days,
        excluded_risk_ids=excluded_risk_ids,
        config_summary=config_summary,
    )
