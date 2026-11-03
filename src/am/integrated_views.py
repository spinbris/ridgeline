"""The integrated numbers the app reads, on the report's basis (INTVIEW-01 stage 2, contract 1.6).

Every dollar the PM and analyst pages show comes from here, so the app formats and never
computes. Each block is built with the report's own function wherever the report has one, so the
two surfaces cannot drift by re-derivation:

* the JCL is ``src.final.sections.integrated_total.stage3_jcl`` itself, on the period's arrays;
* the total cost is ``total_cost_data``, on the base ``deliverable_base_layer`` drew;
* the per-risk dollars are ``src.integrated.leave_one_out.integrated_leave_one_out``, the
  report's masked leave-one-out, with the period kernel as the replay.

What is new here is arithmetic the report prints in prose but no block carries: the build-up at
P50 / P80 / P90, the day-rate derivation, and the replay-noise flag on a saving.

Pure data (hard invariant 9): arrays and dicts in, dicts out.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

#: The build-up and total-cost P-levels (D-2, Director 28/10/2026): P50 / P80 / P90.
BUILD_UP_P_LEVELS: tuple[int, ...] = (50, 80, 90)
#: The P-level every per-risk and per-mitigation saving is read at.
SAVING_P_LEVEL = 80
#: Batches for the replay-noise estimate on a saving. A saving smaller than twice the standard
#: error of its batch values is flagged ``within_noise``: a disclosed presentation flag, the same
#: spirit as ``DELTA_ATTRIBUTION_THRESHOLD_DAYS``, not a significance test.
NOISE_BATCHES = 20
NOISE_MULTIPLIER = 2.0

LEAVE_ONE_OUT_NOTE = (
    "Per-risk dollars are leave-one-out at P80 on the integrated total, by masking: the risk's "
    "fire record is switched off and only the schedule kernel is replayed, every other risk's "
    "draws held fixed (the report's method). Cost is removed first, then delay; the split is "
    "stated, not unique. Bars do not sum to the total."
)

WHAT_COUNTS_WHERE = (
    "Risk event costs exclude site running costs (prelims, site overheads) while the job runs "
    "late. Those are priced once, on the delay line, and only for delay that survives float. "
    "Standby caused by a specific event, such as a crane stood down waiting on wind or a "
    "demobilise and remobilise, stays in that risk's own cost."
)


def _rate(result: Any, where: str) -> float:
    """The period's day rate through ``require_day_rate`` (DAYRATE-02): never a fallback."""
    from src.integrated.run_config_contract import require_day_rate

    return float(require_day_rate(result.day_rate, caller=f"src.am.integrated_views.{where}"))


def _pct(arr: np.ndarray, p: int) -> float:
    return float(np.percentile(np.asarray(arr, dtype=float), p))


def build_up(
    cost_dollars: np.ndarray, delay_days: np.ndarray, day_rate: float,
    p_levels: Sequence[int] = BUILD_UP_P_LEVELS,
) -> list[dict[str, Any]]:
    """Each part at its own P-level, their standalone sum, the joint figure and the difference.

    The joint figure is the integrated total's own P-value (the contingency); the parts do not add
    to it because the two arms do not peak in the same iterations. Diversification is the
    standalone sum less the joint, so the rows reconcile exactly.
    """
    cost = np.asarray(cost_dollars, dtype=float)
    days = np.asarray(delay_days, dtype=float)
    rate = float(day_rate)
    total = cost + days * rate
    rows = []
    for p in p_levels:
        event = _pct(cost, p)
        delay_d = _pct(days, p)
        delay = delay_d * rate
        joint = _pct(total, p)
        rows.append({
            "p_level": int(p),
            "event_cost_dollars": round(event, 2),
            "delay_days": round(delay_d, 3),
            "delay_cost_dollars": round(delay, 2),
            "standalone_sum_dollars": round(event + delay, 2),
            "joint_contingency_dollars": round(joint, 2),
            "diversification_dollars": round(event + delay - joint, 2),
        })
    return rows


