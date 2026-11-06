"""REPORTCOH-01 R3: Appendix A, one iteration of the CPM replay worked through by hand.

The old walkthrough picked an iteration at the 95th percentile of the schedule slip, listed the
retired Mode-scaled delays, and ended there: a reader could not get from what it showed to the
headline. This one picks the iteration whose integrated contingency is nearest the headline
P80, and walks it from the risks that fired to that figure:

1. each risk that fired, its probability, the cost it drew and the delay it injected at its
   gating activity;
2. the delays injected, set against the slip the replay found, the difference being what float
   and parallel paths absorbed;
3. the slip priced at the day rate, added to the event-risk cost, which is that iteration's
   integrated contingency, and where it sits against the P80.

Every figure is read from the arrays the run produced (pure data, hard invariant 9). The chart
is drawn only when the run has a chart folder.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

HEADING_TABLE = "What fired in this iteration"


def _m(dollars: float) -> str:
    return f"${dollars / 1e6:.2f}M"


def pick_iteration(totals: np.ndarray, p_level: int = 80) -> int:
    """The iteration whose integrated contingency is nearest the P-level (lowest index on a tie)."""
    target = float(np.percentile(totals, p_level))
    return int(np.argmin(np.abs(totals - target)))


def worked_iteration(beta: dict[str, Any] | None, *, day_rate: float,
                     risks: list[Any] | None, titles: dict[str, str] | None,
                     p_level: int = 80, chart_dir: Path | str | None = None) -> dict[str, Any]:
    """Appendix A content: intro, the fired-risk table, the reconciliation, the chart path."""
    if not beta:
        return {}
    cost = np.asarray(beta.get("cost_dollars_array", []), dtype=float)
    slip = np.asarray(beta.get("schedule_days_array", []), dtype=float)
    if cost.size == 0 or slip.size != cost.size:
        return {}
    titles = dict(titles or {})
    totals = cost + slip * float(day_rate)
    i = pick_iteration(totals, p_level)
    p_value = float(np.percentile(totals, p_level))
    rank = float((totals <= totals[i]).mean() * 100.0)

    ids_all = list(beta.get("risk_ids_all") or [])
    ids_dual = list(beta.get("risk_ids_dual") or [])
    per_cost = np.asarray(beta.get("per_risk_cost_array", []), dtype=float)
    fired_all = np.asarray(beta.get("fired_array", []), dtype=bool)
    # The delay drawn and injected at the gating activity: the replay's input, before any float.
    injected = np.asarray(beta.get("per_risk_schedule_pre_mode_array", []), dtype=float)
    drivers = beta.get("risk_drivers") or {}
    graph = beta.get("schedule_graph")
    prob = {str(getattr(r, "risk_id", "")): float(getattr(r, "probability", 0.0) or 0.0)
            for r in (risks or [])}

    def gate_name(rid: str) -> str:
        d = drivers.get(rid)
        gid = getattr(d, "gating_activity_id", None) if d is not None else None
        act = getattr(graph, "activities", {}).get(gid) if gid and graph is not None else None
        return str(getattr(act, "name", "") or gid or "-")

    inj_by_id = ({rid: float(injected[i, j]) for j, rid in enumerate(ids_dual)}
                 if injected.ndim == 2 and injected.shape[0] == cost.size else {})
    rows: list[dict[str, str]] = []
    for j, rid in enumerate(ids_all):
        fired = bool(fired_all[i, j]) if fired_all.ndim == 2 else per_cost[i, j] > 0
        if not fired:
            continue
        days = inj_by_id.get(rid, 0.0)
        rows.append({
            "Risk": f"{rid} {titles.get(rid, '')}".strip(),
            "Probability": f"{prob[rid]:.0%}" if rid in prob else "-",
            "Cost drawn ($M)": _m(float(per_cost[i, j])),
            "Delay injected (working days)": f"{days:.1f}" if rid in inj_by_id else "-",
            "Gating activity": gate_name(rid) if rid in inj_by_id else "cost only",
        })

    total_injected = sum(inj_by_id.values())
    if rows:
        rows.append({"Risk": "Total", "Probability": "",
                     "Cost drawn ($M)": _m(float(cost[i])),
                     "Delay injected (working days)": f"{total_injected:.1f}",
                     "Gating activity": ""})
    s = float(slip[i])
    absorbed = total_injected - s
    delay_cost = s * float(day_rate)
    body = rows[:-1]
    n_fired = len(body)
    n_delay = sum(1 for r in body if r["Gating activity"] != "cost only")
    intro = (
        f"This appendix follows one of the {cost.size:,} iterations from the risks that fired to "
        f"its integrated contingency, using the same arithmetic as every other iteration. It is "
        f"iteration {i + 1}, chosen because its integrated contingency, {_m(totals[i])}, is the "
        f"nearest to the P{p_level} headline of {_m(p_value)}: {rank:.0f}% of iterations come in "
        f"at or below it. The chart below marks where it sits on the S-curve.")
    steps = [
        f"In this iteration {n_fired} of the register's {len(ids_all)} event risks fired, "
        f"{n_delay} of them with a delay. Each delay is injected at its gating activity in the "
        "programme; the table lists them.",
        f"The delays injected add to {total_injected:.1f} working days. The CPM replay moved the "
        f"finish by {s:.1f}: {absorbed:.1f} working days were absorbed by float or ran on a path "
        "parallel to a longer one, so did not reach the finish.",
        f"The finish delay of {s:.1f} working days at ${float(day_rate):,.0f} per working day is "
        f"{_m(delay_cost)} of delay cost. Added to the {_m(cost[i])} of event-risk cost drawn, "
        f"that is {_m(totals[i])}, this iteration's integrated contingency.",
        f"The headline P{p_level} is not this iteration: it is the value {p_level}% of all "
        f"{cost.size:,} iterations do not exceed. This iteration happens to land near it; another "
        "near it would have different risks firing.",
    ]
    owner = (beta.get("base_layer") or {}).get("owner_view") or {}
    finish = owner.get("finish_days")
    planned = owner.get("deterministic_finish_days")
    if finish is not None and planned:
        f_i = float(np.asarray(finish, dtype=float)[i])
        steps.append(
            f"In the owner view, where the shared drivers also stretch activity durations, the "
            f"same iteration finishes at working day {f_i:.0f}, {f_i - float(planned):.0f} "
            "working days after the plan.")

    chart_path = ""
    if chart_dir:
        try:
            from src.final.charts import make_worked_iteration_chart
            chart_path = str(make_worked_iteration_chart(
                totals / 1e6, float(totals[i]) / 1e6, p_level,
                Path(chart_dir) / "appendix_a_worked_iteration.png",
                label=f"Iteration {i + 1}").resolve())
        except Exception as exc:  # the appendix reads without its chart
            logger.warning("REPORTCOH-01 R3: worked-iteration chart not drawn: %s", exc)

    return {
        "worked_iteration_intro": intro,
        "worked_iteration_chart_path": chart_path,
        "worked_iteration_table_heading": HEADING_TABLE,
        "worked_iteration_table": rows,
        "worked_iteration_steps": steps,
    }
