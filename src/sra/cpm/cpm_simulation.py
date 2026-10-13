"""Schedule Monte Carlo orchestrator (project-agnostic).

This module is the iteration-loop orchestrator for the Stage 3 schedule
arm. It wires the upstream Beta modules into a streaming, chunked Monte
Carlo simulation:

* :mod:`src.sra.cpm.graph` provides the topologically-sorted activity
  graph (Beta-02).
* :mod:`src.sra.cpm.risk_injection` produces a per-batch
  ``(batch_n, n_act)`` duration array (Beta-04).
* :mod:`src.sra.cpm.cpm_kernel` runs forward + backward + slack +
  critical-path on each batch (Beta-03).
* This module reduces, accumulates, and returns a frozen
  :class:`ScheduleMCResult` dataclass.

The orchestrator does NOT build the graph, do CPM math, sample risk
deltas, run the auto-mapper, read the register or the .xer file, or
render outputs. Each of those is a different module's job. The
orchestrator is a pure wiring layer plus chunking and streaming
aggregation.

Public surface
--------------
* :class:`ScheduleMCConfig` — frozen dataclass of universal sampling
  knobs (n_iter, batch_size, seed, precision, mode, audit-path).
* :class:`ScheduleMCResult` — frozen dataclass of per-iteration finish
  distribution + per-activity criticality index + run metadata.
* :func:`run_schedule_mc` — top-level entry point.

Severity-uniform alignment contract
-----------------------------------
Column ``j`` of ``severity_uniforms`` is consumed by the risk at index
``j`` of ``iter(risk_drivers.keys())``. Same risk in cost arm and
schedule arm; same column. The orchestrator does NOT permute the matrix
and does NOT re-sort the drivers dict — the caller (binding or test
harness) is responsible for constructing ``severity_uniforms`` against
the same ``risk_drivers`` dict order it passes in. A shape mismatch
raises :class:`ValueError` rather than silently misaligning Bernoulli
draws.

Mode gating
-----------
``mode == "prod"`` raises :class:`ValueError` if any
:class:`~src.sra.cpm.risk_driver_schema.RiskDriver` in ``risk_drivers``
has ``derived_at_run_time=True``. Production runs cannot consume
auto-mapper output. The list of offending risk_ids is surfaced in the
error message. The result's ``beta_flag`` is the same scan inverted:
``True`` iff any driver is auto-mapped.

Chunked iteration
-----------------
The full ``(n_iter, n_act)`` duration array is never materialised. Per
batch, ``risk_injection.build_duration_array`` is called with
``batch_n = min(batch_size, n_iter - batch_start)``;
``cpm_kernel.run_batch`` consumes the resulting ``(batch_n, n_act)``
array; the orchestrator immediately reduces to a scalar per-iteration
``project_finish`` and a per-activity on-critical-path bool, accumulates,
and discards the per-iteration matrices before allocating the next
batch.

Streaming aggregation
---------------------
Two state arrays are maintained across batches:

* ``finish_hours_full`` of shape ``(n_iter,)``, precision-typed —
  populated batch-by-batch into contiguous slices.
* ``cp_count`` of shape ``(n_act,)``, ``int64`` — running count of
  iterations where each activity was on the critical path; incremented
  by ``+= on_critical_path.sum(axis=0)`` per batch.

The criticality index is the final ``cp_count / n_iter`` per activity.

Reproducibility
---------------
``rng.spawn(n_batches)`` per numpy ≥ 1.25 produces deterministic
per-batch sub-generators. Re-running with the same
``(graph, risk_drivers, config, severity_uniforms)`` produces a
bit-identical :class:`ScheduleMCResult`.

Precision policy
----------------
Default ``float32`` per ``STAGE3_ROADMAP.md`` §3.3 / Beta-00 §5.
``float64`` is opt-in via :attr:`ScheduleMCConfig.precision`. Explicit
``.astype(dt, copy=False)`` at every numpy boundary; scalars pre-cast
via ``dt.type(...)``. Same regression class as Beta-03 Finding 1 and
Beta-04 §7 Risk 3, mitigated proactively.

This module is project-agnostic — no project paths, file names, or
project codes appear here. The reusability invariant is locked by the
synthetic-graph tests in
:mod:`tests.sra.cpm.test_cpm_simulation` and
:mod:`tests.sra.cpm.test_cpm_simulation_integration`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, TYPE_CHECKING, Any, Literal

import numpy as np

# Runtime imports — these are pulled in at every batch call site.
# Hoisted to module scope (rather than local in ``_run_one_batch``)
# because the current package layout has no circular-import path:
# kernel and risk_injection both import from graph / calendar /
# risk_driver_schema, none of which import this module.
from src.sra.cpm.cpm_kernel import (
    accumulate_batch_stats as _accumulate_batch_stats,
)
from src.sra.cpm.cpm_kernel import run_batch as _kernel_run_batch
from src.rng_streams import require_seed
from src.sra.cpm.risk_injection import build_duration_array as _build_duration_array

if TYPE_CHECKING:
    from src.sra.cpm.graph import ScheduleGraph
    from src.sra.cpm.risk_driver_schema import RiskDriver


logger = logging.getLogger(__name__)


Precision = Literal["float32", "float64"]
SimulationMode = Literal["beta", "prod"]

#: SR10.A — Criticality measurement mode. Selects whether the per-risk
#: Mode multiplier (Series=1.0, Hybrid=0.5, Parallel=0.0) is honoured
#: per-driver ("mode_conditioned", the default and pre-SR10.A semantics
#: when the binding does not populate Mode) or overridden uniformly to
#: 1.0 per AACE 65R-11 §5.4 ("mode_independent"). ``"both"`` runs the
#: simulation twice over one shared set of per-batch sub-generators —
#: spawned once, then each restored to its pre-first-pass state before
#: the second pass — so the two passes draw identical Bernoulli fires and
#: PERT magnitudes and any divergence between the measurements is
#: attributable solely to the Mode multiplier, not to sampling noise
#: (SR10.F). See :func:`run_schedule_mc`'s "both" branch.
CriticalityMeasurementMode = Literal[
    "mode_conditioned",
    "mode_independent",
    "both",
]

_CRITICALITY_MEASUREMENT_MODES: tuple[str, ...] = (
    "mode_conditioned",
    "mode_independent",
    "both",
)


__all__ = [
    "Precision",
    "SimulationMode",
    "CriticalityMeasurementMode",
    "ScheduleMCConfig",
    "ScheduleMCResult",
    "run_schedule_mc",
]


# ---------------------------------------------------------------------------
# Configuration and result dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScheduleMCConfig:
    """Universal knobs for the schedule MC orchestrator.

    Project-agnostic. Project-specific values (paths, CG map, register
    column names) live in the binding layer (Beta-06). Defaults match
    the Stage 3 roadmap, §3.3, and the Beta-00 foundation brief, §5.

    Attributes
    ----------
    n_iter : int
        Total Monte Carlo iterations. Default 100,000.
    batch_size : int
        Per-batch iteration count for the chunked loop. Default 10,000.
        ``batch_size > n_iter`` is allowed and degrades to a single-batch
        run; logged at INFO.
    seed : int | None
        Master seed for reproducibility. No default (SEEDZERO-01): ``None`` is refused by
        :func:`run_schedule_mc` unless the caller passes its own ``rng``.
    precision : {"float32", "float64"}
        Working precision plumbed through to
        :func:`~src.sra.cpm.risk_injection.build_duration_array` and
        :func:`~src.sra.cpm.cpm_kernel.run_batch`. Default ``"float32"``.
    project_start_hours : float
        Working-hour offset that anchors the schedule. Default ``0.0``.
        Forwarded to the kernel via ``project_start``.
    mode : {"beta", "prod"}
        Run mode. ``"beta"`` accepts auto-mapper output; ``"prod"`` raises
        :class:`ValueError` if any driver is auto-mapped (i.e.
        ``derived_at_run_time=True``). Default ``"beta"``.
    beta_flag_threshold_days : float
        Path-crossover delta WARN threshold (days) carried forward from
        Beta-00 §5; informational only at this level — Beta-08's banner
        logic consults it. Default ``30.0``.
    auto_mapper_audit_path : Path | None
        Pointer to the parquet audit trail written by Beta-04's
        :func:`~src.sra.cpm.auto_mapper.write_audit_trail`. The
        orchestrator does NOT write here — it only carries the path
        through to :attr:`ScheduleMCResult.auto_mapper_audit_path` for
        Beta-08's banner application. Default ``None``.
    apply_mode_multipliers : bool
        SR15. Methodology switch governing whether the per-iteration
        risk-impact magnitude is scaled by the driver's declared Mode
        (Series=1.0 / Hybrid=0.5 / Parallel=0.0) via
        the register's Mode multiplier grid (``config.mode_multipliers``) before being applied
        to activity duration deltas. ``True`` (default) preserves the
        pre-SR15 Stage 2.5 behaviour: per-driver lookup against
        ``mode_multipliers[driver.mode]``. ``False`` drops the multiplier
        entirely — every fired risk's PERT magnitude is applied at full
        strength regardless of Mode classification. The Stage 3 full-CPM
        path sets this to ``False`` because the CPM kernel walks the
        network and consumes float directly per iteration; layering a
        Stage 2.5-era practitioner-judgement multiplier on top of the
        CPM mechanics would double-count. Driver Mode classification is
        preserved on :class:`~src.sra.cpm.risk_driver_schema.RiskDriver`
        regardless — the flag affects engine behaviour, not driver data.
        Reproducibility: with ``apply_mode_multipliers=True`` the engine
        is bit-identical to pre-SR15 behaviour (default value preserves
        Stage 2.5 lock continuity). Default ``True``.

    Raises
    ------
    ValueError
        If ``n_iter <= 0``, ``batch_size <= 0``, ``precision`` is not in
        ``{"float32", "float64"}``, or ``mode`` is not in
        ``{"beta", "prod"}``.
    """

    n_iter: int = 100_000
    batch_size: int = 10_000
    seed: int | None = None
    precision: Precision = "float32"
    project_start_hours: float = 0.0
    mode: SimulationMode = "beta"
    beta_flag_threshold_days: float = 30.0
    auto_mapper_audit_path: Path | None = None
    apply_mode_multipliers: bool = True
    #: RS-D-3b (D-15, shape A): the register's Mode multiplier grid, required, no
    #: default. Read it with ``methodology_defaults_reader.read_mode_multipliers``.
    mode_multipliers: Mapping[str, float] = field(kw_only=True)

    def __post_init__(self) -> None:
        if not self.mode_multipliers:
            raise ValueError("mode_multipliers must be the register's non-empty Mode multiplier grid (RS-D-3)")
        if self.n_iter <= 0:
            raise ValueError(f"n_iter must be positive; got {self.n_iter}")
        if self.batch_size <= 0:
            raise ValueError(
                f"batch_size must be positive; got {self.batch_size}"
            )
        if self.batch_size > self.n_iter:
            logger.info(
                "ScheduleMCConfig: batch_size %d >= n_iter %d; "
                "single-batch run",
                self.batch_size,
                self.n_iter,
            )
        if self.precision not in ("float32", "float64"):
            raise ValueError(
                f"precision must be 'float32' or 'float64'; "
                f"got {self.precision!r}"
            )
        if self.mode not in ("beta", "prod"):
            raise ValueError(
                f"mode must be 'beta' or 'prod'; got {self.mode!r}"
            )


@dataclass(frozen=True)
class ScheduleMCResult:
    """Per-iteration project-finish distribution + per-activity criticality.

    Returned by :func:`run_schedule_mc`. All array fields are
    precision-typed per :attr:`ScheduleMCConfig.precision`; counts and
    indices are native ``int`` / ``float`` for readability.

    Attributes
    ----------
    project_finish_hours : np.ndarray
        Shape ``(n_iter,)``; per-iteration project finish in working
        hours. Dtype = ``precision``.
    project_finish_days : np.ndarray
        Shape ``(n_iter,)``; ``project_finish_hours`` divided by the
        graph's ``project_default_calendar.working_hours_per_day``.
        Dtype = ``precision``.
    criticality_index : dict[str, float]
        Activity id → probability of being on the critical path
        (``on_critical_path_count / n_iter``). Iteration order matches
        ``activity_ids``.
    on_critical_path_count : dict[str, int]
        Activity id → integer count of iterations where the activity
        was flagged on the critical path.
    n_iter : int
        Iterations actually run (matches ``config.n_iter``).
    n_act : int
        Number of activities in the graph.
    n_risks : int
        Number of risk drivers consumed.
    n_batches : int
        Number of chunked batches actually run.
    seed_used : int | None
        The seed value the orchestrator threaded through to
        :func:`numpy.random.default_rng` when constructing the run's
        master ``rng``. When the caller passes an explicit ``rng`` to
        :func:`run_schedule_mc`, the master rng was NOT seeded from
        ``config.seed`` — the field is set to ``None`` to signal that
        the run's seed is not recoverable from this audit field; the
        caller's rng provenance lives elsewhere.
    config_summary : dict[str, Any]
        Frozen dict of the most diagnostically useful
        :class:`ScheduleMCConfig` fields, for inclusion in run logs and
        the audit trail.
    beta_flag : bool
        ``True`` iff any :class:`RiskDriver` in the input had
        ``derived_at_run_time=True``. In ``mode="prod"`` this is always
        ``False`` (the mode gate raises before the result is built).
    auto_mapper_audit_path : Path | None
        Mirrored from :attr:`ScheduleMCConfig.auto_mapper_audit_path`.
        Beta-08's banner logic consumes this together with
        :attr:`beta_flag`.
    activity_ids : tuple[str, ...]
        ``tuple(graph.topo_order)`` at construction time. Locks the
        column order of the per-iteration array reductions; consumers
        index ``project_finish_*`` by iteration and look up activities
        via :attr:`criticality_index` / :attr:`on_critical_path_count`.
        Same ordering pins :attr:`total_float_mean_hours` and
        :attr:`total_float_std_hours` column index ``j`` ↔
        ``activity_ids[j]``.
    risk_ids : tuple[str, ...]
        ``tuple(risk_drivers.keys())`` in iteration order. Locks the
        severity-uniform column order — column ``j`` corresponds to
        ``risk_ids[j]``.
    total_float_mean_hours : np.ndarray
        Shape ``(n_act,)``, dtype = ``precision``. Per-activity mean
        total-float across iterations, in working hours. Computed at
        result-construction time from the streaming sum accumulator.
        Beta-12 — defaults to an empty array on legacy callers that
        construct :class:`ScheduleMCResult` directly without populating
        the criticality fields.
    total_float_std_hours : np.ndarray
        Shape ``(n_act,)``, dtype = ``precision``. Per-activity standard
        deviation of total-float across iterations, in working hours.
        Computed via ``sqrt(max(0, sum_sq/n - mean²))``; the floor at
        zero suppresses tiny negative variances arising from numerical
        cancellation when the activity's float is constant across
        iterations. Beta-12.
    deterministic_critical_path : tuple[str, ...]
        Activity ids on the critical path under a single zero-risk pass
        (every duration frozen at the activity's
        :attr:`~src.sra.cpm.graph.Activity.original_duration_hours`,
        no Bernoulli firing, no PERT sampling). The activity *set* with
        ``slack ≤ CRITICAL_PATH_TOL``; for chains with float ties this
        is a superset of any single longest path. Beta-12 §7 Risk 3.
    mode_independent_criticality_index : dict[str, float] | None
        SR10.A. Per AACE 65R-11 §5.4 "true" criticality measurement —
        each Time=Yes risk's PERT impact applied at multiplier 1.0
        regardless of declared Mode, then the fraction of iterations
        the activity sat on the critical path. ``None`` on legacy runs
        (``criticality_measurement_mode="mode_conditioned"``); populated
        on ``"both"`` runs with the AACE-correct CI for every activity
        in :attr:`activity_ids`. The mode-conditioned CI is the
        existing :attr:`criticality_index` field. Iteration order
        matches :attr:`activity_ids`.
    finish_mean_hours : np.ndarray
        SR10.D. Shape ``(n_act,)``, dtype ``float64``. Per-activity
        mean of early-finish (EF) across iterations, in working hours.
        Computed at result-construction time from the streaming
        finish-sum accumulator (same population-mean formula as
        :attr:`total_float_mean_hours`). Reflects the
        **Mode-conditioned** distribution. Under
        ``criticality_measurement_mode="both"``, the Mode-independent
        analogue is :attr:`mode_independent_finish_mean_hours` (SR10.E) —
        prior to SR10.E the second pass's finish-stat accumulators were
        discarded; they are now captured. Defaults to an empty array on
        legacy callers that construct :class:`ScheduleMCResult` directly
        without populating the new fields; ``run_schedule_mc`` always
        populates with real values. Downstream lognormal-fit / normal-fit
        consumers (e.g. AM02 active-management dashboard) consume this
        alongside :attr:`finish_std_hours`.
    finish_std_hours : np.ndarray
        SR10.D. Shape ``(n_act,)``, dtype ``float64``. Per-activity
        standard deviation of EF across iterations, in working hours.
        Computed via ``sqrt(max(0, sum_sq/n - mean²))``; the floor at
        zero suppresses tiny negative variances arising from numerical
        cancellation when an activity's EF is constant across iterations.
        Reflects the Mode-conditioned distribution (see notes on
        :attr:`finish_mean_hours`).
    mode_independent_project_finish_hours : np.ndarray | None
        SR10.E. Shape ``(n_iter,)``, dtype matches
        :attr:`project_finish_hours`'s precision dtype. Per-iteration
        project finish (``EF.max(axis=1)``) under the Mode-independent
        (AACE 65R-11, multiplier 1.0 regardless of declared Mode) pass —
        the Mode-independent analogue of :attr:`project_finish_hours`.
        ``None`` unless ``criticality_measurement_mode="both"`` — same
        convention as :attr:`mode_independent_criticality_index`. This is
        the array a P50/P80/P90 percentile call or S-curve renderer
        should consume for the Mode-independent headline, the same way
        :attr:`project_finish_hours` already is for Mode-conditioned.
    mode_independent_project_finish_days : np.ndarray | None
        SR10.E. Shape ``(n_iter,)``. Working-day conversion of
        :attr:`mode_independent_project_finish_hours` via the project
        calendar's ``working_hours_per_day``, mirroring
        :attr:`project_finish_days`. ``None`` under the same condition as
        :attr:`mode_independent_project_finish_hours`.
    mode_independent_finish_mean_hours : np.ndarray | None
        SR10.E. Shape ``(n_act,)``, dtype ``float64``. Per-activity mean
        of early-finish (EF) across iterations under the Mode-independent
        pass — the Mode-independent analogue of :attr:`finish_mean_hours`.
        Same derivation (population mean of the streaming finish-sum
        accumulator) applied to the second pass's sums. ``None`` unless
        ``criticality_measurement_mode="both"``.
    mode_independent_finish_std_hours : np.ndarray | None
        SR10.E. Shape ``(n_act,)``, dtype ``float64``. Per-activity
        standard deviation of EF under the Mode-independent pass, same
        ``sqrt(max(0, sum_sq/n - mean²))`` derivation as
        :attr:`finish_std_hours`. ``None`` under the same condition as
        :attr:`mode_independent_finish_mean_hours`.
    mode_independent_total_float_mean_hours : np.ndarray | None
        SR10.E. Shape ``(n_act,)``, dtype matches
        :attr:`total_float_mean_hours`'s precision dtype. Per-activity
        mean total float under the Mode-independent pass — the
        Mode-independent analogue of :attr:`total_float_mean_hours`
        (Beta-12), the near-critical-view companion to
        :attr:`mode_independent_criticality_index`. Not currently
        consumed by any reporting surface (SR10.E is additive-only on
        the engine side); available for a future Mode-independent
        near-critical report view at zero further engine cost. ``None``
        unless ``criticality_measurement_mode="both"``.
    mode_independent_total_float_std_hours : np.ndarray | None
        SR10.E. Shape ``(n_act,)``, dtype matches
        :attr:`total_float_std_hours`'s precision dtype. Per-activity
        standard deviation of total float under the Mode-independent
        pass, same derivation as :attr:`total_float_std_hours`. ``None``
        under the same condition as
        :attr:`mode_independent_total_float_mean_hours`.
    """

    project_finish_hours: np.ndarray
    project_finish_days: np.ndarray
    criticality_index: dict[str, float]
    on_critical_path_count: dict[str, int]
    n_iter: int
    n_act: int
    n_risks: int
    n_batches: int
    seed_used: int | None
    config_summary: dict[str, Any]
    beta_flag: bool
    auto_mapper_audit_path: Path | None
    activity_ids: tuple[str, ...]
    risk_ids: tuple[str, ...]
    # Beta-12 — activity-level criticality output (additive). Defaults
    # let pre-Beta-12 callers continue to construct ScheduleMCResult
    # without populating the new fields; run_schedule_mc always
    # populates them with real values.
    total_float_mean_hours: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float32)
    )
    total_float_std_hours: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float32)
    )
    deterministic_critical_path: tuple[str, ...] = ()
    # SR10.A — AACE 65R-11 Mode-independent criticality index. ``None``
    # on legacy runs; populated only when
    # ``run_schedule_mc(criticality_measurement_mode="both")`` was
    # used. Default ``None`` (not an empty dict) is intentional — it
    # lets a downstream consumer distinguish "the engine did not
    # compute this" from "the engine computed it and every activity
    # was 0.0".
    mode_independent_criticality_index: dict[str, float] | None = None
    # SR10.D — per-activity finish-time mean and standard deviation
    # (additive). Defaults let pre-SR10.D callers continue to construct
    # ScheduleMCResult without populating these; run_schedule_mc always
    # populates them with real values. Stored in float64 (not the
    # working precision dtype) because the AM02 lognormal moment-fit
    # consumer needs scalar precision per activity and the float64
    # cost is trivial (~32 KB run-level state at n_act≈2,000).
    finish_mean_hours: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float64)
    )
    finish_std_hours: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float64)
    )
    # SR10.E — Mode-independent finish distribution (project-level and
    # per-activity) and per-activity total-float distribution. ``None``
    # on every run except ``criticality_measurement_mode="both"``;
    # mirrors :attr:`mode_independent_criticality_index`'s ``None``-
    # default convention for the same reason — lets a downstream
    # consumer distinguish "the engine did not compute this" from
    # "computed and zero". The second (Mode-independent) CPM-replay pass
    # under ``"both"`` already computes all of these at no extra engine
    # cost; SR10.D (finish stats) and this addition (project-level
    # trace + total-float stats) simply stop discarding what the pass
    # already produced.
    mode_independent_project_finish_hours: np.ndarray | None = None
    mode_independent_project_finish_days: np.ndarray | None = None
    mode_independent_finish_mean_hours: np.ndarray | None = None
    mode_independent_finish_std_hours: np.ndarray | None = None
    mode_independent_total_float_mean_hours: np.ndarray | None = None
    mode_independent_total_float_std_hours: np.ndarray | None = None

    #: REPORT01 F-B. Shape ``(n_iter, n_risks)`` bool; column ``i`` is ``risk_ids[i]``.
    #: True where that risk fired on that iteration. On the integrated routes this is the
    #: supplied ``fire_mask`` - the cost arm's draw against the register's ``Probability`` -
    #: so it equals the cost arm's own record for every driver (SPEC R-10, METHFIRE-01).
    #: Retained so the report can show realised firing against elicited probability;
    #: nothing in the engine reads it back.
    risk_fired_array: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 0), dtype=bool)
    )


# ---------------------------------------------------------------------------
# Internals — precision and severity-uniform construction
# ---------------------------------------------------------------------------

def _resolve_dtype(precision: Precision) -> np.dtype:
    """Map the public ``precision`` literal to a numpy dtype.

    Mirrors the helpers in :mod:`~src.sra.cpm.cpm_kernel` and
    :mod:`~src.sra.cpm.risk_injection` so the orchestrator's casts are
    locally authoritative. Raises :class:`ValueError` on any input the
    config layer would already have rejected — defence in depth, not a
    primary boundary.
    """
    if precision == "float32":
        return np.dtype(np.float32)
    if precision == "float64":
        return np.dtype(np.float64)
    raise ValueError(
        f"precision must be 'float32' or 'float64'; got {precision!r}"
    )


def _build_severity_uniforms(
    n_iter: int,
    n_risks: int,
    rng: np.random.Generator,
    precision: Precision = "float32",
) -> np.ndarray:
    """Construct the joint severity-uniform matrix for a stand-alone run.

    The integrated run path (Beta-06 binding) passes the cost engine's
    matrix directly via the ``severity_uniforms`` parameter to
    :func:`run_schedule_mc`. This helper covers the stand-alone path
    used by unit tests and schedule-only runs.

    Each column is independent ``U(0, 1)``. The cost engine in
    production introduces correlation across columns within CG groups
    via Cholesky decomposition; stand-alone runs do not exercise that
    correlation (it would require the cost engine's CG map, which is
    project-specific and lives in the binding).

    Parameters
    ----------
    n_iter : int
        Number of Monte Carlo iterations (rows of the matrix).
    n_risks : int
        Number of risk drivers (columns of the matrix). Matches
        ``len(risk_drivers)`` at the call site.
    rng : np.random.Generator
        Generator (Generator API; legacy ``RandomState`` not supported).
        Drawn from once via ``rng.random((n_iter, n_risks))``.
    precision : {"float32", "float64"}
        Output dtype. Default ``"float32"``.

    Returns
    -------
    np.ndarray
        Shape ``(n_iter, n_risks)``, dtype = ``precision``. Values in
        ``[0, 1)``.
    """
    dt = _resolve_dtype(precision)
    # rng.random returns float64 by default; explicit cast keeps the
    # working precision plumbed end-to-end.
    return rng.random((n_iter, n_risks)).astype(dt, copy=False)


# ---------------------------------------------------------------------------
# Per-batch hot path
# ---------------------------------------------------------------------------

def _run_one_batch(
    *,
    batch_start: int,
    batch_end: int,
    graph: "ScheduleGraph",
    risk_drivers: "dict[str, RiskDriver]",
    base_durations: np.ndarray,
    severity_uniforms_batch: np.ndarray,
    batch_rng: np.random.Generator,
    config: ScheduleMCConfig,
    mode_multiplier_override: float | None = None,
    fires_out: dict[str, np.ndarray] | None = None,
    fire_mask_batch: np.ndarray | None = None,
) -> tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray
]:
    """Sample, run CPM, reduce, return small arrays only.

    The orchestrator's per-batch hot path. Calls
    :func:`~src.sra.cpm.risk_injection.build_duration_array` to produce
    the per-iteration duration array, then
    :func:`~src.sra.cpm.cpm_kernel.run_batch` to compute the per-batch
    CPM. Reduces ``(batch_n, n_act)`` arrays to ``(batch_n,)`` and
    ``(n_act,)`` immediately so the ``run_batch`` dict (and its
    underlying numpy buffers) goes out of scope at the end of this
    function.

    Memory discipline: this is the only place in the orchestrator where
    ``(batch_n, n_act)``-shaped buffers exist. The caller
    (:func:`run_schedule_mc`) never allocates ``(n_iter, n_act)``.

    Parameters
    ----------
    batch_start, batch_end : int
        Iteration indices in the full ``(0, n_iter)`` range. The slice
        consumed from ``severity_uniforms`` was ``[batch_start:batch_end, :]``;
        ``base_durations`` is independent of the iteration index.
        ``batch_n = batch_end - batch_start``.
    graph : ScheduleGraph
        Topologically-sorted activity graph (Beta-02).
    risk_drivers : dict[str, RiskDriver]
        Same dict as the orchestrator's input. Iteration order MUST
        match ``severity_uniforms_batch`` column order — the caller
        owns this contract.
    base_durations : np.ndarray
        Held for signature symmetry with the kernel and to make the
        shape contract explicit at the call boundary;
        :func:`~src.sra.cpm.risk_injection.build_duration_array` reads
        durations directly from ``graph.activities[*].original_duration_hours``
        rather than accepting them as a parameter, so this argument is
        passed through unchanged. Required by the orchestrator-side
        memory contract: confirms a ``(n_act,)``-shaped vector exists
        once, not a ``(n_iter, n_act)`` projection per batch.
    severity_uniforms_batch : np.ndarray
        Shape ``(batch_n, n_risks)``; the orchestrator-supplied slice of
        the full severity-uniform matrix.
    batch_rng : np.random.Generator
        Per-batch sub-generator from ``rng.spawn(n_batches)``.
    config : ScheduleMCConfig
        Forwards ``precision`` and ``project_start_hours`` to the kernel
        and risk-injection.

    Returns
    -------
    finish_hours_batch : np.ndarray
        Shape ``(batch_n,)``, dtype = ``config.precision``. Per-iteration
        project finish, computed as ``EF.max(axis=1)``.
    on_cp_count_batch : np.ndarray
        Shape ``(n_act,)``, dtype ``int64``. Count of iterations in this
        batch where each activity was flagged on the critical path.
    total_float_sum_batch : np.ndarray
        Shape ``(n_act,)``, dtype ``float64``. Per-activity sum of
        total-float values across this batch (Beta-12 streaming stat).
    total_float_sum_sq_batch : np.ndarray
        Shape ``(n_act,)``, dtype ``float64``. Per-activity sum of
        squared total-float values across this batch (Beta-12).
    finish_sum_batch : np.ndarray
        SR10.D. Shape ``(n_act,)``, dtype ``float64``. Per-activity sum
        of early-finish (EF) values across this batch, in working hours.
    finish_sum_sq_batch : np.ndarray
        SR10.D. Shape ``(n_act,)``, dtype ``float64``. Per-activity sum
        of squared EF values across this batch.
    """
    # ``base_durations`` is intentionally received and not consumed
    # here — see docstring; it documents the orchestrator-side memory
    # contract at the boundary. ``del`` keeps linters quiet without
    # mutating the parameter list.
    del base_durations

    batch_n = batch_end - batch_start

    # Sample risk deltas + apply to base — Beta-04 wrapper. The
    # severity-uniform slice is passed through verbatim; alignment
    # to driver column order is the orchestrator's caller-side
    # responsibility (asserted at the boundary in run_schedule_mc).
    durations = _build_duration_array(
        drivers=risk_drivers,
        graph=graph,
        n_iter=batch_n,
        rng=batch_rng,
        severity_uniform=severity_uniforms_batch,
        precision=config.precision,
        mode_multiplier_override=mode_multiplier_override,
        mode_multipliers=config.mode_multipliers,  # RS-D-3b
        fires_out=fires_out,
        fire_mask=fire_mask_batch,
    )  # shape (batch_n, n_act), dtype = precision

    # Run CPM kernel — Beta-03. Returns dict with ES/EF/LS/LF/slack
    # ((batch_n, n_act) precision-typed) and on_critical_path
    # ((batch_n, n_act) bool) plus project_finish ((batch_n,)).
    cpm_out = _kernel_run_batch(
        durations=durations,
        graph=graph,
        calendar=graph.project_default_calendar,
        precision=config.precision,
        project_start=config.project_start_hours,
    )

    # Reduce immediately and discard the per-iteration matrices.
    # EF.max(axis=1) is the methodology-standard project-finish
    # definition (kernel returns the same value via cpm_out["project_finish"]
    # — using EF directly here makes the reduction self-contained at
    # the orchestrator level, in case a future kernel change drops the
    # convenience field).
    finish_hours_batch = cpm_out["EF"].max(axis=1)

    # Beta-12 — per-batch CI / total-float streaming reductions routed
    # through the kernel's canonical accumulator (accumulate_batch_stats).
    # Same logic as an inline reduction (sum-axis-0 of on_critical_path
    # and slack with float64 promotion), but routed through the helper
    # so test_total_float_streaming_stats_match_full_array's precision
    # assertion at 1e-6 covers the production path. The accumulators
    # are allocated zeroed per batch; the orchestrator sums them into
    # its run-level totals.
    n_act = cpm_out["on_critical_path"].shape[1]
    on_cp_count_batch = np.zeros(n_act, dtype=np.int64)
    total_float_sum_batch = np.zeros(n_act, dtype=np.float64)
    total_float_sum_sq_batch = np.zeros(n_act, dtype=np.float64)
    # SR10.D — per-activity finish-time streaming reductions. Always
    # populated in the production path; the kernel helper validates and
    # increments only when both kwargs are passed (so legacy synthetic
    # callers that allocate the three Beta-12 accumulators stay valid).
    finish_sum_batch = np.zeros(n_act, dtype=np.float64)
    finish_sum_sq_batch = np.zeros(n_act, dtype=np.float64)
    _accumulate_batch_stats(
        cpm_out,
        ci_counts=on_cp_count_batch,
        total_float_sum=total_float_sum_batch,
        total_float_sum_sq=total_float_sum_sq_batch,
        finish_sum=finish_sum_batch,
        finish_sum_sq=finish_sum_sq_batch,
    )

    return (
        finish_hours_batch,
        on_cp_count_batch,
        total_float_sum_batch,
        total_float_sum_sq_batch,
        finish_sum_batch,
        finish_sum_sq_batch,
    )


# ---------------------------------------------------------------------------
# Batch-loop helper (SR10.A — re-usable so the "both" two-pass path
# can re-enter with paired rng state)
# ---------------------------------------------------------------------------

def _run_batch_loop(
    *,
    n_iter: int,
    n_act: int,
    n_batches: int,
    graph: "ScheduleGraph",
    risk_drivers: "dict[str, RiskDriver]",
    base_durations: np.ndarray,
    severity_uniforms: np.ndarray,
    rng: np.random.Generator,
    config: ScheduleMCConfig,
    dt: np.dtype,
    mode_multiplier_override: float | None,
    batch_rngs: list[np.random.Generator] | None = None,
    fires_out: dict[str, np.ndarray] | None = None,
    fire_mask: np.ndarray | None = None,
) -> tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray
]:
    """Run the chunked CPM-replay loop and return streaming accumulators.

    Factored out of :func:`run_schedule_mc` under SR10.A so the "both"
    measurement mode can call the loop twice over the *same* per-batch
    sub-generators, giving pass 2 draws paired bit-for-bit with pass 1.

    The function returns six streaming accumulators rather than a
    :class:`ScheduleMCResult` so the caller can keep result-construction
    in one place (and avoid duplicating the total-float variance,
    finish-time variance, and finish-days conversion).

    Per-batch RNG (SR10.F)
    ----------------------
    ``batch_rngs`` controls where the per-batch sub-generators come from:

    * ``None`` (default — the single-pass modes) — the loop spawns them
      itself via ``rng.spawn(n_batches)``. This is the original SR10.A
      behaviour and is bit-identical for ``"mode_conditioned"`` /
      ``"mode_independent"``.
    * a pre-spawned list (the ``"both"`` two-pass path) — the loop reuses
      the supplied child generators verbatim and never calls ``.spawn()``.
      The caller spawns ONCE, snapshots each child's
      ``bit_generator.state`` before pass 1, then restores each child to
      that snapshot before handing the SAME list back for pass 2. This is
      the only mechanism that reproduces identical draws across the two
      passes: restoring the *parent* ``rng.bit_generator.state`` and
      re-spawning does NOT, because ``SeedSequence.n_children_spawned``
      advances on every ``.spawn()`` and is not covered by the parent's
      ``bit_generator.state`` (SR10.F root cause; verified against numpy
      1.26.4).

    Side effect: when ``batch_rngs is None`` this function mutates ``rng``
    via ``rng.spawn``. Whether spawned here or supplied by the caller, the
    per-batch sub-generators are consumed (their state advanced) by the
    ``rng.random`` calls inside
    :func:`~src.sra.cpm.risk_injection.sample_risk_deltas` — so a caller
    reusing them for a paired second pass must restore each child's state
    first. That is the contract :func:`run_schedule_mc` uses for
    ``criticality_measurement_mode="both"``.
    """
    finish_hours_full = np.zeros(n_iter, dtype=dt)
    cp_count = np.zeros(n_act, dtype=np.int64)
    # Always float64 to avoid float32 catastrophic cancellation in the
    # variance step (Beta-12 §7 Risk 2). Memory cost ≈ n_act × 16 bytes.
    total_float_sum = np.zeros(n_act, dtype=np.float64)
    total_float_sum_sq = np.zeros(n_act, dtype=np.float64)
    # SR10.D — per-activity finish-time streaming accumulators. Same
    # float64 / cancellation-guard rationale as the total-float pair.
    # Run-level memory adds ≈ n_act × 16 bytes (~32 KB at 2,025
    # activities); negligible vs the per-batch (batch_n, n_act) working
    # buffers allocated inside _run_one_batch.
    finish_sum = np.zeros(n_act, dtype=np.float64)
    finish_sum_sq = np.zeros(n_act, dtype=np.float64)

    # SR10.F — single-pass modes spawn their per-batch sub-generators
    # here (unchanged); the "both" path pre-spawns once and passes the
    # list in so its two passes share (and re-consume) the same children.
    if batch_rngs is None:
        batch_rngs = rng.spawn(n_batches)

    # REPORT01 F-B: per-driver firing masks, stitched from the batches. Allocated for
    # every declared driver, so a driver that never fires reports 0.0 rather than going
    # missing - an absent row and a never-fired row mean opposite things to a reader
    # checking the sampler against the register.
    fires_full: dict[str, np.ndarray] = (
        {rid: np.zeros(n_iter, dtype=bool) for rid in risk_drivers}
        if fires_out is not None
        else {}
    )

    for b_idx in range(n_batches):
        batch_start = b_idx * config.batch_size
        batch_end = min(batch_start + config.batch_size, n_iter)
        sev_slice = severity_uniforms[batch_start:batch_end, :]
        fire_slice = None if fire_mask is None else fire_mask[batch_start:batch_end, :]
        batch_fires: dict[str, np.ndarray] | None = (
            {} if fires_out is not None else None
        )

        (
            finish_batch,
            cp_count_batch,
            tf_sum_batch,
            tf_sum_sq_batch,
            finish_sum_batch,
            finish_sum_sq_batch,
        ) = _run_one_batch(
            fires_out=batch_fires,
            fire_mask_batch=fire_slice,
            batch_start=batch_start,
            batch_end=batch_end,
            graph=graph,
            risk_drivers=risk_drivers,
            base_durations=base_durations,
            severity_uniforms_batch=sev_slice,
            batch_rng=batch_rngs[b_idx],
            config=config,
            mode_multiplier_override=mode_multiplier_override,
        )

        # Streaming aggregation invariants (asserted by tests):
        #   1. finish_hours_full[batch_start:batch_end] == finish_batch
        #      after assignment (contiguous, exact slice).
        #   2. cp_count is monotone non-decreasing per activity across
        #      batches (sums of non-negative integers).
        #   3. total_float_sum / total_float_sum_sq are float64
        #      regardless of working precision (Beta-12 §7 Risk 2).
        #   4. finish_sum / finish_sum_sq are float64 throughout
        #      regardless of working precision (SR10.D mirrors Beta-12).
        finish_hours_full[batch_start:batch_end] = finish_batch
        cp_count += cp_count_batch
        total_float_sum += tf_sum_batch
        total_float_sum_sq += tf_sum_sq_batch
        finish_sum += finish_sum_batch
        finish_sum_sq += finish_sum_sq_batch
        if batch_fires is not None:
            for rid, mask in batch_fires.items():
                fires_full[rid][batch_start:batch_end] = mask

    if fires_out is not None:
        # The "both" measurement mode re-enters this loop over the SAME sub-generators and
        # the same supplied fire mask, so a second pass rewrites identical masks: no
        # measurement mode varies whether a risk fires.
        fires_out.update(fires_full)

    return (
        finish_hours_full,
        cp_count,
        total_float_sum,
        total_float_sum_sq,
        finish_sum,
        finish_sum_sq,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_schedule_mc(
    *,
    graph: "ScheduleGraph",
    risk_drivers: "dict[str, RiskDriver]",
    config: ScheduleMCConfig | None = None,
    severity_uniforms: np.ndarray | None = None,
    rng: np.random.Generator | None = None,
    criticality_measurement_mode: CriticalityMeasurementMode = "mode_conditioned",
    fire_mask: np.ndarray | None = None,
) -> ScheduleMCResult:
    """Run the chunked schedule Monte Carlo simulation.

    Parameters
    ----------
    graph : ScheduleGraph
        Topologically-sorted activity graph from Beta-02. Activities
        must carry ``original_duration_hours``; the orchestrator reads
        these once at start to construct the base-duration vector.
    risk_drivers : dict[str, RiskDriver]
        Resolved per-(risk, activity) assignments. Either auto-mapped
        (Beta-04, ``derived_at_run_time=True``) or workshop-direct
        (``derived_at_run_time=False``). Cost-only risks (Time=No) are
        NOT present in this dict — the binding (Beta-06) excludes them
        when constructing it. ``RiskDriver.probability`` carries the
        time-arm firing probability for the schedule-arm Bernoulli per
        the framing addendum (``SR_S3_Beta_05_06_probability_framing_addendum.md``).
    config : ScheduleMCConfig
        Sampling and chunking configuration, carrying the register's Mode
        multiplier grid. Required since RS-D-3b (D-15): ``None`` raises; there
        is no default configuration.
    severity_uniforms : np.ndarray | None
        Shape ``(n_iter, n_risks)``. Joint severity uniform shared with
        the cost arm. Column index ``j`` corresponds to the ``j``-th
        risk in ``risk_drivers.keys()`` iteration order. When ``None``,
        the orchestrator constructs its own via
        :func:`_build_severity_uniforms` using ``rng`` (or a seed-derived
        rng) — used for stand-alone schedule-only runs and unit tests.
        The integrated run path (Beta-06) always passes the cost
        engine's matrix.
    fire_mask : np.ndarray | None
        Shape ``(n_iter, n_risks)`` bool, aligned like ``severity_uniforms``: whether each
        driver's risk occurs on each iteration. The integrated routes pass the cost arm's
        fire draw (:func:`src.qra_core.draw_fire_matrix`), so one risk is one event on both
        arms (SPEC R-10, METHFIRE-01). When ``None`` - stand-alone schedule runs and unit
        tests - each driver draws its own Bernoulli against ``driver.probability``.
    rng : np.random.Generator | None
        Per-run generator. When ``None``,
        ``np.random.default_rng(config.seed)`` is constructed, and a
        ``config.seed`` of ``None`` is refused. Per-batch sub-generators are
        derived deterministically via ``rng.spawn(n_batches)`` (numpy
        ≥ 1.25).
    criticality_measurement_mode : {"mode_conditioned", "mode_independent", "both"}
        SR10.A. ``"mode_conditioned"`` (default) honours each driver's
        declared Mode via ``mode_multipliers[driver.mode]``; bit-for-bit
        identical to pre-SR10.A behaviour for callers whose drivers
        carry the default ``mode="Series"`` (multiplier 1.0).
        ``"mode_independent"`` overrides every risk's Mode multiplier
        to ``1.0`` per AACE 65R-11 §5.4. ``"both"`` runs the engine
        twice — first ``"mode_conditioned"``, then ``"mode_independent"``
        — sharing one severity-uniform matrix and one set of per-batch
        sub-generators (spawned once, each restored to its pre-first-pass
        state before the second pass — SR10.F) so both passes draw
        identical Bernoulli fires and PERT magnitudes and the per-activity
        divergence is attributable solely to the Mode multiplier. The
        :attr:`ScheduleMCResult.mode_independent_criticality_index`
        field is populated only on ``"both"`` runs, as are the SR10.E
        ``mode_independent_project_finish_hours`` /
        ``_days``, ``mode_independent_finish_mean_hours`` / ``_std_hours``,
        and ``mode_independent_total_float_mean_hours`` / ``_std_hours``
        fields.

    Returns
    -------
    ScheduleMCResult
        Per-iteration project finish distribution, per-activity
        criticality index, run metadata, beta_flag, and pass-through
        of ``auto_mapper_audit_path``.

    Raises
    ------
    ValueError
        If ``risk_drivers`` is empty (degenerate "all base-duration"
        runs are refused; the caller can construct a deterministic
        baseline by passing all-``probability=0.0`` drivers if that is
        the intent).
    ValueError
        If ``config.mode == "prod"`` and any driver has
        ``derived_at_run_time=True``. The error message lists the
        offending risk_ids.
    ValueError
        If ``severity_uniforms`` or ``fire_mask`` is provided with a shape that
        does not match ``(config.n_iter, len(risk_drivers))``.

    Notes
    -----
    Severity-uniform alignment. The column ordering of
    ``severity_uniforms`` is asserted at the call boundary. The
    orchestrator does NOT permute the matrix — the caller (binding or
    test harness) is responsible for constructing it with columns in
    ``risk_drivers.keys()`` iteration order. A shape mismatch raises
    rather than silently misaligning Bernoulli draws.

    Mode gating. In ``mode == "prod"``, the orchestrator scans
    ``risk_drivers.values()`` for any ``derived_at_run_time=True`` and
    raises if found. ``beta_flag`` on the result is the same scan
    inverted: ``True`` iff any driver is auto-mapped.

    Memory. The full ``(n_iter, n_act)`` duration array is never
    materialised. See module docstring for the chunked-iteration
    discipline and per-batch peak.
    """

    # ----- Input validation -----
    if not risk_drivers:
        raise ValueError(
            "risk_drivers must be non-empty; for a deterministic baseline "
            "pass drivers with probability=0.0"
        )
    if config is None:
        raise ValueError(
            "run_schedule_mc requires a ScheduleMCConfig carrying the register's Mode "
            "multiplier grid (RS-D-3, D-15); there is no default configuration."
        )

    # SR10.A — fail fast on an unknown criticality_measurement_mode.
    # No silent default to "mode_conditioned" — a typo at the call site
    # would otherwise pass review and quietly skip the AACE 65R-11
    # measurement.
    if criticality_measurement_mode not in _CRITICALITY_MEASUREMENT_MODES:
        raise ValueError(
            "criticality_measurement_mode must be one of "
            f"{_CRITICALITY_MEASUREMENT_MODES}; got "
            f"{criticality_measurement_mode!r}"
        )

    n_iter = config.n_iter
    n_risks = len(risk_drivers)
    n_act = len(graph.activities)

    # Mode gate: prod refuses any auto-mapped driver. List the offending
    # risk_ids in the error so the reviewer can locate them quickly.
    auto_mapped_ids = [
        rid for rid, d in risk_drivers.items() if d.derived_at_run_time
    ]
    if config.mode == "prod" and auto_mapped_ids:
        raise ValueError(
            "prod mode does not accept auto-mapped drivers; the following "
            f"are auto-mapped (derived_at_run_time=True): {auto_mapped_ids}"
        )
    beta_flag = bool(auto_mapped_ids)

    # ----- RNG -----
    # ``seed_used`` is an audit field. When the orchestrator constructs
    # the rng from ``config.seed``, the seed is recoverable and we
    # record it. When the caller passes an explicit ``rng``,
    # ``config.seed`` is NOT what was actually seeded — the audit field
    # is set to None to signal "external rng; seed not recoverable from
    # config.seed". The caller is responsible for recording its own
    # rng provenance (e.g. on the integrated path the cost-engine
    # binding owns the master rng and its own audit trail).
    if rng is None:
        seed_used: int | None = require_seed(config.seed,
                                             where="src.sra.cpm.cpm_simulation.run_schedule_mc")
        rng = np.random.default_rng(seed_used)
    else:
        seed_used = None

    # ----- Severity uniforms -----
    if severity_uniforms is None:
        severity_uniforms = _build_severity_uniforms(
            n_iter=n_iter,
            n_risks=n_risks,
            rng=rng,
            precision=config.precision,
        )
    else:
        expected_shape = (n_iter, n_risks)
        if severity_uniforms.shape != expected_shape:
            raise ValueError(
                f"severity_uniforms shape mismatch: expected "
                f"{expected_shape}, got {severity_uniforms.shape}"
            )
    if fire_mask is not None and (
        fire_mask.shape != (n_iter, n_risks) or fire_mask.dtype != np.bool_
    ):
        raise ValueError(
            f"fire_mask mismatch: expected {(n_iter, n_risks)} bool, got "
            f"{fire_mask.shape} {fire_mask.dtype}"
        )

    # ----- Base-duration vector (allocated once, (n_act,)) -----
    dt = _resolve_dtype(config.precision)
    activity_ids = tuple(graph.topo_order)
    base_durations = np.array(
        [
            graph.activities[a_id].original_duration_hours
            for a_id in activity_ids
        ],
        dtype=dt,
    )

    # ----- Deterministic critical path (Beta-12) -----
    # One zero-risk forward+backward pass — every duration frozen at
    # the activity's original_duration_hours; no Bernoulli firing, no
    # PERT sampling. The activity *set* with slack ≤ CRITICAL_PATH_TOL
    # is captured as the planner-derived deterministic CP (Beta-12 §3.1
    # / §7 Risk 3). For chains with float ties this set is a superset
    # of any single longest path; that's the documented convention.
    det_durations = base_durations[None, :]
    det_out = _kernel_run_batch(
        durations=det_durations,
        graph=graph,
        calendar=graph.project_default_calendar,
        precision=config.precision,
        project_start=config.project_start_hours,
    )
    det_cp_mask = det_out["on_critical_path"][0]
    deterministic_critical_path: tuple[str, ...] = tuple(
        a_id for a_id, on_cp in zip(activity_ids, det_cp_mask) if bool(on_cp)
    )

    # ----- Batch loop ----------------------------------------------
    n_batches = (n_iter + config.batch_size - 1) // config.batch_size

    logger.info(
        "run_schedule_mc: starting; n_iter=%d, batch_size=%d, n_batches=%d, "
        "n_act=%d, n_risks=%d, precision=%s, mode=%s, beta_flag=%s, "
        "deterministic_cp_size=%d, criticality_measurement_mode=%s",
        n_iter,
        config.batch_size,
        n_batches,
        n_act,
        n_risks,
        config.precision,
        config.mode,
        beta_flag,
        len(deterministic_critical_path),
        criticality_measurement_mode,
    )

    # SR10.F — for "both" mode, spawn the per-batch sub-generators ONCE
    # here and snapshot each child's own bit_generator.state, so the
    # second pass can restore each child and reuse the SAME generator
    # objects. This is what actually pairs the two passes' Bernoulli fires
    # and PERT magnitudes: restoring the *parent* rng.bit_generator.state
    # and re-spawning does NOT, because SeedSequence.n_children_spawned
    # advances on every .spawn() and lives outside the parent's saved
    # state (SR10.F root cause, verified against numpy 1.26.4). Single-pass
    # modes leave batch_rngs None and let _run_batch_loop spawn internally,
    # exactly as before this fix.
    paired_batch_rngs: list[np.random.Generator] | None
    if criticality_measurement_mode == "both":
        paired_batch_rngs = rng.spawn(n_batches)
        paired_child_states = [
            g.bit_generator.state for g in paired_batch_rngs
        ]
    else:
        paired_batch_rngs = None

    # SR15 — Mode-multiplier retirement on the Stage 3 path. When
    # ``config.apply_mode_multipliers`` is ``False``, every per-iteration
    # risk impact is applied at multiplier 1.0 regardless of declared
    # Mode classification; the CPM kernel handles float consumption
    # directly. ``True`` (default) preserves the pre-SR15 Stage 2.5
    # behaviour (per-driver lookup via ``mode_multipliers[driver.mode]``).
    # Interaction with SR10.A: when ``apply_mode_multipliers`` is
    # ``False``, the primary pass uses override=1.0 regardless of
    # ``criticality_measurement_mode``; for ``"both"`` runs the secondary
    # pass also uses override=1.0 (existing SR10.A logic below), so
    # ``mode_independent_criticality_index`` coincides with
    # ``criticality_index`` — both measurements are Mode-suppressed,
    # which is mathematically correct (no Mode multiplier means the two
    # measurements degenerate).
    if not config.apply_mode_multipliers:
        primary_override = 1.0
    elif criticality_measurement_mode == "mode_independent":
        primary_override = 1.0
    else:
        primary_override = None
    # REPORT01 F-B: the primary pass owns the firing record. The mode-independent
    # second pass re-consumes the same sub-generators and would only rewrite it.
    risk_fires: dict[str, np.ndarray] = {}
    (
        finish_hours_full,
        cp_count,
        total_float_sum,
        total_float_sum_sq,
        finish_sum,
        finish_sum_sq,
    ) = _run_batch_loop(
        fires_out=risk_fires,
        fire_mask=fire_mask,
        n_iter=n_iter,
        n_act=n_act,
        n_batches=n_batches,
        graph=graph,
        risk_drivers=risk_drivers,
        base_durations=base_durations,
        severity_uniforms=severity_uniforms,
        rng=rng,
        config=config,
        dt=dt,
        mode_multiplier_override=primary_override,
        batch_rngs=paired_batch_rngs,
    )

    # SR10.F — for "both", re-run with mode_multiplier_override=1.0 over
    # the SAME per-batch sub-generators used by pass 1, each restored to
    # its pre-pass-1 snapshot. Because pass 2 reuses these child objects
    # (rather than re-spawning), its per-batch Bernoulli and PERT draws
    # are paired bit-for-bit with pass 1. Only the post-PERT Mode
    # multiplier differs across the two passes; any divergence in CI or
    # in the finish trace is attributable solely to Mode suppression, not
    # to RNG drift.
    mode_independent_criticality_index: dict[str, float] | None = None
    # SR10.E — the second pass's project-level finish trace and
    # per-activity finish/total-float sums, declared here (None default)
    # so they exist for the derived-stats block below and the
    # dataclass-construction site regardless of mode.
    finish_hours_full_mi: np.ndarray | None = None
    total_float_sum_mi: np.ndarray | None = None
    total_float_sum_sq_mi: np.ndarray | None = None
    finish_sum_mi: np.ndarray | None = None
    finish_sum_sq_mi: np.ndarray | None = None
    if criticality_measurement_mode == "both":
        # SR10.F — restore each pre-spawned child generator to its
        # pre-pass-1 snapshot so pass 2 reuses (re-consumes) the identical
        # sub-generators. This replaces the SR10.A parent-state restore,
        # which did not pair the passes (SeedSequence.n_children_spawned
        # is not part of rng.bit_generator.state, so the SR10.A restore +
        # internal re-spawn drew different children — the bug SR10.F
        # fixes).
        for g, s in zip(paired_batch_rngs, paired_child_states):
            g.bit_generator.state = s
        # SR10.E — the second (Mode-independent) pass's full return
        # tuple is now captured. Previously (SR10.D) only cp_count_mi
        # survived past this call; the project-level finish trace and
        # the per-activity finish/total-float sums were discarded here
        # even though _run_batch_loop always computes them at no extra
        # cost. Derived mean/std stats from these raw sums are computed
        # further below, once hours_per_day_w exists.
        (
            finish_hours_full_mi,
            cp_count_mi,
            total_float_sum_mi,
            total_float_sum_sq_mi,
            finish_sum_mi,
            finish_sum_sq_mi,
        ) = _run_batch_loop(
            n_iter=n_iter,
            n_act=n_act,
            n_batches=n_batches,
            graph=graph,
            risk_drivers=risk_drivers,
            base_durations=base_durations,
            severity_uniforms=severity_uniforms,
            rng=rng,
            config=config,
            dt=dt,
            mode_multiplier_override=1.0,
            batch_rngs=paired_batch_rngs,
            fire_mask=fire_mask,
        )
        n_iter_f_mi = float(n_iter)
        mode_independent_criticality_index = {
            a_id: float(cp_count_mi[i]) / n_iter_f_mi
            for i, a_id in enumerate(activity_ids)
        }

    # ----- Convert finish hours → finish days -----
    hours_per_day = float(
        graph.project_default_calendar.working_hours_per_day
    )
    # Pre-cast the divisor so the division stays in the working dtype
    # under numpy 2.0+ NEP 50; final astype is defensive against any
    # silent promotion in future numpy versions.
    hours_per_day_w = dt.type(hours_per_day)
    finish_days_full = (finish_hours_full / hours_per_day_w).astype(
        dt, copy=False
    )

    # ----- Mode-independent finish / total-float distribution stats (SR10.E) -----
    # Mirrors the Mode-conditioned derivations below (total-float at
    # "Total-float distribution stats (Beta-12)", finish-time at
    # "Finish-time distribution stats (SR10.D)") applied to the second
    # pass's now-captured sums. None unless
    # criticality_measurement_mode="both" — same convention as
    # mode_independent_criticality_index above.
    mode_independent_project_finish_hours: np.ndarray | None = None
    mode_independent_project_finish_days: np.ndarray | None = None
    mode_independent_total_float_mean_hours: np.ndarray | None = None
    mode_independent_total_float_std_hours: np.ndarray | None = None
    mode_independent_finish_mean_hours: np.ndarray | None = None
    mode_independent_finish_std_hours: np.ndarray | None = None
    if criticality_measurement_mode == "both":
        mode_independent_project_finish_hours = finish_hours_full_mi
        mode_independent_project_finish_days = (
            finish_hours_full_mi / hours_per_day_w
        ).astype(dt, copy=False)

        tf_mean_f64_mi = total_float_sum_mi / n_iter_f_mi
        tf_var_f64_mi = np.maximum(
            0.0,
            total_float_sum_sq_mi / n_iter_f_mi - np.square(tf_mean_f64_mi),
        )
        tf_std_f64_mi = np.sqrt(tf_var_f64_mi)
        mode_independent_total_float_mean_hours = tf_mean_f64_mi.astype(
            dt, copy=False
        )
        mode_independent_total_float_std_hours = tf_std_f64_mi.astype(
            dt, copy=False
        )

        mode_independent_finish_mean_hours = finish_sum_mi / n_iter_f_mi
        finish_var_hours_mi = np.maximum(
            0.0,
            finish_sum_sq_mi / n_iter_f_mi
            - np.square(mode_independent_finish_mean_hours),
        )
        mode_independent_finish_std_hours = np.sqrt(finish_var_hours_mi)

    # ----- Build result dicts (deterministic order: topo_order) -----
    n_iter_f = float(n_iter)
    criticality_index = {
        a_id: float(cp_count[i]) / n_iter_f
        for i, a_id in enumerate(activity_ids)
    }
    on_cp_count = {
        a_id: int(cp_count[i]) for i, a_id in enumerate(activity_ids)
    }

    # ----- Total-float distribution stats (Beta-12) -----
    # Mean and variance are computed in float64 to avoid catastrophic
    # cancellation, then downcast to ``precision`` at the boundary so
    # the result fields match the rest of the per-activity arrays.
    # Variance is floored at zero to suppress tiny negatives arising
    # from numerical cancellation when an activity's float is constant
    # across iterations (the algebraic identity E[X²] − (E[X])² ≥ 0
    # holds exactly; the float64 evaluation does not).
    tf_mean_f64 = total_float_sum / n_iter_f
    tf_var_f64 = np.maximum(
        0.0, total_float_sum_sq / n_iter_f - np.square(tf_mean_f64)
    )
    tf_std_f64 = np.sqrt(tf_var_f64)
    total_float_mean_hours = tf_mean_f64.astype(dt, copy=False)
    total_float_std_hours = tf_std_f64.astype(dt, copy=False)

    # ----- Finish-time distribution stats (SR10.D) -----
    # Per-activity finish-day Mean and standard deviation. Mirrors the
    # total-float derivation immediately above with the same float64
    # cancellation guard. Mode-conditioned distribution only — the
    # second ("Mode-independent") pass under
    # ``criticality_measurement_mode="both"`` discards its finish
    # accumulators (see the unpacking comment at the second
    # _run_batch_loop call site).
    #
    # Kept in float64 (no downcast to ``dt``) per the SR10.D brief §3.3:
    # the consuming methodology (e.g. AM02 lognormal moment-fit) takes
    # mean and std as scalar inputs per activity, and the float64
    # precision is cheap (~32 KB run-level state at n_act≈2,000) and
    # avoids the asymmetric-rounding artefacts that float32 downcast
    # introduces for activities with finish hours in the tens of
    # thousands. Exposed on ScheduleMCResult by the SR10.D commit 4
    # follow-up; computed here so the values are available for the
    # dataclass-construction site below.
    finish_mean_hours = finish_sum / n_iter_f
    finish_var_hours = np.maximum(
        0.0, finish_sum_sq / n_iter_f - np.square(finish_mean_hours)
    )
    finish_std_hours = np.sqrt(finish_var_hours)

    config_summary: dict[str, Any] = {
        "n_iter": config.n_iter,
        "batch_size": config.batch_size,
        "seed": config.seed,
        "precision": config.precision,
        "project_start_hours": config.project_start_hours,
        "mode": config.mode,
        "beta_flag_threshold_days": config.beta_flag_threshold_days,
        "apply_mode_multipliers": config.apply_mode_multipliers,
        "mode_multipliers": dict(config.mode_multipliers),  # RS-D-3b: the grid is a per-register input now
    }

    logger.info(
        "run_schedule_mc: complete; n_iter=%d, n_batches=%d, "
        "finish_hours_mean=%.2f, finish_days_mean=%.2f",
        n_iter,
        n_batches,
        float(finish_hours_full.mean()),
        float(finish_days_full.mean()),
    )

    config_summary["criticality_measurement_mode"] = criticality_measurement_mode

    # Column order follows ``risk_drivers`` iteration order, which is what
    # ``risk_ids`` below is built from, so column i belongs to risk_ids[i].
    risk_fired_array = (
        np.stack([risk_fires[rid] for rid in risk_drivers], axis=1)
        if risk_fires
        else np.zeros((n_iter, 0), dtype=bool)
    )

    return ScheduleMCResult(
        risk_fired_array=risk_fired_array,
        project_finish_hours=finish_hours_full,
        project_finish_days=finish_days_full,
        criticality_index=criticality_index,
        on_critical_path_count=on_cp_count,
        n_iter=n_iter,
        n_act=n_act,
        n_risks=n_risks,
        n_batches=n_batches,
        seed_used=seed_used,
        config_summary=config_summary,
        beta_flag=beta_flag,
        auto_mapper_audit_path=config.auto_mapper_audit_path,
        activity_ids=activity_ids,
        risk_ids=tuple(risk_drivers.keys()),
        total_float_mean_hours=total_float_mean_hours,
        total_float_std_hours=total_float_std_hours,
        deterministic_critical_path=deterministic_critical_path,
        mode_independent_criticality_index=mode_independent_criticality_index,
        finish_mean_hours=finish_mean_hours,
        finish_std_hours=finish_std_hours,
        mode_independent_project_finish_hours=mode_independent_project_finish_hours,
        mode_independent_project_finish_days=mode_independent_project_finish_days,
        mode_independent_finish_mean_hours=mode_independent_finish_mean_hours,
        mode_independent_finish_std_hours=mode_independent_finish_std_hours,
        mode_independent_total_float_mean_hours=mode_independent_total_float_mean_hours,
        mode_independent_total_float_std_hours=mode_independent_total_float_std_hours,
    )
