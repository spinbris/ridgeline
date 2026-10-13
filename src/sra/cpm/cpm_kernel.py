"""Vectorised forward + backward CPM kernel (project-agnostic).

Public surface
--------------
* :func:`forward_pass` — compute early-start (ES) and early-finish (EF)
  arrays for a batch of duration samples.
* :func:`backward_pass` — compute late-start (LS) and late-finish (LF)
  arrays.
* :func:`compute_slack` — slack = LS - ES (equivalently LF - EF). In
  CPM terminology this is the per-activity *total float*.
* :func:`run_batch` — convenience wrapper: forward + backward + slack +
  critical-path mask in a single call.
* :func:`accumulate_batch_stats` — streaming aggregator for the
  per-batch ``run_batch`` output: increments per-activity criticality
  counts and total-float sum / sum-of-squares accumulators in place.
  Beta-12 entry point for the activity-level criticality output.
* :data:`CRITICAL_PATH_TOL` — module constant defining the slack
  tolerance (in working hours) below which an activity is considered
  on the critical path.

Algorithm
---------
For each batch of duration samples (shape ``(batch_n, n_act)``), the
kernel walks :attr:`~src.sra.cpm.graph.ScheduleGraph.topo_order` once
forward and once backward. The inner numpy ops vectorise across the
``batch_n`` axis; the outer per-activity Python loop is amortised by the
size of each numpy reduction.

For each activity ``j`` with predecessor link ``l`` (``pred_id == p``)
of type ``link_type`` and ``lag``:

    FS:  implied_start = EF[:, p] + lag
    SS:  implied_start = ES[:, p] + lag
    FF:  implied_start = EF[:, p] + lag - durations[:, j]
    SF:  implied_start = ES[:, p] + lag - durations[:, j]

The forward pass takes the **maximum** over predecessor links and floors
at ``project_start``::

    ES[:, j] = max(project_start, max_l(implied_start_l))
    EF[:, j] = ES[:, j] + durations[:, j]

For each activity ``j`` with successor link ``l`` (``succ_id == s``):

    FS:  implied_finish = LS[:, s] - lag
    SS:  implied_finish = LS[:, s] - lag + durations[:, j]
    FF:  implied_finish = LF[:, s] - lag
    SF:  implied_finish = LF[:, s] - lag + durations[:, j]

The ``durations[:, j]`` term enters the implied_finish on Start-side
links (SS, SF) because the constraint pins the *predecessor's start*
relative to the successor; recovering the *predecessor's finish* must
add back the predecessor's own duration.

The backward pass takes the **minimum** over successor links::

    LF[:, j] = min over successor links of implied_finish (or
                project_finish if no successors)
    LS[:, j] = LF[:, j] - durations[:, j]

Activities with no predecessors anchor at ``ES = project_start``.
Activities with no successors anchor at ``LF = project_finish``.

Critical-path membership is ``slack <= CRITICAL_PATH_TOL`` (1e-3
working hours). The tolerance accounts for float32 rounding accumulated
across the topo iteration.

Precision policy
----------------
Default precision is ``float32`` per
the Stage 3 roadmap, §3.3, and Beta-00 §5.
``float64`` is opt-in via ``precision='float64'`` for diagnostic runs
(notably Validation Gate 1, where bit-exact reproduction of the
hand-worked example would be unfair to ask of float32 with rounding
accumulating across ~2,000 topo iterations).

Precision is set per-call, not as a module-global; both choices are
plumbed through to the dtype of the returned arrays.

Chunked-iteration contract
--------------------------
The kernel **does not loop over batches itself.** That's the
orchestrator's job (Beta-05's ``cpm_simulation.py``). The kernel
operates on **one batch at a time**: the input ``durations`` shape is
``(batch_n, n_act)`` where ``batch_n`` is whatever the caller passes
(typically 10,000, or smaller for the final partial batch).

The kernel **does not retain state across calls**. Per-iteration
ES / EF / LS / LF / slack arrays are returned to the caller and can be
discarded as soon as the orchestrator has streamed off whatever
aggregates it needs (project-finish samples, criticality counts).

Calendar contract
-----------------
For the beta phase the graph carries a single project-default
:class:`~src.sra.cpm.calendar.Calendar`. The kernel treats lag and
duration arithmetic as straight scalar addition in working-hour units
(the calendar already encodes working-hours-per-day, so a duration of
80 working hours = 10 working days at 5×8). **The kernel does not call
calendar methods during the forward/backward pass** — calendar
arithmetic happens at the orchestrator (Beta-05) when converting
working-hour offsets to calendar dates for output rendering.

This keeps the inner loop pure numpy. The ``calendar`` parameter is
plumbed through to enable future per-activity calendar resolution at
SR-S3-Prod without changing the public API.

Memory pattern
--------------
A single :func:`run_batch` call allocates five ``(batch_n, n_act)``
working buffers in the precision dtype (ES, EF, LS, LF, slack), plus
a sixth ``(batch_n, n_act)`` boolean buffer for ``on_critical_path``
(1 byte/element) and a ``(batch_n,)`` ``project_finish`` vector. At
``batch_size=10_000`` and ``n_act≈2,000`` this is
``5 × 10000 × 2000 × 4 bytes + 10000 × 2000 × 1 byte ≈ 0.42 GB``
under float32 (or ``≈0.82 GB`` under float64).

The per-activity ``candidates`` scratch buffer is sized
``(n_preds_or_succs, batch_n)`` and reallocated each iteration. Lag
values are pre-cast to the working dtype before the inner numpy ops
so candidate arithmetic does not promote to float64 (which would
otherwise allocate an undocumented ``(batch_n,)`` float64 intermediate
per FF/SF/SS candidate under ``precision='float32'``).

Resource-loaded scheduling
--------------------------
``RSRC`` and ``TASKRSRC`` tables are out of scope for the beta phase
(Beta-00 §6). Resource-constrained scheduling is deferred to
SR-S3-Prod; the kernel computes purely logic-driven CPM here.

This module is project-agnostic — no project paths, file names, or
project codes appear here. The reusability invariant is locked by the
synthetic-graph tests in :mod:`tests.sra.cpm.test_cpm_kernel` and
:mod:`tests.sra.cpm.test_cpm_kernel_links`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from src.sra.cpm.calendar import Calendar
    from src.sra.cpm.graph import ScheduleGraph


Precision = Literal["float32", "float64"]

#: Slack tolerance (working hours) for critical-path membership.
#: Activities with ``slack <= CRITICAL_PATH_TOL`` are flagged
#: ``on_critical_path = True``. The tolerance accounts for float32
#: rounding accumulating across the topological iteration; float64
#: runs comfortably round-trip well below this bound.
CRITICAL_PATH_TOL: float = 1e-3


# ---------------------------------------------------------------------------
# Internals — predecessor / successor index pre-computation
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


def _build_id_to_idx(graph: "ScheduleGraph") -> dict[str, int]:
    """Map activity id → column index following ``graph.topo_order``.

    The kernel's ``durations`` array is column-indexed in topological
    order; this mapping is the single point of truth for that
    convention.
    """
    return {act_id: i for i, act_id in enumerate(graph.topo_order)}


def _build_predecessor_index(
    graph: "ScheduleGraph", id_to_idx: dict[str, int]
) -> list[list[tuple[int, str, float]]]:
    """Per-activity list of ``(pred_col_idx, link_type, lag_hours)``.

    Indexed by the activity's column index (i.e. its position in
    ``graph.topo_order``).
    """
    pred_index: list[list[tuple[int, str, float]]] = []
    for act_id in graph.topo_order:
        act = graph.activities[act_id]
        entries = [
            (id_to_idx[link.pred_id], link.link_type, float(link.lag_hours))
            for link in act.predecessor_links
        ]
        pred_index.append(entries)
    return pred_index


def _build_successor_index(
    graph: "ScheduleGraph", id_to_idx: dict[str, int]
) -> list[list[tuple[int, str, float]]]:
    """Per-activity list of ``(succ_col_idx, link_type, lag_hours)``.

    Indexed by the predecessor activity's column index. Used by the
    backward pass to walk outbound edges.
    """
    succ_index: list[list[tuple[int, str, float]]] = []
    for act_id in graph.topo_order:
        act = graph.activities[act_id]
        entries = [
            (id_to_idx[link.succ_id], link.link_type, float(link.lag_hours))
            for link in act.successor_links
        ]
        succ_index.append(entries)
    return succ_index


def _validate_durations_shape(
    durations: np.ndarray, graph: "ScheduleGraph"
) -> tuple[int, int]:
    """Sanity-check the ``durations`` shape; return ``(batch_n, n_act)``."""
    if durations.ndim != 2:
        raise ValueError(
            f"durations must be 2-D (batch_n, n_act); got shape {durations.shape}"
        )
    batch_n, n_act = durations.shape
    if n_act != len(graph.topo_order):
        raise ValueError(
            f"durations.shape[1] ({n_act}) does not match len(graph.topo_order) "
            f"({len(graph.topo_order)})"
        )
    return batch_n, n_act


# ---------------------------------------------------------------------------
# Forward pass
# ---------------------------------------------------------------------------

def forward_pass(
    durations: np.ndarray,
    graph: "ScheduleGraph",
    calendar: "Calendar",
    precision: Precision = "float32",
    project_start: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute ES and EF arrays for a batch of duration samples.

    Iterates ``graph.topo_order`` once. For each activity ``j``::

        ES[:, j] = max(project_start, max over predecessor links of implied_start)
        EF[:, j] = ES[:, j] + durations[:, j]

    Implied start by link type (predecessor index ``p``, lag in hours)::

        FS: implied_start = EF[:, p] + lag
        SS: implied_start = ES[:, p] + lag
        FF: implied_start = EF[:, p] + lag - durations[:, j]
        SF: implied_start = ES[:, p] + lag - durations[:, j]

    Activities with no predecessors anchor at ``ES = project_start``.

    Parameters
    ----------
    durations : np.ndarray
        Shape ``(batch_n, n_act)``; units = working hours. Column index
        ``j`` corresponds to ``graph.topo_order[j]``.
    graph : ScheduleGraph
        Topologically-sorted activity graph (Beta-02 output).
    calendar : Calendar
        Project-default calendar. Currently unused inside the inner
        loop (lag and duration are scalar working-hour additions);
        plumbed for future per-activity calendar resolution at
        SR-S3-Prod.
    precision : {"float32", "float64"}
        Output dtype. Default ``float32`` per Beta-00 §5.
    project_start : float
        Working-hour offset that anchors the schedule. Defaults to
        ``0.0``. Floors every ES.

    Returns
    -------
    ES, EF : np.ndarray
        Shape ``(batch_n, n_act)``, dtype = ``precision``. Working-hour
        offsets from ``project_start = 0``.
    """
    del calendar  # plumbed for future per-activity calendar resolution; see docstring
    dt = _resolve_dtype(precision)
    batch_n, n_act = _validate_durations_shape(durations, graph)

    # Coerce the input duration array to the working precision once,
    # rather than allocating cast copies inside the inner loop.
    durations_w = np.asarray(durations, dtype=dt)

    ES = np.zeros((batch_n, n_act), dtype=dt)
    EF = np.zeros((batch_n, n_act), dtype=dt)

    project_start_w = dt.type(project_start)

    id_to_idx = _build_id_to_idx(graph)
    pred_index = _build_predecessor_index(graph, id_to_idx)

    for j in range(n_act):
        preds = pred_index[j]
        if not preds:
            # Root activity: anchor at project_start.
            ES[:, j] = project_start_w
        else:
            # Compute the candidate implied starts for each predecessor
            # link, then reduce max over links.
            #
            # The candidates buffer is sized (n_preds, batch_n) so the
            # subsequent max over axis 0 reduces across links. Per
            # activity this is at most a few KB at standard batch_size
            # (typical max in-degree is single digits); negligible
            # relative to the (batch_n, n_act) main buffers.
            n_preds = len(preds)
            candidates = np.empty((n_preds, batch_n), dtype=dt)
            for k, (pred_idx, link_type, lag) in enumerate(preds):
                # Cast the (Python float) lag to the working dtype so the
                # candidate arithmetic stays in the working precision —
                # otherwise an `array_f32 + python_float` triggers numpy
                # type promotion to float64 and silently allocates an
                # extra (batch_n,) intermediate per FF/SF/SS candidate.
                lag_w = dt.type(lag)
                if link_type == "FS":
                    np.add(EF[:, pred_idx], lag_w, out=candidates[k])
                elif link_type == "SS":
                    np.add(ES[:, pred_idx], lag_w, out=candidates[k])
                elif link_type == "FF":
                    # implied_start = EF[pred] + lag - durations[j]
                    np.add(EF[:, pred_idx], lag_w, out=candidates[k])
                    np.subtract(candidates[k], durations_w[:, j], out=candidates[k])
                elif link_type == "SF":
                    # implied_start = ES[pred] + lag - durations[j]
                    np.add(ES[:, pred_idx], lag_w, out=candidates[k])
                    np.subtract(candidates[k], durations_w[:, j], out=candidates[k])
                else:  # pragma: no cover — guarded upstream by Link.__post_init__
                    raise ValueError(f"unknown link_type {link_type!r}")
            # Reduce max over predecessor links, then floor at project_start.
            np.maximum(candidates.max(axis=0), project_start_w, out=ES[:, j])
        # EF is always start + duration; no special handling for roots.
        np.add(ES[:, j], durations_w[:, j], out=EF[:, j])

    return ES, EF


