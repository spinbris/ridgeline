"""The integrated total, one definition: ``cost + delay_days * day_rate`` per iteration.

STAGE3HEADLINE-01 P2 (10/09/2026). The app's period cycle (``src/am/integrated_period.py``) and
the deliverable's headline (``src/final/headline.py``) both dollarise schedule delay; each used
to write the expression itself. Two constructions that must agree is the shape that drifts, so
the expression lives here, below both, and both import it.
"""
from __future__ import annotations

import numpy as np


def integrated_dollars_array(
    cost_dollars_array: np.ndarray, schedule_days_array: np.ndarray, day_rate: float,
) -> np.ndarray:
    """``cost + delay_days * day_rate`` per iteration, arrays paired by index."""
    cost = np.asarray(cost_dollars_array, dtype=float)
    days = np.asarray(schedule_days_array, dtype=float)
    if cost.shape != days.shape:
        raise ValueError(
            f"cost array {cost.shape} and schedule array {days.shape} differ; the two arms did "
            f"not run the same number of iterations, so pairing them by index would combine "
            f"unrelated draws")
    return cost + days * float(day_rate)
