"""Per-iteration risk-duration injection for the CPM kernel.

Given a resolved ``dict[risk_id, RiskDriver]`` (auto-mapper or workshop
output) and the cost-engine's shared ``severity_uniform`` matrix, this
module produces a ``(n_iter, n_act)`` duration array ready for
:func:`src.sra.cpm.cpm_kernel.run_batch`.

Three public entry points
-------------------------

* :func:`sample_risk_deltas` — per-iteration duration deltas in working
  hours, broadcast onto every affected activity. Outer Python loop is
  over drivers (typically ~15); inner numpy ops are vectorised across
  ``n_iter``.
* :func:`apply_to_durations` — broadcast a base ``(n_act,)`` duration
  vector across iterations and add the deltas. Floors negative
  durations at zero with a logged WARNING.
* :func:`build_duration_array` — convenience wrapper that chains the
  two.

Severity-uniform sharing with the cost engine
---------------------------------------------

The cost engine in :mod:`src.sra.sra_simulation` /
:mod:`src.integrated.integrated_simulation` already produces a per-risk
``u_severity`` uniform draw for joint cost/schedule sampling per
SR-S3-Beta-00.4. Stage 3 consumes the *same* uniform via the
``severity_uniform`` parameter to :func:`sample_risk_deltas` — passing
the matrix of shape ``(n_iter, n_risks)`` aligns the schedule arm's
PERT magnitudes with the cost arm's, which is the joint-sampling
correlation mechanic.

The orchestrator (Beta-05) is responsible for:

* passing ``rng`` and ``severity_uniform`` from the cost engine into
  :func:`build_duration_array`;
* aligning the column ordering of ``severity_uniform`` with ``drivers``
  iteration order — the orchestrator owns both ends.

This module is the consumer side. When ``severity_uniform`` is
``None`` (stand-alone tests only), the function draws its own
uniforms via ``rng.random``.

Multi-risk superposition
------------------------

When two or more risks affect the same activity, their per-iteration
deltas are summed (independent additive PERT model). This matches the
strawman convention and the AACE 132R-23 / AU GN3A v2.0 integrated-
method assumption used elsewhere in the codebase. It is *not* a max
reduction, and it is *not* multiplicative compounding.

Precision policy
----------------

Default ``float32`` per ``STAGE3_ROADMAP.md`` §3.3 / Beta-00 §5;
matches the kernel default. ``float64`` is opt-in for diagnostic runs.
The PERT inverse-CDF goes through ``scipy.stats.beta.ppf``, which
returns ``float64``; explicit ``.astype(dt)`` casts at every
numpy/scipy boundary lock the working precision and prevent silent
float64 promotion under numpy 2.0+ NEP 50 (the same precision-plumbing
class as Beta-03 Finding 1).

Numpy random API
----------------

The ``rng`` parameter must be a :class:`numpy.random.Generator` — the
function calls ``rng.random(n_iter)`` (Generator API). A legacy
:class:`numpy.random.RandomState` will fail fast on the first call;
the orchestrator constructs the generator via
``np.random.default_rng(seed)``.

This module is project-agnostic — no project paths, file names, or
project codes appear here. The reusability invariant is locked by the
synthetic-graph tests in :mod:`tests.sra.cpm.test_risk_injection`.
"""

from __future__ import annotations

import logging
from typing import Mapping, TYPE_CHECKING, Literal

import numpy as np
from scipy import stats

from src.sra.cpm.risk_driver_schema import RiskDriver
from src.sra.mode_multipliers import resolve_mode_multiplier

if TYPE_CHECKING:
    from src.sra.cpm.graph import ScheduleGraph


logger = logging.getLogger(__name__)


Precision = Literal["float32", "float64"]

#: PERT shape parameter (Vose 2008). Matches the cost engine's
#: ``pert_from_uniform`` call site in :mod:`src.distributions`.
_PERT_LAMBDA: float = 4.0

#: Numerical guard for the inverse Beta CDF — ``scipy.stats.beta.ppf``
#: produces ``±inf`` at the open-interval boundary.
_BETA_PPF_EPS: float = 1e-10


__all__ = [
    "sample_risk_deltas",
    "apply_to_durations",
    "build_duration_array",
    "Precision",
]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _resolve_dtype(precision: Precision) -> np.dtype:
    """Map the public ``precision`` literal to a numpy dtype."""
    if precision == "float32":
        return np.dtype(np.float32)
    if precision == "float64":
        return np.dtype(np.float64)
    raise ValueError(
        f"precision must be 'float32' or 'float64', got {precision!r}"
    )


