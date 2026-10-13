"""Stage 7 part B (A-1): the integrated cost-plus-schedule result, for one period.

**What this closes.** SPEC §5 says the two rhythms "share one engine and one register contract",
and until now the period cycle carried the **schedule side only**: `conditional_runner` runs the
Stage 3 CPM-replay under AM pinning and returns a project-finish distribution, with no cost arm at
all. The whole of stages 3b/3c - the integrated result - did not reach the dashboard.

**One shared construction, which is the property A-1 actually asks for.** Every methodology value
here comes from :func:`src.integrated.stage3_config.build_stage3_config`, the same call
`src/final/deliverable.py` makes. Nothing in this module carries a code default for a number:
the day rate, the cost view, the CG coefficients and the iteration count are the register's. Two
constructions that must agree is the shape that drifts (the A-5 lesson), so there is one.

**The cost arm is AM-pinned. Director's ruling, 05/09/2026.** The schedule arm is conditioned on
the period's risk statuses - `conditional_runner._apply_pinning` removes risks Closed this period
and overrides the probability of those Actioned. The cost arm gets the *same* conditioning here,
so a risk closed this period contributes no cost and an actioned one costs at its overridden
probability. The alternative - period-aware on schedule, period-blind on cost - would put two
different questions in one headline's two halves on a client-facing page.

**The one derivation that deliberately differs from the deliverable's, and why.** The integrated
array is ``cost + delay_days * day_rate``, and *delay* means days beyond a deterministic baseline.
`integrated_simulation_stage3` derives that baseline as ``min(project_finish_days)`` and its own
comment calls it a proxy. The period engine does not need a proxy: it already computes a real
zero-risk forward pass (`run_period._deterministic_finish_hours`) and **already publishes delay
against it** in the period JSON's `headline` block. Using the proxy here would make the integrated
block and the headline block report different delays for the same run *in the same document*.
That is an internal-consistency requirement rather than a methodology preference, so the real
baseline is used and the difference is recorded here rather than left for a reader to discover.
If exact parity with the deliverable's derivation is wanted instead, it is a one-line change.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import numpy as np

# STAGE3HEADLINE-01 P2: one derivation of the integrated total, shared with the
# deliverable's headline, from the layer below both.
from src.integrated.integrated_dollars import integrated_dollars_array

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PinningEffect:
    """What the period's pinning did to the cost risk set, for the audit block."""

    n_priced: int
    n_removed: int
    n_reprobabilised: int
    n_closed: int
    removed_risk_ids: tuple[str, ...]
    reprobabilised_risk_ids: tuple[str, ...]
    closed_risk_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntegratedPeriodResult:
    """One period's integrated cost-plus-schedule distribution."""

    cost_dollars_array: np.ndarray
    schedule_days_array: np.ndarray
    integrated_dollars_array: np.ndarray
    day_rate: float
    deterministic_baseline_days: float
    iterations: int
    pinning: PinningEffect


#: Pinning actions that REMOVE a risk from the schedule arm. `conditional_runner` records these
#: with ``new_probability = None``; the cost arm drops the same risks.
_REMOVING_ACTIONS = frozenset({
    "fired_removed", "milestone_excluded", "mitigation_completed_removed",
})
#: The action that carries a period-stated probability for the risk. `conditional_runner` sets
#: ``new_probability`` straight from the workbook's ``probability_override``, so it is the
#: PERIOD's statement about the risk and applies to either arm.
_OVERRIDE_ACTION = "probability_overridden"
#: Closed: the schedule arm forces probability to zero rather than removing the driver, so the
#: audit can still show the risk. The cost arm does the same, and reports it as closed rather
#: than as an override.
_CLOSED_ACTION = "closed_probability_zero"