def day_rate_derivation(
    run_config: dict[str, Any] | None, *, day_rate: float, programme_working_days: float,
) -> dict[str, Any]:
    """The day rate as stated, beside the derivation the register's own inputs support.

    The rate used is always the stated one (DAYRATE-01). Prelims per week x programme weeks over
    the schedule's working days is shown when the register states both inputs; when it differs
    from the stated rate, both are carried and the gap flagged, never re-derived.
    """
    cfg = run_config or {}

    def _num(key: str) -> float | None:
        v = cfg.get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    prelims = _num("avg_prelims_weekly")
    weeks = _num("schedule_duration_weeks")
    wd = float(programme_working_days)
    derived = (prelims * weeks / wd) if (prelims is not None and weeks is not None and wd > 0) \
        else None
    stated = float(day_rate)
    differs = derived is not None and round(derived) != round(stated)
    if derived is None:
        missing = [n for n, v in (("average prelims per week", prelims),
                                  ("schedule duration in weeks", weeks)) if v is None]
        note = (f"The register does not state {' or '.join(missing)}, so the rate is shown as "
                f"stated and not derived.")
    elif differs:
        note = (f"Prelims per week x programme weeks / working days gives "
                f"${derived:,.0f} per working day against ${stated:,.0f} stated. The stated rate "
                f"is the one used; the gap is for the register owner to resolve.")
    else:
        note = "The stated rate agrees with prelims per week x programme weeks / working days."
    return {
        "day_rate_used": round(stated, 2),
        "day_rate_stated": round(stated, 2),
        "avg_prelims_weekly": None if prelims is None else round(prelims, 2),
        "schedule_duration_weeks": None if weeks is None else round(weeks, 3),
        "programme_working_days": round(wd, 3),
        "day_rate_derived": None if derived is None else round(derived, 2),
        "gap_dollars": None if derived is None else round(derived - stated, 2),
        "gap_flagged": bool(differs),
        "note": note,
    }


def period_total_cost(result: Any) -> dict[str, Any] | None:
    """``total_cost_data`` on the period's arrays and its own base draw; ``None`` with no base."""
    from src.final.sections.integrated_total import SUMMARY_P_LEVELS, total_cost_data

    return total_cost_data(
        result.base_layer, result.cost_dollars_array, result.schedule_days_array,
        _rate(result, "period_total_cost"), p_levels=SUMMARY_P_LEVELS)


def period_jcl(result: Any, total_cost: dict[str, Any] | None) -> dict[str, Any] | None:
    """``stage3_jcl`` itself, handed the period's arrays in the shape the report hands it."""
    from types import SimpleNamespace

    from src.final.sections.integrated_total import stage3_jcl

    if result.project_finish_days is None:
        return None
    s3 = {
        "cost_result": {"cost_dollars_array": result.cost_dollars_array},
        "schedule_days_array": result.schedule_days_array,
        "schedule_result": SimpleNamespace(project_finish_days=result.project_finish_days),
    }
    return stage3_jcl(s3, total_cost, _rate(result, "period_jcl"))


def jcl_basis_sentence(jcl: dict[str, Any]) -> str:
    if jcl["base_drawn"]:
        budget = (f"budget = the declared base (${jcl['declared_base_dollars'] / 1e6:.2f}M) plus "
                  f"the P{jcl['p_level']} contingency, cost axis = base drawn + event-risk cost "
                  f"+ delay cost")
    else:
        budget = (f"no base drawn (Layer 1 off), so budget = the P{jcl['p_level']} contingency "
                  f"alone and cost axis = event-risk cost + delay cost")
    return (f"{budget}, as the budget funds delay cost; finish = P80 finish; cost and schedule "
            f"sampled jointly; rank correlation of cost with finish "
            f"{jcl['rank_correlation']:.2f}. The report's basis.")


