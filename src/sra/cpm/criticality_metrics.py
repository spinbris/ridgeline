"""Mode-conditioned vs Mode-independent criticality comparison helpers.

SR10.A presentation-tier helper. Given the two per-activity
Criticality Index arrays produced by
:func:`src.sra.cpm.cpm_simulation.run_schedule_mc` with
``criticality_measurement_mode="both"``, this module produces a single
:class:`pandas.DataFrame` annotated with the signed divergence and a
verbal band (``"suppressed by Mode"`` / ``"consistent"`` /
``"amplified by Mode"``) suitable for SR10.B's side-by-side chart.

Methodology framing
-------------------
Per AACE 65R-11 §5.4, "true" criticality measurement applies each
risk's impact at multiplier 1.0 regardless of declared Mode. The
project's existing Mode-conditioned CI scales each risk's impact by
``mode_multipliers[risk.mode]`` (Series=1.0, Hybrid=0.5, Parallel=0.0)
— useful for contribution analysis under the chosen Mode tuning, but
not the AACE-correct criticality.

``divergence = ci_mode_independent - ci_mode_conditioned``. A positive
divergence is the AACE measurement detecting criticality the Mode
tuning is *suppressing* (e.g., an activity bound to a Parallel-mode
risk that would extend the project finish if the risk's full impact
were measured). A negative divergence is the rarer case where the
Mode tuning *amplifies* criticality relative to AACE — usually
indicative of Mode classifications that have crept beyond their
methodology basis.

The 0.15 absolute-divergence threshold separating the bands is the
starting value documented in §3.4 of the SR10.A brief, aligned with
the "materially divergent" framing in the deep-research note
(``docs/CriticalPath_NearCritical_Visualisation_DeepResearch.docx``
§2.4). Constants are marked ``_INITIAL_*`` so a reviewer (or a
future calibration sprint) can adjust them in one place.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd


__all__ = [
    "compute_criticality_divergence",
    "DIVERGENCE_BAND_SUPPRESSED",
    "DIVERGENCE_BAND_CONSISTENT",
    "DIVERGENCE_BAND_AMPLIFIED",
]


# ---------------------------------------------------------------------------
# Public banding constants — short labels are what the SR10.B chart
# renders inline. Long-form prose for the report's commentary lives in
# :mod:`src.final.commentary_text` (SR10.B scope; not landed yet).
# ---------------------------------------------------------------------------

#: Band assigned to activities whose AACE Mode-independent CI exceeds
#: their Mode-conditioned CI by ``_INITIAL_SUPPRESSION_THRESHOLD`` or
#: more. These are the activities the Mode tuning is masking from the
#: contribution view.
DIVERGENCE_BAND_SUPPRESSED: Final[str] = "suppressed by Mode"

#: Band for activities where the two measurements agree within
#: ``_INITIAL_CONSISTENCY_TOLERANCE``. The Mode tuning is methodology-
#: faithful for these.
DIVERGENCE_BAND_CONSISTENT: Final[str] = "consistent"

#: Band for activities where the Mode-conditioned CI exceeds the
#: Mode-independent CI by ``_INITIAL_AMPLIFICATION_THRESHOLD`` or more.
#: Typically a small minority — flagged for methodology review during
#: workshop adjudication.
DIVERGENCE_BAND_AMPLIFIED: Final[str] = "amplified by Mode"


# ---------------------------------------------------------------------------
# Initial thresholds (single-source-of-truth for adjustment)
# ---------------------------------------------------------------------------

#: Suppression-band threshold. divergence ≥ this value → "suppressed".
_INITIAL_SUPPRESSION_THRESHOLD: Final[float] = 0.15

#: Amplification-band threshold. divergence ≤ -this value → "amplified".
_INITIAL_AMPLIFICATION_THRESHOLD: Final[float] = 0.15

#: Internal tolerance for the "consistent" band — set equal to the two
#: directional thresholds. Pulled out as a named constant so a future
#: asymmetric tuning (e.g., 0.10 amplification but 0.20 suppression) is
#: a one-line edit.
_INITIAL_CONSISTENCY_TOLERANCE: Final[float] = _INITIAL_SUPPRESSION_THRESHOLD


def compute_criticality_divergence(
    ci_mode_conditioned: dict[str, float] | np.ndarray,
    ci_mode_independent: dict[str, float] | np.ndarray,
    *,
    activity_ids: list[str] | tuple[str, ...] | None = None,
    activity_names: dict[str, str] | None = None,
    suppression_threshold: float = _INITIAL_SUPPRESSION_THRESHOLD,
    amplification_threshold: float = _INITIAL_AMPLIFICATION_THRESHOLD,
) -> pd.DataFrame:
    """Per-activity Mode-conditioned vs Mode-independent CI comparison.

    Accepts the two CI views in either of the two shapes the engine
    natively emits:

    * ``dict[activity_id, float]`` (what
      :class:`~src.sra.cpm.cpm_simulation.ScheduleMCResult` returns) —
      ``activity_ids`` is ignored in this case; the row order is the
      iteration order of the mode_conditioned dict.
    * ``np.ndarray`` of shape ``(n_act,)`` — ``activity_ids`` is then
      required and locks the row order.

    Parameters
    ----------
    ci_mode_conditioned, ci_mode_independent
        The two CI views; same shape and same activity ordering.
    activity_ids
        Required when the CI views are ``np.ndarray``; row labels.
        When the CIs are dicts and ``activity_ids`` is supplied, the
        output is sub-set / re-ordered to match.
    activity_names
        Optional human-readable name lookup. Activities not present
        fall back to the activity_id; emitted in column
        ``activity_name``.
    suppression_threshold, amplification_threshold
        Override the default 0.15 absolute-divergence band cutoffs.
        Reviewer-check #6 documents these as starting values; pass
        explicit floats to override in a calibration sprint.

    Returns
    -------
    pd.DataFrame
        Columns ``activity_id``, ``activity_name``,
        ``ci_mode_conditioned``, ``ci_mode_independent``,
        ``divergence``, ``divergence_band``. Rows sorted by
        ``abs(divergence)`` descending — the top of the table is the
        most divergence-material activity, matching the SR10.B side-by-
        side chart's intent.

    Raises
    ------
    ValueError
        If the two CI views are not the same shape; if an
        ``np.ndarray`` CI is passed without ``activity_ids``; if
        ``suppression_threshold`` or ``amplification_threshold`` is
        negative.
    """
    if suppression_threshold < 0.0:
        raise ValueError(
            "suppression_threshold must be non-negative; got "
            f"{suppression_threshold}"
        )
    if amplification_threshold < 0.0:
        raise ValueError(
            "amplification_threshold must be non-negative; got "
            f"{amplification_threshold}"
        )

    # Normalise both inputs to (activity_ids, mc_array, mi_array). Dict
    # inputs propagate their key order; ndarray inputs require the
    # explicit activity_ids tuple.
    mc_dict = isinstance(ci_mode_conditioned, dict)
    mi_dict = isinstance(ci_mode_independent, dict)

    if mc_dict and mi_dict:
        if activity_ids is None:
            row_ids = list(ci_mode_conditioned.keys())
        else:
            row_ids = list(activity_ids)
        # Same activity set required in both dicts.
        missing_in_mi = [a for a in row_ids if a not in ci_mode_independent]
        if missing_in_mi:
            raise ValueError(
                "ci_mode_independent missing activities present in "
                f"ci_mode_conditioned: {missing_in_mi[:5]}"
                + ("..." if len(missing_in_mi) > 5 else "")
            )
        mc_arr = np.asarray(
            [float(ci_mode_conditioned[a]) for a in row_ids],
            dtype=np.float64,
        )
        mi_arr = np.asarray(
            [float(ci_mode_independent[a]) for a in row_ids],
            dtype=np.float64,
        )
    else:
        if activity_ids is None:
            raise ValueError(
                "activity_ids is required when CI inputs are np.ndarray"
            )
        row_ids = list(activity_ids)
        mc_arr = np.asarray(ci_mode_conditioned, dtype=np.float64)
        mi_arr = np.asarray(ci_mode_independent, dtype=np.float64)
        if mc_arr.shape != mi_arr.shape:
            raise ValueError(
                "ci_mode_conditioned and ci_mode_independent must have "
                f"the same shape; got {mc_arr.shape} vs {mi_arr.shape}"
            )
        if mc_arr.shape != (len(row_ids),):
            raise ValueError(
                f"activity_ids length ({len(row_ids)}) does not match "
                f"CI array shape {mc_arr.shape}"
            )

    divergence = mi_arr - mc_arr

    # Vectorised banding. The two directional thresholds are evaluated
    # independently so an asymmetric tuning would land cleanly; the
    # default is symmetric (0.15 each side).
    band = np.full(divergence.shape, DIVERGENCE_BAND_CONSISTENT, dtype=object)
    band[divergence >= suppression_threshold] = DIVERGENCE_BAND_SUPPRESSED
    band[divergence <= -amplification_threshold] = DIVERGENCE_BAND_AMPLIFIED

    if activity_names is None:
        name_lookup: dict[str, str] = {}
    else:
        name_lookup = activity_names
    names = [name_lookup.get(a, a) for a in row_ids]

    df = pd.DataFrame(
        {
            "activity_id": row_ids,
            "activity_name": names,
            "ci_mode_conditioned": mc_arr,
            "ci_mode_independent": mi_arr,
            "divergence": divergence,
            "divergence_band": band,
        }
    )

    # Sort by |divergence| descending so the top rows are the rows that
    # matter most for the SR10.B side-by-side chart. Stable sort
    # preserves the input row order within ties (relevant when many
    # activities sit at divergence ≈ 0).
    df = df.iloc[
        np.argsort(-np.abs(divergence), kind="stable")
    ].reset_index(drop=True)

    return df
