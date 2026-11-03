"""RISKDRV-01 stage 2: the owner-view schedule pass, with the shared drivers on.

Plan R2 (b), Director 02/11/2026: the published headline stays the event-risk contingency on the
event-only CPM pass, which is untouched. A second pass replays the same kernel on the run's own
fire record and severity uniforms (as the masked leave-one-out does), with each shared driver's
duration delta added to the activities it maps to. Its finish and delay feed the owner view: the
finish range, the total cost and the JCL.

The driver delta is drawn with the base (``src.integrated.base_layer.deliverable_base_layer``), on
the Layer 1 stream, so a productivity driver's cost and its duration share one draw, and a
quantity driver's duration follows its quantity factor's draw. That shared draw is the link that
makes cost and schedule move together (JCLAXIS-02).

Pure data (hard invariant 9).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

import numpy as np


@dataclass(frozen=True)
class DurationShift:
    """Per-iteration hours added to each activity: ``deltas @ loading``, built one batch at a time.

    ``deltas`` is ``(n_iter, k)``, the drivers' proportional duration deltas; ``loading`` is
    ``(k, n_act)``, each driver's original activity hours on the activities it maps to (in the
    graph's topological order) and zero elsewhere. Low rank, so a 100k run never holds an
    ``(n_iter, n_act)`` array.
    """

    driver_ids: tuple[str, ...]
    deltas: np.ndarray
    loading: np.ndarray

    def batch(self, start: int, end: int) -> np.ndarray:
        return self.deltas[start:end, :] @ self.loading

    def without(self, driver_id: str) -> "DurationShift":
        """This shift with one driver's deltas zeroed, every other driver's draw unchanged."""
        if driver_id not in self.driver_ids:
            raise KeyError(f"RISKDRV-01: no driver {driver_id!r} in the shift")
        deltas = self.deltas.copy()
        deltas[:, self.driver_ids.index(driver_id)] = 0.0
        return DurationShift(self.driver_ids, deltas, self.loading)


def activity_wbs_codes(xer_tables: dict[str, Any]) -> dict[str, str]:
    """Each TASK's WBS short name, by task id as the graph keys activities."""
    task, wbs = xer_tables["TASK"], xer_tables["PROJWBS"]
    short = {str(i): str(s) for i, s in zip(wbs["wbs_id"], wbs["wbs_short_name"])}
    return {str(t): short.get(str(w), "") for t, w in zip(task["task_id"], task["wbs_id"])}


def schedule_wbs_codes(xer_tables: dict[str, Any]) -> tuple[str, ...]:
    """The schedule's WBS short names, for ``validate_shared_drivers``."""
    return tuple(str(s) for s in xer_tables["PROJWBS"]["wbs_short_name"])


def build_duration_shift(
    shared_drivers: Sequence[Any],
    driver_deltas: dict[str, np.ndarray],
    graph: Any,
    xer_tables: dict[str, Any],
) -> DurationShift | None:
    """The shift the owner-view pass adds, or ``None`` when no driver is declared."""
    if not shared_drivers:
        return None
    wbs_of = activity_wbs_codes(xer_tables)
    order = tuple(graph.topo_order)
    hours = np.array([graph.activities[a].original_duration_hours for a in order], float)
    ids = tuple(d.driver_id for d in shared_drivers)
    loading = np.zeros((len(ids), len(order)), dtype=float)
    for i, d in enumerate(shared_drivers):
        codes = set(d.wbs_codes)
        bound = np.array([wbs_of.get(str(a), "") in codes for a in order])
        if not bound.any():
            raise ValueError(f"RISKDRV-01: driver {d.driver_id} maps to no activity")
        loading[i, bound] = hours[bound]
    deltas = np.stack([np.asarray(driver_deltas[k], float) for k in ids], axis=1)
    return DurationShift(driver_ids=ids, deltas=deltas, loading=loading)


def owner_view(
    replay_finish_days: Callable[[DurationShift | None], np.ndarray],
    shift: DurationShift | None,
    *,
    event_only_finish_days: np.ndarray,
    deterministic_finish_days: float,
) -> dict[str, Any] | None:
    """The owner-view finish and delay, or ``None`` when no driver is declared.

    ``replay_finish_days(shift)`` replays the run's own kernel and returns per-iteration finish
    days. It is called first with ``None`` as a positive control: a replay that does not
    reproduce the event-only finish would pair unlike draws, so it is refused.

    The owner-view delay is finish less the zero-risk pass, **not floored at zero**: a driver can
    shorten work, and an early finish saves time-dependent cost as a late one adds it.
    """
    if shift is None:
        return None
    control = np.asarray(replay_finish_days(None), dtype=float)
    if not np.array_equal(control, np.asarray(event_only_finish_days, dtype=float)):
        raise ValueError(
            "RISKDRV-01: the owner-view replay without drivers does not reproduce the run's "
            "finish, so it would not hold the event draws fixed; refused")
    finish = np.asarray(replay_finish_days(shift), dtype=float)
    # RISKDRV-01 stage 3 (S2, Director 03/11/2026): one replay per driver with that driver's
    # delta zeroed and every other draw held - the masked leave-one-out the risk tornado uses.
    masked = {k: np.asarray(replay_finish_days(shift.without(k)), dtype=float)
              for k in shift.driver_ids}
    return {
        "driver_ids": list(shift.driver_ids),
        "finish_days": finish,
        "delay_days": finish - float(deterministic_finish_days),
        "event_finish_days": control,
        "finish_days_without": masked,
        "deterministic_finish_days": float(deterministic_finish_days),
    }


