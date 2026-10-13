"""
Block-bootstrap confidence intervals for Monte Carlo percentile estimates.

This is a post-hoc analytics layer over the existing simulation output that
produces a 95% Monte-Carlo-error envelope around the point estimate of a
percentile (e.g. P90) at one or more iteration counts. It does not change the
simulation itself.

IMPORTANT: the resulting CI band reflects simulation precision (Monte-Carlo
error) only — it does NOT reflect project-cost uncertainty. Chart captions
and any narrative built on top of these numbers must make that distinction
explicit.

Mining reference: an external Monte Carlo bootstrap implementation, lines
186–218.
"""

from __future__ import annotations

import logging
import warnings
from typing import Iterable

import numpy as np

from src.rng_streams import require_seed

logger = logging.getLogger(__name__)


__all__ = ["bootstrap_percentile_ci", "bootstrap_convergence"]


def _echo(seed: int | None) -> int | None:
    """The seed for the audit trail; ``None`` when the caller's generator carried its own."""
    return None if seed is None else int(seed)


def _scale_n_blocks(k: int, n_blocks_default: int = 100) -> int:
    """Choose ``n_blocks`` for an iteration count ``k`` (SP18a.1).

    Targets a block size of ~100 iterations so that CI width narrows roughly
    as 1/sqrt(k) at high iteration counts rather than plateauing at the
    fixed-``n_blocks`` ceiling that SP18a inherited.

    Schedule:
      - k =   1000 → 50  (block size 20 — floor honoured at small k)
      - k =   5000 → 50  (block size 100)
      - k =  10000 → 100 (block size 100)
      - k =  20000 → 200
      - k =  30000 → 300
      - k = 100000 → 500 (ceiling honoured)

    Floor: 50 blocks (so the bootstrap distribution remains stable at small k).
    Ceiling: 500 blocks (avoid pathological memory / runtime at very high k).

    The default arg ``n_blocks_default`` is preserved for backward-compatibility
    callers but is no longer used inside this helper itself.
    """
    return max(50, min(500, k // 100))


def bootstrap_percentile_ci(
    sample: np.ndarray,
    percentile: float = 90.0,
    n_blocks: int = 100,
    n_resamples: int = 1000,
    rng: np.random.Generator | None = None,
    seed: int | None = None,
) -> dict:
    """Block-bootstrap confidence interval for a single percentile of a 1-D sample.

    Parameters
    ----------
    sample
        Shape ``(n_iter,)`` — e.g. ``raw.outturn`` or ``raw.schedule``.
    percentile
        Percentile of interest, e.g. 90.0 for P90.
    n_blocks
        Number of contiguous blocks the sample is partitioned into. Hard-capped
        at ``n_iter // 10`` to keep at least ten samples per block; a warning is
        logged on downscale (function never raises on small samples).
    n_resamples
        Number of bootstrap resamples drawn.
    rng
        Optional pre-seeded NumPy generator. If ``None``, ``default_rng(seed)``
        is used so re-runs with the same seed give identical CIs.
    seed
        Seed used to construct ``rng`` when ``rng is None``, and then required: there is no
        default (SEEDZERO-01). Echoed back in the returned dict for the audit trail.

    Returns
    -------
    dict with keys ``point``, ``p025``, ``p500``, ``p975``, ``ci95_width``,
    ``n_iter``, ``n_blocks``, ``n_resamples``, ``percentile``, ``seed``.
    """
    arr = np.asarray(sample).ravel()
    n_iter = int(arr.size)

    point = float(np.percentile(arr, percentile))

    if n_iter == 0:
        return {
            "point": point,
            "p025": point,
            "p500": point,
            "p975": point,
            "ci95_width": 0.0,
            "n_iter": 0,
            "n_blocks": 0,
            "n_resamples": int(n_resamples),
            "percentile": float(percentile),
            "seed": _echo(seed),
        }

    cap = max(1, n_iter // 10)
    requested_blocks = int(n_blocks)
    if requested_blocks > cap:
        logger.warning(
            "bootstrap: n_blocks=%d exceeds cap n_iter//10=%d; "
            "downscaling to %d.",
            requested_blocks, cap, cap,
        )
        n_blocks_eff = cap
    else:
        n_blocks_eff = max(1, requested_blocks)

    if rng is None:
        rng = np.random.default_rng(require_seed(seed, where="src.bootstrap.bootstrap_percentile_ci"))

    # Partition contiguous blocks: blocks may differ by at most one element when
    # n_iter is not divisible by n_blocks. np.array_split handles that cleanly.
    blocks = np.array_split(arr, n_blocks_eff)
    block_sizes = np.array([b.size for b in blocks])
    block_starts = np.concatenate(([0], np.cumsum(block_sizes)))

    # Total resampled length matches n_iter when blocks are equal-sized; when
    # they differ by one element the resampled length varies slightly across
    # resamples — that is fine for percentile estimation.
    if int(n_resamples) <= 0:
        boot_pcts = np.array([point])
    else:
        idx_matrix = rng.integers(0, n_blocks_eff, size=(int(n_resamples), n_blocks_eff))
        boot_pcts = np.empty(int(n_resamples), dtype=np.float64)
        for k in range(int(n_resamples)):
            picks = idx_matrix[k]
            # Concatenate the chosen blocks. Equal-block-size case is the common one.
            parts = [arr[block_starts[i]:block_starts[i + 1]] for i in picks]
            resample = np.concatenate(parts)
            boot_pcts[k] = np.percentile(resample, percentile)

    p025 = float(np.percentile(boot_pcts, 2.5))
    p500 = float(np.percentile(boot_pcts, 50.0))
    p975 = float(np.percentile(boot_pcts, 97.5))

    return {
        "point": point,
        "p025": p025,
        "p500": p500,
        "p975": p975,
        "ci95_width": p975 - p025,
        "n_iter": n_iter,
        "n_blocks": int(n_blocks_eff),
        "n_resamples": int(n_resamples),
        "percentile": float(percentile),
        "seed": _echo(seed),
    }


def bootstrap_convergence(
    sample: np.ndarray,
    percentile: float = 90.0,
    iter_grid: Iterable[int] = (1000, 5000, 10000, 20000, 30000),
    n_blocks: int = 100,
    n_resamples: int = 1000,
    rng: np.random.Generator | None = None,
    seed: int | None = None,
) -> dict:
    """Block-bootstrap CI on the percentile at each iteration count in iter_grid.

    For each ``k`` in ``iter_grid``, takes ``sample[:k]`` and runs
    :func:`bootstrap_percentile_ci` on it.

    Block-count scaling (SP18a.1)
    -----------------------------
    ``n_blocks`` scales with iteration count ``k`` via :func:`_scale_n_blocks`:

      * block size held at ~100 iterations (floor of 50 blocks at small k,
        ceiling of 500 blocks at very large k)
      * lets CI width narrow approximately as ``1/sqrt(k)`` at high k rather
        than plateauing at the fixed-``n_blocks`` ceiling SP18a inherited

    The ``n_blocks`` keyword argument is retained as the *default* for direct
    callers of :func:`bootstrap_percentile_ci`, but it does NOT govern the
    per-grid-point block counts inside this function — those come from
    ``_scale_n_blocks(k)``.

    Returns
    -------
    dict with keys:

      * ``iter_grid``    — list of effective grid points (``int``)
      * ``point``        — array of percentile point estimates per grid point
      * ``p025``, ``p500``, ``p975`` — bootstrap quantile arrays
      * ``ci95_width``   — array of ``p975 - p025`` per grid point
      * ``n_blocks``     — array of length ``len(iter_grid)`` giving the
                            actual number of blocks used at each grid point
                            (was a scalar in pre-SP18a.1 contracts)
      * ``percentile``, ``n_resamples``, ``seed`` — scalars, audit trail
    """
    arr = np.asarray(sample).ravel()
    n_iter = int(arr.size)

    grid_in = [int(k) for k in iter_grid]
    grid_eff = [k for k in grid_in if k <= n_iter]
    if not grid_eff:
        # Always include at least the full sample so the chart has one point.
        grid_eff = [n_iter] if n_iter > 0 else [0]
        warnings.warn(
            "bootstrap_convergence: every entry in iter_grid exceeds n_iter; "
            f"falling back to a single point at n_iter={n_iter}.",
            stacklevel=2,
        )

    if rng is None:
        rng = np.random.default_rng(require_seed(seed, where="src.bootstrap.bootstrap_convergence"))

    point = np.empty(len(grid_eff), dtype=np.float64)
    p025 = np.empty(len(grid_eff), dtype=np.float64)
    p500 = np.empty(len(grid_eff), dtype=np.float64)
    p975 = np.empty(len(grid_eff), dtype=np.float64)
    width = np.empty(len(grid_eff), dtype=np.float64)
    blocks_used = np.empty(len(grid_eff), dtype=np.int64)

    for i, k in enumerate(grid_eff):
        sub = arr[:k] if k > 0 else arr
        # SP18a.1: scale n_blocks with iteration count so CI tightens with k
        # rather than plateauing at a fixed cap. The caller's ``n_blocks`` arg
        # is intentionally ignored here — see docstring.
        n_blocks_k = _scale_n_blocks(k) if k > 0 else 1
        out = bootstrap_percentile_ci(
            sub,
            percentile=percentile,
            n_blocks=n_blocks_k,
            n_resamples=n_resamples,
            rng=rng,
            seed=seed,
        )
        point[i] = out["point"]
        p025[i] = out["p025"]
        p500[i] = out["p500"]
        p975[i] = out["p975"]
        width[i] = out["ci95_width"]
        blocks_used[i] = out["n_blocks"]

    return {
        "iter_grid": list(grid_eff),
        "point": point,
        "p025": p025,
        "p500": p500,
        "p975": p975,
        "ci95_width": width,
        "n_blocks": blocks_used,
        "percentile": float(percentile),
        "n_resamples": int(n_resamples),
        "seed": _echo(seed),
    }
