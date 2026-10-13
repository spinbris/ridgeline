"""SR14b.1 AC7 — composer dict-shape test.

Asserts ``build_criticality_section`` populates the additive SR14b.1
keys on ``composed["page4b_criticality"]`` so the new Stage 3 standalone
docx appendix section (rendered by
:func:`src.final.word_generator._add_criticality_appendix`) finds the
chart paths, full tables, and captions where it expects them.

Brief §3.1 lists ten new keys (six path/data + four captions). AC7
narrates "the seven new keys" — counting only the six path/data keys
plus the new ``ci_distribution_caption`` constant the brief introduces.
This test pins all ten so the AC7 count gap doesn't hide a missing
caption shadow.

Uses the same synthetic ScheduleMCResult-like SimpleNamespace stub the
SR-S3-Beta-12 composer tests use; no end-to-end run required.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from src.final import commentary_text
from src.final.sections.criticality import build_criticality_section


# ---------------------------------------------------------------------------
# Synthetic fixtures (same shape as test_final_criticality_composer.py).
# ---------------------------------------------------------------------------


def _make_schedule_result_stub() -> SimpleNamespace:
    """Minimal ScheduleMCResult stub with five activities spanning the
    CI bands; gives the composer enough rows that ``near_critical`` is
    non-empty and the bridge can join against the top-3 driver lookup."""
    activity_ids = ("a1", "a2", "a3", "a4", "a5")
    ci_values = {
        "a1": 0.05,
        "a2": 0.25,
        "a3": 0.50,
        "a4": 0.75,
        "a5": 0.95,
    }
    return SimpleNamespace(
        activity_ids=activity_ids,
        criticality_index=ci_values,
        total_float_mean_hours=np.array(
            [200.0, 100.0, 50.0, 20.0, 0.0], dtype=np.float32,
        ),
        total_float_std_hours=np.array(
            [10.0, 8.0, 6.0, 4.0, 1.0], dtype=np.float32,
        ),
        deterministic_critical_path=("a5",),
        n_iter=1000,
        project_finish_days=np.array([100.0, 102.0, 104.0, 106.0, 108.0]),
        mode_independent_criticality_index=None,
    )


def _make_stage3_beta_result_stub() -> dict:
    return {
        "schedule_result": _make_schedule_result_stub(),
        # STAGE3HEADLINE-01 D-5: the delay array is what the path-crossover diagnostic
        # reads; the finish array on schedule_result is not a delay.
        "schedule_days_array": np.array([0.0, 2.0, 4.0, 6.0, 8.0]),
        "cost_dollars_array": np.array([1.0, 1.0, 1.0, 1.0, 1.0]),
        "schedule_graph": None,
        # PRESENT-01 (D-5): the over-bind denominator is the run's own activity count.
        # This stub has no graph, so it states the count directly.
        "activity_count": 120,
        "risk_drivers": {},
        "risk_titles": {},
    }


# ---------------------------------------------------------------------------
# AC7 — new keys present on composed["page4b_criticality"].
# ---------------------------------------------------------------------------


SR14B_1_NEW_KEYS = (
    # Path / data keys (the AC7 "seven" — six data + ci_distribution_caption).
    "chart1_sorted_top30_path",
    "chart3_risk_to_cp_linkage_path",
    "chart4_float_histogram_path",
    "ci_distribution_chart_path",
    "near_critical_table_full",
    "risk_to_activity_bridge_full",
    # Caption keys.
    "chart1_caption",
    "chart3_caption",
    "chart4_caption",
    "ci_distribution_caption",
)


def test_page4b_criticality_carries_new_keys_with_chart_output_dir(
    tmp_path: Path,
) -> None:
    """With ``chart_output_dir`` supplied, all ten SR14b.1 keys appear on
    ``composed["page4b_criticality"]``. Chart-path keys hold rendered PNG
    paths; table-data keys hold record lists; caption keys hold the
    commentary_text constants."""
    out = build_criticality_section(
        integrated_results_by_scenario={
            "DP_Review": {"schedule_days_array": np.array([10.0, 12.0, 14.0])},
        },
        stage3_beta_result=_make_stage3_beta_result_stub(),
        page4_schedule_drivers={"drivers_table": []},
        chart_output_dir=tmp_path,
    )
    p4b = out.get("page4b_criticality") or {}
    assert p4b, "page4b_criticality dict missing from build_criticality_section"
    missing = [k for k in SR14B_1_NEW_KEYS if k not in p4b]
    assert not missing, f"SR14b.1 keys missing on page4b_criticality: {missing}"


def test_page4b_criticality_carries_new_keys_without_chart_output_dir() -> None:
    """Without ``chart_output_dir``, the ten new keys still appear on
    ``composed["page4b_criticality"]`` — the chart-path keys are empty
    strings, the table-data and caption keys carry their content. The
    Stage 3 appendix renderer's existence guard short-circuits when all
    four chart-path keys are empty, so the docx is not contaminated."""
    out = build_criticality_section(
        integrated_results_by_scenario={
            "DP_Review": {"schedule_days_array": np.array([10.0, 12.0, 14.0])},
        },
        stage3_beta_result=_make_stage3_beta_result_stub(),
        page4_schedule_drivers={"drivers_table": []},
        chart_output_dir=None,
    )
    p4b = out.get("page4b_criticality") or {}
    for k in SR14B_1_NEW_KEYS:
        assert k in p4b, f"SR14b.1 key {k!r} missing without chart_output_dir"
    # Chart-path keys are empty strings when chart_output_dir is None.
    for k in (
        "chart1_sorted_top30_path",
        "chart3_risk_to_cp_linkage_path",
        "chart4_float_histogram_path",
        "ci_distribution_chart_path",
    ):
        assert p4b[k] == "", f"{k} should be '' without chart_output_dir; got {p4b[k]!r}"
    # Captions and table records are populated regardless of chart rendering.
    assert isinstance(p4b["near_critical_table_full"], list)
    assert isinstance(p4b["risk_to_activity_bridge_full"], list)
    assert (
        p4b["ci_distribution_caption"]
        == commentary_text.CRITICALITY_CI_DISTRIBUTION_CAPTION_STAGE3
    )


def test_chart_path_keys_resolve_to_real_pngs(tmp_path: Path) -> None:
    """When ``chart_output_dir`` is supplied the four SR14b.1 chart-path
    keys point at actual PNG files on disk; the renderer's
    ``Path(p).exists()`` guard fires and embeds the image."""
    out = build_criticality_section(
        integrated_results_by_scenario={
            "DP_Review": {"schedule_days_array": np.array([10.0, 12.0, 14.0])},
        },
        stage3_beta_result=_make_stage3_beta_result_stub(),
        page4_schedule_drivers={"drivers_table": []},
        chart_output_dir=tmp_path,
    )
    p4b = out["page4b_criticality"]
    for k in (
        "chart1_sorted_top30_path",
        "chart3_risk_to_cp_linkage_path",
        "chart4_float_histogram_path",
        "ci_distribution_chart_path",
    ):
        p = p4b.get(k)
        assert p, f"chart path key {k} is empty"
        assert Path(p).exists(), f"chart at {p} does not exist on disk"


def test_caption_keys_use_commentary_text_constants(tmp_path: Path) -> None:
    """The four caption keys shadow the canonical commentary_text
    constants verbatim. Pinning the source-of-truth references so a
    future commentary_text rename surfaces here as a test failure."""
    out = build_criticality_section(
        integrated_results_by_scenario={
            "DP_Review": {"schedule_days_array": np.array([10.0, 12.0, 14.0])},
        },
        stage3_beta_result=_make_stage3_beta_result_stub(),
        page4_schedule_drivers={"drivers_table": []},
        chart_output_dir=tmp_path,
    )
    p4b = out["page4b_criticality"]
    assert (
        p4b["chart1_caption"]
        == commentary_text.CRITICALITY_CHART_1_PLACEHOLDER_CAPTION
    )
    assert (
        p4b["chart3_caption"]
        == commentary_text.CRITICALITY_CHART_3_PLACEHOLDER_CAPTION
    )
    assert (
        p4b["chart4_caption"]
        == commentary_text.CRITICALITY_CHART_4_PLACEHOLDER_CAPTION
    )
    assert (
        p4b["ci_distribution_caption"]
        == commentary_text.CRITICALITY_CI_DISTRIBUTION_CAPTION_STAGE3
    )


def test_new_caption_constant_has_no_stage25_references() -> None:
    """AC9 audit: zero "Stage 2.5" substrings in the new caption
    constant. The constant is the only commentary_text addition in
    SR14b.1; the rest of the new appendix's rendered text comes from
    pre-existing constants whose AC9 surface was locked under
    SR14b session 2 (the _STAGE3 additive-only pattern)."""
    text = commentary_text.CRITICALITY_CI_DISTRIBUTION_CAPTION_STAGE3
    assert "Stage 2.5" not in text
    assert "stage 2.5" not in text
    assert "stage2.5" not in text


def test_orphan_criticality_note_still_populated(tmp_path: Path) -> None:
    """Brief §3.1: the new keys shadow ``composed["criticality_note"]``
    rather than replace it. SR14c removes the orphan dict; SR14b.1 must
    keep it populated for one release cycle so legacy callers (the
    deprecated ``generate_criticality_note_docx`` function lingering on
    disk through SR14b session 2 → SR14c) keep working."""
    out = build_criticality_section(
        integrated_results_by_scenario={
            "DP_Review": {"schedule_days_array": np.array([10.0, 12.0, 14.0])},
        },
        stage3_beta_result=_make_stage3_beta_result_stub(),
        page4_schedule_drivers={"drivers_table": []},
        chart_output_dir=tmp_path,
    )
    cn = out.get("criticality_note") or {}
    assert cn, "orphan criticality_note dict should still be populated"
    # The orphan dict's source fields match the new shadow keys on
    # page4b_criticality (paths point at the same files).
    p4b = out["page4b_criticality"]
    assert cn["chart1_path"] == p4b["chart1_sorted_top30_path"]
    assert cn["chart3_path"] == p4b["chart3_risk_to_cp_linkage_path"]
    assert cn["chart4_path"] == p4b["chart4_float_histogram_path"]
    assert cn["near_critical_table_10row"] == p4b["near_critical_table_full"]
    assert cn["risk_to_activity_bridge"] == p4b["risk_to_activity_bridge_full"]