def stage3_owner_view(
    stage3_result: Any, schedule_mc_config: Any, shift: DurationShift | None,
) -> dict[str, Any] | None:
    """:func:`owner_view` on a ``Stage3IntegratedResult``, replaying its own kernel."""
    from src.integrated.integrated_simulation_stage3 import cost_arm_fire_mask
    from src.rng_streams import kernel_generator
    from src.sra.cpm.cpm_simulation import run_schedule_mc

    if shift is None:
        return None
    r = stage3_result
    ids = tuple(r.risk_drivers.keys())
    severity = np.stack([r.severity_uniforms_by_risk_id[k] for k in ids], axis=1)
    mask = cost_arm_fire_mask(r.cost_result, ids)

    def replay(s: DurationShift | None) -> np.ndarray:
        out = run_schedule_mc(
            graph=r.schedule_graph, risk_drivers=r.risk_drivers, config=schedule_mc_config,
            severity_uniforms=severity, rng=kernel_generator(int(r.seed_used)),
            criticality_measurement_mode=r.config_summary["criticality_measurement_mode"],
            fire_mask=mask, duration_shift=s,
        )
        return np.asarray(out.project_finish_days, dtype=float)

    return owner_view(
        replay, shift,
        event_only_finish_days=np.asarray(r.schedule_result.project_finish_days, dtype=float),
        deterministic_finish_days=float(r.config_summary["deterministic_baseline_days"]),
    )


#: Stated beside the driver columns, so they are not read as contributions that add up.
DRIVER_LEAVE_ONE_OUT_METHOD = (
    "leave-one-out at P{p} on the owner view: each figure is the owner-view P{p} with the "
    "driver, less the P{p} with that driver removed (its cost and its duration change) and every "
    "other draw held fixed. They do not sum, as the risk tornado's do not."
)


def driver_leave_one_out(
    *, base_array: np.ndarray, base_without_driver: dict[str, np.ndarray],
    cost_dollars_array: np.ndarray, owner: dict[str, Any], day_rate: float, p_level: int = 80,
) -> dict[str, dict[str, float]]:
    """What each shared driver adds to the owner-view total and finish at ``p_level``.

    ``owner`` is :func:`owner_view`'s dict. Per driver: the total with it is base + event cost +
    owner delay x rate; without it, the base without its cost (a ``Q`` driver adds none, so its
    base is unchanged) + event cost + its masked delay x rate. Report and period JSON both call
    this, so the two agree by construction.
    """
    base = np.asarray(base_array, dtype=float)
    cost = np.asarray(cost_dollars_array, dtype=float)
    rate = float(day_rate)
    det = float(owner["deterministic_finish_days"])
    finish = np.asarray(owner["finish_days"], dtype=float)
    total = base + (cost + (finish - det) * rate)
    p_total = float(np.percentile(total, p_level))
    p_finish = float(np.percentile(finish, p_level))
    out: dict[str, dict[str, float]] = {}
    for k in owner["driver_ids"]:
        f_wo = np.asarray(owner["finish_days_without"][k], dtype=float)
        b_wo = np.asarray(base_without_driver.get(k, base), dtype=float)
        t_wo = b_wo + (cost + (f_wo - det) * rate)
        out[k] = {
            "total_p_dollars": p_total - float(np.percentile(t_wo, p_level)),
            "finish_p_days": p_finish - float(np.percentile(f_wo, p_level)),
        }
    return out


def driver_rows(shared_drivers: Sequence[Any], view: dict[str, Any] | None,
                driver_deltas: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    """One row per driver for the report: kind, range and its mean duration delta drawn."""
    rows = []
    for d in shared_drivers:
        delta = np.asarray(driver_deltas[d.driver_id], float)
        if d.kind == "P":
            rng = f"{d.p10:+.0%} / {d.mode:+.0%} / {d.p90:+.0%}"
            source = f"own range; cost on {', '.join(d.grid_rows)} ({', '.join(d.grid_columns)})"
        else:
            rng = f"from {d.linked_factors[0]} x {d.elasticity:g}"
            source = f"quantity factor {d.linked_factors[0]}; no added cost"
        rows.append({
            "driver_id": d.driver_id, "name": d.name, "kind": d.kind,
            "wbs_codes": list(d.wbs_codes), "range": rng, "source": source,
            "mean_delta": float(delta.mean()), "p80_delta": float(np.percentile(delta, 80)),
            "basis": d.basis,
        })
    return rows


def load_checked_drivers(register_path: Any, xer_tables: dict[str, Any],
                         risk_ids: Sequence[str] | None = None) -> tuple[Any, ...]:
    """The register's shared drivers, checked against its Layer 1 and the schedule.

    ``()`` when the register declares none. ``risk_ids`` defaults to the register's own.
    """
    from src.integrated.base_layer import register_layer1
    from src.shared_drivers import read_shared_drivers, validate_shared_drivers

    drivers = read_shared_drivers(register_path)
    if not drivers:
        return ()
    if risk_ids is None:
        from src.v5_register_reader import read_risks_v5
        risk_ids = [str(r.risk_id) for r in read_risks_v5(str(register_path))]
    validate_shared_drivers(drivers, layer1=register_layer1(register_path),
                            wbs_codes=schedule_wbs_codes(xer_tables), risk_ids=risk_ids)
    return drivers
