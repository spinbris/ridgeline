"""Beta-19b item 10 — CI explainer expansion unit tests.

Locks the contract:
- format_criticality_explainer accepts an optional binding_counts list
- When supplied, the rendered text appends the
  CI_EXPLAINER_MODE_DIFFERENTIATION paragraph
- The appended paragraph names both Mode-conditioned CI and
  Mode-independent CI plus the AACE 65R-11 reference
- {n_min} and {n_max} populate dynamically from the live binding counts
- Empty / missing binding_counts → legacy paragraph unchanged
"""
from __future__ import annotations

from src.final.executive_summary import format_criticality_explainer


def test_explainer_unchanged_when_binding_counts_absent() -> None:
    """Legacy callers (no binding_counts) get the pre-Beta-19b text."""
    text = format_criticality_explainer(n_iter=100_000)
    # The differentiation paragraph leads with "Mode-conditioned" —
    # without binding_counts the appended block must not appear.
    assert "Mode-conditioned CI" not in text
    assert "AACE 65R-11" not in text


def test_explainer_includes_mode_differentiation_when_counts_supplied() -> None:
    """RefProject run path: binding_counts → expanded explainer with both
    Mode flavours named and the AACE reference cited."""
    counts = [471, 598, 53, 94, 471, 471, 607, 598]
    text = format_criticality_explainer(n_iter=100_000, binding_counts=counts)
    assert "Mode-conditioned CI" in text
    assert "Mode-independent CI" in text
    assert "AACE 65R-11" in text
    # Range from the live counts: min=53, max=607.
    assert "53-607" in text


def test_explainer_handles_single_binding_count() -> None:
    """A list with only one entry → n_min == n_max in the rendered text."""
    text = format_criticality_explainer(n_iter=1000, binding_counts=[42])
    # When min == max the prose still substitutes both placeholders.
    assert "42-42" in text


def test_explainer_handles_zero_counts_gracefully() -> None:
    """All-zero binding_counts → no differentiation paragraph (degenerate
    run path; we don't fabricate a number)."""
    text = format_criticality_explainer(n_iter=1000, binding_counts=[0, 0, 0])
    assert "Mode-conditioned CI" not in text


def test_explainer_low_n_iter_path_still_handles_counts() -> None:
    """Low / zero iteration count + binding_counts: explainer collapses the
    iteration phrase but still appends the differentiation paragraph."""
    text = format_criticality_explainer(n_iter=0, binding_counts=[10, 20, 30])
    # iteration-count collapse path:
    assert "the simulated futures" in text
    # differentiation appended:
    assert "Mode-conditioned CI" in text
    assert "10-30" in text