def total_cost_block(total: dict[str, Any] | None) -> dict[str, Any] | None:
    if not total:
        return None
    rows = [{
        "p_level": int(p),
        "total_dollars": round(v, 2),
        "contingency_dollars": round(total["contingency_dollars"][p], 2),
    } for p, v in total["percentiles_dollars"].items()]
    return {
        "label": "Total cost = base estimate drawn + event-risk cost + delay cost, as the report's "
                 "total-cost table. Analyst view only (D-2).",
        "declared_base_dollars": round(total["base_total_dollars"], 2),
        "mean_dollars": round(total["mean_dollars"], 2),
        "rows": rows,
        "excluded_base_factors": [d["name"] for d in total.get("excluded_factors") or []],
    }


RECOMMENDED_LABEL = "Recommended at P80"
HELD_LABEL = "Held against required at P80"


def contingency_block(
    p80_dollars: float,
    inputs: dict[str, Any] | None = None,
    *,
    period_end: Any = None,
    held_jcl: dict[str, Any] | None = None,
    bridge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The owner's contingency position (properties 7 and 10, D-4).

    Before commitment - no contingency sheet, a blank commitment date, or one after this period
    ends - the block reads "Recommended at P80" and every held field is null, so a missing entry
    never reads as funded. From commitment: held = opening less approved draws plus approved
    releases, each counted only if dated from the commitment to this period end; pending draws
    are reported apart and never subtracted. ``shortfall_dollars`` is required less held, so a
    negative figure is headroom.
    """
    required = round(float(p80_dollars), 2)
    commitment = (inputs or {}).get("commitment_date")
    committed = commitment is not None and (period_end is None or commitment <= period_end)
    block: dict[str, Any] = {
        "phase": "recommended",
        "label": RECOMMENDED_LABEL,
        "required_p80_dollars": required,
        "held_dollars": None,
        "commitment_date": None,
        "opening_held_dollars": None,
        "approved_draws_dollars": None,
        "pending_draws_dollars": None,
        "releases_dollars": None,
        "shortfall_dollars": None,
        "jcl_against_held": None,
        "cost_confidence_against_held": None,
        "movements": [],
        "illustrative": bool((inputs or {}).get("illustrative", False)),
        "bridge": bridge,
    }
    if not committed:
        return block

    in_window = [m for m in inputs["movements"]
                 if commitment <= m["date"] and (period_end is None or m["date"] <= period_end)]

    def total(kind: str, status: str) -> float:
        return float(sum(m["amount"] for m in in_window
                         if m["type"] == kind and m["status"] == status))

    approved_draws = total("Draw", "Approved")
    releases = total("Release", "Approved")
    held = float(inputs["opening_held"]) - approved_draws + releases
    block.update(
        phase="held",
        label=HELD_LABEL,
        held_dollars=round(held, 2),
        commitment_date=commitment.isoformat(),
        opening_held_dollars=round(float(inputs["opening_held"]), 2),
        approved_draws_dollars=round(approved_draws, 2),
        pending_draws_dollars=round(total("Draw", "Pending"), 2),
        releases_dollars=round(releases, 2),
        shortfall_dollars=round(float(p80_dollars) - held, 2),
        movements=[{
            "date": m["date"].isoformat(), "type": m["type"],
            "amount_dollars": round(m["amount"], 2), "status": m["status"],
            "risk_id": m["risk_id"], "note": m["note"],
        } for m in sorted(in_window, key=lambda m: m["date"])],
    )
    if held_jcl is not None:
        block["jcl_against_held"] = round(held_jcl["jcl"], 4)
        block["cost_confidence_against_held"] = round(held_jcl["cost_confidence"], 4)
    return block


def jcl_against_held(
    result: Any, total_cost: dict[str, Any] | None, held_dollars: float,
) -> dict[str, Any] | None:
    """The JCL with the budget at declared base + HELD contingency (property 10).

    Same axes as ``stage3_jcl`` - base drawn + event-risk cost + delay cost against the P80
    finish (JCLAXIS-01) - so the
    only difference from the headline JCL is the budget line. Shown beside it, never instead.
    """
    from src.integrated.integrated_dollars import integrated_dollars_array
    from src.integrated.jcl import jcl_data

    if result.project_finish_days is None:
        return None
    finish = np.asarray(result.project_finish_days, dtype=float)
    base = total_cost["base_dollars"] if total_cost else 0.0
    declared = total_cost["base_total_dollars"] if total_cost else 0.0
    integrated = integrated_dollars_array(
        result.cost_dollars_array, result.schedule_days_array, _rate(result, "jcl_against_held"))
    axis = integrated + base
    if (total_cost or {}).get("owner_finish_days") is not None:
        # RISKDRV-01: the owner view's axes, as stage3_jcl draws them with shared drivers on.
        axis = total_cost["total_dollars"]
        finish = np.asarray(total_cost["owner_finish_days"], dtype=float)
    return jcl_data(axis, finish,
                    cost_target=declared + float(held_dollars),
                    finish_target=float(np.percentile(finish, 80)))


#: D-5 (Director 29/10/2026): the bridge's attribution order, stated on the chart. Sequential
#: leave-in attribution is order-dependent, so the order is fixed rather than chosen per period.
BRIDGE_ORDER: tuple[tuple[str, str], ...] = (
    ("closed", "Closed risks"),
    ("new", "New risks"),
    ("reassessed", "Reassessed risks"),
    ("mitigations", "Mitigations"),
)
BRIDGE_RESIDUAL_LABEL = "Other changes (progress, milestones, realised impacts)"
#: Mitigation statuses that make a risk's probability move this period a mitigation step.
MITIGATION_STEP_STATUSES = frozenset({"actioned", "completed"})
#: The replay of this period's own probabilities must land on this period's P80 (a positive
#: control); the tolerance is float rounding only.
BRIDGE_CONTROL_RTOL = 1e-9

BRIDGE_METHOD = (
    "Last period's P80 to this period's P80, attributed by replaying this period's own draws at "
    "last period's probabilities and stepping each change in, in the order closed, new, "
    "reassessed, mitigations. A step's dollars are the P80 after it less the P80 before it, so "
    "the steps depend on the order, which is fixed. A risk counts as a mitigation step when its "
    "probability moved and it has a mitigation at Actioned or Completed. What the replay cannot "
    "rebuild - schedule progress, milestones, realised impacts, a risk removed from the run - is "
    "the last bar, so the bars sum exactly to the movement."
)


def period_bridge(
    *,
    current_p80_dollars: float,
    prior_doc: dict[str, Any] | None,
    current_probabilities: dict[str, float],
    closed_risk_ids: Sequence[str],
    mitigated_risk_ids: Sequence[str],
    p80_at: Callable[[dict[str, float]], float],
) -> dict[str, Any] | None:
    """The P80 bridge (property 11, D-5): ``None`` at period 0, a stated reason when unbuildable.

    ``p80_at`` prices this period's own draws at the probabilities given (cost arm re-priced,
    schedule kernel replayed under the resulting fire record) and returns the integrated P80.
    It is called at last period's probabilities and after each step; the final state is this
    period's own probabilities, so the last call must reproduce this period's P80 - a positive
    control, which raises rather than publish a bridge that does not close.
    """
    if prior_doc is None:
        return None
    prior_period = (prior_doc.get("meta") or {}).get("period_end_date")
    prior_int = prior_doc.get("integrated") or {}
    prior_probs = (prior_int.get("pinning") or {}).get("priced_probabilities")
    if prior_probs is None or prior_int.get("p80_dollars") is None:
        return {
            "available": False,
            "reason": "Last period's file does not record the probability each risk was priced "
                      "at, so the bridge cannot start from it. It appears from the next period.",
            "prior_period_end_date": prior_period,
        }

    def same(a: float, b: float) -> bool:
        return abs(float(a) - float(b)) <= 1e-12

    ids = list(current_probabilities)
    new = [r for r in ids if r not in prior_probs]
    closed = [r for r in ids if r in set(closed_risk_ids) and r not in new
              and not same(prior_probs[r], 0.0)]
    moved = [r for r in ids if r not in new and r not in closed
             and not same(prior_probs[r], current_probabilities[r])]
    mitigated = set(mitigated_risk_ids)
    groups = {
        "closed": closed,
        "new": new,
        "reassessed": [r for r in moved if r not in mitigated],
        "mitigations": [r for r in moved if r in mitigated],
    }

    state = {r: (0.0 if r in new else float(prior_probs[r])) for r in ids}
    start = p80_at(dict(state))
    level = start
    steps = []
    for key, label in BRIDGE_ORDER:
        if groups[key]:
            for r in groups[key]:
                state[r] = float(current_probabilities[r])
            after = p80_at(dict(state))
        else:
            after = level
        steps.append({"key": key, "label": label, "dollars": round(after - level, 2) + 0.0,
                      "risk_ids": sorted(groups[key])})
        level = after

    if not np.isclose(level, current_p80_dollars, rtol=BRIDGE_CONTROL_RTOL, atol=0.01):
        raise ValueError(
            f"bridge positive control failed: replaying this period's own probabilities gives "
            f"P80 {level:,.2f}, the period's P80 is {current_p80_dollars:,.2f}. The replay does "
            f"not reproduce the run, so no step it measures can be published.")
    prior_p80 = float(prior_int["p80_dollars"])
    dropped = sorted(set(prior_probs) - set(ids))
    steps.append({"key": "other", "label": BRIDGE_RESIDUAL_LABEL,
                  "dollars": round(start - prior_p80, 2) + 0.0, "risk_ids": dropped})
    return {
        "available": True,
        "prior_period_end_date": prior_period,
        "prior_p80_dollars": round(prior_p80, 2),
        "current_p80_dollars": round(float(current_p80_dollars), 2),
        "order": [k for k, _ in BRIDGE_ORDER],
        "steps": steps,
        "method": BRIDGE_METHOD,
    }


def bridge_p80_evaluator(
    result: Any,
    *,
    schedule_risk_ids: Sequence[str],
    replay_delay_days: Callable[[np.ndarray], np.ndarray],
) -> Callable[[dict[str, float]], float]:
    """``p80_at`` for :func:`period_bridge`, from the period's re-pricer and kernel replay."""
    from src.integrated.integrated_dollars import integrated_dollars_array

    rate = _rate(result, "bridge_p80_evaluator")
    columns = [list(result.risk_ids_all).index(r) for r in schedule_risk_ids]

    def p80_at(probabilities: dict[str, float]) -> float:
        cost, fired = result.reprice(probabilities)
        delay = replay_delay_days(np.ascontiguousarray(fired[:, columns]))
        return _pct(integrated_dollars_array(cost, delay, rate), SAVING_P_LEVEL)

    return p80_at


