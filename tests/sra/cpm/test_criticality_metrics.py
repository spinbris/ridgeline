"""SR10.A — tests for :mod:`src.sra.cpm.criticality_metrics`.

Three tests covering the divergence-table helper that SR10.B's
side-by-side chart consumes:

(f) Divergence calculation — synthetic CI arrays where divergence is
    known per-activity. Assert the computed divergence column matches.
(g) Divergence banding — activities with divergence above / below /
    between the thresholds land in the correct bands.
(h) Sort order — top rows of the output are the largest absolute
    divergences (stable within ties).
"""

from __future__ import annotations

import numpy as np
import pytest

from src.sra.cpm.criticality_metrics import (
    DIVERGENCE_BAND_AMPLIFIED,
    DIVERGENCE_BAND_CONSISTENT,
    DIVERGENCE_BAND_SUPPRESSED,
    compute_criticality_divergence,
)


# ---------------------------------------------------------------------------
# (f) Divergence calculation — known-input arithmetic
# ---------------------------------------------------------------------------

def test_divergence_column_matches_arithmetic() -> None:
    """``divergence = ci_mode_independent - ci_mode_conditioned`` per
    activity. Synthetic dicts with known values verify the column.
    """
    mc = {"a1": 0.10, "a2": 0.50, "a3": 0.80, "a4": 0.20}
    mi = {"a1": 0.40, "a2": 0.55, "a3": 0.30, "a4": 0.20}
    df = compute_criticality_divergence(mc, mi)

    # Index by activity_id for the lookup; arithmetic per row.
    by_id = df.set_index("activity_id")
    assert by_id.loc["a1", "divergence"] == pytest.approx(0.30)   # 0.40 - 0.10
    assert by_id.loc["a2", "divergence"] == pytest.approx(0.05)   # 0.55 - 0.50
    assert by_id.loc["a3", "divergence"] == pytest.approx(-0.50)  # 0.30 - 0.80
    assert by_id.loc["a4", "divergence"] == pytest.approx(0.0)    # 0.20 - 0.20


# ---------------------------------------------------------------------------
# (g) Divergence banding — threshold boundaries
# ---------------------------------------------------------------------------

def test_divergence_banding_uses_correct_band_for_each_regime() -> None:
    """divergence ≥  0.15  → "suppressed by Mode"
       |divergence| < 0.15 → "consistent"
       divergence ≤ -0.15  → "amplified by Mode"

    Boundary policy:
      * suppression threshold (0.15) is inclusive on the upper side
        (≥ counts as suppressed).
      * amplification threshold (-0.15) is inclusive on the lower side
        (≤ counts as amplified).
      * The "consistent" band is the strict-interior ``(-0.15, 0.15)``.
    """
    # Construct CIs so the divergences are exactly the threshold values
    # and slightly inside / outside.
    mc = {
        "supp_above":     0.10,    # divergence  0.50 → suppressed
        "supp_at_bound":  0.10,    # divergence  0.15 → suppressed (inclusive)
        "consistent_pos": 0.10,    # divergence  0.10 → consistent
        "consistent_zero": 0.30,   # divergence  0.00 → consistent
        "consistent_neg": 0.40,    # divergence -0.10 → consistent
        "ampl_at_bound":  0.50,    # divergence -0.15 → amplified (inclusive)
        "ampl_below":     0.70,    # divergence -0.50 → amplified
    }
    mi = {
        "supp_above":     0.60,
        "supp_at_bound":  0.25,
        "consistent_pos": 0.20,
        "consistent_zero": 0.30,
        "consistent_neg": 0.30,
        "ampl_at_bound":  0.35,
        "ampl_below":     0.20,
    }
    df = compute_criticality_divergence(mc, mi)

    bands = df.set_index("activity_id")["divergence_band"]
    assert bands["supp_above"] == DIVERGENCE_BAND_SUPPRESSED
    assert bands["supp_at_bound"] == DIVERGENCE_BAND_SUPPRESSED
    assert bands["consistent_pos"] == DIVERGENCE_BAND_CONSISTENT
    assert bands["consistent_zero"] == DIVERGENCE_BAND_CONSISTENT
    assert bands["consistent_neg"] == DIVERGENCE_BAND_CONSISTENT
    assert bands["ampl_at_bound"] == DIVERGENCE_BAND_AMPLIFIED
    assert bands["ampl_below"] == DIVERGENCE_BAND_AMPLIFIED