def apply_pinning_to_risks(
    risks: Sequence[Any], pinned_states: Sequence[Any]
) -> tuple[list[Any], PinningEffect]:
    """Condition the cost risk set by the period, keyed on the pinning ACTION.

    **Keyed on `action`, never on comparing `new_probability` with `risk.probability`** - which
    is what the first version of this function did, and it was wrong. At the time those were two
    different fields - `RiskDriver.probability` read `Probability (Time)` and `RiskInput.probability`
    read `Probability` - so comparing them re-priced every cost risk at its time probability on any
    register where the two columns differed, silently, reported on the dashboard as
    "re-probabilised". Found by the part B numerics review (B2). SPEC R-10 (METHFIRE-01) has since
    made them one value, but the action is still the right key: it says what the period did.

    The action tells you what the PERIOD did, which is the thing that transfers between arms:

    * a removing action drops the risk from cost as it dropped it from schedule;
    * ``closed_probability_zero`` zeroes it, and is reported as closed;
    * ``probability_overridden`` carries the workbook's own ``probability_override`` - the
      period's statement about the risk, not a time-arm quantity - so it applies to cost;
    * ``kept_baseline`` changes nothing, which is the case the value comparison got wrong.

    A risk with no state at all is not in the schedule arm's driver set. It was never *excluded*
    by the period, it was simply never a schedule driver, so it prices unchanged - dropping it
    would silently narrow the cost marginal.

    Does not mutate its arguments, and preserves input order for surviving risks: the cost
    engine's per-risk arrays are positional, so a reordering would re-label every one of them.
    """
    state_by_id = {s.risk_id: s for s in pinned_states}

    kept: list[Any] = []
    removed: list[str] = []
    reprobabilised: list[str] = []
    closed: list[str] = []

    for risk in risks:
        state = state_by_id.get(risk.risk_id)
        if state is None:
            kept.append(risk)
            continue

        action = getattr(state, "action", None)
        if action in _REMOVING_ACTIONS:
            removed.append(risk.risk_id)
        elif action == _CLOSED_ACTION:
            kept.append(replace(risk, probability=0.0))
            closed.append(risk.risk_id)
        elif action == _OVERRIDE_ACTION and state.new_probability is not None:
            kept.append(replace(risk, probability=float(state.new_probability)))
            reprobabilised.append(risk.risk_id)
        elif state.new_probability is None:
            # An unrecognised action that nonetheless removed the driver. Follow the schedule
            # arm rather than guess: a new removing action added upstream must not silently
            # keep pricing on the cost side.
            removed.append(risk.risk_id)
        else:
            kept.append(risk)

    return kept, PinningEffect(
        n_priced=len(kept),
        n_removed=len(removed),
        n_reprobabilised=len(reprobabilised),
        n_closed=len(closed),
        removed_risk_ids=tuple(removed),
        reprobabilised_risk_ids=tuple(reprobabilised),
        closed_risk_ids=tuple(closed),
    )


class IntegratedUnavailable(Exception):
    """The integrated arm cannot run on this register, and the period is still valid without it.

    Distinguished from every other failure on purpose. The integrated block is OPTIONAL in
    contract 1.4 (§5.2 decision C2), so a register that cannot supply what the arm needs - a day
    rate, above all: `require_day_rate` refuses to invent one, by the 31/08 ruling that every
    hardcoded number belongs to some other project - must still produce a period JSON with its
    schedule side intact. Failing the whole cycle instead would mean an ADDITIVE feature broke
    every register that lacks a rate, which is a regression dressed as rigour.

    It is not silent: `run_period` records the reason in the audit block and logs at WARNING, so
    a missing integrated result is visible in the artefact rather than merely absent. An engine
    bug inside the arm is NOT this - it propagates.
    """


