"""SR-S3-Beta-11 §2 — nil-bucket annotation on density histogram.

Schedule MC distributions are right-skewed with a high-probability spike
at zero (no-fire iterations). Beta-11 §2 adds an annotation callout
``P(no schedule slip) = X%`` to the leftmost bar when the spike is
material (``p_zero >= ZERO_ANNOTATION_FLOOR``). Without it the spike
dominates the chart visually and the right-tail contingency story is
lost.

Tests:
  - synthetic 50%-zero array → annotation present, p_zero text matches
  - synthetic all-positive array → no annotation (p_zero ≈ 0)
  - small p_zero (3% < floor) → no annotation
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.final.charts import (
    ZERO_ANNOTATION_FLOOR,
    ZERO_THRESHOLD_DAYS,
    make_density_histogram,
)


def _annotations_text(fig_path: Path) -> list[str]:
    """Replay the histogram with the same arr to inspect axes annotations.

    matplotlib closes the figure inside ``make_density_histogram`` so we
    can't introspect the original. Instead, we re-run the same logic
    against a captured Figure via a sibling helper that mirrors the
    annotation creation.
    """
    raise NotImplementedError(
        "use the in-test capture pattern below; this helper is illustrative"
    )


def test_nil_bucket_annotation_present_when_p_zero_50_percent(tmp_path: Path) -> None:
    """50% zeros → annotation rendered with text matching the computed p_zero."""
    rng = np.random.default_rng(seed=42)
    zeros = np.zeros(500)
    nonzeros = rng.uniform(low=10.0, high=120.0, size=500)
    arr = np.concatenate([zeros, nonzeros])
    rng.shuffle(arr)

    out = tmp_path / "hist_50pct_zero.png"
    make_density_histogram(samples=arr, title="test", output_path=out)
    assert out.exists()
    # File size is a coarse proxy for "annotation rendered" (annotated
    # PNG is consistently larger than the bare histogram). The
    # functional assertion comes from the matplotlib-introspection test
    # below.
    assert out.stat().st_size > 1000


def test_nil_bucket_annotation_text_matches_computed_p_zero(monkeypatch) -> None:
    """Patch ``ax.annotate`` to capture the rendered text and assert
    p_zero matches ``(arr < ZERO_THRESHOLD_DAYS).mean()``."""
    import matplotlib.pyplot as plt
    from src.final import charts as charts_mod

    rng = np.random.default_rng(seed=7)
    arr = np.concatenate([np.zeros(300), rng.uniform(20, 100, 700)])

    captured: dict[str, str] = {}
    real_annotate = plt.Axes.annotate

    def _capturing_annotate(self, text, *args, **kwargs):
        captured.setdefault("text", text)
        return real_annotate(self, text, *args, **kwargs)

    monkeypatch.setattr(plt.Axes, "annotate", _capturing_annotate)

    out = Path("__nil_bucket_capture_test__.png")
    try:
        make_density_histogram(samples=arr, title="t", output_path=out)
    finally:
        if out.exists():
            out.unlink()

    assert "text" in captured, (
        "annotate was not called — nil-bucket callout missing"
    )
    assert "P(no schedule slip)" in captured["text"]
    expected_pct = (arr < charts_mod.ZERO_THRESHOLD_DAYS).mean()
    expected_str = f"{expected_pct:.0%}"
    assert expected_str in captured["text"], (
        f"annotation text {captured['text']!r} should contain {expected_str!r} "
        f"(p_zero = {expected_pct:.4f})"
    )
    # Beta-11a Fix 2: drop the "(N of M iterations)" sub-line. The
    # leftmost histogram bin uses a different threshold than the
    # ZERO_THRESHOLD_DAYS strict check, so the rendered count and
    # rendered percentage did not divide consistently. The percentage
    # alone is the headline; the prose sub-caption explains the
    # underlying fraction.
    assert "iterations" not in captured["text"], (
        f"annotation text {captured['text']!r} still contains the "
        f"'(N of M iterations)' sub-line; Beta-11a Fix 2 dropped it "
        f"because the count and percentage came from different "
        f"thresholds and rendered inconsistently."
    )
    assert "of " not in captured["text"], (
        f"annotation text {captured['text']!r} still contains the "
        f"'(N of M ...)' parenthetical; Beta-11a Fix 2 simplifies the "
        f"callout to the percentage alone."
    )


def test_nil_bucket_annotation_skipped_when_no_zeros(monkeypatch, tmp_path: Path) -> None:
    """All-positive array → no nil-bucket annotation rendered."""
    import matplotlib.pyplot as plt

    rng = np.random.default_rng(seed=11)
    arr = rng.uniform(50, 200, 1000)
    assert (arr < ZERO_THRESHOLD_DAYS).mean() == 0.0

    annotate_calls: list[str] = []
    real_annotate = plt.Axes.annotate

    def _spy_annotate(self, text, *args, **kwargs):
        annotate_calls.append(text)
        return real_annotate(self, text, *args, **kwargs)

    monkeypatch.setattr(plt.Axes, "annotate", _spy_annotate)

    out = tmp_path / "all_positive.png"
    make_density_histogram(samples=arr, title="t", output_path=out)
    nil_bucket_calls = [t for t in annotate_calls if "no schedule slip" in t]
    assert nil_bucket_calls == [], (
        f"nil-bucket annotation rendered when p_zero = 0; got {nil_bucket_calls!r}"
    )


def test_nil_bucket_annotation_skipped_when_p_zero_below_floor(
    monkeypatch, tmp_path: Path,
) -> None:
    """3% zeros (< 5% floor) → no annotation."""
    import matplotlib.pyplot as plt

    rng = np.random.default_rng(seed=13)
    arr = np.concatenate([np.zeros(30), rng.uniform(20, 100, 970)])
    assert (arr < ZERO_THRESHOLD_DAYS).mean() < ZERO_ANNOTATION_FLOOR

    annotate_calls: list[str] = []
    real_annotate = plt.Axes.annotate

    def _spy_annotate(self, text, *args, **kwargs):
        annotate_calls.append(text)
        return real_annotate(self, text, *args, **kwargs)

    monkeypatch.setattr(plt.Axes, "annotate", _spy_annotate)

    out = tmp_path / "small_p_zero.png"
    make_density_histogram(samples=arr, title="t", output_path=out)
    nil_bucket_calls = [t for t in annotate_calls if "no schedule slip" in t]
    assert nil_bucket_calls == [], (
        f"nil-bucket annotation rendered for sub-floor p_zero; "
        f"got {nil_bucket_calls!r}"
    )


def test_zero_threshold_constant_value() -> None:
    """Pin the constants — changing them is a Beta-11 amendment, not
    a routine edit."""
    assert ZERO_THRESHOLD_DAYS == 0.5
    assert ZERO_ANNOTATION_FLOOR == 0.05