# ---------------------------------------------------------------------------
# Backward pass
# ---------------------------------------------------------------------------

def backward_pass(
    durations: np.ndarray,
    graph: "ScheduleGraph",
    calendar: "Calendar",
    project_finish: np.ndarray,
    precision: Precision = "float32",
) -> tuple[np.ndarray, np.ndarray]:
    """Compute LS and LF arrays.

    Iterates ``reversed(graph.topo_order)``. For each activity ``j``::

        LF[:, j] = min over successor links of implied_finish
                   (or project_finish if j has no successors)
        LS[:, j] = LF[:, j] - durations[:, j]

    Implied finish by link type (j is the predecessor of a link
    targeting successor index ``s``, lag in hours)::

        FS: implied_finish = LS[:, s] - lag
        SS: implied_finish = LS[:, s] - lag + durations[:, j]
        FF: implied_finish = LF[:, s] - lag
        SF: implied_finish = LF[:, s] - lag + durations[:, j]

    The ``durations[:, j]`` term enters on Start-side links (SS, SF)
    because the constraint pins the *predecessor's start* relative to
    the successor; recovering the predecessor's *finish* must add back
    the predecessor's own duration.

    Parameters
    ----------
    durations : np.ndarray
        Shape ``(batch_n, n_act)``; same column convention as
        :func:`forward_pass`.
    graph : ScheduleGraph
        Topologically-sorted activity graph.
    calendar : Calendar
        Project-default calendar; currently unused inside the inner
        loop (see :func:`forward_pass`).
    project_finish : np.ndarray
        Shape ``(batch_n,)``. Anchor for activities with no successors.
        Typically ``EF.max(axis=1)`` from a prior forward pass; the
        orchestrator may pass a fixed deadline instead for criticality
        analyses.
    precision : {"float32", "float64"}
        Output dtype. Default ``float32``.

    Returns
    -------
    LS, LF : np.ndarray
        Shape ``(batch_n, n_act)``, dtype = ``precision``.
    """
    del calendar  # plumbed for future per-activity calendar resolution
    dt = _resolve_dtype(precision)
    batch_n, n_act = _validate_durations_shape(durations, graph)

    # Single typed cast; np.asarray with explicit dtype handles the shape
    # extraction and any necessary copy in one step.
    project_finish_w = np.asarray(project_finish, dtype=dt)
    if project_finish_w.shape != (batch_n,):
        raise ValueError(
            f"project_finish shape {project_finish_w.shape} does not match "
            f"(batch_n,) = ({batch_n},)"
        )

    durations_w = np.asarray(durations, dtype=dt)

    LS = np.zeros((batch_n, n_act), dtype=dt)
    LF = np.zeros((batch_n, n_act), dtype=dt)

    id_to_idx = _build_id_to_idx(graph)
    succ_index = _build_successor_index(graph, id_to_idx)

    # Walk topo_order in reverse so each activity is visited only after
    # all its successors. Iterate by column index, mirroring forward_pass.
    for j in range(n_act - 1, -1, -1):
        succs = succ_index[j]
        if not succs:
            # Sink activity: anchor LF at the per-iteration project finish.
            LF[:, j] = project_finish_w
        else:
            n_succs = len(succs)
            candidates = np.empty((n_succs, batch_n), dtype=dt)
            for k, (succ_idx, link_type, lag) in enumerate(succs):
                # Cast the (Python float) lag to the working dtype — see
                # the matching forward-pass comment for the rationale.
                lag_w = dt.type(lag)
                if link_type == "FS":
                    np.subtract(LS[:, succ_idx], lag_w, out=candidates[k])
                elif link_type == "SS":
                    # implied_finish = LS[succ] - lag + durations[j]
                    np.subtract(LS[:, succ_idx], lag_w, out=candidates[k])
                    np.add(candidates[k], durations_w[:, j], out=candidates[k])
                elif link_type == "FF":
                    np.subtract(LF[:, succ_idx], lag_w, out=candidates[k])
                elif link_type == "SF":
                    # implied_finish = LF[succ] - lag + durations[j]
                    np.subtract(LF[:, succ_idx], lag_w, out=candidates[k])
                    np.add(candidates[k], durations_w[:, j], out=candidates[k])
                else:  # pragma: no cover — guarded upstream by Link.__post_init__
                    raise ValueError(f"unknown link_type {link_type!r}")
            # Reduce min over successor links.
            candidates.min(axis=0, out=LF[:, j])
        # LS = LF - duration; symmetric to forward's EF = ES + duration.
        np.subtract(LF[:, j], durations_w[:, j], out=LS[:, j])

    return LS, LF


