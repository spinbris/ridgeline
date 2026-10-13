"""Single-iteration walkthrough section builder.

Page 7 / methodology: picks one MC iteration near the target percentile
of total schedule slip (so multiple risks fire) and reports the cost,
schedule slip, and per-risk contributions for that iteration. Gives a
non-technical reader a concrete view of one path through the simulation.

Moved here under SR14a from ``src/final/composer.py`` (private helper
``_build_single_iteration_walkthrough``). Composer re-exports the helper
at module level so existing test imports keep working.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def _build_single_iteration_walkthrough(
    integrated_results: dict[str, Any],
    risks: Iterable[Any] | None,
    target_percentile: int = 95,
) -> str:
    """Construct a concrete-iteration walkthrough from per-risk arrays.

    Picks an iteration near the target percentile of total schedule slip
    (so multiple risks fired). Reports total cost / schedule and the
    risks that fired in that iteration with their cost / schedule
    contribution.
    """
    cost_arr = np.asarray(integrated_results.get("cost_dollars_array", []))
    sched_arr = np.asarray(integrated_results.get("schedule_days_array", []))
    per_risk_cost = np.asarray(integrated_results.get("per_risk_cost_array", []))
    per_risk_sched = np.asarray(integrated_results.get("per_risk_schedule_array", []))
    risk_ids_all = list(integrated_results.get("risk_ids_all", []))
    risk_ids_dual = list(integrated_results.get("risk_ids_dual", []))

    if cost_arr.size == 0 or per_risk_cost.size == 0:
        return ""

    target_value = float(np.percentile(sched_arr, target_percentile))
    chosen_idx = int(np.argmin(np.abs(sched_arr - target_value)))
    pct_rank = float((sched_arr <= sched_arr[chosen_idx]).mean() * 100.0)

    iter_cost = float(cost_arr[chosen_idx])
    iter_sched = float(sched_arr[chosen_idx])

    fired_lines: list[str] = []
    if per_risk_cost.size:
        cost_row = per_risk_cost[chosen_idx]
        for j, c in enumerate(cost_row):
            if c > 0:
                rid = risk_ids_all[j] if j < len(risk_ids_all) else f"risk[{j}]"
                fired_lines.append(f"  - {rid}: cost ${c/1e6:.2f}M")
    if per_risk_sched.size:
        sched_row = per_risk_sched[chosen_idx]
        for j, d in enumerate(sched_row):
            if d > 0:
                rid = risk_ids_dual[j] if j < len(risk_ids_dual) else f"risk[{j}]"
                fired_lines.append(f"  - {rid}: schedule contribution {d:.2f} days")

    if not fired_lines:
        return (
            f"Iteration #{chosen_idx + 1}: total cost ${iter_cost/1e6:.2f}M, "
            f"schedule slip {iter_sched:.2f} days. This iteration sits at "
            f"the {pct_rank:.0f}th percentile of the simulated distribution. "
            f"No risks fired with material contribution in this iteration."
        )

    fired_block = "\n".join(fired_lines)
    return (
        f"Monte Carlo iteration #{chosen_idx + 1} (one of {len(cost_arr):,} "
        f"simulated iterations, sitting at the {pct_rank:.0f}th percentile of "
        f"the schedule distribution): total cost ${iter_cost/1e6:.2f}M, "
        f"schedule slip {iter_sched:.2f} days.\n\nRisks that fired in this "
        f"iteration:\n{fired_block}\n\nThis is one of many simulated "
        f"futures the analysis explored; the headline range and distribution "
        f"charts above are the ensemble of all {len(cost_arr):,} such "
        f"iterations."
    )


def build_walkthrough_section(
    integrated_results: dict[str, Any],
    risks: Iterable[Any] | None,
    target_percentile: int = 95,
) -> dict[str, Any]:
    """Build the single-iteration walkthrough section dict.

    Returns
    -------
    dict[str, Any]
        Walkthrough dict with keys:

        * ``walkthrough`` (str): prose paragraph naming the chosen
          iteration's cost, schedule slip, percentile rank, and the
          per-risk firings (or the no-fires variant). Empty string when
          the input arrays are empty.

    Notes
    -----
    The chosen iteration is the one with total schedule slip closest to
    ``target_percentile`` of the schedule-slip distribution (default
    P95). The narrative wrapping that surrounds the walkthrough — intro
    prose, convergence chart, distribution-shape explainer, standards
    references — stays in the composer's page-7 assembly (Decision
    D3=A).
    """
    return {
        "walkthrough": _build_single_iteration_walkthrough(
            integrated_results, risks, target_percentile=target_percentile,
        ),
    }
