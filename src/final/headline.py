"""The deliverable's headline contingency, from the Stage 3 distribution (STAGE3HEADLINE-01).

Director D-1, 10/09/2026: Stage 3 has one distribution and no Mode family, so the
lower / indicative / upper range that Stage 2.5's Mode scenarios supplied has no Stage 3
equivalent. The headline is a percentile range on the one distribution - P50, P80, P95 - with
the basis said on the page: the spread of one modelled outcome, not a spread between two Mode
assumptions.

One derivation, called from both surfaces (brief property P2): the expression lives in
:mod:`src.integrated.integrated_dollars`, below both the app's period cycle and this module, and
both import it; the headline block here reads percentiles of that array.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from src.integrated.integrated_dollars import integrated_dollars_array

#: The scenario key under which the Stage 3 arrays travel beside the Mode family in the
#: composer's headline family, and the label a reader sees.
STAGE3_SCENARIO_NAME = "Stage3"
STAGE3_SCENARIO_DISPLAY = "Stage 3 (CPM replay, one distribution)"

#: What the headline says its range is. Stated once here so every surface says the same.
STAGE3_HEADLINE_BASIS = (
    "Stage 3 CPM replay: one distribution, percentiles of one modelled outcome. The P50-P95 "
    "spread is project uncertainty, not a spread between Mode assumptions."
)

DEFAULT_P_LEVELS: tuple[int, ...] = (50, 80, 95)


def stage3_headline(
    cost_dollars_array: np.ndarray,
    schedule_days_array: np.ndarray,
    day_rate: float,
    *,
    p_levels: tuple[int, ...] = DEFAULT_P_LEVELS,
    p_level: int = 80,
    headline_metric: str = "P80",
) -> dict[str, Any]:
    """The headline block: percentiles and mean of the Stage 3 integrated total.

    Returns ``{"basis", "p_levels", "percentiles_dollars": {50: ..}, "p<n>_dollars" for each
    level, "mean_dollars", "headline_dollars" (the metric the page leads with), "p_level",
    "headline_metric", "iterations"}``. No labels follow the data here: there is nothing to
    order, because there is one distribution.
    """
    total = integrated_dollars_array(cost_dollars_array, schedule_days_array, day_rate)
    if total.size == 0:
        raise ValueError("stage3_headline: empty integrated array")
    if p_level not in p_levels:
        p_levels = tuple(sorted({*p_levels, int(p_level)}))
    percentiles = {int(p): float(np.percentile(total, p)) for p in p_levels}
    mean = float(np.mean(total))
    metric = str(headline_metric).strip()
    if metric.upper() == "MEAN":
        headline_dollars, metric = mean, "Mean"
    else:
        headline_dollars, metric = percentiles[int(p_level)], f"P{int(p_level)}"
    out: dict[str, Any] = {
        "basis": STAGE3_HEADLINE_BASIS,
        "scenario": STAGE3_SCENARIO_NAME,
        "scenario_display": STAGE3_SCENARIO_DISPLAY,
        "p_levels": tuple(int(p) for p in p_levels),
        "percentiles_dollars": percentiles,
        "mean_dollars": mean,
        "headline_dollars": headline_dollars,
        "p_level": int(p_level),
        "headline_metric": metric,
        "iterations": int(total.size),
    }
    for p, v in percentiles.items():
        out[f"p{p}_dollars"] = v
    return out
