"""Joint confidence level: how often cost and finish both land inside their targets (INTSCURVE-01 C).

The JCL is the share of iterations whose cost is at or under the cost target AND whose finish
is at or before the finish target. It is the joint reading the two separate S-curves cannot give:
a P80 budget and a P80 finish are each met four times in five, but together less often.

**The cost axis excludes delay cost** (Part C property 11). Delay cost is the finish delay
priced at the day rate, so carrying it on the cost axis as well as on the finish axis would count
the same days twice. The axis is base (where the register draws one) plus event-risk cost.

**Targets** (D-3, Director 28/10/2026): cost = base + the event-risk contingency at the headline
P-level; finish = the P80 finish. The 70% frontier (the NASA norm) is drawn for reference; no
Australian guidance requires a JCL, so it is offered beside the headline, never as one.

Pure numpy (hard invariant 9): arrays in, floats and dicts out.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

#: The reference frontier's confidence level (NASA NPR 7120.5 norm), D-3.
JCL_FRONTIER_LEVEL = 0.70


def joint_confidence(
    cost_axis: np.ndarray, finish_axis: np.ndarray, cost_target: float, finish_target: float,
) -> float:
    """Share of iterations with cost <= ``cost_target`` and finish <= ``finish_target``."""
    cost = np.asarray(cost_axis, dtype=float)
    finish = np.asarray(finish_axis, dtype=float)
    if cost.shape != finish.shape or cost.size == 0:
        raise ValueError(
            f"joint_confidence: cost {cost.shape} and finish {finish.shape} must pair, non-empty")
    return float(np.mean((cost <= cost_target) & (finish <= finish_target)))


def jcl_frontier(
    cost_axis: np.ndarray, finish_axis: np.ndarray, level: float = JCL_FRONTIER_LEVEL,
    points: int = 41,
) -> list[tuple[float, float]]:
    """The (finish, cost) target pairs whose JCL is ``level``: the cheapest cost per finish.

    For each finish target on a grid of finish quantiles from ``level`` to 1, the smallest
    cost target whose joint count reaches ``ceil(level * n)``. Finish targets earlier than the
    ``level`` quantile cannot reach the level at any cost, so the grid starts there.
    """
    cost = np.asarray(cost_axis, dtype=float)
    finish = np.asarray(finish_axis, dtype=float)
    n = cost.size
    need = math.ceil(level * n)
    out: list[tuple[float, float]] = []
    for q in np.linspace(level, 1.0, points):
        f_t = float(np.quantile(finish, q))
        inside = np.sort(cost[finish <= f_t])
        if inside.size < need:
            continue
        out.append((f_t, float(inside[need - 1])))
    return out


def jcl_data(
    cost_axis: np.ndarray, finish_axis: np.ndarray, *, cost_target: float,
    finish_target: float, level: float = JCL_FRONTIER_LEVEL,
) -> dict[str, Any]:
    """Everything the JCL chart and sentence need, from one pair of paired arrays.

    Returns ``{"cost_axis", "finish_axis", "meets_both" (bool array), "cost_target",
    "finish_target", "jcl", "cost_confidence", "finish_confidence", "frontier", "level"}``.
    """
    cost = np.asarray(cost_axis, dtype=float)
    finish = np.asarray(finish_axis, dtype=float)
    meets = (cost <= cost_target) & (finish <= finish_target)
    return {
        "cost_axis": cost,
        "finish_axis": finish,
        "meets_both": meets,
        "cost_target": float(cost_target),
        "finish_target": float(finish_target),
        "jcl": joint_confidence(cost, finish, cost_target, finish_target),
        "cost_confidence": float(np.mean(cost <= cost_target)),
        "finish_confidence": float(np.mean(finish <= finish_target)),
        "frontier": jcl_frontier(cost, finish, level),
        "level": float(level),
    }
