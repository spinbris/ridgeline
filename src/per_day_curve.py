"""
SP18b — Per-day P-curve (cumulative risk-cost distribution by project day).

Two pure functions and a thin convenience wrapper that build a per-day
percentile trajectory from a ``timed_events`` array of shape
``(n_iter, n_risks, 2)``, where the last axis carries
``[occurrence_day, cost_at_that_day]`` per risk per iteration.

**This is NOT a phased S-curve.** A phased S-curve shows when contractual
cash flows occur. The per-day P-curve shows when risk-driven losses
crystallise on the project timeline. Chart captions and any narrative built
on these numbers must keep the distinction explicit.

Reference: an external Monte Carlo implementation, lines 84–103 (per-day
rollup), ``visualization.py::compute_p90`` (lower-bin-edge percentile read-off
— this module uses linear interpolation between bin edges instead, for
smoother charts).
"""

from __future__ import annotations

import logging
from typing import Sequence

import numpy as np

logger = logging.getLogger(__name__)


__all__ = [
    "build_per_day_matrix",
    "per_day_percentiles",
    "compute_per_day_curve",
    "build_timed_events",
]


def build_timed_events(
    cost_matrix: np.ndarray,
    planned_days: Sequence[int],
    *,
    fallback_day: int,
    log_fallback: bool = True,
) -> np.ndarray:
    """Assemble the ``(n_iter, n_risks, 2)`` ``timed_events`` matrix.

    Parameters
    ----------
    cost_matrix : ``(n_iter, n_risks)`` per-iteration realised cost (zero where
        the risk did not fire).
    planned_days : length-``n_risks`` sequence of planned project days
        (1-indexed). Entries equal to 0 are treated as "unspecified" and
        replaced with ``fallback_day`` (typically ``programme_days // 2``).
    fallback_day : integer day to assign to any risk whose planned_day is 0.
    log_fallback : if True (default), log a single-line warning naming the
        risks (by index) that were assigned the fallback day.

    Returns
    -------
    ``(n_iter, n_risks, 2)`` float array; column 0 is occurrence_day (broadcast
    across iterations because under the SP18b contract each risk occurs on the
    same project day every iteration), column 1 is the per-iteration cost.
    """
    cost = np.asarray(cost_matrix, dtype=np.float64)
    n_iter, n_risks = cost.shape

    days = np.asarray(planned_days, dtype=np.int64).copy()
    fallback_idx = np.where(days <= 0)[0]
    if fallback_idx.size > 0:
        days[fallback_idx] = int(fallback_day)
        if log_fallback:
            logger.warning(
                "per_day_curve: %d risk(s) had Planned_Day == 0; assigned "
                "fallback day %d (programme mid-point). Risk indices: %s",
                fallback_idx.size, int(fallback_day), fallback_idx.tolist(),
            )

    timed_events = np.empty((n_iter, n_risks, 2), dtype=np.float64)
    timed_events[:, :, 0] = days  # broadcast across iterations
    timed_events[:, :, 1] = cost
    return timed_events