# ---------------------------------------------------------------------------
# Slack and convenience wrapper
# ---------------------------------------------------------------------------

def compute_slack(
    ES: np.ndarray, LS: np.ndarray, EF: np.ndarray, LF: np.ndarray
) -> np.ndarray:
    """Slack = LS - ES (equivalently LF - EF).

    The two definitions are arithmetically identical; we use ``LS - ES``
    because both inputs come from the *start* arrays and the
    subtraction preserves whatever rounding behaviour the upstream
    forward / backward passes carry.

    Parameters
    ----------
    ES, LS, EF, LF : np.ndarray
        Same shape and dtype. ``EF`` and ``LF`` are accepted for
        signature symmetry but not consulted; passing them lets the
        caller name all four corners explicitly.

    Returns
    -------
    slack : np.ndarray
        Same shape and dtype as the inputs. Non-negative for
        well-formed schedules where every constraint is satisfied;
        negative values would indicate a logic error or an externally
        imposed deadline tighter than the network logic permits.
    """
    del EF, LF  # held for signature symmetry; arithmetic uses LS and ES only
    return LS - ES


def run_batch(
    durations: np.ndarray,
    graph: "ScheduleGraph",
    calendar: "Calendar | None" = None,
    precision: Precision = "float32",
    project_start: float = 0.0,
) -> dict[str, np.ndarray]:
    """Forward + backward + slack + critical-path mask in one call.

    Convenience wrapper for callers that want the full per-batch CPM
    state in a single dictionary. The orchestrator (Beta-05) typically
    uses this directly and discards everything except
    ``project_finish`` and ``on_critical_path`` reductions.

    Parameters
    ----------
    durations : np.ndarray
        Shape ``(batch_n, n_act)``; column index ``j`` corresponds to
        ``graph.topo_order[j]``.
    graph : ScheduleGraph
        Topologically-sorted activity graph (Beta-02 output).
    calendar : Calendar | None
        Project-default calendar. If ``None``, falls back to
        ``graph.project_default_calendar``. Currently not consulted in
        the inner loop (see :func:`forward_pass` / :func:`backward_pass`).
    precision : {"float32", "float64"}
        Output dtype. Default ``float32``.
    project_start : float
        Working-hour offset that anchors the schedule. Defaults to
        ``0.0``.

    Returns
    -------
    dict[str, np.ndarray]
        Keys:

        - ``"ES"``, ``"EF"``, ``"LS"``, ``"LF"`` — shape
          ``(batch_n, n_act)``, dtype = ``precision``.
        - ``"slack"`` — shape ``(batch_n, n_act)``; ``LS - ES``.
        - ``"on_critical_path"`` — shape ``(batch_n, n_act)``, dtype
          ``bool``; ``True`` where ``slack <= CRITICAL_PATH_TOL``.
        - ``"project_finish"`` — shape ``(batch_n,)``, dtype =
          ``precision``; per-iteration ``EF.max(axis=1)``.
    """
    if calendar is None:
        calendar = graph.project_default_calendar

    ES, EF = forward_pass(
        durations,
        graph,
        calendar,
        precision=precision,
        project_start=project_start,
    )
    project_finish = EF.max(axis=1)
    LS, LF = backward_pass(
        durations,
        graph,
        calendar,
        project_finish=project_finish,
        precision=precision,
    )
    slack = compute_slack(ES, LS, EF, LF)
    on_critical_path = slack <= CRITICAL_PATH_TOL

    return {
        "ES": ES,
        "EF": EF,
        "LS": LS,
        "LF": LF,
        "slack": slack,
        "on_critical_path": on_critical_path,
        "project_finish": project_finish,
    }


