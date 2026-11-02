"""Joint confidence level: how often cost and finish both land inside their targets (INTSCURVE-01 C).

The JCL is the share of iterations whose cost is at or under the cost target AND whose finish
is at or before the finish target. It is the joint reading the two separate S-curves cannot give:
a P80 budget and a P80 finish are each met four times in five, but together less often.

**The cost axis carries delay cost** (JCLAXIS-01, Director 01/11/2026, superseding INTSCURVE-01
Part C property 11). The budget it is tested against includes delay cost, so the axis must too;
a JCL counts iterations meeting both targets and adds nothing across the axes, so nothing is
counted twice. The axis is base (where the register draws one) + event-risk cost + delay cost.

**The rank correlation and quadrant shares** are returned beside the JCL, because the correlation
between the axes is what most moves a JCL, and a reader cannot judge it by eye from the cloud.

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


def rank_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman's rank correlation, average ranks for ties; NaN when either side has no spread.

    Pure numpy, so the engine layer takes no scipy dependency for one statistic.
    """
    a, b = _average_ranks(x), _average_ranks(y)
    if a.size != b.size or a.size < 2:
        raise ValueError(f"rank_correlation: {a.shape} and {b.shape} must pair, two or more")
    if np.ptp(a) == 0 or np.ptp(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _average_ranks(values: np.ndarray) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    order = np.argsort(v, kind="mergesort")
    sorted_v = v[order]
    # Runs of equal values share the mean of the 1-based ranks they span.
    starts = np.flatnonzero(np.r_[True, sorted_v[1:] != sorted_v[:-1]])
    ends = np.r_[starts[1:], v.size]
    mean_rank = (starts + ends + 1) / 2.0
    ranks = np.empty(v.size, dtype=float)
    ranks[order] = np.repeat(mean_rank, ends - starts)
    return ranks


def jcl_data(
    cost_axis: np.ndarray, finish_axis: np.ndarray, *, cost_target: float,
    finish_target: float, level: float = JCL_FRONTIER_LEVEL,
) -> dict[str, Any]:
    """Everything the JCL chart and sentence need, from one pair of paired arrays.

    Returns ``{"cost_axis", "finish_axis", "meets_both" (bool array), "cost_target",
    "finish_target", "jcl", "cost_confidence", "finish_confidence", "frontier", "level",
    "rank_correlation", "quadrants" {"meets_both", "cost_only", "finish_only", "neither"}}``.
    """
    cost = np.asarray(cost_axis, dtype=float)
    finish = np.asarray(finish_axis, dtype=float)
    on_cost, on_time = cost <= cost_target, finish <= finish_target
    meets = on_cost & on_time
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
        "rank_correlation": rank_correlation(cost, finish),
        "quadrants": {
            "meets_both": float(np.mean(meets)),
            "cost_only": float(np.mean(on_cost & ~on_time)),
            "finish_only": float(np.mean(~on_cost & on_time)),
            "neither": float(np.mean(~on_cost & ~on_time)),
        },
    }
