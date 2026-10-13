"""The zero-risk forward pass: the deterministic finish every delay is measured from.

STAGE3HEADLINE-01 D-7 (Director, 10/09/2026). Three callers subtracted a baseline from the
kernel's project finish and two of them derived it differently: the period engine ran this
pass, the Stage 3 integrated result took ``min(project_finish_days)`` as a proxy for it. The
proxy equals the pass only when some iteration fires no risk; on a project whose drivers fire
in every iteration it overstates the baseline and understates every delay by a constant. One
pass, one function, every caller.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from src.sra.cpm.cpm_kernel import Precision, run_batch as _kernel_run_batch


def deterministic_ef_hours(graph: Any, precision: Precision = "float32") -> np.ndarray:
    """Per-activity early finish, working hours, in ``graph.topo_order``, with no risk fired.

    ``precision`` must match the stochastic batch this pass is a baseline for (review
    re-review: the pass was hardcoded float32 regardless of the batch's own precision,
    coupling two things that should agree by construction, not by accident).
    """
    dtype = np.float32 if precision == "float32" else np.float64
    base_durations = np.array(
        [[graph.activities[a].original_duration_hours for a in graph.topo_order]],
        dtype=dtype,
    )
    out = _kernel_run_batch(
        durations=base_durations,
        graph=graph,
        calendar=graph.project_default_calendar,
        precision=precision,
    )
    return np.asarray(out["EF"][0])


def deterministic_finish_hours(graph: Any, precision: Precision = "float32") -> float:
    """The project's zero-risk finish: the maximum early finish over every activity."""
    return float(deterministic_ef_hours(graph, precision=precision).max())


def deterministic_ef_per_activity(graph: Any, precision: Precision = "float32") -> dict[str, float]:
    """``{activity_id: early finish hours}`` from the zero-risk pass."""
    ef = deterministic_ef_hours(graph, precision=precision)
    return {a_id: float(ef[i]) for i, a_id in enumerate(graph.topo_order)}