class _RecordingReplay:
    """Wraps a replay so each masked delay array is kept, in call order, for the noise flag."""

    def __init__(self, replay: Callable[[np.ndarray], np.ndarray]):
        self._replay = replay
        self.calls: list[np.ndarray] = []

    def __call__(self, mask: np.ndarray) -> np.ndarray:
        out = np.asarray(self._replay(mask), dtype=float)
        self.calls.append(out)
        return out


def _batch_noise(with_arr: np.ndarray, without_arr: np.ndarray, p: int) -> float:
    """``NOISE_MULTIPLIER`` x the standard error of the P-level saving over equal batches."""
    n = with_arr.size
    b = NOISE_BATCHES if n >= NOISE_BATCHES * 10 else max(2, n // 10)
    if b < 2:
        return float("nan")
    edges = np.linspace(0, n, b + 1).astype(int)
    vals = [_pct(with_arr[i:j], p) - _pct(without_arr[i:j], p)
            for i, j in zip(edges[:-1], edges[1:])]
    return NOISE_MULTIPLIER * float(np.std(vals, ddof=1)) / float(np.sqrt(b))


def period_leave_one_out(
    result: Any,
    *,
    schedule_risk_ids: Sequence[str],
    fire_mask: np.ndarray,
    replay_delay_days: Callable[[np.ndarray], np.ndarray],
    p_level: int = SAVING_P_LEVEL,
) -> dict[str, Any]:
    """The report's masked leave-one-out on the period's arrays, plus days saved and noise.

    ``integrated_leave_one_out`` makes the dollar figures and refuses unless the unmasked replay
    reproduces the run's delay array (the positive control); this adds, per risk, the delay days
    saved at ``p_level`` and the batch noise on both the dollar and the days saving, read off the
    same replays rather than new ones.
    """
    from src.integrated.leave_one_out import integrated_leave_one_out

    rec = _RecordingReplay(replay_delay_days)
    ids_all = list(result.risk_ids_all)
    sched_ids = [str(r) for r in schedule_risk_ids]
    loo = integrated_leave_one_out(
        cost_dollars_array=result.cost_dollars_array,
        per_risk_cost_array=result.per_risk_cost_array,
        risk_ids_all=ids_all,
        schedule_days_array=result.schedule_days_array,
        schedule_risk_ids=sched_ids,
        fire_mask=fire_mask,
        replay_delay_days=rec,
        day_rate=_rate(result, "period_leave_one_out"),
        p_level=p_level,
    )
    # Call order inside integrated_leave_one_out: the control, then one replay per risk in
    # risk_ids_all order that is a schedule driver. Rebuilt here rather than inferred from masks.
    replayed = [rid for rid in ids_all if rid in set(sched_ids)]
    if len(rec.calls) != 1 + len(replayed):
        raise ValueError(
            f"expected {1 + len(replayed)} replays (control + one per schedule risk), saw "
            f"{len(rec.calls)}; the delay arrays cannot be matched to their risks")
    delay_without = dict(zip(replayed, rec.calls[1:]))

    cost = np.asarray(result.cost_dollars_array, dtype=float)
    days = np.asarray(result.schedule_days_array, dtype=float)
    per_risk = np.asarray(result.per_risk_cost_array, dtype=float)
    rate = _rate(result, "period_leave_one_out")
    total = cost + days * rate
    col = {rid: i for i, rid in enumerate(ids_all)}
    rows: dict[str, dict[str, Any]] = {}
    for row in loo["rows"]:
        rid = row["risk_id"]
        dw = delay_without.get(rid, days)
        without_both = total - per_risk[:, col[rid]] - (days - dw) * rate
        days_saved = _pct(days, p_level) - _pct(dw, p_level)
        noise_dollars = _batch_noise(total, without_both, p_level)
        noise_days = _batch_noise(days, dw, p_level)
        rows[rid] = {
            "saved_dollars": row["saved_dollars"],
            "cost_part_dollars": row["cost_part_dollars"],
            "delay_part_dollars": row["delay_part_dollars"],
            "delay_days_saved": days_saved,
            "noise_dollars": noise_dollars,
            "noise_days": noise_days,
        }
    return {
        "p_level": int(p_level),
        "iterations": int(loo["iterations"]),
        "replays": int(loo["replays"]),
        "method": LEAVE_ONE_OUT_NOTE,
        "rows": rows,
    }


def within_noise(saving: float, noise: float) -> bool:
    return bool(np.isfinite(noise) and abs(float(saving)) < float(noise))