# ---------------------------------------------------------------------------
# Streaming aggregation — Beta-12 activity-level criticality
# ---------------------------------------------------------------------------

def accumulate_batch_stats(
    out: dict[str, np.ndarray],
    *,
    ci_counts: np.ndarray,
    total_float_sum: np.ndarray,
    total_float_sum_sq: np.ndarray,
    finish_sum: np.ndarray | None = None,
    finish_sum_sq: np.ndarray | None = None,
) -> None:
    """Stream per-activity CI / total-float / finish-time aggregates from a batch.

    Increments per-activity accumulators in place from the
    ``(batch_n, n_act)`` arrays produced by :func:`run_batch`. The
    caller (typically the simulation orchestrator) allocates the
    accumulators once at run start and calls this helper after each
    batch; per-iteration matrices are then free to go out of scope.

    Parameters
    ----------
    out : dict[str, np.ndarray]
        :func:`run_batch` return value. Reads ``out["on_critical_path"]``
        (shape ``(batch_n, n_act)``, dtype ``bool``), ``out["slack"]``
        (shape ``(batch_n, n_act)``, dtype = working precision), and
        — when the finish accumulators are passed — ``out["EF"]`` (same
        shape and dtype as ``slack``).
    ci_counts : np.ndarray
        Shape ``(n_act,)``, dtype ``int64``. Per-activity count of
        iterations where the activity was flagged on the critical path.
        Incremented by ``out["on_critical_path"].sum(axis=0)``.
    total_float_sum : np.ndarray
        Shape ``(n_act,)``, dtype ``float64``. Per-activity running sum
        of the total-float (``slack``) values across iterations.
        Incremented by ``out["slack"].sum(axis=0)`` cast to float64.
    total_float_sum_sq : np.ndarray
        Shape ``(n_act,)``, dtype ``float64``. Per-activity running sum
        of squared total-float values. Incremented by
        ``(out["slack"] ** 2).sum(axis=0)`` cast to float64.
    finish_sum : np.ndarray | None
        SR10.D. Shape ``(n_act,)``, dtype ``float64``. Per-activity
        running sum of the early-finish (``EF``) values across
        iterations, in working hours. Incremented by
        ``out["EF"].sum(axis=0)`` cast to float64. ``None`` (default)
        skips the EF block entirely — preserves the pre-SR10.D contract
        for callers that don't need finish-time moments. Must be paired
        with ``finish_sum_sq``: passing exactly one of the two raises
        :class:`ValueError`.
    finish_sum_sq : np.ndarray | None
        SR10.D. Shape ``(n_act,)``, dtype ``float64``. Per-activity
        running sum of squared EF values. Incremented by
        ``(out["EF"] ** 2).sum(axis=0)`` cast to float64. Pairing rules
        as above.

    Notes
    -----
    Streaming statistics (sum + sum-of-squares) are accumulated in
    ``float64`` regardless of the kernel's working precision, because
    the variance computation ``var = E[X²] − (E[X])²`` is vulnerable
    to catastrophic cancellation in float32 when the mean is large
    relative to the standard deviation. Beta-12 §7 Risk 2.

    Per-activity float-distribution and finish-time aggregates are
    intentionally streaming — the per-iteration ``slack`` and ``EF``
    arrays are not retained beyond the batch. Run-level accumulator
    memory is ``n_act × 40 bytes`` post-SR10.D (one int64 + four
    float64) ≈ 80 KB at 2,025 activities; negligible vs the
    per-iteration ``(batch_n, n_act)`` working buffers that the kernel
    allocates inside :func:`run_batch`.

    Per-batch peak inside this helper allocates two transient
    ``(batch_n, n_act)`` float64 arrays per accumulated source — the
    promoted ``slack_f64`` (or ``ef_f64``) and the squared intermediate
    from ``np.square(...)``. At ``batch_size=10_000`` and
    ``n_act≈2,000`` each is ~160 MB, so the transient peak per source
    is ~320 MB on top of the ~420 MB float32 / 20 MB bool already
    held by ``run_batch``. The ``del slack_f64`` after the slack
    increments releases that block of memory before the EF block
    allocates its own transients — bounding overall per-batch peak at
    ~750 MB when SR10.D's finish accumulators are wired.

    The shape contract for every accumulator is asserted: a mismatched
    ``n_act`` raises :class:`ValueError` rather than silently
    broadcasting.
    """
    if (finish_sum is None) ^ (finish_sum_sq is None):
        raise ValueError(
            "finish_sum and finish_sum_sq must be passed together "
            "(or omitted together); got "
            f"finish_sum={'None' if finish_sum is None else 'array'}, "
            f"finish_sum_sq={'None' if finish_sum_sq is None else 'array'}"
        )
    accumulate_finish = finish_sum is not None and finish_sum_sq is not None

    on_cp = out["on_critical_path"]
    slack = out["slack"]
    if on_cp.ndim != 2 or slack.ndim != 2:
        raise ValueError(
            "accumulate_batch_stats expects 2-D on_critical_path and slack "
            f"arrays; got shapes {on_cp.shape} and {slack.shape}"
        )
    _, n_act = on_cp.shape

    validation_targets: list[tuple[str, np.ndarray, type]] = [
        ("ci_counts", ci_counts, np.int64),
        ("total_float_sum", total_float_sum, np.float64),
        ("total_float_sum_sq", total_float_sum_sq, np.float64),
    ]
    if accumulate_finish:
        # mypy/typing: finish_sum and finish_sum_sq are non-None inside this branch
        # by virtue of the XOR guard above.
        validation_targets.append(("finish_sum", finish_sum, np.float64))
        validation_targets.append(("finish_sum_sq", finish_sum_sq, np.float64))

    for name, arr, expected_dtype in validation_targets:
        if arr.shape != (n_act,):
            raise ValueError(
                f"{name} shape {arr.shape} does not match n_act = ({n_act},)"
            )
        if arr.dtype != np.dtype(expected_dtype):
            raise ValueError(
                f"{name} dtype {arr.dtype} does not match expected "
                f"{np.dtype(expected_dtype)}"
            )

    ci_counts += on_cp.sum(axis=0).astype(np.int64, copy=False)
    # Promote to float64 once at the boundary; the sum and the
    # squared-sum both flow through the same temporary cast so the
    # memory cost is bounded by a single (batch_n, n_act) float64
    # intermediate. For 10k×2k batches this is 160 MB peak under
    # float64 inflation — well below the existing per-batch budget.
    slack_f64 = np.asarray(slack, dtype=np.float64)
    total_float_sum += slack_f64.sum(axis=0)
    total_float_sum_sq += np.square(slack_f64).sum(axis=0)
    # SR10.D — explicit release so the EF block's transient float64
    # allocation does not co-exist with slack_f64. Without this, the
    # naive sequential pattern crosses 1 GB per-batch peak; with it,
    # peak stays at ~750 MB. Pure memory hint; no effect on the
    # arithmetic above.
    del slack_f64

    if accumulate_finish:
        # SR10.D — per-activity finish-time moments. EF is already
        # computed by the existing forward pass and is in the run_batch
        # output dict; SR10.D only reads it. Same float64 cast pattern
        # as the slack block above. Memory peak shaped by the `del`
        # immediately preceding this branch.
        ef = out["EF"]
        if ef.ndim != 2:
            raise ValueError(
                f"accumulate_batch_stats expects a 2-D EF array; got shape "
                f"{ef.shape}"
            )
        ef_f64 = np.asarray(ef, dtype=np.float64)
        finish_sum += ef_f64.sum(axis=0)
        finish_sum_sq += np.square(ef_f64).sum(axis=0)