def test_custom_thresholds_override_defaults() -> None:
    """Caller-supplied thresholds override the 0.15 defaults."""
    mc = {"x": 0.10, "y": 0.30}
    mi = {"x": 0.35, "y": 0.05}  # divergences 0.25 and -0.25

    # With default 0.15 thresholds, both are out-of-band.
    df_default = compute_criticality_divergence(mc, mi).set_index("activity_id")
    assert df_default.loc["x", "divergence_band"] == DIVERGENCE_BAND_SUPPRESSED
    assert df_default.loc["y", "divergence_band"] == DIVERGENCE_BAND_AMPLIFIED

    # With 0.30 thresholds, both fall into the consistent band.
    df_loose = compute_criticality_divergence(
        mc, mi,
        suppression_threshold=0.30,
        amplification_threshold=0.30,
    ).set_index("activity_id")
    assert df_loose.loc["x", "divergence_band"] == DIVERGENCE_BAND_CONSISTENT
    assert df_loose.loc["y", "divergence_band"] == DIVERGENCE_BAND_CONSISTENT


# ---------------------------------------------------------------------------
# (h) Sort order — top rows are the largest absolute divergences
# ---------------------------------------------------------------------------

def test_output_sorted_by_abs_divergence_descending() -> None:
    """The top of the table is the most-divergent activity — same
    intent as the SR10.B side-by-side chart's row order.
    """
    mc = {
        "tiny":   0.50,
        "big_pos": 0.10,
        "big_neg": 0.85,
        "medium": 0.40,
    }
    mi = {
        "tiny":   0.52,   # |div| = 0.02
        "big_pos": 0.80,  # |div| = 0.70
        "big_neg": 0.15,  # |div| = 0.70
        "medium": 0.10,   # |div| = 0.30
    }
    df = compute_criticality_divergence(mc, mi)

    # Top two rows must be the two |div|=0.70 entries (stable-sort
    # preserves input order within ties); third is medium (|div|=0.30);
    # fourth is tiny.
    assert df.iloc[0]["activity_id"] in ("big_pos", "big_neg")
    assert df.iloc[1]["activity_id"] in ("big_pos", "big_neg")
    assert df.iloc[0]["activity_id"] != df.iloc[1]["activity_id"]
    assert df.iloc[2]["activity_id"] == "medium"
    assert df.iloc[3]["activity_id"] == "tiny"

    # And the abs(divergence) column is monotone non-increasing.
    abs_div = df["divergence"].abs().to_numpy()
    assert np.all(np.diff(abs_div) <= 1e-12)


# ---------------------------------------------------------------------------
# Input validation — defence-in-depth
# ---------------------------------------------------------------------------

def test_ndarray_input_requires_activity_ids() -> None:
    """ndarray CIs without activity_ids raise — there is no way to label
    the rows otherwise.
    """
    mc = np.array([0.1, 0.2, 0.3])
    mi = np.array([0.4, 0.2, 0.1])
    with pytest.raises(ValueError, match="activity_ids"):
        compute_criticality_divergence(mc, mi)


def test_ndarray_shape_mismatch_raises() -> None:
    """ndarray CIs of different lengths raise."""
    mc = np.array([0.1, 0.2, 0.3])
    mi = np.array([0.1, 0.2])
    with pytest.raises(ValueError, match="same shape"):
        compute_criticality_divergence(
            mc, mi, activity_ids=["a1", "a2", "a3"]
        )


def test_negative_threshold_raises() -> None:
    """Threshold arguments must be non-negative."""
    mc = {"a1": 0.1}
    mi = {"a1": 0.5}
    with pytest.raises(ValueError, match="suppression_threshold"):
        compute_criticality_divergence(mc, mi, suppression_threshold=-0.1)
    with pytest.raises(ValueError, match="amplification_threshold"):
        compute_criticality_divergence(mc, mi, amplification_threshold=-0.5)