def run_integrated_period(
    *,
    register_path: Path,
    xer_path: Path,
    strawman_path: Path,
    project_finish_days: np.ndarray,
    deterministic_finish_days: float,
    pinned_states: Sequence[Any],
    severity_uniforms_by_risk_id: dict[str, Any],
    iterations: int,
    seed: int,
    project: str | None = None,
) -> IntegratedPeriodResult:
    """Price the period's pinned risk set and combine it with the period's own delay days.

    ``project_finish_days`` is the conditional run's per-iteration finish, already AM-pinned;
    ``deterministic_finish_days`` is the period engine's zero-risk forward pass. The delay array
    is their difference, which is the same quantity the period JSON's headline block reports.

    ``severity_uniforms_by_risk_id`` are **the schedule run's own draws**, threaded through so the
    cost arm consumes them rather than drawing its own - see the joint-sampling note below.
    """
    from src.integrated.integrated_simulation import run_integrated_simulation
    from src.integrated.run_config_contract import RunConfigError, require_day_rate
    from src.integrated.stage3_config import build_stage3_config
    from src.sra.methodology_defaults_reader import MethodologyDefaultsError
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    # W1 from the part B review: build_stage3_config itself raises RunConfigError when the
    # register supplies no day rate - BEFORE any check inside this function could run. The first
    # version guarded on `config.day_rate is None` after the call, which could never be true, so
    # the whole IntegratedUnavailable path was unreachable and its tests asserted only the class
    # hierarchy. The construction belongs inside the try for the guard to exist at all.
    try:
        s3_cfg = build_stage3_config(
            register_path=register_path,
            xer_path=xer_path,
            strawman_path=strawman_path,
            iterations=iterations,
            seed=seed,
            project=project,
            caller_module="src/am/integrated_period.py",
        )
        config = s3_cfg.integrated_config
        day_rate = require_day_rate(config.day_rate, caller="src.am.integrated_period")
    except (RunConfigError, MethodologyDefaultsError) as exc:
        # BOTH, and the second was a regression the re-review caught. `build_stage3_config`
        # reads the reporting P-level, the CG coefficients and the calibration tolerances
        # as well as the day rate, raising `MethodologyDefaultsError` for those. None of
        # them was needed by the period engine before part B, so catching only
        # `RunConfigError` meant an ADDITIVE feature crashed the whole cycle for any
        # register that had a day rate but not, say, calibration tolerances - exactly the
        # regression `IntegratedUnavailable` exists to prevent, reintroduced through a
        # too-narrow catch.
        raise IntegratedUnavailable(
            f"the register does not supply what the integrated arm needs, so schedule days "
            f"cannot be dollarised and there is no integrated result to publish: {exc}"
        ) from exc

    risks = read_risks_v5(str(register_path))
    priced_risks, pinning = apply_pinning_to_risks(risks, pinned_states)
    logger.info(
        "Integrated period cost arm: %d risks priced (%d removed, %d closed, %d re-probabilised)",
        pinning.n_priced, pinning.n_removed, pinning.n_closed, pinning.n_reprobabilised,
    )

    # JOINT SAMPLING - invariant 1 of `integrated_simulation_stage3`, and the defect the part B
    # numerics review caught (B1). A dual-coded risk must share ONE severity uniform per
    # iteration across the cost and schedule arms; only then does adding the two arrays
    # element-wise describe a joint distribution rather than pairing unrelated draws.
    #
    # The first version called `MonteCarloEngine` standalone with its own generator - which is
    # the array `src/final/deliverable.py:274` labels "the cross-validation reference for the
    # cost marginal", the REFERENCE arm, not the headline one. The deliverable's headline reads
    # `stage3_result.cost_result`, produced by `run_integrated_simulation` with
    # `precomputed_severity_uniforms`. This now does the same, against the uniforms the schedule
    # run actually drew: `conditional_runner` already built them over the FULL register for this
    # contract ("joint-sampling contract preserved" at its build site) and they simply had no way
    # out of the function until part B's fix exposed them.
    missing = [r.risk_id for r in priced_risks if r.risk_id not in severity_uniforms_by_risk_id]
    if missing:
        raise ValueError(
            f"severity uniforms are missing for {missing[:5]}"
            f"{'...' if len(missing) > 5 else ''}: the cost arm would have to draw its own for "
            f"these, which breaks joint sampling silently for exactly the dual-coded risks the "
            f"contract is about")

    risk_scope = read_risk_scope(str(strawman_path))
    cost_result = run_integrated_simulation(
        config=config,
        risks=priced_risks,
        risk_scope_df=risk_scope,
        precomputed_severity_uniforms=severity_uniforms_by_risk_id,
    )
    cost_dollars = np.asarray(cost_result["cost_dollars_array"], dtype=float)

    finish_days = np.asarray(project_finish_days, dtype=float)
    schedule_days = finish_days - float(deterministic_finish_days)
    # A conditional run can finish EARLIER than the zero-risk pass only if the baseline itself
    # moved; clamping here would hide that rather than fix it, so it is asserted instead. The
    # tolerance is float32-scaled, not absolute: project_finish_days is float32 divided by the
    # calendar's hours-per-day, which is exact only when that is a power of two, so a fixed 1e-9
    # would abort a whole period over representation error on a non-8h calendar (part B review,
    # W3).
    tolerance = 1e-6 * max(1.0, abs(float(deterministic_finish_days)))
    if schedule_days.min() < -tolerance:
        raise ValueError(
            f"period finish is {abs(schedule_days.min()):.3f} days EARLIER than the deterministic "
            f"baseline ({deterministic_finish_days:.3f} d). Delay days would be negative, so the "
            f"integrated result would subtract money. The baseline and the conditional run "
            f"disagree - stop and report, do not clamp.")
    schedule_days = np.maximum(schedule_days, 0.0)

    if cost_dollars.shape != schedule_days.shape:
        raise ValueError(
            f"cost array {cost_dollars.shape} and schedule array {schedule_days.shape} differ; "
            f"the two arms did not run the same number of iterations, so pairing them by index "
            f"would combine unrelated draws")

    return IntegratedPeriodResult(
        cost_dollars_array=cost_dollars,
        schedule_days_array=schedule_days,
        integrated_dollars_array=integrated_dollars_array(cost_dollars, schedule_days, day_rate),
        day_rate=float(day_rate),
        deterministic_baseline_days=float(deterministic_finish_days),
        iterations=int(iterations),
        pinning=pinning,
    )
