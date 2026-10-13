"""Audit-trail section builder.

Page 8 of the executive summary. Carries SHA-256 hashes of the input
files (register, strawman, P6), the cross-validation one-liner that
opens §8, and the one-sentence counterfactual narrative that prefaces
the 12-scenario appendix table.

Moved here under SR14a from ``src/final/composer.py`` (private helpers
``_hash_file``, ``_build_counterfactual_narrative``, and the public
``build_cross_validation_sentence``). Composer re-exports each helper
at module level so existing test imports keep working.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd


def _hash_file(path: Path | str) -> str:
    """SHA-256 hash of a file's contents (chunked for large files)."""
    p = Path(path)
    if not p.exists():
        return "(file not found)"
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_cross_validation_sentence(
    cv: dict[str, Any],
    n_iter: int | None = None,
) -> str:
    """Compose a one-line cross-validation gate summary for §8 Audit trail.

    Beta-15 Item 1. Inverts to a FAIL statement when any of the four gates
    fails; the FAIL path also clauses out which gates failed so a reader
    can act on it. Numerical values are pulled from the cv dict keys
    populated by ``src.final.cross_validator.cross_validate_reports``.
    """
    if not isinstance(cv, dict) or not cv:
        return ""

    cost_gap_dollars = float(cv.get("cost_absolute_gap_dollars", 0.0) or 0.0)
    cost_gap_pct = float(cv.get("cost_relative_gap_pct", 0.0) or 0.0)
    sched_gap_days = float(cv.get("schedule_absolute_gap_days", 0.0) or 0.0)
    top3_cost_int = list(cv.get("top_3_cost_contributors_integrated", []) or [])
    top3_sched_int = list(
        cv.get("top_3_schedule_contributors_integrated", []) or []
    )
    iter_count = int(
        n_iter
        if n_iter is not None
        else cv.get("n_iter_used_for_scaling", 0) or 0
    )
    iter_clause = f"{iter_count:,}-iteration " if iter_count else ""

    gaps_clause = (
        # DELIVFIX-01: cost_relative_gap_pct is a FRACTION, so the `%` format type, not a literal
        # `%` (FW-17 / STAGE4-F37 - it printed 0.002% for 0.237%); and whole dollars, not thousands,
        # so a $11,872 gap cannot be read on an $11.32M headline's scale (FW-22).
        f"cost marginal gap ${cost_gap_dollars:,.0f} "
        f"/ {cost_gap_pct:.3%}; "
        f"schedule marginal gap {sched_gap_days:.3f}d"
    )
    top3_cost_text = (
        f" ({', '.join(top3_cost_int)})" if top3_cost_int else ""
    )
    top3_sched_text = (
        f" ({', '.join(top3_sched_int)})" if top3_sched_int else ""
    )

    if cv.get("all_pass"):
        cost_consistent_txt = (
            "consistent" if cv.get("top_3_cost_contributors_consistent") else "INCONSISTENT"
        )
        sched_consistent_txt = (
            "consistent" if cv.get("top_3_schedule_contributors_consistent") else "INCONSISTENT"
        )
        return (
            "Internal cross-validation: all four gates passed at the canonical "
            f"{iter_clause}production run. {gaps_clause}; "
            f"top-3 cost contributors {cost_consistent_txt}{top3_cost_text}; "
            f"top-3 schedule contributors {sched_consistent_txt}{top3_sched_text}."
        )

    failed: list[str] = []
    if not cv.get("cost_passes_calibration"):
        failed.append("cost marginal calibration")
    if not cv.get("schedule_passes_calibration"):
        failed.append("schedule marginal calibration")
    if not cv.get("top_3_cost_contributors_consistent"):
        failed.append("top-3 cost contributors consistency")
    if not cv.get("top_3_schedule_contributors_consistent"):
        failed.append("top-3 schedule contributors consistency")
    failed_clause = (
        f" Failed gate{'s' if len(failed) != 1 else ''}: {', '.join(failed)}."
        if failed
        else ""
    )
    return (
        f"Internal cross-validation FAILED at the canonical {iter_clause}"
        f"production run.{failed_clause} {gaps_clause}; "
        f"top-3 cost contributors{top3_cost_text}; "
        f"top-3 schedule contributors{top3_sched_text}. See FAIL banner; "
        "deliverable is suppressed until gates pass."
    )


def _build_counterfactual_narrative(
    counterfactual_df: pd.DataFrame | None,
    baseline_mode_mix: str,
) -> str | None:
    """B3: one-sentence framing for the 12-scenario counterfactual table.

    Explains why duplicate-of-baseline rows exist. The table itself is
    unchanged; the narrative gives the reader the framing they need
    before reading the rows. Returns ``None`` when no duplicates exist
    or the table is empty / missing.
    """
    if counterfactual_df is None or counterfactual_df.empty:
        return None
    dup_col = counterfactual_df.get(
        "is_duplicate_of_baseline", pd.Series(dtype=bool)
    )
    n_dupe = int(dup_col.sum())
    if n_dupe == 0:
        return None
    return (
        f"Single-risk → Series sensitivities collapse onto the DP Review "
        f"baseline by construction whenever the baseline is already "
        f"all-Series. The current strawman classification is "
        f"{baseline_mode_mix or 'unspecified'}, so {n_dupe} of "
        f"{len(counterfactual_df)} sensitivity scenarios are flagged "
        f"is_duplicate_of_baseline=True for transparency. The non-duplicate "
        f"scenarios (All Hybrid, Dummy Realistic) provide the comparator "
        f"coverage for classification sensitivity."
    )


def build_audit_trail_section(
    appendix_audit_trail: dict[str, Any],
    cross_validation: dict[str, Any],
    register_path: Path | str,
    strawman_path: Path | str,
    p6_path: Path | str | None,
    n_iter: int,
    reproducibility_paragraph: str,
) -> dict[str, Any]:
    """Build the page-8 audit-trail section dict.

    Returns
    -------
    dict[str, Any]
        Page-8 dict with keys:

        * Every key from ``appendix_audit_trail`` (register / strawman
          paths, engine versions, iterations, seed, day rate, P-level).
        * ``reproducibility_paragraph`` (str): pass-through of the
          stage-specific reproducibility prose.
        * ``input_hashes`` (dict[str, str]): SHA-256 hex digests keyed by
          ``register_sha256``, ``strawman_sha256``, and ``p6_sha256``
          when ``p6_path`` was supplied.
        * ``cross_validation_sentence`` (str): the cross-validation
          one-liner from :func:`build_cross_validation_sentence`.

    Notes
    -----
    The reproducibility paragraph is passed in by the composer rather
    than imported here so SR14b's Stage 3 composer can substitute its
    own narrative (Decision D3=A — section builders return data only).
    """
    input_hashes = {
        "register_sha256": _hash_file(register_path),
        "strawman_sha256": _hash_file(strawman_path),
    }
    if p6_path is not None:
        input_hashes["p6_sha256"] = _hash_file(p6_path)

    return {
        **appendix_audit_trail,
        "reproducibility_paragraph": reproducibility_paragraph,
        "input_hashes": input_hashes,
        "cross_validation_sentence": build_cross_validation_sentence(
            cross_validation, n_iter=n_iter,
        ),
    }