def _pert_inverse_cdf(
    u: np.ndarray,
    opt: float,
    ml: float,
    pess: float,
    lam: float = _PERT_LAMBDA,
) -> np.ndarray:
    """Standard PERT inverse CDF via the Beta distribution.

    Returns ``float64`` (whatever ``scipy.stats.beta.ppf`` gives us);
    the caller is responsible for casting to the working precision.

    Degenerate ``pess <= opt`` collapses to a deterministic ``ml``
    sample of the input uniform's shape — a constant-PERT risk is a
    legitimate beta-mode input (e.g. opt=ml=pess=10 days for a known
    fixed-magnitude impact).
    """
    if pess <= opt:
        return np.full_like(u, fill_value=ml, dtype=np.float64)

    alpha = 1.0 + lam * (ml - opt) / (pess - opt)
    beta_param = 1.0 + lam * (pess - ml) / (pess - opt)

    u_clipped = np.clip(u.astype(np.float64), _BETA_PPF_EPS, 1.0 - _BETA_PPF_EPS)
    return opt + stats.beta.ppf(u_clipped, alpha, beta_param) * (pess - opt)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sample_risk_deltas(
    drivers: dict[str, RiskDriver],
    graph: "ScheduleGraph",
    n_iter: int,
    rng: np.random.Generator,
    severity_uniform: np.ndarray | None = None,
    precision: Precision = "float32",
    *,
    mode_multiplier_override: float | None = None,
    mode_multipliers: Mapping[str, float],
    fires_out: dict[str, np.ndarray] | None = None,
    fire_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Sample per-iteration duration deltas (working hours) per activity.

    Parameters
    ----------
    drivers : dict[str, RiskDriver]
        Resolved auto-mapper or workshop output.
    graph : ScheduleGraph
        Provides ``topo_order`` for column indexing and the project-
        default calendar's ``working_hours_per_day`` for additive PERT
        days → hours conversion.
    n_iter : int
        Number of Monte Carlo iterations in this batch.
    rng : np.random.Generator
        Per-batch generator. The orchestrator constructs this via
        ``np.random.default_rng(seed)``.
    severity_uniform : np.ndarray | None
        Shape ``(n_iter, n_risks)``; the cost engine's shared U(0,1)
        draws (per Beta-00.4). Column ``i`` aligns with the i-th driver
        in ``drivers.items()`` iteration order — the orchestrator owns
        the alignment. When ``None``, this function draws its own
        uniforms via ``rng.random`` (stand-alone tests only).
    fire_mask : np.ndarray | None, keyword-only
        Shape ``(n_iter, n_risks)`` bool; whether each driver's risk occurs this iteration,
        aligned like ``severity_uniform``. The integrated routes pass the cost arm's fire
        draw here so a dual-coded risk fires once for both arms (SPEC R-10, METHFIRE-01).
        When ``None``, this function draws its own Bernoulli against ``driver.probability``.
    precision : {"float32", "float64"}
        Output dtype. Default ``float32`` per Beta-00 §5.
    mode_multiplier_override : float | None, keyword-only
        SR10.A. When ``None`` (default), each risk's per-iteration delta
        is scaled by ``mode_multipliers[driver.mode]`` (Series=1.0,
        Hybrid=0.5, Parallel=0.0). When set to a float (typically
        ``1.0`` for the Mode-independent AACE 65R-11 measurement), the
        override replaces the per-driver lookup uniformly for every
        risk — no Hybrid leakage, no partial application. Bernoulli
        firing and PERT magnitude draws are unchanged either way; only
        the post-PERT multiplication of the delta differs.

    Returns
    -------
    deltas : np.ndarray
        Shape ``(n_iter, n_act)``, dtype = ``precision``.

        For each iteration and each driver:

        * ``fire_mask`` decides whether the risk fires this iteration when
          supplied; otherwise a Bernoulli draw against ``driver.probability``
          does (separate from the severity uniform — ``rng.random(n_iter)``).
        * On a fired iteration, a PERT magnitude is computed from the
          severity uniform column for this risk:

          - ``"additive_pert_days"`` (legacy) → magnitude ×
            ``working_hours_per_day`` broadcast onto every affected
            activity column. Stage 2.5 baseline mechanic; preserved
            verbatim as the SR12 fallback for strawman rows whose
            ``injection_method`` is null/blank.
          - ``"discrete_event_additive_days"`` (SR12) → magnitude ×
            ``working_hours_per_day`` written to the single column
            corresponding to :attr:`RiskDriver.gating_activity_id`,
            NOT broadcast. Methodologically consistent with AACE 57R-09
            / Hulett / CEGN 3A §3.1-§3.3 for single-event discrete
            delay risks.
          - ``"multiplicative_pert_factor"`` (legacy) and
            ``"productivity_multiplicative_factor"`` (SR12 workshop
            name) → ``(factor - 1) × base_dur`` per activity, computed
            against :attr:`Activity.original_duration_hours`.

        The resulting per-iteration delta is then scaled by the Mode
        multiplier (per-driver lookup, or the
        ``mode_multiplier_override`` argument when set).

        Multiple risks affecting the same activity SUM their deltas
        (independent additive PERT superposition).

    Raises
    ------
    ValueError
        If ``severity_uniform`` or ``fire_mask`` is provided with a shape that
        does not match ``(n_iter, len(drivers))``.
    """
    dt = _resolve_dtype(precision)
    n_act = len(graph.activities)
    n_risks = len(drivers)

    if severity_uniform is not None:
        if severity_uniform.shape != (n_iter, n_risks):
            raise ValueError(
                f"severity_uniform shape {severity_uniform.shape} does not match "
                f"(n_iter, n_risks) = ({n_iter}, {n_risks})"
            )
    if fire_mask is not None:
        if fire_mask.shape != (n_iter, n_risks) or fire_mask.dtype != np.bool_:
            raise ValueError(
                f"fire_mask shape {fire_mask.shape} dtype {fire_mask.dtype} does not match "
                f"(n_iter, n_risks) = ({n_iter}, {n_risks}) bool"
            )

    deltas = np.zeros((n_iter, n_act), dtype=dt)

    if n_risks == 0 or n_iter == 0:
        return deltas

    id_to_col = {a_id: i for i, a_id in enumerate(graph.topo_order)}
    hours_per_day = float(
        graph.project_default_calendar.working_hours_per_day
    )

    # Pre-cast scalars to working dtype once so per-risk inner ops do
    # not promote arrays back to float64 under numpy 2.0+ NEP 50.
    hours_per_day_w = dt.type(hours_per_day)
    one_w = dt.type(1.0)
    zero_w = dt.type(0.0)

    for risk_idx, (driver_id, driver) in enumerate(drivers.items()):
        # Probability gate. On the integrated routes the fire decision is supplied: it is the
        # cost arm's draw, so a dual-coded risk carries its delay exactly when it carries its
        # cost (SPEC R-10, METHFIRE-01). Only a stand-alone schedule run draws its own - a
        # Bernoulli per iteration, on a stream separate from the severity uniform so a
        # probability gate flipping does not change the PERT magnitudes drawn this iteration.
        #
        # Whichever of the two rng.random calls below a run makes, it makes
        # UNCONDITIONALLY, before the zero-expansion check. This keeps the rng
        # stream stable across graph revisions: a rule whose expansion goes from
        # non-empty to empty (or vice versa) still consumes the same
        # ``n_iter``-sized RNG slots, so reproducibility of the fire mask and
        # severity uniforms for the surviving drivers is preserved. A supplied
        # ``fire_mask`` skips the fire draw for every driver alike, and a supplied
        # ``severity_uniform`` skips the severity draw, so each run's stream shape
        # is still fixed by its arguments, not by the graph.
        if fire_mask is not None:
            fires = fire_mask[:, risk_idx]
        else:
            fires = rng.random(n_iter) < driver.probability     # bool (n_iter,)

        # REPORT01 F-B: hand the mask out when the caller asked for it. Captured HERE,
        # above the zero-expansion skip, so the record covers every driver the register
        # declared rather than only those that reached an activity - a rule that expands
        # to nothing still fired, and a model-validation table that omitted it would
        # understate the register's own firing. Read-only: nothing below branches on
        # fires_out, so the draw order and every downstream number are untouched.
        if fires_out is not None:
            fires_out[driver_id] = fires

        # PERT magnitude source — shared severity column when the
        # orchestrator passes one, else our own draw. We pull the
        # uniform vector even on zero-expansion so the standalone-path
        # rng stream stays stable across graph revisions; the
        # severity_uniform path indexes by risk_idx and is naturally
        # aligned regardless of expansion.
        if severity_uniform is None:
            u_native = rng.random(n_iter)
        else:
            u_native = severity_uniform[:, risk_idx]

        if not driver.affected_activity_ids:
            # Zero-expansion rule: retained in audit, contributes no
            # delta. Skip the rest of the per-risk work but the rng
            # draws above have already advanced the stream.
            continue

        magnitudes_native = _pert_inverse_cdf(
            np.asarray(u_native),
            float(driver.opt_pert),
            float(driver.ml_pert),
            float(driver.pess_pert),
        )                                                    # float64 (n_iter,)
        magnitudes = magnitudes_native.astype(dt, copy=False)

        method = driver.injection_method
        if method in ("additive_pert_days", "discrete_event_additive_days"):
            # Days × working_hours_per_day → working hours. Both methods
            # share the same per-iteration magnitude computation; they
            # differ only in the broadcast step below (full-cohort
            # broadcast vs single-column write to gating_activity_id).
            delta_per_iter = magnitudes * hours_per_day_w   # (n_iter,) in dt
        elif method in (
            "multiplicative_pert_factor",
            "productivity_multiplicative_factor",
        ):
            # ``(factor - 1)`` is the additive-equivalent fraction of
            # base duration; per-activity multiplication by base
            # duration happens at the broadcast step below so each
            # activity sees its own base. SR12: the workshop-facing
            # ``productivity_multiplicative_factor`` name routes to
            # the same multiplicative branch (deep research note §7.1).
            delta_per_iter = magnitudes - one_w
        else:  # pragma: no cover — guarded by InjectionMethod literal
            raise ValueError(f"unknown injection_method: {method!r}")

        # SR10.A — Mode multiplier. Default behaviour: lookup against
        # the driver's declared Mode (Series=1.0, Hybrid=0.5,
        # Parallel=0.0). ``mode_multiplier_override`` is the AACE 65R-11
        # Mode-independent hook — when set (typically to 1.0), the same
        # value replaces the per-driver lookup uniformly across all
        # risks regardless of declared Mode. Scaling happens before the
        # fire-mask gate so a Mode=Parallel risk produces a zero delta
        # even on fired iterations (multiplier 0.0 × magnitude = 0.0).
        if mode_multiplier_override is None:
            mode_mult = resolve_mode_multiplier(
                driver.mode, mode_multipliers, getattr(driver, "risk_id", None))  # RS-D-3b
        else:
            mode_mult = float(mode_multiplier_override)
        mode_mult_w = dt.type(mode_mult)
        delta_per_iter = (delta_per_iter * mode_mult_w).astype(dt, copy=False)

        # Apply only on iterations where the risk fired.
        delta_per_iter = np.where(fires, delta_per_iter, zero_w).astype(
            dt, copy=False
        )

        if method == "discrete_event_additive_days":
            # SR12 — single-event additive write. The per-iteration
            # magnitude is written to exactly one column (the gating
            # activity), not broadcast across the bound cohort. This is
            # the methodologically correct mechanic for single-event
            # discrete delay risks per AACE 57R-09 / Hulett / CEGN 3A
            # §3.1-§3.3. Pre-flight validation in
            # :func:`src.sra.cpm._pre_flight.assert_injection_method_consistency`
            # checks that ``gating_activity_id`` resolves to a valid
            # XER ``task_code`` before any iteration runs; this branch
            # treats a stale (e.g. graph-renamed) gating id defensively
            # by skipping the write, same posture as the broadcast
            # branch below.
            gating_id = driver.gating_activity_id
            if not gating_id:
                # Construction-time validation in
                # :class:`RiskDriver.__post_init__` should have caught
                # this; defensive skip preserves the no-raise consumer
                # contract.
                continue
            gating_col = id_to_col.get(gating_id)
            if gating_col is None:
                # Stale gating id (e.g. activity renamed between
                # workshop authoring and the current XER). Skip the
                # write rather than raise mid-batch; the pre-flight
                # gate is the assertive validation surface.
                continue
            deltas[:, gating_col] += delta_per_iter
            continue

        # Resolve affected activity column indices, skipping any id not
        # present in the graph's topo_order (defensive — the orchestrator
        # is expected to filter, but the consumer must not raise on a
        # stale audit-trail row referencing a renamed activity).
        affected_cols_list = [
            id_to_col[a_id]
            for a_id in driver.affected_activity_ids
            if a_id in id_to_col
        ]
        if not affected_cols_list:
            continue
        affected_cols = np.asarray(affected_cols_list, dtype=np.int64)

        if method == "additive_pert_days":
            # Legacy additive-broadcast: same per-iteration delta written
            # to every bound activity column. Preserves pre-SR12
            # behaviour for strawman rows whose ``injection_method`` is
            # null/blank (the binding layer translates null → this
            # method from the register's default (RS-D-6)).
            deltas[:, affected_cols] += delta_per_iter[:, None]
        else:
            # multiplicative_pert_factor (legacy) /
            # productivity_multiplicative_factor (SR12 workshop name):
            # per-activity base duration; cast to working precision so
            # the outer product stays in dt.
            base_for_cols = np.asarray(
                [
                    graph.activities[a_id].original_duration_hours
                    for a_id in driver.affected_activity_ids
                    if a_id in id_to_col
                ],
                dtype=dt,
            )
            # Outer product (n_iter, 1) × (1, n_affected) → (n_iter, n_affected).
            deltas[:, affected_cols] += (
                delta_per_iter[:, None] * base_for_cols[None, :]
            ).astype(dt, copy=False)

    return deltas


def apply_to_durations(
    base_durations: np.ndarray,
    deltas: np.ndarray,
    project_start: float = 0.0,
    precision: Precision = "float32",
) -> np.ndarray:
    """Broadcast base durations across iterations and add risk deltas.

    Parameters
    ----------
    base_durations : np.ndarray
        Shape ``(n_act,)``; working hours.
    deltas : np.ndarray
        Shape ``(n_iter, n_act)`` from :func:`sample_risk_deltas`.
    project_start : float
        Held for signature symmetry with the kernel; not consulted in
        this function — the kernel applies the project-start floor on
        ES, not on durations. Retained so downstream callers can
        stamp it through unchanged.
    precision : {"float32", "float64"}
        Output dtype.

    Returns
    -------
    durations : np.ndarray
        Shape ``(n_iter, n_act)``, dtype = ``precision``. Floor-clipped
        at zero — non-physical negative durations (e.g. multiplicative
        factor < 0 producing a delta exceeding the base) are clipped
        with a logged WARNING reporting the count of clipped cells.
    """
    del project_start  # held for signature symmetry; see docstring
    dt = _resolve_dtype(precision)

    if base_durations.ndim != 1:
        raise ValueError(
            f"base_durations must be 1-D (n_act,); got shape {base_durations.shape}"
        )
    if deltas.ndim != 2:
        raise ValueError(
            f"deltas must be 2-D (n_iter, n_act); got shape {deltas.shape}"
        )
    n_act_base = base_durations.shape[0]
    n_iter, n_act_deltas = deltas.shape
    if n_act_base != n_act_deltas:
        raise ValueError(
            f"base_durations.shape[0] ({n_act_base}) does not match "
            f"deltas.shape[1] ({n_act_deltas})"
        )

    # Broadcast (n_act,) → (1, n_act) → (n_iter, n_act). The sum of two
    # ``dt`` arrays is itself ``dt`` (no NEP 50 promotion in either
    # operand), so a final astype is unnecessary; the sum allocates the
    # single (n_iter, n_act) result buffer.
    base_2d = base_durations.astype(dt, copy=False)[None, :]
    deltas_dt = deltas.astype(dt, copy=False)
    durations = base_2d + deltas_dt

    # Floor at zero — non-physical negative durations clipped.
    zero_w = dt.type(0.0)
    neg_mask = durations < zero_w
    n_clipped = int(np.count_nonzero(neg_mask))
    if n_clipped > 0:
        logger.warning(
            "apply_to_durations: clipped %d cells to zero "
            "(non-physical negative duration; %d × %d total cells)",
            n_clipped, n_iter, n_act_deltas,
        )
        np.maximum(durations, zero_w, out=durations)

    return durations


def build_duration_array(
    drivers: dict[str, RiskDriver],
    graph: "ScheduleGraph",
    n_iter: int,
    rng: np.random.Generator,
    severity_uniform: np.ndarray | None = None,
    precision: Precision = "float32",
    *,
    mode_multiplier_override: float | None = None,
    mode_multipliers: Mapping[str, float],
    fires_out: dict[str, np.ndarray] | None = None,
    fire_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Convenience wrapper: :func:`sample_risk_deltas` then
    :func:`apply_to_durations`.

    Returns a duration array of shape ``(n_iter, n_act)`` ready for
    :func:`src.sra.cpm.cpm_kernel.run_batch`.

    ``mode_multiplier_override`` is forwarded to
    :func:`sample_risk_deltas`; see that function for semantics.
    """
    base_durations = np.asarray(
        [
            graph.activities[a_id].original_duration_hours
            for a_id in graph.topo_order
        ],
        dtype=np.float64,
    )
    deltas = sample_risk_deltas(
        drivers,
        graph,
        n_iter=n_iter,
        rng=rng,
        severity_uniform=severity_uniform,
        precision=precision,
        mode_multiplier_override=mode_multiplier_override,
        mode_multipliers=mode_multipliers,
        fires_out=fires_out,
        fire_mask=fire_mask,
    )
    return apply_to_durations(
        base_durations,
        deltas,
        precision=precision,
    )
