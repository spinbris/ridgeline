"""Stage 3 inputs: the config, the joint severity draw and the injection-method default.

These three pieces run on every project. They lived in a single project's binding module
until REFRETIRE-01, which is why the config class carried that project's paths, CG map and
float threshold as its field defaults - values every other project inherited silently.
**Nothing here has a project default.** A run states its own register, schedule and strawman,
and its own float threshold, or it does not start.

Joint sampling (METHODOLOGY.md §6, SPEC R-10): one severity uniform per ``(iteration, risk)``
is drawn BEFORE either arm runs, and both arms index it by ``risk_id``. For a dual-coded risk
the cost and schedule PERT draws therefore come from the same ``U(0, 1)``, which is the positive
cost/schedule correlation the deliverable reports. The fire decision is separate and shared the
same way (``src.qra_core.draw_fire_matrix``), on its own stream (``src.rng_streams``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

from src.sra.cpm.risk_driver_schema import InjectionMethod


__all__ = [
    "Stage3BindingConfig",
    "build_joint_severity_uniforms",
    "resolve_default_injection_method",
    "resolve_float_threshold_hours",
]


@dataclass(frozen=True)
class Stage3BindingConfig:
    """The inputs a Stage 3 run reads, and the knobs it reads them with.

    Frozen for hashability and so the audit summary cannot be edited after the fact. Path
    existence is checked at use, not at construction, so a test harness can build one without
    the files on disk.

    Attributes
    ----------
    register_path : Path
        Risk register workbook (``.xlsx``).
    xer_path : Path
        Primavera P6 export (``.xer``).
    strawman_path : Path
        SRA strawman workbook (``.xlsx``); supplies the risk scope and per-risk schedule
        parameters.
    float_threshold_hours : float
        Filter B float threshold for the auto-mapper, in working hours. **Required**: it
        decides which activities bind, so a threshold borrowed from another project moves the
        schedule arm without saying anything. Every binding declares its own
        (``ProjectBinding.float_threshold_hours``); validated as positive here.
    cg_coefficients : dict[str, float]
        CG correlation coefficient map, empty unless the caller supplies the active project's.
    default_injection_method : InjectionMethod | None
        ``None`` (the default) means the register's ``Default_Injection_Method`` (RS-D-6,
        D-18); a value pins the method for a diagnostic run. There is no code default.
    populate_modes_from_strawman : bool
        Reported in the run's config summary; the rule builder reads ``Mode_Aggregated`` from
        the strawman row either way.
    apply_mode_multipliers : bool
        Per-run record of the Mode-multiplier call (SR15: off on the Stage 3 full-CPM path).
        The kernel reads its own ``ScheduleMCConfig.apply_mode_multipliers``, never this.
    """

    register_path: Path
    xer_path: Path
    strawman_path: Path
    float_threshold_hours: float
    cg_coefficients: dict[str, float] = field(default_factory=dict)
    default_injection_method: InjectionMethod | None = None
    populate_modes_from_strawman: bool = False
    apply_mode_multipliers: bool = True

    def __post_init__(self) -> None:
        if self.float_threshold_hours <= 0:
            raise ValueError(
                "float_threshold_hours must be positive; got "
                f"{self.float_threshold_hours}"
            )


def resolve_float_threshold_hours(
    project: str | None = None, *, binding: object | None = None,
) -> float:
    """The Filter B float threshold a project declares: the named one, the active one, or the
    binding the caller already holds.

    REFRETIRE-01: this was a field default on the config class, carrying one project's
    threshold onto every route that did not override it. The threshold decides which activities
    bind, so a borrowed one moves the schedule arm silently; a binding that declares none is
    refused by name instead. Imported lazily, as :mod:`src.defaults` does, so the engine reads
    the binding at call time rather than at import.
    """
    from src.sra.cpm.bindings import get_active_binding, get_binding

    if binding is None:
        binding = get_binding(project) if project else get_active_binding()
    value = getattr(binding, "float_threshold_hours", None)
    if value is None:
        raise ValueError(
            f"project {getattr(binding, 'name', project)!r} declares no float_threshold_hours "
            f"in its binding. A float threshold borrowed from another project changes which "
            f"activities bind, and so moves the schedule arm, without saying anything."
        )
    return float(value)


def resolve_default_injection_method(config: Stage3BindingConfig) -> str:
    """The injection method a dual-coded risk takes when its register row pins none
    (RS-D-6, D-18): the caller's explicit pin if set, else the register's value. Never a
    code default."""
    if config.default_injection_method is not None:
        return str(config.default_injection_method)
    from src.sra.methodology_defaults_reader import read_default_injection_method
    return read_default_injection_method(
        config.register_path, caller_module="src/integrated/stage3_inputs.py")


def build_joint_severity_uniforms(
    *,
    risk_ids: tuple[str, ...] | list[str],
    n_iter: int,
    rng: np.random.Generator,
    precision: Literal["float32", "float64"] = "float32",
) -> dict[str, np.ndarray]:
    """Build the joint per-risk severity uniform map.

    Draws a ``(n_iter,)`` ``U(0, 1)`` array per ``risk_id`` in input order. Iteration order
    locks the RNG draw order, so two runs with the same ``rng`` seed and the same ``risk_ids``
    sequence produce bit-identical output. Consumers index by ``risk_id`` lookup, never by
    column position, so a dict-order change on the consumer side cannot misalign the arms.

    Parameters
    ----------
    risk_ids : tuple[str, ...] | list[str]
        ALL risks in the simulation (cost-only and dual-coded), in the order the cost engine
        consumes them - ``risk_ids_all`` from :func:`run_integrated_simulation`. The schedule
        arm consumes the dual-coded subset by lookup.
    n_iter : int
        Iteration count. Must match the run's ``IntegratedConfig.iterations`` and
        ``ScheduleMCConfig.n_iter``.
    rng : np.random.Generator
        The severity stream, drawn from once per ``risk_id``. Must not be the fire draw's
        stream: pass :func:`src.rng_streams.severity_generator` (RNGSTREAM-01).
    precision : {"float32", "float64"}
        Output dtype, default ``"float32"``.

    Returns
    -------
    dict[risk_id, np.ndarray]
        ``{risk_id: U(0, 1) array of shape (n_iter,)}`` for every ``risk_id`` in input order.
    """
    if n_iter <= 0:
        raise ValueError(f"n_iter must be positive; got {n_iter}")
    if precision not in ("float32", "float64"):
        raise ValueError(
            f"precision must be 'float32' or 'float64'; got {precision!r}"
        )

    dt = np.dtype(precision)
    result: dict[str, np.ndarray] = {}
    for rid in risk_ids:
        # rng.random returns float64; cast to the schedule orchestrator's working dtype so the
        # joint-sampling matrix stays aligned with its precision plumbing.
        result[str(rid)] = rng.random(n_iter).astype(dt, copy=False)
    return result
