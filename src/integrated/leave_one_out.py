"""Leave-one-out on the integrated total: what each risk adds to the P80, cost and delay split.

INTSCURVE-01 property 3. The deliverable's two arm tornados rank a risk by its contribution to one
arm; neither says what the project would save at the headline P-level if the risk were gone. This
does: for each risk, the P80 of the Stage 3 integrated total (cost + float-aware delay x day rate)
with the risk, minus the P80 without it.

**Removal by masking, not by re-drawing** (Reviewer R2, 28/10/2026). The period route's
leave-one-out (``src.am.metrics.compute_leave_one_out_metrics``) force-closes the risk and re-runs,
which shrinks the risk list and so reshuffles every other risk's draws; at P80 that noise can swamp
a small risk's delta. Here the run's own fire record and severity uniforms are kept, the removed
risk's fire column is set to False, and only the schedule kernel is replayed, on a fresh copy of the
run's kernel stream. Every other risk sees exactly the draws it saw in the run, so a risk with no
impact gives a delta of exactly zero.

The cost arm needs no replay: a risk's cost is its own column of ``per_risk_cost_array``, so
removing it is a subtraction. Chain children keep the fire state the run gave them (the chain is not
re-resolved without its parent); the report says so. Delay needs a CPM replay per Time=Yes risk,
because a delay that is absorbed by float with one risk present may not be with it absent.

Pure data (hard invariant 9): arrays and dicts in, a dict out.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

#: Written on the chart and in the report so the bars are not read as contributions that add up.
LEAVE_ONE_OUT_METHOD = (
    "leave-one-out at the headline P-level: each bar is the integrated P{p} with the risk, less "
    "the integrated P{p} with that risk removed and every other risk's draws held fixed. Bars do "
    "not sum to the total, because removing two risks together is not removing each alone."
)


def integrated_leave_one_out(
    *,
    cost_dollars_array: np.ndarray,
    per_risk_cost_array: np.ndarray,
    risk_ids_all: Sequence[str],
    schedule_days_array: np.ndarray,
    schedule_risk_ids: Sequence[str],
    fire_mask: np.ndarray,
    replay_delay_days: Callable[[np.ndarray], np.ndarray],
    day_rate: float,
    p_level: int = 80,
) -> dict[str, Any]:
    """Leave-one-out P-level savings on the integrated total, per risk, cost and delay split.

    ``fire_mask`` is the run's fire record in ``schedule_risk_ids`` order (``cost_arm_fire_mask``).
    ``replay_delay_days(mask)`` replays the Stage 3 schedule kernel under ``mask`` on the run's own
    severity uniforms and kernel stream and returns per-iteration delay days. It is called once
    with the unmasked record first, as a positive control: a replay that does not reproduce the
    run's own delay array would compare unlike draws, so it is refused rather than reported.

    For each risk ``j`` with cost column ``c`` and delay-days change ``d``, on total ``T``:

    - ``cost_part = P(T) - P(T - c)``
    - ``delay_part = P(T - c) - P(T - c - d x day_rate)``
    - ``saved = cost_part + delay_part`` (exactly, by construction)

    The split is sequential (cost removed first), which is stated; it is not unique.

    Returns ``{"p_level", "iterations", "replays", "method", "rows"}``, rows sorted by ``saved``
    descending, each ``{"risk_id", "saved_dollars", "cost_part_dollars", "delay_part_dollars"}``.
    """
    cost = np.asarray(cost_dollars_array, dtype=float)
    per_risk = np.asarray(per_risk_cost_array, dtype=float)
    days = np.asarray(schedule_days_array, dtype=float)
    mask = np.asarray(fire_mask, dtype=bool)
    rate = float(day_rate)
    ids = [str(r) for r in risk_ids_all]
    sched_ids = [str(r) for r in schedule_risk_ids]
    if per_risk.shape != (cost.size, len(ids)):
        raise ValueError(
            f"per_risk_cost_array {per_risk.shape} does not match {cost.size} iterations x "
            f"{len(ids)} risks")
    if days.shape != cost.shape or mask.shape != (cost.size, len(sched_ids)):
        raise ValueError(
            f"schedule arrays do not pair with the cost arm: days {days.shape}, fire mask "
            f"{mask.shape}, cost {cost.shape}, {len(sched_ids)} schedule risks")
    unknown = [r for r in sched_ids if r not in ids]
    if unknown:
        raise ValueError(f"schedule risks {unknown[:5]} have no cost-arm column (SPEC R-10)")

    control = np.asarray(replay_delay_days(mask.copy()), dtype=float)
    if not np.array_equal(control, days):
        raise ValueError(
            "the unmasked Stage 3 replay does not reproduce the run's delay array, so a masked "
            "replay would not hold the other risks' draws fixed; leave-one-out refused")

    total = cost + days * rate
    p_total = float(np.percentile(total, p_level))
    col = {rid: i for i, rid in enumerate(sched_ids)}
    rows: list[dict[str, Any]] = []
    replays = 0
    for j, rid in enumerate(ids):
        without_cost = total - per_risk[:, j]
        p_without_cost = float(np.percentile(without_cost, p_level))
        if rid in col:
            masked = mask.copy()
            masked[:, col[rid]] = False
            delay_without = np.asarray(replay_delay_days(masked), dtype=float)
            replays += 1
            without_both = without_cost - (days - delay_without) * rate
            p_without_both = float(np.percentile(without_both, p_level))
        else:
            p_without_both = p_without_cost
        rows.append({
            "risk_id": rid,
            "saved_dollars": p_total - p_without_both,
            "cost_part_dollars": p_total - p_without_cost,
            "delay_part_dollars": p_without_cost - p_without_both,
        })
    rows.sort(key=lambda r: r["saved_dollars"], reverse=True)
    return {
        "p_level": int(p_level),
        "iterations": int(cost.size),
        "replays": replays,
        "method": LEAVE_ONE_OUT_METHOD.format(p=int(p_level)),
        "rows": rows,
    }


def stage3_leave_one_out(
    stage3_result: Any,
    schedule_mc_config: Any,
    *,
    day_rate: float,
    p_level: int = 80,
) -> dict[str, Any]:
    """:func:`integrated_leave_one_out` on a ``Stage3IntegratedResult``, replaying its own kernel.

    The replay uses the run's graph, drivers, severity uniforms and a fresh
    ``kernel_generator(seed)`` - the same parent the run's kernel spawned its batches from - and
    the run's deterministic baseline, so the unmasked replay is the run.
    """
    from src.integrated.integrated_simulation_stage3 import cost_arm_fire_mask
    from src.rng_streams import kernel_generator
    from src.sra.cpm.cpm_simulation import run_schedule_mc

    r = stage3_result
    sched_ids = tuple(r.risk_drivers.keys())
    severity = np.stack([r.severity_uniforms_by_risk_id[k] for k in sched_ids], axis=1)
    baseline = float(r.config_summary["deterministic_baseline_days"])
    mode = r.config_summary["criticality_measurement_mode"]

    def replay(mask: np.ndarray) -> np.ndarray:
        out = run_schedule_mc(
            graph=r.schedule_graph, risk_drivers=r.risk_drivers, config=schedule_mc_config,
            severity_uniforms=severity, rng=kernel_generator(int(r.seed_used)),
            criticality_measurement_mode=mode, fire_mask=mask,
        )
        finish = np.asarray(out.project_finish_days).astype(np.float64)
        return np.maximum(finish - baseline, 0.0)

    cost = r.cost_result
    return integrated_leave_one_out(
        cost_dollars_array=cost["cost_dollars_array"],
        per_risk_cost_array=cost["per_risk_cost_array"],
        risk_ids_all=cost["risk_ids_all"],
        schedule_days_array=r.schedule_days_array,
        schedule_risk_ids=sched_ids,
        fire_mask=cost_arm_fire_mask(cost, sched_ids),
        replay_delay_days=replay,
        day_rate=day_rate,
        p_level=p_level,
    )
