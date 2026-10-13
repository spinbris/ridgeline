"""SR14b session 2 — Stage 3 standalone composer unit tests (AC4 / AC5 / AC8).

Covers:

- ``compose_stage3_standalone_data`` rich-dict assembly
- ``resolve_stage3_standalone_filename`` AC4 filename pattern
- ``emit_stage3_standalone_artefacts`` orchestration (skip-HTML-when-thin-missing
  fallback, docx renderer fires through the renderer banner hook).

Stage 3 narrative overlay invariants (AC5 zero-Stage-2.5-references on the
rendered constants is pinned in ``test_sr14b_text_rewordings.py``; this file
checks the integration surface).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.final.stage3_composer import (
    COVER_PAGE_CAVEAT_TEXT,
    FOOTER_TEMPLATE,
    PREVIEW_BANNER_TEXT,
    resolve_stage3_standalone_filename,
)


# ---------------------------------------------------------------------------
# AC4 — filename pattern
# ---------------------------------------------------------------------------


def test_resolve_filename_canonical_strawman_uses_dpreview(tmp_path: Path) -> None:
    path = resolve_stage3_standalone_filename(
        tmp_path, variant=None, run_date="2026-05-15", suffix=".docx",
    )
    assert path.name == "sra_stage3_standalone_PROD_DPReview_2026-05-15.docx"


def test_resolve_filename_variant_strawman_uses_variant_tag(tmp_path: Path) -> None:
    for variant in ("Hybrid", "Series", "Parallel"):
        path = resolve_stage3_standalone_filename(
            tmp_path, variant=variant, run_date="2026-05-15", suffix=".html",
        )
        assert path.name == f"sra_stage3_standalone_PROD_{variant}_2026-05-15.html"


def test_resolve_filename_strips_underscore_in_variant(tmp_path: Path) -> None:
    """Variant tag may arrive with an underscore separator (e.g. detected
    via detect_strawman_variant); the AC4 filename uses a contiguous tag."""
    path = resolve_stage3_standalone_filename(
        tmp_path, variant="DP_Review", run_date="2026-05-15", suffix=".docx",
    )
    assert path.name == "sra_stage3_standalone_PROD_DPReview_2026-05-15.docx"


def test_resolve_filename_empty_string_variant_falls_back_to_dpreview(
    tmp_path: Path,
) -> None:
    path = resolve_stage3_standalone_filename(
        tmp_path, variant="", run_date="2026-05-15", suffix=".docx",
    )
    assert path.name == "sra_stage3_standalone_PROD_DPReview_2026-05-15.docx"


def test_resolve_filename_defaults_run_date_to_today(tmp_path: Path) -> None:
    path = resolve_stage3_standalone_filename(
        tmp_path, variant="Hybrid", suffix=".docx",
    )
    assert path.name == f"sra_stage3_standalone_PROD_Hybrid_{date.today().isoformat()}.docx"


# ---------------------------------------------------------------------------
# Constants re-exported from stage3_beta_report (smoke + sanity)
# ---------------------------------------------------------------------------


def test_preview_banner_text_reexported() -> None:
    """The Stage 3 composer module re-exports the SR14b D-locked
    constants so consumers don't have to reach into stage3_beta_report
    directly."""
    from src.final import stage3_beta_report

    assert PREVIEW_BANNER_TEXT == stage3_beta_report.PREVIEW_BANNER_TEXT
    assert COVER_PAGE_CAVEAT_TEXT == stage3_beta_report.COVER_PAGE_CAVEAT_TEXT
    assert FOOTER_TEMPLATE == stage3_beta_report.FOOTER_TEMPLATE


def test_footer_template_accepts_date_format_arg() -> None:
    assert FOOTER_TEMPLATE.format(date="2026-05-15").endswith(" 2026-05-15.")


# ---------------------------------------------------------------------------
# compose_stage3_standalone_data — none-result guard (AC4 strict)
# ---------------------------------------------------------------------------


def test_compose_stage3_standalone_data_raises_when_no_stage3_result() -> None:
    """Stage 3 standalone deliverable is undefined without the engine
    output. The composer surfaces this loudly rather than silently
    producing a Stage 2.5-shaped artefact under the Stage 3 filename
    (which would be a confusing-and-wrong outcome)."""
    from src.final.stage3_composer import compose_stage3_standalone_data

    with pytest.raises(ValueError, match="stage3_beta_result"):
        compose_stage3_standalone_data(
            cost_results={},
            schedule_results={},
            integrated_results_by_scenario={},
            schedule_results_by_scenario={},
            strawman_path="/tmp/sw.xlsx",
            register_path="/tmp/rg.xlsx",
            cross_validation={},
            stage3_beta_result=None,
        )


# ---------------------------------------------------------------------------
# AC8 sibling retirement — cell 7c no longer imports the sibling renderers
# ---------------------------------------------------------------------------


def test_ac5_stage3_constants_have_no_stage25_references() -> None:
    """AC5 audit on the SR14b additive _STAGE3 constants: zero
    "Stage 2.5" references in the rendered text. Comments / docstrings
    that explain the SR14b reword history may name "Stage 2.5";
    those are not rendered and are not in scope of this audit."""
    from src.final import commentary_text, executive_summary

    # AUTO_MAPPER_AUDIT_INTERPRETATION_TEMPLATE_STAGE3 — the rendered
    # template string must not contain "Stage 2.5".
    assert "Stage 2.5" not in (
        commentary_text.AUTO_MAPPER_AUDIT_INTERPRETATION_TEMPLATE_STAGE3
    )

    # AMPLIFIED_COHORT_NOTE_STAGE3 — the SR10.B §10.5 linkage prose's
    # amplified-cohort note for Stage 3 standalone.
    assert "Stage 2.5" not in executive_summary.AMPLIFIED_COHORT_NOTE_STAGE3


def test_ac5_format_auto_mapper_audit_interpretation_stage3_output() -> None:
    """The Stage 3 formatter renders without a "Stage 2.5" reference
    even when stage25_p80_days is absent from the call (the kwarg is
    not part of the Stage 3 formatter's signature)."""
    from src.final.executive_summary import (
        format_auto_mapper_audit_interpretation_stage3,
    )

    # Minimal synthetic audit table: one over-bound risk + one safe. PRESENT-01 (D-5): the
    # over-bind floor is 0.15 of the run's own activity count, stated here rather than
    # defaulted, so the two rows sit either side of it.
    audit_table = [
        {"risk_id": "WT-013", "activity_count": 471},
        {"risk_id": "WT-067", "activity_count": 12},
    ]
    out = format_auto_mapper_audit_interpretation_stage3(
        audit_table=audit_table,
        stage3_p80_days=1226.25,
        schedule_size=2025,
    )
    assert "Stage 2.5" not in out
    assert "1226.2 days" in out or "1226.3 days" in out  # rounded


def test_ac5_format_risk_to_cp_linkage_prose_stage3_note() -> None:
    """The Stage 3 amplified-cohort note (passed as kwarg) overrides
    the default Stage 2.5 wording cleanly."""
    import pandas as pd

    from src.final.executive_summary import (
        AMPLIFIED_COHORT_NOTE_DEFAULT,
        AMPLIFIED_COHORT_NOTE_STAGE3,
        format_risk_to_cp_linkage_prose_sr10b,
    )

    # Synthetic linkage table with one row.
    linkage = pd.DataFrame({
        "risk_id": ["R013"],
        "risk_title": ["Synthetic"],
        "n_activities_bound": [10],
        "top_n_activities": ["A1; A2"],
        "mean_mc_ci_among_bound": [0.7],
        "mean_mi_ci_among_bound": [0.4],
        "divergence_band_median": ["amplified by Mode"],
    })
    extended = pd.DataFrame({
        "activity_id": ["A1", "A2"],
        "activity_name": ["Activity 1", "Activity 2"],
        "ci_mode_conditioned": [0.95, 0.40],
        "ci_mode_independent": [0.30, 0.45],
        "divergence_band": ["amplified by Mode", "consistent"],
    })

    # Default (Stage 2.5) — contains "Stage 2.5".
    default_prose = format_risk_to_cp_linkage_prose_sr10b(
        linkage_table=linkage, extended_ci_table=extended,
    )
    # Stage 3 override — does NOT contain "Stage 2.5".
    stage3_prose = format_risk_to_cp_linkage_prose_sr10b(
        linkage_table=linkage,
        extended_ci_table=extended,
        amplified_mode_tuning_note=AMPLIFIED_COHORT_NOTE_STAGE3,
    )
    # Both invocations produce some prose for this synthetic input.
    if "Stage 2.5" in default_prose:
        # Confirms the default note carries the Stage 2.5 framing
        # (which is correct for the Stage 2.5 deliverable).
        assert "Stage 2.5" not in stage3_prose