def build_per_day_matrix(
    timed_events: np.ndarray,
    n_days: int,
    cost_bins: np.ndarray,
) -> np.ndarray:
    """Bin cumulative cost across iterations for each project day.

    Parameters
    ----------
    timed_events : ``(n_iter, n_risks, 2)``. Last axis is
        ``[occurrence_day, cost]``. ``occurrence_day`` is an integer in
        ``[1, n_days]`` (clipped to that range; out-of-range days are treated
        as occurring on the last day so their cost still lands in the matrix).
    n_days : number of project days. The returned matrix has ``n_days + 1``
        rows; row 0 is "before day 1" (always all-zero counts in bin 0 because
        no cost has crystallised yet).
    cost_bins : 1-D array of bin LOWER edges, ascending. Costs are placed
        with ``np.digitize(cumcost, cost_bins) - 1`` so the rightmost open bin
        catches anything above the last edge (then capped to ``n_bins - 1``).

    Returns
    -------
    ``(n_days + 1, len(cost_bins))`` int matrix M where ``M[d, b]`` is the
    count of iterations whose cumulative realised cost up to day ``d`` falls
    into bin ``b``.

    Algorithm
    ---------
    For each iteration, compute the cumulative-cost trajectory across days
    1..n_days by adding the per-risk cost to all days from
    ``occurrence_day`` onwards. Then ``np.digitize`` each row to bin indices
    and ``np.add.at`` accumulate into the matrix. Vectorised over iterations.
    """
    te = np.asarray(timed_events)
    if te.ndim != 3 or te.shape[-1] != 2:
        raise ValueError(
            f"timed_events must have shape (n_iter, n_risks, 2); got {te.shape}"
        )
    n_iter, n_risks, _ = te.shape
    n_days = int(n_days)
    if n_days <= 0:
        raise ValueError(f"n_days must be > 0; got {n_days}")

    bins = np.asarray(cost_bins, dtype=np.float64).ravel()
    n_bins = bins.size
    if n_bins == 0:
        raise ValueError("cost_bins must be non-empty")

    days = np.asarray(te[:, :, 0], dtype=np.int64)
    costs = np.asarray(te[:, :, 1], dtype=np.float64)

    # Clip occurrence days into [1, n_days]. Pre-day-1 occurrences are clamped
    # forward to day 1 so their cost still appears; post-n_days occurrences
    # are clamped to n_days so they appear at the end of the chart.
    days = np.clip(days, 1, n_days)

    # Cumulative cost trajectory per iteration: add each risk's cost to all
    # days from its occurrence day onwards. Vectorised: build a (n_iter,
    # n_days+1) array and for each risk i add cost to columns days[:, i]:end.
    # The naive triple loop is O(n_iter * n_risks * n_days). The vectorised
    # form below uses a per-day-edge accumulator.
    cum = np.zeros((n_iter, n_days + 1), dtype=np.float64)
    # Increment at the occurrence day, decrement at n_days+1 (no-op on last
    # column). Then cumulative-sum across days. This is the classic
    # "difference array" trick.
    diff = np.zeros((n_iter, n_days + 2), dtype=np.float64)
    iter_idx = np.repeat(np.arange(n_iter), n_risks)
    day_idx = days.ravel()
    cost_flat = costs.ravel()
    np.add.at(diff, (iter_idx, day_idx), cost_flat)
    # diff has width (n_days + 2); cumsum gives column 0 zeros, columns 1..n_days
    # the running total. We discard the trailing column.
    cum_full = np.cumsum(diff, axis=1)
    cum[:, :] = cum_full[:, : n_days + 1]

    # Bin each (iter, day) entry to a bin index. np.digitize with right=False
    # gives indices in [0, n_bins], where 0 means "below bins[0]" — but bins
    # starts at 0 so anything ≥ 0 falls in [1, n_bins]; subtract 1 and clip.
    bin_idx = np.digitize(cum, bins, right=False) - 1
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    matrix = np.zeros((n_days + 1, n_bins), dtype=np.int64)
    # Increment matrix[d, bin_idx[i, d]] for every (i, d). Vectorised via
    # np.add.at on a flattened (day, bin) target.
    days_axis = np.tile(np.arange(n_days + 1), n_iter)
    np.add.at(matrix, (days_axis, bin_idx.ravel()), 1)

    return matrix


def per_day_percentiles(
    matrix: np.ndarray,
    cost_bins: np.ndarray,
    percentiles: Sequence[float] = (50.0, 80.0, 90.0),
) -> dict:
    """Read-off percentile cost trajectories from the per-day matrix.

    Uses linear interpolation between bin edges (not the lower-bin-edge
    method) so the resulting curves are visually smooth.

    Parameters
    ----------
    matrix : ``(n_days + 1, n_bins)`` integer count matrix from
        :func:`build_per_day_matrix`.
    cost_bins : 1-D array of bin LOWER edges, ascending.
    percentiles : iterable of percentiles in 0–100. Default ``(50, 80, 90)``.

    Returns
    -------
    dict with:
      * ``day_axis`` — ``np.ndarray`` shape ``(n_days + 1,)`` (0..n_days)
      * for each percentile p, key ``f"p{int(round(p)):03d}"`` carrying a
        ``(n_days + 1,)`` array of cost values

    Notes
    -----
    For day 0 (pre-project) all iterations are in bin 0 by construction, so
    every percentile reads off as ``cost_bins[0]``. We emit that value
    verbatim — typically 0 if ``cost_bins[0] == 0``, which is the standard
    fixture choice.
    """
    M = np.asarray(matrix, dtype=np.float64)
    if M.ndim != 2:
        raise ValueError(f"matrix must be 2-D; got shape {M.shape}")
    n_days_plus_1, n_bins = M.shape

    bins = np.asarray(cost_bins, dtype=np.float64).ravel()
    if bins.size != n_bins:
        raise ValueError(
            f"cost_bins length {bins.size} != matrix.shape[1] {n_bins}"
        )

    # Bin upper edges. For the rightmost open bin, use bins[-1] + (bins[-1] -
    # bins[-2]) as a synthetic upper edge so interpolation has somewhere to go.
    if n_bins >= 2:
        last_edge = bins[-1] + (bins[-1] - bins[-2])
    else:
        last_edge = bins[-1] + 1.0
    upper = np.concatenate([bins[1:], [last_edge]])

    row_totals = M.sum(axis=1)  # (n_days+1,)
    cdf = np.cumsum(M, axis=1)  # (n_days+1, n_bins)

    day_axis = np.arange(n_days_plus_1, dtype=np.int64)
    out: dict = {"day_axis": day_axis}

    for p in percentiles:
        p_frac = float(p) / 100.0
        targets = row_totals * p_frac
        traj = np.empty(n_days_plus_1, dtype=np.float64)
        for d in range(n_days_plus_1):
            total = row_totals[d]
            if total <= 0:
                traj[d] = float(bins[0])
                continue
            # Find first bin where cdf >= target.
            target = targets[d]
            row_cdf = cdf[d]
            b = int(np.searchsorted(row_cdf, target, side="left"))
            b = min(b, n_bins - 1)
            # Linear interpolation within bin [bins[b], upper[b]] using how
            # far the target sits between cdf[d, b-1] and cdf[d, b].
            cdf_lo = float(row_cdf[b - 1]) if b > 0 else 0.0
            cdf_hi = float(row_cdf[b])
            if cdf_hi <= cdf_lo:
                traj[d] = float(bins[b])
            else:
                frac = (target - cdf_lo) / (cdf_hi - cdf_lo)
                frac = max(0.0, min(1.0, frac))
                traj[d] = float(bins[b]) + frac * (float(upper[b]) - float(bins[b]))
        key = f"p{int(round(float(p))):03d}"
        out[key] = traj

    return out


def compute_per_day_curve(
    timed_events: np.ndarray,
    *,
    programme_days: int,
    cost_bin_size: int = 100_000,
    max_cost: int = 200_000_000,
    percentiles: Sequence[float] = (50.0, 80.0, 90.0),
) -> dict:
    """Convenience wrapper: build matrix + read percentiles in one call.

    Returns a dict with ``matrix``, ``day_axis``, ``cost_bins``, ``p050``,
    ``p080``, ``p090`` (or whichever percentiles were requested), plus
    parameter echoes for the audit trail.
    """
    if programme_days <= 0:
        return {
            "enabled": False,
            "reason": (
                f"programme_days={programme_days} (≤ 0) — per-day P-curve "
                "is disabled"
            ),
            "matrix": np.zeros((0, 0), dtype=np.int64),
            "day_axis": np.zeros(0, dtype=np.int64),
            "cost_bins": np.zeros(0, dtype=np.float64),
        }

    cost_bins = np.arange(0, int(max_cost) + int(cost_bin_size), int(cost_bin_size),
                          dtype=np.float64)
    matrix = build_per_day_matrix(timed_events, programme_days, cost_bins)
    pct = per_day_percentiles(matrix, cost_bins, percentiles=percentiles)
    out = {
        "enabled": True,
        "matrix": matrix,
        "cost_bins": cost_bins,
        "programme_days": int(programme_days),
        "cost_bin_size": int(cost_bin_size),
        "max_cost": int(max_cost),
    }
    out.update(pct)
    return out
